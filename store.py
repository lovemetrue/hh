import re
import sqlite3

SCHEMA = """CREATE TABLE IF NOT EXISTS vacancies(
  id TEXT PRIMARY KEY, url TEXT, title TEXT, company TEXT, description TEXT,
  status TEXT DEFAULT 'new', letter TEXT DEFAULT '', warnings TEXT DEFAULT '',
  updated TEXT DEFAULT (datetime('now','localtime')))"""


def connect(path="state.sqlite"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
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
