from __future__ import annotations

from divapply import llm


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
