//! 仅负责引导阶段的两个无鉴权端点：`/api/ping` 与 `/api/pair`。
//!
//! 真正的数据面（manifest/commit/blob/history/stat）全部走 `selfshare-core::Client`，
//! 这里不再重复实现，只保留「探测服务端」和「配对码换令牌」这两个建库前的调用。

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PingResponse {
    #[serde(default)]
    pub ok: bool,
    #[serde(default)]
    pub service: String,
    #[serde(default)]
    pub version: String,
    #[serde(default)]
    pub vaults: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PairResponse {
    #[serde(default)]
    pub vault: String,
    #[serde(default)]
    pub token: String,
    #[serde(default)]
    pub note: String,
}

pub struct SyncClient {
    base: String,
}

impl SyncClient {
    /// 第二个参数（vault）为兼容旧调用保留，建库前用不到。
    pub fn new(url: &str, _vault: &str) -> Self {
        SyncClient {
            base: url.trim_end_matches('/').to_string(),
        }
    }

    pub async fn ping(&self) -> Result<PingResponse, String> {
        let url = format!("{}/api/ping", self.base);
        tokio::task::spawn_blocking(move || {
            ureq::get(&url)
                .timeout(std::time::Duration::from_secs(8))
                .call()
                .map_err(|e| e.to_string())?
                .into_json::<PingResponse>()
                .map_err(|e| e.to_string())
        })
        .await
        .map_err(|e| e.to_string())?
    }

    pub async fn pair(&self, code: &str) -> Result<PairResponse, String> {
        let url = format!("{}/api/pair", self.base);
        let body = serde_json::json!({ "code": code }).to_string();
        tokio::task::spawn_blocking(move || {
            ureq::post(&url)
                .set("Content-Type", "application/json")
                .timeout(std::time::Duration::from_secs(25))
                .send_string(&body)
                .map_err(|e| e.to_string())?
                .into_json::<PairResponse>()
                .map_err(|e| e.to_string())
        })
        .await
        .map_err(|e| e.to_string())?
    }
}
