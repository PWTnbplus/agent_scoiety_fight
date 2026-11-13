from __future__ import annotations

from mini_science.runner import _append_jsonl, _json_write


def test_real_api_logs_redact_authorization_headers(tmp_path):
    value = {"authorization": "Bearer secret-value", "request": "Authorization: Bearer another-secret", "nested": {"api_key": "third-secret"}}
    jsonl = tmp_path / "events.jsonl"
    json_file = tmp_path / "artifact.json"
    _append_jsonl(jsonl, value)
    _json_write(json_file, value)
    for path in (jsonl, json_file):
        text = path.read_text(encoding="utf-8")
        assert "secret-value" not in text
        assert "another-secret" not in text
        assert "third-secret" not in text
        assert "[REDACTED]" in text
