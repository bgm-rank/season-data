from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from loguru import logger

from api.schemas import OverrideCreate, OverrideRead

router = APIRouter()


def _get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db  # type: ignore[no-any-return]


def _row_to_override(row: sqlite3.Row) -> OverrideRead:
    # mal_title / in_season_items 只有 list_overrides 的 JOIN 查询带得出来，
    # create/delete 走的是裸 SELECT，缺列时留给 schema 的默认值
    cols = row.keys()
    return OverrideRead(
        mal_id=row["mal_id"],
        season_id=row["season_id"],
        action=row["action"],
        bgm_id=row["bgm_id"],
        reason=row["reason"],
        target_season_id=row["target_season_id"],
        note=row["note"],
        created_at=row["created_at"],
        mal_title=row["mal_title"] if "mal_title" in cols else None,
        in_season_items=bool(row["in_season_items"]) if "in_season_items" in cols else True,
    )


# 绝大多数 override 的 (season_id, mal_id) 已经在 season_items 里了（skip 全部在，
# add 在 run 之后也会插进去），审核界面就把它们当普通条目展示。剩下的「孤儿」是
# 建了 override 但还没 run 的待办，靠 in_season_items=0 标出来。
_LIST_SQL = """
SELECT o.*, m.title AS mal_title,
       (si.mal_id IS NOT NULL) AS in_season_items
FROM overrides o
LEFT JOIN mal_anime m ON m.mal_id = o.mal_id
LEFT JOIN season_items si ON si.season_id = o.season_id AND si.mal_id = o.mal_id
WHERE o.season_id = ?
ORDER BY o.mal_id ASC
"""


@router.get("/seasons/{season_id}/overrides", response_model=list[OverrideRead])
def list_overrides(season_id: str, db: sqlite3.Connection = Depends(_get_db)) -> list[OverrideRead]:
    rows = db.execute(_LIST_SQL, (season_id,)).fetchall()
    return [_row_to_override(r) for r in rows]


@router.post("/seasons/{season_id}/overrides", response_model=OverrideRead, status_code=201)
def create_override(
    season_id: str,
    body: OverrideCreate,
    db: sqlite3.Connection = Depends(_get_db),
) -> OverrideRead:
    if body.action == "add" and body.bgm_id is None:
        raise HTTPException(status_code=422, detail="bgm_id is required for action=add")
    note = (body.note or "").strip() or None
    if body.reason == "other" and note is None:
        raise HTTPException(status_code=422, detail="note is required when reason=other")

    # 不用 INSERT OR REPLACE：那是删+插，重复提交同一 (mal_id, season_id) 会把
    # created_at 重置成本次时间。DO UPDATE 把 created_at 排除在更新列外，保留首次记录时间。
    db.execute(
        """
        INSERT INTO overrides (mal_id, season_id, action, bgm_id, reason, target_season_id, note, created_at)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(mal_id, season_id) DO UPDATE SET
            action=excluded.action, bgm_id=excluded.bgm_id, reason=excluded.reason,
            target_season_id=excluded.target_season_id, note=excluded.note
        """,
        (
            body.mal_id,
            season_id,
            body.action,
            body.bgm_id,
            body.reason,
            body.target_season_id,
            note,
            datetime.now(UTC).isoformat(),
        ),
    )
    db.commit()

    # add 必须当场落地进 season_items，不能等目标季度下次跑 run——写 override 的时刻人在**源季度**
    # 的界面上，目标季度通常早已审完，那个 run 永远不会来，这条番就在两个季度之间蒸发了。
    # 详见 core/overrides.py 的模块注释。落地失败不回滚 override：意图已经记下了，
    # scripts/apply_pending_adds.py 随时能补。
    if body.action == "add" and body.bgm_id is not None:
        try:
            _apply_add(db, season_id, body.mal_id, body.bgm_id)
        except Exception as e:
            logger.error(
                "[override add] 即时落地失败 {} mal:{}: {}（意图已记录，可跑 apply_pending_adds.py 补）",
                season_id,
                body.mal_id,
                e,
            )

    row = db.execute(
        "SELECT * FROM overrides WHERE mal_id=? AND season_id=?",
        (body.mal_id, season_id),
    ).fetchone()
    return _row_to_override(row)


def _apply_add(db: sqlite3.Connection, season_id: str, mal_id: int, bgm_id: int) -> None:
    from core.overrides import apply_add_override
    from services.bgmtv import BgmtvClient
    from services.mal.client import MalClient

    mal_client_id = os.getenv("MAL_CLIENT_ID", "")
    with BgmtvClient(os.getenv("BGM_TOKEN", "")) as bgmtv:
        if mal_client_id:
            with MalClient(mal_client_id) as mal:
                apply_add_override(db, season_id, mal_id, bgm_id, bgmtv=bgmtv, mal=mal)
        else:
            apply_add_override(db, season_id, mal_id, bgm_id, bgmtv=bgmtv)


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
