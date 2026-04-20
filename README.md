# CoCo v2 -- AI Cohort Copilot for Healthcare RWD

CoCo is a natural-language cohort-building assistant for real-world healthcare data. Ask for a cohort ("Type 2 diabetes patients on metformin with recent labs") and CoCo identifies clinical codes, generates and validates SQL against a Databricks warehouse, executes the query, and synthesizes a response with sample rows and clinical context.

This repo is a **turnkey reference implementation**. Clone it, deploy the bundle, run the setup job, and you'll have a working Cohort Copilot in your own Databricks workspace in about 30 minutes. Multiple users can deploy to the same workspace without collisions. Each user gets their own namespaced resources.

## Quick start

### Prerequisites

You'll need these before you start:

- A Databricks workspace with **Unity Catalog** and **Model Serving**
- An **existing serverless SQL warehouse** (the setup job doesn't create one). Find the warehouse ID on the SQL Warehouses page (hex string in the URL). If you don't have one, ask your workspace admin to create a serverless warehouse.
- An **existing Unity Catalog catalog** where you have CREATE SCHEMA permission. The setup job can't create catalogs on Default Storage workspaces. Run the preflight script (below) to find one you can use.
- `databricks-claude-sonnet-4-5` (or equivalent) **FMAPI endpoint** available in your workspace
- **Databricks CLI** installed and a profile configured (`databricks auth login`)
- **Python 3.10+** locally
- **MLflow Managed Prompt Registry** enabled (Preview feature). The agent loads prompt instructions from the registry, and the optimizer writes tuned prompts back. Enable it under **Settings > Preview features > "Managed MLflow Prompt Registry"**.

> **Note on OBO / user authorization:** CoCo does **not** use on-behalf-of user tokens. Every data access is made by the app's service principal. Its permissions come from typed resource bindings (SQL warehouse `CAN_USE`, agent endpoint `CAN_QUERY`, Lakebase `CAN_CONNECT_AND_CREATE`). Earlier versions required the Apps OBO preview feature. The current version does not. The app deploys cleanly on workspaces without that flag enabled.
- Permissions listed in [`docs/PERMISSIONS.md`](docs/PERMISSIONS.md)

Optional (the setup job creates these if you have permission):
- Lakebase instance (for chat session persistence)
- Vector Search endpoint (for clinical knowledge RAG)

### Step 0: Preflight check (MANDATORY — every deployer runs this)

**Who runs it:** every person who will deploy CoCo — workshop attendees, platform team, facilitators. Run it against **your own** CLI profile so it probes **your** permissions. Admin-only preflights are not enough. The setup job runs as the deployer's identity, so the deployer is the only one whose permissions matter.

**When to run it:** after you have the CLI profile configured (`databricks auth login`) and before any `databricks bundle` command. It takes about 60 seconds.

```bash
python scripts/preflight_check.py \
  -p PROFILE \
  --warehouse-id WH_ID \
  --catalog CATALOG \
  --unique-id YOUR_ID
```

The script actively exercises the permissions (not just lists APIs). It probes:
- authentication + warehouse access + Claude endpoint
- **`CAN_QUERY` on the Claude endpoint** (1-token smoke test)
- **`CREATE SCHEMA` on your catalog** (creates + drops a probe schema)
- **MLflow Managed Prompt Registry preview flag** (registers + deletes a probe prompt)
- **`config/default.yaml` `llm.endpoint` matches what is actually deployed** (catches the 4-5 vs 4-6 mismatch)
- Lakebase, Vector Search, Databricks Apps API reachability
- Existing coco resources that would collide with your unique_id

**What to do based on the result:**

| Summary line | What to do |
|---|---|
| `Results: N passed, 0 failed, 0 warnings` | proceed to Step 1 below |
| `... 0 failed, 1+ warnings` | read each WARN line. Most are handled gracefully by setup, but verify before running a 25-minute job |
| `... 1+ failed` | **stop.** Each FAIL line has a specific fix hint. If it is a permission issue, send `docs/PERMISSIONS.md` to your admin and re-run preflight after the grant |

If **no catalog** passes the CREATE SCHEMA probe:
- **Ask your workspace admin** to grant: `GRANT USE CATALOG, CREATE SCHEMA ON CATALOG <catalog> TO \`<your-email>\``
- **Or** create a catalog you own: UI → Catalog → + → Create a new catalog (not available on all workspaces — Default Storage workspaces block this for non-admins)

### Deploy in 3 commands

```bash
# 1. Clone
git clone https://github.com/debu-sinha/coco-reference.git
cd coco-reference

# 2. Deploy the bundle
#    YOUR_ID   = your initials or short name (namespaces all resources)
#    WH_ID     = your serverless SQL warehouse id (hex string)
#    CATALOG   = Unity Catalog name you have CREATE SCHEMA access on
#    PROFILE   = your Databricks CLI profile name
databricks bundle deploy -t demo -p PROFILE \
  --var unique_id=YOUR_ID \
  --var warehouse_id=WH_ID \
  --var catalog=CATALOG

# 3. Run the setup job (provisions everything: ~25-40 min)
databricks bundle run setup_workspace -t demo -p PROFILE \
  --var unique_id=YOUR_ID \
  --var warehouse_id=WH_ID \
  --var catalog=CATALOG
```

When the job finishes, it'll print the app URL. Open it in a browser, create a thread, and ask a cohort question.

### What the setup job provisions

All resources are namespaced by `unique_id` so multiple users can deploy to the same workspace:

| Resource | Name pattern | What it does |
|----------|-------------|-------------|
| UC Schema | `cohort_builder_<id>` | Tables, volumes, model |
| Delta tables | `patients`, `diagnoses`, `prescriptions`, `procedures`, `claims`, `suppliers` | 10k synthetic patients with clinically realistic correlations |
| Vector Search endpoint | `coco-vs-<id>` | Clinical knowledge RAG |
| Vector Search index | `coco_knowledge_idx` | Hybrid BM25 + BGE embeddings on clinical docs |
| Lakebase instance | `coco-lb-<id>` | Managed Postgres for chat sessions |
| Lakebase database | `coco` | Threads, messages, runs, feedback tables |
| MLflow Prompt Registry | `<catalog>.cohort_builder_<id>.{cohort_query,clinical_codes,sql_generator,response_synthesizer}` | UC-qualified 3-part names. Versioned prompt instructions for DSPy signatures |
| Model Serving endpoint | `coco-agent-<id>` | The dspy.ReAct agent with native tool calling |
| UC registered model | `<catalog>.cohort_builder_<id>.coco_agent_<id>` | Versioned agent model in Unity Catalog |
| Databricks App | `coco-<id>` | FastAPI + HTMX chat UI (SP-only auth, no OBO) |
| MLflow experiment | `/Users/<email>/coco-agent` | Per-user. Traces, runs, model artifacts. Falls back to `/Shared/coco-agent` if `COCO_MLFLOW_EXPERIMENT` is not set |

### Multi-user isolation

Two users deploying to the same workspace with different `unique_id` values get completely separate resources:

```bash
# User A (initials: al)
databricks bundle deploy -t demo -p PROFILE --var unique_id=al --var warehouse_id=WH_ID --var catalog=my_catalog

# User B (initials: mj)
databricks bundle deploy -t demo -p PROFILE --var unique_id=mj --var warehouse_id=WH_ID --var catalog=my_catalog
```

User A gets `coco-agent-al`, `coco-al` app, `cohort_builder_al` schema. User B gets `coco-agent-mj`, `coco-mj` app, `cohort_builder_mj` schema. Zero collisions. This works through the entire pipeline including agent deployment, model registration, and app creation.

### Teardown

To tear down everything your user created (app, serving endpoint, Lakebase instance, UC schema with tables and volumes, prompts, registered model, per-user MLflow experiment):

```bash
databricks bundle run teardown_workspace -t demo -p PROFILE \
  --var unique_id=YOUR_ID \
  --var catalog=CATALOG
```

Shared resources stay intact by default. The teardown never drops the UC catalog or the shared Vector Search endpoint unless you explicitly pass `--var delete_catalog=YES` or `--var delete_vs_endpoint=YES`. Two users running teardown at the same time touch disjoint namespaced resources and cannot interfere with each other. The script is idempotent, so a partial teardown is safe to re-run.

### Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `Only serverless compute is supported` | Workspace is serverless-only | Already handled (jobs use serverless environments) |
| `Metastore storage root URL doesn't exist` | Default Storage workspace | Pass `--var catalog=<existing>` with a catalog you already have access to |
| `Cannot create Lakebase instance` | No Lakebase permission | Ask admin to create the instance, then pass `--var lakebase_instance=<name>`. CU_1 is plenty. |
| `token passthrough feature is not enabled` | Apps OBO not turned on | Workspace admin: Settings > Preview features > enable "User authorization for Databricks Apps" |
| `typing_extensions` / `deprecated` import error | Serverless sys.path issue | Already handled in the notebook. If you see it, redeploy the bundle to pick up the fix. |
| `cannot import name 'agents' from 'databricks'` | Serverless namespace collision | Already handled. The post-restart cell extends `databricks.__path__`. |
| `AiGatewayConfig` import error | Old system databricks-sdk | Already handled. The sys.path fix prioritizes pip-installed packages. |
| `Bad model name: please specify all three levels` | Config env vars not set | Already handled. Notebook sets `COCO_*` env vars from widget values before deploy. |
| Agent returns empty results | Config missing warehouse_id | The deploy resolves config at log_model time. Re-deploy the agent. |

For the full permissions checklist, see [`docs/PERMISSIONS.md`](docs/PERMISSIONS.md).

## Architecture

```
User question
  |
  v
Databricks App (FastAPI + HTMX + SSE)
  |
  v
Lakebase -----> Thread/message persistence + feedback
  |
  v
Model Serving (dspy.ReAct agent)
  |
  +---> Claude Sonnet 4.5 (FMAPI) -----> Plan + synthesize
  +---> SQL Warehouse -----> Execute cohort queries
  +---> Vector Search -----> Clinical knowledge RAG
  +---> MLflow Prompt Registry -----> Dynamic prompt instructions
  +---> MLflow -----> Trace every tool call + user attribution
```

The agent uses `dspy.ReAct` with native tool calling. Claude decides which tools to call (inspect_schema, identify_clinical_codes, generate_sql, execute_sql, retrieve_knowledge) based on tool definitions derived from Python function docstrings. No keyword-matched planner, no separate planning prompt. The model IS the planner. Every tool call is decorated with `@mlflow.trace` for full observability.

For the detailed architecture writeup with gotchas and code pointers, see [`docs/design/apps-mosaic-ai-agent-reference.md`](docs/design/apps-mosaic-ai-agent-reference.md).

## Prompt management and optimization

CoCo uses **MLflow Prompt Registry** for all DSPy signature instructions. The setup notebook registers 4 default prompts under 3-part UC names: `<catalog>.cohort_builder_<id>.{cohort_query,clinical_codes,sql_generator,response_synthesizer}`. The agent loads them at runtime via the `@production` alias, so you can update prompts without redeploying.

**The automatic optimization loop:**

```
User asks a cohort question
  -> Agent answers (prompt loaded from MLflow Prompt Registry at @production)
  -> User clicks thumbs up or thumbs down (stored in Lakebase)
  -> Weekly job (notebooks/03_optimize_dspy.py) queries thumbs-up pairs
  -> mlflow.genai.optimize_prompts with GepaPromptOptimizer runs evolutionary
     search over instruction variations against a Correctness scorer
  -> New prompt version registered, production alias flipped to it
  -> Agent picks up the new prompt on the next request (no redeploy)
```

To enable auto-optimization: collect 2+ thumbs-up interactions (the workshop-demo default) or 10+ for production use, then unpause the `CoCo DSPy Optimization` job in the Workflows UI. It runs weekly on Sunday at 2am UTC. Override `min_examples` via the job widget for production.

**Always gate promotions on evaluation.** GEPA can overfit on small feedback samples and regress on held-out scenarios. The recommended flow is: run the optimize job, run the eval job against the new version, compare metrics against the baseline, and only keep the `@production` alias on the new version if metrics improved. To roll back, call `mlflow.genai.set_prompt_alias(name=..., version=<prev>, alias="production")`. The alias flip takes effect on the next request, no redeploy.

To manually edit a prompt: go to the MLflow Prompt Registry in the Databricks UI, find `<catalog>.cohort_builder_<id>.cohort_query`, and create a new version with the `production` alias.

## Running tests locally

```bash
python -m venv .venv
source .venv/activate
pip install -e ".[dev]"

pytest -m unit                  # fast, no external deps (~65 tests)
pytest -m integration           # mocked Databricks services
ruff check src tests
ruff format src tests
```

## Running the app locally (mocked backend)

```bash
export COCO_CONFIG_PATH=config/default.yaml
export DATABRICKS_HOST=https://example.cloud.databricks.com
export COCO_WAREHOUSE_ID=your_warehouse_id
export COCO_CATALOG_NAME=coco_demo
export COCO_SCHEMA_NAME=cohort_builder
export COCO_AGENT_ENDPOINT_NAME=coco-agent
cd src/coco/app && uvicorn main:app --reload
```

The app should come up at `http://localhost:8000`. SSE streaming won't work without a deployed agent endpoint (`COCO_AGENT_ENDPOINT_URL`).

## Configuration

`config/default.yaml` is the single config file. Environment variables are interpolated via `${VAR}` tokens. Key env vars:

| Env var | What it does | Set by |
|---------|-------------|--------|
| `DATABRICKS_HOST` | Workspace URL | Auto-injected in Databricks Apps |
| `COCO_WAREHOUSE_ID` | SQL warehouse for queries | App resource binding |
| `COCO_AGENT_ENDPOINT_URL` | Agent serving endpoint URL | App resource binding |
| `COCO_AGENT_ENDPOINT_NAME` | Agent serving endpoint name | Setup notebook widget |
| `COCO_CATALOG_NAME` | Unity Catalog name | App env var / notebook widget |
| `COCO_SCHEMA_NAME` | Schema name | App env var / notebook widget |
| `COCO_LAKEBASE_INSTANCE` | Lakebase instance name | Setup notebook widget |

## Key docs

| Doc | What it covers |
|-----|---------------|
| [`docs/PERMISSIONS.md`](docs/PERMISSIONS.md) | Every permission needed for end-to-end deploy |
| [`docs/design/apps-mosaic-ai-agent-reference.md`](docs/design/apps-mosaic-ai-agent-reference.md) | Full architecture with gotchas (Lakebase, token rotation, code_paths, planner) |
| [`docs/examples/`](docs/examples/) | Working Python snippets for calling FMAPI from DSPy |
| [`docs/cost-attribution/`](docs/cost-attribution/) | Cost tracking queries, tagging policy, warehouse setup template |
| [`docs/WORKSHOP_PREREQS.md`](docs/WORKSHOP_PREREQS.md) | Workshop-specific prerequisites checklist |

## Knowledge base: demo vs production

The markdown files in `src/coco/knowledge/` are the **demo knowledge base** that get chunked, embedded, and indexed in Vector Search during setup. The agent's `retrieve_knowledge` tool queries this index.

**This is a demo shortcut, not production practice.** In production:

| Concern | Demo approach | Production approach |
|---------|--------------|-------------------|
| **Schema knowledge** | Hand-written markdown per table | Auto-generate from UC column comments on a schedule |
| **Clinical rules** | Prose in `clinical_rules.md` | A `clinical_reference` table in UC that the clinical team maintains |
| **Unstructured docs** | Static files in git | DLT pipeline from source systems, Delta table with CDC, auto-syncing VS index |
| **Multi-domain** | One set of files for one schema | Each domain gets its own UC schema + VS index |

**The right long-term pattern:**

1. **Put knowledge in UC column comments**, not separate files:
   ```sql
   COMMENT ON COLUMN diagnoses.icd10_code IS 'ICD-10-CM code. E11.* = Type 2 diabetes.';
   ```
   The agent's `inspect_schema` tool already reads column metadata.

2. **Use a reference table for clinical rules**, not markdown:
   ```sql
   CREATE TABLE clinical_reference (
       condition STRING, icd10_pattern STRING, first_line_drugs ARRAY<STRING>,
       source STRING, last_reviewed DATE, reviewed_by STRING
   );
   ```

3. **Use a managed VS pipeline for unstructured docs:**
   ```
   Source docs (PDFs, wikis) -> DLT pipeline -> Delta table (CDC) -> auto-syncing VS index
   ```

## Extending CoCo

After the initial deploy, Claude Code is the recommended path for day-2 changes. Extension points:

- **Tools**: add a function to `src/coco/agent/responses_agent.py` and pass it to `dspy.ReAct(tools=[...])`
- **Prompts**: edit in MLflow Prompt Registry UI (no redeploy needed) or update defaults in `src/coco/agent/prompts/__init__.py`
- **DSPy signatures**: edit `src/coco/agent/signatures.py` for field changes, run `notebooks/03_optimize_dspy.py` for GEPA instruction tuning against thumbs-up feedback
- **Guardrails**: add schemas to `config.guardrails.allowed_schemas` in `config/default.yaml`
- **UI**: edit templates in `src/coco/app/templates/`, CSS in `src/coco/app/static/styles.css`
- **Cost tracking**: customize queries in `docs/cost-attribution/queries/`

## Repo structure

```
coco-reference/
  app.yaml                     Databricks App manifest
  databricks.yml               DABs bundle definition (jobs, variables, targets)
  config/default.yaml          Runtime config (env var interpolated)
  requirements.txt             App container pip deps
  pyproject.toml               Package metadata + dev deps
  scripts/
    preflight_check.py         Pre-deploy workspace permission checker
  src/coco/
    agent/                     The dspy.ReAct agent + tools + deploy
      prompts/                 MLflow Prompt Registry integration + defaults
      signatures.py            DSPy signature definitions (typed I/O contracts)
      responses_agent.py       Main agent: ReAct loop, tool functions
      deploy.py                Model logging, UC registration, endpoint deploy
      guardrails.py            SQL validation (read-only, schema allowlist)
      tools/                   Tool implementations (SQL, VS, schema, codes)
    app/                       FastAPI + HTMX + SSE chat UI
      sessions/                Lakebase CRUD (threads, messages, feedback)
    config.py                  Config loader
    gateway/                   LLM gateway client
    sql/                       Statement Execution API client
    data_generator/            Synthetic patient data generator
    knowledge/                 Clinical knowledge markdown docs (demo)
  notebooks/
    00_setup_workspace.py      Full provisioning notebook (auto-namespaces per user)
    02_evaluate.py             Scenario-based evaluation against the live agent endpoint
    03_optimize_dspy.py        GEPA prompt optimization from Lakebase thumbs-up feedback
    99_teardown.py             Removes every resource the setup created, per-user namespace
  docs/
    PERMISSIONS.md             Required permissions
    design/                    Architecture reference doc
    examples/                  FMAPI + DSPy snippets
    cost-attribution/          Cost tracking queries + policy
  tests/                       Unit + integration tests
```
