//! 本地 base 快照 + 挂载配置。
//!
//! 用 JSON 而不是 SQLite：rusqlite 会引入 C 依赖，与"纯 Rust 可编译"的目标冲突；
//! 快照在每次同步后整体原子重写，几万文件的规模完全够用。

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::util::{atomic_write, norm_rel, STATE_DIR};

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct BaseEntry {
    #[serde(default)]
    pub hash: Option<String>,
    #[serde(default)]
    pub size: Option<i64>,
    #[serde(default)]
    pub mtime: Option<f64>,
    #[serde(default)]
    pub rev: i64,
    #[serde(default)]
    pub deleted: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MountConfig {
    pub url: String,
    pub vault: String,
    pub token: String,
    pub folder: String,
    #[serde(default = "default_host")]
    pub host_id: String,
    #[serde(default)]
    pub created: String,
}

fn default_host() -> String {
    crate::util::host_id()
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Snapshot {
    #[serde(default)]
    pub head_rev: i64,
    #[serde(default)]
    pub last_sync: String,
    #[serde(default)]
    pub files: BTreeMap<String, BaseEntry>,
}

pub struct LocalState {
    folder: PathBuf,
    config: MountConfig,
    snapshot: Snapshot,
}

impl LocalState {
    pub fn dir(folder: &Path) -> PathBuf {
        folder.join(STATE_DIR)
    }

    pub fn config_path(folder: &Path) -> PathBuf {
        folder.join(STATE_DIR).join("config.json")
    }

    pub fn snapshot_path(folder: &Path) -> PathBuf {
        folder.join(STATE_DIR).join("state.json")
    }

    /// 打开已挂载目录；未挂载则报错。
    pub fn open(folder: &Path) -> Result<Self, String> {
        let folder = fs::canonicalize(folder).map_err(|e| format!("目录不可访问：{}", e))?;
        let cfg_path = Self::config_path(&folder);
        if !cfg_path.exists() {
            return Err(format!(
                "该目录尚未挂载到同步库：{}\n请先在「添加同步文件夹」里完成挂载。",
                folder.display()
            ));
        }
        let raw = fs::read_to_string(&cfg_path).map_err(|e| format!("读取配置失败：{}", e))?;
        let mut config: MountConfig =
            serde_json::from_str(&raw).map_err(|e| format!("配置格式错误：{}", e))?;
        if config.host_id.is_empty() {
            config.host_id = crate::util::host_id();
        }
        let snapshot = Self::load_snapshot(&folder);
        Ok(LocalState { folder, config, snapshot })
    }

    /// 初始化一个新挂载点（写入 config.json）。
    ///
    /// 若该目录之前挂载过（存在 state.json），会保留原有基线快照——重复
    /// 挂载（例如换了服务端地址或令牌）不应该把「上次一致的状态」清空，
    /// 否则所有文件都会被当成新增，删除也会被误判。
    pub fn init_mount(folder: &Path, mut config: MountConfig) -> Result<Self, String> {
        fs::create_dir_all(folder).map_err(|e| format!("创建目录失败：{}", e))?;
        let folder = fs::canonicalize(folder).map_err(|e| format!("目录不可访问：{}", e))?;
        // Linux 上 /tmp 常是符号链接，canonicalize 后的路径与调用方传入的不同；
        // 配置里记录规范化后的路径，避免后续比较时对不上。
        config.folder = folder.to_string_lossy().to_string();
        fs::create_dir_all(Self::dir(&folder)).map_err(|e| format!("创建状态目录失败：{}", e))?;
        let payload = serde_json::to_vec_pretty(&config).map_err(|e| e.to_string())?;
        atomic_write(&Self::config_path(&folder), &payload)
            .map_err(|e| format!("写入配置失败：{}", e))?;
        #[cfg(windows)]
        hide_windows(&Self::dir(&folder));
        let snapshot = Self::load_snapshot(&folder);
        Ok(LocalState { folder, config, snapshot })
    }

    fn load_snapshot(folder: &Path) -> Snapshot {
        let path = Self::snapshot_path(folder);
        match fs::read_to_string(&path) {
            Ok(text) => serde_json::from_str(&text).unwrap_or_default(),
            Err(_) => Snapshot::default(),
        }
    }

    pub fn folder(&self) -> &Path {
        &self.folder
    }

    pub fn config(&self) -> &MountConfig {
        &self.config
    }

    pub fn snapshot(&self) -> &Snapshot {
        &self.snapshot
    }

    pub fn snapshot_mut(&mut self) -> &mut Snapshot {
        &mut self.snapshot
    }

    pub fn host_id(&self) -> &str {
        &self.config.host_id
    }

    pub fn save(&self) -> Result<(), String> {
        let payload = serde_json::to_vec(&self.snapshot).map_err(|e| e.to_string())?;
        atomic_write(&Self::snapshot_path(&self.folder), &payload)
            .map_err(|e| format!("保存状态失败：{}", e))
    }

    pub fn set_base(&mut self, rel: &str, entry: BaseEntry) {
        let key = norm_rel(rel).unwrap_or_else(|_| rel.to_string());
        self.snapshot.files.insert(key, entry);
    }

    pub fn forget(&mut self, rel: &str) {
        if let Ok(key) = norm_rel(rel) {
            self.snapshot.files.remove(&key);
        }
    }

    pub fn base_of(&self, rel: &str) -> Option<&BaseEntry> {
        self.snapshot.files.get(rel)
    }
}

#[cfg(windows)]
fn hide_windows(path: &Path) {
    use std::os::windows::ffi::OsStrExt;
    // SetFileAttributesW 位于 kernel32；直接声明以免额外依赖。
    #[link(name = "kernel32")]
    extern "system" {
        fn SetFileAttributesW(name: *const u16, attrs: u32) -> i32;
    }
    const FILE_ATTRIBUTE_HIDDEN: u32 = 0x02;
    let wide: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    unsafe {
        SetFileAttributesW(wide.as_ptr(), FILE_ATTRIBUTE_HIDDEN);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip_snapshot() {
        let dir = std::env::temp_dir().join(format!("ss-state-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let cfg = MountConfig {
            url: "http://localhost:1".into(),
            vault: "v".into(),
            token: "t".into(),
            folder: dir.to_string_lossy().into(),
            host_id: "host-a".into(),
            created: "now".into(),
        };
        {
            let mut st = LocalState::init_mount(&dir, cfg).unwrap();
            st.set_base(
                "a/b.txt",
                BaseEntry { hash: Some("deadbeef".into()), size: Some(3), mtime: Some(1.0), rev: 2, deleted: false },
            );
            st.save().unwrap();
        }
        let st = LocalState::open(&dir).unwrap();
        assert_eq!(st.host_id(), "host-a");
        let e = st.base_of("a/b.txt").unwrap();
        assert_eq!(e.hash.as_deref(), Some("deadbeef"));
        assert_eq!(e.rev, 2);
        let _ = fs::remove_dir_all(&dir);
    }
}
