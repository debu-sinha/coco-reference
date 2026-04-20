# Changelog

## v2.0.0 — 2026-04-19

The first public release.

### What you can expect to work end-to-end

Validated on a fresh Databricks workspace from a `git clone`:

- `scripts/preflight_check.py` probes the real permissions the setup job needs (CREATE SCHEMA, CAN_QUERY on the Claude endpoint, MLflow Prompt Registry preview flag, config/deployed-endpoint match)
- `databricks bundle deploy -t demo` stands up the bundle definitions
- `bundle run setup_workspace` completes in ~18 minutes and provisions UC schema + synthetic data + Vector Search + Lakebase + Prompt Registry + agent endpoint + app
- `bundle run run_evaluation` scores 19 scenarios against the live agent, writes traces to the per-user MLflow experiment
- `bundle run optimize_dspy` runs GEPA through `mlflow.genai.optimize_prompts`, registers a new prompt version, flips `@production`
- `bundle run teardown_workspace` removes every per-user resource and leaves shared resources (catalog, optional VS endpoint) untouched

### Architecture highlights

- `dspy.ReAct` agent with native tool calling on the Foundation Model API (no keyword-matched planner loop)
- Per-user resource isolation across app, agent endpoint, UC schema, Lakebase, Vector Search, MLflow experiment
- Service-principal-only auth using `X-Forwarded-Email`. No OBO / user token passthrough, no JWT decoding.
- MLflow Prompt Registry with `@production` alias for runtime prompt resolution. `register_defaults()` sets aliases on first deploy and hard-fails on `FEATURE_DISABLED`.
- Agent deploy passes `environment_vars` through `databricks.agents.deploy(...)` so the baked config can resolve `COCO_CATALOG_NAME` / `COCO_SCHEMA_NAME` / `COCO_WAREHOUSE_ID` at runtime
- Schema cache at the agent module level, rotated on container restart
- 300-second agent client timeout (up from 120s). Earlier evaluation showed 44% of complex queries timed out at 120s.
- SSE stream persists the agent reply even when the browser disconnects mid-query (`asyncio.shield` around invoke + persist)

### Known limits (see docs/SECURITY.md)

- MLflow traces and Lakebase session rows aren't PHI-redacted
- Row-level access isn't differentiated between app users. The SP executes every query.
- There's no runtime content filter on agent responses. Turn Mosaic AI Gateway safety filters on before deploying against PHI.
- `response_relevance_scorer` and `phi_leak_scorer` call an LLM judge over the Gateway. They're lower-confidence than the code scorers (`sql_validity_scorer`, `clinical_code_accuracy_scorer`).
- Prompt injection through tool docstrings or ambient RAG context isn't mitigated

### Not validated end-to-end in this release

- Blue-green or A/B prompt rollouts mentioned in design docs
- Multi-tenant single-agent variant — the schema cache in `responses_agent.py` is process-wide, so one agent process serves one (catalog, schema) pair
- Inference table population (setup does not enable them)

### Dependency pins

- `mlflow[databricks]>=3.1,<4.0`
- `dspy>=2.5,<3.2`
- `pydantic>=2.7,<2.10`
- `typing-extensions>=4.12`

These pins track API surfaces the repo depends on today. Loosen only after validating against the newer release.
