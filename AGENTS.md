# Mini Science Society MVP

This project implements the synthetic, low-cost scientific question-selection
experiment described by the accompanying skill and protocol.

## Non-negotiable rules

- Keep public world data and private truth/oracle data in separate directories.
- Agents receive only `WorldPublicView`; never pass private paths or `World` objects
  into prompt construction.
- Treat the oracle as an independent numerical evaluator. Never expose IG values,
  best actions, or hidden laws to an agent.
- C/D must share the same stage-1 artifact. D must remove its informative fields in
  `router.py`, not merely ask a model to ignore them.
- Mock runs are engineering smoke tests and are not scientific evidence.
- Real network calls require both a real provider (`existing` or `kimi26`) and
  `--allow-paid-api`.
- Never copy `.env`, API keys, cookies, or authentication headers into this project.
- Failed, invalid, and timed-out attempts remain in the audit ledger.
- v2 work is incremental: preserve `config/pilot.json`, old `runs/mock_*`, and
  the original W001-W004 public/private data. New experiments use
  `config/pilot_v2.json` and new run IDs.
- Before any provider call, write a deterministic `run_plan.jsonl` and enforce
  both a unique provider-call ledger and a per-condition full-workflow ledger.
- Evidence permissions are derived from the routed payload actually sent to a
  role. A blocked D route may never cite source evidence it did not receive.
- Behavioral mocks are test fixtures only. Every behavioral/mock report must be
  marked `NON_EVIDENCE`; four worlds/two law families are descriptive only.
- Real API work is `NOT_RUN` until the user explicitly supplies a model,
  total-cost cap, and execution authorization. Do not print keys or auth
  headers; unknown provider billing is `null`, never zero.

## Verification order

```powershell
python -m pytest -q
python -m mini_science.cli generate --config config/pilot.json
python -m mini_science.cli validate-worlds --config config/pilot.json
python -m mini_science.cli smoke --provider mock --world W001
python -m mini_science.cli pilot --provider mock --worlds all --repeats 1
```

Do not interpret the four-world pilot as confirmation of a scientific theory.
