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

DAILY_LIMIT = 100
HERE = Path(__file__).parent
MAX_FAILURES = 3
MAX_MANUAL = 10  # vacancies with a test or questionnaire are common; a long run hints at a layout change


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
    # verified live 2026-10-07: the apply click sends at once, the letter is attached afterwards
    "apply": 'a[data-qa="vacancy-response-link-top"]',
    "success": '[data-qa="vacancy-response-success-standard-notification"]',
    "attach": 'button[data-qa="responded-success-attach-cover-letter"]',
    "submit": '[data-qa="vacancy-response-letter-submit"]',
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


def go(page, url):
    # domcontentloaded: hh pages are heavy (ads, trackers); waiting for "load" timed out at 30 s.
    page.goto(url, wait_until="domcontentloaded", timeout=45_000)


def first_page(ctx):
    return ctx.pages[0] if ctx.pages else ctx.new_page()


def pause(lo=10, hi=30):
    time.sleep(random.uniform(lo, hi))


def guard(page):
    # Hand control to the human on captcha; never try to solve it.
    if page.query_selector(SEL["captcha"]):
        input("Captcha or anti-bot check shown. Solve it in the browser, then press Enter... ")


def cmd_login(args):
    with sync_playwright() as p:
        ctx = open_context(p)
        try:
            go(first_page(ctx), "https://hh.ru/account/login")
            input("Log in to hh.ru in the browser window, then press Enter here... ")
        finally:
            ctx.close()


def cmd_check_selectors(args):
    with sync_playwright() as p:
        ctx = open_context(p)
        try:
            page = first_page(ctx)
            go(page, args.url)
            guard(page)
            for key, sel in SEL.items():
                print(f"{key:12} {len(page.query_selector_all(sel))} match(es)")
        finally:
            ctx.close()


def read_vacancy(page, url):
    go(page, url)
    guard(page)
    if page.query_selector(SEL["applied"]):
        raise AlreadyApplied("already applied")
    data = {"id": store.vid_from_url(url), "url": url}
    for key in ("title", "company", "description"):
        el = page.query_selector(SEL[key])
        if el is None and key == "company":
            data[key] = "(employer hidden)"
            continue
        if el is None:
            raise RuntimeError(f"selector '{key}' not found on {url}; run check-selectors")
        data[key] = el.inner_text().strip()
    return data


def search_url(args):
    url = args.url or os.environ.get("HH_SEARCH_URL")
    if not url:
        raise SystemExit("Pass a search URL or set HH_SEARCH_URL in .env")
    return url


def cmd_collect(args):
    base_url = search_url(args)
    conn = store.connect()
    added = skipped = failed = streak = 0
    with sync_playwright() as p:
        ctx = open_context(p)
        try:
            page = first_page(ctx)
            links = []
            for n in range(args.pages):
                sep = "&" if "?" in base_url else "?"
                go(page, f"{base_url}{sep}page={n}")
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
                if args.max and added >= args.max:
                    break
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
    print(f"title filter: {store.skip_excluded(conn)} vacancies skipped")
    limit = max(0, min(args.limit, DAILY_LIMIT - store.count_today(conn, "drafted")))
    if limit == 0:
        print(f"Daily draft limit {DAILY_LIMIT} exhausted; nothing to draft.")
        return
    rows = store.by_status(conn, "new")[:limit]
    limited = 0
    for v in rows:
        try:
            text, problems = letter.generate_letter(facts, dict(v))
        except letter.RateLimited:
            limited += 1
            print(f"{v['id']} rate limited ({limited} in a row)")
            if limited >= MAX_FAILURES:
                print("Free-model quota exhausted. Vacancies stay 'new'; rerun `draft` later "
                      "or switch letter.MODEL to a paid model.")
                break
            continue
        except Exception as e:  # one failed LLM call must not lose the whole batch
            print(f"{v['id']} draft failed: {e}")
            continue
        limited = 0
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
    go(page, v["url"])
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
        go(page, v["url"])
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


