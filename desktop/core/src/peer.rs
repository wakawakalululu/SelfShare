//! P2P 节点服务：监听本机端口，向后端其他已认证 peer 提供 blob。
//!
//! 协议与 Python 版 `selfshare/peer.py` 完全一致：
//!
//! ```text
//! GET /p2p/ping                                  -> {"ok":true,...}
//! GET /p2p/blob/<sha256>?peer_id=..&nonce=..     -> 原始字节
//!     Header: X-P2P-MAC = HMAC(token, "vault:peer_id:digest:nonce")
//! ```
//!
//! 手写最小 HTTP/1.1 响应，避免为客户端引入 HTTP 服务端依赖。

use std::collections::BTreeMap;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use sha2::Sha256;

use crate::util::{abs_path, scan_dir};

pub struct PeerServer {
    stop: Arc<AtomicBool>,
    join: Option<JoinHandle<()>>,
    pub listen: String,
    pub peer_id: String,
}

impl PeerServer {
    /// 启动节点服务。`port = 0` 时由系统分配。
    pub fn start(
        folder: PathBuf,
        vault: String,
        token: String,
        peer_id: String,
        port: u16,
    ) -> Result<Self, String> {
        let listener = TcpListener::bind(("0.0.0.0", port))
            .map_err(|e| format!("无法监听 P2P 端口：{}", e))?;
        let actual = listener
            .local_addr()
            .map_err(|e| e.to_string())?
            .port();
        let listen = format!("{}:{}", advertise_host(), actual);

        let stop = Arc::new(AtomicBool::new(false));
        let stop_flag = Arc::clone(&stop);
        let listen_clone = listen.clone();

        let join = std::thread::Builder::new()
            .name("selfshare-peer".into())
            .spawn(move || {
                listener
                    .set_nonblocking(true)
                    .ok();
                while !stop_flag.load(Ordering::SeqCst) {
                    match listener.accept() {
                        Ok((stream, _)) => {
                            let folder = folder.clone();
                            let vault = vault.clone();
                            let token = token.clone();
                            std::thread::spawn(move || {
                                let _ = handle_conn(stream, &folder, &vault, &token);
                            });
                        }
                        Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                            std::thread::sleep(Duration::from_millis(80));
                        }
                        Err(_) => break,
                    }
                }
                let _ = listen_clone;
            })
            .map_err(|e| format!("无法创建节点线程：{}", e))?;

        Ok(PeerServer { stop, join: Some(join), listen, peer_id })
    }

    pub fn stop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(h) = self.join.take() {
            let _ = h.join();
        }
    }
}

impl Drop for PeerServer {
    fn drop(&mut self) {
        self.stop();
    }
}

/// 取本机对外的局域网 IP，供其他主机连接。
fn advertise_host() -> String {
    // 连一个外部地址拿到出口 IP，不会真的发包。
    if let Ok(sock) = std::net::UdpSocket::bind("0.0.0.0:0") {
        if sock.connect("8.8.8.8:80").is_ok() {
            if let Ok(addr) = sock.local_addr() {
                return addr.ip().to_string();
            }
        }
    }
    "127.0.0.1".to_string()
}

