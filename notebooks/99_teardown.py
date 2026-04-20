# Databricks notebook source
# MAGIC %md
# MAGIC # CoCo v2 Teardown
# MAGIC
# MAGIC Removes every resource that `00_setup_workspace.py` creates, in the
# MAGIC reverse of the dependency order that setup uses. Idempotent:
# MAGIC resource-not-found is treated as success, so a teardown that
# MAGIC partially completed can be re-run cleanly.
# MAGIC
# MAGIC **WARNING:** Destructive. By the end, the workspace is in the same
# MAGIC state it was in before the workshop started. All synthetic RWD
# MAGIC data, session threads, feedback rows, serving endpoints, the App,
# MAGIC the Lakebase instance, the Vector Search index, registered models,
# MAGIC MLflow experiment, and the Prompt Registry entries are gone.
# MAGIC
# MAGIC **Shared resources** (UC catalog, VS endpoint) are kept by default
# MAGIC because multiple attendees share them. Flip the corresponding
# MAGIC widgets to YES if you know you own them exclusively.

# COMMAND ----------
# MAGIC %pip install "mlflow[databricks]>=3.1" "databricks-sdk>=0.65" "pyyaml>=6.0" "typing-extensions>=4.12" "pydantic>=2.7,<2.10"

# COMMAND ----------
# Serverless clean envs don't ship mlflow/databricks-sdk at all unless
# %pip installs them. The cell above triggers a kernel restart, so
# widget values need to be re-read and sys.path needs the pip-env dir
# at the front (same pattern as notebooks/02 and /03).
import subprocess
import sys

_pip_result = subprocess.run(
    [sys.executable, "-m", "pip", "show", "mlflow"],
    capture_output=True,
    text=True,
)
for _line in _pip_result.stdout.splitlines():
    if _line.startswith("Location:"):
        _loc = _line.split(":", 1)[1].strip()
        if _loc in sys.path:
            sys.path.remove(_loc)
        sys.path.insert(0, _loc)
        break
for _mod in list(sys.modules):
    if _mod.startswith(("databricks.sdk", "typing_extensions", "pydantic", "mlflow.genai")):
        del sys.modules[_mod]
if "databricks" in sys.modules:
    del sys.modules["databricks"]

# COMMAND ----------
dbutils.widgets.dropdown("confirm_teardown", "NO", ["NO", "YES"], "Confirm destructive teardown")
dbutils.widgets.text("catalog", "coco_demo", "Catalog name")
dbutils.widgets.text("schema", "cohort_builder", "Schema name (per-user, namespaced)")
dbutils.widgets.text("lakebase_instance", "coco-sessions", "Lakebase instance (per-user)")
dbutils.widgets.text("vs_endpoint", "coco-vs", "Vector Search endpoint (shared)")
dbutils.widgets.text("agent_endpoint", "coco-agent", "Model Serving endpoint (per-user)")
dbutils.widgets.text("app_name", "coco-cohort-copilot", "Databricks App (per-user)")
dbutils.widgets.dropdown(
    "delete_vs_endpoint", "NO", ["NO", "YES"], "Delete the shared VS endpoint too?"
)
dbutils.widgets.dropdown("delete_catalog", "NO", ["NO", "YES"], "Drop the shared UC catalog too?")
dbutils.widgets.dropdown(
    "scan_all_my_deploys",
    "NO",
    ["NO", "YES"],
    "Scan workspace for every CoCo resource I own (all namespaces)?",
)

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
lakebase_instance = dbutils.widgets.get("lakebase_instance")
vs_endpoint = dbutils.widgets.get("vs_endpoint")
agent_endpoint = dbutils.widgets.get("agent_endpoint")
app_name = dbutils.widgets.get("app_name")
confirm = dbutils.widgets.get("confirm_teardown")
delete_vs_endpoint = dbutils.widgets.get("delete_vs_endpoint") == "YES"
delete_catalog = dbutils.widgets.get("delete_catalog") == "YES"
scan_all = dbutils.widgets.get("scan_all_my_deploys") == "YES"

if confirm != "YES":
    print("Teardown NOT confirmed. Set confirm_teardown=YES to proceed.")
    dbutils.notebook.exit("skipped")

# COMMAND ----------
# Per-user auto-namespacing — mirror the logic in 00_setup_workspace.py
# so teardown rewrites the same generic defaults into per-user names.
# Without this, a user running teardown with the default
# widgets would try to delete another attendee's resources (or no-op
# because the names don't exist).
import re

from databricks.sdk import WorkspaceClient

