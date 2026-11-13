from __future__ import annotations

import json

import pytest

from mini_science.adapters.existing_project import ExistingProjectAdapter, validate_base_url as validate_existing_url
from mini_science.adapters.kimi26 import Kimi26Adapter


class _FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeOpener:
    def __init__(self, payload, sink):
        self.payload = payload
        self.sink = sink

    def open(self, request, timeout):
        self.sink.append({
            "url": request.full_url,
            "headers": dict(request.header_items()),
            "timeout": timeout,
            "payload": json.loads(request.data.decode("utf-8")),
        })
        return _FakeResponse(self.payload)


def test_existing_protocol_fixture_is_https_and_openai_compatible(monkeypatch):
    calls = []
    monkeypatch.setenv("LLM_API_KEY", "fixture-key")
    monkeypatch.setenv("LLM_MODEL", "fixture-model")
    monkeypatch.setenv("LLM_COST_PER_1K_INPUT_TOKENS", "0.001")
    monkeypatch.setenv("LLM_COST_PER_1K_OUTPUT_TOKENS", "0.002")
    monkeypatch.setattr("urllib.request.build_opener", lambda *args, **kwargs: _FakeOpener({"model": "fixture-model", "choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}, calls))
    response = ExistingProjectAdapter(allow_paid_api=True, base_url="https://example.test/v1").complete([{"role": "user", "content": "hello"}], 8)
    assert response.text == "ok"
    assert calls[0]["url"] == "https://example.test/v1/chat/completions"
    assert calls[0]["payload"]["model"] == "fixture-model"
    assert calls[0]["payload"]["max_tokens"] == 8
    assert "Authorization" in calls[0]["headers"]


def test_kimi26_protocol_fixture_has_fixed_model_and_local_cost(monkeypatch, tmp_path):
    calls = []
    key_file = tmp_path / "kimi-k2.6.txt"
    key_file.write_text("fixture-key", encoding="utf-8")
    monkeypatch.setattr("urllib.request.build_opener", lambda *args, **kwargs: _FakeOpener({"id": "fixture-id", "model": "kimi-k2.6", "choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}, calls))
    response = Kimi26Adapter(allow_paid_api=True, key_file=key_file, base_url="https://example.test/v1", max_output_tokens=24, max_cost_usd=0.05).complete([{"role": "user", "content": "hello"}], 24)
    assert response.text == "ok"
    assert calls[0]["url"] == "https://example.test/v1/chat/completions"
    assert calls[0]["payload"]["model"] == "kimi-k2.6"
    assert calls[0]["payload"]["temperature"] == 0.6
    assert calls[0]["payload"]["stream"] is False
    assert response.metadata["provider_billing_verified"] is False
    assert response.metadata["cost_basis"] == "local_rate_estimate"


def test_existing_url_validation_blocks_http_and_credentials():
    with pytest.raises(ValueError):
        validate_existing_url("http://example.test/v1")
    with pytest.raises(ValueError):
        validate_existing_url("https://u:p@example.test/v1")
