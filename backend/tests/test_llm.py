import pytest

import app.llm as llm


class _FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_generate_script_unknown_provider(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "not-a-real-provider")
    with pytest.raises(ValueError):
        llm.generate_script("do x", "{}", [])


def test_deepseek_request_shape(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")

    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeResp(
            200,
            {"choices": [{"message": {"content": "def edit(doc, tools):\n    pass"}}]},
        )

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    script = llm.generate_script("bold it", '{"total_paragraphs": 1}', [("prev", "failed")])

    assert script == "def edit(doc, tools):\n    pass"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"

    body = captured["kwargs"]["json"]
    assert body["model"] == "deepseek-chat"
    assert body["temperature"] == 0
    assert body["messages"][0]["role"] == "system"
    user_msg = body["messages"][1]["content"]
    assert "bold it" in user_msg
    assert "prev" in user_msg
    assert "failed" in user_msg


def test_deepseek_missing_key(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        llm.generate_script("do x", "{}", [])


def test_deepseek_api_error(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    def fake_post(url, **kwargs):
        return _FakeResp(401, text="unauthorized")

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    with pytest.raises(RuntimeError):
        llm.generate_script("do x", "{}", [])


def test_parse_clarify_clear():
    assert llm._parse_clarify("CLEAR") is None
    assert llm._parse_clarify("Clear.") is None


def test_parse_clarify_question():
    assert llm._parse_clarify("Which paragraph should be bold?") == "Which paragraph should be bold?"


def test_ask_deepseek_clear(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "deepseek")
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: "CLEAR")
    assert llm.ask_clarification("bold headings", "{}", []) is None


def test_ask_deepseek_question(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "deepseek")
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: "Which headings?")
    assert llm.ask_clarification("bold headings", "{}", []) == "Which headings?"


def test_clarifications_included_in_prompt(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    captured = {}

    def fake_post(url, **kwargs):
        captured["messages"] = kwargs["json"]["messages"]
        return _FakeResp(
            200,
            {"choices": [{"message": {"content": "def edit(doc, tools):\n    pass"}}]},
        )

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    llm.generate_script("bold it", "{}", [], [("Which part?", "The title")])

    user_msg = captured["messages"][1]["content"]
    assert "Which part?" in user_msg
    assert "The title" in user_msg
