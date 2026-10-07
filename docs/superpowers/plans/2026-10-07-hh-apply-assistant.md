# hh.ru apply assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A semi-automatic CLI that collects hh.ru vacancies, drafts a cover letter per vacancy from resume facts, and prepares the response form in the user's own browser; the human clicks send.

**Architecture:** Three small modules. `store.py` (sqlite3 queue), `letter.py` (Requesty LLM call plus checks, no browser), `bot.py` (argparse CLI plus Playwright with a persistent profile). The bot never submits a response and never touches captcha.

**Tech Stack:** Python 3, Playwright (sync API, headed Chromium), sqlite3/urllib from stdlib, pytest. LLM: Requesty router, OpenAI-compatible, model `google/gemma-4-31b-it`.

**Spec:** `docs/superpowers/specs/2026-10-07-hh-apply-assistant-design.md`

## Global Constraints

- Code comments, CLI output and commit messages are in English; resume facts and letters are in Russian.
- `REQUESTY_API_KEY` lives only in `.env` (gitignored). Never print it, never put it in code or tests. The user pastes it; do not transcribe it from a screenshot.
- Resume contacts (phone, e-mail, links) never go to the LLM and never appear in `resume_facts.md`.
- The bot never presses the final "Откликнуться"/send button, never solves captcha, never replays hh internal requests outside the browser, never types the hh password.
- Daily limit: 15 responses marked `sent` per local day; random pause 20-60 s between page loads in `collect`.
- Selectors are `data-qa` only, kept in one `SEL` dict; a missing selector raises loudly.
- Commits: the user has not asked for commits yet. Ask once before the first `git commit`; `git init` is local only.

## File Structure

```
hh-bot/
  bot.py              # CLI: login, check-selectors, collect, draft, review (Playwright)
  store.py            # sqlite queue + vacancy id parsing
  letter.py           # prompt, Requesty call, letter checks
  resume_facts.md     # resume facts without contacts
  requirements.txt    # playwright, pytest
  .env.example        # REQUESTY_API_KEY=
  .gitignore          # .env, .profile/, state.sqlite, __pycache__/
  test_store.py
  test_letter.py
```

Deviation from the spec: the spec said the bot clicks "Откликнуться". On hh a click on that button may send the response immediately, without a letter. So the user clicks it; the bot copies the letter to the clipboard and, if the letter field appears, fills it.

---

### Task 1: Scaffold, resume facts, store

**Files:**
- Create: `.gitignore`, `.env.example`, `requirements.txt`, `resume_facts.md`, `store.py`, `test_store.py`

**Interfaces:**
- Produces (`store.py`):
  - `connect(path: str = "state.sqlite") -> sqlite3.Connection` (row_factory=Row, schema created)
  - `vid_from_url(url: str) -> str` (digits after `/vacancy/`, raises `ValueError`)
  - `add(conn, v: dict) -> bool` (v keys: id, url, title, company, description; True if new)
  - `by_status(conn, status: str) -> list[Row]`
  - `set_draft(conn, vid: str, letter: str, warnings: str) -> None` (status `drafted`)
  - `set_letter(conn, vid: str, letter: str) -> None`
  - `set_status(conn, vid: str, status: str) -> None`
  - `count_today(conn, status: str) -> int`
  - Statuses: `new`, `drafted`, `sent`, `skipped`.

- [ ] **Step 1: Create scaffold files**

`.gitignore`:
```
.env
.profile/
state.sqlite
__pycache__/
```

`.env.example`:
```
REQUESTY_API_KEY=
```

`requirements.txt`:
```
playwright
pytest
```

