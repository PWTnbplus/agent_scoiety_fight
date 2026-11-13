from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from mini_science.authorization import V5P4_CONFIRMATION_PHRASE, create_v5p4_authorization, proposed_v5p4_authorization
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config
from mini_science.proposal_fingerprint import proposal_digest
from mini_science.schema import sha256_json
from mini_science.stable_fingerprint import stable_tree_hash


def test_repeated_hash_is_stable(tmp_path: Path):
    (tmp_path / "program.py").write_text("x=1\n", encoding="utf-8")
    values = [stable_tree_hash(tmp_path) for _ in range(100)]
    assert len(set(values)) == 1


def test_pycache_addition_and_deletion_do_not_change_hash(tmp_path: Path):
    (tmp_path / "program.py").write_text("x=1\n", encoding="utf-8")
    before = stable_tree_hash(tmp_path)
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    artifact = cache / "program.cpython-311.pyc"
    artifact.write_bytes(b"compiled")
    assert stable_tree_hash(tmp_path) == before
    artifact.unlink()
    assert stable_tree_hash(tmp_path) == before


def test_pytest_cache_changes_do_not_change_hash(tmp_path: Path):
    (tmp_path / "program.py").write_text("x=1\n", encoding="utf-8")
    before = stable_tree_hash(tmp_path)
    cache = tmp_path / ".pytest_cache"
    cache.mkdir()
    (cache / "v cache").write_text("one", encoding="utf-8")
    assert stable_tree_hash(tmp_path) == before
    (cache / "v cache").write_text("two", encoding="utf-8")
    assert stable_tree_hash(tmp_path) == before


@pytest.mark.parametrize("relative_path", ["agent.py", "prompts.py", "experiment.json", "new_script.py"])
def test_real_file_changes_change_hash(tmp_path: Path, relative_path: str):
    path = tmp_path / relative_path
    path.write_text("one\n", encoding="utf-8")
    before = stable_tree_hash(tmp_path)
    path.write_text("two\n", encoding="utf-8")
    assert stable_tree_hash(tmp_path) != before


def test_creation_order_does_not_change_hash(tmp_path: Path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    for name in ("z.py", "a.py", "settings.json"):
        (left / name).write_text(name, encoding="utf-8")
    for name in ("settings.json", "a.py", "z.py"):
        (right / name).write_text(name, encoding="utf-8")
    assert stable_tree_hash(left) == stable_tree_hash(right)


def test_missing_directory_fails_closed(tmp_path: Path):
    with pytest.raises(ValueError):
        stable_tree_hash(tmp_path / "missing")


def test_symlink_fails_closed_when_supported(tmp_path: Path):
    target = tmp_path / "target.py"
    target.write_text("x=1\n", encoding="utf-8")
    try:
        (tmp_path / "alias.py").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink privilege is unavailable")
    with pytest.raises(ValueError, match="symlink"):
        stable_tree_hash(tmp_path)


def _temporary_proposal_root(tmp_path: Path) -> tuple[Path, object, list[dict]]:
    root = tmp_path / "project"
    for name in ("src", "tests", "scripts", "docs"):
        shutil.copytree(Path(name), root / name)
    shutil.copytree(Path("data/worlds_v5p4_dev"), root / "data/worlds_v5p4_dev")
    shutil.copytree(Path("private/worlds_v5p4_dev"), root / "private/worlds_v5p4_dev")
    config = load_config("config/v5p4_offline_dev.json")
    plan = pilot_request_plan(root, config, worlds=["CV001"], conditions=list(config.conditions), repeats=1)
    return root, config, plan


def _bound_proposal(root: Path, config, plan: list[dict]) -> dict:
    proposal = proposed_v5p4_authorization(root, config, request_plan=plan)
    proposal.update({
        "proposal_version": "V5-P6",
        "source_tree_hash": stable_tree_hash(root / "src"),
        "tests_tree_hash": stable_tree_hash(root / "tests"),
        "scripts_tree_hash": stable_tree_hash(root / "scripts"),
        "public_world_tree_hash": stable_tree_hash(root / "data/worlds_v5p4_dev"),
        "private_fixture_tree_hash": stable_tree_hash(root / "private/worlds_v5p4_dev"),
        "docs_tree_hash": stable_tree_hash(root / "docs"),
        "generated_at": "test",
        "real_api_calls_this_round": 0,
        "network_requests_this_round": 0,
    })
    proposal["proposal_sha256"] = proposal_digest(proposal)
    return proposal


def test_proposal_digest_is_stable_after_cache_creation(tmp_path: Path):
    root, config, plan = _temporary_proposal_root(tmp_path)
    proposal = _bound_proposal(root, config, plan)
    before = proposal["proposal_sha256"]
    (root / "src/mini_science/__pycache__").mkdir(parents=True, exist_ok=True)
    (root / "src/mini_science/__pycache__/x.pyc").write_bytes(b"cache")
    proposal_after = _bound_proposal(root, config, plan)
    assert proposal_after["proposal_sha256"] == before


def test_modified_source_is_rejected_by_proposal_binding(tmp_path: Path):
    root, config, plan = _temporary_proposal_root(tmp_path)
    proposal = _bound_proposal(root, config, plan)
    proposal_path = root / "proposal.json"
    proposal_path.write_text(json.dumps(proposal, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    source = root / "src/mini_science/stable_fingerprint.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# intentional test mutation\n", encoding="utf-8")
    with pytest.raises(PermissionError, match="proposal binding mismatch: source_tree_hash"):
        create_v5p4_authorization(
            root,
            config,
            approved_by="user_explicit",
            confirmation=V5P4_CONFIRMATION_PHRASE,
            authorization_note="test only",
            request_plan=plan,
            worlds=["CV001"],
            conditions=list(config.conditions),
            max_unique_provider_attempts=5,
            max_estimated_cost_usd=0.05,
            proposal_path=proposal_path,
            proposal_sha256=proposal["proposal_sha256"],
            require_proposal_binding=True,
        )


def test_proposal_digest_detects_tamper():
    proposal = {"request_plan_hash": "plan", "config_hash": "config"}
    digest = sha256_json(proposal)
    tampered = dict(proposal, config_hash="changed", proposal_sha256=digest)
    assert proposal_digest(tampered) != digest
