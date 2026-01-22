use reqwest::Client;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tracing::debug;

const BASE_URL: &str = "https://api.deepseek.com";

/// 动漫匹配系统提示（固定以最大化缓存命中）
const MATCH_SYSTEM_PROMPT: &str = r#"匹配MAL动漫与Bangumi候选。续作必须季数一致（2nd/第2期/II等）。输出JSON：{"id":数字或null}"#;

#[derive(Error, Debug)]
pub enum DsError {
    #[error("HTTP request failed: {0}")]
    Request(#[from] reqwest::Error),
    #[error("API error: {0}")]
    Api(String),
    #[error("No response content")]
    NoContent,
}

/// 消息角色
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    System,
    User,
    Assistant,
}

/// 聊天消息
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    pub role: Role,
    pub content: String,
}

impl Message {
    pub fn system(content: impl Into<String>) -> Self {
        Self {
            role: Role::System,
            content: content.into(),
        }
    }

    pub fn user(content: impl Into<String>) -> Self {
        Self {
            role: Role::User,
            content: content.into(),
        }
    }

    pub fn assistant(content: impl Into<String>) -> Self {
        Self {
            role: Role::Assistant,
            content: content.into(),
        }
    }
}

/// 聊天请求
#[derive(Debug, Clone, Serialize)]
pub struct ChatRequest {
    pub model: String,
    pub messages: Vec<Message>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub temperature: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_tokens: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stream: Option<bool>,
}

impl ChatRequest {
    pub fn new(messages: Vec<Message>) -> Self {
        Self {
            model: "deepseek-chat".to_string(),
            messages,
            temperature: Some(0.0), // 确定性输出，适合数据匹配
            max_tokens: Some(256),  // 限制输出长度节省成本
            stream: Some(false),
        }
    }

    pub fn with_model(mut self, model: impl Into<String>) -> Self {
        self.model = model.into();
        self
    }

    pub fn with_temperature(mut self, temperature: f32) -> Self {
        self.temperature = Some(temperature);
        self
    }

    pub fn with_max_tokens(mut self, max_tokens: u32) -> Self {
        self.max_tokens = Some(max_tokens);
        self
    }
}

/// Token 使用统计
#[derive(Debug, Clone, Deserialize)]
pub struct Usage {
    pub prompt_tokens: u32,
    pub completion_tokens: u32,
    pub total_tokens: u32,
    #[serde(default)]
    pub prompt_cache_hit_tokens: Option<u32>,
    #[serde(default)]
    pub prompt_cache_miss_tokens: Option<u32>,
}

/// 响应选项
#[derive(Debug, Clone, Deserialize)]
pub struct Choice {
    pub index: u32,
    pub message: Message,
    #[serde(default)]
    pub finish_reason: Option<String>,
}

/// 聊天响应
#[derive(Debug, Clone, Deserialize)]
pub struct ChatResponse {
    pub id: String,
    pub object: String,
    pub created: u64,
    pub model: String,
    pub choices: Vec<Choice>,
    pub usage: Usage,
}

impl ChatResponse {
    /// 获取第一条响应内容
    pub fn content(&self) -> Option<&str> {
        self.choices.first().map(|c| c.message.content.as_str())
    }

    /// 获取缓存命中率（用于监控成本优化效果）
    pub fn cache_hit_ratio(&self) -> Option<f64> {
        match (
            self.usage.prompt_cache_hit_tokens,
            self.usage.prompt_cache_miss_tokens,
        ) {
            (Some(hit), Some(miss)) if hit + miss > 0 => Some(hit as f64 / (hit + miss) as f64),
            _ => None,
        }
    }
}

pub struct DsClient {
    client: Client,
    api_key: String,
}

impl DsClient {
    pub fn new(api_key: impl Into<String>) -> Self {
        Self {
            client: Client::new(),
            api_key: api_key.into(),
        }
    }

    /// 发送聊天请求
    pub async fn chat(&self, request: &ChatRequest) -> Result<ChatResponse, DsError> {
        let url = format!("{}/chat/completions", BASE_URL);

        let response = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", self.api_key))
            .header("Content-Type", "application/json")
            .json(request)
            .send()
            .await?;

        if !response.status().is_success() {
            let status = response.status();
            let text = response.text().await.unwrap_or_default();
            return Err(DsError::Api(format!("{}: {}", status, text)));
        }

        let result = response.json::<ChatResponse>().await?;
        Ok(result)
    }

    /// 简单对话（单轮）
    pub async fn ask(&self, prompt: &str) -> Result<String, DsError> {
        let request = ChatRequest::new(vec![Message::user(prompt)]);
        let response = self.chat(&request).await?;
        response
            .content()
            .map(|s| s.to_string())
            .ok_or(DsError::NoContent)
    }

