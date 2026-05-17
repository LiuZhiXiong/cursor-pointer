mod api;
mod input;
mod screen;

use std::sync::Arc;
use tauri::{Manager, PhysicalPosition, PhysicalSize, WebviewUrl, WebviewWindowBuilder};
use tracing::info;

const DEFAULT_PORT: u16 = 39213;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let env_filter = tracing_subscriber::EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info"));
    let _ = tracing_subscriber::fmt().with_env_filter(env_filter).try_init();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            api_endpoint,
            quit_app,
            click_at,
            mouse_position,
        ])
        .setup(|app| {
            let port = std::env::var("CURSOR_POINTER_PORT")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(DEFAULT_PORT);
            let state = Arc::new(api::AppState {
                version: env!("CARGO_PKG_VERSION").to_string(),
                fx: Arc::new(api::FxQueue::new()),
                ocr: Arc::new(api::OcrState::new()),
                browser: Arc::new(api::BrowserQueue::new()),
                app: app.handle().clone(),
            });
            tauri::async_runtime::spawn(async move {
                if let Err(e) = api::serve(state, port).await {
                    tracing::error!("api server error: {}", e);
                }
            });

            // Spawn the click-feedback overlay (full-screen, transparent,
            // always-on-top, click-through). Skipped when
            // CURSOR_POINTER_NO_OVERLAY=1 — macOS 26's compositor + xcap can
            // interact badly with a fullscreen transparent window, occasionally
            // making the screenshot omit windows from other apps.
            // Treat empty / "0" / "false" as not-set so an inherited empty var
            // doesn't silently kill the overlay.
            let overlay_disabled = std::env::var("CURSOR_POINTER_NO_OVERLAY")
                .map(|v| !matches!(v.as_str(), "" | "0" | "false" | "no"))
                .unwrap_or(false);
            if !overlay_disabled {
                if let Err(e) = spawn_overlay(app.handle()) {
                    tracing::warn!("overlay not started: {}", e);
                }
            } else {
                info!("overlay disabled via CURSOR_POINTER_NO_OVERLAY");
            }

            info!("cursor-pointer ready, API http://127.0.0.1:{}", port);
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn spawn_overlay(app: &tauri::AppHandle) -> tauri::Result<()> {
    // Probe primary monitor size by spawning a hidden helper window briefly to
    // query monitors via Tauri (the API is only on a WebviewWindow). We use
    // the existing "control" window since it has been built by the config.
    let (w, h, x, y) = if let Some(ctrl) = app.get_webview_window("control") {
        if let Ok(Some(mon)) = ctrl.primary_monitor() {
            let sf = mon.scale_factor();
            let size: PhysicalSize<u32> = *mon.size();
            let pos: PhysicalPosition<i32> = *mon.position();
            (
                size.width as f64 / sf,
                size.height as f64 / sf,
                pos.x as f64 / sf,
                pos.y as f64 / sf,
            )
        } else {
            (1920.0, 1080.0, 0.0, 0.0)
        }
    } else {
        (1920.0, 1080.0, 0.0, 0.0)
    };

    let window = WebviewWindowBuilder::new(app, "overlay", WebviewUrl::App("overlay.html".into()))
        .title("CursorPointer Overlay")
        .transparent(true)
        .always_on_top(true)
        .decorations(false)
        .resizable(false)
        .skip_taskbar(true)
        .shadow(false)
        .visible(true)
        .focused(false)
        .inner_size(w, h)
        .position(x, y)
        .build()?;

    window.set_ignore_cursor_events(true)?;
    Ok(())
}

#[allow(dead_code)]
fn _suppress_unused() {
    let _ = std::mem::size_of::<PhysicalPosition<i32>>();
    let _ = std::mem::size_of::<PhysicalSize<u32>>();
}

#[tauri::command]
fn api_endpoint() -> serde_json::Value {
    let port = std::env::var("CURSOR_POINTER_PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(DEFAULT_PORT);
    serde_json::json!({
        "url": format!("http://127.0.0.1:{}", port),
        "port": port,
        "version": env!("CARGO_PKG_VERSION"),
    })
}

#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    app.exit(0);
}

#[tauri::command]
async fn click_at(x: i32, y: i32, button: Option<String>) -> Result<(), String> {
    let btn = match button.as_deref() {
        Some("right") => input::MouseButton::Right,
        Some("middle") => input::MouseButton::Middle,
        _ => input::MouseButton::Left,
    };
    tokio::task::spawn_blocking(move || input::mouse_click(Some(x), Some(y), btn, 1))
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())
}

#[tauri::command]
async fn mouse_position() -> Result<(i32, i32), String> {
    tokio::task::spawn_blocking(input::mouse_location)
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())
}
