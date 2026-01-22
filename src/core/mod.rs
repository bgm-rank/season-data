use crate::services::bgmtv::BgmtvClient;
use crate::services::ds::DsClient;
use crate::services::mal::{AnimeNode, MalClient, Season};
use chrono::Local;
use serde::{Deserialize, Serialize};
use std::path::Path;
use thiserror::Error;
use tokio::fs;
use tracing::{debug, info, warn};

#[derive(Error, Debug)]
pub enum CoreError {
    #[error("MAL API error: {0}")]
    Mal(#[from] crate::services::mal::MalError),
    #[error("Bangumi API error: {0}")]
    Bgmtv(#[from] crate::services::bgmtv::BgmtvError),
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
}

/// 确认状态
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum ConfirmStatus {
    /// 未确认
    #[default]
    Unconfirmed,
    /// 精确匹配（日文标题完全一致）
    Match,
    /// 模型确认（LLM 判断匹配）
    Model,
    /// 人工确认
    Human,
}

impl ConfirmStatus {
    /// 是否已确认（非 Unconfirmed）
    pub fn is_confirmed(&self) -> bool {
        !matches!(self, ConfirmStatus::Unconfirmed)
    }
}

/// 转换后的 rating 类型
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Rating {
    Kids,
    General,
    R18,
}

impl Rating {
    /// 从 MAL rating 字符串转换
    pub fn from_mal(rating: Option<&str>) -> Self {
        match rating {
            Some("g") | Some("pg") => Rating::Kids,
            Some("r+") | Some("rx") => Rating::R18,
            _ => Rating::General,
        }
    }
}

/// 转换后的 media_type
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum MediaType {
    Tv,
    Ova,
    Ona,
    Movie,
    Special,
    #[serde(rename = "tv_special")]
    TvSpecial,
}

impl MediaType {
    /// 从 MAL media_type 字符串转换，返回 None 表示应该跳过
    pub fn from_mal(media_type: Option<&str>) -> Option<Self> {
        match media_type {
            Some("tv") => Some(MediaType::Tv),
            Some("ova") => Some(MediaType::Ova),
            Some("ona") => Some(MediaType::Ona),
            Some("movie") => Some(MediaType::Movie),
            Some("special") => Some(MediaType::Special),
            Some("tv_special") => Some(MediaType::TvSpecial),
            // music, pv 等类型跳过
            _ => None,
        }
    }
}

/// MAL 条目信息
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MalInfo {
    pub id: u64,
    pub title: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title_ja: Option<String>,
    pub media_type: MediaType,
    pub rating: Rating,
}

impl MalInfo {
    /// 从 MAL AnimeNode 转换
    pub fn from_anime_node(node: &AnimeNode) -> Option<Self> {
        let media_type = MediaType::from_mal(node.media_type.as_deref())?;
        let rating = Rating::from_mal(node.rating.as_deref());
        let title_ja = node
            .alternative_titles
            .as_ref()
            .and_then(|t| t.ja.clone());

        Some(MalInfo {
            id: node.id,
            title: node.title.clone(),
            title_ja,
            media_type,
            rating,
        })
    }
}

/// Bangumi 候选条目
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BgmCandidate {
    pub bgm_id: u64,
    pub bgm_name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bgm_name_cn: Option<String>,
}

/// 季度条目
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SeasonItem {
    pub status: ConfirmStatus,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bgm_id: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bgm_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bgm_name_cn: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub candidates: Vec<BgmCandidate>,
    pub mal: MalInfo,
}

/// 季度数据
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SeasonData {
    pub season: String,
    pub update_time: String,
    pub items: Vec<SeasonItem>,
}

impl SeasonData {
    /// 创建新的季度数据
    pub fn new(year: u32, season: Season) -> Self {
        let season_str = format!("{}-{}", year, season);
        let update_time = Local::now()
            .fixed_offset()
            .format("%Y-%m-%dT%H:%M:%S%:z")
            .to_string();

        SeasonData {
            season: season_str,
            update_time,
            items: Vec::new(),
        }
    }

    /// 从文件加载
    pub async fn load(path: &Path) -> Result<Option<Self>, CoreError> {
        if !path.exists() {
            return Ok(None);
        }

        let content = fs::read_to_string(path).await?;
        if content.trim().is_empty() || content.trim() == "{}" {
            return Ok(None);
        }

        let data = serde_json::from_str(&content)?;
        Ok(Some(data))
    }

    /// 保存到文件
    pub async fn save(&self, path: &Path) -> Result<(), CoreError> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).await?;
        }

