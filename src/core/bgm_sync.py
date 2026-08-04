"""BGM 条目详情的增量同步。

待刷队列就是 `bgm_subject.fetched_at IS NULL` 的骨架行——拉完就置 fetched_at，
所以中断重跑只会捡剩下的，天然断点续传，不需要额外的进度文件。

只写 bgm_subject（可重建缓存），碰不到 season_items 的任何决策列。
"""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Callable, Sequence

from loguru import logger

from api.repo import ensure_bgm_subject
from services.bgmtv import BgmtvClient

# 连续这么多次失败就停：token 失效或被限流时不要白烧一小时
MAX_CONSECUTIVE_ERRORS = 20


def pending_bgm_ids(conn: sqlite3.Connection, season_id: str | None = None) -> list[int]:
    """待刷队列：还没拉过详情的骨架行。

    按「被多少条 included 引用」降序，中途 Ctrl-C 时最有价值的那批已经补齐。
    传 season_id 就只取该季引用到的条目（手测时先刷一季几分钟就能看结果）。
    """
    rows = conn.execute(
        """
        SELECT b.bgm_id FROM bgm_subject b
        WHERE b.fetched_at IS NULL
          AND (?1 IS NULL OR EXISTS (
                SELECT 1 FROM season_items si
                WHERE si.bgm_id = b.bgm_id AND si.season_id = ?1))
        ORDER BY (SELECT COUNT(*) FROM season_items si
                  WHERE si.bgm_id = b.bgm_id AND si.status = 'included') DESC,
                 b.bgm_id
        """,
        (season_id,),
    ).fetchall()
    return [r[0] for r in rows]


def sync_subjects(
    conn: sqlite3.Connection,
    bgm_ids: Sequence[int],
    *,
    sleep: float = 0.3,
    max_consecutive_errors: int = MAX_CONSECUTIVE_ERRORS,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[int, list[int]]:
    """逐条拉详情写库，返回 (成功数, 失败的 bgm_id 列表)。

    每条一次 commit——这就是断点续传的粒度，中断时已拉的不会回滚。
    on_progress 收到的是 (已处理数, 总数)。
    """
    total = len(bgm_ids)
    updated = 0
    failed: list[int] = []
    consecutive_errors = 0

    with BgmtvClient(os.getenv("BGM_TOKEN", "")) as bgmtv:
        for i, bgm_id in enumerate(bgm_ids, 1):
            try:
                ensure_bgm_subject(conn, bgm_id, bgmtv.get_subject(bgm_id))
                conn.commit()
                updated += 1
                consecutive_errors = 0
                time.sleep(sleep)
            except Exception as e:
                logger.warning("同步 BGM 条目失败 bgm:{}: {}", bgm_id, e)
                failed.append(bgm_id)
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    raise RuntimeError(f"连续 {consecutive_errors} 次失败，中止同步（已完成 {updated}/{total}）") from e
            if on_progress is not None:
                on_progress(i, total)

    return updated, failed
