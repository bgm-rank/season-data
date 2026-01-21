# MAL API 参考

## 季度新番 API

- **Endpoint**: `GET https://api.myanimelist.net/v2/anime/season/{year}/{season}`
- **认证**: `X-MAL-CLIENT-ID` header（无需 OAuth）
- **季度**: `winter`, `spring`, `summer`, `fall`

## 请求参数

| 参数 | 说明 |
| ------ | ------ |
| `fields` | 返回字段列表（逗号分隔） |
| `limit` | 每页数量，最大 500 |
| `offset` | 分页偏移 |
| `nsfw` | 设为 `true` 可返回 R+/Rx 内容（默认过滤） |

## 返回字段

```text
id, title, alternative_titles, start_date, end_date, synopsis,
media_type, status, num_episodes, start_season, broadcast, source, studios, rating
```

## media_type 类型

| 值 | 说明 |
| ---- | ------ |
| `tv` | TV 动画 |
| `ona` | 网络动画 |
| `ova` | OVA |
| `movie` | 剧场版 |
| `special` | 特别篇 |
| `tv_special` | TV 特别篇 |
| `music` | 音乐 MV |
| `pv` | 宣传片 |

## rating 年龄分级

| 值 | 说明 | 备注 |
| ---- | ------ | ------ |
| `g` | 全年龄 | Kids 内容 |
| `pg` | 家长指导 | |
| `pg_13` | 13岁以上 | 大部分新番 |
| `r` | 17+（暴力/粗话） | |
| `r+` | 17+（轻度裸露） | 需 `nsfw=true` |
| `rx` | R18/Hentai | 需 `nsfw=true` |

## 示例返回

```json
{
  "node": {
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
  }
}
```

**注意**: seasonal API 返回字段已足够丰富，无需额外调用 anime detail 接口。
