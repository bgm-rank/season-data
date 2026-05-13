from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("/bgm/search")
def search_bgm(
    q: str = Query(..., description="搜索关键词"),
    season: str | None = Query(default=None, description="季度 ID，用于过滤"),
) -> list[dict[str, Any]]:
    bgm_token = os.getenv("BGM_TOKEN", "")

    from core.season import season_date_range
    from services.bgmtv import BgmtvClient

    try:
        with BgmtvClient(bgm_token) as client:
            subjects = []
            if season:
                try:
                    year_str, season_str = season.split("-", 1)
                    start_date, end_date = season_date_range(int(year_str), season_str)
                    subjects = client.search_anime_by_keyword(q, start_date, end_date)
                except Exception:
                    pass
            if not subjects:
                subjects = client.search_anime_by_keyword_no_date(q)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Bangumi API error: {e}") from e

    return [
        {
            "bgm_id": s.id,
            "bgm_name": s.name,
            "bgm_name_cn": s.name_cn,
            "air_date": s.date,
            "media_type": s.platform,
        }
        for s in subjects
    ]
