# Release Data

## 目录结构

```txt
release/
├── {year}/{year}-{season}-mal.json   # 原始数据
├── all-seasons.json                   # 压缩合并后的数据
└── merge_release.py                   # 合并脚本
```

## 原始数据格式 (`{year}-{season}-mal.json`)

```json
{
  "season": "2000-winter",
  "update_time": "2026-02-03T16:26:38+08:00",
  "items": [
    {
      "status": "match",
      "bgm_id": 2979,
      "bgm_name": "勇者王ガオガイガーFINAL",
      "bgm_name_cn": "勇者王GaoGaiGar Final",
      "mal": {
        "id": 1382,
        "title": "Yuusha-Ou GaoGaiGar Final",
        "title_ja": "勇者王ガオガイガーFINAL",
        "media_type": "ova",
        "rating": "general"
      }
    }
  ]
}
```

`status`: `match` | `model` | `human` | `unconfirmed` | `error` | `skip`

| status | 含义 |
| ------ | ------ |
| match | 完全匹配 |
| model | 大模型校对 |
| human | 人工校对 |
| unconfirmed | 未校对 |
| error | API请求错误 |
| skip | 跳过（bangumi没有对应条目/tv_special/special/pv/music） |

## 压缩格式 (`all-seasons.json`)

```json
{"2000":{"1":[{"id":2979,"m":"ova","r":"gnr"}]}}
```

| 原始 | 压缩 |
| ------ | ------ |
| winter / spring / summer / fall | 1 / 4 / 7 / 10 |
| media_type | m |
| rating | r |
| general | gnr |

`id` 为 `bgm_id`。跳过 `status` 为 `unconfirmed` 或 `error` 或 `skip` 的条目。

## 生成

```bash
python release/merge_release.py > release/all-seasons.json
```
