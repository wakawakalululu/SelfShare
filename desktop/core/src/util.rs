//! 通用工具：路径规范化、哈希、原子写入、忽略规则、主机标识。

use std::fs;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use sha2::{Digest, Sha256};

pub const STATE_DIR: &str = ".selfshare";
pub const CHUNK: usize = 1 << 20;

/// 与 Python 版一致：统一成 `/` 分隔、去掉前导 `/`、拒绝 `..`。
pub fn norm_rel(input: &str) -> Result<String, String> {
    let text = input.replace('\\', "/");
    let mut parts: Vec<&str> = Vec::new();
    for seg in text.split('/') {
        match seg {
            "" | "." => continue,
            ".." => return Err(format!("路径不能包含 '..'：{}", input)),
            other => parts.push(other),
        }
    }
    Ok(parts.join("/"))
}

/// 把相对路径拼到本地根目录上，并确保结果不会被绝对路径或盘符逃逸。
pub fn abs_path(root: &Path, rel: &str) -> Result<PathBuf, String> {
    let rel = norm_rel(rel)?;
    if rel.is_empty() {
        return Err("空路径".to_string());
    }
    let mut out = root.to_path_buf();
    for seg in rel.split('/') {
        out.push(seg);
    }
    // 二次防护：规范化后必须仍在 root 之下
    if !out.starts_with(root) {
        return Err(format!("路径逃逸：{}", rel));
    }
    Ok(out)
}

pub fn sha256_file(path: &Path) -> io::Result<String> {
    let mut file = fs::File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buf = vec![0u8; CHUNK];
    loop {
        let n = file.read(&mut buf)?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    Ok(hex(&hasher.finalize()))
}

pub fn sha256_bytes(data: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(data);
    hex(&hasher.finalize())
}

fn hex(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{:02x}", b));
    }
    s
}

/// 原子写入：先写同目录临时文件，再 rename 覆盖。
pub fn atomic_write(path: &Path, data: &[u8]) -> io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let tmp = path.with_extension(format!("selfshare-tmp-{}", std::process::id()));
    {
        let mut f = fs::File::create(&tmp)?;
        f.write_all(data)?;
        f.sync_all()?;
    }
    fs::rename(&tmp, path).map_err(|e| {
        let _ = fs::remove_file(&tmp);
        e
    })
}

pub fn ensure_parent(path: &Path) -> io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    Ok(())
}

