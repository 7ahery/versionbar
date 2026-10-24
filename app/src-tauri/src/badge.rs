//! The tray icon's warning variant, drawn from the normal icon at run time so no second image
//! has to ship and the two can never drift apart.

const FILL: [u8; 4] = [245, 158, 11, 255];
const MARK: [u8; 4] = [40, 28, 4, 255];
const RING: [u8; 4] = [255, 255, 255, 255];

/// Returns a copy of `rgba` (8-bit RGBA, row by row, `width` x `height`) with an amber
/// warning dot containing a dark exclamation mark in the bottom-right corner.
pub fn with_warning_badge(rgba: &[u8], width: u32, height: u32) -> Vec<u8> {
    let mut out = rgba.to_vec();
    let (w, h) = (width as f32, height as f32);
    // About a third of the icon: still readable at the 16 px a tray usually shows.
    let radius = w.min(h) * 0.34;
    let (cx, cy) = (w - radius, h - radius);
    for y in 0..height {
        for x in 0..width {
            let (px, py) = (x as f32 + 0.5, y as f32 + 0.5);
            let distance = ((px - cx).powi(2) + (py - cy).powi(2)).sqrt();
            let colour = if distance > radius {
                continue;
            } else if is_exclamation(px - cx, py - cy, radius) {
                MARK
            } else if distance > radius * 0.82 {
                // A thin light ring keeps the dot visible against a dark taskbar.
                RING
            } else {
                FILL
            };
            let at = ((y * width + x) * 4) as usize;
            if let Some(pixel) = out.get_mut(at..at + 4) {
                pixel.copy_from_slice(&colour);
            }
        }
    }
    out
}

/// The "!" in coordinates relative to the dot's centre: a bar above a small square dot.
fn is_exclamation(dx: f32, dy: f32, radius: f32) -> bool {
    let half = radius * 0.12;
    let bar = dx.abs() <= half && (-radius * 0.5..=radius * 0.15).contains(&dy);
    let dot = dx.abs() <= half && (radius * 0.35..=radius * 0.6).contains(&dy);
    bar || dot
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_the_corner_changes_and_the_size_is_kept() {
        let (w, h) = (32u32, 32u32);
        let plain = vec![10u8; (w * h * 4) as usize];

        let badged = with_warning_badge(&plain, w, h);

        assert_eq!(badged.len(), plain.len());
        // The opposite corner is untouched.
        assert_eq!(badged[0..4], plain[0..4]);
        // A pixel on the dot, away from the exclamation mark, is the opaque amber fill.
        let dot = ((26 * w + 26) * 4) as usize;
        assert_eq!(badged[dot..dot + 4], FILL);
        // The far corner of the square lies outside the round dot.
        let corner = badged.len() - 4;
        assert_eq!(badged[corner..], plain[corner..]);
    }
}
