import os
import re
import sqlite3
from pathlib import Path

DB_PATH = os.environ.get("STATE_DB") or str(Path(os.environ.get("DATA_DIR") or Path(__file__).parent / "data") / "state.sqlite")

SCHEMA = """CREATE TABLE IF NOT EXISTS vacancies(
  id TEXT PRIMARY KEY, url TEXT, title TEXT, company TEXT, description TEXT,
  status TEXT DEFAULT 'new', letter TEXT DEFAULT '', warnings TEXT DEFAULT '',
  updated TEXT DEFAULT (datetime('now','localtime')))"""


def connect(path=None):
    path = path or DB_PATH
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    if "note" not in {r["name"] for r in conn.execute("PRAGMA table_info(vacancies)")}:
        # which letter went out: own (LLM) | hh (hh generator) | none (response without letter)
        conn.execute("ALTER TABLE vacancies ADD COLUMN note TEXT DEFAULT ''")
        conn.commit()
    return conn


def vid_from_url(url):
    m = re.search(r"/vacancy/(\d+)", url)
    if not m:
        raise ValueError(f"not a vacancy url: {url}")
    return m.group(1)


def add(conn, v):
    cur = conn.execute(
        "INSERT OR IGNORE INTO vacancies(id,url,title,company,description) VALUES(?,?,?,?,?)",
        (v["id"], v["url"], v["title"], v["company"], v["description"]))
    conn.commit()
    return cur.rowcount == 1


def by_status(conn, status):
    return conn.execute("SELECT * FROM vacancies WHERE status=? ORDER BY rowid", (status,)).fetchall()


def _update(conn, vid, **cols):
    sets = ", ".join(f"{k}=?" for k in cols)
    conn.execute(f"UPDATE vacancies SET {sets}, updated=datetime('now','localtime') WHERE id=?",
                 (*cols.values(), vid))
    conn.commit()


def set_draft(conn, vid, letter, warnings):
    _update(conn, vid, status="drafted", letter=letter, warnings=warnings)


def set_sent(conn, vid, note):
    _update(conn, vid, status="sent", note=note)


def set_letter(conn, vid, letter):
    _update(conn, vid, letter=letter)


def set_status(conn, vid, status):
    _update(conn, vid, status=status)


def count_today(conn, status):
    return conn.execute(
        "SELECT COUNT(*) FROM vacancies WHERE status=? AND date(updated)=date('now','localtime')",
        (status,)).fetchone()[0]


# Titles the bot never applies to: wrong level, or not a DevOps role.
EXCLUDE_ALWAYS = re.compile(
    r"стаж[её]р|intern\b|trainee|ученик|junior|джуниор|младш|тимлид|team\s*lead|tech\w*\s*lead|"
    r"техническ\w+\s+лидер|руководител|head\s+of|начальник|\blead\b", re.I)
# Sysadmin roles are fine when the title also says DevOps/SRE.
EXCLUDE_UNLESS_DEVOPS = re.compile(r"администратор|sysadmin|системн\w+\s+инженер|техническ\w+\s+поддержк", re.I)
KEEP = re.compile(r"devops|девопс|sre", re.I)


def title_excluded(title):
    return bool(EXCLUDE_ALWAYS.search(title)) or (
        bool(EXCLUDE_UNLESS_DEVOPS.search(title)) and not KEEP.search(title))


def skip_excluded(conn):
    """Mark queued (new/drafted) vacancies with an excluded title as skipped; returns the count."""
    n = 0
    for status in ("new", "drafted"):
        for r in by_status(conn, status):
            if title_excluded(r["title"]):
                set_status(conn, r["id"], "skipped")
                n += 1
    return n


# Sent rows are the history behind the dashboard statistics: they are never deleted.
CLEANABLE = ("new", "drafted", "manual", "skipped")


def backup(conn):
    """Copy the database next to itself (state.sqlite.bak) before a destructive operation."""
    dst = sqlite3.connect(DB_PATH + ".bak")
    with dst:
        conn.backup(dst)
    dst.close()


def clean(conn, statuses=CLEANABLE):
    """Delete found-but-not-sent vacancies; returns the number of rows removed."""
    bad = set(statuses) - set(CLEANABLE)
    if bad or not statuses:
        raise ValueError(f"cannot clean statuses: {sorted(bad) or 'none given'}")
    marks = ",".join("?" * len(statuses))
    n = conn.execute(f"DELETE FROM vacancies WHERE status IN ({marks})", tuple(statuses)).rowcount
    conn.commit()
    return n


def mark(conn, vid, action):
    """Resolve an item of the dashboard's manual lists; False if the row is not in the expected state."""
    row = conn.execute("SELECT status, note FROM vacancies WHERE id=?", (vid,)).fetchone()
    if not row:
        return False
    if action == "done" and row["status"] == "manual":  # applied by hand
        set_sent(conn, vid, "manual")
    elif action == "dismiss" and row["status"] == "manual":  # not interested
        set_status(conn, vid, "skipped")
    elif action == "letter_done" and row["status"] == "sent" and row["note"] == "none":
        _update(conn, vid, note="manual-letter")  # letter attached by hand
    else:
        return False
    return True
