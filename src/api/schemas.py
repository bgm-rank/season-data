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
ExcludeReason = Literal["not_on_bgm", "merged_into_ep", "not_anime", "duplicate", "wrong_season", "other"]


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


class OverrideCreate(BaseModel):
    mal_id: int
    action: OverrideAction
    bgm_id: int | None = None
    reason: ExcludeReason | None = None
    target_season_id: str | None = None
    note: str | None = None
