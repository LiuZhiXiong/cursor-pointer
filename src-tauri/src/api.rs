use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use base64::Engine;
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::net::SocketAddr;
use std::sync::Arc;
use std::sync::Mutex;
use tokio::net::TcpListener;
use tower_http::cors::{Any, CorsLayer};

use crate::input::{self, MouseButton};
use crate::screen;

const FX_BUFFER_MAX: usize = 200;

#[derive(Clone, Debug, Serialize)]
pub struct FxEvent {
    pub id: u64,
    pub kind: &'static str, // "click" | "move" | "key"
    #[serde(skip_serializing_if = "Option::is_none")]
    pub x: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub y: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub button: Option<&'static str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub key: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub modifiers: Option<Vec<String>>,
}

pub struct FxQueue {
    next_id: Mutex<u64>,
    events: Mutex<VecDeque<FxEvent>>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct OcrBox {
    pub id: u32,
    pub x: i32,        // logical screen pixels
    pub y: i32,
    pub w: i32,
    pub h: i32,
    pub text: String,
    #[serde(default)]
    pub score: f32,
    /// 1 = gold (all 3 sources), 2 = silver (AX+OCR), 3 = single AX, 4 = single OCR
    #[serde(default = "default_tier")]
    pub tier: u8,
}

fn default_tier() -> u8 {
    3
}

pub struct OcrState {
    pub enabled: Mutex<bool>,
    pub boxes: Mutex<Vec<OcrBox>>,
}

impl OcrState {
    pub fn new() -> Self {
        Self {
            enabled: Mutex::new(false),
            boxes: Mutex::new(Vec::new()),
        }
    }
}

impl FxQueue {
    pub fn new() -> Self {
        Self {
            next_id: Mutex::new(1),
            events: Mutex::new(VecDeque::with_capacity(FX_BUFFER_MAX)),
        }
    }

    fn push(&self, mut e: FxEvent) {
        let mut id = self.next_id.lock().unwrap();
        e.id = *id;
        *id += 1;
        let mut q = self.events.lock().unwrap();
        if q.len() >= FX_BUFFER_MAX {
            q.pop_front();
        }
        q.push_back(e);
    }

