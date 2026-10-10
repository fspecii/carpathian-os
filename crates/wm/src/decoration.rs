//! Anti-aliased window chrome, rendered in Rust and uploaded through X11.
use carpatic_wm::config::Config;
use fontdue::{Font, FontSettings};
use std::process::Command;
use tiny_skia::{Color, LineCap, Paint, PathBuilder, Pixmap, Rect, Stroke, Transform};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Button {
    Minimize,
    Maximize,
    Close,
}

#[derive(Clone, Debug)]
pub struct Hit {
    pub button: Button,
    pub left: i32,
    pub right: i32,
}

#[derive(Clone, Debug)]
pub enum BarAction {
    Tag(u32),
    Layout,
    Restore(u32),
    Power,
}
#[derive(Clone, Debug)]
pub struct BarHit {
    pub left: i32,
    pub right: i32,
    pub action: BarAction,
}

pub struct Icon(pub Pixmap);
impl Icon {
    pub fn from_argb(values: &[u32], wanted: u32) -> Option<Self> {
        let mut offset = 0;
        let mut best: Option<(u32, u32, &[u32], u32)> = None;
        while offset + 2 <= values.len() {
            let w = values[offset];
            let h = values[offset + 1];
            offset += 2;
            let count = w.checked_mul(h)? as usize;
            if w == 0 || h == 0 || count > values.len() - offset {
                return None;
            }
            let score = w.abs_diff(wanted) + h.abs_diff(wanted);
            if best.is_none_or(|b| score < b.3) {
                best = Some((w, h, &values[offset..offset + count], score));
            }
            offset += count;
        }
        let (w, h, pixels, _) = best?;
        let mut p = Pixmap::new(w, h)?;
        for (out, argb) in p.data_mut().chunks_exact_mut(4).zip(pixels) {
            let a = argb >> 24;
            out.copy_from_slice(&[
                ((argb >> 16 & 255) * a / 255) as u8,
                ((argb >> 8 & 255) * a / 255) as u8,
                ((argb & 255) * a / 255) as u8,
                a as u8,
            ]);
        }
        Some(Self(p))
    }
    fn draw(&self, p: &mut Pixmap, x: f32, y: f32, size: f32) {
        p.draw_pixmap(
            0,
            0,
            self.0.as_ref(),
            &tiny_skia::PixmapPaint {
                quality: tiny_skia::FilterQuality::Bilinear,
                ..Default::default()
            },
            Transform::from_scale(size / self.0.width() as f32, size / self.0.height() as f32)
                .post_translate(x, y),
            None,
        );
    }
}
#[derive(Clone, Copy)]
pub struct Label<'a> {
    pub text: &'a str,
    pub icon: Option<&'a Icon>,
}

pub struct Renderer {
    font: Option<Font>,
    pub font_size: f32,
}

fn color(rgb: u32) -> Color {
    Color::from_rgba8((rgb >> 16) as u8, (rgb >> 8) as u8, rgb as u8, 255)
}

fn fill(p: &mut Pixmap, x: f32, y: f32, w: f32, h: f32, rgb: u32) {
    if let Some(rect) = Rect::from_xywh(x, y, w, h) {
        let mut paint = Paint::default();
        paint.set_color(color(rgb));
        p.fill_rect(rect, &paint, Transform::identity(), None);
    }
}

fn circle(p: &mut Pixmap, x: f32, y: f32, radius: f32, rgb: u32, outline: bool) {
    if let Some(path) = PathBuilder::from_circle(x, y, radius) {
        let mut paint = Paint::default();
        paint.set_color(color(rgb));
        if outline {
            p.stroke_path(
                &path,
                &paint,
                &Stroke {
                    width: 1.5,
                    ..Stroke::default()
                },
                Transform::identity(),
                None,
            );
        } else {
            p.fill_path(
                &path,
                &paint,
                tiny_skia::FillRule::Winding,
                Transform::identity(),
                None,
            );
        }
    }
}

fn line(p: &mut Pixmap, x1: f32, y1: f32, x2: f32, y2: f32, rgb: u32, width: f32) {
    let mut path = PathBuilder::new();
    path.move_to(x1, y1);
    path.line_to(x2, y2);
    let mut paint = Paint::default();
    paint.set_color(color(rgb));
    p.stroke_path(
        &path.finish().unwrap(),
        &paint,
        &Stroke {
            width,
            line_cap: LineCap::Round,
            ..Stroke::default()
        },
        Transform::identity(),
        None,
    );
}

fn blend(bg: u32, fg: u32, alpha: f32) -> u32 {
    [16, 8, 0].into_iter().fold(0, |rgb, shift| {
        rgb | ((((bg >> shift & 255) as f32 * (1.0 - alpha) + (fg >> shift & 255) as f32 * alpha)
            .round() as u32)
            << shift)
    })
}

/// Horizontal colour ramp, one blended column at a time.
fn hgrad(p: &mut Pixmap, x: f32, y: f32, w: f32, h: f32, left: u32, right: u32) {
    if w <= 0.0 || h <= 0.0 {
        return;
    }
    for i in 0..w.max(1.0) as i32 {
        let t = i as f32 / (w - 1.0).max(1.0);
        fill(p, x + i as f32, y, 1.0, h, blend(left, right, t));
    }
}

/// Vertical colour ramp, one blended row at a time.
fn vgrad(p: &mut Pixmap, x: f32, y: f32, w: f32, h: f32, top: u32, bottom: u32) {
    if w <= 0.0 || h <= 0.0 {
        return;
    }
    for i in 0..h.max(1.0) as i32 {
        let t = i as f32 / (h - 1.0).max(1.0);
        fill(p, x, y + i as f32, w, 1.0, blend(top, bottom, t));
    }
}