pub fn mtime_secs(meta: &fs::Metadata) -> f64 {
    meta.modified()
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

pub fn now_epoch() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

/// `YYYYMMDD-HHMMSS`，用于冲突副本命名。
pub fn now_stamp() -> String {
    let secs = now_epoch() as i64;
    let (y, mo, d, h, mi, s) = civil_from_unix(secs);
    format!("{:04}{:02}{:02}-{:02}{:02}{:02}", y, mo, d, h, mi, s)
}

/// 无 chrono 依赖的 UTC 拆解（够用即可，冲突命名不需要本地时区精度）。
fn civil_from_unix(secs: i64) -> (i64, u32, u32, u32, u32, u32) {
    let days = secs.div_euclid(86_400);
    let rem = secs.rem_euclid(86_400);
    let (h, mi, s) = (rem / 3600, (rem % 3600) / 60, rem % 60);
    // Howard Hinnant 的 civil_from_days
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let mo = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    let y = if mo <= 2 { y + 1 } else { y };
    (y, mo, d, h as u32, mi as u32, s as u32)
}

pub fn host_id() -> String {
    let name = std::env::var("COMPUTERNAME")
        .or_else(|_| std::env::var("HOSTNAME"))
        .unwrap_or_else(|_| "host".to_string());
    let clean: String = name
        .chars()
        .map(|c| if c.is_alphanumeric() || c == '-' || c == '_' { c } else { '-' })
        .take(24)
        .collect();
    if clean.is_empty() {
        "host".to_string()
    } else {
        clean
    }
}

// --------------------------------------------------------------------------- //
// 忽略规则
// --------------------------------------------------------------------------- //
pub const ALWAYS_IGNORED_DIRS: &[&str] = &[".selfshare", ".git", "$RECYCLE.BIN", "System Volume Information"];

pub fn load_ignore_patterns(folder: &Path) -> Vec<String> {
    let file = folder.join(".selfshareignore");
    match fs::read_to_string(&file) {
        Ok(text) => text
            .lines()
            .map(|l| l.trim().to_string())
            .filter(|l| !l.is_empty() && !l.starts_with('#'))
            .collect(),
        Err(_) => Vec::new(),
    }
}

/// 简化版 gitignore：`*` 通配、结尾 `/` 只匹配目录、`!` 重新包含。
pub fn is_ignored(rel: &str, patterns: &[String], is_dir: bool) -> bool {
    let rel = rel.trim_matches('/');
    let name = rel.rsplit('/').next().unwrap_or(rel);
    let mut ignored = false;
    for raw in patterns {
        let mut pat = raw.trim();
        if pat.is_empty() || pat.starts_with('#') {
            continue;
        }
        let negate = pat.starts_with('!');
        if negate {
            pat = pat[1..].trim();
        }
        if pat.is_empty() {
            continue;
        }
        let dir_only = pat.ends_with('/');
        if dir_only {
            pat = pat.trim_end_matches('/');
        }
        if dir_only && !is_dir {
            continue;
        }
        let hit = if pat.contains('/') {
            glob_match(pat, rel) || glob_match(&format!("{}/*", pat.trim_end_matches('/')), rel)
        } else {
            glob_match(pat, name)
        };
        if hit {
            ignored = !negate;
        }
    }
    ignored
}

/// `*` 匹配任意字符（含分隔符，与 Python 版 fnmatch 行为一致），`?` 匹配单字符。
fn glob_match(pattern: &str, text: &str) -> bool {
    let p: Vec<char> = pattern.chars().collect();
    let t: Vec<char> = text.chars().collect();
    fn go(p: &[char], t: &[char]) -> bool {
        if p.is_empty() {
            return t.is_empty();
        }
        match p[0] {
            '*' => {
                if go(&p[1..], t) {
                    return true;
                }
                !t.is_empty() && go(p, &t[1..])
            }
            '?' => !t.is_empty() && go(&p[1..], &t[1..]),
            c => !t.is_empty() && t[0] == c && go(&p[1..], &t[1..]),
        }
    }
    go(&p, &t)
}

/// 递归列出目录下的所有文件，返回 `(相对路径, 大小, mtime)`。
pub fn scan_dir(root: &Path, patterns: &[String]) -> io::Result<Vec<(String, u64, f64)>> {
    let mut out = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let entries = match fs::read_dir(&dir) {
            Ok(e) => e,
            Err(_) => continue,
        };
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            let path = entry.path();
            let rel = match path.strip_prefix(root) {
                Ok(p) => p.to_string_lossy().replace('\\', "/"),
                Err(_) => continue,
            };
            let meta = match entry.metadata() {
                Ok(m) => m,
                Err(_) => continue,
            };
            if meta.is_dir() {
                if ALWAYS_IGNORED_DIRS.contains(&name.as_str()) {
                    continue;
                }
                if !patterns.is_empty() && is_ignored(&rel, patterns, true) {
                    continue;
                }
                stack.push(path);
            } else if meta.is_file() {
                if name.starts_with(".selfshare-") || name.ends_with(".selfshare-tmp") {
                    continue;
                }
                if !patterns.is_empty() && is_ignored(&rel, patterns, false) {
                    continue;
                }
                out.push((rel, meta.len(), mtime_secs(&meta)));
            }
        }
    }
    out.sort_by(|a, b| a.0.cmp(&b.0));
    Ok(out)
}

/// 判断路径是否在某个已挂载的同步目录内，返回挂载根。
pub fn find_mount_root(start: &Path) -> Option<PathBuf> {
    let mut cur = Some(start.to_path_buf());
    while let Some(p) = cur {
        if p.join(STATE_DIR).join("config.json").exists() {
            return Some(p);
        }
        cur = p.parent().map(|x| x.to_path_buf());
    }
    None
}

/// 检测平台保留名/非法字符，供 GUI 提前提示。
pub fn validate_mount_name(name: &str) -> Result<(), String> {
    let trimmed = name.trim();
    if trimmed.is_empty() {
        return Err("文件夹名不能为空".to_string());
    }
    if trimmed.chars().any(|c| matches!(c, '<' | '>' | ':' | '"' | '|' | '?' | '*')) {
        return Err("文件夹名不能包含 < > : \" | ? *".to_string());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalises_and_rejects_traversal() {
        assert_eq!(norm_rel("a\\b/c.txt").unwrap(), "a/b/c.txt");
        assert_eq!(norm_rel("./a//b").unwrap(), "a/b");
        assert!(norm_rel("../escape").is_err());
        assert!(norm_rel("a/../../b").is_err());
    }

    #[test]
    fn glob_behaves_like_fnmatch() {
        assert!(glob_match("*.tmp", "x.tmp"));
        assert!(glob_match("*.tmp", "a/b/x.tmp"));
        assert!(!glob_match("*.tmp", "x.txt"));
        assert!(glob_match("?.txt", "a.txt"));
    }

    #[test]
    fn ignore_dir_only_rule() {
        let pats = vec!["build/".to_string(), "*.tmp".to_string()];
        assert!(is_ignored("build", &pats, true));
        assert!(!is_ignored("build", &pats, false));
        assert!(is_ignored("sub/x.tmp", &pats, false));
    }

    #[test]
    fn negate_reincludes() {
        let pats = vec!["*.log".to_string(), "!keep.log".to_string()];
        assert!(is_ignored("a.log", &pats, false));
        assert!(!is_ignored("keep.log", &pats, false));
    }

    #[test]
    fn stamp_is_sortable() {
        let s = now_stamp();
        assert_eq!(s.len(), 15);
        assert!(s.chars().nth(8) == Some('-'));
    }
}
