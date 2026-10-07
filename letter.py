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
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
LATIN = re.compile(r"[A-Za-z][A-Za-z0-9+#.-]{2,}")
CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def build_messages(facts, vacancy):
    user = (f"RESUME FACTS:\n{facts}\n\n"
            f"VACANCY:\n{vacancy['title']} at {vacancy['company']}\n"
            f"{vacancy['description'][:6000]}")
    # One user message: some models (Gemma) reject the system role.
    return [{"role": "user", "content": f"{SYSTEM}\n\n{user}"}]


def call_llm(messages):
    key = os.environ.get("REQUESTY_API_KEY")
    if not key:
        raise RuntimeError("REQUESTY_API_KEY is not set")
    req = urllib.request.Request(
        URL, json.dumps({"model": MODEL, "messages": messages}).encode(),
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        content = json.load(r)["choices"][0]["message"]["content"]
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
    if CYRILLIC.search(text):
        known = {w.rstrip('.,;:!?)"\'').lower() for w in LATIN.findall(facts)}
        unknown = sorted({w.rstrip('.,;:!?)"\'') for w in LATIN.findall(text)
                          if w.rstrip('.,;:!?)"\'').lower() not in known})
        if unknown:
            problems.append("not in resume: " + ", ".join(unknown))
    return problems


def generate_letter(facts, vacancy, llm=call_llm):
    text = llm(build_messages(facts, vacancy))
    return text, check_letter(text, facts)
