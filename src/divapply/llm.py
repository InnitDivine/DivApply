"""
Unified LLM client for DivApply.

Auto-detects provider from environment:
  GEMINI_API_KEY  -> Google Gemini (default: gemini-2.0-flash)
  OPENAI_API_KEY  -> OpenAI (default: gpt-4o-mini)
  LLM_URL         -> Local llama.cpp / Ollama compatible endpoint

LLM_MODEL env var overrides the model name for any provider.
"""

import logging
import os
import queue
import re
import threading
import time
from collections.abc import Callable

import httpx

from divapply.llm_policy import LLMRequestPolicy

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def _detect_provider(alias: str | None = None) -> tuple[str, str, str]:
    """Return (base_url, model, api_key) based on environment variables.

    Reads env at call time (not module import time) so that load_env() called
    in _bootstrap() is always visible here.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    local_url = os.environ.get("LLM_URL", "")
    model_override = os.environ.get("LLM_MODEL", "")

    if alias:
        provider, _, model = alias.partition(":")
        provider = provider.strip().casefold()
        model = model.strip()
        if not model:
            model = provider
            provider = ""
        if provider in ("openai", "oa"):
            if not openai_key:
                raise RuntimeError("DIVAPPLY_LLM alias requested OpenAI but OPENAI_API_KEY is missing.")
            return ("https://api.openai.com/v1", model or model_override or "gpt-4o-mini", openai_key)
        if provider in ("gemini", "google"):
            if not gemini_key:
                raise RuntimeError("DIVAPPLY_LLM alias requested Gemini but GEMINI_API_KEY is missing.")
            return ("https://generativelanguage.googleapis.com/v1beta/openai", model or model_override or "gemini-2.0-flash", gemini_key)
        if provider in ("local", "ollama"):
            base = local_url or os.environ.get("OLLAMA_URL", "http://localhost:11434/v1")
            return (base.rstrip("/"), model or model_override or "local-model", os.environ.get("LLM_API_KEY", ""))
        if provider:
            # Unknown provider labels are treated as model aliases on the default provider.
            model_override = alias

    if gemini_key and not local_url:
        return (
            "https://generativelanguage.googleapis.com/v1beta/openai",
            model_override or "gemini-2.0-flash",
            gemini_key,
        )

    if openai_key and not local_url:
        return (
            "https://api.openai.com/v1",
            model_override or "gpt-4o-mini",
            openai_key,
        )

    if local_url:
        return (
            local_url.rstrip("/"),
            model_override or "local-model",
            os.environ.get("LLM_API_KEY", ""),
        )

    raise RuntimeError(
        "No LLM provider configured. "
        "Set GEMINI_API_KEY, OPENAI_API_KEY, or LLM_URL in your environment."
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


_GEMINI_COMPAT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
_GEMINI_NATIVE_BASE = "https://generativelanguage.googleapis.com/v1beta"


class LLMRequestBudgetExceeded(TimeoutError):
    """Raised when an LLM call exceeds its configured total wall-clock budget."""


class LLMClient:
    """Thin LLM client supporting OpenAI-compatible and native Gemini endpoints.

    For Gemini keys, starts on the OpenAI-compat layer. On a 403 (which
    happens with preview/experimental models not exposed via compat), it
    automatically switches to the native generateContent API and stays there
    for the lifetime of the process.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        *,
        policy: LLMRequestPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self.policy = policy or LLMRequestPolicy.from_env()
        self._clock = clock
        self._sleeper = sleeper
        self._client = self._new_http_client()
        # True once we've confirmed the native Gemini API works for this model
        self._use_native_gemini: bool = False
        self._is_gemini: bool = base_url.startswith(_GEMINI_COMPAT_BASE)

    def _new_http_client(self) -> httpx.Client:
        return httpx.Client(timeout=self.policy.httpx_timeout(remaining=self.policy.total_timeout))

    def _reset_http_client(self) -> None:
        try:
            self._client.close()
        finally:
            self._client = self._new_http_client()

    def _run_with_deadline(self, call: Callable[[], str], *, remaining: float) -> str:
        """Run one blocking request behind a hard caller deadline."""
        result_queue: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

        def invoke() -> None:
            try:
                result: tuple[bool, object] = (True, call())
            except BaseException as exc:
                result = (False, exc)
            try:
                result_queue.put_nowait(result)
            except queue.Full:
                pass

        worker = threading.Thread(target=invoke, name="divapply-llm-request", daemon=True)
        worker.start()
        try:
            ok, payload = result_queue.get(timeout=max(0.001, remaining))
        except queue.Empty as exc:
            self._reset_http_client()
            raise LLMRequestBudgetExceeded(
                f"LLM request exceeded total budget of {self.policy.total_timeout:g}s"
            ) from exc
        if not ok:
            if isinstance(payload, BaseException):
                raise payload
            raise RuntimeError("LLM request worker failed without an exception")
        if not isinstance(payload, str):
            raise TypeError("LLM response must be text")
        return payload

    # -- Native Gemini API --------------------------------------------------

    def _chat_native_gemini(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        request_timeout: httpx.Timeout,
    ) -> str:
        """Call the native Gemini generateContent API.

        Used automatically when the OpenAI-compat endpoint returns 403,
        which happens for preview/experimental models not exposed via compat.

        Converts OpenAI-style messages to Gemini's contents/systemInstruction
        format transparently.
        """
        contents: list[dict] = []
        system_parts: list[dict] = []

        for msg in messages:
            role = msg["role"]
            text = msg.get("content", "")
            if role == "system":
                system_parts.append({"text": text})
            elif role == "user":
                contents.append({"role": "user", "parts": [{"text": text}]})
            elif role == "assistant":
                # Gemini uses "model" instead of "assistant"
                contents.append({"role": "model", "parts": [{"text": text}]})

        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}

        url = f"{_GEMINI_NATIVE_BASE}/models/{self.model}:generateContent"
        resp = self._client.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            timeout=request_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    # -- OpenAI-compat API --------------------------------------------------

    def _chat_compat(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        request_timeout: httpx.Timeout,
    ) -> str:
        """Call the OpenAI-compatible endpoint."""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        # GPT-5.x and o-series models use max_completion_tokens; all others use max_tokens
        _new_token_param = (
            self.model.startswith("gpt-5")
            or self.model.startswith("o1")
            or self.model.startswith("o3")
            or self.model.startswith("o4")
        )
        if _new_token_param:
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["max_tokens"] = max_tokens
        # Ollama 0.9+ supports think:false to disable qwen3 chain-of-thought
        if "qwen" in self.model.lower():
            payload["think"] = False

        resp = self._client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=request_timeout,
        )

        # 403 on Gemini compat = model not available on compat layer.
        # Raise a specific sentinel so chat() can switch to native API.
        if resp.status_code == 403 and self._is_gemini:
            raise _GeminiCompatForbidden(resp)

        return self._handle_compat_response(resp)

    @staticmethod
    def _handle_compat_response(resp: httpx.Response) -> str:
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    # -- public API ---------------------------------------------------------

    def _remaining_budget(self, deadline: float) -> float:
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise LLMRequestBudgetExceeded(
                f"LLM request exceeded total budget of {self.policy.total_timeout:g}s"
            )
        return remaining

    @staticmethod
    def _clean_response(raw: str) -> str:
        if "<think>" in raw:
            return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        return raw

    def _log_success(self, *, started: float, attempts: int, retries: int) -> None:
        duration_ms = max(0, round((self._clock() - started) * 1000))
        log.info(
            "event=llm_request_complete model=%s attempts=%d retries=%d duration_ms=%d",
            self.model,
            attempts,
            retries,
            duration_ms,
        )

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        """Send a chat completion request and return the assistant message text."""
        # Qwen3 optimization: prepend /no_think to skip chain-of-thought
        # reasoning, saving tokens on structured extraction tasks.
        # NOTE: find the first *user* message — there may be a system message at [0].
        if "qwen" in self.model.lower() and messages:
            for _i, _msg in enumerate(messages):
                if _msg.get("role") == "user" and not _msg["content"].startswith("/no_think"):
                    messages = (
                        messages[:_i]
                        + [{"role": _msg["role"], "content": f"/no_think\n{_msg['content']}"}]
                        + messages[_i + 1:]
                    )
                    break

        started = self._clock()
        deadline = started + self.policy.total_timeout
        retries = 0

        for attempt in range(self.policy.max_attempts):
            remaining = self._remaining_budget(deadline)
            request_timeout = self.policy.httpx_timeout(remaining=remaining)
            try:
                # Route to native Gemini if we've already confirmed it's needed
                if self._use_native_gemini:
                    raw = self._run_with_deadline(
                        lambda: self._chat_native_gemini(
                            messages,
                            temperature,
                            max_tokens,
                            request_timeout,
                        ),
                        remaining=remaining,
                    )
                else:
                    raw = self._run_with_deadline(
                        lambda: self._chat_compat(
                            messages,
                            temperature,
                            max_tokens,
                            request_timeout,
                        ),
                        remaining=remaining,
                    )

                self._log_success(started=started, attempts=attempt + 1, retries=retries)
                return self._clean_response(raw)

            except _GeminiCompatForbidden:
                # Model not available on OpenAI-compat layer — switch to native.
                log.warning(
                    "Gemini compat endpoint returned 403 for model '%s'. "
                    "Switching to native generateContent API. "
                    "(Preview/experimental models are often compat-only on native.)",
                    self.model,
                )
                self._use_native_gemini = True
                # Retry immediately with native — don't count as a rate-limit wait
                try:
                    remaining = self._remaining_budget(deadline)
                    request_timeout = self.policy.httpx_timeout(remaining=remaining)
                    raw = self._run_with_deadline(
                        lambda: self._chat_native_gemini(
                            messages,
                            temperature,
                            max_tokens,
                            request_timeout,
                        ),
                        remaining=remaining,
                    )
                    self._log_success(started=started, attempts=attempt + 1, retries=retries)
                    return self._clean_response(raw)
                except httpx.HTTPStatusError as native_exc:
                    raise RuntimeError(
                        f"Both Gemini endpoints failed. Compat: 403 Forbidden. "
                        f"Native: {native_exc.response.status_code} — "
                        f"{native_exc.response.text[:200]}"
                    ) from native_exc

            except httpx.HTTPStatusError as exc:
                resp = exc.response
                if resp.status_code in (429, 503) and attempt < self.policy.max_attempts - 1:
                    retry_after = (
                        resp.headers.get("Retry-After")
                        or resp.headers.get("X-RateLimit-Reset-Requests")
                    )
                    remaining = self._remaining_budget(deadline)
                    wait = self.policy.retry_delay(
                        attempt,
                        retry_after=retry_after,
                        remaining=remaining,
                    )

                    if self._is_gemini:
                        tip = "Gemini free tier is low RPM. Consider a paid account or local model."
                    elif "api.openai.com" in self.base_url:
                        tip = "OpenAI returned a temporary limit/overload response. Retrying may succeed."
                    else:
                        tip = "Provider returned a temporary limit/overload response. Retrying may succeed."

                    log.warning(
                        "LLM rate limited (HTTP %s). Waiting %.3gs before attempt %d/%d. %s",
                        resp.status_code,
                        wait,
                        attempt + 2,
                        self.policy.max_attempts,
                        tip,
                    )
                    self._sleeper(wait)
                    retries += 1
                    continue
                raise

            except httpx.TransportError as exc:
                if attempt < self.policy.max_attempts - 1:
                    remaining = self._remaining_budget(deadline)
                    wait = self.policy.retry_delay(
                        attempt,
                        retry_after=None,
                        remaining=remaining,
                    )
                    log.warning(
                        "LLM transport error (%s). Waiting %.3gs before attempt %d/%d",
                        type(exc).__name__,
                        wait,
                        attempt + 2,
                        self.policy.max_attempts,
                    )
                    self._sleeper(wait)
                    retries += 1
                    continue
                raise

        raise RuntimeError("LLM request failed after all retries")

    def ask(self, prompt: str, **kwargs) -> str:
        """Convenience: single user prompt -> assistant response."""
        return self.chat([{"role": "user", "content": prompt}], **kwargs)

    def close(self) -> None:
        self._client.close()

    def __del__(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass


class _GeminiCompatForbidden(Exception):
    """Sentinel: Gemini OpenAI-compat returned 403. Switch to native API."""
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        super().__init__(f"Gemini compat 403: {response.text[:200]}")


# ---------------------------------------------------------------------------
# Singleton + per-stage clients
# ---------------------------------------------------------------------------

_instance: LLMClient | None = None
_stage_instances: dict[str, LLMClient] = {}

# Stage env-var overrides: LLM_MODEL_SCORE, LLM_MODEL_TAILOR, LLM_MODEL_COVER
_STAGE_MODEL_VARS = {
    "score": "LLM_MODEL_SCORE",
    "tailor": "LLM_MODEL_TAILOR",
    "judge": "LLM_MODEL_JUDGE",
    "cover": "LLM_MODEL_COVER",
    "apply": "LLM_MODEL_APPLY",
}

_STAGE_ALIAS_VARS = {
    "score": "DIVAPPLY_LLM_SCORER",
    "tailor": "DIVAPPLY_LLM_TAILOR",
    "judge": "DIVAPPLY_LLM_JUDGE",
    "cover": "DIVAPPLY_LLM_COVER",
    "apply": "DIVAPPLY_LLM_APPLY",
}


def get_client() -> LLMClient:
    """Return (or create) the module-level LLMClient singleton."""
    global _instance
    if _instance is None:
        base_url, model, api_key = _detect_provider()
        log.info("LLM provider: %s  model: %s", base_url, model)
        _instance = LLMClient(base_url, model, api_key)
    return _instance


def get_client_for_stage(stage: str) -> LLMClient:
    """Return an LLMClient for a specific pipeline stage.

    Checks for a stage-specific model env var first (e.g. LLM_MODEL_TAILOR),
    falls back to the default LLM_MODEL / provider detection.

    This lets you run scoring on qwen2.5:7b and tailoring on a larger model
    simply by setting LLM_MODEL_TAILOR=qwen2.5:14b without touching LLM_MODEL.
    """
    global _stage_instances

    # Re-read env each call so changes after load_env() are picked up.
    # New alias form: DIVAPPLY_LLM_SCORER=openai:gpt-5.4-mini,
    # DIVAPPLY_LLM_TAILOR=ollama:qwen2.5:14b, etc.
    alias_var = _STAGE_ALIAS_VARS.get(stage, "")
    alias = os.environ.get(alias_var, "") if alias_var else ""
    if alias:
        cache_key = f"{stage}:alias:{alias}"
        if cache_key not in _stage_instances:
            base_url, model, api_key = _detect_provider(alias)
            log.info("LLM stage '%s': alias=%s provider=%s model=%s", stage, alias, base_url, model)
            _stage_instances[cache_key] = LLMClient(base_url, model, api_key)
        return _stage_instances[cache_key]

    stage_var = _STAGE_MODEL_VARS.get(stage, "")
    stage_model = os.environ.get(stage_var, "") if stage_var else ""

    if not stage_model:
        # No stage override — use the default singleton
        return get_client()

    cache_key = f"{stage}:{stage_model}"
    if cache_key not in _stage_instances:
        base_url, default_model, api_key = _detect_provider()
        log.info("LLM stage '%s': provider=%s  model=%s", stage, base_url, stage_model)
        _stage_instances[cache_key] = LLMClient(base_url, stage_model, api_key)

    return _stage_instances[cache_key]
