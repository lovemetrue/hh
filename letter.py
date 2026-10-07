import json
import os
import random
import re
import ssl
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
RETRIES = 6
RETRY_CODES = (429, 500, 502, 503, 504)
MIN_INTERVAL, MAX_INTERVAL = 4.0, 120.0
# The free model has a hard request limit and sends no Retry-After: one request at a time,
# with a start-to-start interval that doubles on 429 and shrinks slowly on success.
_pace = {"interval": 8.0, "last": 0.0}


class RateLimited(RuntimeError):
    """429 survived every retry: the free-model quota is exhausted for now."""
SYSTEM = (
    "You write short cover letters for a job seeker.\n"
    "Use ONLY the facts in RESUME FACTS. Never invent technologies, employers, "
    "titles, numbers or years.\n"
    "Write in Russian, unless the vacancy text is in English; then write in English.\n"
    "700-1000 characters, plain text, no emoji, no bullet lists, no placeholders, "
    "no contact details.\n"
    "Address the reader without a name unless the vacancy gives one.\n"
    "Pick only the facts relevant to this vacancy; do not repeat the whole resume.\n"
    "Experience: if you state years, say exactly '2,2 года DevOps-опыта' "
    "(optionally 'плюс около 2 лет смежного опыта'); NEVER write 4 years of DevOps experience.\n"
    "Do not write about salary, office work, relocation, start date or availability; "
    "do not call the job a trainee/intern position.\n"
    "The candidate's role is DevOps: never write the word DevSecOps (security tools such as Trivy "
    "or Checkov may be named as part of DevOps work)."
)

PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
LATIN = re.compile(r"[A-Za-z][A-Za-z0-9+#.-]{2,}")
TRAIL = '.,;:!?)"\'-'  # trailing punctuation and hyphens glued to a Latin token
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
# the resume says 2,2 years of DevOps; "4 years" is the old, wrong claim (total IT tenure is not DevOps tenure)
WRONG_EXP = re.compile(r"(?<![\d,.])(?:4|четыр\w+)\+?\s+(?:лет|год\w*)|\b(?:4|four)\+?\s+years", re.I)


def build_messages(facts, vacancy):
    user = (f"RESUME FACTS:\n{facts}\n\n"
            f"VACANCY:\n{vacancy['title']} at {vacancy['company']}\n"
            f"{vacancy['description'][:6000]}")
    # One user message: some models (Gemma) reject the system role.
    return [{"role": "user", "content": f"{SYSTEM}\n\n{user}"}]


def _throttle():
    wait = _pace["last"] + _pace["interval"] - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _pace["last"] = time.monotonic()


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
            _pace["interval"] = max(MIN_INTERVAL, _pace["interval"] * 0.9)
            break
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_CODES:
                raise
            if e.code == 429:
                _pace["interval"] = min(MAX_INTERVAL, _pace["interval"] * 2)
            if attempt == RETRIES - 1:
                if e.code == 429:
                    raise RateLimited("free-model rate limit persists") from e
                raise
            time.sleep(float(e.headers.get("Retry-After") or min(60, 15 * 2 ** attempt)) + random.uniform(0, 2))
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
    if "devsecops" in text.lower():
        problems.append("mentions DevSecOps")
    if WRONG_EXP.search(text):
        problems.append("wrong experience (4 years)")
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