    fn since(&self, since: u64) -> Vec<FxEvent> {
        let q = self.events.lock().unwrap();
        q.iter().filter(|e| e.id > since).cloned().collect()
    }
}

#[derive(Clone)]
pub struct AppState {
    pub version: String,
    pub fx: Arc<FxQueue>,
    pub ocr: Arc<OcrState>,
    pub app: tauri::AppHandle,
}

impl AppState {
    fn push_click(&self, x: i32, y: i32, btn: &'static str) {
        self.fx.push(FxEvent {
            id: 0,
            kind: "click",
            x: Some(x),
            y: Some(y),
            button: Some(btn),
            key: None,
            modifiers: None,
        });
    }
    fn push_move(&self, x: i32, y: i32) {
        self.fx.push(FxEvent {
            id: 0,
            kind: "move",
            x: Some(x),
            y: Some(y),
            button: None,
            key: None,
            modifiers: None,
        });
    }
    fn push_key(&self, key: &str, modifiers: &[String]) {
        self.fx.push(FxEvent {
            id: 0,
            kind: "key",
            x: None,
            y: None,
            button: None,
            key: Some(key.to_string()),
            modifiers: Some(modifiers.to_vec()),
        });
    }
}

#[derive(Debug, Serialize)]
pub struct ApiError {
    pub error: String,
}

fn err<S: Into<String>>(code: StatusCode, msg: S) -> (StatusCode, Json<ApiError>) {
    (code, Json(ApiError { error: msg.into() }))
}

fn bad(msg: impl Into<String>) -> (StatusCode, Json<ApiError>) {
    err(StatusCode::BAD_REQUEST, msg)
}

fn internal(msg: impl Into<String>) -> (StatusCode, Json<ApiError>) {
    err(StatusCode::INTERNAL_SERVER_ERROR, msg)
}

type ApiResult<T> = std::result::Result<Json<T>, (StatusCode, Json<ApiError>)>;

async fn run_blocking_input<F, T>(f: F) -> std::result::Result<T, (StatusCode, Json<ApiError>)>
where
    F: FnOnce() -> input::Result<T> + Send + 'static,
    T: Send + 'static,
{
    tokio::task::spawn_blocking(f)
        .await
        .map_err(|e| internal(format!("join error: {}", e)))?
        .map_err(|e| bad(e.to_string()))
}

async fn run_blocking_screen<F, T>(f: F) -> std::result::Result<T, (StatusCode, Json<ApiError>)>
where
    F: FnOnce() -> screen::Result<T> + Send + 'static,
    T: Send + 'static,
{
    tokio::task::spawn_blocking(f)
        .await
        .map_err(|e| internal(format!("join error: {}", e)))?
        .map_err(|e| internal(e.to_string()))
}

#[derive(Serialize)]
struct Health {
    ok: bool,
    name: &'static str,
    version: String,
}

async fn health(State(s): State<Arc<AppState>>) -> Json<Health> {
    Json(Health {
        ok: true,
        name: "cursor-pointer",
        version: s.version.clone(),
    })
}

#[derive(Deserialize)]
struct MoveReq {
    x: i32,
    y: i32,
}

async fn mouse_move(
    State(s): State<Arc<AppState>>,
    Json(b): Json<MoveReq>,
) -> ApiResult<serde_json::Value> {
    run_blocking_input(move || input::mouse_move(b.x, b.y)).await?;
    s.push_move(b.x, b.y);
    Ok(Json(serde_json::json!({ "ok": true })))
}

#[derive(Deserialize)]
struct ClickReq {
    x: Option<i32>,
    y: Option<i32>,
    button: Option<MouseButton>,
    count: Option<u32>,
}

async fn mouse_click(
    State(s): State<Arc<AppState>>,
    Json(b): Json<ClickReq>,
) -> ApiResult<serde_json::Value> {
    let btn = b.button.unwrap_or(MouseButton::Left);
    let cnt = b.count.unwrap_or(1);
    let x = b.x;
    let y = b.y;
    run_blocking_input(move || input::mouse_click(x, y, btn, cnt)).await?;
    // The position used for the click is either the explicit x,y or the
    // current cursor. Read it back to label the fx accurately.
    let (fx_x, fx_y) = if let (Some(x), Some(y)) = (b.x, b.y) {
        (x, y)
    } else {
        run_blocking_input(input::mouse_location)
            .await
            .unwrap_or((0, 0))
    };
    let btn_name = match btn {
        MouseButton::Left => "left",
        MouseButton::Right => "right",
        MouseButton::Middle => "middle",
    };
    for _ in 0..cnt.max(1) {
        s.push_click(fx_x, fx_y, btn_name);
    }
    Ok(Json(serde_json::json!({ "ok": true })))
}

#[derive(Deserialize)]
struct ButtonReq {
    button: Option<MouseButton>,
}

async fn mouse_down(Json(b): Json<ButtonReq>) -> ApiResult<serde_json::Value> {
    let btn = b.button.unwrap_or(MouseButton::Left);
    run_blocking_input(move || input::mouse_button(btn, true)).await?;
    Ok(Json(serde_json::json!({ "ok": true })))
}

async fn mouse_up(Json(b): Json<ButtonReq>) -> ApiResult<serde_json::Value> {
    let btn = b.button.unwrap_or(MouseButton::Left);
    run_blocking_input(move || input::mouse_button(btn, false)).await?;
    Ok(Json(serde_json::json!({ "ok": true })))
}

#[derive(Deserialize)]
struct ScrollReq {
    dx: Option<i32>,
    dy: Option<i32>,
    x: Option<i32>,
    y: Option<i32>,
}

async fn mouse_scroll(Json(b): Json<ScrollReq>) -> ApiResult<serde_json::Value> {
    run_blocking_input(move || {
        input::mouse_scroll(b.dx.unwrap_or(0), b.dy.unwrap_or(0), b.x, b.y)
    })
    .await?;
    Ok(Json(serde_json::json!({ "ok": true })))
}

async fn mouse_position() -> ApiResult<serde_json::Value> {
    let (x, y) = run_blocking_input(input::mouse_location).await?;
    Ok(Json(serde_json::json!({ "x": x, "y": y })))
}

#[derive(Deserialize)]
struct TypeReq {
    text: String,
}

async fn type_text(Json(b): Json<TypeReq>) -> ApiResult<serde_json::Value> {
    run_blocking_input(move || input::type_text(&b.text)).await?;
    Ok(Json(serde_json::json!({ "ok": true })))
}

#[derive(Deserialize)]
struct KeyReq {
    key: String,
    #[serde(default)]
    modifiers: Vec<String>,
}

async fn key_press(
    State(s): State<Arc<AppState>>,
    Json(b): Json<KeyReq>,
) -> ApiResult<serde_json::Value> {
    let key = b.key.clone();
    let mods = b.modifiers.clone();
    run_blocking_input(move || input::key_press(&b.key, &b.modifiers)).await?;
    s.push_key(&key, &mods);
    Ok(Json(serde_json::json!({ "ok": true })))
}

#[derive(Deserialize)]
struct KeyToggleReq {
    key: String,
}

async fn key_down(Json(b): Json<KeyToggleReq>) -> ApiResult<serde_json::Value> {
    run_blocking_input(move || input::key_toggle(&b.key, true)).await?;
    Ok(Json(serde_json::json!({ "ok": true })))
}

async fn key_up(Json(b): Json<KeyToggleReq>) -> ApiResult<serde_json::Value> {
    run_blocking_input(move || input::key_toggle(&b.key, false)).await?;
    Ok(Json(serde_json::json!({ "ok": true })))
}

#[derive(Deserialize)]
struct ScreenshotQ {
    monitor: Option<usize>,
    format: Option<String>,
}

async fn screenshot(Query(q): Query<ScreenshotQ>) -> impl IntoResponse {
    let idx = q.monitor.unwrap_or(0);
    let want_raw = matches!(q.format.as_deref(), Some("png") | Some("raw"));
    let shot = match run_blocking_screen(move || screen::screenshot(idx)).await {
        Ok(s) => s,
        Err(e) => return e.into_response(),
    };
    if want_raw {
        (
            [(axum::http::header::CONTENT_TYPE, "image/png")],
            shot.png,
        )
            .into_response()
    } else {
        let b64 = base64::engine::general_purpose::STANDARD.encode(&shot.png);
        Json(serde_json::json!({
            "width": shot.width,
            "height": shot.height,
            "image": format!("data:image/png;base64,{}", b64),
        }))
        .into_response()
    }
}

#[derive(Deserialize)]
struct FxNextQ {
    since: Option<u64>,
}

async fn fx_next(
    State(s): State<Arc<AppState>>,
    Query(q): Query<FxNextQ>,
) -> Json<serde_json::Value> {
    let since = q.since.unwrap_or(0);
    let events = s.fx.since(since);
    Json(serde_json::json!({ "events": events }))
}

async fn window_minimize(State(s): State<Arc<AppState>>) -> Json<serde_json::Value> {
    use tauri::Manager;
    if let Some(w) = s.app.get_webview_window("control") {
        let _ = w.minimize();
    }
    Json(serde_json::json!({ "ok": true }))
}

async fn window_compact(State(s): State<Arc<AppState>>) -> Json<serde_json::Value> {
    use tauri::Manager;
    if let Some(w) = s.app.get_webview_window("control") {
        // Compute bottom-right anchor in logical pixels.
        let (mx, my, mw, mh, sf) = match w.primary_monitor() {
            Ok(Some(mon)) => {
                let sf = mon.scale_factor();
                let pos = *mon.position();
                let size = *mon.size();
                (
                    pos.x as f64 / sf,
                    pos.y as f64 / sf,
                    size.width as f64 / sf,
                    size.height as f64 / sf,
                    sf,
                )
            }
            _ => (0.0, 0.0, 1920.0, 1080.0, 2.0),
        };
        let _ = sf;
        let w_size = 160.0;
        let h_size = 48.0;
        let margin_x = 16.0;
        // Stay clear of the Dock at the bottom (typical Dock ≈ 80 logical px).
        let margin_y = 96.0;
        let x = mx + mw - w_size - margin_x;
        let y = my + mh - h_size - margin_y;
        let _ = w.set_size(tauri::Size::Logical(tauri::LogicalSize::new(w_size, h_size)));
        let _ = w.set_position(tauri::Position::Logical(tauri::LogicalPosition::new(x, y)));
        let _ = w.eval("document.body.classList.add('compact')");
    }
    Json(serde_json::json!({ "ok": true }))
}

async fn window_expand(State(s): State<Arc<AppState>>) -> Json<serde_json::Value> {
    use tauri::Manager;
    if let Some(w) = s.app.get_webview_window("control") {
        let (mx, my, mw, mh) = match w.primary_monitor() {
            Ok(Some(mon)) => {
                let sf = mon.scale_factor();
                let pos = *mon.position();
                let size = *mon.size();
                (
                    pos.x as f64 / sf,
                    pos.y as f64 / sf,
                    size.width as f64 / sf,
                    size.height as f64 / sf,
                )
            }
            _ => (0.0, 0.0, 1920.0, 1080.0),
        };
        let w_size = 320.0;
        let h_size = 220.0;
        // Restore to centred-ish (upper third) so it doesn't jump back to corner
        let x = mx + (mw - w_size) / 2.0;
        let y = my + (mh - h_size) / 3.0;
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_size(tauri::Size::Logical(tauri::LogicalSize::new(w_size, h_size)));
        let _ = w.set_position(tauri::Position::Logical(tauri::LogicalPosition::new(x, y)));
        let _ = w.set_focus();
        let _ = w.eval("document.body.classList.remove('compact')");
    }
    Json(serde_json::json!({ "ok": true }))
}

// ----- OCR overlay ---------------------------------------------------------

#[derive(Deserialize)]
struct OcrBoxesIn {
    boxes: Vec<OcrBox>,
    #[serde(default = "default_enable_true")]
    enable: bool,
}
fn default_enable_true() -> bool {
    true
}

async fn ocr_get(State(s): State<Arc<AppState>>) -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "enabled": *s.ocr.enabled.lock().unwrap(),
        "boxes": s.ocr.boxes.lock().unwrap().clone(),
    }))
}

