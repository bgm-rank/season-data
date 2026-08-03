-- 把 items 宽表拆成三张表，按数据的生命周期隔离写入边界。
--
-- 原 items 一行里塞了三类东西：MAL 事实、BGM 事实（都是可重建的缓存）、
-- 匹配决策（不可重建的人工资产）。放在同一行意味着「刷新缓存」的 SQL 物理上
-- 碰得到人工决策，只能靠记得把 15 个列名写对来防灾——而它已经失败过两次
-- （fetch 的 INSERT OR REPLACE、export/import 漏掉 bgm_air_date）。
--
-- 拆完之后 fetch 的 SQL 里根本不存在 status 这个列名，这类事故不再可能发生。

-- MAL 侧事实，可重建缓存。fetch 全权负责。
CREATE TABLE IF NOT EXISTS mal_anime (
    mal_id            INTEGER PRIMARY KEY,
    title             TEXT NOT NULL,
    title_ja          TEXT,
    title_en          TEXT,
    media_type        TEXT NOT NULL,
    rating            TEXT NOT NULL,   -- Rating.from_mal() 降维后的 kids/general/r18，非 MAL 原始值
    start_date        TEXT,
    end_date          TEXT,
    num_episodes      INTEGER,
    source            TEXT,            -- 原作类型 manga / light_novel / original ...
    studios           TEXT,            -- JSON array，MAL 原样存
    synopsis          TEXT,
    start_season_year INTEGER,
    start_season      TEXT,
    fetched_at        TEXT             -- NULL = 从旧 items 回填的骨架，MAL 详情待补
);

-- BGM 侧事实，可重建缓存。sync-bgm 与 processor 的搜索结果负责填充。
CREATE TABLE IF NOT EXISTS bgm_subject (
    bgm_id     INTEGER PRIMARY KEY,
    type       INTEGER,
    name       TEXT,
    name_cn    TEXT,
    air_date   TEXT,
    platform   TEXT,                   -- TV / 剧场版 / OVA，可与 media_type 交叉验证
    summary    TEXT,
    tags       TEXT,                   -- JSON array
    nsfw       INTEGER,
    fetched_at TEXT                    -- NULL = 骨架行，排在待同步队列里
);

-- 关联 + 决策，不可重建的资产。只有 run 和人工审核能写。
CREATE TABLE IF NOT EXISTS season_items (
    season_id  TEXT    NOT NULL REFERENCES seasons(id),
    mal_id     INTEGER NOT NULL REFERENCES mal_anime(mal_id),
    status     TEXT    NOT NULL CHECK(status IN ('pending','included','excluded')),
    source     TEXT    CHECK(source IN ('rule','exact','llm','human') OR source IS NULL),
    confidence REAL,
    -- 刻意不加 UNIQUE：MAL 拆分 / BGM 合并（剧场版、SP、分季）导致 N:1 和 1:N
    -- 现实中都合法，硬约束会挡掉正确数据。撞车只能做成质量视图，不能做成约束。
    bgm_id     INTEGER REFERENCES bgm_subject(bgm_id),
    candidates TEXT,                   -- JSON: [{bgm_id, bgm_name, air_date, confidence}]
    error      TEXT,
    origin     TEXT NOT NULL DEFAULT 'mal' CHECK(origin IN ('mal','override')),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (season_id, mal_id)
);

CREATE INDEX IF NOT EXISTS idx_si_season_status ON season_items(season_id, status);
CREATE INDEX IF NOT EXISTS idx_si_bgm           ON season_items(bgm_id) WHERE bgm_id IS NOT NULL;

-- 从旧 items 回填。顺序必须满足外键：mal_anime → bgm_subject → season_items。
-- 跨季重复的 mal_id 只有 9 个且 MAL 事实相同，GROUP BY 任取一行即可。
INSERT INTO mal_anime (mal_id, title, title_ja, media_type, rating)
SELECT mal_id, mal_title, mal_title_ja, mal_media_type, mal_rating
FROM items
GROUP BY mal_id;

-- MAX() 用于在同一 bgm_id 的多行之间取到非 NULL 的那个值。
-- fetched_at 一律留 NULL：等于把这 11068 条排进待刷队列，顺手补齐 97% 缺失的 air_date。
INSERT INTO bgm_subject (bgm_id, name, name_cn, air_date)
SELECT bgm_id, MAX(bgm_name), MAX(bgm_name_cn), MAX(bgm_air_date)
FROM items
WHERE bgm_id IS NOT NULL
GROUP BY bgm_id;

INSERT INTO season_items
    (season_id, mal_id, status, source, confidence, bgm_id, candidates, error, origin, updated_at)
SELECT season_id, mal_id, status, source, confidence, bgm_id, candidates, error, 'mal', updated_at
FROM items;

-- overrides 的 add 动作插进来的条目标记出处，取代原先靠 source='human' 猜测的做法
UPDATE season_items SET origin = 'override'
WHERE (season_id, mal_id) IN (SELECT season_id, mal_id FROM overrides WHERE action = 'add');

-- 兼容视图：把三表拼回旧 items 的扁平形状，列名与 schemas.py 的 ItemRead 一一对应。
-- 读路径走这里，前端和 API schema 一行都不用改。写路径必须指向实表。
CREATE VIEW IF NOT EXISTS items_flat AS
SELECT si.mal_id,
       si.season_id,
       si.status,
       si.source,
       si.confidence,
       si.bgm_id,
       b.name     AS bgm_name,
       b.name_cn  AS bgm_name_cn,
       b.air_date AS bgm_air_date,
       m.title      AS mal_title,
       m.title_ja   AS mal_title_ja,
       m.media_type AS mal_media_type,
       m.rating     AS mal_rating,
       si.error,
       si.candidates,
       si.origin,
       si.updated_at
FROM season_items si
JOIN mal_anime m USING (mal_id)
LEFT JOIN bgm_subject b ON b.bgm_id = si.bgm_id;

-- 旧 items 表刻意保留：切换期间它是唯一的回滚手段（单机模式下没有 data/ 兜底了）。
-- 确认稳定运行后再用单独的 004 迁移删除。
