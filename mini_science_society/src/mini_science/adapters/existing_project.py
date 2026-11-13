from __future__ import annotations

"""Legacy-compatible OpenAI-compatible adapter.

The request shape and environment names are extracted from the user's existing
`OpenAICompatibleProvider` implementation. This module is fail-closed and does
not perform any request unless `allow_paid_api=True` is explicitly set by the
caller.
"""

import json
import math
import os
import time
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from .base import LLMResponse, ProviderAdapter


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.split()), math.ceil(len(text) / 2)) if text else 0


class ExistingProjectAdapter(ProviderAdapter):
    def __init__(
        self,
        *,
        allow_paid_api: bool = False,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        input_cost_per_1k: float | None = None,
        output_cost_per_1k: float | None = None,
        max_cost_usd: float | None = None,
    ) -> None:
        self.allow_paid_api = allow_paid_api
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.model_name = model_name or os.getenv("LLM_MODEL", "")
        self.timeout = float(timeout if timeout is not None else os.getenv("LLM_TIMEOUT", "60"))
        self.max_retries = int(max_retries if max_retries is not None else os.getenv("LLM_MAX_RETRIES", "0"))
        self.input_cost_per_1k = float(input_cost_per_1k if input_cost_per_1k is not None else os.getenv("LLM_COST_PER_1K_INPUT_TOKENS", "0"))
        self.output_cost_per_1k = float(output_cost_per_1k if output_cost_per_1k is not None else os.getenv("LLM_COST_PER_1K_OUTPUT_TOKENS", "0"))
        configured_cap = os.getenv("LLM_MAX_COST_USD", "")
        self.max_cost_usd = max_cost_usd if max_cost_usd is not None else (float(configured_cap) if configured_cap else None)
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        self.calls: list[dict[str, Any]] = []
        self.traces: list[dict[str, Any]] = []
        self.observed_cost_usd = 0.0

    def complete(self, messages: list[dict[str, str]], max_output_tokens: int) -> LLMResponse:
        if not self.allow_paid_api:
            raise PermissionError("real provider disabled: pass --allow-paid-api")
        if not self.api_key:
            raise RuntimeError("LLM_API_KEY is not configured")
        if not self.model_name:
            raise RuntimeError("LLM_MODEL is not configured")
        if self.input_cost_per_1k <= 0 and self.output_cost_per_1k <= 0:
            raise RuntimeError("LLM token pricing is not configured")
        payload = {"model": self.model_name, "messages": messages, "max_tokens": int(max_output_tokens)}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            estimated_input = _estimate_tokens(json.dumps({"messages": messages}, ensure_ascii=False))
            worst_case = estimated_input / 1000.0 * self.input_cost_per_1k + max_output_tokens / 1000.0 * self.output_cost_per_1k
            if self.max_cost_usd is not None and self.observed_cost_usd + worst_case > self.max_cost_usd:
                raise RuntimeError("hard cost cap would be exceeded before provider request")
            started = time.monotonic()
            try:
                req = urlrequest.Request(f"{self.base_url}/chat/completions", data=body, headers=headers, method="POST")
                with urlrequest.urlopen(req, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                latency_ms = int((time.monotonic() - started) * 1000)
                choice = data["choices"][0]
                message = choice.get("message", {})
                text = message.get("content") or ""
                usage = data.get("usage") or {}
                input_tokens = int(usage.get("prompt_tokens", estimated_input))
                output_tokens = int(usage.get("completion_tokens", _estimate_tokens(text)))
                cost = input_tokens / 1000.0 * self.input_cost_per_1k + output_tokens / 1000.0 * self.output_cost_per_1k
                self.observed_cost_usd += cost
                record = {"model": self.model_name, "attempt": attempt + 1, "latency_ms": latency_ms, "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}, "response_model": data.get("model"), "raw_id": data.get("id")}
                self.calls.append(record)
                self.traces.append({"call_index": len(self.traces), "request": {"messages": messages, "max_tokens": max_output_tokens}, "response": {"content": text, "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}, "metadata": record}})
                if self.max_cost_usd is not None and self.observed_cost_usd > self.max_cost_usd + 1e-12:
                    raise RuntimeError("provider usage exceeded local hard cost cap")
                return LLMResponse(text=text, model=self.model_name, input_tokens=input_tokens, output_tokens=output_tokens, latency_ms=latency_ms, cost_usd=cost, metadata={"provider": "openai-compatible", **record})
            except HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:2000]
                except Exception:
                    detail = ""
                last_error = RuntimeError(f"HTTP {exc.code} {exc.reason}: {detail}" if detail else f"HTTP {exc.code} {exc.reason}")
                self.traces.append({"call_index": len(self.traces), "request": {"messages": messages, "max_tokens": max_output_tokens}, "attempt": attempt + 1, "error": {"type": type(exc).__name__, "status_code": exc.code}, "latency_ms": int((time.monotonic() - started) * 1000)})
            except (URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
                last_error = exc
                self.traces.append({"call_index": len(self.traces), "request": {"messages": messages, "max_tokens": max_output_tokens}, "attempt": attempt + 1, "error": {"type": type(exc).__name__, "message": str(exc)[:500]}, "latency_ms": int((time.monotonic() - started) * 1000)})
            if attempt < self.max_retries:
                continue
        raise RuntimeError(f"LLM provider request failed after retries: {last_error}") from last_error

    def audit_trace(self) -> list[dict[str, Any]]:
        return json.loads(json.dumps(self.traces))