/// A gel plate: squared corners, a vertical gradient body, a gloss line under
/// the top edge and a light rim, all solid fills (no compositor needed).
#[allow(clippy::too_many_arguments)]
fn gel(p: &mut Pixmap, x: f32, y: f32, w: f32, h: f32, r: f32, top: u32, bottom: u32, rim: u32) {
    // Whole-pixel geometry: tiny-skia's debug rasterizer rejects 1 px fills
    // with a fractional origin (their interior width collapses to zero).
    let (x, y, w, h) = (x.round(), y.round(), w.round(), h.round());
    let r = r.min(w / 2.0).min(h / 2.0).max(0.0);
    for row in 0..h.max(1.0) as i32 {
        let mid = row as f32 + 0.5;
        let mut inset = 0.0;
        if mid < r {
            inset = r - (r * r - (r - mid) * (r - mid)).max(0.0).sqrt();
        } else if mid > h - r {
            inset = r - (r * r - (mid - (h - r)) * (mid - (h - r))).max(0.0).sqrt();
        }
        let t = row as f32 / (h - 1.0).max(1.0);
        let span = (w - 2.0 * inset).max(0.0);
        if span >= 1.0 {
            fill(
                p,
                x + inset,
                y + row as f32,
                span,
                1.0,
                blend(top, bottom, t),
            );
        }
    }
    fill(
        p,
        x + r.ceil(),
        y + 1.0,
        (w - 2.0 * r.ceil()).max(0.0),
        1.0,
        blend(top, 0xffffff, 0.45),
    );
    plate(p, x, y, w, h, r, rim, 1.2);
}
fn metrics(style: &str) -> (f32, f32, f32, f32, bool) {
    match style {
        "windows" => (46.0, 0.0, 0.0, 46.0, false),
        "macos" => (12.0, 8.0, 14.0, 12.0, true),
        "gnome" => (24.0, 6.0, 8.0, 24.0, true),
        "kde" => (24.0, 2.0, 6.0, 24.0, false),
        "minimal" => (10.0, 10.0, 14.0, 10.0, false),
        "ring" => (14.0, 9.0, 14.0, 14.0, false),
        "squircle" => (22.0, 6.0, 8.0, 22.0, false),
        "contrast" => (28.0, 6.0, 6.0, 28.0, false),
        "omarchy" => (12.0, 16.0, 14.0, 12.0, false),
        "kylin" => (30.0, 4.0, 4.0, 30.0, false),
        "nothing" => (24.0, 4.0, 10.0, 24.0, false),
        "classic98" => (18.0, 0.0, 3.0, 32.0, false),
        "luna" => (22.0, 2.0, 4.0, 32.0, false),
        _ => (0.0, 0.0, 0.0, 1.0, false),
    }
}
#[allow(clippy::too_many_arguments)]
fn plate(p: &mut Pixmap, x: f32, y: f32, w: f32, h: f32, r: f32, rgb: u32, stroke: f32) {
    let r = r.min(w / 2.0).min(h / 2.0).max(0.0);
    let mut path = PathBuilder::new();
    path.move_to(x + r, y);
    path.line_to(x + w - r, y);
    path.quad_to(x + w, y, x + w, y + r);
    path.line_to(x + w, y + h - r);
    path.quad_to(x + w, y + h, x + w - r, y + h);
    path.line_to(x + r, y + h);
    path.quad_to(x, y + h, x, y + h - r);
    path.line_to(x, y + r);
    path.quad_to(x, y, x + r, y);
    path.close();
    let mut paint = Paint::default();
    paint.set_color(color(rgb));
    if let Some(path) = path.finish() {
        if stroke > 0.0 {
            p.stroke_path(
                &path,
                &paint,
                &Stroke {
                    width: stroke,
                    ..Stroke::default()
                },
                Transform::identity(),
                None,
            );
        } else {
            p.fill_path(
                &path,
                &paint,
                tiny_skia::FillRule::Winding,
                Transform::identity(),
                None,
            );
        }
    }
}

