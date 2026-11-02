//! HTTP 传输层：与 Python 版服务端协议一致。

use std::fs;
use std::io::Read;
use std::path::Path;
use std::time::Duration;

use serde::{Deserialize, Serialize};

const UA: &str = "SelfShare-Core/1.0";

#[derive(Debug)]
pub struct RemoteError {
    pub message: String,
    pub status: u16,
}

impl std::fmt::Display for RemoteError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for RemoteError {}

impl From<std::io::Error> for RemoteError {
    fn from(e: std::io::Error) -> Self {
        RemoteError { message: e.to_string(), status: 0 }
    }
}

pub type Result<T> = std::result::Result<T, RemoteError>;

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Entry {
    pub path: String,
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

#[derive(Debug, Clone, Deserialize)]
pub struct Manifest {
    pub head_rev: i64,
    #[serde(default)]
    pub entries: Vec<Entry>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Op {
    pub op: &'static str,
    pub path: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hash: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub size: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mtime: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub base_hash: Option<String>,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub force: bool,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Applied {
    pub path: String,
    #[serde(default)]
    pub rev: i64,
    #[serde(default)]
    pub action: String,
    #[serde(default)]
    pub hash: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ConflictItem {
    pub path: String,
    #[serde(default)]
    pub reason: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct CommitResult {
    #[serde(default)]
    pub head_rev: i64,
    #[serde(default)]
    pub applied: Vec<Applied>,
    #[serde(default)]
    pub conflicts: Vec<ConflictItem>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct HistoryItem {
    pub path: String,
    #[serde(default)]
    pub hash: Option<String>,
    #[serde(default)]
    pub size: Option<i64>,
    #[serde(default)]
    pub rev: i64,
    #[serde(default)]
    pub time: String,
    #[serde(default)]
    pub origin: String,
    #[serde(default)]
    pub action: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Stats {
    #[serde(default)]
    pub files: i64,
    #[serde(default)]
    pub bytes: i64,
    #[serde(default)]
    pub versions: i64,
    #[serde(default)]
    pub blobs: i64,
    #[serde(default)]
    pub blob_bytes: i64,
    #[serde(default)]
    pub head_rev: i64,
}

pub struct Client {
    base_url: String,
    vault: String,
    token: String,
    agent: ureq::Agent,
}

impl Client {
    pub fn new(base_url: &str, vault: &str, token: &str) -> Self {
        let agent = ureq::AgentBuilder::new()
            .timeout_connect(Duration::from_secs(15))
            .timeout_read(Duration::from_secs(300))
            .timeout_write(Duration::from_secs(300))
            .user_agent(UA)
            .build();
        Client {
            base_url: base_url.trim_end_matches('/').to_string(),
            vault: vault.to_string(),
            token: token.to_string(),
            agent,
        }
    }

    fn url(&self, action: &str, tail: &str) -> String {
        let mut u = format!("{}/api/v/{}/{}", self.base_url, self.vault, action);
        if !tail.is_empty() {
            u.push('/');
            u.push_str(tail.trim_start_matches('/'));
        }
        u
    }

    fn request(&self, method: &str, url: &str) -> ureq::Request {
        self.agent
            .request(method, url)
            .set("Authorization", &format!("Bearer {}", self.token))
    }

    fn to_remote(&self, err: ureq::Error) -> RemoteError {
        match err {
            ureq::Error::Status(code, resp) => {
                let detail = resp.into_string().unwrap_or_default();
                let msg = serde_json::from_str::<serde_json::Value>(&detail)
                    .ok()
                    .and_then(|v| v.get("error").and_then(|e| e.as_str()).map(String::from))
                    .unwrap_or_else(|| detail.chars().take(180).collect());
                RemoteError {
                    message: format!("HTTP {} {}", code, msg),
                    status: code,
                }
            }
            ureq::Error::Transport(t) => RemoteError {
                message: format!("无法连接 {}：{}", self.base_url, t),
                status: 0,
            },
        }
    }

    fn get_json<T: for<'de> Deserialize<'de>>(&self, url: &str) -> Result<T> {
        let resp = self.request("GET", url).call().map_err(|e| self.to_remote(e))?;
        let text = resp
            .into_string()
            .map_err(|e| RemoteError { message: e.to_string(), status: 0 })?;
        serde_json::from_str(&text).map_err(|e| RemoteError {
            message: format!("响应解析失败：{}", e),
            status: 0,
        })
    }

    pub fn stat(&self) -> Result<Stats> {
        self.get_json(&self.url("stat", ""))
    }

    pub fn manifest(&self, since: i64) -> Result<Manifest> {
        self.get_json(&self.url("manifest", &format!("?since={}", since)))
    }

    pub fn commit(&self, ops: &[Op], origin: &str) -> Result<CommitResult> {
        let body = serde_json::json!({ "origin": origin, "ops": ops });
        let resp = self
            .request("POST", &self.url("commit", ""))
            .set("Content-Type", "application/json")
            .send_string(&body.to_string())
            .map_err(|e| self.to_remote(e))?;
        let text = resp
            .into_string()
            .map_err(|e| RemoteError { message: e.to_string(), status: 0 })?;
        serde_json::from_str(&text).map_err(|e| RemoteError {
            message: format!("commit 响应解析失败：{}", e),
            status: 0,
        })
    }

    pub fn history(&self, path: Option<&str>, limit: usize) -> Result<Vec<HistoryItem>> {
        let mut url = self.url("history", &format!("?limit={}", limit));
        if let Some(p) = path {
            url.push_str("&path=");
            url.push_str(&urlencode(p));
        }
        #[derive(Deserialize)]
        struct Wrap {
            #[serde(default)]
            entries: Vec<HistoryItem>,
        }
        let wrap: Wrap = self.get_json(&url)?;
        Ok(wrap.entries)
    }

    pub fn has_blob(&self, digest: &str) -> Result<bool> {
        match self.request("HEAD", &self.url("blob", digest)).call() {
            Ok(_) => Ok(true),
            Err(ureq::Error::Status(404, _)) => Ok(false),
            Err(e) => Err(self.to_remote(e)),
        }
    }

    /// 流式上传，不把整个文件读进内存。
    pub fn put_blob_file(&self, digest: &str, path: &Path) -> Result<()> {
        let meta = fs::metadata(path)?;
        let file = fs::File::open(path)?;
        self.request("PUT", &self.url("blob", digest))
            .set("Content-Type", "application/octet-stream")
            .set("Content-Length", &meta.len().to_string())
            .send(file)
            .map(|_| ())
            .map_err(|e| self.to_remote(e))
    }

    pub fn get_blob_bytes(&self, digest: &str) -> Result<Vec<u8>> {
        let resp = self
            .request("GET", &self.url("blob", digest))
            .call()
            .map_err(|e| self.to_remote(e))?;
        let mut buf = Vec::new();
        resp.into_reader()
            .read_to_end(&mut buf)
            .map_err(|e| RemoteError { message: e.to_string(), status: 0 })?;
        Ok(buf)
    }
}

fn urlencode(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char)
            }
            _ => out.push_str(&format!("%{:02X}", b)),
        }
    }
    out
}
