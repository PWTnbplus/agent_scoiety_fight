from __future__ import annotations

import json

import pytest

from mini_science.adapters.base import LLMResponse
from mini_science.adapters.kimi26 import Kimi26Adapter
from mini_science.protocol_checks import check_api_response


def _response(text: str, **metadata: object) -> LLMResponse:
    return LLMResponse(
        text=text,
        model="kimi-k2.6",
        input_tokens=12,
        output_tokens=5,
        latency_ms=1,
        cost_usd=0.001,
        metadata={"provider": "fake", "usage_verified": True, **metadata},
    )


def test_v3_api_contract_requires_exact_status_model_and_usage():
    passed = check_api_response(
        _response('{"status":"ok"}', returned_model="kimi-k2.6", provider_billing_verified=True),
        requested_model="kimi-k2.6",
    )
    assert passed["gate_result"] == "PASS"
    assert passed["response_status_ok"] is True
    assert passed["usage_source"] == "provider_usage"

    failed = check_api_response(_response('{"status":"error"}', returned_model="kimi-k2.6"), requested_model="kimi-k2.6")
    assert failed["gate_result"] == "FAIL"

    mismatch = check_api_response(_response('{"status":"ok"}', returned_model="other-model"), requested_model="kimi-k2.6")
    assert mismatch["model_status"] == "MODEL_ID_MISMATCH"
    assert mismatch["gate_result"] == "FAIL"

    unverified = check_api_response(_response('{"status":"ok"}'), requested_model="kimi-k2.6")
    assert unverified["gate_result"] == "UNVERIFIED"
    assert unverified["model_status"] == "MODEL_ID_UNVERIFIED"


def test_v3_truncation_is_reported():
    result = check_api_response(_response('{"status":"ok"}', returned_model="kimi-k2.6", finish_reason="length"), requested_model="kimi-k2.6")
    assert result["truncated"] is True


def test_v3_fake_http_preserves_kimi_contract(monkeypatch, tmp_path):
    key_file = tmp_path / "fake-key.txt"
    key_file.write_text("offline-fixture-key", encoding="utf-8")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({
                "id": "fake-request",
                "model": "kimi-k2.6",
                "choices": [{"message": {"content": '{"status":"ok"}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5, "cost_usd": 0.001},
            }).encode("utf-8")

    class FakeOpener:
        def open(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr("urllib.request.build_opener", lambda *_args, **_kwargs: FakeOpener())
    adapter = Kimi26Adapter(allow_paid_api=True, key_file=key_file, timeout=1, max_output_tokens=32)
    response = adapter.complete([{"role": "user", "content": "contract"}], 8)
    result = check_api_response(response, requested_model=adapter.model_name)
    assert result["gate_result"] == "PASS"
    assert result["returned_model"] == "kimi-k2.6"
    assert result["usage_source"] == "provider_usage"

