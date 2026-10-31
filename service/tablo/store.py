"""SQLite storage for state that must survive restarts (§6.1)."""

import json
import sqlite3
from pathlib import Path

SCHEMA = """
create table if not exists kv (
    key text primary key,
    value text not null
);
"""

# Left by the sources that moved to infomaster (§6.1): the university app login is a secret, the rest are caches.
# Their old tables stay in an existing tablo.db until it is started afresh, so a rollback still finds them.
OLD_KEYS = ("hseapp.auth", "hseapp.deadlines", "telegram.last", "mail.state")
OLD_PREFIXES = ("hseapp.label:", "grades.layout:")


class Store:
    def __init__(self, path: Path | str = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._forget_old()

    def _forget_old(self) -> None:
        with self.db:
            self.db.execute(f"delete from kv where key in ({', '.join('?' * len(OLD_KEYS))})", OLD_KEYS)
            for prefix in OLD_PREFIXES:
                self.db.execute("delete from kv where substr(key, 1, ?) = ?", (len(prefix), prefix))

    def get_json(self, key: str):
        row = self.db.execute("select value from kv where key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def put_json(self, key: str, value) -> None:
        with self.db:
            self.db.execute(
                "insert into kv(key, value) values(?, ?) on conflict(key) do update set value = excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )
