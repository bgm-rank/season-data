from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sqlite3
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from loguru import logger

from api.quality import ISSUE_KINDS, issue_counts, item_issues, season_issue_map
from api.repo import ensure_bgm_subject
from api.schemas import ItemDetailRead, ItemListResponse, ItemRead, ItemUpdate

if TYPE_CHECKING:
    from services.bgmtv import Subject

router = APIRouter()

_sync_tasks: dict[str, asyncio.Task[None]] = {}
_sync_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}


def _get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db  # type: ignore[no-any-return]


def _try_fetch_subject(bgm_id: int) -> Subject | None:
    """拉一条 BGM 条目详情，失败返回 None（调用方会退化成骨架行）。"""
    from services.bgmtv import BgmtvClient

    try:
        with BgmtvClient(os.getenv("BGM_TOKEN", "")) as bgmtv:
            return bgmtv.get_subject(bgm_id)
    except Exception as e:
        logger.warning("拉取 BGM 条目失败 bgm:{}: {}", bgm_id, e)
        return None


def _row_to_item(row: sqlite3.Row, issues: list[str] | None = None) -> ItemRead:
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
        reason=row["reason"],
        note=row["note"],
        override_action=row["override_action"],
        override_reason=row["override_reason"],
        override_target_season_id=row["override_target_season_id"],
        updated_at=row["updated_at"],
        issues=issues or [],  # type: ignore[arg-type]
    )


def _json_list(raw: str | None) -> list[dict[str, Any]] | None:
    """candidates / studios / tags 三个列都是 TEXT 里存 JSON array。"""
    if not raw:
        return None
    parsed: list[dict[str, Any]] = json.loads(raw)
    return parsed


# 详情不走 items_flat：那个视图的列刻意与 ItemRead 一一对应，扩展字段往里加会打破
# 拆表时定下的边界。这里自己 JOIN 四张实表查单行。
_DETAIL_SQL = """
SELECT si.*,
       m.title AS mal_title, m.title_ja AS mal_title_ja, m.title_en AS mal_title_en,
       m.media_type AS mal_media_type, m.rating AS mal_rating,
       m.start_date AS mal_start_date, m.end_date AS mal_end_date,
       m.num_episodes AS mal_num_episodes, m.source AS mal_source,
       m.studios AS mal_studios, m.synopsis AS mal_synopsis,
       m.fetched_at AS mal_fetched_at,
       b.name AS bgm_name, b.name_cn AS bgm_name_cn, b.air_date AS bgm_air_date,
       b.type AS bgm_type, b.platform AS bgm_platform, b.summary AS bgm_summary,
       b.tags AS bgm_tags, b.nsfw AS bgm_nsfw, b.fetched_at AS bgm_fetched_at,
       o.action AS override_action, o.bgm_id AS override_bgm_id,
       o.reason AS override_reason, o.target_season_id AS override_target_season_id,
       o.note AS override_note, o.created_at AS override_created_at
FROM season_items si
JOIN mal_anime m USING (mal_id)
LEFT JOIN bgm_subject b ON b.bgm_id = si.bgm_id
LEFT JOIN overrides o ON o.season_id = si.season_id AND o.mal_id = si.mal_id
WHERE si.season_id = ? AND si.mal_id = ?
"""


def _row_to_detail(row: sqlite3.Row, issues: list[str]) -> ItemDetailRead:
    return ItemDetailRead(
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
        candidates=_json_list(row["candidates"]),
        bgm_air_date=row["bgm_air_date"],
        reason=row["reason"],
        note=row["note"],
        override_action=row["override_action"],
        override_reason=row["override_reason"],
        override_target_season_id=row["override_target_season_id"],
        updated_at=row["updated_at"],
        issues=issues,  # type: ignore[arg-type]
        origin=row["origin"],
        mal_title_en=row["mal_title_en"],
        mal_start_date=row["mal_start_date"],
        mal_end_date=row["mal_end_date"],
        mal_num_episodes=row["mal_num_episodes"],
        mal_source=row["mal_source"],
        mal_studios=_json_list(row["mal_studios"]),
        mal_synopsis=row["mal_synopsis"],
        mal_fetched_at=row["mal_fetched_at"],
        bgm_type=row["bgm_type"],
        bgm_platform=row["bgm_platform"],
        bgm_summary=row["bgm_summary"],
        bgm_tags=_json_list(row["bgm_tags"]),
        bgm_nsfw=row["bgm_nsfw"],
        bgm_fetched_at=row["bgm_fetched_at"],
        override_bgm_id=row["override_bgm_id"],
        override_note=row["override_note"],
        override_created_at=row["override_created_at"],
    )


