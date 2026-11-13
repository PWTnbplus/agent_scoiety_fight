# V3 real pilot protocol

This document defines the staged protocol for a future authorized Kimi2.6
micro-pilot. This V3 implementation performs only Gate 1-A/1-B offline work;
`REAL_API_NOT_RUN` remains the default.

Order:

1. API contract: one provider request, exact JSON `{"status":"ok"}`, model
   identity and usage status checked.
2. Role probes: two independent one-call probes on W001, one question designer
   and one pattern extractor.
3. W001 A/B/C/D: five unique provider calls; C/D share one stage1 call.
4. Four-world A/B/C/D: twenty unique calls only after the preceding gate and a
   new explicit authorization.

Every real call must satisfy both `--allow-paid-api` and the persistent V3 gate
authorization. The gate counts attempts before transport; timeouts and unknown
billing remain charged attempts for local safety accounting. No automatic
retry is permitted. API keys are read only by the existing Kimi adapter and are
never placed in plans, ledgers, events or reports.

Before any paid request, an operator must create an explicit local
authorization manifest. Codex must not create this record without the user's
confirmation:

```powershell
python -m mini_science.cli authorize-real `
  --config config/real_gate_v3.json `
  --approved-by user_explicit `
  --provider kimi26 `
  --model kimi-k2.6 `
  --scope check-api,probe-role,pilot `
  --worlds W001 `
  --conditions A_TARGET_ONLY,B_SINGLE_RELATED,C_SEQ2_TRANSFER,D_SEQ2_BLOCK `
  --max-calls 8 `
  --max-estimated-cost-usd 0.10 `
  --confirmation V3_REAL_API_AUTHORIZED `
  --authorization-note "user-approved staged V3 engineering pilot"
```

After each successful gate, advance the same authorization explicitly with
`advance-real-stage`; this cannot increase the approved scope, call cap, or
cost cap. The JSON gate uses a create-exclusive lock and atomic replacement so
two processes cannot reserve the same remaining allowance.

The four worlds contain two law families and are exploratory development data.
They cannot support a general mechanism or significance claim.
