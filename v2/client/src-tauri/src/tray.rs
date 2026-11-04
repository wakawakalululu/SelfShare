//! 系统托盘：参考 syncthingtray 的实时状态提示 + 菜单控制。
//!
//! 菜单里的「暂停 / 恢复 / 立即同步全部」直接作用于共享的 SyncEngine，
//! 不再只是打印日志；tooltip 由 `spawn_status_updater` 每 5 秒刷新一次。

use std::time::Duration;

use tauri::{
    menu::MenuBuilder,
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager,
};

use crate::commands::AppState;

const TRAY_ID: &str = "main";

pub fn setup_tray(app: &AppHandle) -> tauri::Result<()> {
    let menu = MenuBuilder::new(app)
        .text("open", "打开 SelfShare")
        .separator()
        .text("sync_all", "立即同步全部")
        .text("pause", "暂停同步")
        .text("resume", "恢复同步")
        .separator()
        .text("quit", "退出")
        .build()?;

    let _tray = TrayIconBuilder::with_id(TRAY_ID)
        .tooltip("SelfShare - 文件同步")
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main(tray.app_handle());
            }
        })
        .menu(&menu)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open" => show_main(app),
            "sync_all" => {
                let engine = app.state::<AppState>().engine.clone();
                tauri::async_runtime::spawn(async move {
                    let e = engine.lock().await;
                    let _ = e.sync_all().await;
                });
            }
            "pause" => {
                let engine = app.state::<AppState>().engine.clone();
                let handle = app.clone();
                tauri::async_runtime::spawn(async move {
                    let e = engine.lock().await;
                    let _ = e.pause_all().await;
                    set_tooltip(&handle, "SelfShare · 同步已暂停");
                });
            }
            "resume" => {
                let engine = app.state::<AppState>().engine.clone();
                let handle = app.clone();
                tauri::async_runtime::spawn(async move {
                    let e = engine.lock().await;
                    let _ = e.resume_all().await;
                    set_tooltip(&handle, "SelfShare · 同步已恢复");
                });
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .build(app)?;

    Ok(())
}

/// 周期性把引擎状态反映到托盘提示（暂停 / 同步中 / 监控数量）。
pub fn spawn_status_updater(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        let mut tick = tokio::time::interval(Duration::from_secs(5));
        loop {
            tick.tick().await;
            let engine = {
                let state = app.state::<AppState>();
                state.engine.clone()
            };
            let (paused, syncing, watching) = {
                let e = engine.lock().await;
                e.tray_state()
            };
            let text = if paused {
                "SelfShare · 同步已暂停".to_string()
            } else if syncing > 0 {
                format!("SelfShare · 正在同步 {} 个文件夹", syncing)
            } else {
                format!("SelfShare · {} 个文件夹监控中", watching)
            };
            set_tooltip(&app, &text);
        }
    });
}

fn set_tooltip(app: &AppHandle, text: &str) {
    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        let _ = tray.set_tooltip(Some(text));
    }
}

fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}
