//! 不依赖 GUI 的引擎状态测试：设置持久化与托盘暂停/恢复。

use selfshare_lib::{MountConfig, Settings, SyncEngine};

fn temp_dir(name: &str) -> std::path::PathBuf {
    let dir = std::env::temp_dir().join(format!("selfshare-{}-{}", name, std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    dir
}

#[tokio::test]
async fn settings_roundtrip() {
    let dir = temp_dir("settings");
    let engine = SyncEngine::new(dir.clone());
    let defaults = engine.load_settings();
    assert_eq!(defaults.sync_interval_secs, 10);
    assert!(!defaults.enable_p2p);

    let updated = Settings {
        default_server_url: "https://192.168.1.10:8484".to_string(),
        sync_interval_secs: 25,
        enable_p2p: true,
        ..defaults
    };
    engine.save_settings(&updated).expect("保存设置失败");

    // 模拟重启：新实例从磁盘读回同一份配置。
    let reloaded = SyncEngine::new(dir.clone()).load_settings();
    assert_eq!(reloaded.default_server_url, "https://192.168.1.10:8484");
    assert_eq!(reloaded.sync_interval_secs, 25);
    assert!(reloaded.enable_p2p);
    let _ = std::fs::remove_dir_all(&dir);
}

#[tokio::test]
async fn pause_resume_and_tray_state() {
    let dir = temp_dir("pause");
    let engine = SyncEngine::new(dir.clone());
    let (paused, syncing, watching) = engine.tray_state();
    assert!(!paused && syncing == 0 && watching == 0);

    engine.pause_all().await.expect("暂停失败");
    assert!(engine.is_paused());
    assert!(engine.tray_state().0);

    engine.resume_all().await.expect("恢复失败");
    assert!(!engine.is_paused());
    assert!(!engine.tray_state().0);
    let _ = std::fs::remove_dir_all(&dir);
}

#[tokio::test]
async fn pause_twice_then_resume_restarts_watchers() {
    let dir = temp_dir("pause-twice");
    let engine = SyncEngine::new(dir.clone());

    // 准备「已挂载 + 正在监控」的文件夹。127.0.0.1:1 会被立即拒绝，
    // 不需要任何服务端夹具：watcher 启动同步失败只写状态表，
    // 不影响「watcher 句柄是否存在」的断言。
    let mount = MountConfig {
        name: "m".to_string(),
        local_path: dir.join("folder").to_string_lossy().to_string(),
        server_url: "http://127.0.0.1:1".to_string(),
        vault_id: "v".to_string(),
        token: "t".to_string(),
    };
    engine.add_mount(mount).await.expect("挂载失败");
    // 取轮询下限，缩短测试结束时 join 监视线程的等待。
    engine
        .save_settings(&Settings {
            sync_interval_secs: 5,
            ..engine.load_settings()
        })
        .expect("保存设置失败");
    engine.start_watch("m").await.expect("启动监控失败");
    assert_eq!(engine.tray_state().2, 1, "暂停前应有 1 个 watcher");

    // 首次暂停：记录 resume_names={"m"} 并摘除 watcher。
    engine.pause_all().await.expect("首次暂停失败");
    assert_eq!(engine.tray_state().2, 0, "暂停后 watcher 应全部摘除");
    // 回归点：第二次暂停时 watchers 已空，绝不能把 resume_names 覆盖为空。
    engine.pause_all().await.expect("二次暂停失败");
    assert!(engine.is_paused());

    engine.resume_all().await.expect("恢复失败");
    assert!(!engine.is_paused());
    assert_eq!(
        engine.tray_state().2,
        1,
        "恢复后必须按首次记录的集合重启 watcher"
    );
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn restore_keeps_local_unsynced_edit() {
    let dir = temp_dir("restore");
    std::fs::create_dir_all(&dir).expect("创建临时目录失败");

    // 本地同名文件含未同步编辑；恢复内容来自历史 blob。
    let target = dir.join("note.txt");
    let local_edit: &[u8] = b"LOCAL UNSYNCED EDIT";
    let restored: &[u8] = b"content from history rev 7";
    std::fs::write(&target, local_edit).expect("写入本地文件失败");

    // 直接调用不触网的落地段（等价于 restore_version 下载 blob 后的写入）。
    let written =
        SyncEngine::write_restored_bytes(&target, restored).expect("写入恢复版本失败");

    // 1) 本地未同步编辑未被覆盖（数据不丢红线）。
    assert_eq!(std::fs::read(&target).unwrap().as_slice(), local_edit);
    // 2) 恢复内容落在同目录的「(恢复 时间戳)」副本，而非原路径。
    assert_ne!(written, target);
    assert_eq!(written.parent(), Some(dir.as_path()));
    let name = written.file_name().unwrap().to_string_lossy().to_string();
    assert!(name.starts_with("note (恢复 "), "副本命名不符：{}", name);
    assert!(name.ends_with(").txt"), "副本扩展名不符：{}", name);
    assert_eq!(std::fs::read(&written).unwrap().as_slice(), restored);
    // 3) 目标不存在时仍写原路径。
    let missing = dir.join("fresh.txt");
    let written2 =
        SyncEngine::write_restored_bytes(&missing, restored).expect("写入新文件失败");
    assert_eq!(written2, missing);
    assert_eq!(std::fs::read(&missing).unwrap().as_slice(), restored);

    let _ = std::fs::remove_dir_all(&dir);
}
