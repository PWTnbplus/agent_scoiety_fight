from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from mini_science.config import load_config
from mini_science.public_loader import load_world
from mini_science.schema import parse_json_object, validate_final_question


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs" / "real_kimi26_w001_v3_01" / "agent_artifacts" / "W001" / "replicate_0"


def raw_text(condition: str) -> str:
    value = json.loads((RUN / condition / "final.json").read_text(encoding="utf-8"))
    return str(value.get("raw_text", ""))


def strip_one_fence(raw: str) -> str:
    match = re.fullmatch(r"\s*```(?:json)?\s*\n?(.*?)\n?```\s*", raw, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else raw


def normalize_diagnostic(value: dict) -> dict:
    copy = json.loads(json.dumps(value, ensure_ascii=False))
    copy["hypotheses_to_discriminate"] = [str(item).split(":", 1)[0].strip() for item in copy.get("hypotheses_to_discriminate", [])]
    return copy


def main() -> None:
    config = load_config(ROOT / "config" / "pilot_v2.json")
    view = load_world(ROOT, "W001", "related", worlds_subdir=config.worlds_subdir)
    a_raw = raw_text("A_TARGET_ONLY")
    b_raw = raw_text("B_SINGLE_RELATED")
    a_stripped = strip_one_fence(a_raw)
    a_strict = parse_json_object(a_raw)
    a_after_fence = parse_json_object(a_stripped)
    a_normalized = validate_final_question(json.dumps(normalize_diagnostic(a_after_fence.data or {}), ensure_ascii=False), view)
    b_parsed = parse_json_object(b_raw)
    b_validation = validate_final_question(b_raw, view)
    report = [
        "# V3 raw failure replay",
        "",
        "This is a diagnostic-only replay. It reads historical artifacts and never modifies the V3 result, ledger, authorization, or reports.",
        "",
        f"- A raw SHA256: `{hashlib.sha256(a_raw.encode('utf-8')).hexdigest()}`",
        f"- B raw SHA256: `{hashlib.sha256(b_raw.encode('utf-8')).hexdigest()}`",
        f"- A strict parse: `{a_strict.reason}`",
        f"- A after removing one diagnostic fence: `{a_after_fence.reason}`",
        f"- A after diagnostic hypothesis normalization: `{a_normalized.reason}`",
        f"- B strict parse: `{b_parsed.reason}`",
        f"- B final schema validation: `{b_validation.reason}`",
        "",
        "## Independent failure causes",
        "",
        "1. The original A response contains a Markdown JSON fence; strict parsing rejects it.",
        "2. Removing that fence only for a diagnostic copy still exposes explanatory strings in `hypotheses_to_discriminate`, not exact candidate IDs.",
        "3. The diagnostic copy still contains the compressed evidence token `S01-S04`; individual evidence IDs are required, so it is rejected. This is a formatting failure, not an evidence-permission violation: S01–S04 were visible in the A prompt.",
        "4. B parses and validates structurally, but its prose numeric claims are audited separately and are not treated as verified predictions.",
        "",
        "No normalized diagnostic value was written back to the historical A result.",
    ]
    destination = ROOT / "reports" / "v4_preflight" / "V3_A_RAW_FAILURE_REPLAY.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
