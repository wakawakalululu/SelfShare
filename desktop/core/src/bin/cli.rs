//! 内核自带的最小 CLI，用于在没有 Flutter 的机器上验证同步逻辑。

use std::path::PathBuf;
use std::process::ExitCode;

use selfshare_core::client::Client;
use selfshare_core::engine::{SyncOptions, Syncer};
use selfshare_core::state::{LocalState, MountConfig};

fn usage() {
    eprintln!(
        "用法:
  selfshare-cli mount <目录> <url> <vault> <token>
  selfshare-cli sync  <目录> [--dry-run]
  selfshare-cli plan  <目录>
  selfshare-cli info  <目录>"
    );
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() < 2 {
        usage();
        return ExitCode::from(2);
    }
    let cmd = args[0].as_str();
    let folder = PathBuf::from(&args[1]);
    match cmd {
        "mount" => {
            if args.len() < 5 {
                usage();
                return ExitCode::from(2);
            }
            let url = &args[2];
            let vault = &args[3];
            let token = &args[4];
            let client = Client::new(url, vault, token);
            match client.stat() {
                Ok(s) => println!("连接成功：远端 {} 个文件，{} 字节", s.files, s.bytes),
                Err(e) => {
                    eprintln!("连接失败：{}", e);
                    return ExitCode::from(1);
                }
            }
            let cfg = MountConfig {
                url: url.trim_end_matches('/').to_string(),
                vault: vault.clone(),
                token: token.clone(),
                folder: folder.to_string_lossy().to_string(),
                host_id: selfshare_core::util::host_id(),
                created: selfshare_core::util::now_stamp(),
            };
            match LocalState::init_mount(&folder, cfg) {
                Ok(_) => println!("已挂载：{}", folder.display()),
                Err(e) => {
                    eprintln!("挂载失败：{}", e);
                    return ExitCode::from(1);
                }
            }
        }
        "sync" | "plan" => {
            let dry = args.iter().any(|a| a == "--dry-run");
            let state = match LocalState::open(&folder) {
                Ok(s) => s,
                Err(e) => {
                    eprintln!("{}", e);
                    return ExitCode::from(1);
                }
            };
            let cfg = state.config().clone();
            let client = Client::new(&cfg.url, &cfg.vault, &cfg.token);
            let mut options = SyncOptions::load(state.folder());
            options.dry_run = dry;
            let mut syncer = Syncer::with_options(client, state, options);
            // --p2p：先起节点服务，再让同步优先走 peer
            let mut node = if args.iter().any(|a| a == "--p2p") {
                let cfg2 = syncer.state.config().clone();
                let peer_id = selfshare_core::peer::make_peer_id(&format!("rust-{}", selfshare_core::util::host_id()));
                match selfshare_core::PeerServer::start(
                    syncer.state.folder().to_path_buf(),
                    cfg2.vault.clone(),
                    cfg2.token.clone(),
                    peer_id.clone(),
                    0,
                ) {
                    Ok(n) => {
                        println!("P2P 节点: {} (peer_id={})", n.listen, peer_id);
                        syncer.peer_id = Some(peer_id);
                        Some(n)
                    }
                    Err(e) => {
                        eprintln!("P2P 启动失败，回退服务器模式：{}", e);
                        None
                    }
                }
            } else {
                None
            };
            if args[0] == "plan" {
                match syncer.plan() {
                    Ok(actions) => {
                        for a in actions {
                            println!("{:?}\t{}\t{}", a.kind, a.path, a.reason);
                        }
                    }
                    Err(e) => {
                        eprintln!("{}", e);
                        return ExitCode::from(1);
                    }
                }
            } else {
                let result = syncer.sync();
                if let Some(n) = node.as_mut() { n.stop(); }
                match result {
                    Ok(r) => {
                        println!("{}", r.summary());
                        for p in &r.pulls {
                            println!("  ↓ {}", p);
                        }
                        for p in &r.pushes {
                            println!("  ↑ {}", p);
                        }
                        for p in &r.conflicts {
                            println!("  * {}", p);
                        }
                        for e in &r.errors {
                            println!("  ! {}", e);
                        }
                        if !syncer.sources.is_empty() {
                            for (rel, src) in &syncer.sources {
                                println!("    {} <- {}", rel, src);
                            }
                        }
                    }
                    Err(e) => {
                        eprintln!("同步失败：{}", e);
                        return ExitCode::from(1);
                    }
                }
            }
        }
        "info" => match LocalState::open(&folder) {
            Ok(st) => {
                let c = st.config();
                println!("目录  : {}", st.folder().display());
                println!("服务端: {}", c.url);
                println!("同步库: {}", c.vault);
                println!("本机  : {}", c.host_id);
                println!("跟踪  : {} 项", st.snapshot().files.len());
                println!("修订  : {}", st.snapshot().head_rev);
                println!("上次  : {}", st.snapshot().last_sync);
            }
            Err(e) => {
                eprintln!("{}", e);
                return ExitCode::from(1);
            }
        },
        _ => {
            usage();
            return ExitCode::from(2);
        }
    }
    ExitCode::SUCCESS
}
