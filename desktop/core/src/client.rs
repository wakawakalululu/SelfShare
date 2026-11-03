//! HTTP 传输层：与 Python 版服务端协议一致。

use std::fs;
use std::io::Read;
use std::path::Path;
use std::time::Duration;

use serde::{Deserialize, Serialize};

const UA: &str = "SelfShare-Core/1.0";

#[derive(Debug)]
pub struct RemoteError {
    pub message: String,
    pub status: u16,
}

impl std::fmt::Display for RemoteError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for RemoteError {}

impl From<std::io::Error> for RemoteError {
    fn from(e: std::io::Error) -> Self {
        RemoteError { message: e.to_string(), status: 0 }
    }
}

pub type Result<T> = std::result::Result<T, RemoteError>;

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Entry {
    pub path: String,
    #[serde(default)]
    pub hash: Option<String>,
    #[serde(default)]
    pub size: Option<i64>,
    #[serde(default)]
    pub mtime: Option<f64>,
    #[serde(default)]
    pub rev: i64,
    #[serde(default)]
    pub deleted: bool,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Manifest {
    pub head_rev: i64,
    #[serde(default)]
    pub entries: Vec<Entry>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Op {
    pub op: &'static str,
    pub path: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hash: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub size: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mtime: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub base_hash: Option<String>,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub force: bool,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Applied {
    pub path: String,
    #[serde(default)]
    pub rev: i64,
    #[serde(default)]
    pub action: String,
    #[serde(default)]
    pub hash: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ConflictItem {
    pub path: String,
    #[serde(default)]
    pub reason: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct CommitResult {
    #[serde(default)]
    pub head_rev: i64,
    #[serde(default)]
    pub applied: Vec<Applied>,
    #[serde(default)]
    pub conflicts: Vec<ConflictItem>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct HistoryItem {
    pub path: String,
    #[serde(default)]
    pub hash: Option<String>,
    #[serde(default)]
    pub size: Option<i64>,
    #[serde(default)]
    pub rev: i64,
    #[serde(default)]
    pub time: String,
    #[serde(default)]
    pub origin: String,
    #[serde(default)]
    pub action: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Stats {
    #[serde(default)]
    pub files: i64,
    #[serde(default)]
    pub bytes: i64,
    #[serde(default)]
    pub versions: i64,
    #[serde(default)]
    pub blobs: i64,
    #[serde(default)]
    pub blob_bytes: i64,
    #[serde(default)]
    pub head_rev: i64,
}

pub struct Client {
    base_url: String,
    vault: String,
    token: String,
    agent: ureq::Agent,
}

impl Client {
    pub fn new(base_url: &str, vault: &str, token: &str) -> Self {
        let agent = ureq::AgentBuilder::new()
            .timeout_connect(Duration::from_secs(15))
            .timeout_read(Duration::from_secs(300))
            .timeout_write(Duration::from_secs(300))
            .user_agent(UA)
            .build();
        Client {
            base_url: base_url.trim_end_matches('/').to_string(),
            vault: vault.to_string(),
            token: token.to_string(),
            agent,
        }
    }

    fn url(&self, action: &str, tail: &str) -> String {
        let mut u = format!("{}/api/v/{}/{}", self.base_url, self.vault, action);
        if !tail.is_empty() {
            u.push('/');
            u.push_str(tail.trim_start_matches('/'));
        }
        u
    }

    fn request(&self, method: &str, url: &str) -> ureq::Request {
        self.agent
            .request(method, url)
            .set("Authorization", &format!("Bearer {}", self.token))
    }

    fn to_remote(&self, err: ureq::Error) -> RemoteError {
        match err {
            ureq::Error::Status(code, resp) => {
                let detail = resp.into_string().unwrap_or_default();
                let msg = serde_json::from_str::<serde_json::Value>(&detail)
                    .ok()
                    .and_then(|v| v.get("error").and_then(|e| e.as_str()).map(String::from))
                    .unwrap_or_else(|| detail.chars().take(180).collect());
                RemoteError {
                    message: format!("HTTP {} {}", code, msg),
                    status: code,
                }
            }
            ureq::Error::Transport(t) => RemoteError {
                message: format!("无法连接 {}：{}", self.base_url, t),
                status: 0,
            },
        }
    }

    fn get_json<T: for<'de> Deserialize<'de>>(&self, url: &str) -> Result<T> {
        let resp = self.request("GET", url).call().map_err(|e| self.to_remote(e))?;
        let text = resp
            .into_string()
            .map_err(|e| RemoteError { message: e.to_string(), status: 0 })?;
        serde_json::from_str(&text).map_err(|e| RemoteError {
            message: format!("响应解析失败：{}", e),
            status: 0,
        })
    }

    pub fn stat(&self) -> Result<Stats> {
        self.get_json(&self.url("stat", ""))
    }

    pub fn manifest(&self, since: i64) -> Result<Manifest> {
        self.get_json(&self.url("manifest", &format!("?since={}", since)))
    }

    pub fn commit(&self, ops: &[Op], origin: &str) -> Result<CommitResult> {
        let body = serde_json::json!({ "origin": origin, "ops": ops });
        let resp = self
            .request("POST", &self.url("commit", ""))
            .set("Content-Type", "application/json")
            .send_string(&body.to_string())
            .map_err(|e| self.to_remote(e))?;
        let text = resp
            .into_string()
            .map_err(|e| RemoteError { message: e.to_string(), status: 0 })?;
        serde_json::from_str(&text).map_err(|e| RemoteError {
            message: format!("commit 响应解析失败：{}", e),
            status: 0,
        })
    }

    pub fn history(&self, path: Option<&str>, limit: usize) -> Result<Vec<HistoryItem>> {
        let mut url = self.url("history", &format!("?limit={}", limit));
        if let Some(p) = path {
            url.push_str("&path=");
            url.push_str(&urlencode(p));
        }
        #[derive(Deserialize)]
        struct Wrap {
            #[serde(default)]
            entries: Vec<HistoryItem>,
        }
        let wrap: Wrap = self.get_json(&url)?;
        Ok(wrap.entries)
    }

    pub fn has_blob(&self, digest: &str) -> Result<bool> {
        match self.request("HEAD", &self.url("blob", digest)).call() {
            Ok(_) => Ok(true),
            Err(ureq::Error::Status(404, _)) => Ok(false),
            Err(e) => Err(self.to_remote(e)),
        }
    }

    /// 流式上传，不把整个文件读进内存。
    pub fn put_blob_file(&self, digest: &str, path: &Path) -> Result<()> {
        let meta = fs::metadata(path)?;
        let file = fs::File::open(path)?;
        self.request("PUT", &self.url("blob", digest))
            .set("Content-Type", "application/octet-stream")
            .set("Content-Length", &meta.len().to_string())
            .send(file)
            .map(|_| ())
            .map_err(|e| self.to_remote(e))
    }

    pub fn get_blob_bytes(&self, digest: &str) -> Result<Vec<u8>> {
        let resp = self
            .request("GET", &self.url("blob", digest))
            .call()
            .map_err(|e| self.to_remote(e))?;
        let mut buf = Vec::new();
        resp.into_reader()
            .read_to_end(&mut buf)
            .map_err(|e| RemoteError { message: e.to_string(), status: 0 })?;
        Ok(buf)
    }
}

fn urlencode(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char)
            }
            _ => out.push_str(&format!("%{:02X}", b)),
        }
    }
    out
}

// --------------------------------------------------------------------------- //
// P2P：中心认证 + 节点直连
// --------------------------------------------------------------------------- //
#[derive(Debug, Clone, Deserialize)]
pub struct PeerInfo {
    pub peer_id: String,
    pub listen: String,
    #[serde(default)]
    pub blob_count: i64,
    #[serde(default)]
    pub host_id: String,
}

impl Client {
    /// 用配对码换取 vault 令牌（不需要预先知道库名）。
    pub fn pair(base_url: &str, code: &str) -> Result<(String, String)> {
        let url = format!("{}/api/pair", base_url.trim_end_matches('/'));
        let body = serde_json::json!({ "code": code });
        let resp = ureq::post(&url)
            .set("Content-Type", "application/json")
            .set("User-Agent", UA)
            .timeout(Duration::from_secs(25))
            .send_string(&body.to_string());
        let resp = match resp {
            Ok(r) => r,
            Err(ureq::Error::Status(c, r)) => {
                let detail = r.into_string().unwrap_or_default();
                let msg = serde_json::from_str::<serde_json::Value>(&detail)
                    .ok()
                    .and_then(|v| v.get("error").and_then(|e| e.as_str()).map(String::from))
                    .unwrap_or(detail);
                return Err(RemoteError { message: format!("配对失败：{}", msg), status: c });
            }
            Err(ureq::Error::Transport(t)) => {
                return Err(RemoteError {
                    message: format!("无法连接 {}：{}", base_url, t),
                    status: 0,
                })
            }
        };
        let text = resp
            .into_string()
            .map_err(|e| RemoteError { message: e.to_string(), status: 0 })?;
        let v: serde_json::Value = serde_json::from_str(&text)
            .map_err(|e| RemoteError { message: format!("配对响应解析失败：{}", e), status: 0 })?;
        let vault = v.get("vault").and_then(|x| x.as_str()).unwrap_or_default().to_string();
        let token = v.get("token").and_then(|x| x.as_str()).unwrap_or_default().to_string();
        if vault.is_empty() || token.is_empty() {
            return Err(RemoteError { message: "配对响应缺少字段".into(), status: 0 });
        }
        Ok((vault, token))
    }

    /// 检查地址是否为 SelfShare 服务端。
    pub fn probe(base_url: &str) -> bool {
        let url = format!("{}/api/pair", base_url.trim_end_matches('/'));
        match ureq::get(&url).timeout(Duration::from_secs(8)).call() {
            Ok(r) => r
                .into_string()
                .map(|s| s.contains("selfshare"))
                .unwrap_or(false),
            Err(_) => false,
        }
    }

    /// 向中心服务器注册本节点。
    pub fn peer_register(
        &self,
        peer_id: &str,
        listen: &str,
        blobs: &[String],
        host_id: &str,
    ) -> Result<()> {
        let body = serde_json::json!({
            "peer_id": peer_id,
            "listen": listen,
            "blobs": blobs,
            "host_id": host_id,
            "version": crate::VERSION,
        });
        self.request("POST", &self.url("peer/register", ""))
            .set("Content-Type", "application/json")
            .send_string(&body.to_string())
            .map(|_| ())
            .map_err(|e| self.to_remote(e))
    }

    /// 心跳，维持节点在线状态。
    pub fn peer_heartbeat(&self, peer_id: &str, blob_count: i64) -> Result<()> {
        let body = serde_json::json!({ "peer_id": peer_id, "blob_count": blob_count });
        self.request("POST", &self.url("peer/heartbeat", ""))
            .set("Content-Type", "application/json")
            .send_string(&body.to_string())
            .map(|_| ())
            .map_err(|e| self.to_remote(e))
    }

    /// 从中心服务器获取在线节点列表。
    pub fn peers(&self, exclude_peer_id: Option<&str>) -> Result<Vec<PeerInfo>> {
        let mut url = self.url("peers", "");
        if let Some(p) = exclude_peer_id {
            url.push_str(&format!("?exclude={}", urlencode(p)));
        }
        #[derive(Deserialize)]
        struct Wrap {
            #[serde(default)]
            peers: Vec<PeerInfo>,
        }
        let wrap: Wrap = self.get_json(&url)?;
        Ok(wrap.peers)
    }

    /// 直接从一个 peer 拉取 blob，用 HMAC 认证（token 不上网）。
    pub fn get_blob_p2p(
        &self,
        digest: &str,
        peer_listen: &str,
        peer_id: &str,
    ) -> Result<Vec<u8>> {
        let nonce = random_nonce();
        let mac = p2p_hmac(&self.token, &format!("{}:{}", self.vault, peer_id), digest, &nonce);
        let url = format!(
            "http://{}/p2p/blob/{}?peer_id={}&nonce={}",
            peer_listen, digest, urlencode(peer_id), nonce
        );
        let resp = self
            .agent
            .get(&url)
            .set("X-P2P-MAC", &mac)
            .set("User-Agent", UA)
            .timeout(Duration::from_secs(120))
            .call()
            .map_err(|e| self.to_remote(e))?;
        let mut buf = Vec::new();
        resp.into_reader()
            .read_to_end(&mut buf)
            .map_err(|e| RemoteError { message: e.to_string(), status: 0 })?;
        Ok(buf)
    }

    /// 优先走 peer，全部失败后回退中心服务器。返回实际来源。
    pub fn get_blob_with_peers(
        &self,
        digest: &str,
        exclude_peer_id: Option<&str>,
    ) -> Result<(Vec<u8>, String)> {
        // 逐个 peer 尝试。不按 blob_count 预筛：节点可能按需扫描目录提供数据，
        // 计数为 0 并不代表它没有该 blob。
        if let Ok(peers) = self.peers(exclude_peer_id) {
            for p in peers {
                if let Ok(data) = self.get_blob_p2p(digest, &p.listen, &p.peer_id) {
                    return Ok((data, format!("peer:{}", p.listen)));
                }
            }
        }
        let data = self.get_blob_bytes(digest)?;
        Ok((data, "server".to_string()))
    }
}

/// HMAC-SHA256(token, "peer_id:digest:nonce")，与 Python 端保持一致。
fn p2p_hmac(token: &str, peer_scope: &str, digest: &str, nonce: &str) -> String {
    use hmac::{Hmac, Mac};
    use sha2::Sha256;
    type HmacSha256 = Hmac<Sha256>;
    let mut mac = match HmacSha256::new_from_slice(token.as_bytes()) {
        Ok(m) => m,
        Err(_) => return String::new(),
    };
    mac.update(format!("{}:{}:{}", peer_scope, digest, nonce).as_bytes());
    mac.finalize().into_bytes().iter().map(|b| format!("{:02x}", b)).collect()
}

fn random_nonce() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let mixed = nanos ^ ((std::process::id() as u128) << 64);
    format!("{:032x}", mixed)
}
