//! 启动 nonce 与短标识：系统安全随机数（Windows 上为 ProcessPrng/BCryptGenRandom）。

/// 32 字节随机数的 64 位十六进制，作为每次 sidecar 启动的 `--launch-nonce`。
pub fn launch_nonce() -> String {
    random_hex::<32>()
}

/// 16 字节随机数的十六进制，用于 pick_id、临时文件名。
pub fn short_id() -> String {
    random_hex::<16>()
}

fn random_hex<const N: usize>() -> String {
    let mut bytes = [0u8; N];
    getrandom::fill(&mut bytes).expect("系统随机数不可用");
    hex(&bytes)
}

pub fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// 64 位小写十六进制。
pub fn is_launch_nonce(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nonces_are_64_hex_and_distinct() {
        let a = launch_nonce();
        let b = launch_nonce();
        assert!(is_launch_nonce(&a));
        assert_ne!(a, b);
        assert_eq!(short_id().len(), 32);
        assert!(!is_launch_nonce("ABC"));
    }
}