async fn ocr_set(
    State(s): State<Arc<AppState>>,
    Json(b): Json<OcrBoxesIn>,
) -> Json<serde_json::Value> {
    *s.ocr.boxes.lock().unwrap() = b.boxes;
    *s.ocr.enabled.lock().unwrap() = b.enable;
    Json(serde_json::json!({ "ok": true }))
}

async fn ocr_clear(State(s): State<Arc<AppState>>) -> Json<serde_json::Value> {
    s.ocr.boxes.lock().unwrap().clear();
    *s.ocr.enabled.lock().unwrap() = false;
    Json(serde_json::json!({ "ok": true }))
}

async fn ocr_toggle(State(s): State<Arc<AppState>>) -> Json<serde_json::Value> {
    let mut en = s.ocr.enabled.lock().unwrap();
    *en = !*en;
    Json(serde_json::json!({ "enabled": *en }))
}

/// Fire off the bundled Python OCR helper.
/// It does the screenshot → OCR → POST /ocr/boxes round-trip itself.
async fn ocr_run() -> Json<serde_json::Value> {
    let venv_py = "/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/python";
    let script = "/Users/liuzhixiong/coding-project/cursor-pointer/python-client/tools/run_ocr.py";
    tokio::spawn(async move {
        let _ = tokio::process::Command::new(venv_py)
            .arg(script)
            .spawn();
    });
    Json(serde_json::json!({ "started": true }))
}