impl Renderer {
    // Renderer inputs are explicit so X11 ownership stays in the WM.
    #[allow(clippy::too_many_arguments)]
    pub fn bar(
        &self,
        config: &Config,
        width: u32,
        height: u32,
        view: u32,
        occupied: u32,
        urgent: u32,
        layout: u8,
        title: Label<'_>,
        status: &str,
        minimized: &[(u32, String)],
        tray_width: u32,
    ) -> (Pixmap, Vec<BarHit>, i32) {
        let mut p = Pixmap::new(width.max(1), height.max(1)).unwrap();
        p.fill(color(config.inactive_background));
        let mut hits = Vec::new();
        let mut x = 0i32;
        let baseline = (height as f32 + self.font_size * 0.7) / 2.0;
        for index in 0..config.workspaces {
            let name = config
                .workspace_names
                .get(index as usize)
                .cloned()
                .unwrap_or_else(|| (index + 1).to_string());
            let text_width = self
                .font
                .as_ref()
                .map(|f| {
                    name.chars()
                        .map(|ch| f.metrics(ch, self.font_size).advance_width)
                        .sum::<f32>()
                })
                .unwrap_or(15.0);
            let size = (text_width + 20.0).max(height as f32) as i32;
            if view & (1 << index) != 0 {
                fill(
                    &mut p,
                    x as f32,
                    0.0,
                    size as f32,
                    height as f32,
                    config.background,
                );
            }
            self.text(
                &mut p,
                &name,
                x as f32 + 10.0,
                baseline,
                (x + size - 4) as f32,
                if urgent & (1 << index) != 0 {
                    config.red
                } else if view & (1 << index) != 0 {
                    config.foreground
                } else {
                    config.inactive_foreground
                },
            );
            if occupied & (1 << index) != 0 {
                fill(
                    &mut p,
                    x as f32 + 5.0,
                    height as f32 - 3.0,
                    (size - 10) as f32,
                    2.0,
                    config.border_active,
                );
            }
            hits.push(BarHit {
                left: x,
                right: x + size,
                action: BarAction::Tag(1 << index),
            });
            x += size;
        }
        let symbol = match layout {
            1 => "<>",
            2 => "[M]",
            _ => "[]=",
        };
        self.text(
            &mut p,
            symbol,
            x as f32 + 8.0,
            baseline,
            (x + 52) as f32,
            config.inactive_foreground,
        );
        hits.push(BarHit {
            left: x,
            right: x + 56,
            action: BarAction::Layout,
        });
        x += 56;
        let power_width = if config.power_button {
            height as i32
        } else {
            0
        };
        let status_width = self
            .font
            .as_ref()
            .map(|f| {
                status
                    .chars()
                    .map(|ch| f.metrics(ch, self.font_size).advance_width)
                    .sum::<f32>() as i32
                    + 20
            })
            .unwrap_or(0);
        let tray_x = (width as i32 - power_width - status_width - tray_width as i32).max(x);
        self.text(
            &mut p,
            status,
            (width as i32 - power_width - status_width + 10) as f32,
            baseline,
            (width as i32 - power_width - 6) as f32,
            config.inactive_foreground,
        );
        if config.power_button {
            let cx = width as f32 - height as f32 / 2.0;
            let cy = height as f32 / 2.0;
            circle(&mut p, cx, cy, 7.0, config.inactive_foreground, true);
            fill(
                &mut p,
                cx - 3.0,
                cy - 9.0,
                6.0,
                8.0,
                config.inactive_background,
            );
            line(
                &mut p,
                cx,
                cy - 9.0,
                cx,
                cy - 1.0,
                config.inactive_foreground,
                1.7,
            );
            hits.push(BarHit {
                left: width as i32 - power_width,
                right: width as i32,
                action: BarAction::Power,
            });
        }
        for (id, name) in minimized {
            if x + 110 >= tray_x {
                break;
            }
            fill(
                &mut p,
                x as f32 + 2.0,
                4.0,
                106.0,
                height as f32 - 8.0,
                config.background,
            );
            self.text(
                &mut p,
                name,
                x as f32 + 8.0,
                baseline,
                (x + 102) as f32,
                config.foreground,
            );
            hits.push(BarHit {
                left: x,
                right: x + 110,
                action: BarAction::Restore(*id),
            });
            x += 110;
        }
        let icon_size = (17.0 * config.scale as f32 / 100.0).min(height as f32 - 4.0);
        if let Some(icon) = title.icon {
            icon.draw(
                &mut p,
                x as f32 + 6.0,
                (height as f32 - icon_size) / 2.0,
                icon_size,
            );
            x += icon_size as i32 + 8;
        }
        self.text(
            &mut p,
            title.text,
            x as f32 + 10.0,
            baseline,
            (tray_x - 10) as f32,
            config.inactive_foreground,
        );
        (p, hits, tray_x)
    }
    pub fn new(config: &Config) -> Self {
        let path = Command::new("fc-match")
            .args(["-f", "%{file}", &config.font])
            .output()
            .ok()
            .filter(|o| o.status.success())
            .and_then(|o| String::from_utf8(o.stdout).ok());
        let font = path
            .and_then(|p| std::fs::read(p).ok())
            .and_then(|bytes| Font::from_bytes(bytes, FontSettings::default()).ok());
        Self {
            font,
            font_size: config
                .font
                .split(':')
                .find_map(|part| {
                    part.strip_prefix("size=")
                        .and_then(|s| s.parse::<f32>().ok())
                })
                .unwrap_or(10.0)
                .clamp(6.0, 48.0)
                * 96.0
                / 72.0
                * config.scale as f32
                / 100.0,
        }
    }

    pub fn height(&self, config: &Config) -> u32 {
        if config.titlebar.height > 0 {
            config.titlebar.height * config.scale / 100
        } else {
            (32 * config.scale / 100).max(20)
        }
    }

