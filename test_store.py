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