        let content = serde_json::to_string_pretty(self)?;
        fs::write(path, content).await?;
        Ok(())
    }

    /// 获取已确认的 MAL ID 集合
    pub fn confirmed_mal_ids(&self) -> std::collections::HashSet<u64> {
        self.items
            .iter()
            .filter(|item| item.status.is_confirmed())
            .map(|item| item.mal.id)
            .collect()
    }
}

/// 获取季度的日期范围
pub fn season_date_range(year: u32, season: Season) -> (String, String) {
    match season {
        // 冬季: 12月1日 ~ 3月31日
        Season::Winter => (format!("{}-12-01", year - 1), format!("{}-03-31", year)),
        // 春季: 3月1日 ~ 6月30日
        Season::Spring => (format!("{}-03-01", year), format!("{}-06-30", year)),
        // 夏季: 6月1日 ~ 9月30日
        Season::Summer => (format!("{}-06-01", year), format!("{}-09-30", year)),
        // 秋季: 9月1日 ~ 12月31日
        Season::Fall => (format!("{}-09-01", year), format!("{}-12-31", year)),
    }
}

/// 季度处理器
pub struct SeasonProcessor {
    mal_client: MalClient,
    bgm_client: BgmtvClient,
    ds_client: Option<DsClient>,
}

impl SeasonProcessor {
    pub fn new(mal_client: MalClient, bgm_client: BgmtvClient) -> Self {
        Self {
            mal_client,
            bgm_client,
            ds_client: None,
        }
    }

    /// 设置 DeepSeek 客户端（用于模型匹配验证）
    pub fn with_ds_client(mut self, ds_client: DsClient) -> Self {
        self.ds_client = Some(ds_client);
        self
    }

