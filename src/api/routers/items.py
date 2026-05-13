from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sqlite3
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from api.schemas import ItemRead, ItemUpdate

router = APIRouter()

_sync_tasks: dict[str, asyncio.Task[None]] = {}
_sync_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}


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
        bgm_air_date=row["bgm_air_date"],
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
    elif body.action == "pending":
        db.execute(
            "UPDATE items SET status='pending', source=NULL, bgm_id=NULL, bgm_name=NULL, bgm_name_cn=NULL, bgm_air_date=NULL, updated_at=? WHERE mal_id=? AND season_id=?",
            (now, mal_id, season_id),
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


def _run_sync(
    db: sqlite3.Connection,
    season_id: str,
    queue: asyncio.Queue[dict[str, Any]],
) -> None:
    from services.bgmtv import BgmtvClient

    rows = db.execute(
        "SELECT mal_id, bgm_id FROM items WHERE season_id=? AND bgm_id IS NOT NULL",
        (season_id,),
    ).fetchall()
    total = len(rows)
    updated = 0
    errors = 0
    now = datetime.now(UTC).isoformat()

    try:
        bgm_token = os.getenv("BGM_TOKEN", "")
        with BgmtvClient(bgm_token) as bgmtv:
            for i, row in enumerate(rows, 1):
                try:
                    subject = bgmtv.get_subject(row["bgm_id"])
                    db.execute(
                        "UPDATE items SET bgm_name=?, bgm_name_cn=?, bgm_air_date=?, updated_at=?"
                        " WHERE mal_id=? AND season_id=?",
                        (subject.name, subject.name_cn, subject.date, now, row["mal_id"], season_id),
                    )
                    db.commit()
                    updated += 1
                    time.sleep(0.3)
                except Exception:
                    errors += 1
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait({"type": "progress", "processed": i, "total": total})
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait({"type": "done", "processed": total, "total": total, "updated": updated, "errors": errors})
    except Exception as e:
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait({"type": "error", "message": str(e)})


@router.post("/seasons/{season_id}/sync-bgm", status_code=202)
async def sync_bgm(
    season_id: str,
    db: sqlite3.Connection = Depends(_get_db),
) -> dict[str, str]:
    if season_id in _sync_tasks and not _sync_tasks[season_id].done():
        raise HTTPException(status_code=409, detail=f"Season {season_id} already syncing")

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
    _sync_queues[season_id] = queue

    loop = asyncio.get_event_loop()

    async def _run() -> None:
        await loop.run_in_executor(None, _run_sync, db, season_id, queue)
        _sync_tasks.pop(season_id, None)

    task = asyncio.create_task(_run())
    _sync_tasks[season_id] = task
    return {"task_id": season_id}


@router.get("/seasons/{season_id}/sync-bgm/progress")
async def sync_bgm_progress(season_id: str) -> StreamingResponse:
    no_task = season_id not in _sync_tasks or _sync_tasks[season_id].done()
    if no_task and season_id not in _sync_queues:
        raise HTTPException(status_code=404, detail=f"No running sync for season {season_id}")

    queue = _sync_queues.get(season_id)
    if queue is None:
        raise HTTPException(status_code=404, detail=f"No running sync for season {season_id}")

    async def event_stream() -> AsyncIterator[str]:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
            except TimeoutError:
                yield 'data: {"type":"heartbeat"}\n\n'
                continue
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event.get("type") in ("done", "error"):
                _sync_queues.pop(season_id, None)
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")
