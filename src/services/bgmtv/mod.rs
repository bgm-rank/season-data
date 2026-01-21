use reqwest::Client;
use serde::{Deserialize, Serialize};
use thiserror::Error;

const BASE_URL: &str = "https://api.bgm.tv";
const USER_AGENT: &str = "bgm-rank/season-data (https://github.com/bgm-rank/season-data)";

#[derive(Error, Debug)]
pub enum BgmtvError {
    #[error("HTTP request failed: {0}")]
    Request(#[from] reqwest::Error),
    #[error("API error: {0}")]
    Api(String),
}

/// 条目类型
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[repr(u8)]
pub enum SubjectType {
    Book = 1,
    Anime = 2,
    Music = 3,
    Game = 4,
    Real = 6,
}

impl From<SubjectType> for u8 {
    fn from(t: SubjectType) -> Self {
        t as u8
    }
}

/// 图片信息
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Images {
    #[serde(default)]
    pub large: Option<String>,
    #[serde(default)]
    pub common: Option<String>,
    #[serde(default)]
    pub medium: Option<String>,
    #[serde(default)]
    pub small: Option<String>,
    #[serde(default)]
    pub grid: Option<String>,
}

/// 评分信息
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Rating {
    #[serde(default)]
    pub rank: Option<u32>,
    #[serde(default)]
    pub total: Option<u32>,
    #[serde(default)]
    pub score: Option<f64>,
    #[serde(default)]
    pub count: Option<RatingCount>,
}

/// 各分数段的评分人数
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RatingCount {
    #[serde(rename = "1", default)]
    pub score_1: Option<u32>,
    #[serde(rename = "2", default)]
    pub score_2: Option<u32>,
    #[serde(rename = "3", default)]
    pub score_3: Option<u32>,
    #[serde(rename = "4", default)]
    pub score_4: Option<u32>,
    #[serde(rename = "5", default)]
    pub score_5: Option<u32>,
    #[serde(rename = "6", default)]
    pub score_6: Option<u32>,
    #[serde(rename = "7", default)]
    pub score_7: Option<u32>,
    #[serde(rename = "8", default)]
    pub score_8: Option<u32>,
    #[serde(rename = "9", default)]
    pub score_9: Option<u32>,
    #[serde(rename = "10", default)]
    pub score_10: Option<u32>,
}

/// 收藏信息
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Collection {
    #[serde(default)]
    pub wish: Option<u32>,
    #[serde(default)]
    pub collect: Option<u32>,
    #[serde(default)]
    pub doing: Option<u32>,
    #[serde(default)]
    pub on_hold: Option<u32>,
    #[serde(default)]
    pub dropped: Option<u32>,
}

/// 标签
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tag {
    pub name: String,
    pub count: u32,
}

/// 信息框项目
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InfoboxItem {
    pub key: String,
    pub value: serde_json::Value,
}

/// 条目信息
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Subject {
    pub id: u64,
    #[serde(rename = "type")]
    pub subject_type: u8,
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub name_cn: Option<String>,
    #[serde(default)]
    pub summary: Option<String>,
    #[serde(default)]
    pub series: Option<bool>,
    #[serde(default)]
    pub nsfw: Option<bool>,
    #[serde(default)]
    pub locked: Option<bool>,
    #[serde(default)]
    pub date: Option<String>,
    #[serde(default)]
    pub platform: Option<String>,
    #[serde(default)]
    pub images: Option<Images>,
    #[serde(default)]
    pub infobox: Option<Vec<InfoboxItem>>,
    #[serde(default)]
    pub volumes: Option<u32>,
    #[serde(default)]
    pub eps: Option<u32>,
    #[serde(default)]
    pub total_episodes: Option<u32>,
    #[serde(default)]
    pub rating: Option<Rating>,
    #[serde(default)]
    pub collection: Option<Collection>,
    #[serde(default)]
    pub meta_tags: Option<Vec<String>>,
    #[serde(default)]
    pub tags: Option<Vec<Tag>>,
}

/// 搜索筛选器
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SearchFilter {
    #[serde(rename = "type", skip_serializing_if = "Option::is_none")]
    pub subject_type: Option<Vec<u8>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub meta_tags: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tag: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub air_date: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rating: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rating_count: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rank: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub nsfw: Option<bool>,
}

impl SearchFilter {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_type(subject_type: SubjectType) -> Self {
        Self {
            subject_type: Some(vec![subject_type as u8]),
            ..Default::default()
        }
    }

    pub fn anime() -> Self {
        Self::with_type(SubjectType::Anime)
    }

    pub fn air_date_range(mut self, start: &str, end: &str) -> Self {
        self.air_date = Some(vec![format!(">={}", start), format!("<{}", end)]);
        self
    }

    pub fn include_nsfw(mut self) -> Self {
        self.nsfw = Some(true);
        self
    }
}

/// 排序规则
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SortOrder {
    Match,
    Heat,
    Rank,
    Score,
}

impl Default for SortOrder {
    fn default() -> Self {
        Self::Match
    }
}

/// 搜索请求
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchRequest {
    pub keyword: String,
    #[serde(default)]
    pub sort: SortOrder,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub filter: Option<SearchFilter>,
}

impl SearchRequest {
    pub fn new(keyword: impl Into<String>) -> Self {
        Self {
            keyword: keyword.into(),
            sort: SortOrder::default(),
            filter: None,
        }
    }

    pub fn with_sort(mut self, sort: SortOrder) -> Self {
        self.sort = sort;
        self
    }