    pub fn hits(&self, config: &Config, width: u32, height: u32) -> Vec<Hit> {
        let tb = &config.titlebar;
        if !tb.buttons || tb.style == "none" {
            return Vec::new();
        }
        let left = tb.side == "left" || tb.side == "auto" && tb.style == "macos";
        let sequence = if !tb.order.is_empty() {
            tb.order
                .split(',')
                .filter_map(|s| match s.trim() {
                    "min" => Some(Button::Minimize),
                    "max" => Some(Button::Maximize),
                    "close" => Some(Button::Close),
                    _ => None,
                })
                .collect::<Vec<_>>()
        } else if tb.shown == "close" {
            vec![Button::Close]
        } else if left {
            vec![Button::Close, Button::Minimize, Button::Maximize]
        } else {
            vec![Button::Minimize, Button::Maximize, Button::Close]
        };
        let (cell, default_gap, margin, nominal, _) = metrics(&tb.style);
        let u = if tb.size > 0 {
            tb.size as f32 * config.scale as f32 / 100.0 / nominal
        } else {
            height as f32 / 32.0
        };
        let size = (cell * u).round().max(1.0) as i32;
        let gap = if tb.gap >= 0 {
            (tb.gap as f32 * config.scale as f32 / 100.0).round() as i32
        } else {
            (default_gap * u).round() as i32
        };
        let margin = (margin * u).round() as i32;
        let sequence: Vec<_> = sequence
            .into_iter()
            .filter(|button| tb.shown != "close" || *button == Button::Close)
            .collect();
        let total = size * sequence.len() as i32 + gap * sequence.len().saturating_sub(1) as i32;
        let start = if left {
            margin
        } else {
            (width as i32 - total - margin).max(0)
        };
        sequence
            .into_iter()
            .enumerate()
            .map(|(i, button)| {
                let left = start + i as i32 * (size + gap);
                Hit {
                    button,
                    left,
                    right: (left + size).min(width as i32),
                }
            })
            .collect()
    }

    pub fn text(&self, p: &mut Pixmap, text: &str, x: f32, baseline: f32, max_x: f32, rgb: u32) {
        let Some(font) = &self.font else {
            return;
        };
        let mut cursor = x;
        for ch in text.chars() {
            let (m, bitmap) = font.rasterize(ch, self.font_size);
            if cursor + m.advance_width > max_x {
                break;
            }
            let left = cursor as i32 + m.xmin;
            let top = baseline as i32 - m.height as i32 - m.ymin;
            for y in 0..m.height {
                for x in 0..m.width {
                    let px = left + x as i32;
                    let py = top + y as i32;
                    if px < 0 || py < 0 || px >= p.width() as i32 || py >= p.height() as i32 {
                        continue;
                    }
                    let a = u32::from(bitmap[y * m.width + x]);
                    if a == 0 {
                        continue;
                    }
                    let i = (py as usize * p.width() as usize + px as usize) * 4;
                    let data = p.data_mut();
                    for (channel, shift) in [16, 8, 0].into_iter().enumerate() {
                        data[i + channel] = (((rgb >> shift & 255) * a
                            + u32::from(data[i + channel]) * (255 - a))
                            / 255) as u8;
                    }
                    data[i + 3] = 255;
                }
            }
            cursor += m.advance_width;
        }
    }

