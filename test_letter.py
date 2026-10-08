from pathlib import Path

import io
import json

import pytest

import letter

FACTS = "Kubernetes Docker Terraform Ansible GitLab DevSecOps"
GOOD = "Здравствуйте! " + "Работаю с Kubernetes и Docker, автоматизирую инфраструктуру на Terraform и Ansible. " * 9
VAC = {"title": "DevOps", "company": "Acme", "description": "Нужен Kubernetes"}


def test_clean_letter_has_no_problems():
    assert letter.check_letter(GOOD, FACTS) == []


def test_phone_email_and_unknown_tech_are_flagged():
    assert "phone number" in letter.check_letter(GOOD + " +7 900 000 0000", FACTS)
    assert "e-mail" in letter.check_letter(GOOD + " me@example.com", FACTS)
    problems = letter.check_letter(GOOD + " Знаю Hadoop.", FACTS)
    assert any("Hadoop" in p for p in problems)


def test_emoji_is_flagged():
    problems = letter.check_letter(GOOD + " \U0001F525", FACTS)
    assert "emoji" in problems


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


def test_substring_not_confused_with_word():
    # "Doc" is a substring of "Docker" but should be flagged as unknown
    problems = letter.check_letter("Здравствуйте! Работаю с Doc технологиями " * 20, FACTS)
    assert any("Doc" in p for p in problems)


def test_resume_facts_file_has_no_contacts():
    p = Path(__file__).parent / "resume_facts.md"
    facts = p.read_text()
    assert not letter.PHONE.search(facts) and not letter.EMAIL.search(facts)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("REQUESTY_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="REQUESTY_API_KEY is not set"):
        letter.call_llm([])


def test_null_content_raises(monkeypatch):
    monkeypatch.setenv("REQUESTY_API_KEY", "k")
    body = b'{"choices":[{"message":{"content":null}}]}'
    monkeypatch.setattr(letter.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(body))
    with pytest.raises(RuntimeError, match="empty content"):
        letter.call_llm([])


def test_call_llm_retries_on_429(monkeypatch):
    import io
    import urllib.error
    monkeypatch.setenv("REQUESTY_API_KEY", "k")
    monkeypatch.setattr(letter.time, "sleep", lambda s: None)
    body = json.dumps({"choices": [{"message": {"content": " ok "}}]}).encode()
    calls = []

    def fake(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError("u", 429, "Too Many", {"Retry-After": "1"}, None)
        return io.BytesIO(body)

    monkeypatch.setattr(letter.urllib.request, "urlopen", fake)
    assert letter.call_llm([{"role": "user", "content": "x"}]) == "ok"
    assert len(calls) == 2


def test_call_llm_retries_on_502(monkeypatch):
    import urllib.error
    monkeypatch.setenv("REQUESTY_API_KEY", "k")
    monkeypatch.setattr(letter.time, "sleep", lambda s: None)
    body = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
    calls = []

    def fake(*a, **k):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError("u", 502, "Bad Gateway", {}, None)
        return io.BytesIO(body)

    monkeypatch.setattr(letter.urllib.request, "urlopen", fake)
    assert letter.call_llm([{"role": "user", "content": "x"}]) == "ok"
    assert len(calls) == 3


def test_english_letter_with_stray_cyrillic_skips_unknown_word_check():
    text = ("Hello, I run Kubernetes clusters and Docker builds at scale. " * 12) + "Спасибо."
    assert letter.check_letter(text, FACTS) == []


def test_wrong_experience_claim_is_flagged():
    for bad in (" Опыт более 4 лет.", " Мой опыт 4 года и 1 месяц.", " Имею четыре года опыта.", " Over 4 years of DevOps."):
        assert any("wrong experience" in p for p in letter.check_letter(GOOD + bad, FACTS)), bad
    for ok in (" Опыт 2,2 года.", " Работаю 24 года назад не начинал.", " Около 2 лет смежного опыта."):
        assert not any("wrong experience" in p for p in letter.check_letter(GOOD + ok, FACTS)), ok


def test_devsecops_word_is_flagged():
    assert "mentions DevSecOps" in letter.check_letter(GOOD + " Работаю как DevSecOps.", FACTS)


def test_persistent_429_raises_rate_limited_and_slows_down(monkeypatch):
    import urllib.error
    monkeypatch.setenv("REQUESTY_API_KEY", "k")
    monkeypatch.setattr(letter.time, "sleep", lambda s: None)
    letter._pace.update(interval=8.0, last=0.0)

    def always_429(*a, **k):
        raise urllib.error.HTTPError("u", 429, "Too Many", {}, None)

    monkeypatch.setattr(letter.urllib.request, "urlopen", always_429)
    with pytest.raises(letter.RateLimited):
        letter.call_llm([{"role": "user", "content": "x"}])
    assert letter._pace["interval"] == letter.MAX_INTERVAL


def test_hh_text_problems():
    facts = FACTS + " ускорил деплой на 30%"
    assert letter.hh_text_problems("Ускорил деплой на 30%. Работаю с Kubernetes.", facts) == []
    assert any("100%" in p for p in letter.hh_text_problems("Покрытие выросло до 100%.", facts))
    assert "DevSecOps" in letter.hh_text_problems("Внедрил DevSecOps-контур.", facts)
    assert "4 years" in letter.hh_text_problems("Опыт более 4 лет.", facts)


def test_sanitize_hh_text_drops_bad_sentences():
    facts = FACTS + " ускорил деплой на 30%"
    raw = ("Здравствуйте! Ускорил деплой на 30%. Внедрил DevSecOps-контур. "
           "Покрытие выросло до 100%. Работаю с Kubernetes.")
    out = letter.sanitize_hh_text(raw, facts)
    assert "DevSecOps" not in out and "100%" not in out
    assert "30%" in out and "Kubernetes" in out
