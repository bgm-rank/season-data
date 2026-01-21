use reqwest::Client;
use serde::{Deserialize, Serialize};
use thiserror::Error;

const BASE_URL: &str = "https://api.myanimelist.net/v2";

/// 请求的字段列表
const FIELDS: &str = "id,title,alternative_titles,start_date,end_date,synopsis,media_type,status,num_episodes,start_season,broadcast,source,studios,rating";

#[derive(Error, Debug)]
pub enum MalError {
    #[error("HTTP request failed: {0}")]
    Request(#[from] reqwest::Error),
    #[error("API error: {0}")]
    Api(String),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Season {
    Winter,
    Spring,
    Summer,
    Fall,
}

impl std::fmt::Display for Season {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Season::Winter => write!(f, "winter"),
            Season::Spring => write!(f, "spring"),
            Season::Summer => write!(f, "summer"),
            Season::Fall => write!(f, "fall"),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AlternativeTitles {
    #[serde(default)]
    pub en: Option<String>,
    #[serde(default)]
    pub ja: Option<String>,
    #[serde(default)]
    pub synonyms: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StartSeason {
    pub year: u32,
    pub season: Season,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Broadcast {
    #[serde(default)]
    pub day_of_the_week: Option<String>,
    #[serde(default)]
    pub start_time: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Studio {
    pub id: u64,
    pub name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MainPicture {
    pub medium: String,
    pub large: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnimeNode {
    pub id: u64,
    pub title: String,
    #[serde(default)]
    pub main_picture: Option<MainPicture>,
    #[serde(default)]
    pub alternative_titles: Option<AlternativeTitles>,
    #[serde(default)]
    pub start_date: Option<String>,
    #[serde(default)]
    pub end_date: Option<String>,
    #[serde(default)]
    pub synopsis: Option<String>,
    #[serde(default)]
    pub media_type: Option<String>,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub num_episodes: Option<u32>,
    #[serde(default)]
    pub start_season: Option<StartSeason>,
    #[serde(default)]
    pub broadcast: Option<Broadcast>,
    #[serde(default)]
    pub source: Option<String>,
    #[serde(default)]
    pub studios: Vec<Studio>,
    #[serde(default)]
    pub rating: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnimeEntry {
    pub node: AnimeNode,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Paging {
    #[serde(default)]
    pub next: Option<String>,
    #[serde(default)]
    pub previous: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SeasonInfo {
    pub year: u32,
    pub season: Season,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SeasonalAnimeResponse {
    pub data: Vec<AnimeEntry>,
    pub paging: Paging,
    #[serde(default)]
    pub season: Option<SeasonInfo>,
}

pub struct MalClient {
    client: Client,
    client_id: String,
}

impl MalClient {
    pub fn new(client_id: String) -> Self {
        Self {
            client: Client::new(),
            client_id,
        }
    }

    /// 获取指定季度的新番列表
    ///
    /// - `nsfw`: 是否包含 NSFW 内容 (true = 包含 r+/rx 评级)
    pub async fn get_seasonal_anime(
        &self,
        year: u32,
        season: Season,
        limit: Option<u32>,
        offset: Option<u32>,
        nsfw: bool,
    ) -> Result<SeasonalAnimeResponse, MalError> {
        let url = format!("{}/anime/season/{}/{}", BASE_URL, year, season);

        let mut request = self
            .client
            .get(&url)
            .header("X-MAL-CLIENT-ID", &self.client_id)
            .query(&[("fields", FIELDS)]);

        if nsfw {
            request = request.query(&[("nsfw", "true")]);
        }
        if let Some(limit) = limit {
            request = request.query(&[("limit", limit.min(500))]);
        }
        if let Some(offset) = offset {
            request = request.query(&[("offset", offset)]);
        }

        let response = request.send().await?;

        if !response.status().is_success() {
            let status = response.status();
            let text = response.text().await.unwrap_or_default();
            return Err(MalError::Api(format!("{}: {}", status, text)));
        }

        let result = response.json::<SeasonalAnimeResponse>().await?;
        Ok(result)
    }

    /// 获取指定季度的所有新番（自动分页）
    ///
    /// - `nsfw`: 是否包含 NSFW 内容 (true = 包含 r+/rx 评级)
    pub async fn get_all_seasonal_anime(
        &self,
        year: u32,
        season: Season,
        nsfw: bool,
    ) -> Result<Vec<AnimeNode>, MalError> {
        let mut all_anime = Vec::new();
        let mut offset = 0u32;
        let limit = 500u32;

        loop {
            let response = self
                .get_seasonal_anime(year, season, Some(limit), Some(offset), nsfw)
                .await?;

            let count = response.data.len();
            for entry in response.data {
                all_anime.push(entry.node);
            }

            if response.paging.next.is_none() || count < limit as usize {
                break;
            }

            offset += limit;
        }

        Ok(all_anime)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_season_display() {
        assert_eq!(Season::Winter.to_string(), "winter");
        assert_eq!(Season::Spring.to_string(), "spring");
        assert_eq!(Season::Summer.to_string(), "summer");
        assert_eq!(Season::Fall.to_string(), "fall");
    }

    #[test]
    fn test_deserialize_anime_node() {
        let json = r#"{
            "id": 59978,
            "title": "Sousou no Frieren 2nd Season",
            "alternative_titles": {
                "en": "Frieren: Beyond Journey's End Season 2",
                "ja": "葬送のフリーレン 第2期",
                "synonyms": ["Frieren at the Funeral Season 2"]
            },
            "start_date": "2026-01-16",
            "media_type": "tv",
            "status": "currently_airing",
            "num_episodes": 10,
            "source": "manga",
            "studios": [{ "id": 11, "name": "Madhouse" }],
            "rating": "pg_13"
        }"#;

        let node: AnimeNode = serde_json::from_str(json).unwrap();

        assert_eq!(node.id, 59978);
        assert_eq!(node.title, "Sousou no Frieren 2nd Season");
        assert_eq!(
            node.alternative_titles.as_ref().unwrap().ja,
            Some("葬送のフリーレン 第2期".to_string())
        );
        assert_eq!(node.start_date, Some("2026-01-16".to_string()));
        assert_eq!(node.media_type, Some("tv".to_string()));
        assert_eq!(node.num_episodes, Some(10));
        assert_eq!(node.studios.len(), 1);
        assert_eq!(node.studios[0].name, "Madhouse");
        assert_eq!(node.rating, Some("pg_13".to_string()));
    }

    #[test]
    fn test_deserialize_rating_values() {
        // 测试各种 rating 值
        let ratings = ["g", "pg", "pg_13", "r", "r+", "rx"];

        for rating in ratings {
            let json = format!(r#"{{"id": 1, "title": "Test", "rating": "{}"}}"#, rating);
            let node: AnimeNode = serde_json::from_str(&json).unwrap();
            assert_eq!(node.rating, Some(rating.to_string()));
        }
    }

    #[test]
    fn test_deserialize_media_type_values() {
        // 测试各种 media_type 值
        let types = [
            "tv",
            "ona",
            "ova",
            "movie",
            "special",
            "tv_special",
            "music",
            "pv",
        ];

        for media_type in types {
            let json = format!(
                r#"{{"id": 1, "title": "Test", "media_type": "{}"}}"#,
                media_type
            );
            let node: AnimeNode = serde_json::from_str(&json).unwrap();
            assert_eq!(node.media_type, Some(media_type.to_string()));
        }
    }

    #[test]
    fn test_deserialize_seasonal_response() {
        let json = r#"{
            "data": [
                {
                    "node": {
                        "id": 59978,
                        "title": "Sousou no Frieren 2nd Season"
                    }
                }
            ],
            "paging": {
                "next": "https://api.myanimelist.net/v2/anime/season/2026/winter?offset=1"
            },
            "season": {
                "year": 2026,
                "season": "winter"
            }
        }"#;

        let response: SeasonalAnimeResponse = serde_json::from_str(json).unwrap();

        assert_eq!(response.data.len(), 1);
        assert_eq!(response.data[0].node.id, 59978);
        assert!(response.paging.next.is_some());
        assert_eq!(response.season.as_ref().unwrap().year, 2026);
        assert_eq!(response.season.as_ref().unwrap().season, Season::Winter);
    }
}