    pub fn title(
        &self,
        config: &Config,
        width: u32,
        height: u32,
        title: Label<'_>,
        focused: bool,
        buttons: (Option<Button>, Option<Button>, bool),
    ) -> Pixmap {
        let (hover, pressed, maximized) = buttons;
        let mut p = Pixmap::new(width.max(1), height.max(1)).unwrap();
        let bg = if focused {
            config.background
        } else {
            config.inactive_background
        };
        let fg = if focused {
            config.foreground
        } else {
            config.inactive_foreground
        };
        p.fill(color(bg));
        // Era backdrops repaint the bar with the theme's selection colours;
        // the shared border strips and corner arcs below still frame them.
        match config.titlebar.style.as_str() {
            "classic98" => {
                let face = if focused {
                    0xc0c0c0
                } else {
                    blend(0xc0c0c0, 0x808080, 0.30)
                };
                fill(&mut p, 0.0, 0.0, width as f32, height as f32, face);
                let (left, right) = if focused {
                    (config.background, blend(config.background, 0xffffff, 0.35))
                } else {
                    (
                        blend(config.inactive_background, 0x000000, 0.25),
                        blend(config.inactive_background, 0xffffff, 0.25),
                    )
                };
                hgrad(
                    &mut p,
                    3.0,
                    3.0,
                    width as f32 - 6.0,
                    height as f32 - 5.0,
                    left,
                    right,
                );
            }
            "luna" => {
                let (top, bottom) = if focused {
                    (blend(bg, 0xffffff, 0.28), blend(bg, 0x000000, 0.16))
                } else {
                    (blend(bg, 0xffffff, 0.12), blend(bg, 0x000000, 0.06))
                };
                vgrad(&mut p, 0.0, 0.0, width as f32, height as f32, top, bottom);
                fill(
                    &mut p,
                    0.0,
                    0.0,
                    width as f32,
                    1.0,
                    blend(top, 0xffffff, 0.35),
                );
            }
            _ => {}
        }
        let edge = if focused {
            config.border_active
        } else {
            config.border_inactive
        };
        fill(&mut p, 0.0, 0.0, width as f32, config.border as f32, edge);
        fill(&mut p, 0.0, 0.0, config.border as f32, height as f32, edge);
        fill(
            &mut p,
            width.saturating_sub(config.border) as f32,
            0.0,
            config.border as f32,
            height as f32,
            edge,
        );
        // Follow the rounded shape with the border rather than ending the
        // horizontal/vertical strips before the corner's arc.
        let radius = config.radius.min(width / 2).min(height / 2);
        let inner_radius = radius.saturating_sub(config.border) as f32;
        for y in 0..radius {
            let dy = radius as f32 - y as f32 - 0.5;
            let outer = (radius as f32 - ((radius * radius) as f32 - dy * dy).sqrt()).ceil();
            let inner = if y < config.border || dy >= inner_radius {
                width as f32 / 2.0
            } else {
                radius as f32 - (inner_radius * inner_radius - dy * dy).sqrt()
            };
            fill(&mut p, outer, y as f32, (inner - outer).max(0.0), 1.0, edge);
            fill(
                &mut p,
                width as f32 - inner,
                y as f32,
                (inner - outer).max(0.0),
                1.0,
                edge,
            );
        }
        let hits = self.hits(config, width, height);
        let left_side = hits.first().is_some_and(|h| h.left < width as i32 / 2);
        let mut text_left = if left_side {
            hits.last().map(|h| h.right as f32 + 10.0).unwrap_or(12.0)
        } else {
            12.0
        };
        let text_right = if left_side {
            width as f32 - 12.0
        } else {
            hits.first()
                .map(|h| h.left as f32 - 10.0)
                .unwrap_or(width as f32 - 12.0)
        };
        let icon_size = (17.0 * config.scale as f32 / 100.0).min(height as f32 - 4.0);
        if let Some(icon) = title.icon {
            icon.draw(
                &mut p,
                text_left,
                (height as f32 - icon_size) / 2.0,
                icon_size,
            );
            text_left += icon_size + 8.0;
        }
        let center = config.titlebar.align == "center"
            || config.titlebar.align == "auto" && metrics(&config.titlebar.style).4;
        let text_width = self
            .font
            .as_ref()
            .map(|f| {
                title
                    .text
                    .chars()
                    .map(|c| f.metrics(c, self.font_size).advance_width)
                    .sum::<f32>()
            })
            .unwrap_or(0.0);
        let text_x = if center {
            ((width as f32 - text_width) / 2.0)
                .max(text_left)
                .min(text_right)
        } else {
            text_left
        };
        self.text(
            &mut p,
            title.text,
            text_x,
            (height as f32 + self.font_size * 0.7) / 2.0,
            text_right,
            fg,
        );
        for hit in hits {
            let cx = (hit.left + hit.right) as f32 / 2.0;
            let cy = height as f32 / 2.0;
            let style = config.titlebar.style.as_str();
            let (_, _, _, nominal, _) = metrics(style);
            let u = if config.titlebar.size > 0 {
                config.titlebar.size as f32 * config.scale as f32 / 100.0 / nominal
            } else {
                height as f32 / 32.0
            };
            let hovered = hover == Some(hit.button);
            let down = hovered && pressed == Some(hit.button);
            let high = hovered || down;
            let close = hit.button == Button::Close;
            let palette = match hit.button {
                Button::Close => config.red,
                Button::Minimize => config.yellow,
                Button::Maximize => config.green,
            };
            let foreground = blend(bg, fg, if focused { 1.0 } else { 0.6 });
            let mut ink = foreground;
            let mut g = 10.0 * u;
            let mut stroke = u.max(1.0);
            match style {
                "windows" => {
                    if high {
                        fill(
                            &mut p,
                            hit.left as f32,
                            config.border as f32,
                            (hit.right - hit.left) as f32,
                            height as f32 - config.border as f32,
                            if close {
                                blend(bg, palette, if down { 0.78 } else { 1.0 })
                            } else {
                                blend(bg, fg, if down { 0.16 } else { 0.10 })
                            },
                        );
                        if close {
                            ink = 0xffffff;
                        }
                    }
                }
                "macos" => {
                    let tint = if focused {
                        palette
                    } else {
                        config.border_inactive
                    };
                    circle(
                        &mut p,
                        cx,
                        cy,
                        6.0 * u,
                        if down { blend(tint, 0, 0.25) } else { tint },
                        false,
                    );
                    circle(&mut p, cx, cy, 5.6 * u, blend(tint, 0, 0.18), true);
                    if hover.is_none() {
                        continue;
                    }
                    ink = blend(tint, 0, 0.62);
                    g = if hit.button == Button::Maximize {
                        6.2 * u
                    } else {
                        5.6 * u
                    };
                    stroke = (1.15 * u).max(1.0);
                }
                "gnome" => {
                    circle(
                        &mut p,
                        cx,
                        cy,
                        12.0 * u,
                        blend(
                            bg,
                            if close && high { palette } else { fg },
                            if down {
                                if close {
                                    0.45
                                } else {
                                    0.22
                                }
                            } else if hovered {
                                if close {
                                    0.30
                                } else {
                                    0.14
                                }
                            } else {
                                0.07
                            },
                        ),
                        false,
                    );
                    g = 8.0 * u;
                    stroke = (1.6 * u).max(1.2);
                }
                "kde" => {
                    if high {
                        plate(
                            &mut p,
                            cx - 11.0 * u,
                            cy - 11.0 * u,
                            22.0 * u,
                            22.0 * u,
                            4.0 * u,
                            blend(
                                bg,
                                if close { palette } else { config.border_active },
                                if close {
                                    if down {
                                        1.0
                                    } else {
                                        0.88
                                    }
                                } else if down {
                                    0.38
                                } else {
                                    0.22
                                },
                            ),
                            0.0,
                        );
                        if close {
                            ink = 0xffffff;
                        }
                    }
                    stroke = (1.3 * u).max(1.0);
                }
                "minimal" => {
                    circle(
                        &mut p,
                        cx,
                        cy,
                        5.0 * u,
                        if high {
                            if down {
                                blend(palette, 0, 0.25)
                            } else {
                                palette
                            }
                        } else {
                            blend(bg, foreground, 0.55)
                        },
                        false,
                    );
                    continue;
                }
                "ring" => {
                    if high {
                        circle(
                            &mut p,
                            cx,
                            cy,
                            6.25 * u,
                            blend(bg, palette, if down { 0.6 } else { 0.3 }),
                            false,
                        );
                    }
                    circle(
                        &mut p,
                        cx,
                        cy,
                        6.25 * u,
                        if high {
                            palette
                        } else {
                            blend(bg, foreground, 0.6)
                        },
                        true,
                    );
                    continue;
                }
                "squircle" => {
                    plate(
                        &mut p,
                        cx - 11.0 * u,
                        cy - 11.0 * u,
                        22.0 * u,
                        22.0 * u,
                        7.0 * u,
                        blend(
                            bg,
                            if high {
                                if close {
                                    palette
                                } else {
                                    config.border_active
                                }
                            } else {
                                fg
                            },
                            if high {
                                if down {
                                    0.7
                                } else {
                                    0.92
                                }
                            } else {
                                0.10
                            },
                        ),
                        0.0,
                    );
                    if high {
                        ink = if close { 0xffffff } else { bg };
                    }
                    g = 9.0 * u;
                    stroke = (1.5 * u).max(1.1);
                }
                "contrast" => {
                    let col = if high {
                        blend(bg, fg, if down { 0.8 } else { 1.0 })
                    } else {
                        fg
                    };
                    plate(
                        &mut p,
                        cx - 14.0 * u,
                        cy - 14.0 * u,
                        28.0 * u,
                        28.0 * u,
                        3.0 * u,
                        col,
                        if high { 0.0 } else { (2.2 * u).max(1.5) },
                    );
                    if high {
                        ink = bg;
                    }
                    g = 12.0 * u;
                    stroke = (2.2 * u).max(1.5) * 1.1;
                }
                "omarchy" => {
                    ink = if high {
                        blend(
                            bg,
                            if close { palette } else { config.border_active },
                            if down { 0.7 } else { 1.0 },
                        )
                    } else {
                        blend(bg, foreground, 0.55)
                    };
                    g = 12.0 * u;
                    stroke = (1.4 * u).max(1.0);
                }
                "kylin" => {
                    if high {
                        plate(
                            &mut p,
                            cx - 14.0 * u,
                            cy - 14.0 * u,
                            28.0 * u,
                            28.0 * u,
                            6.0 * u,
                            if close {
                                if down {
                                    0xc21b24
                                } else {
                                    0xe7202b
                                }
                            } else {
                                blend(bg, fg, if down { 0.24 } else { 0.16 })
                            },
                            0.0,
                        );
                        if close {
                            ink = 0xffffff;
                        }
                    }
                    stroke = (1.1 * u).max(1.0);
                }
                "nothing" => {
                    plate(
                        &mut p,
                        cx - 9.0 * u,
                        cy - 9.0 * u,
                        18.0 * u,
                        18.0 * u,
                        0.0,
                        foreground,
                        u.max(1.0),
                    );
                    if high {
                        plate(
                            &mut p,
                            cx - 9.0 * u,
                            cy - 9.0 * u,
                            18.0 * u,
                            18.0 * u,
                            0.0,
                            blend(
                                bg,
                                if close { config.border_active } else { fg },
                                if close {
                                    if down {
                                        0.7
                                    } else {
                                        1.0
                                    }
                                } else if down {
                                    0.22
                                } else {
                                    0.12
                                },
                            ),
                            0.0,
                        );
                    }
                    for dy in -1..=1 {
                        for dx in -1..=1 {
                            let on = match hit.button {
                                Button::Minimize => dy == 1,
                                Button::Maximize => {
                                    if maximized {
                                        dx != 0 && dy != 0
                                    } else {
                                        dx != 0 || dy != 0
                                    }
                                }
                                Button::Close => (dx != 0 && dy != 0) || (dx == 0 && dy == 0),
                            };
                            if on {
                                circle(
                                    &mut p,
                                    cx + dx as f32 * 4.2 * u,
                                    cy + dy as f32 * 4.2 * u,
                                    (1.15 * u).max(0.9),
                                    if high && close { bg } else { foreground },
                                    false,
                                );
                            }
                        }
                    }
                    continue;
                }
                "classic98" => {
                    // Square beveled caption box; sunken when pressed, tinted
                    // toward the theme accent on hover. Whole-pixel geometry
                    // keeps the 1 px bevel fills away from tiny-skia's
                    // fractional-origin edge cases.
                    let side = (18.0 * u).round().max(6.0);
                    let bx = (cx - side / 2.0).round();
                    let by = (cy - side / 2.0).round();
                    let (face, light, dark) = if down {
                        (blend(0xc0c0c0, 0x000000, 0.15), 0x808080, 0xffffff)
                    } else if hovered {
                        (
                            blend(0xc0c0c0, config.border_active, 0.28),
                            0xffffff,
                            0x808080,
                        )
                    } else if focused {
                        (0xc0c0c0, 0xffffff, 0x808080)
                    } else {
                        (blend(0xc0c0c0, 0x808080, 0.30), 0xdfdfdf, 0x606060)
                    };
                    fill(&mut p, bx, by, side, side, face);
                    fill(&mut p, bx, by, side, 1.0, light);
                    fill(&mut p, bx, by, 1.0, side, light);
                    fill(&mut p, bx, by + side - 1.0, side, 1.0, dark);
                    fill(&mut p, bx + side - 1.0, by, 1.0, side, dark);
                    ink = if focused { 0x000000 } else { 0x808080 };
                    let w = (1.6 * u).max(1.1);
                    let s = side * 0.44;
                    let gx = cx - s / 2.0;
                    let gy = cy - s / 2.0;
                    match hit.button {
                        Button::Close => {
                            let r = s / 2.0 - w * 0.3;
                            line(&mut p, cx - r, cy - r, cx + r, cy + r, ink, w);
                            line(&mut p, cx - r, cy + r, cx + r, cy - r, ink, w);
                        }
                        Button::Minimize => {
                            // era underscore: short bar at the glyph bottom
                            let y = gy + s - w / 2.0;
                            line(&mut p, gx, y, gx + s * 0.75, y, ink, w);
                        }
                        Button::Maximize => {
                            let off = s * 0.30;
                            if maximized {
                                plate(&mut p, gx, gy + off, s - off, s - off, 0.0, ink, w);
                                line(&mut p, gx, gy + off, gx + s - off, gy + off, ink, w * 1.6);
                                line(&mut p, gx + off, gy, gx + s, gy, ink, w);
                                line(&mut p, gx + s, gy, gx + s, gy + s - off, ink, w);
                                line(&mut p, gx + off, gy, gx + off, gy + off, ink, w);
                            } else {
                                plate(&mut p, gx, gy, s, s, 0.0, ink, w);
                                line(&mut p, gx, gy, gx + s, gy, ink, w * 1.6);
                            }
                        }
                    }
                    continue;
                }
                "luna" => {
                    // gel plate: accent gradient for min/max, theme red for
                    // close; glyphs fall through to the shared shapes so the
                    // maximize/restore mapping stays identical.
                    let side = 22.0 * u;
                    let bx = cx - side / 2.0;
                    let by = cy - side / 2.0;
                    let accent = if focused {
                        config.background
                    } else {
                        config.inactive_background
                    };
                    let (top, bottom) = match hit.button {
                        Button::Close => (
                            blend(config.red, 0xffffff, 0.35),
                            blend(config.red, 0x000000, 0.18),
                        ),
                        _ => (blend(accent, 0xffffff, 0.35), blend(accent, 0x000000, 0.20)),
                    };
                    let wash = |c: u32| {
                        if focused {
                            c
                        } else {
                            blend(blend(c, 0x8e8e8e, 0.35), bg, 0.25)
                        }
                    };
                    let (top, bottom) = if down {
                        (
                            blend(wash(top), 0x000000, 0.18),
                            blend(wash(bottom), 0x000000, 0.32),
                        )
                    } else if hovered {
                        (
                            blend(wash(top), 0xffffff, 0.15),
                            blend(wash(bottom), 0xffffff, 0.08),
                        )
                    } else {
                        (wash(top), wash(bottom))
                    };
                    let rim = blend(top, 0xffffff, 0.75);
                    gel(&mut p, bx, by, side, side, 3.5 * u, top, bottom, rim);
                    ink = 0xffffff;
                    g = side * 0.42;
                    stroke = if close {
                        (2.1 * u).max(1.3)
                    } else {
                        (1.9 * u).max(1.2)
                    };
                }
                _ => {}
            }
            let r = g / 2.0;
            match hit.button {
                Button::Close => {
                    line(&mut p, cx - r, cy - r, cx + r, cy + r, ink, stroke);
                    line(&mut p, cx - r, cy + r, cx + r, cy - r, ink, stroke);
                }
                Button::Minimize => line(&mut p, cx - r, cy, cx + r, cy, ink, stroke),
                Button::Maximize if style == "macos" => {
                    line(&mut p, cx - r, cy + r, cx + r, cy - r, ink, stroke);
                    let off = g * 0.364;
                    line(&mut p, cx + r - off, cy - r, cx + r, cy - r, ink, stroke);
                    line(&mut p, cx + r, cy - r, cx + r, cy - r + off, ink, stroke);
                    line(&mut p, cx - r, cy + r - off, cx - r, cy + r, ink, stroke);
                    line(&mut p, cx - r, cy + r, cx - r + off, cy + r, ink, stroke);
                }
                Button::Maximize => {
                    if maximized {
                        let off = g * 0.28;
                        plate(
                            &mut p,
                            cx - r,
                            cy - r + off,
                            g - off,
                            g - off,
                            g * 0.1,
                            ink,
                            stroke,
                        );
                        line(&mut p, cx - r + off, cy - r, cx + r, cy - r, ink, stroke);
                        line(&mut p, cx + r, cy - r, cx + r, cy + r - off, ink, stroke);
                    } else {
                        plate(&mut p, cx - r, cy - r, g, g, g * 0.1, ink, stroke);
                    }
                }
            }
        }
        p
    }
}

