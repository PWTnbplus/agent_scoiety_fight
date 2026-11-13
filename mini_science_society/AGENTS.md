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
- Real network calls require both `--provider existing` and `--allow-paid-api`.
- Never copy `.env`, API keys, cookies, or authentication headers into this project.
- Failed, invalid, and timed-out attempts remain in the audit ledger.

## Verification order

```powershell
python -m pytest -q
python -m mini_science.cli generate --config config/pilot.json
python -m mini_science.cli validate-worlds --config config/pilot.json
python -m mini_science.cli smoke --provider mock --world W001
python -m mini_science.cli pilot --provider mock --worlds all --repeats 1
```

Do not interpret the four-world pilot as confirmation of a scientific theory.
