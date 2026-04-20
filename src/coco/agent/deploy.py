"""Deploy the CoCo agent to Databricks Model Serving.

Logs the `CocoResponsesAgent` (defined in responses_agent_entry.py) via
MLflow's models-from-code path, registers it to Unity Catalog, and
calls `databricks.agents.deploy(...)`.

The models-from-code pattern (passing a file path to `python_model=`)
is required because the wrapper holds httpx async clients and other
non-pickleable state. Plain `mlflow.pyfunc.log_model(python_model=<instance>)`
cloudpickles the instance and fails with "Failed to serialize Python
model" — using the entry file sidesteps pickling entirely.

Called in-process from the workshop setup notebook via `deploy_agent()`.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile

import mlflow
import mlflow.pyfunc
from databricks import agents
from mlflow.models.resources import (
    DatabricksServingEndpoint,
    DatabricksSQLWarehouse,
    DatabricksTable,
    DatabricksVectorSearchIndex,
)

from coco.config import get_config

logger = logging.getLogger(__name__)

# Subpackages under src/coco/ that the agent does NOT need at inference
# time. These get excluded from code_paths so the model artifact stays
# small and we don't leak the workshop front-end / data-gen / raw
# knowledge markdown into the serving container.
#
#   app/             — FastAPI front-end. Runs in Databricks Apps, not
#                      in the Model Serving container.
#   data_generator/  — Faker-based synthetic patient generator used
#                      once by the setup notebook.
#   evaluation/      — Scenario runner used by the eval job, not at
#                      inference time.
_RUNTIME_EXCLUDED_TOP_DIRS = {
    "app",
    "data_generator",
    "evaluation",
}


def _stage_runtime_code(src_coco_dir: str) -> str:
    """Copy the subset of `src/coco/` the agent needs at inference time
    into a temp directory.

    Returns the path to the staged `coco/` directory (not its parent),
    suitable to pass into `code_paths=[...]`. MLflow copies the
    directory into the model artifact preserving its basename so
    `import coco.agent.X` resolves at load time.

    What gets dropped:
      - `app/`, `data_generator/`, `evaluation/` (see constant above)
      - All `*.md` files under `knowledge/` (the raw docs are already
        indexed into Vector Search; the agent calls VS, not the files)
      - All `__pycache__/` dirs and `*.pyc` files
    """
    tmp_root = tempfile.mkdtemp(prefix="coco-agent-code-")
    dst = os.path.join(tmp_root, "coco")

    def _ignore(path: str, names: list[str]) -> set[str]:
        rel = os.path.relpath(path, src_coco_dir)
        drop: set[str] = set()
        if rel == ".":
            drop.update(n for n in names if n in _RUNTIME_EXCLUDED_TOP_DIRS)
        # Under knowledge/, drop raw markdown (indexed into VS already)
        if rel == "knowledge" or rel.startswith("knowledge" + os.sep):
            drop.update(n for n in names if n.endswith(".md"))
        # Everywhere, drop caches
        drop.update(n for n in names if n == "__pycache__" or n.endswith(".pyc"))
        return drop

    shutil.copytree(src_coco_dir, dst, ignore=_ignore)

    # Sanity-log what landed in the staged dir so `test_step7_deploy_agent.py`
    # output makes it obvious when the include/exclude list drifts.
    try:
        top = sorted(os.listdir(dst))
        logger.info("Staged coco runtime code to %s (top-level: %s)", dst, top)
    except OSError:
        pass

    return dst


def _build_resources(config) -> list:
    """Build the typed MLflow resources the serving endpoint needs.

    The agent must be able to call the LLM, the Vector Search index,
    the SQL warehouse, and the cohort tables from inside the serving
    container. MLflow uses these to scope the container's auth — the
    serving SP gets precisely the grants implied by this list.

    Without DatabricksTable entries, the schema_inspector tool's
    `client.tables.list(...)` returns empty (no USE_SCHEMA), the
    execute_sql tool can't read the cohort tables, and the agent
    hallucinates about what tables exist. The SQL warehouse binding
    alone doesn't grant SELECT on the tables — it grants CAN_USE on
    the warehouse.
    """
    resources: list = [
        DatabricksServingEndpoint(endpoint_name=config.llm.gateway_route),
    ]
    vs_index = f"{config.catalog.name}.{config.catalog.schema}.{config.vector_search.index_name}"
    resources.append(DatabricksVectorSearchIndex(index_name=vs_index))
    if config.sql_warehouse.id:
        resources.append(DatabricksSQLWarehouse(warehouse_id=config.sql_warehouse.id))

    # Grant the serving SP SELECT on every cohort table the agent
    # may query. These come from config.tables and are resolved
    # against the catalog/schema from config.catalog.
    cohort_table_attrs = (
        "patients",
        "diagnoses",
        "prescriptions",
        "procedures",
        "claims",
        "suppliers",
    )
    catalog = config.catalog.name
    schema = config.catalog.schema
    for attr in cohort_table_attrs:
        name = getattr(config.tables, attr, None)
        if not name:
            continue
        resources.append(DatabricksTable(table_name=f"{catalog}.{schema}.{name}"))

    return resources


def _find_repo_root() -> str:
    """Find the coco repo root from this module's path.

    When deploy.py is imported from the setup notebook, __file__ is
    under <repo_root>/src/coco/agent/. Walk up three levels.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", ".."))


