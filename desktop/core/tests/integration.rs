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

/// 找可用的 Python 解释器：Linux 上通常只有 `python3`。
fn python_exe() -> String {
    for cand in ["python3", "python"] {
        if Command::new(cand)
            .arg("--version")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
        {
            return cand.to_string();
        }
    }
    "python".to_string()
}


/// 每个测试用独立临时目录，避免并行执行时互相覆盖。
fn tmp_dir(tag: &str) -> PathBuf {
    static SEQ: AtomicUsize = AtomicUsize::new(0);
    let n = SEQ.fetch_add(1, Ordering::SeqCst);
    let p = std::env::temp_dir().join(format!("ss-{}-{}-{}", tag, std::process::id(), n));
    let _ = fs::remove_dir_all(&p);
    p
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
    let root = tmp_dir("rs-test");
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).ok()?;
    let token = "rs-test-token".to_string();
    let vault = "v1".to_string();

    // 先建库
    let py = python_exe();
    let create = Command::new(&py)
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
    let child = Command::new(&py)
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
    let a = tmp_dir("rs-a");
    let b = tmp_dir("rs-b");
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
    let a = tmp_dir("rs-ca");
    let b = tmp_dir("rs-cb");
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
    let a = tmp_dir("rs-da");
    let b = tmp_dir("rs-db");
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
    let a = tmp_dir("rs-ia");
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
    let a = tmp_dir("rs-pa");
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

/// `ss_pair` 失败后必须把 PROGRESS 从 "syncing" 复位，否则 GUI 轮询 `ss_progress`
/// 会永远停在「同步中」。用刚释放的空闲端口让 `Client::pair` 立即失败，
/// 不依赖真实服务端（start_server / python）。
#[test]
fn ffi_pair_failure_resets_progress() {
    use std::ffi::{CStr, CString};
    use std::os::raw::c_char;

    // free_port() 只短暂占用一个本地端口便释放，此处不启动任何监听；
    // 配合无效配对码，无论该端口是否恰好被其它并行测试占用，pair 都会失败。
    let port = free_port();
    let req = format!(
        "{{\"folder\":\"unused\",\"url\":\"http://127.0.0.1:{}\",\"code\":\"invalid-code\"}}",
        port
    );

    unsafe {
        let input = CString::new(req).unwrap();
        let out = selfshare_core::ffi::ss_pair(input.as_ptr() as *const c_char);
        let msg = CStr::from_ptr(out).to_str().unwrap().to_string();
        selfshare_core::ffi::ss_free(out);
        assert!(msg.contains("\"ok\":false"), "配对失败应返回错误 JSON：{}", msg);

        // 紧接着读取全局进度快照：失败路径不得遗留 syncing，且必须写入错误信息与文本。
        let snap = selfshare_core::ffi::ss_progress();
        let text = CStr::from_ptr(snap).to_str().unwrap().to_string();
        selfshare_core::ffi::ss_free(snap);
        assert!(
            !text.contains("\"state\":\"syncing\""),
            "失败后不得停留在 syncing：{}",
            text
        );
        assert!(
            text.contains("\"last_error\":") && !text.contains("\"last_error\":null"),
            "失败后必须写入 last_error：{}",
            text
        );
        assert!(
            !text.contains("\"message\":\"\""),
            "失败后 message 应给出可观测文本：{}",
            text
        );
    }
}

// --------------------------------------------------------------------------- //
// 删除与编辑相撞（AGENTS.md §6 四类必测之一）：两向端到端断言
// --------------------------------------------------------------------------- //

