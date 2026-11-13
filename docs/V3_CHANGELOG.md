# V3 changelog

## 2026-11-12 — offline Gate 1-A/1-B implementation

- Added `config/real_gate_v3.json` with default `NOT_AUTHORIZED`, zero calls,
  model/provider/world/condition allowlists and an 800-token role budget.
- Added `src/mini_science/real_gate.py` for persistent cross-process attempt and
  estimated-cost accounting.
- Added `src/mini_science/protocol_checks.py` for exact check-api response,
  model identity, usage, truncation and role schema status.
- Hardened `cli.py`, `runner.py`, and probe reports so real status is explicit.
- Added V3 fake-HTTP/BehavioralMock tests; no real request was made.
- Added cheap-baseline columns and V3 reports without modifying V2 worlds or
  historical runs.

## 2026-11-12 — G0 real-API preflight hardening

- Added `src/mini_science/authorization.py` and `authorize-real` /
  `advance-real-stage`; only an explicit operator confirmation can create or
  advance a real-provider authorization manifest.
- Added `src/mini_science/budget_plan.py` to calculate the actual public prompt
  shapes and conservative output caps for G1, G2, and the five-request W001
  A/B/C/D plan.
- Added an exclusive file lock around persistent gate reserve/finish/update,
  preserved atomic JSON replacement, and made CLI run caps unable to expand
  the permanent authorization caps.
- Added non-secret G1/G2/G3 report writers and redaction at JSON/JSONL audit
  boundaries; failed/unknown billing remains explicitly unverified.
- G0 result: 46 offline tests passed; no authorization manifest, gate state, or
  real API request was created.
