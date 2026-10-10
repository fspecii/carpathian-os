//! Pointer drop decisions, independent of the X server.
use carpatic_wm::Rect;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u32)]
pub enum Mode {
    Before = 1,
    After = 2,
    Swap = 3,
    Empty = 4,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Target {
    pub client: Option<u32>,
    pub monitor: usize,
    pub mode: Mode,
    pub rect: Rect,
}

pub fn choose(monitor: usize, work: Rect, tiles: &[(u32, Rect)], x: i32, y: i32) -> Option<Target> {
    if !contains(work, x, y) {
        return None;
    }
    if tiles.is_empty() {
        return Some(Target {
            client: None,
            monitor,
            mode: Mode::Empty,
            rect: work,
        });
    }
    for (client, rect) in tiles {
        if !contains(*rect, x, y) {
            continue;
        }
        let fx = (x - rect.x) as f64 / rect.width.max(1) as f64;
        let fy = (y - rect.y) as f64 / rect.height.max(1) as f64;
        let mut preview = *rect;
        let mode = if (0.3..0.7).contains(&fx) && (0.3..0.7).contains(&fy) {
            Mode::Swap
        } else if (fx - 0.5).abs() > (fy - 0.5).abs() {
            preview.width = (rect.width / 2).max(1);
            if fx < 0.5 {
                Mode::Before
            } else {
                preview.x += (rect.width - preview.width) as i32;
                Mode::After
            }
        } else {
            preview.height = (rect.height / 2).max(1);
            if fy < 0.5 {
                Mode::Before
            } else {
                preview.y += (rect.height - preview.height) as i32;
                Mode::After
            }
        };
        return Some(Target {
            client: Some(*client),
            monitor,
            mode,
            rect: preview,
        });
    }
    None
}
pub fn contains(rect: Rect, x: i32, y: i32) -> bool {
    x >= rect.x && y >= rect.y && x < rect.x + rect.width as i32 && y < rect.y + rect.height as i32
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn pointer_zones_choose_swap_or_directional_insert() {
        let area = Rect {
            x: 100,
            y: 50,
            width: 800,
            height: 600,
        };
        let tiles = [(7, area)];
        assert_eq!(choose(0, area, &tiles, 500, 350).unwrap().mode, Mode::Swap);
        let left = choose(0, area, &tiles, 120, 350).unwrap();
        assert_eq!(left.mode, Mode::Before);
        assert_eq!(left.rect.width, 400);
        let right = choose(0, area, &tiles, 880, 350).unwrap();
        assert_eq!(right.mode, Mode::After);
        assert_eq!(right.rect.x, 500);
        assert_eq!(choose(0, area, &tiles, 500, 60).unwrap().mode, Mode::Before);
        assert_eq!(choose(0, area, &tiles, 500, 640).unwrap().mode, Mode::After);
        assert!(choose(0, area, &tiles, 900, 350).is_none());
    }
    #[test]
    fn gaps_are_not_tiles_and_empty_monitor_accepts_a_drop() {
        let work = Rect {
            x: 0,
            y: 0,
            width: 1000,
            height: 700,
        };
        let tiles = [(
            7,
            Rect {
                x: 10,
                y: 10,
                width: 400,
                height: 680,
            },
        )];
        assert!(choose(1, work, &tiles, 450, 350).is_none());
        let empty = choose(1, work, &[], 450, 350).unwrap();
        assert_eq!(empty.mode, Mode::Empty);
        assert_eq!(empty.monitor, 1);
    }
}
