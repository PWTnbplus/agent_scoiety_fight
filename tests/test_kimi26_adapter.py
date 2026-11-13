from __future__ import annotations

import pytest

from mini_science.adapters.kimi26 import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL_ID,
    Kimi26Adapter,
    validate_base_url,
)


def test_kimi26_defaults_are_frozen_to_audited_contract():
    adapter = Kimi26Adapter()
    assert adapter.model_name == DEFAULT_MODEL_ID == "kimi-k2.6"
    assert adapter.base_url == DEFAULT_BASE_URL == "https://token.ctflow.cn/v1"
    assert adapter.max_output_tokens == 1200
    assert adapter.key_file.name == "kimi-k2.6.txt"


def test_kimi26_refuses_network_before_key_read_without_authorization(monkeypatch, tmp_path):
    called = False

    def no_network(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not be touched")

    monkeypatch.setattr("urllib.request.build_opener", no_network)
    adapter = Kimi26Adapter(allow_paid_api=False, key_file=tmp_path / "missing-key.txt")
    with pytest.raises(PermissionError):
        adapter.complete([{"role": "user", "content": "offline"}], 8)
    assert called is False


def test_kimi26_rejects_insecure_or_credentialed_base_url():
    with pytest.raises(ValueError):
        validate_base_url("http://token.ctflow.cn/v1")
    with pytest.raises(ValueError):
        validate_base_url("https://user:pass@token.ctflow.cn/v1")
