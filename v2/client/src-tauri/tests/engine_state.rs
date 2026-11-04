//! 不依赖 GUI 的引擎状态测试：设置持久化与托盘暂停/恢复。

use selfshare_lib::{Settings, SyncEngine};

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
