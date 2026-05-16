use serde::Serialize;
use std::io::Cursor;
use xcap::Monitor;

#[derive(Debug, thiserror::Error)]
pub enum ScreenError {
    #[error("xcap error: {0}")]
    Xcap(String),
    #[error("monitor {0} not found")]
    NotFound(usize),
    #[error("image encode error: {0}")]
    Encode(String),
}

pub type Result<T> = std::result::Result<T, ScreenError>;

fn monitors() -> Result<Vec<Monitor>> {
    Monitor::all().map_err(|e| ScreenError::Xcap(e.to_string()))
}

#[derive(Debug, Serialize)]
pub struct MonitorInfo {
    pub index: usize,
    pub name: String,
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
    pub is_primary: bool,
    pub scale_factor: f32,
}

pub fn list_monitors() -> Result<Vec<MonitorInfo>> {
    let mons = monitors()?;
    let mut out = Vec::with_capacity(mons.len());
    for (i, m) in mons.iter().enumerate() {
        out.push(MonitorInfo {
            index: i,
            name: m.name().map(|s| s.to_string()).unwrap_or_default(),
            x: m.x().unwrap_or(0),
            y: m.y().unwrap_or(0),
            width: m.width().unwrap_or(0),
            height: m.height().unwrap_or(0),
            is_primary: m.is_primary().unwrap_or(false),
            scale_factor: m.scale_factor().unwrap_or(1.0),
        });
    }
    Ok(out)
}

pub struct Screenshot {
    pub png: Vec<u8>,
    pub width: u32,
    pub height: u32,
}

pub fn screenshot(index: usize) -> Result<Screenshot> {
    let mons = monitors()?;
    let m = mons.get(index).ok_or(ScreenError::NotFound(index))?;
    let image = m
        .capture_image()
        .map_err(|e| ScreenError::Xcap(e.to_string()))?;
    let width = image.width();
    let height = image.height();
    let dynimg = image::DynamicImage::ImageRgba8(image);
    let mut buf: Vec<u8> = Vec::new();
    dynimg
        .write_to(&mut Cursor::new(&mut buf), image::ImageFormat::Png)
        .map_err(|e| ScreenError::Encode(e.to_string()))?;
    Ok(Screenshot {
        png: buf,
        width,
        height,
    })
}
