CREATE TABLE IF NOT EXISTS seasons (
    id          TEXT    PRIMARY KEY,
    year        INTEGER NOT NULL,
    season      TEXT    NOT NULL         CHECK(season IN ('winter','spring','summer','fall')),
    released_at TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    mal_id          INTEGER NOT NULL,
    season_id       TEXT    NOT NULL,
    status          TEXT    NOT NULL     CHECK(status IN ('pending','included','excluded')),
    source          TEXT                 CHECK(source IN ('rule','exact','llm','human') OR source IS NULL),
    confidence      REAL,
    bgm_id          INTEGER,
    bgm_name        TEXT,
    bgm_name_cn     TEXT,
    mal_title       TEXT    NOT NULL,
    mal_title_ja    TEXT,
    mal_media_type  TEXT    NOT NULL,
    mal_rating      TEXT    NOT NULL,
    error           TEXT,
    candidates      TEXT,
    updated_at      TEXT    NOT NULL,
    PRIMARY KEY (mal_id, season_id),
    FOREIGN KEY (season_id) REFERENCES seasons(id)
);

CREATE TABLE IF NOT EXISTS overrides (
    mal_id      INTEGER NOT NULL,
    season_id   TEXT    NOT NULL,
    action      TEXT    NOT NULL         CHECK(action IN ('add','skip')),
    bgm_id      INTEGER,
    PRIMARY KEY (mal_id, season_id),
    FOREIGN KEY (season_id) REFERENCES seasons(id)
);

CREATE INDEX IF NOT EXISTS idx_items_season_status ON items(season_id, status);
CREATE INDEX IF NOT EXISTS idx_items_season_bgm ON items(season_id, bgm_id);
