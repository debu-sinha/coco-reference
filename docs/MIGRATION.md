# Migrating an existing agent into the CoCo pattern

You already have an agent. Maybe it's running on Claude Code with the Databricks MCP, maybe it's a Python service calling OpenAI, maybe it's a LangGraph DAG. Before you deploy CoCo, decide whether to adopt the whole pattern or borrow pieces. This doc tells you how.

## When to adopt the whole pattern

Do all of it when two or more of these are true:

1. You need PHI-adjacent prompt data to live inside your UC governance boundary, not in an external provider's logs.
2. Your compliance team wants a SQL-queryable audit trail of "who asked what, got what response, ran what SQL, when."
3. You want to expose the agent to users who do not have a Databricks CLI PAT (medical directors, account managers, partners).
4. You want to swap LLM providers, add tools, or change prompts without redeploying the agent.

If none of those apply, keep Claude Code + Databricks MCP for your four developers. Don't migrate.

## When to borrow pieces

You can cherry-pick pieces of CoCo without taking the whole thing:

- **Just the prompt registry integration:** [`src/coco/agent/prompts/__init__.py`](../src/coco/agent/prompts/__init__.py) is ~150 lines, drop-in for any DSPy agent.
- **Just the SQL guardrails:** [`src/coco/agent/guardrails.py`](../src/coco/agent/guardrails.py) is pure Python, no Databricks dependency beyond the read-only enforcement pattern. Works in front of any SQL executor.
- **Just the preflight probes:** [`scripts/preflight_check.py`](../scripts/preflight_check.py) is standalone. Fork it, rename the probes, point it at your own resources.
- **Just the teardown pattern:** [`notebooks/99_teardown.py`](../notebooks/99_teardown.py) has an idempotent removal pattern for every Databricks resource type. Useful for any per-user Databricks workload.

## Full migration: 5 steps

### Step 1 - Map your tools to DSPy tool functions

CoCo uses `dspy.ReAct(tools=[fn, fn, fn])` ([see responses_agent.py](../src/coco/agent/responses_agent.py)). DSPy introspects each tool function's Python signature and docstring to build the schema the LLM sees. Every tool you have today needs to be a Python function with:

- A typed signature (`def identify_codes(query: str) -> list[dict]:`)
- A docstring describing what it does, when to call it, what it returns
- A pure-Python implementation (sync or async, but the agent invokes sync)

If your existing tools are OpenAI function definitions, the schemas translate one-to-one. The docstring replaces the `description` field.

If your tools are MCP tools you access via Claude Code, reimplement them as Python functions inside the agent codebase. The MCP server goes away in this pattern - the tools run in the agent container.

### Step 2 - Move prompts into MLflow Prompt Registry

Your current prompts are probably markdown files or constants. Migrate them to 3-part UC names:

```python
import mlflow
mlflow.set_registry_uri("databricks-uc")
mlflow.genai.register_prompt(
    name="<catalog>.<schema>.cohort_query",
    template="...your existing system prompt...",
)
mlflow.genai.set_prompt_alias(
    name="<catalog>.<schema>.cohort_query",
    version=1,
    alias="production",
)
```

Do this for every distinct prompt your agent uses. Then change your agent to load them at request time:

```python
p = mlflow.genai.load_prompt("prompts:/<catalog>.<schema>.cohort_query/production")
instructions = p.template
```

Prompts are now editable in the Databricks UI without redeploying your agent.

### Step 3 - Serve via Mosaic AI Agent Framework

Package the agent as a `ResponsesAgent`. The entry point goes in `responses_agent_entry.py` and is passed to `mlflow.pyfunc.log_model(python_model=<path>, ...)` via the models-from-code path. See [`src/coco/agent/deploy.py`](../src/coco/agent/deploy.py) for the full recipe.

The typed resources (`DatabricksSQLWarehouse`, `DatabricksVectorSearchIndex`, `DatabricksServingEndpoint`, `DatabricksTable`) are how the framework grants the serving container scoped auth. Your existing agent probably runs on whatever PAT you put in the env. Stop that - the framework's SP-scoped bindings are a significant security upgrade.

