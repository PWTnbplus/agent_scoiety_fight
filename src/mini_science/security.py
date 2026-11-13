from __future__ import annotations

"""Small recursive redaction boundary for local audit artifacts."""

import re
from typing import Any


_BEARER = re.compile(r"(?i)(Bearer\s+)[^\s,;]+")
_AUTH_HEADER = re.compile(r"(?i)(authorization\s*[:=]\s*)[^\s,;]+")


def redact_text(value: str) -> str:
    value = _BEARER.sub(r"\1[REDACTED]", value)
    return _AUTH_HEADER.sub(r"\1[REDACTED]", value)


def redact_for_log(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in {"authorization", "proxy-authorization", "api_key", "apikey", "access_token"}:
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = redact_for_log(item)
        return result
    if isinstance(value, list):
        return [redact_for_log(item) for item in value]
    if isinstance(value, tuple):
        return [redact_for_log(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
