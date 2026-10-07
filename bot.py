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


def cmd_draft(args):
    facts = Path("resume_facts.md").read_text()
    conn = store.connect()
    for v in store.by_status(conn, "new")[: args.limit]:
        text, problems = letter.generate_letter(facts, dict(v))
        store.set_draft(conn, v["id"], text, "; ".join(problems))
        print(f"{v['id']} {v['title']} | warnings: {problems or 'none'}")


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
