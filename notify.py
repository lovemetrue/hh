"""Telegram alert for events that need a human (captcha). A no-op until the token and chat id are set."""
import json
import os
import urllib.parse
import urllib.request

import letter  # reuses its certifi SSL context


def send(text):
    """Send a message to the owner. Returns True on success; never raises (an alert must not stop a run)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    base = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")
    req = urllib.request.Request(
        f"{base}/bot{token}/sendMessage",
        json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode(),
        {"Content-Type": "application/json"})
    handlers = [urllib.request.HTTPSHandler(context=letter.SSL_CTX)]
    proxy = os.environ.get("TELEGRAM_PROXY")  # e.g. a relay when Telegram is blocked on the network
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"https": proxy, "http": proxy}))
    try:
        with urllib.request.build_opener(*handlers).open(req, timeout=15) as r:
            return json.load(r).get("ok", False)
    except Exception as e:
        print(f"telegram alert failed: {type(e).__name__}")  # never print the URL: it contains the token
        return False
