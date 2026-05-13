from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
DEFAULT_DB_PATH = ROOT_DIR / "season.db"


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(filename TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        conn.commit()

        applied = {row[0] for row in conn.execute("SELECT filename FROM schema_migrations")}
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if migration.name in applied:
                continue
            conn.executescript(migration.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (filename, applied_at) VALUES (?, datetime('now'))",
                (migration.name,),
            )
            conn.commit()
    finally:
        conn.close()


def get_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def derive_phase(total: int, unprocessed: int, pending: int, released_at: str | None) -> str:
    if total == 0:
        return "init"
    if unprocessed == total:
        return "fetched"
    if released_at:
        return "released"
    if pending > 0:
        return "reviewing"
    return "done"
