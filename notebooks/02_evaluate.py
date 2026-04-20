# Databricks notebook source
# MAGIC %md
# MAGIC # CoCo v2 Evaluation
# MAGIC
# MAGIC Offline evaluation of the CoCo agent against a fixed golden set of
# MAGIC cohort questions, using `mlflow.genai.evaluate()`.
# MAGIC
# MAGIC This notebook replaces the previous `EvaluationRunner` (which had a
# MAGIC `use_mock=True` default and never actually called the endpoint).
# MAGIC Scorers live in `src/coco/observability/scorers.py` and are the same
# MAGIC objects that can be attached to production traces.
# MAGIC
# MAGIC **Schedule:** weekly Sunday 02:00 UTC (paused by default; unpause once
# MAGIC you want regression alerting).

# COMMAND ----------
# MAGIC %pip install "mlflow[databricks]>=3.1" "pydantic>=2.7,<2.10" "typing-extensions>=4.12" "databricks-sdk>=0.65" "databricks-agents>=1.1" "httpx>=0.27" "pyyaml>=6.0" "sqlparse>=0.5"

# COMMAND ----------
# Post-%pip-restart kernel. We deliberately do NOT flush or re-import
# mlflow here because doing so triggers protobuf's C++ descriptor pool
# to reject the duplicate registration of service.proto. The only
# mlflow 3.4-specific symbol we had been using was mlflow.entities.Feedback
# in scorers.py - that has been replaced with a dict-returning shim
# that works on mlflow 3.1+. Everything else (mlflow.start_run,
# log_param, log_metric, log_text, log_artifacts, and
# mlflow.genai.evaluate on runtimes that have it) works on the
# preloaded mlflow regardless of version.
import os
import subprocess
import sys
from pathlib import Path

dbutils.widgets.text("catalog", "coco_demo", "Catalog name")
dbutils.widgets.text("schema", "cohort_builder", "Schema name")
dbutils.widgets.text("warehouse_id", "", "SQL Warehouse ID")
dbutils.widgets.text("agent_endpoint", "coco-agent", "Agent endpoint name")
dbutils.widgets.text("category", "", "Scenario category filter (optional)")
dbutils.widgets.text("difficulty", "", "Scenario difficulty filter (optional)")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
warehouse_id = dbutils.widgets.get("warehouse_id")
agent_endpoint_name = dbutils.widgets.get("agent_endpoint")
category_filter = dbutils.widgets.get("category") or None
difficulty_filter = dbutils.widgets.get("difficulty") or None

os.environ["COCO_CATALOG_NAME"] = catalog
os.environ["COCO_SCHEMA_NAME"] = schema
os.environ["COCO_WAREHOUSE_ID"] = warehouse_id
os.environ["COCO_AGENT_ENDPOINT_NAME"] = agent_endpoint_name
os.environ.setdefault(
    "DATABRICKS_HOST",
    spark.conf.get("spark.databricks.workspaceUrl", "") or "",
)

# Per-user MLflow experiment path. Fails hard if the username cannot
# be resolved, because landing in /Shared is a workshop-isolation
# violation and silent drift is worse than a fast failure here.
from databricks.sdk import WorkspaceClient as _UserWs

_user_email = (_UserWs().current_user.me().user_name or "").strip()
if not _user_email:
    raise RuntimeError(
        "Cannot resolve workspace username for per-user MLflow experiment. "
        "Every workshop attendee must have a valid email-backed Databricks "
        "identity. Refusing to fall back to /Shared/coco-agent."
    )
os.environ["COCO_MLFLOW_EXPERIMENT"] = f"/Users/{_user_email}/coco-agent"
print(f"MLflow experiment (per-user): {os.environ['COCO_MLFLOW_EXPERIMENT']}")

