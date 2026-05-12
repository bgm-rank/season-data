from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.schemas import ItemRead, ItemUpdate

router = APIRouter()


def _get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db  # type: ignore[no-any-return]


def _row_to_item(row: sqlite3.Row) -> ItemRead:
    candidates_raw = row["candidates"]
    candidates: list[dict[str, Any]] | None = json.loads(candidates_raw) if candidates_raw else None
    return ItemRead(
        mal_id=row["mal_id"],
        season_id=row["season_id"],
        status=row["status"],
        source=row["source"],
        confidence=row["confidence"],
        bgm_id=row["bgm_id"],
        bgm_name=row["bgm_name"],
        bgm_name_cn=row["bgm_name_cn"],
        mal_title=row["mal_title"],
        mal_title_ja=row["mal_title_ja"],
        mal_media_type=row["mal_media_type"],
        mal_rating=row["mal_rating"],
        error=row["error"],
        candidates=candidates,
        updated_at=row["updated_at"],
    )


@router.get("/seasons/{season_id}/items", response_model=list[ItemRead])
def list_items(
    season_id: str,
    db: sqlite3.Connection = Depends(_get_db),
    status: str | None = Query(default=None),
    source: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1),
    offset: int = Query(default=0, ge=0),
) -> list[ItemRead]:
    clauses = ["season_id = ?"]
    params: list[Any] = [season_id]

    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if source is not None:
        clauses.append("source = ?")
        params.append(source)

    where = " AND ".join(clauses)
    order = "confidence ASC NULLS LAST" if status == "pending" else "mal_id ASC"

    rows = db.execute(
        f"SELECT * FROM items WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return [_row_to_item(r) for r in rows]


@router.patch("/seasons/{season_id}/items/{mal_id}", response_model=ItemRead)
def update_item(
    season_id: str,
    mal_id: int,
    body: ItemUpdate,
    db: sqlite3.Connection = Depends(_get_db),
) -> ItemRead:
    row = db.execute(
        "SELECT * FROM items WHERE mal_id = ? AND season_id = ?",
        (mal_id, season_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Item {mal_id} not found in season {season_id}")

    now = datetime.now(UTC).isoformat()

    if body.action == "include":
        if body.bgm_id is None:
            raise HTTPException(status_code=422, detail="bgm_id is required for action=include")
        db.execute(
            "UPDATE items SET status='included', source='human', bgm_id=?, updated_at=? WHERE mal_id=? AND season_id=?",
            (body.bgm_id, now, mal_id, season_id),
        )
    else:
        db.execute(
            "UPDATE items SET status='excluded', source='human', updated_at=? WHERE mal_id=? AND season_id=?",
            (now, mal_id, season_id),
        )

    db.execute("UPDATE seasons SET updated_at=? WHERE id=?", (now, season_id))
    db.commit()

    updated = db.execute(
        "SELECT * FROM items WHERE mal_id=? AND season_id=?",
        (mal_id, season_id),
    ).fetchone()
    return _row_to_item(updated)
