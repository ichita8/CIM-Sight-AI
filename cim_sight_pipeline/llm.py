from __future__ import annotations
import json
import time
from .config import ExperimentConfig


class LLMError(Exception):
    pass


class FatalLLMError(LLMError):
    """Raised when the error is not retryable or retries are exhausted."""
    pass


class LLMClient:
    """Phase 2 (#4): transport with exception-class-aware retry + backoff."""

    def __init__(self, config: ExperimentConfig):
        self.config = config
        from openai import OpenAI
        self._client = OpenAI(base_url=config.base_url, api_key=config.api_key)

    def audit_chunk(self, system_prompt: str, user_prompt: str):
        """Returns (parsed_dict, meta) where meta holds retries/latency/tokens."""
        meta = {"retries": 0, "latency_ms": 0.0, "tokens_in": 0, "tokens_out": 0}
        last_error = None
        for attempt in range(self.config.max_retries + 1):
            try:
                t0 = time.time()
                resp = self._client.chat.completions.create(
                    model=self.config.model,
                    temperature=self.config.temperature,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                )
                meta["latency_ms"] += (time.time() - t0) * 1000
                content = resp.choices[0].message.content or "{}"
                data = json.loads(content)
                usage = getattr(resp, "usage", None)
                if usage:
                    meta["tokens_in"] += getattr(usage, "prompt_tokens", 0) or 0
                    meta["tokens_out"] += getattr(usage, "completion_tokens", 0) or 0
                return data, meta
            except Exception as e:
                last_error = e
                kind = self._classify_error(e)
                if kind == "fatal" or attempt == self.config.max_retries:
                    raise FatalLLMError(
                        "LLM call failed after %d attempts: %s" % (attempt + 1, e)
                    ) from e
                meta["retries"] += 1
                time.sleep(self.config.base_backoff * (2 ** attempt))
        raise FatalLLMError("LLM call failed: %s" % last_error)

    @staticmethod
    def _classify_error(exc) -> str:
        name = type(exc).__name__
        msg = str(exc).lower()
        try:
            import openai
            if isinstance(exc, openai.RateLimitError):
                return "rate_limit"
            if isinstance(exc, openai.APITimeoutError):
                return "timeout"
            if isinstance(exc, openai.APIConnectionError):
                return "connection"
            if isinstance(exc, openai.APIError):
                return "api"
        except Exception:
            pass
        if "404" in msg or "model not found" in msg or "does not exist" in msg:
            return "fatal"
        if "timeout" in name.lower() or "timeout" in msg:
            return "timeout"
        if "rate" in msg or "429" in msg:
            return "rate_limit"
        if "connection" in name.lower() or "connection" in msg:
            return "connection"
        return "api"