    /// 带系统提示的对话
    pub async fn ask_with_system(
        &self,
        system: &str,
        prompt: &str,
    ) -> Result<ChatResponse, DsError> {
        let request = ChatRequest::new(vec![Message::system(system), Message::user(prompt)]);
        self.chat(&request).await
    }

    /// 动漫匹配验证
    ///
    /// 返回匹配的 Bangumi ID，无匹配返回 None
    pub async fn match_anime(
        &self,
        mal_title: &str,
        mal_title_ja: Option<&str>,
        candidates: &[(u64, &str, Option<&str>)], // (bgm_id, name, name_cn)
    ) -> Result<Option<u64>, DsError> {
        if candidates.is_empty() {
            return Ok(None);
        }

        // 构建精简的用户输入
        let mut input = format!("MAL:{}", mal_title);
        if let Some(ja) = mal_title_ja {
            input.push_str(&format!("|{}", ja));
        }
        input.push_str("\nBGM:");
        for (id, name, name_cn) in candidates {
            input.push_str(&format!("\n{}:{}", id, name));
            if let Some(cn) = name_cn {
                input.push_str(&format!("|{}", cn));
            }
        }

        let request = ChatRequest::new(vec![
            Message::system(MATCH_SYSTEM_PROMPT),
            Message::user(&input),
        ])
        .with_max_tokens(32); // 输出只需 {"id":123456}

        let response = self.chat(&request).await?;
        let content = response.content().ok_or(DsError::NoContent)?;

        debug!(
            input = %input,
            output = %content,
            cache_hit = ?response.cache_hit_ratio(),
            "anime match"
        );

        // 解析 {"id": 123} 或 {"id": null}
        let result: MatchResult = serde_json::from_str(content)
            .map_err(|e| DsError::Api(format!("Invalid JSON: {} - {}", content, e)))?;

        Ok(result.id)
    }
}

/// 匹配结果
#[derive(Debug, Deserialize)]
struct MatchResult {
    id: Option<u64>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_message_creation() {
        let system = Message::system("你是助手");
        assert_eq!(system.role, Role::System);
        assert_eq!(system.content, "你是助手");

        let user = Message::user("你好");
        assert_eq!(user.role, Role::User);
    }

    #[test]
    fn test_chat_request_defaults() {
        let request = ChatRequest::new(vec![Message::user("test")]);

        assert_eq!(request.model, "deepseek-chat");
        assert_eq!(request.temperature, Some(0.0));
        assert_eq!(request.max_tokens, Some(256));
        assert_eq!(request.stream, Some(false));
    }

    #[test]
    fn test_chat_request_serialization() {
        let request = ChatRequest::new(vec![
            Message::system("你是助手"),
            Message::user("你好"),
        ]);

        let json = serde_json::to_string(&request).unwrap();
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();

        assert_eq!(parsed["model"], "deepseek-chat");
        assert_eq!(parsed["temperature"], 0.0);
        assert_eq!(parsed["max_tokens"], 256);
        assert_eq!(parsed["messages"][0]["role"], "system");
        assert_eq!(parsed["messages"][1]["role"], "user");
    }

    #[test]
    fn test_deserialize_response() {
        let json = r#"{
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "deepseek-chat",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "你好！"
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "prompt_cache_hit_tokens": 8,
                "prompt_cache_miss_tokens": 2
            }
        }"#;

        let response: ChatResponse = serde_json::from_str(json).unwrap();

        assert_eq!(response.id, "chatcmpl-123");
        assert_eq!(response.content(), Some("你好！"));
        assert_eq!(response.usage.prompt_tokens, 10);
        assert_eq!(response.usage.prompt_cache_hit_tokens, Some(8));

        // 缓存命中率 = 8 / (8 + 2) = 0.8
        let hit_ratio = response.cache_hit_ratio().unwrap();
        assert!((hit_ratio - 0.8).abs() < 0.001);
    }

    #[test]
    fn test_deserialize_response_without_cache_info() {
        let json = r#"{
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "deepseek-chat",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "你好！"
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15
            }
        }"#;

        let response: ChatResponse = serde_json::from_str(json).unwrap();
        assert!(response.cache_hit_ratio().is_none());
    }

    #[test]
    fn test_match_result_deserialize() {
        let json = r#"{"id":400602}"#;
        let result: MatchResult = serde_json::from_str(json).unwrap();
        assert_eq!(result.id, Some(400602));

        let json_null = r#"{"id":null}"#;
        let result_null: MatchResult = serde_json::from_str(json_null).unwrap();
        assert_eq!(result_null.id, None);
    }

    #[test]
    fn test_system_prompt_is_compact() {
        // 确保系统提示足够精简（中文 UTF-8 约 3 字节/字）
        assert!(MATCH_SYSTEM_PROMPT.len() < 150);
    }
}
