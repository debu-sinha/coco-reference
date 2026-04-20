# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

CoCo v2 is a natural-language Cohort Copilot for healthcare real-world data. A user asks for a cohort ("Type 2 diabetes patients on metformin with recent labs"), and the agent identifies clinical codes, generates and validates SQL, executes it on Databricks, then synthesizes a response. The codebase is a Databricks-native app: FastAPI UI, DSPy-orchestrated agent, Mosaic AI Gateway LLM calls, Lakebase session store, Unity Catalog data, and Databricks Vector Search for clinical RAG.

## Common commands

```bash
# Install (dev extras include pytest, ruff, mypy)
pip install -e ".[dev]"

# Required env vars for local runs
export COCO_CONFIG_PATH=config/default.yaml
export DATABRICKS_HOST=https://<workspace>.cloud.databricks.com
export DATABRICKS_TOKEN=dapi...

# Tests — markers are `unit`, `integration`, `slow` (see pyproject.toml)
pytest                                      # all tests
pytest -m unit                              # fast, no external deps
pytest -m integration                       # mocked Databricks services
pytest tests/unit/test_config.py -v         # single file
pytest tests/unit/test_guardrails.py::test_read_only -v  # single test

# Lint / type-check
ruff check src tests
ruff format src tests
mypy src

# Run FastAPI app locally (backend calls are mocked)
cd src/coco/app && uvicorn main:app --reload    # http://localhost:8000

# Evaluation — run notebook 02 against the live agent via mlflow.genai.evaluate
# Scenarios live in evaluation/scenarios.yaml. Trigger the Databricks job:
databricks bundle run run_evaluation -t demo -p feai \
    --var catalog=... --var schema=... --var warehouse_id=... --var agent_endpoint=...

# Databricks Asset Bundles — always use profile `feai`
databricks bundle deploy -t demo -p feai    # demo | dev | staging | prod
databricks bundle validate -t prod -p feai
```

First-time workspace provisioning is done by running `notebooks/00_setup_workspace.py` as a Databricks job (creates UC catalog/schema/volumes, generates 10k synthetic patients, builds Vector Search index, deploys Model Serving endpoint, initializes Lakebase). The setup writes a `setup_complete.json` with resource URLs.

## Architecture

### Request flow
User message → `src/coco/app/routes/` (FastAPI) → `CocoAgent.predict_stream()` in `src/coco/agent/responses_agent.py` → planner LLM picks a tool → tool executes → repeat → synthesizer LLM emits final response. The app streams events over SSE as `tool_call` → `tool_result` → `assistant`. Session state (threads/messages/runs/feedback) is persisted to Lakebase so conversations survive restarts.

### Agent orchestration (`src/coco/agent/`)
- `responses_agent.py` — `CocoAgent` runs a fixed-iteration loop (`max_turns=10`). Each turn: `_plan_next_action` calls the Gateway LLM to choose a tool by keyword-matching the response, `_execute_tool` dispatches to the async tool function, and when the planner says `respond` it calls `_synthesize_response`. MLflow spans wrap `agent_turn`, `plan_action`, `tool_<name>`, and `synthesize_response`. `mlflow.dspy.autolog()` is enabled at import time.
- `signatures.py` — DSPy signatures: `ClinicalCodeSignature`, `SQLGeneratorSignature`, `ResponseSynthesizerSignature`. These are the optimization target for `notebooks/03_optimize_dspy.py` (MIPROv2 over thumbs-up feedback), and optimized artifacts land in the `coco_artifacts` UC volume.
- `guardrails.py` — `validate_sql_query(sql)` enforces read-only (no INSERT/UPDATE/DELETE/DDL) and a schema allowlist (default `coco_demo.cohort_builder`). Every SQL must pass this before `execute_sql` runs. Do not bypass — the Gateway-level PHI filters are the second layer, not the first.
- `tools/` — `clinical_codes.py`, `sql_generator.py`, `sql_executor.py`, `knowledge_rag.py`, `schema_inspector.py`. All tools are async and return Pydantic models from `agent/models.py`. The planner keyword-matches on tool names, so renaming a tool function requires updating `_plan_next_action` as well.
- `prompts/` + MLflow Prompt Registry — prompts are loaded via `load_prompt(name)` and pinned to MLflow registry names defined under `mlflow.prompt_registry` in `config/default.yaml`. Change the prompt text in both places.

### Platform integrations
- **LLM** — `src/coco/gateway/client.py` calls `databricks-claude-sonnet-4-5` through the `coco-llm` Mosaic AI Gateway route (rate-limit aware, SSE streaming, 60s timeout). Never call the model endpoint directly. The Gateway route is where safety filters and usage tags live.
- **SQL execution** — `src/coco/sql/statement_client.py` wraps the Databricks Statement Execution API. Large results come back as Arrow streams or presigned URLs (`arrow_utils.py`). Warehouse id comes from `COCO_WAREHOUSE_ID`.
- **Lakebase sessions** — `src/coco/app/sessions/{threads,messages,runs,feedback}.py` use a psycopg connection pool. Every query filters by `user_id` from `X-User-ID` (see `app/auth.py`). User isolation is a hard requirement, so don't add queries that skip the filter.
- **Vector Search** — `src/coco/knowledge/indexer.py` builds the `coco_knowledge_idx` hybrid (BM25 + BGE embedding) index for the RAG tool.
- **Observability** — `src/coco/observability/scorers.py` defines MLflow scorers used by `notebooks/02_evaluate.py`. Feedback flows Lakebase → MLflow → weekly optimizer notebook.

### Config
`src/coco/config.py::get_config()` reads YAML at `$COCO_CONFIG_PATH` (default `config/default.yaml`), interpolates `${ENV_VAR}` tokens, and caches the result in a module-level singleton. All runtime settings — catalog/schema names, warehouse id, LLM endpoint, Lakebase pool, guardrails allowlist, Vector Search index, agent endpoint sizing — go through `CocoConfig` dataclasses. When adding a setting, update the YAML, the matching dataclass, and the build in `get_config`.

### Deployment (`databricks.yml`)
One bundle, four targets (`demo`, `dev`, `staging`, `prod`). `prod` switches jobs to the `coco-service-principal` run-as. Resources declared: the `coco_app` Databricks App (launches `uvicorn coco.app.main:app`), and three jobs — `setup_workspace` (manual), `run_evaluation` (weekly, Sunday 02:00 UTC), `optimize_dspy` (weekly, Sunday 02:00 UTC). Notebook parameters are populated from top-level `variables:`.

## Conventions

- Python 3.11+, ruff line length 100, type hints on public functions.
- Tests are marker-gated. Keep new tests mocked by default and mark them `unit` or `integration`. The Databricks SDK, warehouse, and Lakebase are always mocked in tests — `tests/conftest.py` has the fixtures.
- Tools return Pydantic models with `to_dict()`, and the agent serializes them into the message history as JSON strings. Keep that contract when adding a tool.
- SQL in generated queries must be Databricks SQL and reference only `coco_demo.cohort_builder.*` tables listed in `config.tables`. Anything outside that schema will be rejected by `guardrails.py`.
- Prompts live both in `src/coco/agent/prompts/` and the MLflow Prompt Registry — don't drift them.