async fn window_quit(State(s): State<Arc<AppState>>) -> Json<serde_json::Value> {
    let app = s.app.clone();
    tokio::spawn(async move {
        tokio::time::sleep(std::time::Duration::from_millis(50)).await;
        app.exit(0);
    });
    Json(serde_json::json!({ "ok": true }))
}

async fn list_monitors() -> ApiResult<Vec<screen::MonitorInfo>> {
    let mons = run_blocking_screen(screen::list_monitors).await?;
    Ok(Json(mons))
}

/// Shell out to macOS native `screencapture` — diagnostic to compare with xcap.
async fn screencapture_native() -> impl IntoResponse {
    let path = "/tmp/native_screencapture.png";
    let out = tokio::task::spawn_blocking(move || {
        // -x silent  -C include cursor  -t png
        std::process::Command::new("/usr/sbin/screencapture")
            .args(["-x", "-C", "-t", "png", path])
            .output()
    })
    .await;
    match out {
        Ok(Ok(o)) if o.status.success() => match std::fs::read(path) {
            Ok(bytes) => (
                [(axum::http::header::CONTENT_TYPE, "image/png")],
                bytes,
            )
                .into_response(),
            Err(e) => internal(format!("read png failed: {}", e)).into_response(),
        },
        Ok(Ok(o)) => internal(format!(
            "screencapture failed: {}",
            String::from_utf8_lossy(&o.stderr)
        ))
        .into_response(),
        Ok(Err(e)) => internal(format!("exec error: {}", e)).into_response(),
        Err(e) => internal(format!("join error: {}", e)).into_response(),
    }
}

pub async fn serve(state: Arc<AppState>, port: u16) -> anyhow::Result<()> {
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);
    let app = Router::new()
        .route("/health", get(health))
        .route("/mouse/move", post(mouse_move))
        .route("/mouse/click", post(mouse_click))
        .route("/mouse/down", post(mouse_down))
        .route("/mouse/up", post(mouse_up))
        .route("/mouse/scroll", post(mouse_scroll))
        .route("/mouse/position", get(mouse_position))
        .route("/keyboard/type", post(type_text))
        .route("/keyboard/key", post(key_press))
        .route("/keyboard/down", post(key_down))
        .route("/keyboard/up", post(key_up))
        .route("/screen/screenshot", get(screenshot))
        .route("/screen/screenshot_native", get(screencapture_native))
        .route("/screen/monitors", get(list_monitors))
        .route("/_fx/next", get(fx_next))
        .route("/_window/minimize", post(window_minimize))
        .route("/_window/compact", post(window_compact))
        .route("/_window/expand", post(window_expand))
        .route("/_window/quit", post(window_quit))
        .route("/ocr/boxes", get(ocr_get).post(ocr_set))
        .route("/ocr/clear", post(ocr_clear))
        .route("/ocr/toggle", post(ocr_toggle))
        .route("/ocr/run", post(ocr_run))
        .layer(cors)
        .with_state(state);

    let addr: SocketAddr = format!("127.0.0.1:{}", port).parse()?;
    let listener = TcpListener::bind(addr).await?;
    tracing::info!("cursor-pointer HTTP API listening on http://{}", addr);
    axum::serve(listener, app).await?;
    Ok(())
}
