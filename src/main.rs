mod services;

use services::mal::{MalClient, Season};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    dotenvy::dotenv().ok();

    let client_id =
        std::env::var("MYANIMELIST_CLIENT_ID").expect("MYANIMELIST_CLIENT_ID must be set in .env");

    let client = MalClient::new(client_id);

    // 获取 2026 年冬季新番（包含 NSFW）
    println!("正在获取 2026 年冬季新番（nsfw=true）...");
    let anime_list = client.get_all_seasonal_anime(2026, Season::Winter, true).await?;

    println!("共获取到 {} 部新番:\n", anime_list.len());

    // 搜索特定动画
    let search = "android";
    println!("搜索 '{}':", search);
    for anime in &anime_list {
        if anime.title.to_lowercase().contains(search) {
            println!("  找到: [{}] {} | rating: {:?}", anime.id, anime.title, anime.rating);
        }
    }

    // 显示所有 r+ 评级
    println!("\n=== r+ 评级的动画 ===");
    for anime in &anime_list {
        if anime.rating.as_deref() == Some("r+") {
            println!("  [{}] {}", anime.id, anime.title);
        }
    }

    println!("\n=== rating 统计 ===");
    let mut rating_count: std::collections::HashMap<String, u32> = std::collections::HashMap::new();
    for anime in &anime_list {
        let rating = anime.rating.clone().unwrap_or("-".to_string());
        *rating_count.entry(rating).or_default() += 1;
    }
    let mut ratings: Vec<_> = rating_count.iter().collect();
    ratings.sort_by(|a, b| b.1.cmp(a.1));
    for (r, c) in ratings {
        println!("  {}: {}", r, c);
    }

    Ok(())
}
