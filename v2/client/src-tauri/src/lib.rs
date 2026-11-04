use std::path::PathBuf;
use std::sync::Arc;
use tauri::Manager;
use tokio::sync::Mutex;

mod commands;
mod sync;
mod tray;

pub use commands::*;
pub use sync::*;

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            let config_dir = dirs::config_dir()
                .unwrap_or_else(|| PathBuf::from("."))
                .join("selfshare");

            let engine = crate::sync::SyncEngine::new(config_dir);
            let state = commands::AppState {
                engine: Arc::new(Mutex::new(engine)),
            };
            app.manage(state);

            tray::setup_tray(app.handle())?;
            // 参考 syncthingtray：托盘提示随同步状态实时变化。
            tray::spawn_status_updater(app.handle().clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_version,
            commands::probe_server,
            commands::pair_with_code,
            commands::add_mount,
            commands::remove_mount,
            commands::list_mounts,
            commands::sync_mount,
            commands::get_sync_status,
            commands::start_watching,
            commands::stop_watching,
            commands::get_history,
            commands::restore_version,
            commands::get_vault_stat,
            commands::get_settings,
            commands::save_settings,
            commands::pause_sync_all,
            commands::resume_sync_all,
            commands::is_sync_paused,
            commands::sync_all_mounts,
            commands::list_peers,
        ])
        .run(tauri::generate_context!())
        .expect("error while running SelfShare");
}
