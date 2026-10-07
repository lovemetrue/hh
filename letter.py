import json
import os
import random
import re
import ssl
import threading
import time
import urllib.error
import urllib.request

try:  # python.org builds on macOS ship without root certs; certifi fixes that
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = None

URL = "https://router.requesty.ai/v1/chat/completions"
MODEL = "google/gemma-4-31b-it"
RETRIES = 8
RETRY_CODES = (429, 500, 502, 503, 504)
MIN_INTERVAL = 1.5  # seconds between LLM requests across all threads
_throttle_lock = threading.Lock()
_last_call = [0.0]
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
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
LATIN = re.compile(r"[A-Za-z][A-Za-z0-9+#.-]{2,}")
TRAIL = '.,;:!?)"\'-'  # trailing punctuation and hyphens glued to a Latin token
CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def build_messages(facts, vacancy):
    user = (f"RESUME FACTS:\n{facts}\n\n"
            f"VACANCY:\n{vacancy['title']} at {vacancy['company']}\n"
            f"{vacancy['description'][:6000]}")
    # One user message: some models (Gemma) reject the system role.
    return [{"role": "user", "content": f"{SYSTEM}\n\n{user}"}]


def _throttle():
    with _throttle_lock:
        wait = _last_call[0] + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()


def call_llm(messages):
    key = os.environ.get("REQUESTY_API_KEY")
    if not key:
        raise RuntimeError("REQUESTY_API_KEY is not set")
    req = urllib.request.Request(
        URL, json.dumps({"model": MODEL, "messages": messages}).encode(),
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for attempt in range(RETRIES):
        _throttle()
        try:
            with urllib.request.urlopen(req, timeout=120, context=SSL_CTX) as r:
                content = json.load(r)["choices"][0]["message"]["content"]
            break
        except urllib.error.HTTPError as e:
            # rate limit or flaky gateway: wait as the server asks (Retry-After) or back off, capped
            if e.code not in RETRY_CODES or attempt == RETRIES - 1:
                raise
            delay = float(e.headers.get("Retry-After") or min(60, 5 * 2 ** attempt))
            time.sleep(delay + random.uniform(0, 2))
    if not content or not content.strip():
        raise RuntimeError("LLM returned empty content")
    return content.strip()


def check_letter(text, facts):
    problems = []
    if PHONE.search(text):
        problems.append("phone number")
    if EMAIL.search(text):
        problems.append("e-mail")
    if EMOJI.search(text):
        problems.append("emoji")
    if not 700 <= len(text) <= 1000:
        problems.append(f"length {len(text)}")
    # Latin words missing from the facts hint at invented tech; skipped for English letters.
    if len(CYRILLIC.findall(text)) > len(text) * 0.3:
        known = {w.rstrip(TRAIL).lower() for w in LATIN.findall(facts)}
        unknown = sorted({w.rstrip(TRAIL) for w in LATIN.findall(text)
                          if w.rstrip(TRAIL).lower() not in known})
        if unknown:
            problems.append("not in resume: " + ", ".join(unknown))
    return problems


def generate_letter(facts, vacancy, llm=call_llm):
    text = llm(build_messages(facts, vacancy))
    return text, check_letter(text, facts)
