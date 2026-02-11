# Bangumi.tv API 参考

## 条目搜索 API

- **Endpoint**: `POST https://api.bgm.tv/v0/search/subjects`
- **认证**: 无需认证（公开 API）
- **User-Agent**: 必须指定，格式 `项目名 (项目主页)`

## 请求参数

### Query 参数

| 参数 | 说明 |
| ------ | ------ |
| `limit` | 每页数量 |
| `offset` | 分页偏移 |

### Request Body

```json
{
  "keyword": "搜索关键字",
  "sort": "rank",
  "filter": {
    "type": [2],
    "air_date": [">=2025-12-01", "<2026-03-31"],
    "nsfw": true
  }
}
```

## 筛选条件 (filter)

| 字段 | 说明 | 关系 |
| ------ | ------ | ------ |
| `type` | 条目类型 | 或 |
| `tag` | 用户标签 | 且 |
| `meta_tags` | 元标签 | 且 |
| `air_date` | 播出日期 | 且 |
| `rating` | 评分 | 且 |
| `rating_count` | 评分人数 | 且 |
| `rank` | 排名 | 且 |
| `nsfw` | 是否包含 NSFW | - |

**注意**: 不同筛选条件之间为 **且** 关系。

## 条目类型 (type)

| 值 | 说明 |
| ---- | ------ |
| `1` | 书籍 |
| `2` | 动画 |
| `3` | 音乐 |
| `4` | 游戏 |
| `6` | 三次元 |

## 排序规则 (sort)

| 值 | 说明 |
| ---- | ------ |
| `match` | 匹配度（默认） |
| `heat` | 收藏人数 |
| `rank` | 排名 |
| `score` | 评分 |

## 日期/数值筛选格式

支持比较运算符：`>=`, `>`, `<=`, `<`

```json
{
  "air_date": [">=2025-12-01", "<2026-03-31"],
  "rating": [">=6", "<8"],
  "rank": [">10", "<=100"]
}
```

## 返回结构

```json
{
  "total": 100,
  "limit": 10,
  "offset": 0,
  "data": [
    {
      "id": 515759,
      "type": 2,
      "name": "葬送のフリーレン 第2期",
      "name_cn": "葬送的芙莉莲 第二季",
      "date": "2026-01-16",
      "platform": "TV",
      "nsfw": false,
      "rating": {
        "rank": 189,
        "total": 1234,
        "score": 8.1
      },
      "tags": [
        {"name": "奇幻", "count": 100}
      ]
    }
  ]
}
```

## 示例请求

```bash
curl -X POST 'https://api.bgm.tv/v0/search/subjects?limit=10' \
  -H 'User-Agent: bgm-rank/season-data (https://github.com/bgm-rank/season-data)' \
  -H 'Content-Type: application/json' \
  -d '{
    "keyword": "葬送のフリーレン 第2期",
    "sort": "rank",
    "filter": {
      "type": [2],
      "air_date": [">=2025-12-01", "<2026-03-31"]
    }
  }'
```

## User-Agent 要求

必须指定带有项目信息的 User-Agent，否则可能被禁用：

```text
bgm-rank/season-data (https://github.com/bgm-rank/season-data)
```

格式建议：

- 开源项目: `用户名/项目名 (项目主页URL)`
- 分发应用: `用户名/应用名/版本号 (平台) (项目主页URL)`
- 私有项目: `用户名/my-private-project`
