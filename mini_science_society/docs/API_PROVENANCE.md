# API provenance

## Kimi K2.6 migration

The Kimi2.6 path is implemented locally in
`src/mini_science/adapters/kimi26.py`; it does not import the old repository.
The implementation was copied from an audit of the following old-project
sources:

| Field | Value |
|---|---|
| source model matrix | `E:\\master_exp\\nature_prj1_cal\\from_llm_to_agent\\configs\\ctflow_model_matrix.json` |
| source runner | `E:\\master_exp\\nature_prj1_cal\\from_llm_to_agent\\scripts\\run_external_vluq_agent_on_newtonbench.py` |
| source provider contract | `E:\\master_exp\\nature_prj1_cal\\from_llm_to_agent\\src\\scientific_discovery\\models\\provider.py` and `external_vluq_provider.py` |
| model id | `kimi-k2.6` |
| base URL | `https://token.ctflow.cn/v1` |
| endpoint | `POST /chat/completions` |
| authentication | `Authorization: Bearer <key>` |
| default key file | `api_key/kimi/kimi-k2.6.txt` under the configured source project |
| request settings | `temperature=0.6`, `stream=false`, `max_tokens<=1200` |
| transport policy | HTTPS only, redirects blocked, zero retries |
| local accounting | `$0.00095/1K` input, `$0.004/1K` output, hard cap before request |
| secret values copied | false |

The old external VLUQ adapter depended on another project at runtime. This
project instead contains a standalone standard-library `urllib` adapter that
preserves the audited wire contract and records request/response metadata,
usage provenance, model identity, latency, and local cost estimates. It does
not copy the key file, `.env`, or private traces.

## Source audit

| Field | Value |
|---|---|
| `api_source_project` | `E:\\master_exp\\nature_prj1_cal\\from_llm_to_agent` |
| `source_client_file` | `src/scientific_discovery/models/provider.py` |
| `source_function` | `OpenAICompatibleProvider.__init__`; `OpenAICompatibleProvider.complete` |
| `new_adapter_file` | `src/mini_science/adapters/existing_project.py` (generic provider); `src/mini_science/adapters/kimi26.py` (Kimi2.6) |
| `copied_strategy` | function extraction with an auditable adapter wrapper |
| `preserved_settings` | OpenAI-compatible `/chat/completions`, JSON messages, `max_tokens`, Bearer header, timeout, retry count, model and usage fields |
| `credential_env_names` | `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT`, `LLM_MAX_RETRIES`, `LLM_COST_PER_1K_INPUT_TOKENS`, `LLM_COST_PER_1K_OUTPUT_TOKENS`, `LLM_MAX_COST_USD` |
| `secret_values_copied` | false |
| `api_check_status` | SKIPPED: no paid request authorized in this run |

## What was retained

The source project uses Python standard-library `urllib`, posts to
`{base_url}/chat/completions`, sends `model`, `messages`, and `max_tokens`, and
reads `choices[0].message.content` plus `usage.prompt_tokens` and
`usage.completion_tokens`. Its safe default is zero transport retries; retries
are explicit because a retry can create another billable request. The adapter
keeps those semantics and records attempt, latency, model, response ID, usage,
and estimated cost without recording credentials.

The source project also contains `scripts/ctflow_models.py`. That file is a
model-catalog/preflight helper and explicitly labels its chat request as
`PROVISIONAL`; it was used only as corroborating audit context, not copied as
the primary provider implementation.

## Deliberate differences

- The new adapter accepts `max_output_tokens` per call so each Society role can
  use the frozen budget while still sending the same `max_tokens` field.
- The adapter refuses network access unless constructed with
  `allow_paid_api=True`; the CLI additionally requires `--allow-paid-api`.
- The new project does not import the old repository at runtime, so its source
  tree remains unchanged and no private files are copied.
- The new adapter requires positive input/output token price configuration before
  a real request, preserving the old project's fail-closed cost gate. Provider
  billing is still marked unverified unless the provider returns a billable
  receipt.

No `.env`, key, cookie, authorization value, or private trace was copied.
