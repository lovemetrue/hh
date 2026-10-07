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
