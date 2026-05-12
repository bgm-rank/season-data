from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from api.schemas import OverrideCreate, OverrideRead

router = APIRouter()


def _get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db  # type: ignore[no-any-return]


def _row_to_override(row: sqlite3.Row) -> OverrideRead:
    return OverrideRead(
        mal_id=row["mal_id"],
        season_id=row["season_id"],
        action=row["action"],
        bgm_id=row["bgm_id"],
    )


@router.get("/seasons/{season_id}/overrides", response_model=list[OverrideRead])
def list_overrides(season_id: str, db: sqlite3.Connection = Depends(_get_db)) -> list[OverrideRead]:
    rows = db.execute("SELECT * FROM overrides WHERE season_id = ?", (season_id,)).fetchall()
    return [_row_to_override(r) for r in rows]


@router.post("/seasons/{season_id}/overrides", response_model=OverrideRead, status_code=201)
def create_override(
    season_id: str,
    body: OverrideCreate,
    db: sqlite3.Connection = Depends(_get_db),
) -> OverrideRead:
    if body.action == "add" and body.bgm_id is None:
        raise HTTPException(status_code=422, detail="bgm_id is required for action=add")

    db.execute(
        "INSERT OR REPLACE INTO overrides (mal_id, season_id, action, bgm_id) VALUES (?,?,?,?)",
        (body.mal_id, season_id, body.action, body.bgm_id),
    )
    db.commit()

    row = db.execute(
        "SELECT * FROM overrides WHERE mal_id=? AND season_id=?",
        (body.mal_id, season_id),
    ).fetchone()
    return _row_to_override(row)


@router.delete("/seasons/{season_id}/overrides/{mal_id}", status_code=204)
def delete_override(
    season_id: str,
    mal_id: int,
    db: sqlite3.Connection = Depends(_get_db),
) -> Response:
    row = db.execute(
        "SELECT 1 FROM overrides WHERE mal_id=? AND season_id=?",
        (mal_id, season_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Override {mal_id} not found in season {season_id}")
    db.execute("DELETE FROM overrides WHERE mal_id=? AND season_id=?", (mal_id, season_id))
    db.commit()
    return Response(status_code=204)