`resume_facts.md` (the user must review it; every line comes from the resume):
```markdown
# Resume facts (no contacts)

Роль: DevOps / DevSecOps инженер, опыт 4 года 1 месяц, Санкт-Петербург, удалённо или гибрид.
Английский: B1 (обновить, если изменился).

## Мад Софт, DevSecOps-инженер, с октября 2025
- Проектирование, развёртывание и сопровождение инфраструктуры (on-prem и облака).
- Автоматизация и IaC: Ansible, Terraform, Bash.
- CI/CD: GitLab, TeamCity, Jenkins.
- Управление кластерами Kubernetes: сетевые политики, ingress, ресурсы, обновления, helm. Проектировал миграцию с ingress-nginx-controller на Envoy Gateway.
- Контейнеризация: Docker, Podman, containerd; виртуализация VMware в ЦОДе.
- Observability: Prometheus, Grafana, ELK/EFK, OpenTelemetry (метрики, логи, алерты).
- Безопасность в пайплайне и инфраструктуре: секреты, права доступа, базовые практики ИБ и SDLC.
- Отказоустойчивость и производительность: балансировка, кластеризация, резервирование, бэкапы, кластерные бэкапы Velero, DR.
- Распределённые хранилища и S3: SeaweedFS, Minio, Garage.
- Внедрил DevSecOps-ядро в государственную инфраструктуру: Harbor, Trivy, Dependency Track + CycloneDX, OWASP ZAP, Checkov, Semgrep, Falco (соответствует SLSA, ISO/IEC 27001, NIST SP 800-53).

## ELMA, SRE-инженер, октябрь 2024 - октябрь 2025
- Развернул multinode-кластер Kubernetes на bare-metal (kubeadm, Calico, Longhorn), настроил Ingress, мониторинг и аутентификацию.
- Ingress-контроллеры Nginx, HAProxy: TLS, CORS, балансировка.
- Отказоустойчивый кластер PostgreSQL: Patroni, pgBouncer, HAProxy.
- Разбор OOMKilled и CPU throttling (HPA/VPA, requests/limits).
- Мониторинг и профилирование: Prometheus, Grafana, Loki, Pyroscope, pprof.
- Внедрил ArgoCD (GitOps, multi-cluster, RBAC): время деплоя меньше на 30%.
- Нашёл утечку памяти в сервисе аутентификации: потребление упало с 192 ГБ до 24 ГБ.
- Централизованный сбор логов (Loki) и трейсов (Tempo) ускорил расследование инцидентов.
- Тюнинг swappiness и vm.dirty_ratio снизил латентность примерно на 30%.
- Ansible, GitLab CE, GitHub Actions, Docker, Docker Compose, Bash, Python.

## E-telecom, специалист техподдержки, март - октябрь 2024
- Удалённая диагностика коммутаторов (telnet, ssh), VLAN, DNS, DHCP.
- Zabbix, Observium, NetUp, The Dude.
- За 3 месяца повышен до второго грейда.

## Раньше
- YCLIENTS, техподдержка (2016-2017); НПО Взлёт, помощник сисадмина, bash-скрипты (2015).
```

- [ ] **Step 2: Write the failing store test**

`test_store.py`:
```python
import pytest
import store


def vac(i="1"):
    return {"id": i, "url": f"https://hh.ru/vacancy/{i}", "title": "DevOps",
            "company": "Acme", "description": "k8s"}


def test_vid_from_url():
    assert store.vid_from_url("https://spb.hh.ru/vacancy/138162602?query=x") == "138162602"
    with pytest.raises(ValueError):
        store.vid_from_url("https://hh.ru/employer/5950")


def test_add_is_idempotent_and_status_flow():
    conn = store.connect(":memory:")
    assert store.add(conn, vac()) is True
    assert store.add(conn, vac()) is False
    assert [r["id"] for r in store.by_status(conn, "new")] == ["1"]

    store.set_draft(conn, "1", "letter", "length 10")
    row = store.by_status(conn, "drafted")[0]
    assert (row["letter"], row["warnings"]) == ("letter", "length 10")

    store.set_letter(conn, "1", "edited")
    assert store.by_status(conn, "drafted")[0]["letter"] == "edited"

    assert store.count_today(conn, "sent") == 0
    store.set_status(conn, "1", "sent")
    assert store.count_today(conn, "sent") == 1
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/madsoft/Desktop/MadSoftProjects/hh-bot && python3 -m pytest test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'store'`

- [ ] **Step 4: Write `store.py`**

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest test_store.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit (ask the user first, see Global Constraints)**

```bash
git init
git add .gitignore .env.example requirements.txt resume_facts.md store.py test_store.py
git commit -m "feat: scaffold, resume facts and sqlite store"
```