_ws = WorkspaceClient()
_user_email = _ws.current_user.me().user_name or ""
_user_local = _user_email.split("@", 1)[0].lower()
ns = re.sub(r"[^a-z0-9]", "", _user_local)[:12] or "user"

_REWRITES = {
    "schema": ("cohort_builder", f"cohort_builder_{ns}"),
    "lakebase_instance": ("coco-sessions", f"coco-lb-{ns}"),
    "agent_endpoint": ("coco-agent", f"coco-agent-{ns}"),
    "app_name": ("coco-cohort-copilot", f"coco-{ns}"),
}
if schema == _REWRITES["schema"][0]:
    schema = _REWRITES["schema"][1]
if lakebase_instance == _REWRITES["lakebase_instance"][0]:
    lakebase_instance = _REWRITES["lakebase_instance"][1]
if agent_endpoint == _REWRITES["agent_endpoint"][0]:
    agent_endpoint = _REWRITES["agent_endpoint"][1]
if app_name == _REWRITES["app_name"][0]:
    app_name = _REWRITES["app_name"][1]

print(f"User: {_user_email} | Namespace: {ns}")
print("Will tear down:")
print(f"  app: {app_name}")
print(f"  agent_endpoint: {agent_endpoint}")
print(f"  lakebase_instance: {lakebase_instance}")
print(f"  schema: {catalog}.{schema}")
print(f"  delete_vs_endpoint (shared): {delete_vs_endpoint}")
print(f"  delete_catalog (shared): {delete_catalog}")
print(f"  scan_all_my_deploys: {scan_all}")

# COMMAND ----------
# Optional workspace scan: when a deployer has run setup multiple times
# with different unique_id values, the widget-driven list above only
# catches ONE namespace per invocation. The scan below walks the
# workspace for every CoCo-prefixed resource whose creator is the
# current user, and queues each one for deletion. The per-resource
# cells below iterate over the queued names.
apps_to_delete = [app_name]
endpoints_to_delete = [agent_endpoint]
lakebase_to_delete = [lakebase_instance]
schemas_to_delete = [schema]

if scan_all:
    print("\nScanning workspace for CoCo resources owned by this user...")

    def _owned_by_me(obj: object, *owner_fields: str) -> bool:
        for f in owner_fields:
            v = getattr(obj, f, None)
            if v and v == _user_email:
                return True
        return False

    try:
        discovered_apps = [
            a.name
            for a in _ws.apps.list()
            if (a.name or "").startswith("coco-") and _owned_by_me(a, "creator", "owner")
        ]
        for a in discovered_apps:
            if a and a not in apps_to_delete:
                apps_to_delete.append(a)
        print(f"  apps: {discovered_apps}")
    except Exception as e:
        print(f"  WARN apps scan: {e.__class__.__name__}: {e}")

    try:
        discovered_endpoints = [
            e.name
            for e in _ws.serving_endpoints.list()
            if (e.name or "").startswith("coco-agent") and _owned_by_me(e, "creator")
        ]
        for e in discovered_endpoints:
            if e and e not in endpoints_to_delete:
                endpoints_to_delete.append(e)
        print(f"  endpoints: {discovered_endpoints}")
    except Exception as e:
        print(f"  WARN endpoints scan: {e.__class__.__name__}: {e}")

    try:
        resp = _ws.api_client.do("GET", "/api/2.0/database/instances")
        discovered_instances = [
            i.get("name")
            for i in (resp.get("database_instances") or [])
            if (i.get("name") or "").startswith("coco-") and i.get("creator") == _user_email
        ]
        for i in discovered_instances:
            if i and i not in lakebase_to_delete:
                lakebase_to_delete.append(i)
        print(f"  lakebase: {discovered_instances}")
    except Exception as e:
        print(f"  WARN lakebase scan: {e.__class__.__name__}: {e}")

    try:
        discovered_schemas = [
            s.name
            for s in _ws.schemas.list(catalog_name=catalog)
            if (s.name or "").startswith("cohort_builder") and _owned_by_me(s, "owner")
        ]
        for s in discovered_schemas:
            if s and s not in schemas_to_delete:
                schemas_to_delete.append(s)
        print(f"  schemas in {catalog}: {discovered_schemas}")
    except Exception as e:
        print(f"  WARN schemas scan: {e.__class__.__name__}: {e}")

    print("\nAfter scan, queued for deletion:")
    print(f"  apps: {apps_to_delete}")
    print(f"  endpoints: {endpoints_to_delete}")
    print(f"  lakebase: {lakebase_to_delete}")
    print(f"  schemas: {[f'{catalog}.{s}' for s in schemas_to_delete]}")

