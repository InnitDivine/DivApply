"""Typed timeout and retry policy for synchronous LLM requests."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os

import httpx


def _float_env(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name)
    try:
        value = default if raw is None or not raw.strip() else float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number between {minimum} and {maximum}") from exc
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise ValueError(f"{name} must be a finite number between {minimum} and {maximum}")
    return value


def _int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    try:
        value = default if raw is None or not raw.strip() else int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class LLMRequestPolicy:
    """Per-operation timeouts plus a hard caller deadline and bounded retries."""

    connect_timeout: float = 10.0
    read_timeout: float = 300.0
    write_timeout: float = 30.0
    pool_timeout: float = 10.0
    max_attempts: int = 3
    total_timeout: float = 600.0
    retry_base_delay: float = 5.0
    retry_max_delay: float = 60.0

    def __post_init__(self) -> None:
        numeric = {
            "connect_timeout": (self.connect_timeout, 0.01, 3600.0),
            "read_timeout": (self.read_timeout, 0.01, 3600.0),
            "write_timeout": (self.write_timeout, 0.01, 3600.0),
            "pool_timeout": (self.pool_timeout, 0.01, 3600.0),
            "total_timeout": (self.total_timeout, 0.01, 3600.0),
            "retry_base_delay": (self.retry_base_delay, 0.0, 60.0),
            "retry_max_delay": (self.retry_max_delay, 0.0, 60.0),
        }
        for name, (value, minimum, maximum) in numeric.items():
            if not math.isfinite(value) or value < minimum or value > maximum:
                raise ValueError(f"{name} must be finite and between {minimum} and {maximum}")
        if self.max_attempts < 1 or self.max_attempts > 3:
            raise ValueError("max_attempts must be between 1 and 3")
        if self.retry_base_delay > self.retry_max_delay:
            raise ValueError("retry_base_delay must not exceed retry_max_delay")

    @classmethod
    def from_env(cls) -> "LLMRequestPolicy":
        """Load validated policy values from DivApply environment variables."""
        return cls(
            connect_timeout=_float_env(
                "DIVAPPLY_LLM_CONNECT_TIMEOUT", 10.0, minimum=0.01, maximum=3600.0
            ),
            read_timeout=_float_env(
                "DIVAPPLY_LLM_READ_TIMEOUT", 300.0, minimum=0.01, maximum=3600.0
            ),
            write_timeout=_float_env(
                "DIVAPPLY_LLM_WRITE_TIMEOUT", 30.0, minimum=0.01, maximum=3600.0
            ),
            pool_timeout=_float_env(
                "DIVAPPLY_LLM_POOL_TIMEOUT", 10.0, minimum=0.01, maximum=3600.0
            ),
            max_attempts=_int_env(
                "DIVAPPLY_LLM_MAX_ATTEMPTS", 3, minimum=1, maximum=3
            ),
            total_timeout=_float_env(
                "DIVAPPLY_LLM_TOTAL_TIMEOUT", 600.0, minimum=0.01, maximum=3600.0
            ),
            retry_base_delay=_float_env(
                "DIVAPPLY_LLM_RETRY_BASE_DELAY", 5.0, minimum=0.0, maximum=60.0
            ),
            retry_max_delay=_float_env(
                "DIVAPPLY_LLM_RETRY_MAX_DELAY", 60.0, minimum=0.0, maximum=60.0
            ),
        )

    def httpx_timeout(self, *, remaining: float) -> httpx.Timeout:
        """Clamp each HTTPX operation timeout to the remaining caller budget."""
        limit = max(0.001, remaining)
        return httpx.Timeout(
            connect=min(self.connect_timeout, limit),
            read=min(self.read_timeout, limit),
            write=min(self.write_timeout, limit),
            pool=min(self.pool_timeout, limit),
        )

    def retry_delay(
        self,
        attempt_index: int,
        *,
        retry_after: str | None,
        remaining: float,
    ) -> float:
        """Return a finite server/fallback delay below both policy and deadline."""
        fallback = min(self.retry_base_delay * (2 ** max(0, attempt_index)), self.retry_max_delay)
        candidate = fallback
        if retry_after:
            try:
                parsed = float(retry_after)
            except (TypeError, ValueError):
                parsed = fallback
            if math.isfinite(parsed) and parsed >= 0:
                candidate = parsed
        deadline_limit = max(0.0, remaining - 0.001)
        return min(candidate, self.retry_max_delay, deadline_limit)