    /// 处理季度数据
    pub async fn process(
        &self,
        year: u32,
        season: Season,
        output_path: &Path,
    ) -> Result<SeasonData, CoreError> {
        // 尝试加载现有数据
        let existing = SeasonData::load(output_path).await?;
        let confirmed_ids = existing
            .as_ref()
            .map(|d| d.confirmed_mal_ids())
            .unwrap_or_default();

        info!(
            year = year,
            season = %season,
            confirmed_count = confirmed_ids.len(),
            "开始处理季度数据"
        );

        // 获取 MAL 季度列表
        let anime_list = self
            .mal_client
            .get_all_seasonal_anime(year, season, true)
            .await?;
        info!(total = anime_list.len(), "从 MAL 获取番组列表");

        let mut data = SeasonData::new(year, season);
        let (start_date, end_date) = season_date_range(year, season);

        for anime in anime_list {
            // 跳过续播番组（start_season 与当前季度不匹配）
            let is_new = anime
                .start_season
                .as_ref()
                .map(|s| s.year == year && s.season == season)
                .unwrap_or(false);
            if !is_new {
                debug!(id = anime.id, title = %anime.title, "跳过续播番组");
                continue;
            }

            // 转换 MAL 数据，跳过 music/pv
            let mal_info = match MalInfo::from_anime_node(&anime) {
                Some(info) => info,
                None => {
                    debug!(id = anime.id, title = %anime.title, "跳过非动画类型");
                    continue;
                }
            };

            // 如果已经确认，保留原有数据
            if confirmed_ids.contains(&mal_info.id) {
                if let Some(ref existing_data) = existing {
                    if let Some(item) = existing_data
                        .items
                        .iter()
                        .find(|i| i.mal.id == mal_info.id)
                    {
                        data.items.push(item.clone());
                        debug!(mal_id = mal_info.id, "保留已确认条目");
                        continue;
                    }
                }
            }

            // 使用日文标题搜索 Bangumi
            let search_keyword = mal_info.title_ja.as_deref().unwrap_or(&mal_info.title);
            debug!(keyword = search_keyword, mal_id = mal_info.id, "搜索 Bangumi");

            // 先限制日期搜索
            let results = self
                .bgm_client
                .search_anime_by_keyword(search_keyword, &start_date, &end_date)
                .await?;

            // 如果没有结果，不限制日期再搜一次
            let results = if results.is_empty() {
                debug!(keyword = search_keyword, "限制日期搜索无结果，回退到无限制搜索");
                self.bgm_client
                    .search_anime_by_keyword_no_date(search_keyword)
                    .await?
            } else {
                results
            };

            let candidates: Vec<_> = results
                .iter()
                .map(|s| BgmCandidate {
                    bgm_id: s.id,
                    bgm_name: s.name.clone().unwrap_or_default(),
                    bgm_name_cn: s.name_cn.clone(),
                })
                .collect();

            // 严格匹配：日文标题完全相等
            let exact_match = candidates
                .iter()
                .find(|c| Some(c.bgm_name.as_str()) == mal_info.title_ja.as_deref());

            let item = if let Some(matched) = exact_match {
                info!(
                    mal_id = mal_info.id,
                    bgm_id = matched.bgm_id,
                    name = %matched.bgm_name,
                    "完全匹配"
                );
                SeasonItem {
                    status: ConfirmStatus::Match,
                    bgm_id: Some(matched.bgm_id),
                    bgm_name: Some(matched.bgm_name.clone()),
                    bgm_name_cn: matched.bgm_name_cn.clone(),
                    candidates: vec![],
                    mal: mal_info,
                }
            } else if !candidates.is_empty() {
                // 使用 LLM 验证匹配
                let model_match = if let Some(ref ds) = self.ds_client {
                    let candidate_tuples: Vec<_> = candidates
                        .iter()
                        .map(|c| {
                            (
                                c.bgm_id,
                                c.bgm_name.as_str(),
                                c.bgm_name_cn.as_deref(),
                            )
                        })
                        .collect();

                    match ds
                        .match_anime(
                            &mal_info.title,
                            mal_info.title_ja.as_deref(),
                            &candidate_tuples,
                        )
                        .await
                    {
                        Ok(Some(bgm_id)) => {
                            candidates.iter().find(|c| c.bgm_id == bgm_id).cloned()
                        }
                        Ok(None) => None,
                        Err(e) => {
                            warn!(
                                mal_id = mal_info.id,
                                error = %e,
                                "LLM 匹配失败"
                            );
                            None
                        }
                    }
                } else {
                    None
                };

                if let Some(matched) = model_match {
                    info!(
                        mal_id = mal_info.id,
                        bgm_id = matched.bgm_id,
                        name = %matched.bgm_name,
                        "模型匹配"
                    );
                    SeasonItem {
                        status: ConfirmStatus::Model,
                        bgm_id: Some(matched.bgm_id),
                        bgm_name: Some(matched.bgm_name),
                        bgm_name_cn: matched.bgm_name_cn,
                        candidates: vec![],
                        mal: mal_info,
                    }
                } else {
                    debug!(
                        mal_id = mal_info.id,
                        candidates_count = candidates.len(),
                        "未匹配，保留候选"
                    );
                    SeasonItem {
                        status: ConfirmStatus::Unconfirmed,
                        bgm_id: None,
                        bgm_name: None,
                        bgm_name_cn: None,
                        candidates,
                        mal: mal_info,
                    }
                }
            } else {
                warn!(
                    mal_id = mal_info.id,
                    title = %mal_info.title,
                    "未找到匹配"
                );
                SeasonItem {
                    status: ConfirmStatus::Unconfirmed,
                    bgm_id: None,
                    bgm_name: None,
                    bgm_name_cn: None,
                    candidates: vec![],
                    mal: mal_info,
                }
            };

            data.items.push(item);
        }

        // 统计结果
        let match_count = data
            .items
            .iter()
            .filter(|i| i.status == ConfirmStatus::Match)
            .count();
        let model_count = data
            .items
            .iter()
            .filter(|i| i.status == ConfirmStatus::Model)
            .count();
        let human_count = data
            .items
            .iter()
            .filter(|i| i.status == ConfirmStatus::Human)
            .count();
        let unconfirmed_count = data
            .items
            .iter()
            .filter(|i| i.status == ConfirmStatus::Unconfirmed)
            .count();
        info!(
            total = data.items.len(),
            match_confirmed = match_count,
            model_confirmed = model_count,
            human_confirmed = human_count,
            unconfirmed = unconfirmed_count,
            "处理完成"
        );

        // 保存结果
        data.save(output_path).await?;
        info!(path = %output_path.display(), "已保存到文件");

        Ok(data)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_rating_from_mal() {
        assert_eq!(Rating::from_mal(Some("g")), Rating::Kids);
        assert_eq!(Rating::from_mal(Some("pg")), Rating::Kids);
        assert_eq!(Rating::from_mal(Some("pg_13")), Rating::General);
        assert_eq!(Rating::from_mal(Some("r")), Rating::General);
        assert_eq!(Rating::from_mal(Some("r+")), Rating::R18);
        assert_eq!(Rating::from_mal(Some("rx")), Rating::R18);
        assert_eq!(Rating::from_mal(None), Rating::General);
    }

    #[test]
    fn test_media_type_from_mal() {
        assert_eq!(MediaType::from_mal(Some("tv")), Some(MediaType::Tv));
        assert_eq!(MediaType::from_mal(Some("ova")), Some(MediaType::Ova));
        assert_eq!(MediaType::from_mal(Some("ona")), Some(MediaType::Ona));
        assert_eq!(MediaType::from_mal(Some("movie")), Some(MediaType::Movie));
        assert_eq!(
            MediaType::from_mal(Some("special")),
            Some(MediaType::Special)
        );
        assert_eq!(
            MediaType::from_mal(Some("tv_special")),
            Some(MediaType::TvSpecial)
        );
        // 应该跳过的类型
        assert_eq!(MediaType::from_mal(Some("music")), None);
        assert_eq!(MediaType::from_mal(Some("pv")), None);
        assert_eq!(MediaType::from_mal(None), None);
    }

    #[test]
    fn test_season_date_range() {
        let (start, end) = season_date_range(2026, Season::Winter);
        assert_eq!(start, "2025-12-01");
        assert_eq!(end, "2026-03-31");

        let (start, end) = season_date_range(2026, Season::Spring);
        assert_eq!(start, "2026-03-01");
        assert_eq!(end, "2026-06-30");

        let (start, end) = season_date_range(2026, Season::Summer);
        assert_eq!(start, "2026-06-01");
        assert_eq!(end, "2026-09-30");

        let (start, end) = season_date_range(2026, Season::Fall);
        assert_eq!(start, "2026-09-01");
        assert_eq!(end, "2026-12-31");
    }

    #[test]
    fn test_confirm_status() {
        assert!(!ConfirmStatus::Unconfirmed.is_confirmed());
        assert!(ConfirmStatus::Match.is_confirmed());
        assert!(ConfirmStatus::Model.is_confirmed());
        assert!(ConfirmStatus::Human.is_confirmed());

        // 序列化测试
        assert_eq!(
            serde_json::to_string(&ConfirmStatus::Unconfirmed).unwrap(),
            "\"unconfirmed\""
        );
        assert_eq!(
            serde_json::to_string(&ConfirmStatus::Match).unwrap(),
            "\"match\""
        );
        assert_eq!(
            serde_json::to_string(&ConfirmStatus::Model).unwrap(),
            "\"model\""
        );
        assert_eq!(
            serde_json::to_string(&ConfirmStatus::Human).unwrap(),
            "\"human\""
        );
    }

    #[test]
    fn test_season_data_serialization() {
        let mut data = SeasonData {
            season: "2026-winter".to_string(),
            update_time: "2026-01-22T10:36:29+08:00".to_string(),
            items: vec![],
        };

        data.items.push(SeasonItem {
            status: ConfirmStatus::Match,
            bgm_id: Some(400602),
            bgm_name: Some("葬送のフリーレン 第2期".to_string()),
            bgm_name_cn: Some("葬送的芙莉莲 第二季".to_string()),
            candidates: vec![],
            mal: MalInfo {
                id: 59978,
                title: "Sousou no Frieren 2nd Season".to_string(),
                title_ja: Some("葬送のフリーレン 第2期".to_string()),
                media_type: MediaType::Tv,
                rating: Rating::General,
            },
        });

        let json = serde_json::to_string_pretty(&data).unwrap();
        assert!(json.contains("\"season\": \"2026-winter\""));
        assert!(json.contains("\"bgm_id\": 400602"));
        assert!(json.contains("\"status\": \"match\""));

        // 反序列化测试
        let parsed: SeasonData = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.season, "2026-winter");
        assert_eq!(parsed.items.len(), 1);
        assert_eq!(parsed.items[0].bgm_id, Some(400602));
        assert_eq!(parsed.items[0].status, ConfirmStatus::Match);
    }

