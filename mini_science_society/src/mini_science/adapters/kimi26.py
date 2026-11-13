from __future__ import annotations

"""Standalone Kimi K2.6 adapter copied from the existing project's contract.

This module intentionally does not import the old project. It reproduces the
verified CTFlow/OpenAI-compatible request shape used by the Kimi 2.6 entrypoint:
explicit key-file loading, HTTPS base validation, redirect blocking, zero
transport retries, fixed Kimi pricing for local accounting, usage extraction,
model-identity checking, and a hard local cost cap.
"""

import json
import math
import os
from pathlib import Path
import time
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from .base import LLMResponse, ProviderAdapter


DEFAULT_MODEL_ID = "kimi-k2.6"
DEFAULT_BASE_URL = "https://token.ctflow.cn/v1"
DEFAULT_INPUT_COST_PER_1K = 0.00095
DEFAULT_OUTPUT_COST_PER_1K = 0.004
DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_MAX_OUTPUT_TOKENS = 1200
DEFAULT_KEY_RELATIVE_PATH = Path("api_key") / "kimi" / "kimi-k2.6.txt"
DEFAULT_SOURCE_PROJECT = Path(r"E:\master_exp\nature_prj1_cal\from_llm_to_agent")


class NoRedirect(urlrequest.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("redirect blocked; credentials were not forwarded")


def validate_base_url(value: str) -> str:
    parsed = urlsplit(value.rstrip("/"))
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Kimi base URL must be HTTPS without credentials, query, or fragment")
    if not parsed.hostname:
        raise ValueError("Kimi base URL has no host")
    return value.rstrip("/")


def estimate_tokens(text: str) -> int:
    return max(1, len(text.split()), math.ceil(len(text) / 2)) if text else 0


class Kimi26Adapter(ProviderAdapter):
    """Direct, standalone Kimi K2.6 CTFlow adapter."""

    def __init__(
        self,
        *,
        allow_paid_api: bool = False,
        key_file: str | Path | None = None,
        source_project: str | Path | None = None,
        base_url: str | None = None,
        model_id: str | None = None,
        timeout: float | None = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        max_cost_usd: float | None = None,
        input_cost_per_1k: float = DEFAULT_INPUT_COST_PER_1K,
        output_cost_per_1k: float = DEFAULT_OUTPUT_COST_PER_1K,
        temperature: float = 0.6,
    ) -> None:
        self.allow_paid_api = allow_paid_api
        self.model_name = model_id or os.getenv("KIMI26_MODEL_ID", DEFAULT_MODEL_ID)
        if self.model_name != DEFAULT_MODEL_ID:
            raise ValueError(f"Kimi26Adapter is frozen to model {DEFAULT_MODEL_ID}")
        self.base_url = validate_base_url(base_url or os.getenv("KIMI26_BASE_URL", DEFAULT_BASE_URL))
        self.timeout = float(timeout if timeout is not None else os.getenv("KIMI26_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)))
        self.max_output_tokens = int(max_output_tokens if max_output_tokens is not None else os.getenv("KIMI26_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS)))
        self.max_cost_usd = max_cost_usd if max_cost_usd is not None else self._optional_float_env("KIMI26_MAX_COST_USD")
        self.input_cost_per_1k = float(input_cost_per_1k)
        self.output_cost_per_1k = float(output_cost_per_1k)
        self.temperature = float(temperature)
        if self.max_output_tokens <= 0 or self.timeout <= 0:
            raise ValueError("Kimi timeout and max output tokens must be positive")
        if self.input_cost_per_1k <= 0 or self.output_cost_per_1k <= 0:
            raise ValueError("Kimi local pricing must be positive")
        if self.max_cost_usd is not None and self.max_cost_usd <= 0:
            raise ValueError("Kimi max cost must be positive when configured")
        source_root = Path(source_project) if source_project else DEFAULT_SOURCE_PROJECT
        explicit_key = key_file or os.getenv("KIMI26_KEY_FILE")
        self.key_file = Path(explicit_key) if explicit_key else source_root / DEFAULT_KEY_RELATIVE_PATH
        self.reserved_cost_usd = 0.0
        self.observed_cost_usd = 0.0
        self.calls: list[dict[str, Any]] = []
        self.traces: list[dict[str, Any]] = []

    @staticmethod
    def _optional_float_env(name: str) -> float | None:
        value = os.getenv(name, "").strip()
        return float(value) if value else None

    def _read_key(self) -> str:
        try:
            key = self.key_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"Kimi key file cannot be read: {self.key_file}") from exc
        if not key:
            raise RuntimeError(f"Kimi key file is empty: {self.key_file}")
        return key

    def complete(self, messages: list[dict[str, str]], max_output_tokens: int) -> LLMResponse:
        if not self.allow_paid_api:
            raise PermissionError("Kimi K2.6 provider disabled: pass --allow-paid-api")
        key = self._read_key()
        requested_output_tokens = min(int(max_output_tokens), self.max_output_tokens)
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": requested_output_tokens,
            "temperature": self.temperature,
            "stream": False,
        }
        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        }
        estimated_input = estimate_tokens(json.dumps({"messages": messages}, ensure_ascii=False))
        worst_case_cost = (estimated_input / 1000.0) * self.input_cost_per_1k + (requested_output_tokens / 1000.0) * self.output_cost_per_1k
        if self.max_cost_usd is not None and self.reserved_cost_usd + worst_case_cost > self.max_cost_usd:
            raise RuntimeError("Kimi local hard cost cap would be exceeded before request")
        self.reserved_cost_usd += worst_case_cost
        started = time.monotonic()
        request_hash = __import__("hashlib").sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        trace: dict[str, Any] = {
            "request_hash": request_hash,
            "model_requested": self.model_name,
            "endpoint": f"{self.base_url}/chat/completions",
            "max_tokens": requested_output_tokens,
            "temperature": self.temperature,
            "stream": False,
            "retry_count": 0,
        }
        try:
            request = urlrequest.Request(f"{self.base_url}/chat/completions", data=request_body, headers=headers, method="POST")
            with urlrequest.build_opener(NoRedirect()).open(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            choice = data["choices"][0]
            message = choice.get("message", {})
            content = message.get("content") or ""
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            response_model = data.get("model")
            if response_model and str(response_model) != self.model_name:
                raise RuntimeError(f"MODEL_IDENTITY_MISMATCH:requested={self.model_name}:returned={response_model}")
            usage_data = data.get("usage") or {}
            usage_verified = "prompt_tokens" in usage_data and "completion_tokens" in usage_data
            input_tokens = int(usage_data.get("prompt_tokens", estimated_input))
            output_tokens = int(usage_data.get("completion_tokens", estimate_tokens(content)))
            provider_cost = usage_data.get("cost_usd")
            cost_basis = "provider_reported" if provider_cost is not None else "local_rate_estimate"
            cost = float(provider_cost) if provider_cost is not None else (input_tokens / 1000.0) * self.input_cost_per_1k + (output_tokens / 1000.0) * self.output_cost_per_1k
            latency_ms = int((time.monotonic() - started) * 1000)
            self.observed_cost_usd += cost
            trace.update({
                "status": "completed",
                "response_model": response_model,
                "response_id": data.get("id"),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost,
                "cost_basis": cost_basis,
                "usage_verified": usage_verified,
                "provider_billing_verified": provider_cost is not None,
                "latency_ms": latency_ms,
            })
            self.calls.append(trace.copy())
            self.traces.append({"request": {"messages": messages, "payload": {key: value for key, value in payload.items() if key != "messages"}}, "response": {"content": content, "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost}, "metadata": trace.copy()}})
            if self.max_cost_usd is not None and self.observed_cost_usd > self.max_cost_usd + 1e-12:
                raise RuntimeError("provider usage exceeded Kimi local hard cost cap")
            return LLMResponse(text=content, model=self.model_name, input_tokens=input_tokens, output_tokens=output_tokens, latency_ms=latency_ms, cost_usd=cost, raw_response_ref=data.get("id"), metadata={"provider": "ctflow", "model": self.model_name, **trace})
        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:2000]
            except Exception:
                detail = ""
            trace.update({"status": "http_error", "http_status": exc.code, "latency_ms": int((time.monotonic() - started) * 1000)})
            self.traces.append({"request": {"messages": messages, "payload": {key: value for key, value in payload.items() if key != "messages"}}, "error": {"type": "HTTPError", "status_code": exc.code, "detail": detail}, "metadata": trace.copy()})
            raise RuntimeError(f"Kimi HTTP {exc.code} {exc.reason}") from exc
        except (URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            trace.update({"status": "transport_or_parse_error", "error_type": type(exc).__name__, "latency_ms": int((time.monotonic() - started) * 1000)})
            self.traces.append({"request": {"messages": messages, "payload": {key: value for key, value in payload.items() if key != "messages"}}, "error": {"type": type(exc).__name__, "message": str(exc)[:500]}, "metadata": trace.copy()})
            raise RuntimeError(f"Kimi request failed without retry: {type(exc).__name__}") from exc

    def audit_trace(self) -> list[dict[str, Any]]:
        return json.loads(json.dumps(self.traces, ensure_ascii=False))
