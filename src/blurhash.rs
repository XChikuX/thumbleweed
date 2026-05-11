use std::f64::consts::PI;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use thiserror::Error;

// ── Error types ──────────────────────────────────────────────────────────────

/// Errors that can occur while decoding a BlurHash string.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Error)]
pub enum BlurHashDecodeError {
    #[error("hash is too short: need at least 6 characters, got {got}")]
    TooShort { got: usize },

    #[error("hash length {got} does not match component count (expected {expected})")]
    LengthMismatch { expected: usize, got: usize },

    #[error("hash contains invalid base-83 character {ch:?}")]
    InvalidCharacter { ch: char },
}

/// Errors that can occur while encoding an image to a BlurHash string.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Error)]
pub enum BlurHashEncodeError {
    #[error("cx and cy must each be in 1..=9, got cx={cx}, cy={cy}")]
    InvalidComponents { cx: usize, cy: usize },

    #[error("pixel buffer is {got} bytes but {width}×{height}×4 = {expected} was expected")]
    BufferMismatch {
        width: usize,
        height: usize,
        expected: usize,
        got: usize,
    },
}

// Teach PyO3 how to turn our errors into Python ValueErrors automatically.
impl From<BlurHashDecodeError> for PyErr {
    fn from(e: BlurHashDecodeError) -> Self {
        PyValueError::new_err(e.to_string())
    }
}

impl From<BlurHashEncodeError> for PyErr {
    fn from(e: BlurHashEncodeError) -> Self {
        PyValueError::new_err(e.to_string())
    }
}

// ── Base-83 alphabet ────────────────────────────────────────────────────────

static CHARS: [char; 83] = [
    '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I',
    'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z', 'a', 'b',
    'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n', 'o', 'p', 'q', 'r', 's', 't', 'u',
    'v', 'w', 'x', 'y', 'z', '#', '$', '%', '*', '+', ',', '-', '.', ':', ';', '=', '?', '@', '[',
    ']', '^', '_', '{', '|', '}', '~',
];

// ── Internal helpers ─────────────────────────────────────────────────────────

fn decode_base83(s: &str) -> Result<usize, BlurHashDecodeError> {
    let mut value: usize = 0;
    for c in s.chars() {
        let digit = CHARS
            .iter()
            .position(|&ch| ch == c)
            .ok_or(BlurHashDecodeError::InvalidCharacter { ch: c })?;
        value = value * 83 + digit;
    }
    Ok(value)
}

fn encode_base83(value: usize, length: usize) -> String {
    let mut result = String::with_capacity(length);
    let mut remaining = value;
    for _ in 0..length {
        let digit = remaining % 83;
        remaining /= 83;
        result.push(CHARS[digit]);
    }
    // The encoding is big-endian (most-significant digit first) but we
    // collected least-significant first, so reverse.
    let mut bytes = result.into_bytes();
    bytes.reverse();
    // SAFETY: every byte came from `CHARS` which are all ASCII.
    String::from_utf8(bytes).unwrap()
}

/// Extract a slice of the hash string, returning `TooShort` if the range is
/// out of bounds.
fn hash_slice(s: &str, range: std::ops::Range<usize>) -> Result<&str, BlurHashDecodeError> {
    if range.end > s.len() {
        return Err(BlurHashDecodeError::TooShort { got: s.len() });
    }
    Ok(&s[range])
}

fn sign_pow(value: f64, exp: f64) -> f64 {
    value.signum() * value.abs().powf(exp)
}

fn linear_to_srgb(value: f64) -> u8 {
    let v = value.max(0.0).min(1.0);
    let srgb = if v <= 0.0031308 {
        v * 12.92
    } else {
        1.055 * v.powf(1.0 / 2.4) - 0.055
    };
    (srgb * 255.0 + 0.5) as u8
}

fn srgb_to_linear(value: usize) -> f64 {
    let v = value as f64 / 255.0;
    if v <= 0.04045 {
        v / 12.92
    } else {
        ((v + 0.055) / 1.055).powf(2.4)
    }
}

fn decode_dc(value: usize) -> [f64; 3] {
    let r = value >> 16;
    let g = (value >> 8) & 255;
    let b = value & 255;
    [srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b)]
}

fn decode_ac(value: usize, max_ac: f64) -> [f64; 3] {
    let q_r = (value / (19 * 19)) as f64;
    let q_g = ((value / 19) % 19) as f64;
    let q_b = (value % 19) as f64;
    [
        sign_pow((q_r - 9.0) / 9.0, 2.0) * max_ac,
        sign_pow((q_g - 9.0) / 9.0, 2.0) * max_ac,
        sign_pow((q_b - 9.0) / 9.0, 2.0) * max_ac,
    ]
}

fn encode_dc(value: [f64; 3]) -> usize {
    let r = linear_to_srgb(value[0]);
    let g = linear_to_srgb(value[1]);
    let b = linear_to_srgb(value[2]);
    ((r as usize) << 16) | ((g as usize) << 8) | (b as usize)
}