#[cfg(test)]
mod render_tests {
    use super::*;
    #[test]
    fn rounded_titlebar_border_follows_both_arcs() {
        let mut config = Config {
            border: 2,
            radius: 10,
            ..Config::default()
        };
        config.titlebar.buttons = false;
        let renderer = Renderer::new(&config);
        let image = renderer.title(
            &config,
            200,
            36,
            Label {
                text: "",
                icon: None,
            },
            true,
            (None, None, false),
        );
        let edge = color(config.border_active).premultiply().to_color_u8();
        assert_eq!(image.pixel(3, 4).unwrap(), edge);
        assert_eq!(image.pixel(196, 4).unwrap(), edge);
        assert_eq!(
            image.pixel(10, 10).unwrap(),
            color(config.background).premultiply().to_color_u8()
        );
    }
    #[test]
    fn argb_icons_and_all_styles_are_distinct() {
        let icon = Icon::from_argb(&[1, 1, 0x80ff0000], 17).unwrap();
        assert_eq!(icon.0.data(), &[128, 0, 0, 128]);
        assert!(Icon::from_argb(&[100, 100, 0], 17).is_none());
        let styles = [
            "windows",
            "macos",
            "gnome",
            "kde",
            "minimal",
            "ring",
            "squircle",
            "contrast",
            "omarchy",
            "kylin",
            "nothing",
            "classic98",
            "luna",
            "none",
        ];
        for light in [false, true] {
            let mut config = Config::default();
            config.titlebar.enabled = true;
            if light {
                config.background = 0xffffff;
                config.foreground = 0x172029;
                config.inactive_background = 0xf5f7fa;
                config.inactive_foreground = 0x4e5b6c;
            }
            let renderer = Renderer::new(&config);
            let mut sheet = Pixmap::new(1200, styles.len() as u32 * 54).unwrap();
            sheet.fill(color(if light { 0xe9edf2 } else { 0x0b0e13 }));
            let mut signatures = std::collections::HashSet::new();
            for (index, style) in styles.iter().enumerate() {
                config.titlebar.style = style.to_string();
                for (column, buttons) in [
                    (0, (None, None, false)),
                    (1, (Some(Button::Close), None, false)),
                    (2, (Some(Button::Close), Some(Button::Close), true)),
                ] {
                    let image = renderer.title(
                        &config,
                        390,
                        40,
                        Label {
                            text: style,
                            icon: None,
                        },
                        true,
                        buttons,
                    );
                    if column == 0 {
                        assert!(
                            signatures.insert(
                                renderer
                                    .title(
                                        &config,
                                        390,
                                        40,
                                        Label {
                                            text: "Window",
                                            icon: None
                                        },
                                        true,
                                        buttons
                                    )
                                    .data()
                                    .to_vec()
                            ),
                            "style {style} has no distinct rendering"
                        );
                    }
                    sheet.draw_pixmap(
                        column * 400,
                        index as i32 * 54,
                        image.as_ref(),
                        &tiny_skia::PixmapPaint::default(),
                        Transform::identity(),
                        None,
                    );
                }
            }
            if let Ok(path) = std::env::var("CARPATIC_RENDER_DIR") {
                std::fs::create_dir_all(&path).unwrap();
                sheet
                    .save_png(std::path::Path::new(&path).join(if light {
                        "all-buttons-light.png"
                    } else {
                        "all-buttons-dark.png"
                    }))
                    .unwrap();
            }
        }
    }
    #[test]
    fn classic98_and_luna_hits_and_chrome() {
        let mut config = Config::default();
        config.titlebar.enabled = true;
        let renderer = Renderer::new(&config);
        let blank = Label {
            text: "",
            icon: None,
        };
        for (style, cell, gap) in [("classic98", 18, 0), ("luna", 22, 2)] {
            config.titlebar.style = style.to_string();
            let hits = renderer.hits(&config, 390, 32);
            assert_eq!(
                hits.iter().map(|h| h.button).collect::<Vec<_>>(),
                vec![Button::Minimize, Button::Maximize, Button::Close],
                "{style}: min/max/close order"
            );
            assert!(hits[0].left >= 195, "{style}: buttons sit on the right");
            for hit in &hits {
                assert_eq!(hit.right - hit.left, cell, "{style}: square cell");
            }
            assert_eq!(hits[1].left - hits[0].right, gap, "{style}: gap");
        }
        config.titlebar.style = "classic98".to_string();
        let active = renderer.title(&config, 390, 32, blank, true, (None, None, false));
        let inactive = renderer.title(&config, 390, 32, blank, false, (None, None, false));
        // A genuine horizontal title ramp, rather than an alias for the
        // flat Windows style, and a visibly different inactive state.
        assert_ne!(active.pixel(20, 16), active.pixel(250, 16));
        assert_eq!(
            active.pixel(2, 16).unwrap(),
            color(0xc0c0c0).premultiply().to_color_u8()
        );
        assert_ne!(active.pixel(60, 16), inactive.pixel(60, 16));
        // hover and press repaint the close button only, inside its hit span
        let hover = renderer.title(
            &config,
            390,
            32,
            blank,
            true,
            (Some(Button::Close), None, false),
        );
        let press = renderer.title(
            &config,
            390,
            32,
            blank,
            true,
            (Some(Button::Close), Some(Button::Close), false),
        );
        let close = renderer.hits(&config, 390, 32).pop().unwrap();
        assert_ne!(active.data(), hover.data());
        assert_ne!(hover.data(), press.data());
        for y in 0..32u32 {
            for x in 0..close.left.max(0) as u32 {
                assert_eq!(
                    active.pixel(x, y),
                    hover.pixel(x, y),
                    "classic98 hover stays inside the close hit span"
                );
            }
        }
        config.titlebar.style = "luna".to_string();
        let gel = renderer.title(&config, 390, 32, blank, true, (None, None, false));
        // vertical gradient: top and bottom of the bar differ, and neither is
        // the flat theme fill
        assert_ne!(gel.pixel(60, 2).unwrap(), gel.pixel(60, 29).unwrap());
        assert_ne!(
            gel.pixel(60, 2).unwrap(),
            color(config.background).premultiply().to_color_u8()
        );
        // gel buttons: the red close plate differs from the accent min plate
        let hits = renderer.hits(&config, 390, 32);
        let mid = |h: &Hit| ((h.left + h.right) / 2) as u32;
        assert_ne!(
            gel.pixel(mid(&hits[2]), 8).unwrap(),
            gel.pixel(mid(&hits[0]), 8).unwrap()
        );
        // the shared glyphs keep the maximize/restore distinction
        let maximized = renderer.title(&config, 390, 32, blank, true, (None, None, true));
        assert_ne!(gel.data(), maximized.data());
    }
}
