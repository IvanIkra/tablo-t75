"""SQLite storage for state that must survive restarts (§6.1)."""

import json
import sqlite3
from pathlib import Path

SCHEMA = """
create table if not exists kv (
    key text primary key,
    value text not null
);
create table if not exists grade_sheets (
    sheet_id text primary key,
    title text,
    baseline_at text            -- first successful fetch; grades seen then are not "new"
);
create table if not exists grade_items (
    key text primary key,       -- sheet/tab/column/header path: stable across Haiku relabelling
    sheet_id text not null,
    label text not null,
    value real not null,        -- normalised to 0-10
    bonus real,
    position integer not null   -- order in the sheet, for baseline display
);
create table if not exists grade_events (
    id integer primary key,
    key text not null,
    label text not null,
    value real not null,
    bonus real,
    seen_at text not null
);
create table if not exists subjects (
    name text primary key,      -- course name as a source gives it, Russian or English
    title text not null,        -- short English name for the Classes block
    abbr text not null,         -- course prefix for deadline labels: Calc, DM
    manual integer not null default 0  -- set by hand (HA): Haiku never overwrites it
);
create table if not exists news_posts (
    key text primary key,       -- "tg:example_se/23"; mail later
    source text not null,       -- "tg" | "mail"
    origin text not null,       -- channel or sender
    posted_at text not null,    -- local time
    body text not null,         -- plain text as Haiku reads it
    study integer not null,
    parsed_at text              -- set once Haiku has read it
);
"""


class Store:
    def __init__(self, path: Path | str = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def get_json(self, key: str):
        row = self.db.execute("select value from kv where key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def put_json(self, key: str, value) -> None:
        with self.db:
            self.db.execute(
                "insert into kv(key, value) values(?, ?) on conflict(key) do update set value = excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )
