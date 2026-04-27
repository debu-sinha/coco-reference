# Databricks notebook source
# MAGIC %md
# MAGIC # CoCo Prompt Optimization
# MAGIC
# MAGIC Uses the Databricks-native `mlflow.genai.optimize_prompts` API with
# MAGIC GEPA (Genetic Evolutionary Prompt Adaptation) and a built-in
# MAGIC `Correctness` scorer. GEPA evolves the registered cohort_query
# MAGIC prompt against thumbs-up feedback pulled from Lakebase and writes
# MAGIC back a new version to the MLflow Prompt Registry.
# MAGIC
# MAGIC This replaced the earlier hand-rolled MIPROv2 loop in this file.
# MAGIC The old pattern worked but was ~4x the code and fought the
# MAGIC serverless runtime's mlflow/protobuf preloads at every step. The
# MAGIC current shape matches the official Databricks tutorial at
# MAGIC docs.databricks.com/aws/en/mlflow3/genai/tutorials/examples/prompt-optimization-quickstart.
# MAGIC
# MAGIC **Schedule:** Weekly (Sunday 2am UTC), paused by default. Unpause
# MAGIC once you have enough thumbs-up feedback (~20+ examples).
# MAGIC
# MAGIC **Compute:** Expects classic compute with mlflow[databricks]>=3.4.
# MAGIC Serverless compute preloads an older mlflow that does not have
# MAGIC optimize_prompts + GepaPromptOptimizer; running this notebook on
# MAGIC serverless will raise ImportError at the imports cell below.

# COMMAND ----------
# MAGIC %pip install --upgrade "mlflow[databricks]>=3.4" "databricks-sdk>=0.65" "psycopg[binary]>=3.2" "pyyaml>=6.0" "typing-extensions>=4.12" "pydantic>=2.7,<2.10" "dspy>=2.5,<3.2"
# MAGIC # dspy is a transitive dep of mlflow.genai.optimize + mlflow.dspy.autolog
# MAGIC # but mlflow[databricks] does NOT pin it, so the runtime's missing-dspy
# MAGIC # surfaces as ModuleNotFoundError on first import. dspy<3.2 matches the
# MAGIC # main package pin (see pyproject.toml) that avoids an incompatible
# MAGIC # breaking change in dspy 3.2's tracer API.
# MAGIC # typing-extensions>=4.12 and pydantic<2.10 pin avoids the
# MAGIC # `cannot import name 'Sentinel' from 'typing_extensions'` crash
# MAGIC # when pydantic_core>=2.23 loads under the serverless runtime's
# MAGIC # preloaded typing_extensions 4.4. Must stay pinned here because
# MAGIC # %pip on classic/serverless takes this list verbatim; it does NOT
# MAGIC # inherit the pyproject.toml constraints.

# COMMAND ----------
# Serverless sys.path fix: %pip above installs typing-extensions>=4.12
# and pydantic<2.10, but the runtime preloads an old
# /databricks/python/lib/python3.10/site-packages/typing_extensions.py
# earlier in sys.path. The old one lacks `deprecated` and `Sentinel`,
# which pydantic_core>=2.23 imports at module load time — so the next
# cell's `import mlflow` (via its pydantic dep chain) crashes.
#
# Move the pip-env dir to the front of sys.path and evict any already-
# imported shadow modules so the fresh versions take effect. Same
# pattern as notebooks/02_evaluate.py.
import os
import subprocess
import sys

_pip_result = subprocess.run(
    [sys.executable, "-m", "pip", "show", "typing-extensions"],
    capture_output=True,
    text=True,
)
for _line in _pip_result.stdout.splitlines():
    if _line.startswith("Location:"):
        _pip_env_loc = _line.split(":", 1)[1].strip()
        if _pip_env_loc in sys.path:
            sys.path.remove(_pip_env_loc)
        sys.path.insert(0, _pip_env_loc)
        break

# Evict preloaded shadow modules so the next `import x` resolves to the
# pip-env copy. mlflow is intentionally omitted because flushing and
# re-importing it triggers protobuf "duplicate file name service.proto"
# errors on serverless.
for _mod in list(sys.modules):
    if _mod.startswith(("typing_extensions", "pydantic", "databricks.sdk", "openai", "litellm")):
        del sys.modules[_mod]
if "databricks" in sys.modules:
    del sys.modules["databricks"]

# COMMAND ----------
import json
from datetime import datetime, timedelta
from uuid import uuid4

import mlflow
import psycopg
from databricks.sdk import WorkspaceClient
from mlflow.genai.judges import make_judge
from mlflow.genai.optimize import GepaPromptOptimizer

