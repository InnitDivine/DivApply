from __future__ import annotations

import httpx

from divapply import llm


def test_openai_default_uses_current_cost_sensitive_model(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    _, model, _ = llm._detect_provider()

    assert model == "gpt-5.6-luna"


def test_gpt_5_6_preserves_low_cost_reasoning_baseline(monkeypatch) -> None:
    captured: dict = {}

    class Response:
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict:
            return {"choices": [{"message": {"content": "ok"}}]}

    client = llm.LLMClient("https://api.openai.com/v1", "gpt-5.6-luna", "test-key")

    def fake_post(*_args, **kwargs):
        captured.update(kwargs["json"])
        return Response()

    monkeypatch.setattr(client._client, "post", fake_post)

    assert client._chat_compat([], 0.0, 32, httpx.Timeout(1.0)) == "ok"
    assert captured["reasoning_effort"] == "none"


def test_stage_alias_resolves_openai_model(monkeypatch) -> None:
    llm._stage_instances.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_URL", raising=False)
    monkeypatch.setenv("DIVAPPLY_LLM_SCORER", "openai:gpt-test")

    client = llm.get_client_for_stage("score")

    assert client.base_url == "https://api.openai.com/v1"
    assert client.model == "gpt-test"
    llm._stage_instances.clear()