fn encode_ac(value: [f64; 3], max_ac: f64) -> usize {
    let q_r = (sign_pow(value[0] / max_ac, 0.5) * 9.0 + 9.5)
        .round()
        .max(0.0)
        .min(18.0) as usize;
    let q_g = (sign_pow(value[1] / max_ac, 0.5) * 9.0 + 9.5)
        .round()
        .max(0.0)
        .min(18.0) as usize;
    let q_b = (sign_pow(value[2] / max_ac, 0.5) * 9.0 + 9.5)
        .round()
        .max(0.0)
        .min(18.0) as usize;
    q_r * 19 * 19 + q_g * 19 + q_b
}

fn multiply_basis_function(
    pixels: &[u8],
    width: usize,
    height: usize,
    nx: usize,
    ny: usize,
) -> [f64; 3] {
    let mut r = 0.0_f64;
    let mut g = 0.0_f64;
    let mut b = 0.0_f64;

    let scale_x = PI / width as f64;
    let scale_y = PI / height as f64;

    for y in 0..height {
        let y_cos = (ny as f64 * y as f64 * scale_y).cos();
        for x in 0..width {
            let basis = nx as f64 * x as f64 * scale_x;
            let x_cos = basis.cos();
            let pixel = &pixels[(y * width + x) * 4..];
            r += x_cos * y_cos * srgb_to_linear(pixel[0] as usize);
            g += x_cos * y_cos * srgb_to_linear(pixel[1] as usize);
            b += x_cos * y_cos * srgb_to_linear(pixel[2] as usize);
        }
    }

    let normalisation = if nx == 0 && ny == 0 { 1.0 } else { 2.0 };
    let scale = normalisation / (width * height) as f64;
    [r * scale, g * scale, b * scale]
}

// ── Public API ───────────────────────────────────────────────────────────────

/// Decode a BlurHash string into raw RGBA pixels.
///
/// Returns a `Vec<u8>` of length `width * height * 4` (row-major RGBA).
pub fn decode(
    blur_hash: &str,
    width: usize,
    height: usize,
) -> Result<Vec<u8>, BlurHashDecodeError> {
    if blur_hash.len() < 6 {
        return Err(BlurHashDecodeError::TooShort {
            got: blur_hash.len(),
        });
    }

    let size_flag = decode_base83(hash_slice(blur_hash, 0..1)?)?;
    let ny = (size_flag / 9) + 1;
    let nx = (size_flag % 9) + 1;

    let quant_max_value = decode_base83(hash_slice(blur_hash, 1..2)?)?;
    let max_ac = (quant_max_value as f64 + 1.0) / 166.0;

    // Expected hash length: 4 + nx * ny * 2
    let expected = 4 + nx * ny * 2;
    if blur_hash.len() != expected {
        return Err(BlurHashDecodeError::LengthMismatch {
            expected,
            got: blur_hash.len(),
        });
    }

    let dc_value = decode_base83(hash_slice(blur_hash, 2..6)?)?;
    let dc = decode_dc(dc_value);

    let mut ac_components: Vec<[f64; 3]> = vec![[0.0; 3]; nx * ny];
    for j in 0..ny {
        for i in 0..nx {
            if i == 0 && j == 0 {
                ac_components[0] = dc;
                continue;
            }
            let start = 4 + (j * nx + i) * 2;
            let ac_value = decode_base83(hash_slice(blur_hash, start..start + 2)?)?;
            ac_components[j * nx + i] = decode_ac(ac_value, max_ac);
        }
    }

    // Render the image
    let mut pixels = vec![0u8; width * height * 4];
    for y in 0..height {
        for x in 0..width {
            let mut r = 0.0_f64;
            let mut g = 0.0_f64;
            let mut b = 0.0_f64;

            for j in 0..ny {
                for i in 0..nx {
                    let basis = (i as f64 * PI * x as f64 / width as f64).cos()
                        * (j as f64 * PI * y as f64 / height as f64).cos();
                    let comp = ac_components[j * nx + i];
                    r += comp[0] * basis;
                    g += comp[1] * basis;
                    b += comp[2] * basis;
                }
            }

            let idx = (y * width + x) * 4;
            pixels[idx] = linear_to_srgb(r);
            pixels[idx + 1] = linear_to_srgb(g);
            pixels[idx + 2] = linear_to_srgb(b);
            pixels[idx + 3] = 255; // full opacity
        }
    }

    Ok(pixels)
}

