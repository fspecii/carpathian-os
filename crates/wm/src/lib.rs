//! Window layout independent of X11. Geometry includes the border.
pub mod config;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}

pub fn tile(area: Rect, count: usize, gap: u32, master_percent: u32) -> Vec<Rect> {
    if count == 0 {
        return Vec::new();
    }
    let gap = gap.min(area.width / 4).min(area.height / 4);
    let inner = Rect {
        x: area.x + gap as i32,
        y: area.y + gap as i32,
        width: area.width.saturating_sub(gap * 2).max(1),
        height: area.height.saturating_sub(gap * 2).max(1),
    };
    if count == 1 {
        return vec![inner];
    }
    let split = (inner.width.saturating_sub(gap) * master_percent.clamp(5, 95) / 100).max(1);
    let mut result = vec![Rect {
        width: split,
        ..inner
    }];
    let rows = count as u32 - 1;
    let row_gap = gap.min(inner.height / rows.max(1) / 2);
    let available = inner.height.saturating_sub(row_gap * (rows - 1));
    let mut y = inner.y;
    for row in 0..rows {
        let height = available / rows + u32::from(row < available % rows);
        result.push(Rect {
            x: inner.x + split as i32 + gap as i32,
            y,
            width: inner.width.saturating_sub(split + gap).max(1),
            height: height.max(1),
        });
        y += (height + row_gap) as i32;
    }
    result
}

pub fn clamp(mut rect: Rect, area: Rect) -> Rect {
    rect.width = rect.width.clamp(1, area.width.max(1));
    rect.height = rect.height.clamp(1, area.height.max(1));
    rect.x = rect
        .x
        .clamp(area.x, area.x + (area.width - rect.width) as i32);
    rect.y = rect
        .y
        .clamp(area.y, area.y + (area.height - rect.height) as i32);
    rect
}

/// Master/stack with multiple masters and weighted client heights. `area` already excludes outer gaps.
pub fn weighted_tile(
    area: Rect,
    weights: &[f32],
    masters: usize,
    master_percent: u32,
    gap: u32,
) -> Vec<Rect> {
    if weights.is_empty() {
        return Vec::new();
    }
    let masters = if masters == 0 {
        weights.len()
    } else {
        masters.min(weights.len())
    };
    let gap = gap.min(area.width / 4);
    let master_width = if masters == weights.len() {
        area.width
    } else {
        (area.width.saturating_sub(gap) * master_percent.clamp(5, 95) / 100).max(1)
    };
    let mut result = Vec::with_capacity(weights.len());
    for (column, range) in [0..masters, masters..weights.len()].into_iter().enumerate() {
        if range.is_empty() {
            continue;
        }
        let row_gap = gap.min(area.height / (range.len() as u32 * 2).max(1));
        let mut remaining = area
            .height
            .saturating_sub(row_gap * (range.len() as u32 - 1));
        let mut total: f64 = weights[range.clone()]
            .iter()
            .map(|w| f64::from(w.clamp(0.25, 4.0)))
            .sum();
        let mut y = area.y;
        for index in range.clone() {
            let weight = f64::from(weights[index].clamp(0.25, 4.0));
            let rows_left = range.end - index;
            let height = if rows_left == 1 {
                remaining
            } else {
                ((f64::from(remaining) * weight / total).round() as u32)
                    .max(1)
                    .min(remaining.saturating_sub(rows_left as u32 - 1).max(1))
            };
            let x = if column == 0 {
                area.x
            } else {
                area.x + master_width as i32 + gap as i32
            };
            let width = if column == 0 {
                master_width
            } else {
                area.width.saturating_sub(master_width + gap).max(1)
            };
            result.push(Rect {
                x,
                y,
                width,
                height: height.max(1),
            });
            y += (height + row_gap) as i32;
            remaining = remaining.saturating_sub(height);
            total -= weight;
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn layouts_fit_and_never_overlap() {
        for count in 1..=16 {
            let area = Rect {
                x: 0,
                y: 0,
                width: 1280,
                height: 800,
            };
            let rs = tile(area, count, 8, 60);
            assert_eq!(rs.len(), count);
            for (i, r) in rs.iter().enumerate() {
                assert!(r.width > 0 && r.height > 0);
                assert!(r.x >= 0 && r.y >= 0);
                assert!(r.x + r.width as i32 <= 1280 && r.y + r.height as i32 <= 800);
                for other in &rs[i + 1..] {
                    assert!(
                        r.x + r.width as i32 <= other.x
                            || other.x + other.width as i32 <= r.x
                            || r.y + r.height as i32 <= other.y
                            || other.y + other.height as i32 <= r.y
                    );
                }
            }
        }
    }
    #[test]
    fn floating_windows_stay_on_screen() {
        let area = Rect {
            x: 0,
            y: 0,
            width: 800,
            height: 600,
        };
        assert_eq!(
            clamp(
                Rect {
                    x: -50,
                    y: 900,
                    width: 2000,
                    height: 100
                },
                area
            ),
            Rect {
                x: 0,
                y: 500,
                width: 800,
                height: 100
            }
        );
    }
}
