# Core 模块设计文档

## 数据文件

按信息源分文件存储：

- `release/2026-winter-mal.json`
- `release/2026-winter-yucwiki.json`
- `release/2026-winter-youranimes.json`

发布到 GitHub Release 时再合并。

## JSON 格式

```json
{
  "season": "2026-winter",
  "update_time": "2026-01-22T10:36:29+08:00",
  "items": [
    {
      "confirmed": true,
      "bgm_id": 400602,
      "bgm_name": "葬送のフリーレン 第2期",
      "bgm_name_cn": "葬送的芙莉莲 第二季",
      "mal": {
        "id": 59978,
        "title": "Sousou no Frieren 2nd Season",
        "title_ja": "葬送のフリーレン 第2期",
        "media_type": "tv",
        "rating": "general"
      }
    },
    {
      "confirmed": false,
      "candidates": [
        { "bgm_id": 500001, "bgm_name": "おそ松さん 第4期", "bgm_name_cn": "阿松 第四季" },
        { "bgm_id": 500002, "bgm_name": "おそ松さん", "bgm_name_cn": "阿松" }
      ],
      "mal": {
        "id": 12345,
        "title": "Osomatsu-san 4",
        "title_ja": "おそ松さん 4期",
        "media_type": "tv",
        "rating": "general"
      }
    }
  ]
}
```

## 匹配规则

### 匹配字段

- MAL: `alternative_titles.ja`
- Bangumi: `name`

### 匹配策略

1. **严格匹配**：字符串完全相等才设置 `confirmed: true`
2. **不匹配时**：保留 `candidates` 列表，留给人工/LLM 确认

### Bangumi 搜索策略

1. 先限制 `air_date` 搜索（提高多季动画匹配准确度）
2. 如果搜索结果为空，回退到不限制 `air_date`

## 字段转换

### media_type

保留：`tv`, `ova`, `ona`, `movie`, `special`, `tv_special`

丢弃（不处理）：`music`, `pv`

### rating

| MAL 原始值 | 转换后 |
| ----------- | -------- |
| `g`, `pg` | `kids` |
| `r+`, `rx` | `r18` |
| `pg_13`, `r`, 其他 | `general` |

## 增量更新

- `confirmed: true` 的记录跳过，只处理新增或未确认数据
- 通过修改 `confirmed` 字段或 patch 文件进行人工修正
