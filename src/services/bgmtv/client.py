from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger

BASE_URL = "https://api.bgm.tv"


def _date_from_infobox(infobox: list[dict[str, Any]]) -> str | None:
    for item in infobox:
        if item.get("key") == "放送开始":
            val = item.get("value", "")
            if not isinstance(val, str):
                continue
            m = re.match(r"(\d{4})年(\d{1,2})月(?:(\d{1,2})日)?", val)
            if m:
                year, month, day = m.group(1), m.group(2), m.group(3)
                if day:
                    return f"{year}-{int(month):02d}-{int(day):02d}"
                return f"{year}-{int(month):02d}"
            m2 = re.match(r"(\d{4})年", val)
            if m2:
                return m2.group(1)
    return None


USER_AGENT = "bgm-rank/season-data (https://github.com/bgm-rank/season-data)"
MAX_RETRIES = 3
RETRY_DELAY = 1.0


@dataclass
class Subject:
    """Bangumi 条目信息。"""

    id: int
    type: int
    name: str | None = None
    name_cn: str | None = None
    summary: str | None = None
    date: str | None = None
    platform: str | None = None
    nsfw: bool | None = None
    tags: list[dict[str, Any]] | None = None

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Subject:
        date = data.get("date")
        if date is None:
            infobox = data.get("infobox") or []
            date = _date_from_infobox(infobox)
        return Subject(
            id=data["id"],
            type=data["type"],
            name=data.get("name"),
            name_cn=data.get("name_cn"),
            summary=data.get("summary"),
            date=date,
            platform=data.get("platform"),
            nsfw=data.get("nsfw"),
            tags=data.get("tags"),
        )


@dataclass
class PagedSubject:
    """分页条目响应。"""

    total: int
    limit: int
    offset: int
    data: list[Subject]

    @staticmethod
    def from_dict(data: dict[str, Any]) -> PagedSubject:
        return PagedSubject(
            total=data["total"],
            limit=data["limit"],
            offset=data["offset"],
            data=[Subject.from_dict(s) for s in data.get("data", [])],
        )


@dataclass
class SearchFilter:
    """搜索筛选器。"""

    type: list[int] | None = None
    air_date: list[str] | None = None
    nsfw: bool | None = None

    @staticmethod
    def anime() -> SearchFilter:
        return SearchFilter(type=[2])

    def with_air_date_range(self, start: str, end: str) -> SearchFilter:
        self.air_date = [f">={start}", f"<{end}"]
        return self

    def with_nsfw(self) -> SearchFilter:
        self.nsfw = True
        return self

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.type is not None:
            d["type"] = self.type
        if self.air_date is not None:
            d["air_date"] = self.air_date
        if self.nsfw is not None:
            d["nsfw"] = self.nsfw
        return d


@dataclass
class SearchRequest:
    """搜索请求。"""

    keyword: str
    sort: str = "match"
    filter: SearchFilter | None = None

    def with_filter(self, f: SearchFilter) -> SearchRequest:
        self.filter = f
        return self

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"keyword": self.keyword, "sort": self.sort}
        if self.filter is not None:
            d["filter"] = self.filter.to_dict()
        return d


class BgmtvClient:
    def __init__(self, access_token: str = "") -> None:
        headers: dict[str, str] = {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        self.client = httpx.Client(headers=headers, timeout=30.0)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> BgmtvClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def search_subjects(
        self,
        request: SearchRequest,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> PagedSubject:
        """搜索条目（带重试逻辑）。"""
        url = f"{BASE_URL}/v0/search/subjects"
        params: dict[str, int] = {}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset

        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.client.post(
                    url,
                    params=params,
                    json=request.to_dict(),
                )
                if not resp.is_success:
                    raise httpx.HTTPStatusError(
                        f"{resp.status_code}: {resp.text}",
                        request=resp.request,
                        response=resp,
                    )
                return PagedSubject.from_dict(resp.json())
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    logger.warning(
                        "请求失败 ({}), 第 {}/{} 次重试...",
                        e,
                        attempt,
                        MAX_RETRIES,
                    )
                    time.sleep(RETRY_DELAY)

        # mypy can't prove last_error is non-None here: loop runs MAX_RETRIES times and
        # always assigns last_error in the except branch, but flow analysis doesn't track that.
        raise last_error  # type: ignore[misc]

    def get_subject(self, subject_id: int) -> Subject:
        """按 ID 获取条目详情（带重试逻辑）。"""
        url = f"{BASE_URL}/v0/subjects/{subject_id}"

        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.client.get(url)
                if not resp.is_success:
                    raise httpx.HTTPStatusError(
                        f"{resp.status_code}: {resp.text}",
                        request=resp.request,
                        response=resp,
                    )
                return Subject.from_dict(resp.json())
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    logger.warning(
                        "请求失败 ({}), 第 {}/{} 次重试...",
                        e,
                        attempt,
                        MAX_RETRIES,
                    )
                    time.sleep(RETRY_DELAY)

        # mypy can't prove last_error is non-None here: loop runs MAX_RETRIES times and
        # always assigns last_error in the except branch, but flow analysis doesn't track that.
        raise last_error  # type: ignore[misc]

    def search_anime_by_keyword(
        self,
        keyword: str,
        start_date: str,
        end_date: str,
    ) -> list[Subject]:
        """按关键词搜索动画（包含 NSFW，限制日期范围）。"""
        f = SearchFilter.anime().with_air_date_range(start_date, end_date).with_nsfw()
        request = SearchRequest(keyword=keyword).with_filter(f)
        result = self.search_subjects(request, limit=10)
        return result.data

    def search_anime_by_keyword_no_date(
        self,
        keyword: str,
    ) -> list[Subject]:
        """按关键词搜索动画（包含 NSFW，不限制日期）。"""
        f = SearchFilter.anime().with_nsfw()
        request = SearchRequest(keyword=keyword).with_filter(f)
        result = self.search_subjects(request, limit=10)
        return result.data
