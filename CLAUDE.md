# CLAUDE.md

Guidance for Claude Code when working in this repo.

## Project

CoCo v2 is a natural-language cohort copilot for healthcare real-world
data. A user asks for a cohort ("Type 2 diabetes patients on metformin
with recent labs") and the agent identifies clinical codes, generates
and validates SQL, executes it on a Databricks SQL warehouse, then
synthesizes a response. It's Databricks-native: FastAPI + HTMX + SSE
front-end in Databricks Apps, a `dspy.ReAct` agent served from Mosaic
AI Agent Framework, Lakebase for session state, Unity Catalog for
data + prompts + registered models, and Vector Search for clinical
knowledge RAG.

## Common commands

```bash
# Install (dev extras include pytest, ruff, mypy)
pip install -e ".[dev]"

# Required env vars for local runs
export COCO_CONFIG_PATH=config/default.yaml
export DATABRICKS_HOST=https://<workspace>.cloud.databricks.com
export DATABRICKS_TOKEN=dapi...

# Tests — markers `unit`, `integration`, `slow` (see pyproject.toml)
pytest                                      # all tests
pytest -m unit                              # fast, no external deps
pytest -m integration                       # mocked Databricks services
pytest tests/unit/test_guardrails.py -v     # single file

# Lint / type-check
ruff check src tests
ruff format src tests
mypy src

# Run the FastAPI app locally (no Databricks Apps runtime)
cd src/coco/app && uvicorn main:app --reload    # http://localhost:8000

# Databricks Asset Bundles — pass your own CLI profile
databricks bundle deploy -t demo -p PROFILE \
    --var unique_id=YOUR_ID \
    --var warehouse_id=WH_ID \
    --var catalog=CATALOG
databricks bundle run setup_workspace -t demo -p PROFILE \
    --var unique_id=YOUR_ID \
    --var warehouse_id=WH_ID \
    --var catalog=CATALOG
```

Workspace provisioning runs through `notebooks/00_setup_workspace.py`.
It creates UC schema + volumes, generates 10k synthetic patients,
builds the Vector Search index, provisions Lakebase, registers the
four default prompts (with `@production` aliases), deploys the agent
to Model Serving, and creates the Databricks App. Idempotent. Writes
`setup_complete.json` to the `coco_artifacts` UC volume.

Preflight check before deploy: `python scripts/preflight_check.py`.
It probes `CREATE SCHEMA`, `CAN_QUERY` on the Claude endpoint, and
the Prompt Registry preview flag — the three things that have bitten
first-time deployers.

## Architecture

### Request flow

User message hits the FastAPI app ([`src/coco/app/routes/pages.py`](src/coco/app/routes/pages.py)),
gets persisted to Lakebase as a `messages` row ([`src/coco/app/sessions/messages.py`](src/coco/app/sessions/messages.py)),
then the SSE route ([`src/coco/app/routes/sse.py`](src/coco/app/routes/sse.py))
opens an event stream that POSTs to the agent serving endpoint via
[`agent_client.py`](src/coco/app/agent_client.py). The SSE stream
emits two frame types: `message` (full rendered HTML of the reply,
one frame) and `close`. It doesn't emit per-tool-call events today.

The agent itself is a `dspy.ReAct` with native tool calling. Claude
decides which tool to call by reading tool docstrings — there's no
keyword-matched planner loop. See [`CocoAgent.predict_stream`](src/coco/agent/responses_agent.py#L411)
for the serving entry point. MLflow traces wrap every span via
`@mlflow.trace` on each tool function plus `dspy` autolog.

### Agent orchestration (`src/coco/agent/`)

- [`responses_agent.py`](src/coco/agent/responses_agent.py) — the `CocoAgent`
  class implements `predict` and `predict_stream` per the Mosaic AI
  Responses API contract. Configures `dspy.LM` against the FMAPI
  endpoint from config, builds a `dspy.ReAct(tools=[...])` with the
  tool functions defined in the same file, and runs the conversation.
  Tool results are serialized as JSON in the message history.
- [`signatures.py`](src/coco/agent/signatures.py) — DSPy signatures for the
  sub-steps (`ClinicalCodeSignature`, `SQLGeneratorSignature`,
  `ResponseSynthesizerSignature`). Their instructions come from the
  MLflow Prompt Registry at runtime.
- [`prompts/__init__.py`](src/coco/agent/prompts/__init__.py) — `load_prompt(name)`
  resolves to `<catalog>.<schema>.<name>` via `_registry_name()`,
  loads the `@production` alias, falls back to the bundled DEFAULTS
  when the registry is unreachable. `register_defaults()` registers
  all four prompts and flips the alias — hard-fails on
  `FEATURE_DISABLED` so setup doesn't silently ship without prompts.
- [`guardrails.py`](src/coco/agent/guardrails.py) — `validate_sql_query()`
  strips comments and string literals, rejects DML/DDL keywords
  (DROP, INSERT, UPDATE, DELETE, ALTER, CREATE, TRUNCATE, MERGE,
  REPLACE, GRANT, REVOKE), and enforces the three-part UC allowlist
  from `config.guardrails.allowed_schemas`. Defense in depth — the
  agent SP's UC grants are the primary boundary. Adversarial tests
  live in [`tests/unit/test_guardrails.py`](tests/unit/test_guardrails.py).
- [`tools/`](src/coco/agent/tools) — `schema_inspector`, `clinical_codes`,
  `sql_generator`, `sql_executor`, `knowledge_rag`. All tool functions
  are registered with `dspy.ReAct` by their docstring — renaming a
  function is fine, but change the docstring and you change what the
  LLM thinks the tool does.
- [`deploy.py`](src/coco/agent/deploy.py) — models-from-code deploy via
  `mlflow.pyfunc.log_model` + `databricks.agents.deploy(...)`. Passes
  `environment_vars=COCO_CATALOG_NAME / SCHEMA_NAME / WAREHOUSE_ID`
  into the serving container so the baked config YAML can resolve
  `${...}` tokens at request time.

### Optimization loop

`notebooks/03_optimize_dspy.py` uses [`mlflow.genai.optimize_prompts`](https://docs.databricks.com/aws/en/mlflow3/genai/prompt-registry/optimize-prompts)
with `GepaPromptOptimizer`. Pulls thumbs-up pairs from Lakebase,
registers new prompt versions, flips `@production`. Earlier versions
of this notebook used a hand-rolled MIPROv2 loop. That's gone.
`mlflow.genai.optimize_prompts` is the supported path today.

### Platform integrations

- **LLM** — configured endpoint is `databricks-claude-sonnet-4-6`
  (see [`config/default.yaml`](config/default.yaml#L37)). DSPy's `LM`
  speaks to it directly through the Databricks Foundation Model API.
  The config has a separate `gateway_route` field in case you want
  to front the endpoint with a [Mosaic AI Gateway route](https://docs.databricks.com/aws/en/generative-ai/ai-gateway/index.html)
  for rate limiting and filters — it defaults to the same endpoint
  name, which means no gateway is in front yet.
- **SQL execution** — [`src/coco/sql/`](src/coco/sql) wraps the Databricks
  [Statement Execution API](https://docs.databricks.com/aws/en/sql/api/sql-execution-tutorial).
  Large results come back as Arrow streams or presigned URLs. Warehouse
  id comes from `COCO_WAREHOUSE_ID` (injected by the Apps resource
  binding and baked into the agent artifact at deploy time).
- **Lakebase sessions** — [`src/coco/app/sessions/`](src/coco/app/sessions)
  uses a psycopg async pool. Every query filters by `user_id`, which
  comes from the `X-Forwarded-Email` header set by Databricks Apps.
  Auth lives in [`src/coco/app/auth.py`](src/coco/app/auth.py). User
  isolation is enforced at the SQL layer. Don't add queries that
  skip the user_id filter.
- **Vector Search** — the setup notebook builds a Delta Sync index
  over `knowledge_chunks` in the per-user schema. The agent calls it
  via the `knowledge_rag` tool. See [`src/coco/agent/tools/knowledge_rag.py`](src/coco/agent/tools/knowledge_rag.py).
- **Observability** — [`src/coco/observability/scorers.py`](src/coco/observability/scorers.py)
  defines the four scorers used by `notebooks/02_evaluate.py`. Two
  (`sql_validity_scorer`, `clinical_code_accuracy_scorer`) are code
  scorers. Two (`response_relevance_scorer`, `phi_leak_scorer`) call
  an LLM judge through [`src/coco/gateway/client.py`](src/coco/gateway/client.py).
  The LLM-judge path is sensitive to the runtime's event-loop state
  (uses `asyncio.run`), which can fail in some evaluation contexts —
  the code path ran successfully in fevm2 evaluation but treat it as
  lower-confidence than the code scorers.

### Config

[`src/coco/config.py::get_config()`](src/coco/config.py) reads YAML at
`$COCO_CONFIG_PATH`, interpolates `${ENV_VAR}` and `${VAR:default}`
tokens, caches the result. Runtime settings go through `CocoConfig`
dataclasses. When adding a setting, update the YAML, the matching
dataclass, and the builder in `get_config`. The `llm.experiment_name`
field has no default — if `COCO_MLFLOW_EXPERIMENT` isn't set, MLflow
calls error loudly. That's intentional. It stops traces from silently
landing in `/Shared/coco-agent` when per-user isolation is the goal.

### Deployment (`databricks.yml`)

One bundle, four targets (`demo`, `dev`, `staging`, `prod`). `prod`
switches run-as to `coco-service-principal`. Four jobs:
`setup_workspace` (manual), `run_evaluation` (weekly, paused by
default), `optimize_dspy` (weekly, paused by default),
`teardown_workspace` (manual). Per-attendee resources are namespaced
by `var.unique_id`. The setup notebook also auto-namespaces from the
workspace username if the widget values are left at their generic
defaults.

## Conventions

- Python 3.10+, ruff line length 100, type hints on public functions.
- Tests are marker-gated. Mock Databricks SDK, warehouse, and
  Lakebase — `tests/conftest.py` has the fixtures.
- Tool functions return either plain strings or Pydantic models with
  `.to_dict()`. `dspy.ReAct` serializes whatever they return into the
  message history.
- SQL must be Databricks SQL and reference only the tables in
  `config.tables` under the configured catalog + schema. Anything
  else is rejected by `guardrails.py`.
- Prompts live in `src/coco/agent/prompts/__init__.py` (the bundled
  defaults) AND in the MLflow Prompt Registry (the runtime source of
  truth). `register_defaults()` keeps them in sync on first deploy.
  After that, edit in the Prompt Registry UI — the agent picks up
  alias flips on the next request.
- Any change in the agent's tool definitions or signatures requires
  re-running `deploy_agent()` — those are baked into the model
  artifact. Changes in prompt text or alias do NOT require a redeploy.

## What's tested end-to-end

As of April 2026, the following flows are validated on a fresh
Databricks workspace from a `git clone`:

- `scripts/preflight_check.py` catches missing Prompt Registry flag,
  missing CREATE SCHEMA, and Claude endpoint mismatches
- `bundle deploy` + `bundle run setup_workspace` on a fresh clone
  completes in ~18 minutes
- `bundle run run_evaluation` scores all 19 scenarios, traces land
  in the per-user MLflow experiment
- `bundle run optimize_dspy` runs GEPA to a new prompt version and
  flips the `@production` alias
- `bundle run teardown_workspace` removes every per-user resource
  and leaves shared resources (catalog, optional VS endpoint) intact

Anything not in that list is "implemented but not validated on a
real workspace." When in doubt, check [`scripts/preflight_check.py`](scripts/preflight_check.py)
and the notebook cells for the validated path.