# Serverless sys.path fix: put the pip env ahead of the read-only system
# site-packages so fresh packages are preferred on import.
_pip_result = subprocess.run(
    [sys.executable, "-m", "pip", "show", "mlflow"],
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
# Evict cached versions of fast-moving packages so the next `import x`
# picks up the pip-env copy. mlflow is intentionally NOT in this list -
# re-importing it causes protobuf's C++ descriptor pool to reject the
# duplicate registration of service.proto. Scorers use a local Feedback
# shim so they do not need mlflow.entities.Feedback from 3.4+.
for _mod in list(sys.modules):
    if _mod.startswith(("databricks.sdk", "typing_extensions", "pydantic", "openai", "litellm")):
        del sys.modules[_mod]
if "databricks" in sys.modules:
    del sys.modules["databricks"]

# Runtime compatibility: newer serverless runtimes (e2-dogfood) removed
# getDbfsPath; older runtimes still have it. Try the modern API first.
try:
    _nb_path = (
        dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
    )
except Exception:
    _nb_path = dbutils.notebook.entry_point.getDbfsPath()
# notebookPath() returns the logical path (/Users/...) without the
# /Workspace prefix that on-disk lookups need. getDbfsPath() includes
# it. Normalize so Path(...).is_dir() works regardless.
if _nb_path and not _nb_path.startswith("/Workspace") and not _nb_path.startswith("/dbfs"):
    _nb_path = f"/Workspace{_nb_path}"
_repo_root = None
_candidate = _nb_path
for _ in range(6):
    _candidate = _candidate.rsplit("/", 1)[0]
    if not _candidate:
        break
    if Path(_candidate, "src/coco").is_dir():
        _repo_root = _candidate
        break
if _repo_root is None:
    raise RuntimeError(
        f"Could not locate src/coco above {_nb_path!r}. Has the bundle been deployed?"
    )
repo_root = _repo_root
sys.path.insert(0, f"{repo_root}/src")
os.environ["COCO_CONFIG_PATH"] = f"{repo_root}/config/default.yaml"

# COMMAND ----------
import json
import logging
from datetime import datetime

import mlflow
import yaml

from coco.app.agent_client import AgentClient
from coco.config import get_config
from coco.observability.scorers import (
    clinical_code_accuracy_scorer,
    phi_leak_scorer,
    response_relevance_scorer,
    sql_validity_scorer,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config = get_config()

# COMMAND ----------
# MAGIC %md
# MAGIC ## Load scenarios and build the eval dataset

# COMMAND ----------
scenarios_path = Path(f"{repo_root}/{config.evaluation.scenarios_file}")
scenarios = yaml.safe_load(scenarios_path.read_text())["scenarios"]

if category_filter:
    scenarios = [s for s in scenarios if s.get("category") == category_filter]
if difficulty_filter:
    scenarios = [s for s in scenarios if s.get("difficulty") == difficulty_filter]

# mlflow.genai.evaluate expects: {"inputs": ..., "expectations": ..., <extra_cols>}.
# Scorers receive `inputs` and `expectations` exactly as we shape them here.
eval_data = []
for s in scenarios:
    expected_codes = s.get("expected_codes", []) or []
    eval_data.append(
        {
            "inputs": {"query": s["query"]},
            "expectations": {
                "expected_tables": s.get("expected_tables", []),
                "expected_icd10": [c["code"] for c in expected_codes if c.get("type") == "ICD-10"],
                "expected_ndc": [c["code"] for c in expected_codes if c.get("type") == "NDC"],
                "expected_sql_pattern": s.get("expected_sql_pattern", ""),
            },
            "scenario_id": s["id"],
            "category": s.get("category"),
            "difficulty": s.get("difficulty"),
        }
    )

print(
    f"Evaluating {len(eval_data)} scenarios "
    f"(category={category_filter or 'all'}, difficulty={difficulty_filter or 'all'})"
)

# COMMAND ----------
# MAGIC %md
# MAGIC ## Wire a predict_fn around the live agent endpoint

# COMMAND ----------
agent_client = AgentClient(endpoint_name=agent_endpoint_name)


def predict_fn(query: str) -> dict:
    """Invoke the live CoCo agent and shape the output for scorers.

    Calls the sync HTTP path directly (agent_client._invoke_sync)
    because mlflow.genai.evaluate runs predict_fn inside its own
    asyncio event loop; wrapping an `asyncio.run(...)` call inside
    that context raises "cannot be called from a running event loop".

    The scorers accept either a string or a dict with `response`,
    `output`, or `sql` keys. We populate all three so each scorer
    finds what it needs without extra glue.
    """
    text = agent_client._invoke_sync([{"role": "user", "content": query}])
    return {"response": text, "output": text, "sql": text}


# COMMAND ----------
# MAGIC %md
# MAGIC ## Run evaluation

# COMMAND ----------
mlflow.set_tracking_uri("databricks")
mlflow.set_experiment(config.mlflow.experiment_name)

run_name = f"eval_{datetime.utcnow().strftime('%Y%m%d_%H%M')}"
with mlflow.start_run(run_name=run_name) as active_run:
    mlflow.log_param("scenario_count", len(eval_data))
    mlflow.log_param("category_filter", category_filter or "all")
    mlflow.log_param("difficulty_filter", difficulty_filter or "all")
    mlflow.log_param("agent_endpoint", agent_endpoint_name)

    result = mlflow.genai.evaluate(
        data=eval_data,
        predict_fn=predict_fn,
        scorers=[
            sql_validity_scorer,
            clinical_code_accuracy_scorer,
            response_relevance_scorer,
            phi_leak_scorer,
        ],
    )

    run_id = active_run.info.run_id
    print(f"MLflow run: {run_id}")
    print("Aggregate metrics:")
    for k, v in (result.metrics or {}).items():
        print(f"  {k}: {v}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Summary for job-exit
# MAGIC
# MAGIC Emitted as the notebook's exit value so a scheduled job can alert
# MAGIC on regressions (e.g. downstream Workflow task reads this JSON).

# COMMAND ----------
summary = {
    "status": "completed",
    "scenario_count": len(eval_data),
    "category_filter": category_filter,
    "difficulty_filter": difficulty_filter,
    "metrics": dict(result.metrics or {}),
    "run_id": run_id,
    "timestamp": datetime.utcnow().isoformat() + "Z",
}
print(json.dumps(summary, indent=2, default=str))
dbutils.notebook.exit(json.dumps(summary, default=str))
