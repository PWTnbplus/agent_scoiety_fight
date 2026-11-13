# Kimi K2.6 API provenance and protocol comparison

This document records the read-only source audit used for the V5-P5 offline
preflight. It contains no API key, bearer value, response body, or private
credential content.

## Source locations inspected

- Existing project: `E:\master_exp\nature_prj1_cal\from_llm_to_agent`
- Current standalone adapter: `src/mini_science/adapters/kimi26.py`
- Current provider protocol: `src/mini_science/adapters/base.py`
- Existing project's model matrix: `configs/ctflow_model_matrix.json`
- Existing project's generic provider: `src/scientific_discovery/models/provider.py`
- Existing project's legacy multiprovider helper: `third_party/NewtonBench/utils/call_llm_api.py`
- Existing project's integration notes: `CTFLOW_INTEGRATION_SETUP.md`

The key-file check is existence/readability-only. The file content is never
read into an audit log, copied into this repository, or emitted to chat.

## Frozen Kimi protocol used by this project

The current `Kimi26Adapter` implements the following explicit contract:

- model ID: `kimi-k2.6`
- base URL: `https://token.ctflow.cn/v1`
- endpoint: `/chat/completions`
- key source: `KIMI26_KEY_FILE`, or the existing project's
  `api_key/kimi/kimi-k2.6.txt` relative to the configured source project
- request fields: `model`, `messages`, `max_tokens`, `temperature`, `stream:false`
- authentication: in-memory `Authorization: Bearer ...`; the value is excluded
  from traces and logs
- default timeout: 180 seconds
- redirects: blocked so credentials cannot be forwarded to a new host
- transport retries: zero; a failed request is not automatically repeated
- response contract: `choices[0].message.content`, optional response `model`,
  and `usage.prompt_tokens` / `usage.completion_tokens`
- identity check: a returned model, when present, must equal `kimi-k2.6`
- cost accounting: provider-reported `usage.cost_usd` when present, otherwise
  the frozen local input/output rate estimate; a local hard cap is checked
  before and after the request
- failures: bounded/redacted HTTP diagnostics and classified transport,
  timeout, and response-parse errors

## Comparison with the existing project's implementation

`configs/ctflow_model_matrix.json` confirms the Kimi group contains the exact
`kimi-k2.6` model ID and uses the CTFlow base URL above. The legacy
`call_llm_api.py` is a general multi-provider helper: it selects OpenAI or
OpenRouter from environment keys and its mapping does not itself provide the
Kimi-specific CTFlow path. It also has broad response-repair fallbacks and
uses completion-token estimates when usage is missing.

The existing project's `src/scientific_discovery/models/provider.py` is the
closest generic OpenAI-compatible implementation. It posts to
`{base_url}/chat/completions`, sends `model`, `messages`, and `max_tokens`,
uses a bearer header, parses `choices[0].message.content` plus prompt and
completion usage, and supports configurable retries and a cost ledger.

The current adapter retains those verified wire-level elements while making
the V5-P5 requirements explicit and stricter: Kimi model identity is frozen,
the key path is explicit, `stream:false` is sent, redirects are blocked,
retry count is fixed at zero, all traces redact the credential, and the
pre-request cost cap is enforced before any HTTP dispatch. This is a
standalone implementation copied into the current project; the current
project does not import or call the old project at runtime.

## Evidence boundary

This provenance document is an engineering record, not evidence that the
provider is reachable or that billing is verified. V5-P5 offline preflight
does not send a network request. Any future live result must record returned
model identity, response shape, provider usage, local estimate, and billing
verification separately.
