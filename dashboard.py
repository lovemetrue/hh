"""Local dashboard for hh-bot: stats, start a run by count, progress, cancel.

Stdlib only. Run: python3 dashboard.py  ->  http://127.0.0.1:8765
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import store

HERE = Path(__file__).parent
DATA = Path(os.environ.get("DATA_DIR") or HERE / "data")
STATE_FILE = DATA / "run_state.json"
LOG_FILE = DATA / "run.log"
SESSION_FILE = DATA / "session.json"
HOST = os.environ.get("DASH_HOST", "127.0.0.1")
PORT = int(os.environ.get("DASH_PORT", 8765))
DAILY_LIMIT = 100

lock = threading.Lock()
proc = None  # the bot process started from this dashboard


def tail(path, n=14):
    try:
        return path.read_text(errors="replace").splitlines()[-n:]
    except OSError:
        return []


def run_info():
    state = {}
    try:
        state = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        pass
    running = proc is not None and proc.poll() is None
    if state.get("state") in ("running", "collecting", "drafting") and not running:
        state["state"] = "crashed"  # the process is gone without a final report
    state["running"] = running
    state["log"] = tail(LOG_FILE)
    state["session"] = SESSION_FILE.exists() or os.environ.get("HH_USE_SESSION") != "1"
    return state


def stats():
    c = store.connect()
    one = lambda sql: c.execute(sql).fetchone()[0]
    counts = {r["status"]: r["n"] for r in c.execute("select status, count(*) n from vacancies group by status")}
    days = {r["d"]: r["n"] for r in c.execute(
        "select date(updated) d, count(*) n from vacancies where status='sent' "
        "and date(updated) >= date('now','-13 days','localtime') group by d")}
    today = date.today()
    daily = [{"day": (today - timedelta(days=i)).isoformat(),
              "n": days.get((today - timedelta(days=i)).isoformat(), 0)} for i in range(13, -1, -1)]
    sources = {(r["note"] or "n/a"): r["n"] for r in c.execute(
        "select note, count(*) n from vacancies where status='sent' group by note")}
    recent = [dict(r) for r in c.execute(
        "select updated, company, title, url, note from vacancies where status='sent' "
        "order by updated desc limit 20")]
    return {
        "counts": counts,
        "today": one("select count(*) from vacancies where status='sent' and date(updated)=date('now','localtime')"),
        "week": one("select count(*) from vacancies where status='sent' and updated >= datetime('now','-7 days','localtime')"),
        "total": counts.get("sent", 0),
        "queue": counts.get("new", 0) + counts.get("drafted", 0),
        "daily_limit": DAILY_LIMIT,
        "daily": daily,
        "sources": sources,
        "recent": recent,
    }


def start_run(count, collect):
    global proc
    with lock:
        if proc is not None and proc.poll() is None:
            return False, "Запуск уже идёт"
        if collect:
            cmd = [sys.executable, "bot.py", "auto", "--max", str(count),
                   "--pages", str(max(1, min(6, count // 30 + 1)))]
        else:
            cmd = [sys.executable, "bot.py", "send", "--limit", str(count)]
        DATA.mkdir(parents=True, exist_ok=True)
        log = open(LOG_FILE, "w")
        proc = subprocess.Popen(cmd, cwd=HERE, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                env={**os.environ, "PYTHONUNBUFFERED": "1"})
        return True, "Запущено"


def cancel_run(force):
    with lock:
        if proc is None or proc.poll() is not None:
            return False, "Нет активного запуска"
        if force:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)  # bot and its browser
            return True, "Прервано принудительно"
        os.kill(proc.pid, signal.SIGTERM)  # the bot finishes the current vacancy and stops cleanly
        return True, "Останавливаю после текущей вакансии"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def local_only(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost", "[::1]")

    def do_GET(self):
        if not self.local_only():
            return self.send_json({"error": "forbidden"}, 403)
        if self.path == "/api/stats":
            return self.send_json(stats())
        if self.path == "/api/run":
            return self.send_json(run_info())
        if self.path in ("/", "/index.html"):
            body = (HERE / "dashboard.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        # Browser-form CSRF guard: only JSON from a local Host is accepted.
        if not self.local_only() or "application/json" not in (self.headers.get("Content-Type") or ""):
            return self.send_json({"error": "forbidden"}, 403)
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.send_json({"error": "bad json"}, 400)
        if self.path == "/api/start":
            count = int(data.get("count") or 0)
            if not 1 <= count <= DAILY_LIMIT:
                return self.send_json({"ok": False, "message": f"Количество от 1 до {DAILY_LIMIT}"}, 400)
            ok, msg = start_run(count, bool(data.get("collect")))
            return self.send_json({"ok": ok, "message": msg}, 200 if ok else 409)
        if self.path == "/api/clean":
            with lock:
                if proc is not None and proc.poll() is None:
                    return self.send_json({"ok": False, "message": "Сначала остановите запуск"}, 409)
                statuses = tuple(data.get("statuses") or ())
                try:
                    conn = store.connect()
                    store.backup(conn)
                    n = store.clean(conn, statuses)
                except ValueError as e:
                    return self.send_json({"ok": False, "message": str(e)}, 400)
            return self.send_json({"ok": True, "message": f"Удалено вакансий: {n} (копия базы: state.sqlite.bak)"})
        if self.path == "/api/cancel":
            ok, msg = cancel_run(bool(data.get("force")))
            return self.send_json({"ok": ok, "message": msg}, 200 if ok else 409)
        self.send_json({"error": "not found"}, 404)


if __name__ == "__main__":
    print(f"dashboard on http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
