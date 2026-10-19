"""Tiny local history: log every finished job, show recent in tray."""
from __future__ import annotations

import sqlite3
from pathlib import Path


def _db() -> Path:
    import os
    import sys
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "DragShift" / "history.db"


def log(action: str, srcs: list[str], outs: list[str]) -> None:
    try:
        db = _db()
        db.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(db)
        c.execute("CREATE TABLE IF NOT EXISTS h(ts TEXT, action TEXT, srcs TEXT, outs TEXT)")
        c.execute("INSERT INTO h VALUES(datetime('now'),?,?,?)",
                  (action, "\n".join(srcs[:10]), "\n".join(outs[:10])))
        c.execute("DELETE FROM h WHERE rowid NOT IN (SELECT rowid FROM h ORDER BY rowid DESC LIMIT 100)")
        c.commit()
        c.close()
    except Exception:
        pass


def recent(n: int = 10) -> list[tuple[str, str, str]]:
    try:
        c = sqlite3.connect(_db())
        rows = c.execute("SELECT ts, action, outs FROM h ORDER BY rowid DESC LIMIT ?", (n,)).fetchall()
        c.close()
        return rows
    except Exception:
        return []
