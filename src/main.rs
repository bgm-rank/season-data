mod core;
mod services;

use anyhow::{Context, Result};
use core::SeasonProcessor;
use services::bgmtv::BgmtvClient;
use services::mal::{MalClient, Season};
use std::path::PathBuf;
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

    let bgm_token = std::env::var("BGM_TOKEN").context("BGM_TOKEN must be set in .env")?;
    let mal_client_id =
        std::env::var("MAL_CLIENT_ID").context("MAL_CLIENT_ID must be set in .env")?;

    let bgm_client = BgmtvClient::new(bgm_token);
    let mal_client = MalClient::new(mal_client_id);

    let processor = SeasonProcessor::new(mal_client, bgm_client);

    // 处理 2026 年冬季
    let year = 2026;
    let season = Season::Winter;
    let output_path = PathBuf::from(format!("release/{}-{}-mal.json", year, season));

    info!(year = year, season = %season, "开始处理季度番组");

    let result = processor.process(year, season, &output_path).await?;

    info!(
        total = result.items.len(),
        confirmed = result.items.iter().filter(|i| i.confirmed).count(),
        "处理完成"
    );

    Ok(())
}
