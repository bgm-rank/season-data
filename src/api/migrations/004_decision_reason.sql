-- 给人工决策补上「为什么」，并把 override skip 从伪装成 rule 的状态里解救出来。
--
-- 两件事：
-- A. skip 的语义是「这条番成立，但不在这一季」（位置错误），跟审核界面的 exclude
--    （「这个东西在 BGM 侧不成立」）不是一回事。原先记成 source='rule' 等于把位置错误
--    伪装成媒体类型规则过滤，事后无法回答「这条是规则踢的还是我手工挪走的」。
-- B. exclude / skip 都没有原因字段。半年后看到一条 excluded，无从知道当时是因为
--    BGM 没收录、还是 BGM 把它并进本篇的额外 ep 了。
--
-- reason 刻意不加 CHECK：取值是凭现有样例推的，接下来那次一次性清理很可能冒出新原因，
-- 而 SQLite 改 CHECK 要重建 20000 行的 season_items。约束交给 schemas.py 的 Literal
-- 和前端下拉，DB 只负责存。
--
-- 也刻意**不加** CHECK(action <> 'add' OR bgm_id IS NOT NULL)：本来打算顺手补上，
-- 但库里 11 条 add 里有 6 条 bgm_id 为空，且每条都与一条 skip 配对
-- （mal 60629 / 61303 / 58888 / 58954 / 62494 / 63096）——那是「这条番该挪到 X 季，
-- bgm_id 待查」的待办记录，不是脏数据。加约束等于把这套用法判死刑。
-- 真正的问题在 processor 的 add 分支拿到 None 之后报了个看不懂的错，已就地修掉。

ALTER TABLE season_items ADD COLUMN reason TEXT;
ALTER TABLE season_items ADD COLUMN note   TEXT;

ALTER TABLE overrides ADD COLUMN reason           TEXT;
-- 仅线索/备忘：skip 时记下「它该去哪」。刻意不加外键，目标季度可能还没建。
-- 也不做成 action='move' 自动跨季写入：skip 时未必已知 bgm_id。
ALTER TABLE overrides ADD COLUMN target_season_id TEXT;
ALTER TABLE overrides ADD COLUMN note             TEXT;
-- 老行留 NULL：真实创建时间无从得知，填迁移时间是伪造。
-- 新行由 overrides 路由显式写 ISO 时间戳（ADD COLUMN 不接受非常量默认值）。
ALTER TABLE overrides ADD COLUMN created_at       TEXT;

-- 回填 A：历史上被 skip 排除掉的行改记 human + wrong_season。
-- 条件写紧（status/source 双限），只碰确实由 skip 造成的那几行。
UPDATE season_items SET source = 'human', reason = 'wrong_season'
WHERE status = 'excluded' AND source = 'rule'
  AND (season_id, mal_id) IN (SELECT season_id, mal_id FROM overrides WHERE action = 'skip');

-- 视图重建：加 season_items 的 reason/note，并 LEFT JOIN overrides 带出人工意图。
-- override 的 reason 不冗余进 season_items（skip 落地那一次除外）——override 行是 append
-- 的意图记录、不会删，从这里 JOIN 出来即可。overrides 的主键就是 (mal_id, season_id)，
-- 一个条目最多匹配一行，不会让行数翻倍。
DROP VIEW IF EXISTS items_flat;
CREATE VIEW items_flat AS
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
       si.reason,
       si.note,
       o.action           AS override_action,
       o.reason           AS override_reason,
       o.target_season_id AS override_target_season_id,
       si.updated_at
FROM season_items si
JOIN mal_anime m USING (mal_id)
LEFT JOIN bgm_subject b ON b.bgm_id = si.bgm_id
LEFT JOIN overrides   o ON o.season_id = si.season_id AND o.mal_id = si.mal_id;
