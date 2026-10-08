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


def test_title_filter():
    for bad in ("Стажер DevOps / SRE", "Junior DevOps", "Технический лидер", "Team Lead DevOps",
                "Системный администратор Linux", "Младший инженер инфраструктуры", "DevOps инженер (ученик)"):
        assert store.title_excluded(bad), bad
    for ok in ("DevOps-инженер", "DevOps / Системный администратор Linux", "SRE-инженер",
               "Старший DevOps-инженер", "Ведущий DevOps-инженер", "Platform Engineer", "Инженер Kubernetes"):
        assert not store.title_excluded(ok), ok


def test_skip_excluded_marks_queue():
    conn = store.connect(":memory:")
    store.add(conn, {**vac("1"), "title": "Стажер DevOps"})
    store.add(conn, {**vac("2"), "title": "DevOps-инженер"})
    assert store.skip_excluded(conn) == 1
    assert [r["id"] for r in store.by_status(conn, "skipped")] == ["1"]
    assert [r["id"] for r in store.by_status(conn, "new")] == ["2"]


def test_set_sent_records_note():
    conn = store.connect(":memory:")
    store.add(conn, vac("7"))
    store.set_sent(conn, "7", "hh")
    row = store.by_status(conn, "sent")[0]
    assert row["note"] == "hh"


def test_clean_removes_unsent_and_keeps_sent():
    conn = store.connect(":memory:")
    for i, st in enumerate(("new", "drafted", "manual", "skipped", "sent"), 1):
        store.add(conn, vac(str(i)))
        store.set_status(conn, str(i), st)
    assert store.clean(conn, ("new", "drafted")) == 2
    assert sorted(r["status"] for r in conn.execute("select status from vacancies")) == ["manual", "sent", "skipped"]
    assert store.clean(conn) == 2
    assert [r["status"] for r in conn.execute("select status from vacancies")] == ["sent"]


def test_clean_refuses_sent_and_unknown():
    conn = store.connect(":memory:")
    for bad in (("sent",), ("new", "sent"), ("bogus",), ()):
        try:
            store.clean(conn, bad)
        except ValueError:
            continue
        raise AssertionError(f"clean accepted {bad}")


def test_mark_resolves_manual_lists():
    conn = store.connect(":memory:")
    for i in "123":
        store.add(conn, vac(i))
    store.set_status(conn, "1", "manual")
    store.set_status(conn, "2", "manual")
    store.set_sent(conn, "3", "none")
    assert store.mark(conn, "1", "done") and store.by_status(conn, "sent")[0]["id"] in ("1", "3")
    assert conn.execute("select note from vacancies where id='1'").fetchone()["note"] == "manual"
    assert store.mark(conn, "2", "dismiss")
    assert store.by_status(conn, "skipped")[0]["id"] == "2"
    assert store.mark(conn, "3", "letter_done")
    assert conn.execute("select note from vacancies where id='3'").fetchone()["note"] == "manual-letter"
    # wrong state or unknown id is refused
    assert not store.mark(conn, "1", "done") and not store.mark(conn, "9", "done")
    assert not store.mark(conn, "3", "letter_done")


def test_company_filter_excludes_sber_family():
    for company in ("Сбер. IT", "SberTech", "Сбер. Кибербезопасность", "СберКорус", "SberCIB", "Сбербанк"):
        assert store.title_excluded("DevOps-инженер", company), company
    for company in ("Яндекс", "Альфа-Банк", "Tinkoff", ""):
        assert not store.title_excluded("DevOps-инженер", company), company


def test_sber_is_matched_in_company_title_and_description():
    assert store.title_excluded("DevOps", "ИЦ АЙ-ТЕКО", "Проект для Сбербанка, команда AI HUB")
    assert store.title_excluded("DevOps в Сбере", "Рога и копыта")
    assert store.title_excluded("DevOps", "Агентство", "заказчик: SberTech")
    assert store.title_excluded("DevOps", "Cбер. IT")      # a Latin C hiding in the name
    assert store.title_excluded("DevOps", "SBER")
    assert store.title_excluded("DevOps", "x", "работа в СБЕРБАНК")


def test_sber_filter_has_no_false_positives():
    assert not store.title_excluded("DevOps", "Яндекс", "накопим сбережения, сберечь время, Super Berry")
    assert not store.title_excluded("DevOps", "Альфа-Банк", "Kubernetes, GitLab CI")
    assert not store.title_excluded("DevOps", "Tinkoff", "Hyperberry, Passberry, ресурсы без сбоев")