/// Encode raw RGBA pixels into a BlurHash string.
///
/// `cx` and `cy` are the number of components in the x and y directions
/// (each must be in 1..=9).
pub fn encode(
    pixels: &[u8],
    cx: usize,
    cy: usize,
    width: usize,
    height: usize,
) -> Result<String, BlurHashEncodeError> {
    if cx < 1 || cx > 9 || cy < 1 || cy > 9 {
        return Err(BlurHashEncodeError::InvalidComponents { cx, cy });
    }

    let expected = width * height * 4;
    if pixels.len() != expected {
        return Err(BlurHashEncodeError::BufferMismatch {
            width,
            height,
            expected,
            got: pixels.len(),
        });
    }

    let mut factors: Vec<[f64; 3]> = vec![[0.0; 3]; cx * cy];
    for y in 0..cy {
        for x in 0..cx {
            factors[y * cx + x] = multiply_basis_function(pixels, width, height, x, y);
        }
    }

    let mut hash = String::new();

    // Size flag
    let size_flag = (cx - 1) + (cy - 1) * 9;
    hash.push_str(&encode_base83(size_flag, 1));

    // Max AC value
    let dc = factors[0];
    let mut max_ac = 0.0_f64;
    for y in 0..cy {
        for x in 0..cx {
            if x == 0 && y == 0 {
                continue;
            }
            let factor = factors[y * cx + x];
            for c in 0..3 {
                max_ac = max_ac.max(factor[c].abs());
            }
        }
    }
    let quant_max = ((max_ac * 166.0) - 0.5).round().max(0.0).min(18.0) as usize;
    hash.push_str(&encode_base83(quant_max, 1));

    // DC component
    hash.push_str(&encode_base83(encode_dc(dc), 4));

    // AC components
    let ac_norm = if quant_max == 0 {
        1.0 / 166.0
    } else {
        (quant_max + 1) as f64 / 166.0
    };
    for y in 0..cy {
        for x in 0..cx {
            if x == 0 && y == 0 {
                continue;
            }
            hash.push_str(&encode_base83(encode_ac(factors[y * cx + x], ac_norm), 2));
        }
    }

    Ok(hash)
}

// ── Tests ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decodes_size_flag() {
        // "L" is index 21 in the base-83 alphabet => size_flag = 21
        // ny = 21 / 9 + 1 = 3,  nx = 21 % 9 + 1 = 4
        // For a valid hash with 3*4 components we need length 4 + 3*4*2 = 28.
        // Build a minimal hash starting with "L", then pad with "0" (index 0).
        let hash = "L000000000000000000000000000"; // 28 chars
        // Should not error on length - just verify it parses.
        let result = decode(hash, 4, 4);
        assert!(result.is_ok());
    }

    #[test]
    fn out_of_range_char_returns_error() {
        let value = decode_base83("!");
        assert_eq!(
            value,
            Err(BlurHashDecodeError::InvalidCharacter { ch: '!' })
        );
    }

    #[test]
    fn hash_too_short_returns_error() {
        let result = decode("abc", 4, 4);
        assert_eq!(result, Err(BlurHashDecodeError::TooShort { got: 3 }));
    }

    #[test]
    fn encode_then_decode_roundtrip() {
        // Build a small 4×4 solid red image (RGBA).
        let width = 4;
        let height = 4;
        let mut pixels = vec![0u8; width * height * 4];
        for pixel in pixels.chunks_exact_mut(4) {
            pixel[0] = 255; // R
            pixel[1] = 0; // G
            pixel[2] = 0; // B
            pixel[3] = 255; // A
        }

        let hash = encode(&pixels, 2, 2, width, height).unwrap();
        assert!(!hash.is_empty());

        let decoded = decode(&hash, width, height).unwrap();
        // The decoded image should have the same dimensions.
        assert_eq!(decoded.len(), width * height * 4);

        // Solid red should decode back to roughly red pixels.
        // Allow some tolerance since BlurHash is lossy.
        let r = decoded[0];
        let g = decoded[1];
        let b = decoded[2];
        assert!(r > 200, "red channel should be high, got {r}");
        assert!(g < 50, "green channel should be low, got {g}");
        assert!(b < 50, "blue channel should be low, got {b}");
    }

    #[test]
    fn encode_rejects_invalid_components() {
        let pixels = vec![0u8; 4 * 4 * 4];
        assert_eq!(
            encode(&pixels, 0, 2, 4, 4),
            Err(BlurHashEncodeError::InvalidComponents { cx: 0, cy: 2 })
        );
        assert_eq!(
            encode(&pixels, 10, 2, 4, 4),
            Err(BlurHashEncodeError::InvalidComponents { cx: 10, cy: 2 })
        );
    }

    #[test]
    fn encode_rejects_buffer_mismatch() {
        let pixels = vec![0u8; 10]; // too short for 4×4
        assert_eq!(
            encode(&pixels, 2, 2, 4, 4),
            Err(BlurHashEncodeError::BufferMismatch {
                width: 4,
                height: 4,
                expected: 64,
                got: 10,
            })
        );
    }

    #[test]
    fn linear_srgb_roundtrip_at_boundaries() {
        // Black
        assert_eq!(linear_to_srgb(srgb_to_linear(0)), 0);
        // White
        assert_eq!(linear_to_srgb(srgb_to_linear(255)), 255);
    }
}
