from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SeasonPhase = Literal["init", "fetched", "reviewing", "done", "released"]
ItemStatus = Literal["pending", "included", "excluded"]
ItemSource = Literal["rule", "exact", "llm", "human"]
OverrideAction = Literal["add", "skip"]
# 质量问题代码，取值见 api/quality.py 的 ISSUE_KINDS
IssueKind = Literal["dup_in_season", "dup_global", "date_mismatch", "no_bgm_name"]
# 人工排除的原因。DB 侧刻意不加 CHECK（见 004 迁移），这里的 Literal 就是唯一的约束点，
# 加值只改这一行 + web/src/lib/reasons.ts。wrong_season 同时是 override skip 的原因。
# kids / mini 与 not_on_bgm 的区别是「有没有真去查过」：not_on_bgm 是确认过 BGM 上不存在，
# 这两个是按经验直接排除、没有逐条确认，分开记是为了以后能按 reason 捞出来复查。
ExcludeReason = Literal[
    "not_on_bgm", "kids", "mini", "merged_into_ep", "not_anime", "duplicate", "wrong_season", "other"
]


class SeasonSummary(BaseModel):
    id: str
    year: int
    season: str
    phase: SeasonPhase
    total_count: int
    pending_count: int
    included_count: int
    excluded_count: int
    released_at: str | None
    updated_at: str


class SeasonDetail(SeasonSummary):
    created_at: str


class SeasonCreate(BaseModel):
    year: int
    season: Literal["winter", "spring", "summer", "fall"]


class ItemRead(BaseModel):
    mal_id: int
    season_id: str
    status: ItemStatus
    source: ItemSource | None
    confidence: float | None
    bgm_id: int | None
    bgm_name: str | None
    bgm_name_cn: str | None
    mal_title: str
    mal_title_ja: str | None
    mal_media_type: str
    mal_rating: str
    error: str | None
    candidates: list[dict[str, object]] | None
    bgm_air_date: str | None
    # 人工 exclude 的原因；status != 'excluded' 时恒为 None
    reason: ExcludeReason | None = None
    note: str | None = None
    # 从 overrides JOIN 出来的人工意图，只读（写 override 走 overrides 路由）
    override_action: OverrideAction | None = None
    override_reason: ExcludeReason | None = None
    override_target_season_id: str | None = None
    updated_at: str
    # 派生的质量问题，不落库，每次读时算（见 api/quality.py）
    issues: list[IssueKind] = Field(default_factory=list)


class ItemDetailRead(ItemRead):
    """单条详情，比列表多出三张表的扩展字段。

    这些列刻意不进 items_flat 视图——视图列与 ItemRead 一一对应是拆表时定下的边界
    （见 003_split_tables.sql）。详情路由自己 JOIN 四张实表查单行，所以列表响应
    体积不变：synopsis + summary + tags 乘以 300 条会让列表从几百 KB 涨到数 MB。
    """

    origin: str
    # mal_anime 扩展（backfill_mal.py 回填的那批）
    mal_title_en: str | None = None
    mal_start_date: str | None = None
    mal_end_date: str | None = None
    mal_num_episodes: int | None = None
    # 原作类型（manga/light_novel/...）。与 season_items.source 撞名，故加前缀
    mal_source: str | None = None
    mal_studios: list[dict[str, object]] | None = None
    mal_synopsis: str | None = None
    mal_fetched_at: str | None = None
    # bgm_subject 扩展
    bgm_type: int | None = None
    bgm_platform: str | None = None
    bgm_summary: str | None = None
    bgm_tags: list[dict[str, object]] | None = None
    bgm_nsfw: int | None = None
    # NULL 表示骨架行（只有 ID，详情待拉）
    bgm_fetched_at: str | None = None
    # overrides 的剩余列，视图只带出了 action/reason/target_season_id
    override_bgm_id: int | None = None
    override_note: str | None = None
    override_created_at: str | None = None


class ItemListResponse(BaseModel):
    """列表信封。

    total 是满足筛选的总数、不受 limit 影响——旧版返回裸数组，前端无从知道
    自己被截断了，51 个季度的尾巴就这么消失了。
    issue_counts 始终是全季计数（不受 issue 筛选影响），供前端 tab 显示数量。
    """

    total: int
    limit: int
    offset: int
    items: list[ItemRead]
    issue_counts: dict[str, int] = Field(default_factory=dict)


class ItemUpdate(BaseModel):
    action: Literal["include", "exclude", "pending"]
    bgm_id: int | None = None
    # 只对 action='exclude' 有意义，允许不填；其余 action 传了会 422
    reason: ExcludeReason | None = None
    note: str | None = None


class OverrideRead(BaseModel):
    mal_id: int
    season_id: str
    action: OverrideAction
    bgm_id: int | None
    reason: ExcludeReason | None = None
    # skip 时的线索：这条番该去哪个季度。不做成自动跨季写入，只供将来查待办
    target_season_id: str | None = None
    note: str | None = None
    created_at: str | None = None
    # 以下两个是读时 JOIN 出来的派生字段，不落库
    mal_title: str | None = None
    # False = 这条 override 还没落进 season_items（等 run 才会插进来）。
    # 前端靠它把「孤儿 override」合成伪行插进列表
    in_season_items: bool = True


class OverrideCreate(BaseModel):
    mal_id: int
    action: OverrideAction
    bgm_id: int | None = None
    reason: ExcludeReason | None = None
    target_season_id: str | None = None
    note: str | None = None
