mod services;

use anyhow::{Context, Result};
use services::mal::{MalClient, Season};
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

    let client_id = std::env::var("MYANIMELIST_CLIENT_ID")
        .context("MYANIMELIST_CLIENT_ID must be set in .env")?;

    let client = MalClient::new(client_id);

    // 获取 2026 年冬季新番（包含 NSFW）
    info!("正在获取 2026 年冬季新番（nsfw=true）...");
    let anime_list = client
        .get_all_seasonal_anime(2026, Season::Winter, true)
        .await?;

    info!(count = anime_list.len(), "获取新番完成");

    // 搜索特定动画
    let search = "android";
    info!(keyword = search, "搜索动画");
    for anime in &anime_list {
        if anime.title.to_lowercase().contains(search) {
            info!(id = anime.id, title = %anime.title, rating = ?anime.rating, "找到匹配");
        }
    }

    // 显示所有 r+ 评级
    info!("=== r+ 评级的动画 ===");
    for anime in &anime_list {
        if anime.rating.as_deref() == Some("r+") {
            info!(id = anime.id, title = %anime.title, "r+ 评级");
        }
    }

    info!("=== rating 统计 ===");
    let mut rating_count: std::collections::HashMap<String, u32> = std::collections::HashMap::new();
    for anime in &anime_list {
        let rating = anime.rating.clone().unwrap_or("-".to_string());
        *rating_count.entry(rating).or_default() += 1;
    }
    let mut ratings: Vec<_> = rating_count.iter().collect();
    ratings.sort_by(|a, b| b.1.cmp(a.1));
    for (r, c) in ratings {
        info!(rating = r, count = c, "统计");
    }

    Ok(())
}
