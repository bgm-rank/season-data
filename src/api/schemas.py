from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

SeasonPhase = Literal["init", "fetched", "reviewing", "done", "released"]
ItemStatus = Literal["pending", "included", "excluded"]
ItemSource = Literal["rule", "exact", "llm", "human"]
OverrideAction = Literal["add", "skip"]


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
    updated_at: str


class ItemUpdate(BaseModel):
    action: Literal["include", "exclude"]
    bgm_id: int | None = None


class OverrideRead(BaseModel):
    mal_id: int
    season_id: str
    action: OverrideAction
    bgm_id: int | None


class OverrideCreate(BaseModel):
    mal_id: int
    action: OverrideAction
    bgm_id: int | None = None