@router.get("/seasons/{season_id}/items", response_model=ItemListResponse)
def list_items(
    season_id: str,
    db: sqlite3.Connection = Depends(_get_db),
    status: str | None = Query(default=None),
    source: str | None = Query(default=None),
    issue: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> ItemListResponse:
    if issue is not None and issue not in ISSUE_KINDS:
        raise HTTPException(status_code=422, detail=f"Unknown issue kind: {issue}")

    issue_map = season_issue_map(db, season_id)

    clauses = ["season_id = ?"]
    params: list[Any] = [season_id]

    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if source is not None:
        clauses.append("source = ?")
        params.append(source)
    if issue is not None:
        # 把命中的 mal_id 拼进同一条 SQL，让 total 和 LIMIT 都对得上；
        # 在 Python 里对已分页的结果过滤会让分页立刻错乱。
        matched = [mal_id for mal_id, kinds in issue_map.items() if issue in kinds]
        if not matched:
            return ItemListResponse(total=0, limit=limit, offset=offset, items=[], issue_counts=issue_counts(issue_map))
        clauses.append(f"mal_id IN ({','.join('?' * len(matched))})")
        params.extend(matched)

    where = " AND ".join(clauses)

    total: int = db.execute(f"SELECT COUNT(*) FROM items_flat WHERE {where}", params).fetchone()[0]
    # 恒按 mal_id 排。pending 时按置信度升序是老审核队列（先审最可疑的）的排法，
    # 队列已并进详情面板，左列要的是一份顺序稳定、切筛选不跳位的全季清单。
    rows = db.execute(
        f"SELECT * FROM items_flat WHERE {where} ORDER BY mal_id ASC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return ItemListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[_row_to_item(r, issue_map.get(r["mal_id"])) for r in rows],
        issue_counts=issue_counts(issue_map),
    )


@router.get("/seasons/{season_id}/items/{mal_id}", response_model=ItemDetailRead)
def get_item(
    season_id: str,
    mal_id: int,
    db: sqlite3.Connection = Depends(_get_db),
) -> ItemDetailRead:
    row = db.execute(_DETAIL_SQL, (season_id, mal_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Item {mal_id} not found in season {season_id}")
    return _row_to_detail(row, item_issues(db, season_id, mal_id))


@router.patch("/seasons/{season_id}/items/{mal_id}", response_model=ItemRead)
def update_item(
    season_id: str,
    mal_id: int,
    body: ItemUpdate,
    db: sqlite3.Connection = Depends(_get_db),
) -> ItemRead:
    row = db.execute(
        "SELECT * FROM items_flat WHERE mal_id = ? AND season_id = ?",
        (mal_id, season_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Item {mal_id} not found in season {season_id}")

    # 原因只对排除有意义。include/pending 带着 reason 提交多半是前端漏清状态，
    # 静默丢掉会让人以为记下了，直接拒绝。
    note = (body.note or "").strip() or None
    if body.action != "exclude" and (body.reason is not None or note is not None):
        raise HTTPException(status_code=422, detail="reason/note is only allowed for action=exclude")
    if body.reason == "other" and note is None:
        raise HTTPException(status_code=422, detail="note is required when reason=other")

    now = datetime.now(UTC).isoformat()

    if body.action == "include":
        if body.bgm_id is None:
            raise HTTPException(status_code=422, detail="bgm_id is required for action=include")
        # 外键要求先有 bgm_subject 行。顺手把名称拉回来，人工填完 ID 立刻能看到番名做二次确认；
        # BGM API 不可用就退化成骨架行，不能让外键把人工输入卡死。
        subject = _try_fetch_subject(body.bgm_id)
        ensure_bgm_subject(db, body.bgm_id, subject)
        # reason/note 是上一次排除判定的产物，收录等于推翻它，留着会误导
        db.execute(
            "UPDATE season_items SET status='included', source='human', bgm_id=?,"
            " confidence=NULL, error=NULL, reason=NULL, note=NULL, updated_at=? WHERE mal_id=? AND season_id=?",
            (body.bgm_id, now, mal_id, season_id),
        )
    elif body.action == "pending":
        db.execute(
            "UPDATE season_items SET status='pending', source=NULL, bgm_id=NULL, confidence=NULL,"
            " candidates=NULL, error=NULL, reason=NULL, note=NULL, updated_at=? WHERE mal_id=? AND season_id=?",
            (now, mal_id, season_id),
        )
    else:
        db.execute(
            "UPDATE season_items SET status='excluded', source='human', reason=?, note=?,"
            " updated_at=? WHERE mal_id=? AND season_id=?",
            (body.reason, note, now, mal_id, season_id),
        )

    db.execute("UPDATE seasons SET updated_at=? WHERE id=?", (now, season_id))
    db.commit()

    updated = db.execute(
        "SELECT * FROM items_flat WHERE mal_id=? AND season_id=?",
        (mal_id, season_id),
    ).fetchone()
    # 前端拿这个返回值做局部替换，不带 issues 会把质量 badge 洗掉
    return _row_to_item(updated, item_issues(db, season_id, mal_id))


def _run_sync(
    db: sqlite3.Connection,
    season_id: str,
    queue: asyncio.Queue[dict[str, Any]],
) -> None:
    from core.bgm_sync import sync_subjects

    # 按 bgm_id 去重：同一条目被本季多个 MAL 条目引用时只需拉一次。
    # 这里刻意不看 fetched_at——按钮的语义是「强制刷新本季」，
    # 增量补齐走 scripts/sync_bgm.py。
    rows = db.execute(
        "SELECT DISTINCT bgm_id FROM season_items WHERE season_id=? AND bgm_id IS NOT NULL",
        (season_id,),
    ).fetchall()
    bgm_ids = [r["bgm_id"] for r in rows]
    total = len(bgm_ids)

    def on_progress(processed: int, count: int) -> None:
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait({"type": "progress", "processed": processed, "total": count})

    try:
        updated, failed = sync_subjects(db, bgm_ids, on_progress=on_progress)
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(
                {"type": "done", "processed": total, "total": total, "updated": updated, "errors": len(failed)}
            )
    except Exception as e:
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait({"type": "error", "message": str(e)})


@router.post("/seasons/{season_id}/items/{mal_id}/sync-bgm", response_model=ItemRead)
def sync_bgm_item(
    season_id: str,
    mal_id: int,
    db: sqlite3.Connection = Depends(_get_db),
) -> ItemRead:
    row = db.execute(
        "SELECT * FROM items_flat WHERE mal_id=? AND season_id=?",
        (mal_id, season_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Item {mal_id} not found in season {season_id}")
    if row["bgm_id"] is None:
        raise HTTPException(status_code=422, detail="Item has no bgm_id")

    from services.bgmtv import BgmtvClient

    bgm_token = os.getenv("BGM_TOKEN", "")
    with BgmtvClient(bgm_token) as bgmtv:
        subject = bgmtv.get_subject(row["bgm_id"])

    ensure_bgm_subject(db, row["bgm_id"], subject)
    db.commit()

    updated = db.execute(
        "SELECT * FROM items_flat WHERE mal_id=? AND season_id=?",
        (mal_id, season_id),
    ).fetchone()
    return _row_to_item(updated, item_issues(db, season_id, mal_id))


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
