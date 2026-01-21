mod core;
mod services;

use anyhow::{Context, Result};
use services::bgmtv::{BgmtvClient, SearchFilter, SearchRequest, SortOrder};
use tracing::info;

#[tokio::main]
async fn main() -> Result<()> {
    dotenvy::dotenv().ok();

    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive(tracing::Level::INFO.into()),
        )
        .init();

    let token = std::env::var("BGM_TOKEN").context("BGM_TOKEN must be set in .env")?;
    let client = BgmtvClient::new(token);

    // 搜索 NSFW 动画测试 token 认证
    // 2026年冬季番：2025-12-01 ~ 2026-03-31
    let keyword = "アンドロイドは経験人数に入りますか？？";
    let filter = SearchFilter::anime()
        .air_date_range("2025-12-01", "2026-03-31")
        .include_nsfw();
    let request = SearchRequest::new(keyword)
        .with_sort(SortOrder::Rank)
        .with_filter(filter);

    info!(keyword = keyword, "搜索 bangumi.tv...");

    let result = client.search_subjects(&request, Some(10), None).await?;

    info!(total = result.total, "搜索结果数量");

    for subject in &result.data {
        info!(
            id = subject.id,
            name = ?subject.name,
            name_cn = ?subject.name_cn,
            date = ?subject.date,
            rank = ?subject.rating.as_ref().and_then(|r| r.rank),
            score = ?subject.rating.as_ref().and_then(|r| r.score),
            "找到条目"
        );
    }

    Ok(())
}