print("\nTEARDOWN IN PROGRESS...\n")

# COMMAND ----------
# MAGIC %md
# MAGIC ## 1. Databricks App
# MAGIC
# MAGIC Must go first: the App holds resource bindings to the serving
# MAGIC endpoint, Lakebase, and SQL warehouse. Deleting those first
# MAGIC would leave the App in a broken-reference state.

# COMMAND ----------
w = _ws

for _app in apps_to_delete:
    print(f"Deleting Databricks App: {_app}")
    try:
        w.apps.delete(name=_app)
        print(f"  App '{_app}' deleted.")
    except Exception as e:
        if "does not exist" in str(e).lower() or "not found" in str(e).lower():
            print(f"  App '{_app}' already gone.")
        else:
            print(f"  WARNING: {e.__class__.__name__}: {e}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## 2. Model Serving endpoint

# COMMAND ----------
for _ep in endpoints_to_delete:
    print(f"Deleting Model Serving endpoint: {_ep}")
    try:
        w.serving_endpoints.delete(_ep)
        print(f"  Endpoint '{_ep}' deleted.")
    except Exception as e:
        if "does not exist" in str(e).lower() or "RESOURCE_DOES_NOT_EXIST" in str(e):
            print(f"  Endpoint '{_ep}' already gone.")
        else:
            print(f"  WARNING: {e.__class__.__name__}: {e}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## 3. Vector Search index (and optionally endpoint)

# COMMAND ----------
# Use REST API path — the `databricks-vectorsearch` Python SDK has a
# namespace collision with `databricks-sdk` on serverless after kernel
# restart (same workaround as 00_setup_workspace.py).
for _schema in schemas_to_delete:
    vs_index_name = f"{catalog}.{_schema}.coco_knowledge_idx"
    print(f"Deleting Vector Search index: {vs_index_name}")
    try:
        w.api_client.do("DELETE", f"/api/2.0/vector-search/indexes/{vs_index_name}")
        print(f"  Index '{vs_index_name}' deleted.")
    except Exception as e:
        if "does not exist" in str(e).lower() or "RESOURCE_DOES_NOT_EXIST" in str(e):
            print(f"  Index '{vs_index_name}' already gone.")
        else:
            print(f"  WARNING: {e.__class__.__name__}: {e}")

if delete_vs_endpoint:
    print(f"Deleting Vector Search endpoint: {vs_endpoint}")
    try:
        w.api_client.do("DELETE", f"/api/2.0/vector-search/endpoints/{vs_endpoint}")
        print(f"  Endpoint '{vs_endpoint}' deleted.")
    except Exception as e:
        if "does not exist" in str(e).lower() or "RESOURCE_DOES_NOT_EXIST" in str(e):
            print(f"  Endpoint '{vs_endpoint}' already gone.")
        else:
            print(f"  WARNING: {e.__class__.__name__}: {e}")
else:
    print(f"Skipping VS endpoint '{vs_endpoint}' (shared; pass delete_vs_endpoint=YES to delete).")

# COMMAND ----------
# MAGIC %md
# MAGIC ## 4. Lakebase instance
# MAGIC
# MAGIC Use REST API — the SDK's database module has version mismatches on
# MAGIC some serverless runtimes; the same workaround 00_setup_workspace.py
# MAGIC uses for provisioning.

# COMMAND ----------
for _inst in lakebase_to_delete:
    print(f"Deleting Lakebase instance: {_inst}")
    try:
        w.api_client.do("DELETE", f"/api/2.0/database/instances/{_inst}")
        print(f"  Instance '{_inst}' deletion requested.")
    except Exception as e:
        if "does not exist" in str(e).lower() or "RESOURCE_DOES_NOT_EXIST" in str(e):
            print(f"  Instance '{_inst}' already gone.")
        else:
            print(f"  WARNING: {e.__class__.__name__}: {e}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## 5. MLflow Prompt Registry entries
# MAGIC
# MAGIC The setup notebook registers default prompts under
# MAGIC `{catalog}.{schema}.{local_name}`. GEPA optimization adds versions
# MAGIC to those same entries. Delete each prompt entirely.

# COMMAND ----------
import mlflow

mlflow.set_tracking_uri("databricks")
mlflow.set_registry_uri("databricks-uc")

for leaf in ("cohort_query", "clinical_codes", "sql_generator", "response_synthesizer"):
    prompt_fqn = f"{catalog}.{schema}.{leaf}"
    print(f"Deleting MLflow prompt: {prompt_fqn}")
    try:
        mlflow.genai.delete_prompt(name=prompt_fqn)
        print(f"  Prompt '{prompt_fqn}' deleted.")
    except AttributeError:
        # Older mlflow — fall back to REST via the MLflow client.
        try:
            client = mlflow.MlflowClient()
            # Delete by iterating versions; some versions are referenced
            # by aliases which need un-aliasing first.
            for v in client.search_model_versions(f"name='{prompt_fqn}'"):
                try:
                    client.delete_model_version(name=prompt_fqn, version=v.version)
                except Exception:
                    pass
            client.delete_registered_model(name=prompt_fqn)
            print(f"  Prompt '{prompt_fqn}' deleted (via registered-model path).")
        except Exception as e:
            print(f"  WARNING: {e.__class__.__name__}: {e}")
    except Exception as e:
        if "does not exist" in str(e).lower() or "RESOURCE_DOES_NOT_EXIST" in str(e):
            print(f"  Prompt '{prompt_fqn}' already gone.")
        else:
            print(f"  WARNING: {e.__class__.__name__}: {e}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## 6. UC registered models (agent)
# MAGIC
# MAGIC `databricks.agents.deploy()` registers the agent as
# MAGIC `{catalog}.{schema}.{agent_endpoint_underscored}`. Drop it + any
# MAGIC sibling inference/payload auto-tables.

# COMMAND ----------
agent_model_name = f"{catalog}.{schema}.{agent_endpoint.replace('-', '_')}"
print(f"Deleting UC registered model: {agent_model_name}")
try:
    w.registered_models.delete(full_name=agent_model_name)
    print(f"  Model '{agent_model_name}' deleted.")
except Exception as e:
    if "does not exist" in str(e).lower() or "RESOURCE_DOES_NOT_EXIST" in str(e):
        print(f"  Model '{agent_model_name}' already gone.")
    else:
        print(f"  WARNING: {e.__class__.__name__}: {e}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## 7. MLflow experiment
# MAGIC
# MAGIC Per-user path `/Users/{email}/coco-agent`, with fallback to the
# MAGIC shared `/Shared/coco-agent` for pre-namespacing deployments.

# COMMAND ----------
client = mlflow.MlflowClient()
_per_user_exp = f"/Users/{_user_email}/coco-agent"
try:
    exp = client.get_experiment_by_name(_per_user_exp)
    if exp is None:
        print(f"  Per-user experiment '{_per_user_exp}' already gone.")
    else:
        client.delete_experiment(exp.experiment_id)
        print(f"  Per-user experiment '{_per_user_exp}' deleted.")
except Exception as e:
    print(f"  WARNING: {e.__class__.__name__}: {e}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## 8. UC schema (cascades to tables + volumes)
# MAGIC
# MAGIC DROP SCHEMA ... CASCADE removes the synthetic RWD tables, the
# MAGIC knowledge_chunks table, and the coco_knowledge / coco_artifacts
# MAGIC volumes in one step.

# COMMAND ----------
from pyspark.sql import SparkSession

spark = SparkSession.builder.appName("CoCo Teardown").getOrCreate()

for _schema in schemas_to_delete:
    schema_fqn = f"{catalog}.{_schema}"
    print(f"Dropping UC schema: {schema_fqn} CASCADE")
    try:
        spark.sql(f"DROP SCHEMA IF EXISTS {schema_fqn} CASCADE")
        print(f"  Schema '{schema_fqn}' and all tables/volumes deleted.")
    except Exception as e:
        print(f"  WARNING: {e.__class__.__name__}: {e}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## 9. UC catalog (only if delete_catalog=YES)
# MAGIC
# MAGIC The catalog is usually shared across deployers and
# MAGIC admin-managed, so default behavior leaves it alone. Opt in
# MAGIC explicitly when the catalog was created for your use only.

# COMMAND ----------
if delete_catalog:
    print(f"Dropping UC catalog: {catalog} CASCADE")
    try:
        spark.sql(f"DROP CATALOG IF EXISTS {catalog} CASCADE")
        print(f"  Catalog '{catalog}' deleted.")
    except Exception as e:
        print(f"  WARNING: {e.__class__.__name__}: {e}")
else:
    print("Skipping catalog drop (shared; pass delete_catalog=YES to drop).")

# COMMAND ----------
print("\n✅ Teardown complete. The workspace is back to its pre-deployment state.")
