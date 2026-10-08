import io
import json

import notify


def test_noop_without_token_or_chat(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notify.send("x") is False


def test_sends_to_the_chat_and_hides_token_on_failure(monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:SECRET")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    seen = {}

    class Opener:
        def open(self, req, timeout):
            seen["url"], seen["body"] = req.full_url, json.loads(req.data)
            return io.BytesIO(b'{"ok": true}')

    monkeypatch.setattr(notify.urllib.request, "build_opener", lambda *h: Opener())
    assert notify.send("hello") is True
    assert seen["url"].endswith("/bot123:SECRET/sendMessage")
    assert seen["body"]["chat_id"] == "42" and seen["body"]["text"] == "hello"

    class Boom:
        def open(self, req, timeout):
            raise OSError("https://api.telegram.org/bot123:SECRET/sendMessage unreachable")

    monkeypatch.setattr(notify.urllib.request, "build_opener", lambda *h: Boom())
    assert notify.send("hello") is False
    assert "SECRET" not in capsys.readouterr().out


def test_accepts_telegram_token_alias(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_TOKEN", "9:ALIAS")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    seen = {}

    class Opener:
        def open(self, req, timeout):
            seen["url"] = req.full_url
            return io.BytesIO(b'{"ok": true}')

    monkeypatch.setattr(notify.urllib.request, "build_opener", lambda *h: Opener())
    assert notify.send("x") is True and "/bot9:ALIAS/" in seen["url"]