---

### Task 2: Letter generation and checks

**Files:**
- Create: `letter.py`, `test_letter.py`

**Interfaces:**
- Consumes: `resume_facts.md` text (str), vacancy dict with `title`, `company`, `description`.
- Produces (`letter.py`):
  - `build_messages(facts: str, vacancy: dict) -> list[dict]`
  - `call_llm(messages: list[dict]) -> str` (reads `REQUESTY_API_KEY` from env)
  - `check_letter(text: str, facts: str) -> list[str]` (empty list means clean)
  - `generate_letter(facts: str, vacancy: dict, llm=call_llm) -> tuple[str, list[str]]`
  - Constants `PHONE`, `EMAIL` regexes (reused by tests).

- [ ] **Step 1: Write the failing tests**

`test_letter.py`:
```python
from pathlib import Path

import letter

FACTS = "Kubernetes Docker Terraform Ansible GitLab DevSecOps"
GOOD = "Здравствуйте! " + "Работаю с Kubernetes и Docker, автоматизирую инфраструктуру на Terraform и Ansible. " * 8
VAC = {"title": "DevOps", "company": "Acme", "description": "Нужен Kubernetes"}


def test_clean_letter_has_no_problems():
    assert letter.check_letter(GOOD, FACTS) == []


def test_phone_email_and_unknown_tech_are_flagged():
    assert "phone number" in letter.check_letter(GOOD + " +7 900 000 0000", FACTS)
    assert "e-mail" in letter.check_letter(GOOD + " me@example.com", FACTS)
    problems = letter.check_letter(GOOD + " Знаю Hadoop.", FACTS)
    assert any("Hadoop" in p for p in problems)


def test_length_is_flagged():
    assert any(p.startswith("length") for p in letter.check_letter("Привет", FACTS))


def test_english_letter_skips_unknown_word_check():
    text = "Hello, I run Kubernetes clusters and Docker builds at scale. " * 12
    assert letter.check_letter(text, FACTS) == []


def test_generate_uses_facts_and_vacancy_only():
    seen = {}

    def fake(messages):
        seen["text"] = " ".join(m["content"] for m in messages)
        return GOOD

    text, problems = letter.generate_letter(FACTS, VAC, llm=fake)
    assert text == GOOD and problems == []
    assert "Kubernetes" in seen["text"] and "Нужен Kubernetes" in seen["text"]


def test_resume_facts_file_has_no_contacts():
    p = Path(__file__).parent / "resume_facts.md"
    facts = p.read_text()
    assert not letter.PHONE.search(facts) and not letter.EMAIL.search(facts)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test_letter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'letter'`

- [ ] **Step 3: Write `letter.py`**

```python
import json
import os
import re
import urllib.request

URL = "https://router.requesty.ai/v1/chat/completions"
MODEL = "google/gemma-4-31b-it"
SYSTEM = (
    "You write short cover letters for a job seeker.\n"
    "Use ONLY the facts in RESUME FACTS. Never invent technologies, employers, "
    "titles, numbers or years.\n"
    "Write in Russian, unless the vacancy text is in English; then write in English.\n"
    "700-1000 characters, plain text, no emoji, no bullet lists, no placeholders, "
    "no contact details.\n"
    "Address the reader without a name unless the vacancy gives one.\n"
    "Pick only the facts relevant to this vacancy; do not repeat the whole resume."
)

PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
LATIN = re.compile(r"[A-Za-z][A-Za-z0-9+#.-]{2,}")
CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def build_messages(facts, vacancy):
    user = (f"RESUME FACTS:\n{facts}\n\n"
            f"VACANCY:\n{vacancy['title']} at {vacancy['company']}\n"
            f"{vacancy['description'][:6000]}")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def call_llm(messages):
    key = os.environ["REQUESTY_API_KEY"]
    req = urllib.request.Request(
        URL, json.dumps({"model": MODEL, "messages": messages}).encode(),
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["choices"][0]["message"]["content"].strip()


def check_letter(text, facts):
    problems = []
    if PHONE.search(text):
        problems.append("phone number")
    if EMAIL.search(text):
        problems.append("e-mail")
    if not 500 <= len(text) <= 1300:
        problems.append(f"length {len(text)}")
    # Latin words missing from the facts hint at invented tech; skipped for English letters.
    if CYRILLIC.search(text):
        known = facts.lower()
        unknown = sorted({w for w in LATIN.findall(text) if w.lower() not in known})
        if unknown:
            problems.append("not in resume: " + ", ".join(unknown))
    return problems


def generate_letter(facts, vacancy, llm=call_llm):
    text = llm(build_messages(facts, vacancy))
    return text, check_letter(text, facts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest test_letter.py test_store.py -v`