# Why mlflow.deployments instead of databricks_openai.DatabricksOpenAI:
# the serverless runtime's preinstalled databricks-openai is 0.0.x and
# doesn't export DatabricksOpenAI (it was added in 0.2). The %pip
# upgrade above should pull a newer one, but pip-env shadowing on
# serverless is unreliable for namespace packages that the runtime
# already has loaded. mlflow.deployments is version-stable across 3.1+,
# uses the notebook's implicit Databricks auth, and does not need a
# separate client class.

# COMMAND ----------
dbutils.widgets.text("catalog", "coco_demo", "Unity Catalog")
dbutils.widgets.text("schema", "cohort_builder", "Schema")
dbutils.widgets.text("lakebase_instance", "", "Lakebase instance name")
# min_examples=2 is a workshop-demo default so a fresh deployment with
# only a couple of thumbs-up can still exercise the full GEPA pipeline
# end-to-end (register prompt -> run optimizer -> write new version ->
# set production alias). Production schedules should override this to
# a realistic value (20+) via the Workflows job widget or
# --var min_examples=... on bundle run.
dbutils.widgets.text("min_examples", "2", "Minimum thumbs-up examples")
dbutils.widgets.text("reflection_model", "databricks-claude-sonnet-4-6", "GEPA reflection model")
dbutils.widgets.text("judge_model", "databricks-claude-sonnet-4-6", "Correctness judge model")
dbutils.widgets.text("chat_model", "databricks-claude-sonnet-4-6", "LLM for predict_fn")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
lakebase_instance = dbutils.widgets.get("lakebase_instance")
min_examples = int(dbutils.widgets.get("min_examples"))
reflection_model = dbutils.widgets.get("reflection_model")
judge_model = dbutils.widgets.get("judge_model")
chat_model = dbutils.widgets.get("chat_model")

os.environ.setdefault("DATABRICKS_HOST", spark.conf.get("spark.databricks.workspaceUrl", "") or "")

# Per-user MLflow experiment. Fails hard if username cannot be
# resolved, matching eval notebook. No /Shared fallback - landing in
# the shared experiment is a workshop-isolation violation.
_user_email = (WorkspaceClient().current_user.me().user_name or "").strip()
if not _user_email:
    raise RuntimeError(
        "Cannot resolve workspace username for per-user MLflow experiment. "
        "Refusing to fall back to /Shared/coco-agent."
    )
_experiment_path = f"/Users/{_user_email}/coco-agent"
mlflow.set_experiment(_experiment_path)
print(f"MLflow experiment (per-user): {_experiment_path}")
mlflow.dspy.autolog(log_compiles=True, log_evals=True, log_traces_from_compile=True)

# COMMAND ----------
# MAGIC %md
# MAGIC ## 1. Pull thumbs-up training pairs from Lakebase

# COMMAND ----------
w = WorkspaceClient()
cred = w.api_client.do(
    "POST",
    "/api/2.0/database/credentials",
    body={"instance_names": [lakebase_instance], "request_id": str(uuid4())},
)
pg_token = cred.get("token", "")
inst = w.api_client.do("GET", f"/api/2.0/database/instances/{lakebase_instance}")
dns = inst.get("read_write_dns")
cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
pg_user = w.current_user.me().user_name

