from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.db import get_connection, init_db

load_dotenv()


def create_app() -> FastAPI:
    db_conn: sqlite3.Connection | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal db_conn
        init_db()
        db_conn = get_connection()
        app.state.db = db_conn
        yield
        if db_conn:
            db_conn.close()

    app = FastAPI(title="bgm-rank API", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:4321"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from api.routers import bgm, items, overrides, run, seasons

    app.include_router(seasons.router, prefix="/api")
    app.include_router(items.router, prefix="/api")
    app.include_router(overrides.router, prefix="/api")
    app.include_router(run.router, prefix="/api")
    app.include_router(bgm.router, prefix="/api")

    return app


app = create_app()
