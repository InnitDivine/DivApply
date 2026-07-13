from __future__ import annotations

import logging
import time

import httpx
import pytest

from divapply.llm import LLMClient, LLMRequestBudgetExceeded
from divapply.llm_policy import LLMRequestPolicy


_POLICY_ENV = (
    "DIVAPPLY_LLM_CONNECT_TIMEOUT",
    "DIVAPPLY_LLM_READ_TIMEOUT",
    "DIVAPPLY_LLM_WRITE_TIMEOUT",
    "DIVAPPLY_LLM_POOL_TIMEOUT",
    "DIVAPPLY_LLM_MAX_ATTEMPTS",
    "DIVAPPLY_LLM_TOTAL_TIMEOUT",
    "DIVAPPLY_LLM_RETRY_BASE_DELAY",
    "DIVAPPLY_LLM_RETRY_MAX_DELAY",
)


def _clear_policy_env(monkeypatch) -> None:
    for name in _POLICY_ENV:
        monkeypatch.delenv(name, raising=False)


def test_policy_from_env_has_bounded_defaults_and_validates_overrides(monkeypatch) -> None:
    _clear_policy_env(monkeypatch)
    default = LLMRequestPolicy.from_env()

    assert default.max_attempts == 3
    assert default.total_timeout == 600.0
    assert default.retry_max_delay == 60.0

    monkeypatch.setenv("DIVAPPLY_LLM_CONNECT_TIMEOUT", "4.5")
    monkeypatch.setenv("DIVAPPLY_LLM_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("DIVAPPLY_LLM_TOTAL_TIMEOUT", "120")
    overridden = LLMRequestPolicy.from_env()

    assert overridden.connect_timeout == 4.5
    assert overridden.max_attempts == 2
    assert overridden.total_timeout == 120.0

    monkeypatch.setenv("DIVAPPLY_LLM_TOTAL_TIMEOUT", "nan")
    with pytest.raises(ValueError, match="DIVAPPLY_LLM_TOTAL_TIMEOUT"):
        LLMRequestPolicy.from_env()
    monkeypatch.setenv("DIVAPPLY_LLM_TOTAL_TIMEOUT", "120")
    monkeypatch.setenv("DIVAPPLY_LLM_MAX_ATTEMPTS", "4")
    with pytest.raises(ValueError, match="DIVAPPLY_LLM_MAX_ATTEMPTS"):
        LLMRequestPolicy.from_env()


def test_policy_clamps_operation_timeouts_and_untrusted_retry_after() -> None:
    policy = LLMRequestPolicy(
        connect_timeout=10,
        read_timeout=300,
        write_timeout=30,
        pool_timeout=10,
        max_attempts=3,
        total_timeout=600,
        retry_base_delay=5,
        retry_max_delay=60,
    )

    timeout = policy.httpx_timeout(remaining=2.5)
    assert timeout.connect == 2.5
    assert timeout.read == 2.5
    assert timeout.write == 2.5
    assert timeout.pool == 2.5
    assert policy.retry_delay(0, retry_after="999999", remaining=10) < 10
    assert policy.retry_delay(1, retry_after="nan", remaining=100) == 10
    assert policy.retry_delay(1, retry_after="-2", remaining=100) == 10
    assert policy.retry_delay(1, retry_after="inf", remaining=100) == 10


def test_chat_retries_at_most_three_times_with_fake_clock(monkeypatch, caplog) -> None:
    now = [0.0]
    sleeps: list[float] = []
    policy = LLMRequestPolicy(
        connect_timeout=1,
        read_timeout=1,
        write_timeout=1,
        pool_timeout=1,
        max_attempts=3,
        total_timeout=30,
        retry_base_delay=1,
        retry_max_delay=5,
    )

    def sleep(delay: float) -> None:
        sleeps.append(delay)
        now[0] += delay

    client = LLMClient(
        "https://api.example.test/v1",
        "test-model",
        "secret",
        policy=policy,
        clock=lambda: now[0],
        sleeper=sleep,
    )
    calls = 0

    def fail(*_args, **_kwargs) -> str:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(client, "_chat_compat", fail)

    with caplog.at_level(logging.WARNING), pytest.raises(httpx.ReadTimeout):
        client.chat([{"role": "user", "content": "hello"}])

    assert calls == 3
    assert sleeps == [1, 2]
    assert "attempt 2/3" in caplog.text
    client.close()


def test_chat_clamps_server_retry_after_to_policy(monkeypatch) -> None:
    now = [0.0]
    sleeps: list[float] = []
    policy = LLMRequestPolicy(
        connect_timeout=1,
        read_timeout=1,
        write_timeout=1,
        pool_timeout=1,
        max_attempts=2,
        total_timeout=100,
        retry_base_delay=1,
        retry_max_delay=7,
    )
    client = LLMClient(
        "https://api.example.test/v1",
        "test-model",
        "secret",
        policy=policy,
        clock=lambda: now[0],
        sleeper=lambda delay: (sleeps.append(delay), now.__setitem__(0, now[0] + delay)),
    )
    request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
    response = httpx.Response(429, request=request, headers={"Retry-After": "9999"})

    def limited(*_args, **_kwargs) -> str:
        raise httpx.HTTPStatusError("limited", request=request, response=response)

    monkeypatch.setattr(client, "_chat_compat", limited)

    with pytest.raises(httpx.HTTPStatusError):
        client.chat([{"role": "user", "content": "hello"}])

    assert sleeps == [7]
    client.close()


def test_hard_budget_returns_while_request_worker_is_stalled(monkeypatch) -> None:
    policy = LLMRequestPolicy(
        connect_timeout=0.05,
        read_timeout=0.05,
        write_timeout=0.05,
        pool_timeout=0.05,
        max_attempts=1,
        total_timeout=0.05,
        retry_base_delay=0,
        retry_max_delay=0,
    )
    client = LLMClient(
        "https://api.example.test/v1",
        "test-model",
        "secret",
        policy=policy,
    )
    monkeypatch.setattr(client, "_chat_compat", lambda *_args, **_kwargs: time.sleep(1) or "late")

    started = time.monotonic()
    with pytest.raises(LLMRequestBudgetExceeded):
        client.chat([{"role": "user", "content": "hello"}])
    elapsed = time.monotonic() - started

    assert elapsed < 0.5
    client.close()
