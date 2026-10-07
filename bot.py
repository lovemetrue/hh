import argparse
import os
import random
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

import letter
import store

DAILY_LIMIT = 15
HERE = Path(__file__).parent
MAX_FAILURES = 3


class AlreadyApplied(RuntimeError):
    pass


def clean(text):
    # Strip ESC so vacancy/letter text cannot inject terminal escape sequences.
    return (text or "").replace("\x1b", "")
PROFILE = str(Path(__file__).parent / ".profile")

# captcha is detected via data-qa or an iframe src; detection only, never interaction
# data-qa selectors only; fix here when hh changes its markup (see `check-selectors`).
SEL = {
    "serp_link": 'a[data-qa="serp-item__title"]',
    "title": '[data-qa="vacancy-title"]',
    "company": '[data-qa="vacancy-company-name"]',
    "description": '[data-qa="vacancy-description"]',
    "letter": '[data-qa="vacancy-response-popup-form-letter-input"]',
    "applied": '[data-qa="vacancy-response-link-view-topic"]',
    "captcha": '[data-qa*="captcha"], iframe[src*="captcha"]',
}


def load_env(path=HERE / ".env"):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"\''))


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
        try:
            first_page(ctx).goto("https://hh.ru/account/login")
            input("Log in to hh.ru in the browser window, then press Enter here... ")
        finally:
            ctx.close()


def cmd_check_selectors(args):
    with sync_playwright() as p:
        ctx = open_context(p)
        try:
            page = first_page(ctx)
            page.goto(args.url)
            guard(page)
            for key, sel in SEL.items():
                print(f"{key:12} {len(page.query_selector_all(sel))} match(es)")
        finally:
            ctx.close()


def read_vacancy(page, url):
    page.goto(url)
    guard(page)
    if page.query_selector(SEL["applied"]):
        raise AlreadyApplied("already applied")
    data = {"id": store.vid_from_url(url), "url": url}
    for key in ("title", "company", "description"):
        el = page.query_selector(SEL[key])
        if el is None:
            raise RuntimeError(f"selector '{key}' not found on {url}; run check-selectors")
        data[key] = el.inner_text().strip()
    return data


def cmd_collect(args):
    conn = store.connect()
    added = skipped = failed = streak = 0
    with sync_playwright() as p:
        ctx = open_context(p)
        try:
            page = first_page(ctx)
            links = []
            for n in range(args.pages):
                sep = "&" if "?" in args.url else "?"
                page.goto(f"{args.url}{sep}page={n}")
                guard(page)
                hrefs = [a.get_attribute("href") for a in page.query_selector_all(SEL["serp_link"])]
                found = [h.split("?")[0] for h in hrefs if h and "/vacancy/" in h]
                if not found:
                    if n == 0:
                        raise RuntimeError("selector 'serp_link' matched nothing; run check-selectors")
                    break
                links += found
                if n < args.pages - 1:
                    pause()
            urls = list(dict.fromkeys(links))
            for i, url in enumerate(urls):
                exists = conn.execute("SELECT 1 FROM vacancies WHERE id=?",
                                      (store.vid_from_url(url),)).fetchone()
                if exists:
                    skipped += 1
                    continue
                try:
                    store.add(conn, read_vacancy(page, url))
                except Exception as e:
                    failed += 1
                    print(f"skip {url}: {e}")
                    # Layout-change failures stop the run; "already applied" is normal.
                    if not isinstance(e, AlreadyApplied):
                        streak += 1
                        if streak >= MAX_FAILURES:
                            raise RuntimeError(
                                f"{MAX_FAILURES} consecutive failures; run check-selectors") from e
                    if i < len(urls) - 1:
                        pause()
                    continue
                streak = 0
                added += 1
                print(f"+ {url}")
                if i < len(urls) - 1:
                    pause()
        finally:
            ctx.close()
    print(f"added {added} new, skipped {skipped} known, {failed} failed")