    pub fn with_filter(mut self, filter: SearchFilter) -> Self {
        self.filter = Some(filter);
        self
    }
}

/// 分页条目响应
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PagedSubject {
    pub total: u32,
    pub limit: u32,
    pub offset: u32,
    pub data: Vec<Subject>,
}

pub struct BgmtvClient {
    client: Client,
    access_token: Option<String>,
}

impl BgmtvClient {
    pub fn new(access_token: impl Into<String>) -> Self {
        Self {
            client: Client::new(),
            access_token: Some(access_token.into()),
        }
    }

    /// 搜索条目
    ///
    /// POST /v0/search/subjects
    pub async fn search_subjects(
        &self,
        request: &SearchRequest,
        limit: Option<u32>,
        offset: Option<u32>,
    ) -> Result<PagedSubject, BgmtvError> {
        let url = format!("{}/v0/search/subjects", BASE_URL);

        let mut query_params = Vec::new();
        if let Some(limit) = limit {
            query_params.push(("limit", limit.to_string()));
        }
        if let Some(offset) = offset {
            query_params.push(("offset", offset.to_string()));
        }

        let mut req = self
            .client
            .post(&url)
            .header("User-Agent", USER_AGENT)
            .header("Content-Type", "application/json")
            .query(&query_params)
            .json(request);

        if let Some(token) = &self.access_token {
            req = req.header("Authorization", format!("Bearer {}", token));
        }

        let response = req.send().await?;

        if !response.status().is_success() {
            let status = response.status();
            let text = response.text().await.unwrap_or_default();
            return Err(BgmtvError::Api(format!("{}: {}", status, text)));
        }

        let result = response.json::<PagedSubject>().await?;
        Ok(result)
    }

    /// 搜索动画条目（便捷方法）
    pub async fn search_anime(
        &self,
        keyword: &str,
        limit: Option<u32>,
        offset: Option<u32>,
    ) -> Result<PagedSubject, BgmtvError> {
        let request = SearchRequest::new(keyword).with_filter(SearchFilter::anime());
        self.search_subjects(&request, limit, offset).await
    }

    /// 搜索指定季度的动画
    pub async fn search_seasonal_anime(
        &self,
        keyword: &str,
        start_date: &str,
        end_date: &str,
        limit: Option<u32>,
        offset: Option<u32>,
    ) -> Result<PagedSubject, BgmtvError> {
        let filter = SearchFilter::anime().air_date_range(start_date, end_date);
        let request = SearchRequest::new(keyword).with_filter(filter);
        self.search_subjects(&request, limit, offset).await
    }
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_subject_type_values() {
        assert_eq!(SubjectType::Book as u8, 1);
        assert_eq!(SubjectType::Anime as u8, 2);
        assert_eq!(SubjectType::Music as u8, 3);
        assert_eq!(SubjectType::Game as u8, 4);
        assert_eq!(SubjectType::Real as u8, 6);
    }

    #[test]
    fn test_search_filter_anime() {
        let filter = SearchFilter::anime();
        assert_eq!(filter.subject_type, Some(vec![2]));
    }

    #[test]
    fn test_search_filter_with_date_range() {
        let filter = SearchFilter::anime().air_date_range("2020-07-01", "2020-10-01");
        assert_eq!(
            filter.air_date,
            Some(vec![
                ">=2020-07-01".to_string(),
                "<2020-10-01".to_string()
            ])
        );
    }

    #[test]
    fn test_search_request_serialization() {
        let request = SearchRequest::new("葬送的芙莉莲")
            .with_sort(SortOrder::Rank)
            .with_filter(SearchFilter::anime());

        let json = serde_json::to_string(&request).unwrap();
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();

        assert_eq!(parsed["keyword"], "葬送的芙莉莲");
        assert_eq!(parsed["sort"], "rank");
        assert_eq!(parsed["filter"]["type"], serde_json::json!([2]));
    }

    #[test]
    fn test_deserialize_subject() {
        let json = r#"{
            "id": 400602,
            "type": 2,
            "name": "Sousou no Frieren",
            "name_cn": "葬送的芙莉莲",
            "date": "2023-09-29",
            "platform": "TV",
            "nsfw": false,
            "rating": {
                "rank": 15,
                "total": 12345,
                "score": 8.5
            },
            "tags": [
                {"name": "原创", "count": 100},
                {"name": "奇幻", "count": 200}
            ]
        }"#;

        let subject: Subject = serde_json::from_str(json).unwrap();

        assert_eq!(subject.id, 400602);
        assert_eq!(subject.subject_type, 2);
        assert_eq!(subject.name, Some("Sousou no Frieren".to_string()));
        assert_eq!(subject.name_cn, Some("葬送的芙莉莲".to_string()));
        assert_eq!(subject.date, Some("2023-09-29".to_string()));
        assert_eq!(subject.nsfw, Some(false));
        assert_eq!(subject.rating.as_ref().unwrap().rank, Some(15));
        assert_eq!(subject.tags.as_ref().unwrap().len(), 2);
    }

    #[test]
    fn test_deserialize_paged_response() {
        let json = r#"{
            "total": 100,
            "limit": 10,
            "offset": 0,
            "data": [
                {
                    "id": 400602,
                    "type": 2,
                    "name": "Sousou no Frieren"
                }
            ]
        }"#;

        let response: PagedSubject = serde_json::from_str(json).unwrap();

        assert_eq!(response.total, 100);
        assert_eq!(response.limit, 10);
        assert_eq!(response.offset, 0);
        assert_eq!(response.data.len(), 1);
        assert_eq!(response.data[0].id, 400602);
    }

    #[test]
    fn test_filter_serialization_skips_none() {
        let filter = SearchFilter::anime();
        let json = serde_json::to_string(&filter).unwrap();
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();

        // 只有 type 字段存在
        assert!(parsed.get("type").is_some());
        assert!(parsed.get("tag").is_none());
        assert!(parsed.get("air_date").is_none());
        assert!(parsed.get("nsfw").is_none());
    }
}
