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

/// §5.3 合规回归：save_settings 走原子写后，磁盘内容仍是与
/// `serde_json::to_vec_pretty` 完全一致的序列化字节，且不残留同目录临时文件；
/// 模拟重启后字段逐一还原。纯本地文件 IO，不依赖网络 / 权限。
#[test]
fn settings_atomic_roundtrip_keeps_serialized_bytes() {
    let dir = temp_dir("atomic-settings");
    let engine = SyncEngine::new(dir.clone());

    let updated = Settings {
        default_server_url: "https://192.168.1.11:9443".to_string(),
        sync_interval_secs: 30,
        enable_p2p: true,
        ..Settings::default()
    };
    let expected = serde_json::to_vec_pretty(&updated).expect("序列化设置失败");
    engine.save_settings(&updated).expect("原子保存设置失败");

    let path = dir.join("settings.json");
    let on_disk = std::fs::read(&path).expect("读取 settings.json 失败");
    // 1) 写盘字节 == 序列化字节（路径、JSON 结构、字段名均不变）。
    assert_eq!(on_disk, expected, "落盘字节与序列化结果不一致");

    // 2) 原子写 rename 后不应留下 `*.selfshare-tmp-*` 临时文件。
    for entry in std::fs::read_dir(&dir).expect("读取配置目录失败") {
        let name = entry.expect("遍历配置目录失败").file_name();
        let name = name.to_string_lossy();
        assert!(
            !name.contains("selfshare-tmp-"),
            "原子写残留临时文件：{}",
            name
        );
    }

    // 3) 模拟重启：新实例读回同一份配置。
    let reloaded = SyncEngine::new(dir.clone()).load_settings();
    assert_eq!(reloaded.default_server_url, updated.default_server_url);
    assert_eq!(reloaded.sync_interval_secs, 30);
    assert!(reloaded.enable_p2p);
    let _ = std::fs::remove_dir_all(&dir);
}

/// 现有行为回归：load_settings 对损坏 / 类型错误的 settings.json 静默回退
/// 默认值（unwrap_or_default），且不改写磁盘上的损坏文件；随后仍可正常覆盖保存。
/// 断言严格基于当前行为，不改变契约。
#[test]
fn corrupt_settings_falls_back_to_defaults_and_is_observable() {
    let dir = temp_dir("corrupt-settings");
    std::fs::create_dir_all(&dir).expect("创建临时目录失败");
    let path = dir.join("settings.json");

    // (a) 非 JSON 文本：整体解析失败 → Default。
    let broken: &[u8] = b"{ this is not valid json";
    std::fs::write(&path, broken).expect("写入损坏文件失败");
    let engine = SyncEngine::new(dir.clone());
    let loaded = engine.load_settings();
    assert_eq!(loaded.sync_interval_secs, 10);
    assert!(!loaded.enable_p2p);
    assert_eq!(loaded.default_server_url, "http://127.0.0.1:8484");
    assert_eq!(loaded.theme, "system");
    assert!(loaded.show_notifications);
    assert!(!loaded.auto_start);
    // 回退是纯内存行为：磁盘上的损坏内容原样保留，未被 load_settings 改写。
    assert_eq!(std::fs::read(&path).unwrap().as_slice(), broken);

    // (b) 合法 JSON 但字段类型错误：同样整体回退默认值。
    std::fs::write(&path, b"{\"sync_interval_secs\": \"oops\"}").expect("写入类型错误文件失败");
    let loaded2 = SyncEngine::new(dir.clone()).load_settings();
    assert_eq!(loaded2.sync_interval_secs, 10);

    // (c) 回退之后仍可覆盖修复，新实例读到新值。
    let repaired = Settings {
        sync_interval_secs: 42,
        ..Settings::default()
    };
    engine.save_settings(&repaired).expect("覆盖修复失败");
    let reloaded = SyncEngine::new(dir.clone()).load_settings();
    assert_eq!(reloaded.sync_interval_secs, 42);
    let _ = std::fs::remove_dir_all(&dir);
}