def _entry_file_path() -> str:
    """Path to the models-from-code entry script."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "responses_agent_entry.py")


def deploy_agent() -> None:
    """Log, register, and deploy the CoCo agent."""
    config = get_config()

    # Tracking URI must be "databricks" whether we're running inside a
    # Databricks notebook (where it's the default) or from a local
    # laptop (where it defaults to ./mlruns and the local path can
    # contain spaces that break the Unity Catalog registry REST calls).
    mlflow.set_tracking_uri("databricks")
    mlflow.set_registry_uri("databricks-uc")
    mlflow.set_experiment(config.mlflow.experiment_name)

    uc_model_name = (
        f"{config.catalog.name}.{config.catalog.schema}."
        f"{config.agent_endpoint.name.replace('-', '_')}"
    )
    logger.info("Target UC model: %s", uc_model_name)

    repo_root = _find_repo_root()
    coco_src = os.path.join(repo_root, "src", "coco")
    coco_config_file = os.path.join(repo_root, "config", "default.yaml")
    entry_script = _entry_file_path()
    logger.info("Models-from-code entry: %s", entry_script)
    logger.info("Bundling coco source from: %s (filtered)", coco_src)

    # Resolve ${ENV_VAR} template tokens in the config YAML before
    # saving it as the model artifact. The Model Serving container
    # does NOT inject COCO_WAREHOUSE_ID / COCO_AGENT_ENDPOINT_URL /
    # etc. as environment variables: the resource bindings grant
    # permissions but don't set env vars. So any ${...} token left
    # unresolved in the config artifact resolves to "" at load_context
    # time, and every tool that needs the warehouse_id fails silently.
    # Baking the resolved values into the artifact at deploy time
    # (when the env vars ARE set by the deployer) eliminates the gap.
    import re

    import yaml

    with open(coco_config_file) as _f:
        raw_cfg = yaml.safe_load(_f)

    _VAR_TOKEN = re.compile(r"\$\{([^}]+)\}")

    def _resolve_env(obj):  # type: ignore[no-untyped-def]
        # Regex-based substitution so compound strings like
        # "${COCO_CATALOG_NAME}.${COCO_SCHEMA_NAME}" resolve correctly.
        # The earlier `startswith("${") and endswith("}")` check matched
        # such strings but then treated the whole thing as one variable
        # name, producing an empty resolved value and a silently broken
        # allowed_schemas guardrail.
        if isinstance(obj, str):

            def _sub(m):
                name = m.group(1)
                value = os.environ.get(name, "")
                if not value:
                    logger.warning("Config resolve: ${%s} empty in env", name)
                return value

            resolved = _VAR_TOKEN.sub(_sub, obj)
            if resolved != obj:
                logger.info("Config resolve: %s -> %s", obj, resolved[:80])
            return resolved
        if isinstance(obj, dict):
            return {k: _resolve_env(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_resolve_env(v) for v in obj]
        return obj

    resolved_cfg = _resolve_env(raw_cfg)
    resolved_config_path = os.path.join(tempfile.mkdtemp(prefix="coco-config-"), "default.yaml")
    with open(resolved_config_path, "w") as _f:
        yaml.dump(resolved_cfg, _f, default_flow_style=False, sort_keys=False)
    logger.info("Resolved config written to: %s", resolved_config_path)
    coco_config_file = resolved_config_path

    # Stage only the subpackages the agent needs at inference time so
    # we don't ship the FastAPI app, the data generator, and the raw
    # knowledge markdown into the model artifact (see _stage_runtime_code).
    staged_coco_dir = _stage_runtime_code(coco_src)
    staged_parent = os.path.dirname(staged_coco_dir)

    example_request = {"input": [{"role": "user", "content": "How many patients have diabetes?"}]}

    try:
        with mlflow.start_run(run_name="coco-agent-deploy") as run:
            logger.info("Logging CoCo agent to MLflow run %s", run.info.run_id)
            logged = mlflow.pyfunc.log_model(
                name="agent",
                # models-from-code: pass the entry file path, NOT an instance
                python_model=entry_script,
                input_example=example_request,
                code_paths=[staged_coco_dir],
                artifacts={"coco_config": coco_config_file},
                pip_requirements=[
                    "mlflow>=3.1",
                    "databricks-sdk>=0.30",
                    "databricks-vectorsearch>=0.40",
                    "databricks-agents>=1.1",
                    "dspy>=2.5",
                    "httpx>=0.27",
                    "pydantic>=2.5",
                    "pyyaml>=6.0",
                    "sqlparse>=0.5",
                    "pyarrow>=16",
                    "pandas>=2.2",
                ],
                resources=_build_resources(config),
                metadata={
                    "agent_type": "healthcare_cohort_builder",
                    "version": "2.0.0",
                },
            )
            logger.info("Model logged: %s", logged.model_uri)

            registered = mlflow.register_model(
                model_uri=logged.model_uri,
                name=uc_model_name,
            )
            logger.info(
                "Registered %s version %s",
                uc_model_name,
                registered.version,
            )
    finally:
        # Clean up the staging dir — MLflow has already copied what it
        # needs into the run artifact.
        shutil.rmtree(staged_parent, ignore_errors=True)

    # databricks.agents.deploy takes model_name + int model_version,
    # NOT model_uri.
    logger.info(
        "Calling agents.deploy(model_name=%s, version=%s, endpoint=%s)",
        uc_model_name,
        registered.version,
        config.agent_endpoint.name,
    )
    # Pass the COCO_* env vars to the serving container so the baked
    # config.yaml can still resolve ${COCO_CATALOG_NAME} etc. at runtime
    # via coco.config._interpolate_env_vars. Without these, the agent's
    # load_prompt() finds catalog="" in config, returns None from
    # _registry_name(), and silently falls back to DEFAULTS — so
    # optimized prompts from GEPA never get loaded. Confirmed in practice:
    # the original deploy had no env vars, and every prompt load landed
    # on DEFAULTS even after GEPA wrote v4 to the Prompt Registry.
    _serving_env_vars = {
        "COCO_CATALOG_NAME": os.environ.get("COCO_CATALOG_NAME", ""),
        "COCO_SCHEMA_NAME": os.environ.get("COCO_SCHEMA_NAME", ""),
        "COCO_WAREHOUSE_ID": os.environ.get("COCO_WAREHOUSE_ID", ""),
        "COCO_CONFIG_PATH": "config/default.yaml",
    }
    logger.info("Serving env vars: %s", _serving_env_vars)
    deployment = agents.deploy(
        model_name=uc_model_name,
        model_version=int(registered.version),
        endpoint_name=config.agent_endpoint.name,
        scale_to_zero=config.agent_endpoint.scale_to_zero,
        workload_size=config.agent_endpoint.workload_size,
        environment_vars=_serving_env_vars,
    )
    logger.info("Deployment response: %s", deployment)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        deploy_agent()
    except Exception:
        logger.exception("Deployment failed")
        sys.exit(1)
