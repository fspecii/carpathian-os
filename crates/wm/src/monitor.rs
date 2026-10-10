use carpatic_wm::Rect;
use x11rb::{
    protocol::{randr::ConnectionExt as _, xproto::Window},
    rust_connection::RustConnection,
};

#[derive(Clone)]
pub struct Monitor {
    pub name: u32,
    pub area: Rect,
    pub work: Rect,
    pub desktop: u32,
    pub view: u32,
    pub previous_view: u32,
    pub all_mask: u32,
    pub all_view: bool,
    pub previous_all: bool,
    pub layouts: [u8; 32],
    pub masters: [usize; 32],
    pub factors: [u32; 32],
}

impl Monitor {
    pub fn slot(&self) -> usize {
        if self.all_view {
            0
        } else {
            self.desktop as usize + 1
        }
    }
    pub fn new(name: u32, area: Rect, float: bool) -> Self {
        Self {
            name,
            area,
            work: area,
            desktop: 0,
            view: 1,
            previous_view: 1,
            all_mask: 511,
            all_view: false,
            previous_all: false,
            layouts: [u8::from(float); 32],
            masters: [1; 32],
            factors: [55; 32],
        }
    }
}

pub fn discover(conn: &RustConnection, root: Window, fallback: Rect, float: bool) -> Vec<Monitor> {
    if let Ok(cookie) = conn.randr_get_monitors(root, false) {
        if let Ok(reply) = cookie.reply() {
            let manual = reply.monitors.iter().any(|m| !m.automatic);
            let mut monitors: Vec<_> = reply
                .monitors
                .into_iter()
                .filter(|m| m.width > 0 && m.height > 0 && (!manual || !m.automatic))
                .map(|m| {
                    Monitor::new(
                        m.name,
                        Rect {
                            x: m.x.into(),
                            y: m.y.into(),
                            width: m.width.into(),
                            height: m.height.into(),
                        },
                        float,
                    )
                })
                .collect();
            monitors.sort_by_key(|m| (m.area.x, m.area.y));
            if !monitors.is_empty() {
                return monitors;
            }
        }
    }
    vec![Monitor::new(0, fallback, float)]
}

pub fn contains(area: Rect, x: i32, y: i32) -> bool {
    x >= area.x && y >= area.y && x < area.x + area.width as i32 && y < area.y + area.height as i32
}

pub fn reserve(area: Rect, root: Rect, struts: &[Vec<u32>]) -> Rect {
    let mut left = area.x;
    let mut right = area.x + area.width as i32;
    let mut top = area.y;
    let mut bottom = area.y + area.height as i32;
    for original in struts {
        if original.len() < 4 {
            continue;
        }
        let mut s = original.clone();
        if s.len() < 12 {
            s.extend([
                0,
                root.height - 1,
                0,
                root.height - 1,
                0,
                root.width - 1,
                0,
                root.width - 1,
            ]);
        }
        let intersects_y = |start: u32, end: u32| {
            area.y <= end as i32 && area.y + area.height as i32 > start as i32
        };
        let intersects_x = |start: u32, end: u32| {
            area.x <= end as i32 && area.x + area.width as i32 > start as i32
        };
        if s[0] > 0 && intersects_y(s[4], s[5]) {
            left = left.max(root.x + s[0].min(root.width) as i32);
        }
        if s[1] > 0 && intersects_y(s[6], s[7]) {
            right = right.min(root.x + root.width as i32 - s[1].min(root.width) as i32);
        }
        if s[2] > 0 && intersects_x(s[8], s[9]) {
            top = top.max(root.y + s[2].min(root.height) as i32);
        }
        if s[3] > 0 && intersects_x(s[10], s[11]) {
            bottom = bottom.min(root.y + root.height as i32 - s[3].min(root.height) as i32);
        }
    }
    left = left.min(area.x + area.width as i32 - 1);
    top = top.min(area.y + area.height as i32 - 1);
    Rect {
        x: left,
        y: top,
        width: (right - left).max(1) as u32,
        height: (bottom - top).max(1) as u32,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn panel_struts_reserve_only_their_monitor_range() {
        let root = Rect {
            x: 0,
            y: 0,
            width: 1600,
            height: 900,
        };
        let left = Rect { width: 800, ..root };
        let right = Rect {
            x: 800,
            width: 800,
            ..root
        };
        let strut = vec![0, 0, 40, 0, 0, 0, 0, 0, 0, 799, 0, 0];
        assert_eq!(reserve(left, root, std::slice::from_ref(&strut)).y, 40);
        assert_eq!(reserve(right, root, &[strut]).y, 0);
    }
}
