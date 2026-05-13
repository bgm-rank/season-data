from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.db import derive_phase
from api.schemas import SeasonCreate, SeasonDetail, SeasonSummary

router = APIRouter()


def _get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db  # type: ignore[no-any-return]


def _season_stats(conn: sqlite3.Connection, season_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN source IS NULL THEN 1 ELSE 0 END) AS unprocessed,
            SUM(CASE WHEN status = 'pending'  THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN status = 'included' THEN 1 ELSE 0 END) AS included,
            SUM(CASE WHEN status = 'excluded' THEN 1 ELSE 0 END) AS excluded
        FROM items WHERE season_id = ?
        """,
        (season_id,),
    ).fetchone()
    return {
        "total": row["total"] or 0,
        "unprocessed": row["unprocessed"] or 0,
        "pending": row["pending"] or 0,
        "included": row["included"] or 0,
        "excluded": row["excluded"] or 0,
    }


def _row_to_summary(conn: sqlite3.Connection, row: sqlite3.Row) -> SeasonSummary:
    season_id = row["id"]
    stats = _season_stats(conn, season_id)
    phase = derive_phase(stats["total"], stats["unprocessed"], stats["pending"], row["released_at"])
    return SeasonSummary(
        id=season_id,
        year=row["year"],
        season=row["season"],
        phase=phase,  # type: ignore[arg-type]
        total_count=stats["total"],
        pending_count=stats["pending"],
        included_count=stats["included"],
        excluded_count=stats["excluded"],
        released_at=row["released_at"],
        updated_at=row["updated_at"],
    )


def _row_to_detail(conn: sqlite3.Connection, row: sqlite3.Row) -> SeasonDetail:
    season_id = row["id"]
    stats = _season_stats(conn, season_id)
    phase = derive_phase(stats["total"], stats["unprocessed"], stats["pending"], row["released_at"])
    return SeasonDetail(
        id=season_id,
        year=row["year"],
        season=row["season"],
        phase=phase,  # type: ignore[arg-type]
        total_count=stats["total"],
        pending_count=stats["pending"],
        included_count=stats["included"],
        excluded_count=stats["excluded"],
        released_at=row["released_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("/seasons", response_model=list[SeasonSummary])
def list_seasons(db: sqlite3.Connection = Depends(_get_db)) -> list[SeasonSummary]:
    rows = db.execute(
        "SELECT * FROM seasons ORDER BY year DESC,"
        " CASE season WHEN 'fall' THEN 4 WHEN 'summer' THEN 3 WHEN 'spring' THEN 2 WHEN 'winter' THEN 1 END DESC"
    ).fetchall()
    return [_row_to_summary(db, row) for row in rows]


@router.post("/seasons", response_model=SeasonDetail, status_code=201)
def create_season(body: SeasonCreate, db: sqlite3.Connection = Depends(_get_db)) -> SeasonDetail:
    season_id = f"{body.year}-{body.season}"
    now = datetime.now(UTC).isoformat()
    try:
        db.execute(
            "INSERT INTO seasons (id, year, season, released_at, created_at, updated_at) VALUES (?,?,?,NULL,?,?)",
            (season_id, body.year, body.season, now, now),
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail=f"Season {season_id} already exists") from exc
    row = db.execute("SELECT * FROM seasons WHERE id = ?", (season_id,)).fetchone()
    return _row_to_detail(db, row)


@router.get("/seasons/{season_id}", response_model=SeasonDetail)
def get_season(season_id: str, db: sqlite3.Connection = Depends(_get_db)) -> SeasonDetail:
    row = db.execute("SELECT * FROM seasons WHERE id = ?", (season_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Season {season_id} not found")
    return _row_to_detail(db, row)


@router.post("/seasons/{season_id}/fetch")
def fetch_season(
    season_id: str,
    db: sqlite3.Connection = Depends(_get_db),
) -> dict[str, int]:
    from core.models import Rating
    from core.season import is_new_anime
    from services.mal import MalClient

    row = db.execute("SELECT * FROM seasons WHERE id = ?", (season_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Season {season_id} not found")

    mal_client_id = os.getenv("MAL_CLIENT_ID", "")
    if not mal_client_id:
        raise HTTPException(status_code=502, detail="MAL_CLIENT_ID not configured")

    year: int = row["year"]
    season: str = row["season"]
    try:
        with MalClient(mal_client_id) as client:
            items = client.get_all_seasonal_anime(year, season)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MAL API error: {e}") from e

    now = datetime.now(UTC).isoformat()
    count = 0
    for raw in items:
        if not is_new_anime(raw, year, season):
            continue
        mal_id: int = raw["id"]
        mal_title: str = raw.get("title", "")
        mal_title_ja: str | None = raw.get("alternative_titles", {}).get("ja")
        mal_media_type: str = raw.get("media_type", "tv")
        mal_rating: str = Rating.from_mal(raw.get("rating")).value

        db.execute(
            """
            INSERT OR REPLACE INTO items
              (mal_id, season_id, status, source, confidence, bgm_id, bgm_name, bgm_name_cn,
               mal_title, mal_title_ja, mal_media_type, mal_rating, error, candidates, updated_at)
            VALUES (?,?,?,NULL,NULL,NULL,NULL,NULL,?,?,?,?,NULL,NULL,?)
            """,
            (mal_id, season_id, "pending", mal_title, mal_title_ja, mal_media_type, mal_rating, now),
        )
        count += 1

    db.execute("UPDATE seasons SET updated_at = ? WHERE id = ?", (now, season_id))
    db.commit()
    return {"fetched_count": count}
