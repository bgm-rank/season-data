from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

router = APIRouter()

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent


def _get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db  # type: ignore[no-any-return]


def _build_release_items(conn: sqlite3.Connection, season_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM items WHERE season_id=? AND status='included' ORDER BY bgm_id ASC",
        (season_id,),
    ).fetchall()
    items = []
    for row in rows:
        if row["bgm_id"] is None:
            continue
        mal: dict[str, Any] = {
            "id": row["mal_id"],
            "title": row["mal_title"],
            "media_type": row["mal_media_type"],
            "rating": row["mal_rating"],
        }
        if row["mal_title_ja"]:
            mal["title_ja"] = row["mal_title_ja"]
        item: dict[str, Any] = {"bgm_id": row["bgm_id"]}
        if row["bgm_name"]:
            item["bgm_name"] = row["bgm_name"]
        if row["bgm_name_cn"]:
            item["bgm_name_cn"] = row["bgm_name_cn"]
        item["mal"] = mal
        items.append(item)
    return items


@router.get("/seasons/{season_id}/release")
def preview_release(season_id: str, db: sqlite3.Connection = Depends(_get_db)) -> dict[str, Any]:
    row = db.execute("SELECT 1 FROM seasons WHERE id=?", (season_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Season {season_id} not found")
    items = _build_release_items(db, season_id)
    return {"season": season_id, "items": items}


@router.post("/seasons/{season_id}/export/release")
def export_release(season_id: str, db: sqlite3.Connection = Depends(_get_db)) -> dict[str, Any]:
    row = db.execute("SELECT * FROM seasons WHERE id=?", (season_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Season {season_id} not found")

    items = _build_release_items(db, season_id)
    data = {"season": season_id, "items": items}

    year: int = row["year"]
    season: str = row["season"]
    release_path = ROOT_DIR / "release" / f"{year}-{season}.json"
    release_path.parent.mkdir(parents=True, exist_ok=True)
    release_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    now = datetime.now(UTC).isoformat()
    db.execute("UPDATE seasons SET released_at=?, updated_at=? WHERE id=?", (now, now, season_id))
    db.commit()

    return {"path": str(release_path.relative_to(ROOT_DIR)), "item_count": len(items)}


@router.post("/seasons/{season_id}/export/snapshot")
def export_snapshot(season_id: str, db: sqlite3.Connection = Depends(_get_db)) -> dict[str, Any]:
    row = db.execute("SELECT * FROM seasons WHERE id=?", (season_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Season {season_id} not found")

    rows = db.execute("SELECT * FROM items WHERE season_id=?", (season_id,)).fetchall()
    items = []
    for r in rows:
        candidates_raw = r["candidates"]
        item: dict[str, Any] = {
            "mal_id": r["mal_id"],
            "season_id": r["season_id"],
            "status": r["status"],
            "source": r["source"],
            "confidence": r["confidence"],
            "bgm_id": r["bgm_id"],
            "bgm_name": r["bgm_name"],
            "bgm_name_cn": r["bgm_name_cn"],
            "mal_title": r["mal_title"],
            "mal_title_ja": r["mal_title_ja"],
            "mal_media_type": r["mal_media_type"],
            "mal_rating": r["mal_rating"],
            "error": r["error"],
            "candidates": json.loads(candidates_raw) if candidates_raw else None,
            "updated_at": r["updated_at"],
        }
        items.append(item)

    today = datetime.now(UTC).strftime("%Y%m%d")
    snapshots_dir = ROOT_DIR / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshots_dir / f"{season_id}-{today}.json"
    snapshot_path.write_text(
        json.dumps({"season": season_id, "items": items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {"path": str(snapshot_path.relative_to(ROOT_DIR)), "item_count": len(items)}
