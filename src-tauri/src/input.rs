use enigo::{Axis, Button, Coordinate, Direction, Enigo, Key, Keyboard, Mouse, Settings};
use serde::Deserialize;

#[derive(Debug, thiserror::Error)]
pub enum InputError {
    #[error("enigo init failed: {0}")]
    Init(String),
    #[error("input error: {0}")]
    Op(String),
    #[error("unknown key: {0}")]
    UnknownKey(String),
}

pub type Result<T> = std::result::Result<T, InputError>;

fn enigo() -> Result<Enigo> {
    Enigo::new(&Settings::default()).map_err(|e| InputError::Init(e.to_string()))
}

#[derive(Debug, Deserialize, Clone, Copy)]
#[serde(rename_all = "lowercase")]
pub enum MouseButton {
    Left,
    Right,
    Middle,
}

impl From<MouseButton> for Button {
    fn from(b: MouseButton) -> Self {
        match b {
            MouseButton::Left => Button::Left,
            MouseButton::Right => Button::Right,
            MouseButton::Middle => Button::Middle,
        }
    }
}

pub fn mouse_move(x: i32, y: i32) -> Result<()> {
    let mut e = enigo()?;
    e.move_mouse(x, y, Coordinate::Abs)
        .map_err(|err| InputError::Op(err.to_string()))
}

pub fn mouse_click(x: Option<i32>, y: Option<i32>, button: MouseButton, count: u32) -> Result<()> {
    let mut e = enigo()?;
    if let (Some(x), Some(y)) = (x, y) {
        e.move_mouse(x, y, Coordinate::Abs)
            .map_err(|err| InputError::Op(err.to_string()))?;
        // enigo's button() reads `NSEvent.mouseLocation()` to determine the
        // click event's CGPoint. After `CGWarpMouseCursorPosition` (used by
        // move_mouse), that NS-side mouseLocation lags by ~a frame, so without
        // this sync the click event is created at the *previous* cursor
        // position. Spin briefly until location() reflects the requested
        // target (up to 50ms).
        let deadline = std::time::Instant::now() + std::time::Duration::from_millis(50);
        loop {
            match e.location() {
                Ok((lx, ly)) if lx == x && ly == y => break,
                _ if std::time::Instant::now() >= deadline => break,
                _ => std::thread::sleep(std::time::Duration::from_micros(500)),
            }
        }
    }
    let n = count.max(1);
    for _ in 0..n {
        e.button(button.into(), Direction::Click)
            .map_err(|err| InputError::Op(err.to_string()))?;
    }
    Ok(())
}

pub fn mouse_button(button: MouseButton, press: bool) -> Result<()> {
    let mut e = enigo()?;
    let dir = if press { Direction::Press } else { Direction::Release };
    e.button(button.into(), dir)
        .map_err(|err| InputError::Op(err.to_string()))
}

pub fn mouse_scroll(dx: i32, dy: i32, x: Option<i32>, y: Option<i32>) -> Result<()> {
    let mut e = enigo()?;
    if let (Some(x), Some(y)) = (x, y) {
        e.move_mouse(x, y, Coordinate::Abs)
            .map_err(|err| InputError::Op(err.to_string()))?;
    }
    if dx != 0 {
        e.scroll(dx, Axis::Horizontal)
            .map_err(|err| InputError::Op(err.to_string()))?;
    }
    if dy != 0 {
        e.scroll(dy, Axis::Vertical)
            .map_err(|err| InputError::Op(err.to_string()))?;
    }
    Ok(())
}

pub fn mouse_location() -> Result<(i32, i32)> {
    let e = enigo()?;
    e.location()
        .map_err(|err| InputError::Op(err.to_string()))
}

pub fn type_text(text: &str) -> Result<()> {
    let mut e = enigo()?;
    e.text(text).map_err(|err| InputError::Op(err.to_string()))
}

pub fn key_press(key: &str, modifiers: &[String]) -> Result<()> {
    let mut e = enigo()?;
    let mod_keys: Vec<Key> = modifiers
        .iter()
        .filter_map(|m| parse_key(m))
        .collect();
    for m in &mod_keys {
        e.key(*m, Direction::Press)
            .map_err(|err| InputError::Op(err.to_string()))?;
    }
    let k = parse_key(key).ok_or_else(|| InputError::UnknownKey(key.to_string()))?;
    let res = e
        .key(k, Direction::Click)
        .map_err(|err| InputError::Op(err.to_string()));
    for m in mod_keys.iter().rev() {
        let _ = e.key(*m, Direction::Release);
    }
    res
}

pub fn key_toggle(key: &str, press: bool) -> Result<()> {
    let mut e = enigo()?;
    let k = parse_key(key).ok_or_else(|| InputError::UnknownKey(key.to_string()))?;
    let dir = if press { Direction::Press } else { Direction::Release };
    e.key(k, dir).map_err(|err| InputError::Op(err.to_string()))
}

