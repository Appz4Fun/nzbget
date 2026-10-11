//! Byte searches for the ports: the C library's memmem and memchr (SIMD in
//! glibc, the speed of the strstr/strchr the C++ used) where available, a
//! plain scan elsewhere. Results are the same either way.

#[cfg(unix)]
extern "C" {
    fn memmem(hay: *const u8, hay_len: usize, needle: *const u8, needle_len: usize) -> *const u8;
    fn memchr(s: *const u8, c: i32, n: usize) -> *const u8;
}

/// The first occurrence of `needle` in `hay` (an empty needle is at 0).
pub fn find(hay: &[u8], needle: &[u8]) -> Option<usize> {
    if needle.is_empty() {
        return Some(0);
    }
    if needle.len() > hay.len() {
        return None;
    }
    #[cfg(unix)]
    {
        // borrowed for the call; memmem reads within both lengths
        let p = unsafe { memmem(hay.as_ptr(), hay.len(), needle.as_ptr(), needle.len()) };
        (!p.is_null()).then(|| p as usize - hay.as_ptr() as usize)
    }
    #[cfg(not(unix))]
    {
        hay.windows(needle.len()).position(|w| w == needle)
    }
}

/// The first `byte` in `hay`.
pub fn find_byte(hay: &[u8], byte: u8) -> Option<usize> {
    #[cfg(unix)]
    {
        if hay.is_empty() {
            return None;
        }
        let p = unsafe { memchr(hay.as_ptr(), byte as i32, hay.len()) };
        (!p.is_null()).then(|| p as usize - hay.as_ptr() as usize)
    }
    #[cfg(not(unix))]
    {
        hay.iter().position(|&b| b == byte)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn same_as_a_scan() {
        let naive = |h: &[u8], n: &[u8]| if n.is_empty() { Some(0) } else { h.windows(n.len()).position(|w| w == n) };
        let mut state = 0x2545f4914f6cdd1du64;
        for _ in 0..50_000 {
            state ^= state << 13; state ^= state >> 7; state ^= state << 17;
            let hay: Vec<u8> = (0..state % 40).map(|i| b"ab<\0"[((state >> (i % 60)) % 4) as usize]).collect();
            let needle: Vec<u8> = (0..(state >> 8) % 5).map(|i| b"ab<\0"[((state >> (i * 3 + 7)) % 4) as usize]).collect();
            assert_eq!(find(&hay, &needle), naive(&hay, &needle));
            assert_eq!(find_byte(&hay, b'<'), hay.iter().position(|&b| b == b'<'));
            assert_eq!(find_byte(&hay, 0), hay.iter().position(|&b| b == 0));
        }
    }
}
