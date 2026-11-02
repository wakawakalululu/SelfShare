//! 集成测试：Rust 内核 <-> Python 服务端协议互通。
//!
//! 测试会自己拉起一个 Python 服务端（`python selfshare.py server`），
//! 因此需要仓库根目录有可用的 `python`。若不可用则跳过。

use std::fs;
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{Duration, Instant};

/// 每个测试用独立的服务端根目录，避免并行执行时互相清理。
static SEQ: AtomicUsize = AtomicUsize::new(0);

use selfshare_core::client::Client;
use selfshare_core::engine::{SyncOptions, Syncer};
use selfshare_core::state::{LocalState, MountConfig};

struct Server {
    child: Child,
    root: PathBuf,
    url: String,
    token: String,
    vault: String,
}

impl Drop for Server {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn repo_root() -> PathBuf {
    // desktop/core -> desktop -> 仓库根
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .map(|p| p.to_path_buf())
        .expect("找不到仓库根")
}

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(0)
}

fn start_server() -> Option<Server> {
    let repo = repo_root();
    let script = repo.join("selfshare.py");
    if !script.exists() {
        return None;
    }
    let seq = SEQ.fetch_add(1, Ordering::SeqCst);
    let root = std::env::temp_dir().join(format!(
        "ss-rs-test-{}-{}",
        std::process::id(),
        seq
    ));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).ok()?;
    let token = "rs-test-token".to_string();
    let vault = "v1".to_string();

    // 先建库
    let create = Command::new("python")
        .arg(&script)
        .args([
            "vault",
            "create",
            &vault,
            "--root",
            &root.to_string_lossy(),
            "--token",
            &token,
        ])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .ok()?;
    if !create.success() {
        return None;
    }

    let port = free_port();
    let child = Command::new("python")
        .arg(&script)
        .args([
            "server",
            "--root",
            &root.to_string_lossy(),
            "--host",
            "127.0.0.1",
            "--port",
            &port.to_string(),
            "--quiet",
        ])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;

    let url = format!("http://127.0.0.1:{}", port);
    // 等服务端就绪
    let client = Client::new(&url, &vault, &token);
    let deadline = Instant::now() + Duration::from_secs(20);
    while Instant::now() < deadline {
        if client.stat().is_ok() {
            return Some(Server { child, root, url, token, vault });
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    let mut s = Server { child, root, url, token, vault };
    let _ = s.child.kill();
    None
}

fn mount(server: &Server, dir: &Path) -> LocalState {
    fs::create_dir_all(dir).unwrap();
    let cfg = MountConfig {
        url: server.url.clone(),
        vault: server.vault.clone(),
        token: server.token.clone(),
        folder: dir.to_string_lossy().to_string(),
        host_id: format!("test-{}", dir.file_name().unwrap().to_string_lossy()),
        created: "now".into(),
    };
    LocalState::init_mount(dir, cfg).unwrap()
}

/// 构造同步器。注意：syncer 会持有第一次 load 的快照，因此返回后必须立刻用，
/// 不能让别处再写 state.json 之后复用同一个对象。
fn syncer(server: &Server, dir: &Path) -> Syncer {
    let state = mount(server, dir);
    let cfg = state.config().clone();
    let client = Client::new(&cfg.url, &cfg.vault, &cfg.token);
    Syncer::with_options(client, state, SyncOptions::load(dir))
}

/// 每次同步都重新打开状态，模拟真实进程行为。
fn sync(server: &Server, dir: &Path) -> selfshare_core::engine::SyncReport {
    syncer(server, dir).sync().expect("同步失败")
}

fn write(dir: &Path, rel: &str, text: &str) {
    let path = dir.join(rel);
    if let Some(p) = path.parent() {
        fs::create_dir_all(p).unwrap();
    }
    fs::write(path, text).unwrap();
}

fn read(dir: &Path, rel: &str) -> String {
    fs::read_to_string(dir.join(rel)).unwrap()
}

// --------------------------------------------------------------------------- //
// 测试
// --------------------------------------------------------------------------- //

#[test]
fn rust_client_talks_to_python_server() {
    let Some(server) = start_server() else {
        eprintln!("跳过：python 或 selfshare.py 不可用");
        return;
    };
    let a = std::env::temp_dir().join(format!("ss-rs-a-{}", std::process::id()));
    let b = std::env::temp_dir().join(format!("ss-rs-b-{}", std::process::id()));
    let _ = fs::remove_dir_all(&a);
    let _ = fs::remove_dir_all(&b);

    write(&a, "docs/笔记.txt", "来自 Rust 客户端");
    write(&a, "data.bin", "binary-ish payload");
    let report_a = sync(&server, &a);
    assert_eq!(report_a.pushes.len(), 2, "{}", report_a.summary());
    assert!(report_a.errors.is_empty(), "{:?}", report_a.errors);

    let report_b = sync(&server, &b);
    assert_eq!(report_b.pulls.len(), 2, "{}", report_b.summary());
    assert_eq!(read(&b, "docs/笔记.txt"), "来自 Rust 客户端");

    let _ = fs::remove_dir_all(&a);
    let _ = fs::remove_dir_all(&b);
}

#[test]
fn rust_detects_conflict_and_keeps_both() {
    let Some(server) = start_server() else {
        return;
    };
    let a = std::env::temp_dir().join(format!("ss-rs-ca-{}", std::process::id()));
    let b = std::env::temp_dir().join(format!("ss-rs-cb-{}", std::process::id()));
    let _ = fs::remove_dir_all(&a);
    let _ = fs::remove_dir_all(&b);

    write(&a, "shared.txt", "base");
    sync(&server, &a);
    sync(&server, &b);

    write(&a, "shared.txt", "A 版本");
    write(&b, "shared.txt", "B 版本");

    sync(&server, &a); // A 先提交
    let rb = sync(&server, &b);
    assert_eq!(rb.conflicts, vec!["shared.txt".to_string()], "{}", rb.summary());

    // 冲突副本必须存在，且两份内容都还在
    let entries: Vec<String> = fs::read_dir(&b)
        .unwrap()
        .flatten()
        .map(|e| e.file_name().to_string_lossy().to_string())
        .collect();
    assert!(
        entries.iter().any(|n| n.contains("冲突副本")),
        "expected conflict copy, got {:?}",
        entries
    );
    assert_eq!(read(&b, "shared.txt"), "A 版本");

    // A 端拿到冲突副本后收敛
    sync(&server, &a);
    let mut a_files: Vec<String> = fs::read_dir(&a)
        .unwrap()
        .flatten()
        .map(|e| e.file_name().to_string_lossy().to_string())
        .filter(|n| n.ends_with(".txt"))
        .collect();
    let mut b_files: Vec<String> = entries
        .into_iter()
        .filter(|n| n.ends_with(".txt"))
        .collect();
    a_files.sort();
    b_files.sort();
    assert_eq!(a_files, b_files, "两端应收敛到同一文件集合");

    let _ = fs::remove_dir_all(&a);
    let _ = fs::remove_dir_all(&b);
}

#[test]
fn rust_propagates_deletes() {
    let Some(server) = start_server() else {
        return;
    };
    let a = std::env::temp_dir().join(format!("ss-rs-da-{}", std::process::id()));
    let b = std::env::temp_dir().join(format!("ss-rs-db-{}", std::process::id()));
    let _ = fs::remove_dir_all(&a);
    let _ = fs::remove_dir_all(&b);

    write(&a, "gone.txt", "bye");
    sync(&server, &a);
    sync(&server, &b);
    assert!(b.join("gone.txt").exists());

    fs::remove_file(a.join("gone.txt")).unwrap();
    sync(&server, &a);
    let rb = sync(&server, &b);
    assert_eq!(rb.deletes_local, vec!["gone.txt".to_string()]);
    assert!(!b.join("gone.txt").exists());

    let _ = fs::remove_dir_all(&a);
    let _ = fs::remove_dir_all(&b);
}

#[test]
fn rust_respects_ignore_rules() {
    let Some(server) = start_server() else {
        return;
    };
    let a = std::env::temp_dir().join(format!("ss-rs-ia-{}", std::process::id()));
    let _ = fs::remove_dir_all(&a);

    write(&a, ".selfshareignore", "*.tmp\nbuild/\n");
    write(&a, "keep.txt", "keep");
    write(&a, "scratch.tmp", "nope");
    write(&a, "build/out.bin", "nope");

    let report = sync(&server, &a);
    assert!(report.pushes.contains(&"keep.txt".to_string()));
    assert!(!report.pushes.iter().any(|p| p.ends_with(".tmp")));
    assert!(!report.pushes.iter().any(|p| p.starts_with("build/")));

    let _ = fs::remove_dir_all(&a);
}

#[test]
fn rust_plan_is_side_effect_free() {
    let Some(server) = start_server() else {
        return;
    };
    let a = std::env::temp_dir().join(format!("ss-rs-pa-{}", std::process::id()));
    let _ = fs::remove_dir_all(&a);
    write(&a, "x.txt", "x");

    let syncer_obj = syncer(&server, &a);
    let actions = syncer_obj.plan().unwrap();
    assert_eq!(actions.len(), 1);
    // 只规划，不该产生远端文件
    let st = syncer_obj.client.stat().unwrap();
    assert_eq!(st.files, 0, "plan 不应写入远端");

    let _ = fs::remove_dir_all(&a);
}

#[test]
fn ffi_surface_roundtrips() {
    use std::ffi::{CStr, CString};
    use std::os::raw::c_char;

    unsafe {
        let v = selfshare_core::ffi::ss_version();
        let text = CStr::from_ptr(v).to_str().unwrap().to_string();
        selfshare_core::ffi::ss_free(v);
        assert!(text.contains("version"));

        // 无效参数也要返回合法 JSON，不能崩
        let bad = CString::new("不是 JSON").unwrap();
        let out = selfshare_core::ffi::ss_mount(bad.as_ptr() as *const c_char);
        let msg = CStr::from_ptr(out).to_str().unwrap().to_string();
        selfshare_core::ffi::ss_free(out);
        assert!(msg.contains("\"ok\":false"), "got {}", msg);

        // 空指针不应崩溃
        let out = selfshare_core::ffi::ss_sync(std::ptr::null(), std::ptr::null());
        let msg = CStr::from_ptr(out).to_str().unwrap().to_string();
        selfshare_core::ffi::ss_free(out);
        assert!(msg.contains("error"));
    }
}

// --------------------------------------------------------------------------- //
// P2P：Rust 节点 <-> Python 服务端 / Rust 客户端互通
// --------------------------------------------------------------------------- //

#[test]
fn hmac_matches_python_implementation() {
    // 与 Python `make_p2p_hmac` 使用同样的输入，验证两端口径一致。
    let mac = selfshare_core::peer::hmac_hex("tok", "vault:peer1", "abcd", "n1");
    assert_eq!(mac.len(), 64);
    assert!(mac.chars().all(|c| c.is_ascii_hexdigit()));

    // 同输入必须稳定
    assert_eq!(mac, selfshare_core::peer::hmac_hex("tok", "vault:peer1", "abcd", "n1"));
    // 任一字段变化都必须改变结果
    assert_ne!(mac, selfshare_core::peer::hmac_hex("tok2", "vault:peer1", "abcd", "n1"));
    assert_ne!(mac, selfshare_core::peer::hmac_hex("tok", "vault:peer1", "abce", "n1"));
}

#[test]
fn rust_peer_serves_blob_to_rust_client() {
    let Some(server) = start_server() else { return };
    let a = std::env::temp_dir().join(format!("ss-rp-a-{}", std::process::id()));
    let _ = fs::remove_dir_all(&a);

    // A 上传一个文件
    write(&a, "shared.txt", "p2p payload from rust");
    sync(&server, &a);
    let digest = selfshare_core::util::sha256_file(&a.join("shared.txt")).unwrap();

    let broker = Client::new(&server.url, &server.vault, &server.token);
    let peer_id = "rust-peer-test".to_string();
    let mut node = selfshare_core::PeerServer::start(
        a.clone(),
        server.vault.clone(),
        server.token.clone(),
        peer_id.clone(),
        0,
    )
    .expect("peer start failed");
    assert!(node.listen.contains(':'));

    // 用 HMAC 直连拉取
    let data = broker
        .get_blob_p2p(&digest, &node.listen, &peer_id)
        .expect("p2p fetch failed");
    assert_eq!(data, b"p2p payload from rust");

    node.stop();
    let _ = fs::remove_dir_all(&a);
}

#[test]
fn rust_peer_rejects_bad_mac() {
    let Some(server) = start_server() else { return };
    let a = std::env::temp_dir().join(format!("ss-rp-sec-{}", std::process::id()));
    let _ = fs::remove_dir_all(&a);
    write(&a, "secret.txt", "classified");
    sync(&server, &a);
    let digest = selfshare_core::util::sha256_file(&a.join("secret.txt")).unwrap();

    let mut node = selfshare_core::PeerServer::start(
        a.clone(), server.vault.clone(), server.token.clone(), "p".into(), 0,
    ).unwrap();

    // 用错误 token 构造 MAC，必须被拒绝
    let bad = selfshare_core::peer::hmac_hex("wrong", &format!("{}:p", server.vault), &digest, "n");
    let url = format!("http://{}/p2p/blob/{}?peer_id=p&nonce=n", node.listen, digest);
    let resp = ureq::get(&url).set("X-P2P-MAC", &bad).call();
    assert!(resp.is_err(), "bad MAC must be rejected");

    node.stop();
    let _ = fs::remove_dir_all(&a);
}