pub fn clipboard_get() -> Result<String> {
    let out = std::process::Command::new("/usr/bin/pbpaste")
        .output()
        .map_err(|e| InputError::Op(format!("pbpaste spawn: {}", e)))?;
    if !out.status.success() {
        return Err(InputError::Op(format!(
            "pbpaste exited {}: {}",
            out.status,
            String::from_utf8_lossy(&out.stderr).trim()
        )));
    }
    Ok(String::from_utf8_lossy(&out.stdout).to_string())
}

pub fn clipboard_set(text: &str) -> Result<()> {
    use std::io::Write;
    let mut child = std::process::Command::new("/usr/bin/pbcopy")
        .stdin(std::process::Stdio::piped())
        .spawn()
        .map_err(|e| InputError::Op(format!("pbcopy spawn: {}", e)))?;
    child
        .stdin
        .as_mut()
        .ok_or_else(|| InputError::Op("pbcopy stdin missing".into()))?
        .write_all(text.as_bytes())
        .map_err(|e| InputError::Op(format!("pbcopy write: {}", e)))?;
    let status = child
        .wait()
        .map_err(|e| InputError::Op(format!("pbcopy wait: {}", e)))?;
    if !status.success() {
        return Err(InputError::Op(format!("pbcopy exited {}", status)));
    }
    Ok(())
}

/// Parse a key name to enigo's `Key`.
///
/// Important: on macOS, `Key::Unicode(c)` resolves the character to a virtual
/// keycode by calling Apple's TIS (Text Input Source) APIs. Those APIs are not
/// thread-safe and SIGTRAP the process when called from a tokio worker thread
/// (anything other than the main thread). To avoid this, we map ASCII keys to
/// fixed ANSI keycodes via `Key::Other(<keycode>)`, which bypasses TIS entirely.
fn parse_key(name: &str) -> Option<Key> {
    let n = name.to_lowercase();
    Some(match n.as_str() {
        "enter" | "return" => Key::Return,
        "tab" => Key::Tab,
        "space" => Key::Space,
        "backspace" => Key::Backspace,
        "delete" => Key::Delete,
        "escape" | "esc" => Key::Escape,
        "up" | "arrowup" => Key::UpArrow,
        "down" | "arrowdown" => Key::DownArrow,
        "left" | "arrowleft" => Key::LeftArrow,
        "right" | "arrowright" => Key::RightArrow,
        "home" => Key::Home,
        "end" => Key::End,
        "pageup" => Key::PageUp,
        "pagedown" => Key::PageDown,
        "shift" => Key::Shift,
        "control" | "ctrl" => Key::Control,
        "alt" | "option" => Key::Alt,
        "meta" | "cmd" | "command" | "super" => Key::Meta,
        "capslock" => Key::CapsLock,
        "f1" => Key::F1,
        "f2" => Key::F2,
        "f3" => Key::F3,
        "f4" => Key::F4,
        "f5" => Key::F5,
        "f6" => Key::F6,
        "f7" => Key::F7,
        "f8" => Key::F8,
        "f9" => Key::F9,
        "f10" => Key::F10,
        "f11" => Key::F11,
        "f12" => Key::F12,
        c if c.chars().count() == 1 => {
            let ch = c.chars().next().unwrap();
            single_char_key(ch)?
        }
        _ => return None,
    })
}

#[cfg(target_os = "macos")]
fn single_char_key(c: char) -> Option<Key> {
    ascii_to_keycode(c).map(|kc| Key::Other(kc as u32))
}

#[cfg(not(target_os = "macos"))]
fn single_char_key(c: char) -> Option<Key> {
    Some(Key::Unicode(c))
}

#[cfg(target_os = "macos")]
fn ascii_to_keycode(c: char) -> Option<u16> {
    Some(match c.to_ascii_lowercase() {
        'a' => 0x00, 's' => 0x01, 'd' => 0x02, 'f' => 0x03, 'h' => 0x04,
        'g' => 0x05, 'z' => 0x06, 'x' => 0x07, 'c' => 0x08, 'v' => 0x09,
        'b' => 0x0B, 'q' => 0x0C, 'w' => 0x0D, 'e' => 0x0E, 'r' => 0x0F,
        'y' => 0x10, 't' => 0x11,
        '1' => 0x12, '2' => 0x13, '3' => 0x14, '4' => 0x15,
        '6' => 0x16, '5' => 0x17, '=' => 0x18, '9' => 0x19,
        '7' => 0x1A, '-' => 0x1B, '8' => 0x1C, '0' => 0x1D,
        ']' => 0x1E, 'o' => 0x1F, 'u' => 0x20, '[' => 0x21,
        'i' => 0x22, 'p' => 0x23,
        'l' => 0x25, 'j' => 0x26, '\'' => 0x27, 'k' => 0x28,
        ';' => 0x29, '\\' => 0x2A, ',' => 0x2B, '/' => 0x2C,
        'n' => 0x2D, 'm' => 0x2E, '.' => 0x2F, '`' => 0x32,
        ' ' => 0x31,
        _ => return None,
    })
}

