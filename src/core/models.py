from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ConfirmStatus(Enum):
    """匹配确认状态。"""

    UNCONFIRMED = "unconfirmed"
    MATCH = "match"
    MODEL = "model"
    MODEL_SKIP = "model_skip"
    HUMAN = "human"
    HUMAN_SKIP = "human_skip"
    ERROR = "error"
    SKIP = "skip"

    def is_confirmed(self) -> bool:
        return self in (
            ConfirmStatus.MATCH,
            ConfirmStatus.MODEL,
            ConfirmStatus.MODEL_SKIP,
            ConfirmStatus.HUMAN,
            ConfirmStatus.HUMAN_SKIP,
            ConfirmStatus.SKIP,
        )

    def status_to_category(self) -> str:
        """返回状态对应的 state 子目录名。"""
        if self == ConfirmStatus.SKIP:
            return "skip"
        if self == ConfirmStatus.MATCH:
            return "match"
        if self in (ConfirmStatus.MODEL, ConfirmStatus.MODEL_SKIP):
            return "model"
        return "manual"


class Rating(Enum):
    """内容分级。"""

    KIDS = "kids"
    GENERAL = "general"
    R18 = "r18"

    @staticmethod
    def from_mal(rating: str | None) -> Rating:
        if rating in ("g", "pg"):
            return Rating.KIDS
        if rating in ("r+", "rx"):
            return Rating.R18
        return Rating.GENERAL


class MediaType(Enum):
    """媒体类型。"""

    TV = "tv"
    OVA = "ova"
    ONA = "ona"
    MOVIE = "movie"
    SPECIAL = "special"
    TV_SPECIAL = "tv_special"
    MUSIC = "music"
    PV = "pv"
    CM = "cm"

    def should_skip(self) -> bool:
        return self in (
            MediaType.SPECIAL,
            MediaType.TV_SPECIAL,
            MediaType.MUSIC,
            MediaType.PV,
            MediaType.CM,
        )

    @staticmethod
    def from_mal(media_type: str) -> MediaType:
        return MediaType(media_type)


@dataclass
class MalInfo:
    """MAL 精简信息（用于 release 输出）。"""

    id: int
    title: str
    title_ja: str | None
    media_type: str
    rating: str

    @staticmethod
    def from_raw(raw: dict[str, Any]) -> MalInfo:
        return MalInfo(
            id=raw["id"],
            title=raw["title"],
            title_ja=raw.get("alternative_titles", {}).get("ja"),
            media_type=raw["media_type"],
            rating=Rating.from_mal(raw.get("rating")).value,
        )

    @staticmethod
    def from_dict(data: dict[str, Any]) -> MalInfo:
        return MalInfo(
            id=data["id"],
            title=data["title"],
            title_ja=data.get("title_ja"),
            media_type=data["media_type"],
            rating=data["rating"],
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "media_type": self.media_type,
            "rating": self.rating,
        }
        if self.title_ja is not None:
            d["title_ja"] = self.title_ja
        return d


@dataclass
class BgmCandidate:
    """Bangumi 候选条目。"""

    bgm_id: int
    bgm_name: str | None = None
    bgm_name_cn: str | None = None

    @staticmethod
    def from_dict(data: dict[str, Any]) -> BgmCandidate:
        return BgmCandidate(
            bgm_id=data["bgm_id"],
            bgm_name=data.get("bgm_name"),
            bgm_name_cn=data.get("bgm_name_cn"),
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"bgm_id": self.bgm_id}
        if self.bgm_name is not None:
            d["bgm_name"] = self.bgm_name
        if self.bgm_name_cn is not None:
            d["bgm_name_cn"] = self.bgm_name_cn
        return d


@dataclass
class StateItem:
    """状态条目（state 文件中的单个条目）。"""

    mal_id: int
    status: ConfirmStatus
    bgm_id: int | None = None
    bgm_name: str | None = None
    bgm_name_cn: str | None = None
    mal: MalInfo | None = None
    candidates: list[BgmCandidate] | None = None

    @staticmethod
    def from_dict(data: dict[str, Any]) -> StateItem:
        candidates = None
        if "candidates" in data:
            candidates = [BgmCandidate.from_dict(c) for c in data["candidates"]]
        mal = None
        if "mal" in data:
            mal = MalInfo.from_dict(data["mal"])
        return StateItem(
            mal_id=data["mal_id"],
            status=ConfirmStatus(data["status"]),
            bgm_id=data.get("bgm_id"),
            bgm_name=data.get("bgm_name"),
            bgm_name_cn=data.get("bgm_name_cn"),
            mal=mal,
            candidates=candidates,
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "mal_id": self.mal_id,
            "status": self.status.value,
            "bgm_id": self.bgm_id,
        }
        if self.bgm_name is not None:
            d["bgm_name"] = self.bgm_name
        if self.bgm_name_cn is not None:
            d["bgm_name_cn"] = self.bgm_name_cn
        if self.mal is not None:
            d["mal"] = self.mal.to_dict()
        if self.candidates is not None:
            d["candidates"] = [c.to_dict() for c in self.candidates]
        return d


@dataclass
class StateData:
    """状态文件顶层结构。"""

    season: str
    items: list[StateItem]

    def confirmed_mal_ids(self) -> set[int]:
        return {item.mal_id for item in self.items if item.status.is_confirmed()}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> StateData:
        return StateData(
            season=data["season"],
            items=[StateItem.from_dict(i) for i in data.get("items", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "items": [i.to_dict() for i in self.items],
        }
