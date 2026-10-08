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
