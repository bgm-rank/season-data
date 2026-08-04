"""included 条目的质量检查。

匹配管线会把明显错的东西也标成 included（撞车的 bgm_id、日期对不上的条目），
而列表里它们和正确条目长得一模一样。这里把「纯 SQL 就能查出来的可疑」标出来，
让二次审核有筛选维度。

刻意不做成 DB 约束：MAL 拆分 / BGM 合并导致 N:1 和 1:N 现实中都合法，
硬 UNIQUE 会挡掉正确数据（见 003_split_tables.sql 的注释）。只能是质量视图。

全部是派生数据，不落库，每次读时算。单季 4 条 SQL 都走索引，实测 <2ms。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from core.season import season_date_range

ISSUE_KINDS: tuple[str, ...] = ("dup_in_season", "dup_global", "date_mismatch", "no_bgm_name")

# air_date 有 YYYY / YYYY-MM / YYYY-MM-DD 三种精度（见 services/bgmtv/client.py
# 的 _date_from_infobox）。短格式展开成区间，再用「区间重叠」判定，
# 避免把「2023」这种只精确到年的条目误判成日期不符。
_DATE_LO = (
    "CASE length(b.air_date) WHEN 4 THEN b.air_date || '-01-01' WHEN 7 THEN b.air_date || '-01' ELSE b.air_date END"
)
_DATE_HI = (
    "CASE length(b.air_date) WHEN 4 THEN b.air_date || '-12-31' WHEN 7 THEN b.air_date || '-31' ELSE b.air_date END"
)

# 同季 bgm_id 被多条 MAL 条目占用——至少一半是错的
_SQL_DUP_IN_SEASON = """
SELECT si.mal_id FROM season_items si
WHERE si.season_id = ? AND si.status = 'included' AND si.bgm_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM season_items o
              WHERE o.season_id = si.season_id AND o.status = 'included'
                AND o.bgm_id = si.bgm_id AND o.mal_id <> si.mal_id)
"""

# 该 bgm_id 在别的季度也被 included。严格排除同季，与 dup_in_season 不重叠，
# 两个 badge 可以并存。走 idx_si_bgm 这个全局 partial index。
_SQL_DUP_GLOBAL = """
SELECT si.mal_id FROM season_items si
WHERE si.season_id = ? AND si.status = 'included' AND si.bgm_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM season_items o
              WHERE o.status = 'included' AND o.bgm_id = si.bgm_id
                AND o.season_id <> si.season_id)
"""

# BGM 播出日期与季度范围没有交集
_SQL_DATE_MISMATCH = f"""
SELECT si.mal_id FROM season_items si
JOIN bgm_subject b ON b.bgm_id = si.bgm_id
WHERE si.season_id = ? AND si.status = 'included'
  AND b.air_date IS NOT NULL AND b.air_date <> ''
  AND NOT ({_DATE_HI} >= ? AND {_DATE_LO} <= ?)
"""

# included 却拿不到 BGM 名：要么 bgm_id 为空，要么还是只有 ID 的骨架行
_SQL_NO_BGM_NAME = """
SELECT si.mal_id FROM season_items si
LEFT JOIN bgm_subject b ON b.bgm_id = si.bgm_id
WHERE si.season_id = ? AND si.status = 'included'
  AND (si.bgm_id IS NULL OR b.name IS NULL OR b.name = '')
"""


def season_issue_map(conn: sqlite3.Connection, season_id: str) -> dict[int, list[str]]:
    """mal_id -> 命中的 issue 代码列表。没问题的条目不出现在结果里。"""
    row = conn.execute("SELECT year, season FROM seasons WHERE id = ?", (season_id,)).fetchone()
    if row is None:
        return {}
    start, end = season_date_range(row["year"], row["season"])

    queries: list[tuple[str, str, tuple[object, ...]]] = [
        ("dup_in_season", _SQL_DUP_IN_SEASON, (season_id,)),
        ("dup_global", _SQL_DUP_GLOBAL, (season_id,)),
        ("date_mismatch", _SQL_DATE_MISMATCH, (season_id, start, end)),
        ("no_bgm_name", _SQL_NO_BGM_NAME, (season_id,)),
    ]

    result: dict[int, list[str]] = {}
    for kind, sql, params in queries:
        for r in conn.execute(sql, params):
            result.setdefault(r["mal_id"], []).append(kind)
    return result


def issue_counts(issue_map: Mapping[int, list[str]]) -> dict[str, int]:
    """每类 issue 命中多少条目，供前端 tab 显示数量。未命中的类也给 0。"""
    counts = dict.fromkeys(ISSUE_KINDS, 0)
    for kinds in issue_map.values():
        for kind in kinds:
            counts[kind] += 1
    return counts


def item_issues(conn: sqlite3.Connection, season_id: str, mal_id: int) -> list[str]:
    """单条重算。PATCH / sync-bgm 的返回值要带上它，否则前端做局部替换时会把
    badge 洗掉。单季全量算一遍也才几毫秒，不值得为单条写四条特化 SQL。"""
    return season_issue_map(conn, season_id).get(mal_id, [])