def respond(page, v):
    """Apply and attach the letter. Returns sent | sent-no-letter | already | manual."""
    go(page, v["url"])
    guard(page)
    if page.query_selector(SEL["applied"]):
        return "already"
    buttons = [b for b in page.query_selector_all(SEL["apply"]) if b.is_visible()]
    if not buttons:
        return "manual"
    buttons[0].click()
    try:
        # hh sends the response at once; any of these shows it went through (or asks for the letter).
        page.wait_for_selector(f'{SEL["success"]}, {SEL["applied"]}, {SEL["letter"]}', timeout=3_000)
    except PWTimeout:
        guard(page)
        # the response may have gone through without a visible toast
        return "sent-no-letter" if page.query_selector(SEL["applied"]) else "manual"
    try:
        if not page.is_visible(SEL["letter"]):
            page.click(SEL["attach"], timeout=3_000)
        page.fill(SEL["letter"], v["letter"])
        page.click(SEL["submit"])
        # text match: hh shows no data-qa for this toast
        page.get_by_text("Сопроводительное письмо отправлено").first.wait_for(timeout=3_000)
    except Exception as e:
        print(f"  letter not attached: {e}")
        return "sent-no-letter"
    return "sent"


def cmd_send(args):
    conn = store.connect()
    print(f"title filter: {store.skip_excluded(conn)} vacancies skipped")
    manual_streak = 0
    with sync_playwright() as p:
        ctx = open_context(p)
        try:
            page = first_page(ctx)
            for v in store.by_status(conn, "drafted"):
                if store.count_today(conn, "sent") >= DAILY_LIMIT:
                    print(f"Daily limit {DAILY_LIMIT} reached.")
                    break
                # No manual review by decision of the user; only contact leaks are held back.
                if any(w in v["warnings"] for w in ("phone number", "e-mail", "wrong experience")):
                    print(f"hold (contacts or wrong experience in letter): {clean(v['title'])} ({v['id']})")
                    continue
                result = respond(page, v)
                print(f"{result}: {clean(v['title'])} | {clean(v['company'])} {v['url']}")
                if result == "already":
                    store.set_status(conn, v["id"], "skipped")
                elif result == "manual":
                    store.set_status(conn, v["id"], "manual")
                    manual_streak += 1
                    if manual_streak >= MAX_MANUAL:
                        raise RuntimeError(f"{MAX_MANUAL} vacancies in a row need manual response; "
                                           "run check-selectors")
                else:
                    store.set_status(conn, v["id"], "sent")
                    if result == "sent-no-letter":
                        print("  !! response sent WITHOUT the letter; attach it by hand")
                if result != "manual":
                    manual_streak = 0
                pause()
        finally:
            ctx.close()


def cmd_auto(args):
    args.limit = args.max
    cmd_collect(args)
    cmd_draft(args)
    cmd_send(args)


def main():
    ap = argparse.ArgumentParser(prog="bot.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login").set_defaults(fn=cmd_login)
    c = sub.add_parser("check-selectors")
    c.add_argument("url")
    c.set_defaults(fn=cmd_check_selectors)
    c = sub.add_parser("collect")
    c.add_argument("url", nargs="?", help="search URL; default: HH_SEARCH_URL from .env")
    c.add_argument("--pages", type=int, default=2)
    c.add_argument("--max", type=int, default=0, help="stop after N new vacancies (0 = no cap)")
    c.set_defaults(fn=cmd_collect)
    c = sub.add_parser("draft")
    c.add_argument("--limit", type=int, default=DAILY_LIMIT)
    c.set_defaults(fn=cmd_draft)
    sub.add_parser("review").set_defaults(fn=cmd_review)
    sub.add_parser("send").set_defaults(fn=cmd_send)
    c = sub.add_parser("auto")
    c.add_argument("url", nargs="?", help="search URL; default: HH_SEARCH_URL from .env")
    c.add_argument("--pages", type=int, default=1)
    c.add_argument("--max", type=int, default=DAILY_LIMIT, help="new vacancies to collect and draft")
    c.set_defaults(fn=cmd_auto)
    args = ap.parse_args()
    load_env()
    args.fn(args)


if __name__ == "__main__":
    main()