    #[test]
    fn test_mal_info_from_anime_node() {
        use crate::services::mal::{AlternativeTitles, AnimeNode};

        let node = AnimeNode {
            id: 59978,
            title: "Sousou no Frieren 2nd Season".to_string(),
            main_picture: None,
            alternative_titles: Some(AlternativeTitles {
                en: Some("Frieren Season 2".to_string()),
                ja: Some("葬送のフリーレン 第2期".to_string()),
                synonyms: vec![],
            }),
            start_date: Some("2026-01-16".to_string()),
            end_date: None,
            synopsis: None,
            media_type: Some("tv".to_string()),
            status: None,
            num_episodes: Some(12),
            start_season: None,
            broadcast: None,
            source: None,
            studios: vec![],
            rating: Some("pg_13".to_string()),
        };

        let info = MalInfo::from_anime_node(&node).unwrap();
        assert_eq!(info.id, 59978);
        assert_eq!(info.title, "Sousou no Frieren 2nd Season");
        assert_eq!(info.title_ja, Some("葬送のフリーレン 第2期".to_string()));
        assert_eq!(info.media_type, MediaType::Tv);
        assert_eq!(info.rating, Rating::General);
    }

    #[test]
    fn test_skip_music_and_pv() {
        use crate::services::mal::AnimeNode;

        let music_node = AnimeNode {
            id: 1,
            title: "Some Music".to_string(),
            main_picture: None,
            alternative_titles: None,
            start_date: None,
            end_date: None,
            synopsis: None,
            media_type: Some("music".to_string()),
            status: None,
            num_episodes: None,
            start_season: None,
            broadcast: None,
            source: None,
            studios: vec![],
            rating: None,
        };

        assert!(MalInfo::from_anime_node(&music_node).is_none());

        let pv_node = AnimeNode {
            id: 2,
            title: "Some PV".to_string(),
            main_picture: None,
            alternative_titles: None,
            start_date: None,
            end_date: None,
            synopsis: None,
            media_type: Some("pv".to_string()),
            status: None,
            num_episodes: None,
            start_season: None,
            broadcast: None,
            source: None,
            studios: vec![],
            rating: None,
        };

        assert!(MalInfo::from_anime_node(&pv_node).is_none());
    }
}
