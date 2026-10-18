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
create table if not exists news_items (
    id text primary key,        -- key of the post or letter it was written from
    source text not null,
    study integer not null,
    posted_at text not null,    -- local time; the item ages from here
    full text not null,         -- up to 2 lines of the column
    short text not null,        -- 1 line
    importance integer not null,
    replaced_by text            -- a newer item on the same topic took its place
);
create table if not exists own_deadlines (
    id integer primary key,     -- added to a to-do list in HA (§8.4)
    title text not null,
    due text not null,
    category text not null      -- "study" | "personal": the list it was added to
);
create table if not exists hidden_deadlines (
    uid text primary key,       -- deleted or marked done in HA: never shown again
    source text not null,
    course text,
    title text not null,
    due text not null
);
create table if not exists llm_runs (   -- every Haiku call, kept for good (§6.6)
    id integer primary key,
    at text not null,           -- UTC, ISO 8601
    task text not null,         -- news, grades, deadlines, subjects
    model text not null,
    ok integer not null,
    error text,
    input_tokens integer not null,
    output_tokens integer not null,
    cache_write integer not null,
    cache_read integer not null,
    cost_usd real,              -- null for a model without known prices
    duration_s real not null
);
create index if not exists llm_runs_at on llm_runs(at);
create table if not exists news_deadlines (
    id integer primary key,
    item text not null,         -- news item it came from
    source text not null,
    course text,                -- course abbreviation from the dictionary, for merging duplicates
    label text not null,
    due text not null,
    moved_by integer            -- deadline that moved this one to another date
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

    # --- LLM runs ---------------------------------------------------------------

    LLM_FIELDS = ("at", "task", "model", "ok", "error", "input_tokens", "output_tokens", "cache_write",
                  "cache_read", "cost_usd", "duration_s")

    def add_llm_run(self, run: dict) -> None:
        with self.db:
            self.db.execute(f"insert into llm_runs({', '.join(self.LLM_FIELDS)}) values({', '.join('?' * len(self.LLM_FIELDS))})",
                            [run[f] for f in self.LLM_FIELDS])

    def _llm_run(self, row) -> dict:
        return {**{f: row[f] for f in self.LLM_FIELDS}, "ok": bool(row["ok"])}

    def llm_runs(self, limit: int = 100, task: str | None = None) -> list[dict]:
        """Newest first."""
        where, args = ("where task = ?", [task]) if task else ("", [])
        rows = self.db.execute(f"select * from llm_runs {where} order by id desc limit ?", [*args, limit])
        return [self._llm_run(r) for r in rows]

    def llm_last_by_task(self) -> dict[str, dict]:
        rows = self.db.execute("select * from llm_runs where id in (select max(id) from llm_runs group by task)")
        return {r["task"]: self._llm_run(r) for r in rows}

    def llm_failing(self) -> dict | None:
        """The newest failed run if nothing has succeeded since: the LLM is failing now."""
        row = self.db.execute("select * from llm_runs where ok = 0 and id > coalesce("
                              "(select max(id) from llm_runs where ok = 1), 0) order by id desc limit 1").fetchone()
        return self._llm_run(row) if row else None

    def llm_totals(self, since_utc: str) -> dict:
        row = self.db.execute("select count(*) n, coalesce(sum(cost_usd), 0) cost, "
                              "coalesce(sum(input_tokens + output_tokens + cache_write + cache_read), 0) tokens "
                              "from llm_runs where at >= ?", (since_utc,)).fetchone()
        return {"runs": row["n"], "cost_usd": round(row["cost"], 6), "tokens": row["tokens"]}

    def put_json(self, key: str, value) -> None:
        with self.db:
            self.db.execute(
                "insert into kv(key, value) values(?, ?) on conflict(key) do update set value = excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )
