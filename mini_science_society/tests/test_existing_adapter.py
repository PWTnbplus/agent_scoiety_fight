from __future__ import annotations

import pytest

from mini_science.adapters.existing_project import ExistingProjectAdapter


def test_existing_provider_is_fail_closed_without_authorization(monkeypatch):
    called = False

    def no_network(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not be touched")

    monkeypatch.setattr("urllib.request.urlopen", no_network)
    adapter = ExistingProjectAdapter(allow_paid_api=False)
    with pytest.raises(PermissionError):
        adapter.complete([{"role": "user", "content": "ok"}], 8)
    assert called is False