/// 「删除撞编辑」方向一：A 删除、B 编辑，最终保留 B 的编辑（不丢数据）。
/// 语义基线：sync.py 三方合并表第 16 行 / engine.rs::plan_with
/// 「本地已删但远端有改动 → 保留远端」。该分支是 Pull 而非 Conflict，
/// 故不产生冲突副本；keep-both 仅用于「双方都改」，已由
/// rust_detects_conflict_and_keeps_both 覆盖。
#[test]
fn rust_delete_vs_edit_remote_wins() {
    let Some(server) = start_server() else { return };
    let a = tmp_dir("rs-dea");
    let b = tmp_dir("rs-deb");
    let _ = fs::remove_dir_all(&a);
    let _ = fs::remove_dir_all(&b);

    // 共同基线：A 上传、B 拉取，两端各建立 base 快照。
    write(&a, "shared.txt", "base");
    let mut revs = vec![sync(&server, &a).head_rev];
    revs.push(sync(&server, &b).head_rev);
    assert_eq!(read(&b, "shared.txt"), "base");

    // 离线并发：A 删除、B 编辑。内容长度刻意不同，避免 (size, mtime) 复用误判。
    fs::remove_file(a.join("shared.txt")).unwrap();
    write(&b, "shared.txt", "B 编辑版本");

    // B 先把编辑推到服务端。
    let rb = sync(&server, &b);
    revs.push(rb.head_rev);
    assert!(rb.pushes.contains(&"shared.txt".to_string()), "{}", rb.summary());
    assert!(rb.errors.is_empty(), "{:?}", rb.errors);

    // A 同步：本地已删 + 远端有改动 → Pull，被删文件复活为 B 的编辑版本。
    let ra = sync(&server, &a);
    revs.push(ra.head_rev);
    assert!(ra.pulls.contains(&"shared.txt".to_string()), "{}", ra.summary());
    assert!(ra.conflicts.is_empty(), "删除撞编辑不应判为双方都改：{}", ra.summary());
    assert!(ra.errors.is_empty(), "{:?}", ra.errors);
    assert_eq!(read(&a, "shared.txt"), "B 编辑版本", "B 的编辑不得丢失");

    // 再各同步一次收敛，两端应完全一致。
    revs.push(sync(&server, &b).head_rev);
    revs.push(sync(&server, &a).head_rev);
    assert_eq!(read(&a, "shared.txt"), read(&b, "shared.txt"));

    // 服务端 head_rev 全局单调递增，不得回退；且本用例确有提交。
    assert!(revs.windows(2).all(|w| w[1] >= w[0]), "head_rev 必须单调不减：{:?}", revs);
    assert!(*revs.last().unwrap() > revs[0], "本用例应当发生提交：{:?}", revs);

    // 冲突副本命名契约：删除撞编辑保留编辑 ≠ 保留双方，不生成副本；
    // 命名常量仍须是「冲突副本」，与 rust_detects_conflict_and_keeps_both 一致。
    assert_eq!(selfshare_core::engine::CONFLICT_TAG, "冲突副本");
    let no_copy = |d: &Path| {
        let names: Vec<String> = fs::read_dir(d)
            .unwrap()
            .flatten()
            .map(|e| e.file_name().to_string_lossy().to_string())
            .collect();
        assert!(
            !names.iter().any(|n| n.contains(selfshare_core::engine::CONFLICT_TAG)),
            "删除撞编辑不应产生冲突副本：{:?}",
            names
        );
    };
    no_copy(&a);
    no_copy(&b);

    let _ = fs::remove_dir_all(&a);
    let _ = fs::remove_dir_all(&b);
}

/// 「删除撞编辑」方向二：A 编辑、B 删除，最终保留 A 的编辑
/// （force 复活墓碑，不丢数据）。语义基线：sync.py 第 18 行 /
/// engine.rs::plan_with「本地有改动但远端已删 → 保留本地」；
/// 对应 store.py::commit 的 force + current is None 分支，
/// 与 Go 侧 tombstone + force resurrect 对齐。
#[test]
fn rust_edit_vs_delete_local_wins() {
    let Some(server) = start_server() else { return };
    let a = tmp_dir("rs-eda");
    let b = tmp_dir("rs-edb");
    let _ = fs::remove_dir_all(&a);
    let _ = fs::remove_dir_all(&b);

    write(&a, "shared.txt", "base");
    let mut revs = vec![sync(&server, &a).head_rev];
    revs.push(sync(&server, &b).head_rev);
    assert_eq!(read(&b, "shared.txt"), "base");

    // 离线并发：A 编辑、B 删除。
    write(&a, "shared.txt", "A 编辑版本");
    fs::remove_file(b.join("shared.txt")).unwrap();

    // B 先把删除推到服务端（写墓碑、head_rev 递增）。
    let rb = sync(&server, &b);
    revs.push(rb.head_rev);
    assert!(rb.deletes_remote.contains(&"shared.txt".to_string()), "{}", rb.summary());
    assert!(rb.errors.is_empty(), "{:?}", rb.errors);

    // A 同步：本地有改动 + 远端已删 → Push(force) 复活；
    // 若 force 被服务端拒绝，错误会落进 report.errors，此断言即暴露问题。
    let ra = sync(&server, &a);
    revs.push(ra.head_rev);
    assert!(ra.pushes.contains(&"shared.txt".to_string()), "{}", ra.summary());
    assert!(ra.conflicts.is_empty(), "删除撞编辑不应判为双方都改：{}", ra.summary());
    assert!(ra.errors.is_empty(), "force 复活不应被判提交冲突：{:?}", ra.errors);
    assert_eq!(read(&a, "shared.txt"), "A 编辑版本", "A 的编辑不得丢失");

    // B 收敛：之前删掉的文件以 A 的编辑版本复活（远端新增 → Pull）。
    let rb2 = sync(&server, &b);
    revs.push(rb2.head_rev);
    assert!(rb2.errors.is_empty(), "{:?}", rb2.errors);
    assert_eq!(read(&b, "shared.txt"), "A 编辑版本", "B 端应拉回被保留的编辑");
    revs.push(sync(&server, &a).head_rev);
    assert_eq!(read(&a, "shared.txt"), read(&b, "shared.txt"));

    assert!(revs.windows(2).all(|w| w[1] >= w[0]), "head_rev 必须单调不减：{:?}", revs);
    assert!(*revs.last().unwrap() > revs[0], "本用例应当发生提交：{:?}", revs);

    assert_eq!(selfshare_core::engine::CONFLICT_TAG, "冲突副本");
    let no_copy = |d: &Path| {
        let names: Vec<String> = fs::read_dir(d)
            .unwrap()
            .flatten()
            .map(|e| e.file_name().to_string_lossy().to_string())
            .collect();
        assert!(
            !names.iter().any(|n| n.contains(selfshare_core::engine::CONFLICT_TAG)),
            "删除撞编辑不应产生冲突副本：{:?}",
            names
        );
    };
    no_copy(&a);
    no_copy(&b);

    let _ = fs::remove_dir_all(&a);
    let _ = fs::remove_dir_all(&b);
}