fn handle_conn(
    mut stream: TcpStream,
    folder: &Path,
    vault: &str,
    token: &str,
) -> std::io::Result<()> {
    stream.set_read_timeout(Some(Duration::from_secs(15)))?;
    stream.set_write_timeout(Some(Duration::from_secs(120)))?;

    let mut reader = BufReader::new(stream.try_clone()?);
    let mut request_line = String::new();
    if reader.read_line(&mut request_line)? == 0 {
        return Ok(());
    }
    let mut headers: BTreeMap<String, String> = BTreeMap::new();
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line)? == 0 {
            break;
        }
        let trimmed = line.trim_end();
        if trimmed.is_empty() {
            break;
        }
        if let Some((k, v)) = trimmed.split_once(':') {
            headers.insert(k.trim().to_ascii_lowercase(), v.trim().to_string());
        }
    }

    let parts: Vec<&str> = request_line.split_whitespace().collect();
    if parts.len() < 2 || parts[0] != "GET" {
        return write_json(&mut stream, 405, r#"{"error":"method not allowed"}"#);
    }
    let path_and_query = parts[1];
    let (path, query) = match path_and_query.split_once('?') {
        Some((p, q)) => (p, q),
        None => (path_and_query, ""),
    };
    let params = parse_query(query);

    if path == "/p2p/ping" {
        return write_json(&mut stream, 200, r#"{"ok":true}"#);
    }
    if let Some(digest) = path.strip_prefix("/p2p/blob/") {
        let digest = digest.to_ascii_lowercase();
        let peer_id = params.get("peer_id").cloned().unwrap_or_default();
        let nonce = params.get("nonce").cloned().unwrap_or_default();
        let mac = headers.get("x-p2p-mac").cloned().unwrap_or_default();
        let expected = hmac_hex(token, &format!("{}:{}", vault, peer_id), &digest, &nonce);
        if mac.is_empty() || !constant_eq(&mac, &expected) {
            return write_json(&mut stream, 401, r#"{"error":"unauthorised"}"#);
        }
        return match locate_blob(folder, &digest) {
            Some(file) => stream_blob(&mut stream, &file),
            None => write_json(&mut stream, 404, r#"{"error":"blob not found"}"#),
        };
    }
    write_json(&mut stream, 404, r#"{"error":"not found"}"#)
}

/// 在本地同步目录里按内容哈希找文件。
fn locate_blob(folder: &Path, digest: &str) -> Option<PathBuf> {
    let started = Instant::now();
    let files = scan_dir(folder, &[]).ok()?;
    for (rel, _, _) in files {
        if started.elapsed() > Duration::from_secs(30) {
            break;
        }
        let full = abs_path(folder, &rel).ok()?;
        if file_hash_matches(&full, digest) {
            return Some(full);
        }
    }
    None
}

fn file_hash_matches(path: &Path, digest: &str) -> bool {
    crate::util::sha256_file(path)
        .map(|h| h == digest)
        .unwrap_or(false)
}

fn stream_blob(stream: &mut TcpStream, path: &Path) -> std::io::Result<()> {
    let mut file = std::fs::File::open(path)?;
    let size = file.metadata()?.len();
    let head = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        size
    );
    stream.write_all(head.as_bytes())?;
    let mut buf = vec![0u8; 1 << 16];
    loop {
        let n = file.read(&mut buf)?;
        if n == 0 {
            break;
        }
        stream.write_all(&buf[..n])?;
    }
    stream.flush()
}

fn write_json(stream: &mut TcpStream, code: u16, body: &str) -> std::io::Result<()> {
    let reason = match code {
        200 => "OK",
        401 => "Unauthorized",
        404 => "Not Found",
        _ => "Error",
    };
    let head = format!(
        "HTTP/1.1 {} {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        code,
        reason,
        body.len()
    );
    stream.write_all(head.as_bytes())?;
    stream.write_all(body.as_bytes())?;
    stream.flush()
}

fn parse_query(q: &str) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    for pair in q.split('&') {
        if pair.is_empty() {
            continue;
        }
        let (k, v) = match pair.split_once('=') {
            Some((k, v)) => (k, v),
            None => (pair, ""),
        };
        out.insert(k.to_string(), percent_decode(v));
    }
    out
}

fn percent_decode(s: &str) -> String {
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let Ok(b) = u8::from_str_radix(&s[i + 1..i + 3], 16) {
                out.push(b);
                i += 3;
                continue;
            }
        }
        if bytes[i] == b'+' {
            out.push(b' ');
        } else {
            out.push(bytes[i]);
        }
        i += 1;
    }
    String::from_utf8_lossy(&out).to_string()
}

pub fn hmac_hex(token: &str, scope: &str, digest: &str, nonce: &str) -> String {
    // 与 Python `hmac.new(token, msg, sha256)` 一致
    use hmac::{Hmac, Mac};
    type HmacSha256 = Hmac<Sha256>;
    let mut mac = match HmacSha256::new_from_slice(token.as_bytes()) {
        Ok(m) => m,
        Err(_) => return String::new(),
    };
    mac.update(format!("{}:{}:{}", scope, digest, nonce).as_bytes());
    mac.finalize()
        .into_bytes()
        .iter()
        .map(|b| format!("{:02x}", b))
        .collect()
}

fn constant_eq(a: &str, b: &str) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff = 0u8;
    for (x, y) in a.bytes().zip(b.bytes()) {
        diff |= x ^ y;
    }
    diff == 0
}