with psycopg.connect(
    f"host={dns} port=5432 dbname=coco user={pg_user} password={pg_token} sslmode=require"
) as conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m_user.content, m_asst.content
            FROM coco_sessions.feedback f
            JOIN coco_sessions.messages m_asst ON f.message_id = m_asst.id
            JOIN coco_sessions.messages m_user ON (
                m_user.thread_id = m_asst.thread_id
                AND m_user.role = 'user'
                AND m_user.created_at < m_asst.created_at
            )
            WHERE f.rating = 1
              AND f.created_at > %s
              AND m_asst.role = 'assistant'
            ORDER BY f.created_at DESC
            """,
            (cutoff,),
        )
        rows = cur.fetchall()

print(f"Found {len(rows)} thumbs-up pairs in the last 7 days")
if len(rows) < min_examples:
    print(f"Need {min_examples}, got {len(rows)}. Skipping optimization.")
    dbutils.notebook.exit(
        json.dumps({"status": "skipped", "reason": "insufficient_feedback", "count": len(rows)})
    )

# mlflow.genai.optimize_prompts expects
#   {"inputs": {...}, "outputs": {...}, "expectations": {...}}
# We use the thumbs-up answer as both the expected output AND as the
# single expectation fact for the Correctness scorer.
all_data = [
    {
        "inputs": {"question": q},
        "outputs": {"response": a},
        "expectations": {"expected_facts": [a[:500]]},
    }
    for q, a in rows
]

# Hold back 30% as a validation set so we can detect overfitting before
# promoting the optimized prompt. Without this guard, a prompt that
# scored 100% on 3 training examples could be promoted even if it broke
# every real query in production. Minimum 1 holdout example; falls back
# to using all rows for both train and holdout if we only have 1-2
# thumbs-up (workshop demo case).
import random as _random

_random.seed(42)
_shuffled = list(all_data)
_random.shuffle(_shuffled)
_holdout_n = max(1, len(_shuffled) // 3)
if len(_shuffled) < 3:
    train_data = _shuffled
    holdout_data = _shuffled
    print(f"Only {len(_shuffled)} examples — using all for both train and holdout.")
else:
    holdout_data = _shuffled[:_holdout_n]
    train_data = _shuffled[_holdout_n:]
    print(f"Split: {len(train_data)} train / {len(holdout_data)} holdout")

# COMMAND ----------
# MAGIC %md
# MAGIC ## 2. Register the cohort_query prompt as a GEPA-optimizable template
# MAGIC
# MAGIC GEPA evolves a template string with variable placeholders. The
# MAGIC agent's existing load_prompt call still works - it just reads
# MAGIC whichever version is tagged "production" after this notebook runs.

# COMMAND ----------
prompt_name = f"{catalog}.{schema}.cohort_query"

# Seed the initial template with either the current registered version
# or the bundled default, plus a {{question}} placeholder.
try:
    existing = mlflow.genai.load_prompt(f"prompts:/{prompt_name}/production")
    initial_body = existing.template
except Exception:
    initial_body = (
        "You are a clinical data analyst for a healthcare real-world data "
        "platform. Answer questions about patient cohorts by querying the "
        "Unity Catalog tables on Databricks. ALWAYS call inspect_schema "
        "first, use the exact fully-qualified table names it returns, and "
        "pass generated SQL through execute_sql."
    )

# Strip any existing {{question}} placeholder so we can add one cleanly.
initial_body = initial_body.replace("{{question}}", "").strip()
initial_template = initial_body + "\n\nQuestion: {{question}}\n\nAnswer:"

prompt = mlflow.genai.register_prompt(name=prompt_name, template=initial_template)
print(f"Registered initial prompt: {prompt.uri}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## 3. Define the predict_fn GEPA will optimize against


# COMMAND ----------
def predict_fn(question: str) -> str:
    """Call the chat model with the current prompt template.

    All imports are inside the function because GEPA dill-pickles
    predict_fn and re-executes it in a worker process where the
    notebook's top-level imports are not in scope. Closure-captured
    scalars (prompt_name, prompt.version, chat_model) pickle fine.
    """
    import mlflow
    from mlflow.deployments import get_deploy_client

    client = get_deploy_client("databricks")
    p = mlflow.genai.load_prompt(f"prompts:/{prompt_name}/{prompt.version}")
    resp = client.predict(
        endpoint=chat_model,
        inputs={
            "messages": [{"role": "user", "content": p.format(question=question)}],
        },
    )
    return resp["choices"][0]["message"]["content"]


# COMMAND ----------
# MAGIC %md
# MAGIC ## 4. Optimize + promote

# COMMAND ----------
with mlflow.start_run(run_name=f"optimize_prompts_{datetime.utcnow().strftime('%Y%m%d_%H%M')}"):
    mlflow.log_param("train_examples", len(train_data))
    mlflow.log_param("optimizer", "GepaPromptOptimizer")
    mlflow.log_param("reflection_model", reflection_model)
    mlflow.log_param("judge_model", judge_model)

    # Use make_judge with feedback_value_type=bool for structured output.
    # The legacy Correctness scorer routed through the Gateway adapter,
    # which assumed the judge response was pure JSON and called
    # json.loads() on the full string. Reasoning-style models (Claude,
    # GPT-5+) prepend chain-of-thought before the JSON block, breaking
    # that path with "Expecting value: line 1 column 1". make_judge uses
    # structured output (typed feedback value) so the response is
    # extracted as a proper bool regardless of any prose preamble.
    cohort_correctness = make_judge(
        name="cohort_correctness",
        instructions=(
            "You are evaluating a clinical-data assistant's answer.\n\n"
            "Question (inputs): {{ inputs }}\n\n"
            "Expected reference answer (expectations): {{ expectations }}\n\n"
            "Agent's actual answer (outputs): {{ outputs }}\n\n"
            "Return True if the agent's answer is factually consistent with the "
            "expected answer (same patient counts, same cohort definition, same "
            "clinical codes referenced), False otherwise. Minor differences in "
            "phrasing or formatting are acceptable."
        ),
        model=f"databricks:/{judge_model}",
        feedback_value_type=bool,
    )

    result = mlflow.genai.optimize_prompts(
        predict_fn=predict_fn,
        train_data=train_data,
        prompt_uris=[prompt.uri],
        optimizer=GepaPromptOptimizer(reflection_model=f"databricks:/{reflection_model}"),
        scorers=[cohort_correctness],
    )

    optimized = result.optimized_prompts[0]
    print(f"Optimized prompt: {optimized.uri}")
    print(f"\nFirst 500 chars of new template:\n{optimized.template[:500]}")

    mlflow.log_param("optimized_version", optimized.version)
    mlflow.log_text(optimized.template, "optimized_template.txt")

    run_id = mlflow.active_run().info.run_id

    # COMMAND ----------
    # Held-out validation BEFORE promoting to @production. GEPA is
    # allowed to overfit the training subset (small N, repeated judging).
    # The held-out set is the first time the optimized prompt sees
    # questions it wasn't tuned against. If it regresses, we keep the old
    # prompt and log the failure so the next run can try again.
    def _baseline_predict(question: str) -> str:
        import mlflow
        from mlflow.deployments import get_deploy_client

        client = get_deploy_client("databricks")
        # Load whatever the CURRENT @production version is (i.e. before
        # this optimizer run). If no production alias yet, fall back to v1.
        try:
            p = mlflow.genai.load_prompt(f"prompts:/{prompt_name}/production")
        except Exception:
            p = mlflow.genai.load_prompt(f"prompts:/{prompt_name}/1")
        resp = client.predict(
            endpoint=chat_model,
            inputs={"messages": [{"role": "user", "content": p.format(question=question)}]},
        )
        return resp["choices"][0]["message"]["content"]

    def _optimized_predict(question: str) -> str:
        import mlflow
        from mlflow.deployments import get_deploy_client

        client = get_deploy_client("databricks")
        p = mlflow.genai.load_prompt(f"prompts:/{prompt_name}/{optimized.version}")
        resp = client.predict(
            endpoint=chat_model,
            inputs={"messages": [{"role": "user", "content": p.format(question=question)}]},
        )
        return resp["choices"][0]["message"]["content"]

    print(f"\nRunning held-out validation on {len(holdout_data)} examples...")
    baseline_eval = mlflow.genai.evaluate(
        data=holdout_data, predict_fn=_baseline_predict, scorers=[cohort_correctness]
    )
    optimized_eval = mlflow.genai.evaluate(
        data=holdout_data, predict_fn=_optimized_predict, scorers=[cohort_correctness]
    )

    # mlflow.genai.evaluate returns an EvaluationResult with metrics; for
    # bool scorers the aggregate is the pass-rate (0.0 to 1.0).
    def _pass_rate(eval_result):
        df = eval_result.tables.get("eval_results", None)
        if df is None or len(df) == 0:
            return 0.0
        col = f"assessments/{cohort_correctness.name}/value"
        if col in df.columns:
            return float(df[col].mean())
        # fallback: any boolean assessment column
        for c in df.columns:
            if c.startswith("assessments/") and c.endswith("/value"):
                return float(df[c].mean())
        return 0.0

    baseline_score = _pass_rate(baseline_eval)
    optimized_score = _pass_rate(optimized_eval)
    mlflow.log_metric("holdout_baseline_score", baseline_score)
    mlflow.log_metric("holdout_optimized_score", optimized_score)
    mlflow.log_metric("holdout_delta", optimized_score - baseline_score)
    print(f"Held-out: baseline={baseline_score:.3f}  optimized={optimized_score:.3f}")

# COMMAND ----------
# Conditionally promote the optimized version to @production. Only flip
# the alias if the optimized prompt scores at least as well as the
# baseline on the held-out set. Previously the alias flipped
# unconditionally, so a prompt that overfit to 3 training examples could
# regress production behavior with no warning.
if optimized_score >= baseline_score:
    mlflow.genai.set_prompt_alias(
        name=prompt_name,
        version=int(optimized.version),
        alias="production",
    )
    print(
        f"Promoted production -> v{optimized.version} "
        f"(holdout {baseline_score:.3f} -> {optimized_score:.3f})"
    )
else:
    print(
        f"REGRESSION on holdout ({baseline_score:.3f} -> {optimized_score:.3f}). "
        f"Keeping current @production. v{optimized.version} remains registered "
        f"but unaliased."
    )

# COMMAND ----------
_promoted = optimized_score >= baseline_score
summary = {
    "status": "completed" if _promoted else "completed_regression_held_back",
    "train_examples": len(train_data),
    "holdout_examples": len(holdout_data),
    "holdout_baseline_score": baseline_score,
    "holdout_optimized_score": optimized_score,
    "promoted_to_production": _promoted,
    "optimizer": "GepaPromptOptimizer",
    "prompt_name": prompt_name,
    "optimized_version": optimized.version,
    "optimized_uri": optimized.uri,
    "run_id": run_id,
    "timestamp": datetime.utcnow().isoformat() + "Z",
}
print("\n" + "=" * 60)
print("OPTIMIZATION SUMMARY")
print("=" * 60)
print(json.dumps(summary, indent=2, default=str))
dbutils.notebook.exit(json.dumps(summary, default=str))