// --------------------------------------------------------------------------- //
// P2P：Rust 节点 <-> Python 服务端 / Rust 客户端互通
// --------------------------------------------------------------------------- //

#[test]
fn hmac_matches_python_implementation() {
    use std::io::Write;

    let mac = selfshare_core::peer::hmac_hex("tok", "vault:peer1", "abcd", "n1");
    assert_eq!(mac.len(), 64);
    assert!(mac.chars().all(|c| c.is_ascii_hexdigit()));

    // 同输入必须稳定
    assert_eq!(mac, selfshare_core::peer::hmac_hex("tok", "vault:peer1", "abcd", "n1"));
    // 任一字段变化都必须改变结果
    assert_ne!(mac, selfshare_core::peer::hmac_hex("tok2", "vault:peer1", "abcd", "n1"));
    assert_ne!(mac, selfshare_core::peer::hmac_hex("tok", "vault:peer1", "abce", "n1"));

    // 逐字节一致性必须拿 Python 的实现来比，只比 Rust 自己证明不了跨实现互通
    let cases = [
        ("tok", "vault:peer1", "abcd", "n1"),
        ("tok2", "vault:peer1", "abcd", "n1"),
        ("tok", "vault:peer1", "abce", "n1"),
        ("", "v:1", &"0".repeat(64), "nonce with spaces"),
        ("s3cr3t", "myvault:peer-9", "deadbeef", "cafe"),
        ("tok", "vault:peer1", "abcd", ""),
    ];

    let snippet = r#"
import sys
from selfshare.p2p import make_p2p_hmac
for line in sys.stdin:
    line = line.rstrip("\n")
    if not line:
        continue
    token, peer, digest, nonce = line.split("\t")
    print(make_p2p_hmac(token, peer, digest, nonce))
"#;

    let mut child = match Command::new(python_exe())
        .arg("-c")
        .arg(snippet)
        .current_dir(repo_root())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(c) => c,
        Err(_) => {
            eprintln!("跳过：python 不可用，无法做跨实现 HMAC 对比");
            return;
        }
    };

    {
        let stdin = child.stdin.as_mut().expect("stdin");
        for (token, peer, digest, nonce) in cases {
            writeln!(stdin, "{token}\t{peer}\t{digest}\t{nonce}").unwrap();
        }
    }

    let out = child.wait_with_output().expect("等待 python 结束");
    if !out.status.success() {
        eprintln!("跳过：python 计算 HMAC 失败");
        return;
    }
    let lines: Vec<String> = String::from_utf8_lossy(&out.stdout)
        .lines()
        .map(|s| s.trim().to_string())
        .collect();
    assert_eq!(
        lines.len(),
        cases.len(),
        "python 返回的行数与输入不一致"
    );
    for (idx, (token, peer, digest, nonce)) in cases.iter().enumerate() {
        assert_eq!(
            lines[idx],
            selfshare_core::peer::hmac_hex(token, peer, digest, nonce),
            "第 {} 组输入的 HMAC 两端不一致",
            idx + 1
        );
    }
    println!("HMAC 跨实现比对完成：{} 组输入与 python make_p2p_hmac 逐字节一致", cases.len());
}