```python
from databricks import agents
agents.deploy(
    model_name="<catalog>.<schema>.<model>",
    model_version=<int>,
    endpoint_name="your-agent",
    environment_vars={
        "CATALOG_NAME": catalog,
        "SCHEMA_NAME": schema,
        "WAREHOUSE_ID": warehouse_id,
    },
)
```

The `environment_vars` pass-through is new-ish. Without it the serving container has none of the config your `${...}` interpolation needs. Pass it explicitly.

### Step 4 - Put Databricks Apps in front of the serving endpoint

If your agent is consumed by a web UI or an API today, replace that layer with a Databricks App. The typed resource bindings (`AppResourceServingEndpoint`, `AppResourceDatabase`, `AppResourceSqlWarehouse`) grant the app's SP scoped access. Auth is `X-Forwarded-Email` - the app sees the signed-in user's identity on every request.

You do not need OBO (`user_api_scopes`). CoCo used to require it and dropped the requirement. Every data access runs as the app's SP. The user identity is used for audit tagging, not for authorization.

### Step 5 - Wire up MLflow experiment + feedback loop

Add `@mlflow.trace` decorators to every tool function and the main agent entry. With `mlflow.dspy.autolog()` on at import, every LM call also gets traced. Set the experiment to a per-user path:

```python
mlflow.set_experiment(f"/Users/{user_email}/your-agent")
```

Collect user feedback somewhere (CoCo uses a Lakebase `feedback` table). Pipe it into `mlflow.genai.optimize_prompts` on a schedule:

```python
result = mlflow.genai.optimize_prompts(
    predict_fn=your_predict_fn,
    train_data=feedback_pairs,
    prompt_uris=["prompts:/<catalog>.<schema>.cohort_query"],
    optimizer=GepaPromptOptimizer(reflection_model="databricks:/<endpoint>"),
    scorers=[Correctness(model="databricks:/<endpoint>")],
)
```

The optimizer registers a new prompt version. Gate promotion to `@production` on whatever quality metric matters to you.

## Pitfalls to avoid

**Don't try to keep your existing PAT-based auth and add the agent endpoint as a second path.** That leaves two auth models in production. Pick one. The CoCo pattern is SP-only.

**Don't migrate the knowledge base shortcut in [`src/coco/knowledge/`](../src/coco/knowledge/).** Those markdown files are demo content. In production, put table knowledge in UC column comments (the `inspect_schema` tool reads them) and clinical rules in a dedicated UC table the clinical team maintains.

**Don't skip the preflight step.** Every permission the setup notebook needs is probed by [`scripts/preflight_check.py`](../scripts/preflight_check.py). Running it saves 20+ minutes of deploy time when something is missing.

**Don't assume the migration is free.** The CoCo pattern takes a week to understand and a week to adopt cleanly. If your current setup works and none of the "when to adopt" conditions apply, stay put.

## What you give up

Moving from Claude Code + MCP to the CoCo pattern costs you:

- **Per-user local context.** Each of your developers has their own Claude Code history, tool state, and conversation memory. CoCo persists threads in Lakebase tied to email identity, but the interaction model is a web UI, not a local terminal.
- **Rapid prompt iteration through a markdown file.** You will edit prompts in the Databricks UI instead. For most teams that's a wash, but if your current loop is "edit prompt.md, run one test, commit," the registry UI is a context switch.
- **Tool flexibility via MCP.** Every tool is Python code in the agent repo now. Adding a tool is a PR, not a config flip.

Know what you're giving up before you commit.

## What you gain

- Governance-grade audit trail (MLflow traces with user_id, thread_id, SQL, every tool call)
- Prompt registry with versioning, aliasing, rollback
- Per-query cost attribution through `system.billing` tagging
- A runtime that serves multiple users concurrently, not one developer at a time
- Scoped SP auth so queries run with least-privilege UC grants, not a developer's PAT
- A deploy + teardown pipeline that stands up and removes everything idempotently

If those matter to you, the migration pays off within a month. If they don't, skip it.