Expected: 8 passed

- [ ] **Step 5: Live LLM check (needs the user's `.env`)**

Ask the user to copy `.env.example` to `.env` and paste the key. Then run:
```bash
set -a; . ./.env; set +a
python3 - <<'EOF'
import letter
facts = open("resume_facts.md").read()
vac = {"title": "DevOps engineer", "company": "Acme",
       "description": "Kubernetes, GitLab CI, Terraform, Prometheus. Remote."}
text, problems = letter.generate_letter(facts, vac)
print(text); print("PROBLEMS:", problems)
EOF
```
Expected: a Russian letter of roughly 700-1000 characters; read it for invented facts. If `problems` lists words that are legitimately in the resume, add them to `resume_facts.md`; if the letter embellishes, tighten `SYSTEM` and re-run. Do not paste the key into any output.

- [ ] **Step 6: Commit**

```bash
git add letter.py test_letter.py
git commit -m "feat: cover letter generation with fact checks"
```

---

### Task 3: Browser skeleton, login and selector check

**Files:**
- Create: `bot.py`

**Interfaces:**
- Consumes: `store` module (Task 1).
- Produces (`bot.py`):
  - `SEL: dict[str, str]` with keys `serp_link`, `title`, `company`, `description`, `letter`, `applied`, `captcha`
  - `load_env(path: str = ".env") -> None` (sets missing env vars)
  - `open_context(p) -> BrowserContext` (persistent profile `.profile/`, headed, `ru-RU`)
  - `guard(page) -> None` (pauses for the human if the captcha selector is present)
  - `pause(lo: float = 20, hi: float = 60) -> None`
  - CLI `main()` with subcommands `login`, `check-selectors <url>`; later tasks add `collect`, `draft`, `review`.

- [ ] **Step 1: Install Playwright**

Run:
```bash
cd /Users/madsoft/Desktop/MadSoftProjects/hh-bot
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
```
Expected: `playwright install` finishes with Chromium downloaded.

- [ ] **Step 2: Write `bot.py` skeleton**

```python
import argparse
import os
import random
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

import letter
import store

DAILY_LIMIT = 15
PROFILE = str(Path(__file__).parent / ".profile")

# data-qa selectors only; fix here when hh changes its markup (see `check-selectors`).
SEL = {
    "serp_link": 'a[data-qa="serp-item__title"]',
    "title": '[data-qa="vacancy-title"]',
    "company": '[data-qa="vacancy-company-name"]',
    "description": '[data-qa="vacancy-description"]',
    "letter": 'textarea[name="text"], [data-qa="vacancy-response-popup-form-letter-input"]',
    "applied": '[data-qa="vacancy-response-link-view-topic"]',
    "captcha": '[data-qa*="captcha"], iframe[src*="captcha"]',
}


def load_env(path=".env"):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def open_context(p):
    return p.chromium.launch_persistent_context(PROFILE, headless=False, locale="ru-RU")


def first_page(ctx):
    return ctx.pages[0] if ctx.pages else ctx.new_page()


def pause(lo=20, hi=60):
    time.sleep(random.uniform(lo, hi))


def guard(page):
    # Hand control to the human on captcha; never try to solve it.
    if page.query_selector(SEL["captcha"]):
        input("Captcha or anti-bot check shown. Solve it in the browser, then press Enter... ")


def cmd_login(args):
    with sync_playwright() as p:
        ctx = open_context(p)
        first_page(ctx).goto("https://hh.ru/account/login")
        input("Log in to hh.ru in the browser window, then press Enter here... ")
        ctx.close()


def cmd_check_selectors(args):
    with sync_playwright() as p:
        ctx = open_context(p)
        page = first_page(ctx)
        page.goto(args.url)
        guard(page)
        for key, sel in SEL.items():
            print(f"{key:12} {len(page.query_selector_all(sel))} match(es)")
        ctx.close()


def main():
    ap = argparse.ArgumentParser(prog="bot.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login").set_defaults(fn=cmd_login)
    c = sub.add_parser("check-selectors")
    c.add_argument("url")
    c.set_defaults(fn=cmd_check_selectors)
    args = ap.parse_args()
    load_env()
    args.fn(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Log in (user action)**

Run: `python3 bot.py login`
Expected: a Chromium window opens on the hh login page. The user logs in themselves, then presses Enter in the terminal; the session is kept in `.profile/`.

- [ ] **Step 4: Verify selectors on a search page and a vacancy page**

Ask the user for one search URL (their saved search) and one vacancy URL. Run:
```bash
python3 bot.py check-selectors "<search-url>"
python3 bot.py check-selectors "https://hh.ru/vacancy/138162602"
```
Expected: on the search page `serp_link` has 1+ matches; on the vacancy page `title`, `company`, `description` have 1 match each; `captcha` has 0. Any key showing 0 where it should match: open DevTools on that page, find the real `data-qa`, update `SEL`, re-run until the expected keys match. `letter` and `applied` are verified in Task 6.

- [ ] **Step 5: Commit**

```bash
git add bot.py
git commit -m "feat: browser skeleton, login and selector check"
```

---

### Task 4: `collect`

**Files:**
- Modify: `bot.py` (add `read_vacancy`, `cmd_collect`, subparser)

**Interfaces:**
- Consumes: `SEL`, `guard`, `pause`, `first_page`, `open_context` (Task 3); `store.add`, `store.vid_from_url`, `store.connect`.
- Produces:
  - `read_vacancy(page, url: str) -> dict` (keys id, url, title, company, description; raises `RuntimeError` naming the missing selector)
  - CLI `collect <search-url> [--pages N]` (default 2 pages) printing `added X new, skipped Y known`.

- [ ] **Step 1: Add `read_vacancy` and `cmd_collect` above `main()`**

```python
def read_vacancy(page, url):
    page.goto(url)
    guard(page)
    data = {"id": store.vid_from_url(url), "url": url}
    for key in ("title", "company", "description"):
        el = page.query_selector(SEL[key])
        if el is None:
            raise RuntimeError(f"selector '{key}' not found on {url}; run check-selectors")
        data[key] = el.inner_text().strip()
    return data


def cmd_collect(args):
    conn = store.connect()
    added = skipped = 0
    with sync_playwright() as p:
        ctx = open_context(p)
        page = first_page(ctx)
        links = []
        for n in range(args.pages):
            sep = "&" if "?" in args.url else "?"
            page.goto(f"{args.url}{sep}page={n}")
            guard(page)
            hrefs = [a.get_attribute("href") for a in page.query_selector_all(SEL["serp_link"])]
            links += [h.split("?")[0] for h in hrefs if h and "/vacancy/" in h]
            pause(3, 8)
        for url in dict.fromkeys(links):
            exists = conn.execute("SELECT 1 FROM vacancies WHERE id=?",
                                  (store.vid_from_url(url),)).fetchone()
            if exists:
                skipped += 1
                continue
            store.add(conn, read_vacancy(page, url))
            added += 1
            print(f"+ {url}")
            pause()
        ctx.close()
    print(f"added {added} new, skipped {skipped} known")
```

- [ ] **Step 2: Register the subcommand in `main()`**

Add after the `check-selectors` block:
```python
    c = sub.add_parser("collect")
    c.add_argument("url")
    c.add_argument("--pages", type=int, default=2)
    c.set_defaults(fn=cmd_collect)
```

- [ ] **Step 3: Run it on a small search**

Run: `python3 bot.py collect "<search-url>" --pages 1`
Expected: lines `+ https://hh.ru/vacancy/...` for new vacancies (with 20-60 s pauses), then `added N new, skipped 0 known`. Re-running immediately prints `added 0 new, skipped N known`.

- [ ] **Step 4: Check the queue**

Run: `python3 -c "import store; c=store.connect(); print([(r['id'], r['title'], r['company']) for r in store.by_status(c,'new')][:5])"`
Expected: real titles and companies, descriptions non-empty.

- [ ] **Step 5: Commit**

```bash
git add bot.py
git commit -m "feat: collect vacancies from a saved search"
```

---

### Task 5: `draft`

**Files:**
- Modify: `bot.py` (add `cmd_draft`, subparser)

**Interfaces:**
- Consumes: `letter.generate_letter`, `store.by_status`, `store.set_draft`, `load_env` (key must be in env).
- Produces: CLI `draft [--limit N]` (default 15) that moves `new` vacancies to `drafted`.

- [ ] **Step 1: Add `cmd_draft` above `main()`**

```python
def cmd_draft(args):
    facts = Path("resume_facts.md").read_text()
    conn = store.connect()
    for v in store.by_status(conn, "new")[: args.limit]:
        text, problems = letter.generate_letter(facts, dict(v))
        store.set_draft(conn, v["id"], text, "; ".join(problems))
        print(f"{v['id']} {v['title']} | warnings: {problems or 'none'}")
```

- [ ] **Step 2: Register the subcommand in `main()`**

```python
    c = sub.add_parser("draft")
    c.add_argument("--limit", type=int, default=DAILY_LIMIT)
    c.set_defaults(fn=cmd_draft)
```

- [ ] **Step 3: Run on the collected vacancies**

Run: `python3 bot.py draft --limit 3`
Expected: three lines `<id> <title> | warnings: ...`. If `KeyError: 'REQUESTY_API_KEY'`, the `.env` is missing the key.

- [ ] **Step 4: Read the drafts**

Run: `python3 -c "import store; [print(r['title'], '\n', r['letter'], '\n', r['warnings'], '\n---') for r in store.by_status(store.connect(),'drafted')]"`
Expected: Russian letters grounded in `resume_facts.md`; warnings only where the check fired. Anything invented: fix `SYSTEM` in `letter.py` or the facts file and re-draft (reset with `UPDATE vacancies SET status='new' WHERE status='drafted'` on `state.sqlite`).

- [ ] **Step 5: Commit**

```bash
git add bot.py
git commit -m "feat: draft cover letters for new vacancies"
```

---

### Task 6: `review`

**Files:**
- Modify: `bot.py` (add `edit_text`, `prepare_response`, `cmd_review`, subparser)

**Interfaces:**
- Consumes: everything above; `store.set_letter`, `store.set_status`, `store.count_today`.
- Produces: CLI `review` walking `drafted` vacancies with `[s]end / [e]dit / [k]skip / [q]uit`. On `s` it opens the vacancy, copies the letter to the clipboard (`pbcopy`), fills the letter field if it appears, waits for the human to send, then marks `sent` if the applied marker is visible or the human confirms.

- [ ] **Step 1: Add the helpers and the command above `main()`**

```python
def edit_text(text):
    with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False) as f:
        f.write(text)
        path = f.name
    subprocess.run([os.environ.get("EDITOR", "nano"), path], check=True)
    out = Path(path).read_text().strip()
    Path(path).unlink()
    return out


def prepare_response(page, v):
    """Open the vacancy and stage the letter. The human clicks the response/send buttons."""
    page.goto(v["url"])
    guard(page)
    subprocess.run(["pbcopy"], input=v["letter"].encode(), check=True)
    print("Letter is in the clipboard. In the browser: click 'Откликнуться', "
          "paste the letter if the field is empty, press send.")
    try:
        page.wait_for_selector(SEL["letter"], timeout=60_000)
        page.fill(SEL["letter"], v["letter"])
        print("Letter field filled.")
    except PWTimeout:
        print("Letter field did not appear; use the clipboard.")
    input("Press Enter here after you pressed send (or if you give up)... ")
    page.reload()
    if page.query_selector(SEL["applied"]):
        return True
    return input("Response not detected on the page. Mark as sent? [y/N] ").strip().lower() == "y"


def cmd_review(args):
    conn = store.connect()
    with sync_playwright() as p:
        ctx = open_context(p)
        page = first_page(ctx)
        for v in store.by_status(conn, "drafted"):
            if store.count_today(conn, "sent") >= DAILY_LIMIT:
                print(f"Daily limit {DAILY_LIMIT} reached.")
                break
            while True:
                v = conn.execute("SELECT * FROM vacancies WHERE id=?", (v["id"],)).fetchone()
                print(f"\n=== {v['title']} | {v['company']}\n{v['url']}")
                print(f"warnings: {v['warnings'] or 'none'}\n\n{v['letter']}\n")
                a = input("[s]end / [e]dit / [k]skip / [q]uit: ").strip().lower()
                if a == "e":
                    store.set_letter(conn, v["id"], edit_text(v["letter"]))
                elif a == "k":
                    store.set_status(conn, v["id"], "skipped")
                    break
                elif a == "q":
                    ctx.close()
                    return
                elif a == "s":
                    if prepare_response(page, v):
                        store.set_status(conn, v["id"], "sent")
                    break
        ctx.close()
```

- [ ] **Step 2: Register the subcommand in `main()`**

```python
    sub.add_parser("review").set_defaults(fn=cmd_review)
```

- [ ] **Step 3: Dry-run on ONE vacancy with the user**

Run: `python3 bot.py review`
Walk through the first vacancy with the user: press `s`, watch what happens when the user clicks "Откликнуться" (does a letter field appear? does the response send immediately?). Record the real flow. Expected: the vacancy page opens, the letter is in the clipboard; if the field appears it is filled; after the user sends and presses Enter the vacancy is marked `sent` (applied marker or `y`).

- [ ] **Step 4: Fix `SEL["letter"]` / `SEL["applied"]` from what was observed**

If the letter field never auto-filled, DevTools on the open form gives the real `data-qa`/`name`; if `applied` was never detected, find the marker shown after sending. Update `SEL`, re-run `python3 bot.py review` on the next vacancy to confirm. Expected: both detected, or the clipboard fallback documented as the normal path.

- [ ] **Step 5: Commit**

```bash
git add bot.py
git commit -m "feat: review loop with browser-assisted response"
```

---

### Task 7: README and final check

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# hh-bot

Полуавтомат для откликов на hh.ru: собирает вакансии, пишет письма по фактам
из резюме, готовит форму в твоём браузере. Кнопку отправки нажимаешь ты.

## Установка
    python3 -m pip install -r requirements.txt
    python3 -m playwright install chromium
    cp .env.example .env   # вставить REQUESTY_API_KEY

## Использование
    python3 bot.py login                      # один раз, вход делаешь сам
    python3 bot.py collect "<URL поиска hh>"  # собрать вакансии
    python3 bot.py draft                      # написать письма
    python3 bot.py review                     # просмотр и отклик по одной

Лимит 15 откликов в день. При капче бот останавливается и ждёт тебя.
Сломалась вёрстка: `python3 bot.py check-selectors <url>` и правка `SEL` в bot.py.
Перед отправкой читай письмо: модель может приукрасить, предупреждения
проверки показываются над текстом. Файл `resume_facts.md` держи без контактов.
```

- [ ] **Step 2: Run the full test suite**

Run: `python3 -m pytest -v`
Expected: 8 passed.

- [ ] **Step 3: Confirm nothing secret is tracked**

Run: `git status --short && git ls-files | grep -E '^\.env$|\.profile|state\.sqlite' || echo "clean"`
Expected: `clean` printed (no `.env`, profile or database in the index).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: usage readme"
```

---

## Self-Review (done)

- **Spec coverage:** collect/draft/review → Tasks 4-6; daily limit 15 and pauses → constants plus `pause` in `collect`, `count_today` in `review`; captcha handoff → `guard`; `data-qa` only plus loud failure → `SEL` and `read_vacancy`; Requesty/Gemma/.env → Task 2; resume facts without contacts and smoke test → Tasks 1-2; human final click → Task 6 and the deviation note.
- **Placeholders:** none; the only open points are live-verified selectors (Tasks 3 and 6 have explicit steps for them).
- **Type consistency:** `store` function names and `letter` signatures match across tasks; `SEL` keys are the same everywhere.