#[test]
fn rust_peer_serves_blob_to_rust_client() {
    let Some(server) = start_server() else { return };
    let a = tmp_dir("rp-a");
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
    let a = tmp_dir("rp-sec");
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

/// docs/p2p.md 声称两种实现可互为 peer：这里让 Rust 客户端直接从 Python 节点取数据，
/// 并验证 Python 节点会拒绝 Rust 用错误 token 生成的 MAC。
#[test]
fn rust_client_pulls_blob_from_python_peer() {
    let Some(server) = start_server() else { return };
    let script = repo_root().join("selfshare.py");
    let py = python_exe();
    let peer_dir = tmp_dir("py-peer");
    let _ = fs::remove_dir_all(&peer_dir);
    fs::create_dir_all(&peer_dir).unwrap();

    let mounted = Command::new(&py)
        .arg(&script)
        .args([
            "mount",
            &peer_dir.to_string_lossy(),
            "--url",
            &server.url,
            "--vault",
            &server.vault,
            "--token",
            &server.token,
        ])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    if !mounted.map(|s| s.success()).unwrap_or(false) {
        eprintln!("跳过：python mount 不可用");
        let _ = fs::remove_dir_all(&peer_dir);
        return;
    }

    let payload = "payload served by the python peer";
    write(&peer_dir, "python-held.bin", payload);
    let uploaded = Command::new(&py)
        .arg(&script)
        .args(["sync", &peer_dir.to_string_lossy()])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    assert!(uploaded.map(|s| s.success()).unwrap_or(false), "python 端上传应成功");
    let digest = selfshare_core::util::sha256_file(&peer_dir.join("python-held.bin")).unwrap();

    let mut peer = match Command::new(&py)
        .arg(&script)
        .args([
            "watch", &peer_dir.to_string_lossy(), "--p2p",
            "--interval", "1", "--debounce", "1",
        ])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(c) => c,
        Err(_) => {
            eprintln!("跳过：无法启动 python peer");
            let _ = fs::remove_dir_all(&peer_dir);
            return;
        }
    };

    let client = Client::new(&server.url, &server.vault, &server.token);
    let mut found: Option<(String, String)> = None;
    for _ in 0..60 {
        if let Ok(ps) = client.peers(None) {
            if let Some(p) = ps.first() {
                found = Some((p.listen.clone(), p.peer_id.clone()));
                break;
            }
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    let Some((listen, peer_id)) = found else {
        let _ = peer.kill();
        let _ = fs::remove_dir_all(&peer_dir);
        panic!("Python peer 没有注册到中心服务器");
    };

    let got = client.get_blob_p2p(&digest, &listen, &peer_id);
    let wrong = Client::new(&server.url, &server.vault, "totally-wrong-token");
    let rejected = wrong.get_blob_p2p(&digest, &listen, &peer_id).is_err();

    let _ = peer.kill();
    let _ = peer.wait();
    let _ = fs::remove_dir_all(&peer_dir);

    assert_eq!(
        got.expect("Rust 客户端应能从 Python peer 直连取回 blob").as_slice(),
        payload.as_bytes()
    );
    assert!(rejected, "Python 节点必须拒绝错误 token 的 Rust 请求");
    println!("跨实现 peer 互通已验证：python 节点 {} (peer_id={})", listen, peer_id);
}

/// 预演（dry run）必须报告“会拉取哪些文件”，与 Python 端保持一致，
/// 同时不能真的写盘。
#[test]
fn rust_dry_run_reports_pending_pulls() {
    let Some(server) = start_server() else { return };
    let a = tmp_dir("rs-dr-a");
    let b = tmp_dir("rs-dr-b");
    let _ = fs::remove_dir_all(&a);
    let _ = fs::remove_dir_all(&b);
    fs::create_dir_all(&b).unwrap();

    write(&a, "pending.txt", "to be pulled");
    sync(&server, &a);

    let state = mount(&server, &b);
    let cfg = state.config().clone();
    let client = Client::new(&cfg.url, &cfg.vault, &cfg.token);
    let mut opts = SyncOptions::load(&b);
    opts.dry_run = true;
    let mut syncer = Syncer::with_options(client, state, opts);
    let report = syncer.sync().expect("预演同步失败");

    assert_eq!(
        report.pulls.len(),
        1,
        "预演应报告 1 个待拉取文件，否则 GUI 预演与真实同步结果不一致"
    );
    assert!(
        !b.join("pending.txt").exists(),
        "预演不能真的把文件写到磁盘"
    );
    println!("预演报告 pulls={:?}", report.pulls);

    let _ = fs::remove_dir_all(&a);
    let _ = fs::remove_dir_all(&b);
}
