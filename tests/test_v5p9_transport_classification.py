from __future__ import annotations

import json
import socket
import ssl
from urllib.error import HTTPError, URLError

import pytest

from mini_science.adapters.kimi26 import Kimi26Adapter, KimiRequestError


def _adapter(monkeypatch, tmp_path, error):
    key_file = tmp_path / "key.txt"
    key_file.write_text("SECRET_FIXTURE_KEY", encoding="utf-8")

    class FakeOpener:
        calls = 0

        def open(self, *_args, **_kwargs):
            self.calls += 1
            raise error

    opener = FakeOpener()
    monkeypatch.setattr("urllib.request.build_opener", lambda *_args, **_kwargs: opener)
    return Kimi26Adapter(allow_paid_api=True, key_file=key_file, timeout=1, max_output_tokens=32), opener


def test_dns_failure_is_classified_without_secret_or_retry(monkeypatch, tmp_path):
    adapter, opener = _adapter(monkeypatch, tmp_path, URLError(socket.gaierror(-2, "hidden dns detail")))
    with pytest.raises(KimiRequestError) as error:
        adapter.complete([{"role": "user", "content": "offline"}], 8)
    assert error.value.failure_kind == "DNS_FAILURE"
    assert error.value.reason_type == "DNS_RESOLUTION"
    assert error.value.detail_code == "DNS_GAIERROR"
    assert opener.calls == 1
    assert "SECRET_FIXTURE_KEY" not in json.dumps(adapter.audit_trace())


def test_tls_verification_failure_is_classified(monkeypatch, tmp_path):
    error = ssl.SSLCertVerificationError(1, "certificate detail must not be logged")
    adapter, opener = _adapter(monkeypatch, tmp_path, URLError(error))
    with pytest.raises(KimiRequestError) as raised:
        adapter.complete([{"role": "user", "content": "offline"}], 8)
    assert raised.value.failure_kind == "TLS_VERIFY_FAILURE"
    assert raised.value.detail_code == "TLS_CERT_VERIFY"
    assert opener.calls == 1


def test_interrupted_post_is_ambiguous_for_billing(monkeypatch, tmp_path):
    adapter, opener = _adapter(monkeypatch, tmp_path, URLError(socket.timeout("timed out")))
    with pytest.raises(KimiRequestError) as raised:
        adapter.complete([{"role": "user", "content": "offline"}], 8)
    assert raised.value.failure_kind == "AMBIGUOUS_POST_OUTCOME"
    assert raised.value.reason_type == "TIMEOUT"
    assert opener.calls == 1


def test_http_status_preserves_legacy_kind_and_adds_reason_type(monkeypatch, tmp_path):
    error = HTTPError("https://token.ctflow.cn/v1/chat/completions", 503, "unlogged reason", {}, None)
    adapter, opener = _adapter(monkeypatch, tmp_path, error)
    with pytest.raises(KimiRequestError) as raised:
        adapter.complete([{"role": "user", "content": "offline"}], 8)
    assert raised.value.failure_kind == "HTTP_ERROR"
    assert raised.value.reason_type == "HTTP_STATUS_ERROR"
    assert raised.value.detail_code == "HTTP_503"
    assert opener.calls == 1