def cmd_draft(args):
    facts = (HERE / "resume_facts.md").read_text()
    conn = store.connect()
    limit = max(0, min(args.limit, DAILY_LIMIT - store.count_today(conn, "drafted")))
    if limit == 0:
        print(f"Daily draft limit {DAILY_LIMIT} exhausted; nothing to draft.")
        return
    for v in store.by_status(conn, "new")[:limit]:
        text, problems = letter.generate_letter(facts, dict(v))
        store.set_draft(conn, v["id"], text, "; ".join(problems))
        print(f"{v['id']} {v['title']} | warnings: {problems or 'none'}")


def edit_text(text):
    with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False) as f:
        f.write(text)
        path = f.name
    try:
        subprocess.run(shlex.split(os.environ.get("EDITOR", "nano")) + [path], check=True)
        return Path(path).read_text().strip()
    finally:
        Path(path).unlink()


def prepare_response(page, v):
    """Open the vacancy and stage the letter. The human clicks the response/send buttons."""
    page.goto(v["url"])
    guard(page)
    if page.query_selector(SEL["applied"]):
        print("Already responded to this vacancy; marking as skipped.")
        return None
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
    try:
        page.goto(v["url"])
        guard(page)
        if page.query_selector(SEL["applied"]):
            return True
    except Exception as e:
        print(f"Verification failed: {e}")
        return input("Could not verify on the page. Mark as sent? [y/N] ").strip().lower() == "y"
    return input("Response not detected on the page. Mark as sent? [y/N] ").strip().lower() == "y"


def cmd_review(args):
    facts = (HERE / "resume_facts.md").read_text()
    conn = store.connect()
    with sync_playwright() as p:
        ctx = open_context(p)
        try:
            page = first_page(ctx)
            for v in store.by_status(conn, "drafted"):
                if store.count_today(conn, "sent") >= DAILY_LIMIT:
                    print(f"Daily limit {DAILY_LIMIT} reached.")
                    break
                while True:
                    v = conn.execute("SELECT * FROM vacancies WHERE id=?", (v["id"],)).fetchone()
                    print(f"\n=== {clean(v['title'])} | {clean(v['company'])}\n{v['url']}")
                    print(clean(v["description"])[:800] + "\n")
                    print(f"warnings: {clean(v['warnings']) or 'none'}\n\n{clean(v['letter'])}\n")
                    a = input("[s]end / [e]dit / [k]skip / [q]uit: ").strip().lower()
                    if a == "e":
                        new = edit_text(v["letter"])
                        if not new:
                            print("Empty letter refused; keeping the old one.")
                        else:
                            store.set_draft(conn, v["id"], new,
                                            "; ".join(letter.check_letter(new, facts)))
                    elif a == "k":
                        store.set_status(conn, v["id"], "skipped")
                        break
                    elif a == "q":
                        return
                    elif a == "s":
                        done = prepare_response(page, v)
                        if done is None:
                            store.set_status(conn, v["id"], "skipped")
                        elif done:
                            store.set_status(conn, v["id"], "sent")
                        break
        finally:
            ctx.close()


def main():
    ap = argparse.ArgumentParser(prog="bot.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login").set_defaults(fn=cmd_login)
    c = sub.add_parser("check-selectors")
    c.add_argument("url")
    c.set_defaults(fn=cmd_check_selectors)
    c = sub.add_parser("collect")
    c.add_argument("url")
    c.add_argument("--pages", type=int, default=2)
    c.set_defaults(fn=cmd_collect)
    c = sub.add_parser("draft")
    c.add_argument("--limit", type=int, default=DAILY_LIMIT)
    c.set_defaults(fn=cmd_draft)
    sub.add_parser("review").set_defaults(fn=cmd_review)
    args = ap.parse_args()
    load_env()
    args.fn(args)


if __name__ == "__main__":
    main()
