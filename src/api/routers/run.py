from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sqlite3
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

router = APIRouter()

_active_tasks: dict[str, asyncio.Task[None]] = {}
_active_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}


def _get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db  # type: ignore[no-any-return]


def _run_processor(
    conn: sqlite3.Connection,
    season_id: str,
    retry: bool,
    queue: asyncio.Queue[dict[str, Any]],
) -> None:
    from services.bgmtv import BgmtvClient
    from services.openrouter import DEEPSEEK_BASE_URL, DEFAULT_DEEPSEEK_MODEL, DEFAULT_MODEL, OpenRouterClient

    bgm_token = os.getenv("BGM_TOKEN", "")
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    mal_client_id = os.getenv("MAL_CLIENT_ID", "")

    try:
        with BgmtvClient(bgm_token) as bgmtv:
            openrouter: OpenRouterClient | None = None
            if deepseek_key:
                model = os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
                openrouter = OpenRouterClient(deepseek_key, model=model, base_url=DEEPSEEK_BASE_URL)
            elif openrouter_key:
                model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
                openrouter = OpenRouterClient(openrouter_key, model=model)
            try:
                from core.processor import SeasonProcessor
                from services.mal.client import MalClient

                mal: MalClient | None = MalClient(mal_client_id) if mal_client_id else None
                processor = SeasonProcessor(
                    conn=conn,
                    season_id=season_id,
                    bgmtv_client=bgmtv,
                    openrouter_client=openrouter,
                    mal_client=mal,
                    progress_queue=queue,
                    retry=retry,
                )
                processor.process()
            finally:
                if openrouter:
                    openrouter.close()
    except Exception as e:
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait({"type": "error", "message": str(e)})


@router.post("/seasons/{season_id}/run", status_code=202)
async def run_season(
    season_id: str,
    retry: bool = False,
    db: sqlite3.Connection = Depends(_get_db),
) -> dict[str, str]:
    row = db.execute("SELECT 1 FROM seasons WHERE id=?", (season_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Season {season_id} not found")

    if season_id in _active_tasks and not _active_tasks[season_id].done():
        raise HTTPException(status_code=409, detail=f"Season {season_id} already has a running task")

    task_id = f"{season_id}-{uuid4().hex[:8]}"
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
    _active_queues[season_id] = queue

    loop = asyncio.get_event_loop()

    async def _run() -> None:
        await loop.run_in_executor(None, _run_processor, db, season_id, retry, queue)
        _active_tasks.pop(season_id, None)

    task = asyncio.create_task(_run())
    _active_tasks[season_id] = task

    return {"task_id": task_id}


@router.get("/seasons/{season_id}/run/progress")
async def run_progress(season_id: str) -> StreamingResponse:
    no_task = season_id not in _active_tasks or _active_tasks[season_id].done()
    if no_task and season_id not in _active_queues:
        raise HTTPException(status_code=404, detail=f"No running task for season {season_id}")

    queue = _active_queues.get(season_id)
    if queue is None:
        raise HTTPException(status_code=404, detail=f"No running task for season {season_id}")

    async def event_stream() -> AsyncIterator[str]:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
            except TimeoutError:
                yield 'data: {"type":"heartbeat"}\n\n'
                continue

            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            if event.get("type") in ("done", "error"):
                _active_queues.pop(season_id, None)
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")
