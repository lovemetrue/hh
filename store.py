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
