# Databricks notebook source
# MAGIC %md
# MAGIC # CoCo v2 Setup — Workspace Provisioning
# MAGIC
# MAGIC This notebook provisions the entire CoCo v2 workspace for the workshop.
# MAGIC - **Duration:** ~20 minutes
# MAGIC - **Output:** `setup_complete.json` containing all connection strings and resource URLs
# MAGIC - **Run all cells.** The setup is idempotent and safe to re-run.
# MAGIC
# MAGIC After successful completion, share `setup_complete.json` with the Databricks platform team.

# COMMAND ----------
dbutils.widgets.text("catalog", "coco_demo", "Catalog name")
dbutils.widgets.text("schema", "cohort_builder", "Schema name")
dbutils.widgets.text("warehouse_id", "", "SQL Warehouse ID (for queries)")
dbutils.widgets.text("lakebase_instance", "coco-sessions", "Lakebase instance name")
dbutils.widgets.text("vs_endpoint", "coco-vs", "Vector Search endpoint name")
dbutils.widgets.text("agent_endpoint", "coco-agent", "Model Serving endpoint name")
dbutils.widgets.text("app_name", "coco-cohort-copilot", "Databricks App name")
dbutils.widgets.text(
    "agent_repo_volume", "/Workspace/Repos/coco-reference", "Path to cloned repo or volume mount"
)
# "minimal" mode skips the optional resources (Lakebase, Vector Search).
# Useful for: first-time learners who want to see the core agent work
# without provisioning two more preview services, or workspaces that
# don't have Lakebase / VS available, or cost-sensitive test runs.
# The app will boot without Lakebase (sessions will 503 at runtime) and
# without a VS index (the retrieve_knowledge tool returns empty).
dbutils.widgets.dropdown("minimal", "false", ["false", "true"], "Minimal mode (skip Lakebase + VS)")

# Retrieve widget values
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
warehouse_id = dbutils.widgets.get("warehouse_id")
lakebase_instance = dbutils.widgets.get("lakebase_instance")
vs_endpoint = dbutils.widgets.get("vs_endpoint")
agent_endpoint = dbutils.widgets.get("agent_endpoint")
app_name = dbutils.widgets.get("app_name")
agent_repo_volume = dbutils.widgets.get("agent_repo_volume")
minimal = dbutils.widgets.get("minimal").lower() == "true"

print(f"Catalog: {catalog}")
print(f"Schema: {schema}")
print(f"Warehouse ID: {warehouse_id}")
print(f"Lakebase instance: {lakebase_instance}")
print(f"Vector Search endpoint: {vs_endpoint}")
print(f"Agent endpoint: {agent_endpoint}")
print(f"App name: {app_name}")
print(f"Agent repo volume: {agent_repo_volume}")
print(f"Minimal mode: {minimal}  (Lakebase + VS {'SKIPPED' if minimal else 'included'})")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 1: Install Dependencies
# MAGIC
# MAGIC Install required Python packages from the project requirements.

# COMMAND ----------
# MAGIC %pip install "typing-extensions>=4.12" databricks-sdk>=0.65 "dspy>=2.5,<3.2" databricks-agents>=1.1 mlflow>=3.1 "psycopg[binary]>=3.2" psycopg_pool>=3.2 sqlparse>=0.5 httpx>=0.27 markdown-it-py>=3.0 pyyaml>=6.0 "pydantic>=2.5,<2.10" pyarrow>=16 python-jose>=3.3

# COMMAND ----------
# %pip auto-restarts the Python process on serverless. Re-read
# widget values and set up sys.path after the restart.
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
warehouse_id = dbutils.widgets.get("warehouse_id")
lakebase_instance = dbutils.widgets.get("lakebase_instance")
vs_endpoint = dbutils.widgets.get("vs_endpoint")
agent_endpoint = dbutils.widgets.get("agent_endpoint")
app_name = dbutils.widgets.get("app_name")
agent_repo_volume = dbutils.widgets.get("agent_repo_volume")
minimal = dbutils.widgets.get("minimal").lower() == "true"

import os
import subprocess
import sys

# --- Serverless sys.path fix ---
# On serverless, %pip installs packages to an ephemeral env directory, but
# after kernel restart the SYSTEM site-packages (/databricks/python/lib/...)
# comes first in sys.path. This shadows pip-installed upgrades for
# typing_extensions, databricks-sdk, and everything else. Fix: find the
# pip env directory and move it to the front of sys.path BEFORE importing
# anything else.
_pip_result = subprocess.run(
    [sys.executable, "-m", "pip", "show", "dspy"],
    capture_output=True,
    text=True,
)
_pip_env_loc = None
for _line in _pip_result.stdout.splitlines():
    if _line.startswith("Location:"):
        _pip_env_loc = _line.split(":", 1)[1].strip()
        break

if _pip_env_loc and _pip_env_loc not in sys.path[:2]:
    if _pip_env_loc in sys.path:
        sys.path.remove(_pip_env_loc)
    sys.path.insert(0, _pip_env_loc)
    print(f"Prioritized pip packages: {_pip_env_loc}")

# Force Python to re-resolve modules from the corrected path.
# Without this, already-cached system modules stay in sys.modules.
for _mod_name in list(sys.modules.keys()):
    if _mod_name.startswith(("databricks.sdk", "typing_extensions")):
        del sys.modules[_mod_name]
# Also clear the parent 'databricks' module so sub-packages re-resolve
if "databricks" in sys.modules:
    del sys.modules["databricks"]

import typing_extensions as _te

if hasattr(_te, "deprecated"):
    print(f"typing_extensions {getattr(_te, '__version__', '?')} OK")
else:
    raise RuntimeError(
        f"typing_extensions at {_te.__file__} still too old after sys.path fix. "
        f"sys.path[0:3]={sys.path[:3]}"
    )

# The serverless runtime's databricks package at /databricks/python_shell/databricks/
# has an __init__.py (regular package), which blocks namespace sub-packages
# (agents, vectorsearch) installed in different directories. Extend __path__.
import databricks

for _ns_pkg in ["databricks-agents", "databricks-vectorsearch"]:
    _show = subprocess.run(
        [sys.executable, "-m", "pip", "show", _ns_pkg],
        capture_output=True,
        text=True,
    )
    for _line in _show.stdout.splitlines():
        if _line.startswith("Location:"):
            _loc = _line.split(":", 1)[1].strip()
            _db_sub = os.path.join(_loc, "databricks")
            if os.path.isdir(_db_sub) and _db_sub not in databricks.__path__:
                databricks.__path__.insert(0, _db_sub)
                print(f"  Extended databricks.__path__ for {_ns_pkg}")
            break

src_path = f"{agent_repo_volume}/src"
if src_path not in sys.path:
    sys.path.insert(0, src_path)
print(f"sys.path ready. Pip env: {_pip_env_loc}, src: {src_path}")

# Verify all critical imports; re-install any that the kernel restart dropped.
_required = [
    ("databricks-sdk", "databricks.sdk"),
    ("dspy", "dspy"),
    ("databricks-agents", "databricks.agents"),
    ("mlflow", "mlflow"),
    ("psycopg[binary]", "psycopg"),
    ("psycopg_pool", "psycopg_pool"),
    ("sqlparse", "sqlparse"),
    ("httpx", "httpx"),
    ("markdown-it-py", "markdown_it"),
    ("pyyaml", "yaml"),
    ("pydantic", "pydantic"),
    ("pyarrow", "pyarrow"),
]
_missing = []
for pip_name, mod_name in _required:
    try:
        __import__(mod_name)
    except ImportError:
        _missing.append(pip_name)
if _missing:
    print(f"Re-installing {len(_missing)} missing packages: {_missing}")
    subprocess.check_call([sys.executable, "-m", "pip", "install"] + _missing + ["-q"])
print(f"All {len(_required)} packages verified.")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 2: Create UC Catalog, Schema, and Volumes
# MAGIC
# MAGIC Create the Unity Catalog structure idempotently. This includes:
# MAGIC - Main catalog
# MAGIC - Schema for RWD and session tables
# MAGIC - Knowledge volume (for uploaded markdown docs)
# MAGIC - Artifacts volume (for setup_complete.json and other outputs)

# COMMAND ----------
# dbutils.library.restartPython() in Step 1 wiped the kernel state, so
# re-read every widget value we'll use for the rest of the notebook.
# Widgets themselves persist server-side; only Python variables reset.
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
warehouse_id = dbutils.widgets.get("warehouse_id")
lakebase_instance = dbutils.widgets.get("lakebase_instance")
vs_endpoint = dbutils.widgets.get("vs_endpoint")
agent_endpoint = dbutils.widgets.get("agent_endpoint")
app_name = dbutils.widgets.get("app_name")
agent_repo_volume = dbutils.widgets.get("agent_repo_volume")
minimal = dbutils.widgets.get("minimal").lower() == "true"
knowledge_vol = "coco_knowledge"
artifacts_vol = "coco_artifacts"

# Make the coco package importable without leaning on pip's editable
# install (which has PEP 660 / Workspace Files edge cases). Every cell
# after this one picks up the sys.path change via the shared kernel.
import os
import re
import sys

coco_src_path = f"{agent_repo_volume}/src"
if coco_src_path not in sys.path:
    sys.path.insert(0, coco_src_path)

from pyspark.sql import SparkSession

spark = SparkSession.builder.appName("CoCo Setup").getOrCreate()

# -------------------- Per-user namespace --------------------
# Multiple users share one workspace, so every
# per-attendee resource (schema, Lakebase instance, agent endpoint,
# app, MLflow experiment) must be namespaced. We derive the namespace
# from the workspace username so attendees don't have to pick one.
#
# When the notebook runs via `databricks bundle run` with explicit
# --var overrides (see databricks.yml which already uses
# ${var.unique_id}), the widget values come in pre-namespaced. In that
# case the auto-namespace below is a no-op because the values won't
# match the generic widget defaults.
from databricks.sdk import WorkspaceClient

_ws = WorkspaceClient()
_user_email = _ws.current_user.me().user_name or ""
_user_local = _user_email.split("@", 1)[0].lower()
# Databricks App names have a 30-char limit and must match [a-z0-9-].
# Schema names must match [a-z0-9_]. Strip everything else and truncate
# to 12 chars so `coco-{ns}` stays <=17 chars with room to spare.
ns = re.sub(r"[^a-z0-9]", "", _user_local)[:12] or "user"

_COLLISION_DEFAULTS = {
    # Every per-attendee resource is namespaced. The only shared item
    # is the UC catalog itself, which is admin-managed and has no
    # reasonable per-user alternative on most workspaces (Default
    # Storage workspaces block non-admins from CREATE CATALOG). All
    # per-user data lives in the per-attendee schema underneath.
    "schema": ("cohort_builder", f"cohort_builder_{ns}"),
    "lakebase_instance": ("coco-sessions", f"coco-lb-{ns}"),
    "agent_endpoint": ("coco-agent", f"coco-agent-{ns}"),
    "app_name": ("coco-cohort-copilot", f"coco-{ns}"),
    # VS endpoint IS namespaced per user. Earlier versions sharded one
    # shared endpoint across attendees. The workshop model is "every
    # attendee's resources in their own namespace, zero cross-user
    # dependencies", so this follows the same pattern. Endpoints are
    # CU-backed and cheap at workshop scale (1 index each, light query
    # load). If you want to collapse to a shared endpoint to cut cost,
    # do it explicitly by passing --var vs_endpoint=coco-vs-shared; the
    # auto-namespace only rewrites the generic `coco-vs` default.
    "vs_endpoint": ("coco-vs", f"coco-vs-{ns}"),
}

_renamed = []
if schema == _COLLISION_DEFAULTS["schema"][0]:
    schema = _COLLISION_DEFAULTS["schema"][1]
    _renamed.append(f"schema -> {schema}")
if lakebase_instance == _COLLISION_DEFAULTS["lakebase_instance"][0]:
    lakebase_instance = _COLLISION_DEFAULTS["lakebase_instance"][1]
    _renamed.append(f"lakebase_instance -> {lakebase_instance}")
if agent_endpoint == _COLLISION_DEFAULTS["agent_endpoint"][0]:
    agent_endpoint = _COLLISION_DEFAULTS["agent_endpoint"][1]
    _renamed.append(f"agent_endpoint -> {agent_endpoint}")
if app_name == _COLLISION_DEFAULTS["app_name"][0]:
    app_name = _COLLISION_DEFAULTS["app_name"][1]
    _renamed.append(f"app_name -> {app_name}")
if vs_endpoint == _COLLISION_DEFAULTS["vs_endpoint"][0]:
    vs_endpoint = _COLLISION_DEFAULTS["vs_endpoint"][1]
    _renamed.append(f"vs_endpoint -> {vs_endpoint}")

print(f"User: {_user_email} | Namespace: {ns}")
if _renamed:
    print("Auto-namespaced (default widget values rewritten to avoid collisions):")
    for line in _renamed:
        print(f"  {line}")
else:
    print("All widget values look pre-namespaced; no auto-rewrites.")
print(f"  catalog: {catalog} (shared — UC admin-managed)")
print(f"  schema: {schema}  (per-user)")
print(f"  lakebase_instance: {lakebase_instance}  (per-user)")
print(f"  vs_endpoint: {vs_endpoint}  (per-user)")
print(f"  agent_endpoint: {agent_endpoint}  (per-user)")
print(f"  app_name: {app_name}  (per-user)")

# coco.config.get_config() reads COCO_CONFIG_PATH from env (default is
# config/default.yaml relative to cwd, which on a notebook runner points
# nowhere sensible). Point it at the bundle-uploaded config.
os.environ["COCO_CONFIG_PATH"] = f"{agent_repo_volume}/config/default.yaml"
os.environ.setdefault(
    "DATABRICKS_HOST",
    spark.conf.get("spark.databricks.workspaceUrl", "") or "",
)
os.environ["COCO_CATALOG_NAME"] = catalog
os.environ["COCO_SCHEMA_NAME"] = schema
os.environ["COCO_WAREHOUSE_ID"] = warehouse_id
os.environ["COCO_LAKEBASE_INSTANCE"] = lakebase_instance
os.environ["COCO_AGENT_ENDPOINT_NAME"] = agent_endpoint
# Per-user MLflow experiment path — prevents attendees from racing
# on the same `/Shared/coco-agent` experiment. Picked up by
# config.mlflow.experiment_name via the ${COCO_MLFLOW_EXPERIMENT:...}
# interpolation in config/default.yaml.
os.environ["COCO_MLFLOW_EXPERIMENT"] = f"/Users/{_user_email}/coco-agent"
print(f"  mlflow_experiment: {os.environ['COCO_MLFLOW_EXPERIMENT']}")

# Create catalog. On Default Storage workspaces, even
# CREATE CATALOG IF NOT EXISTS fails for catalogs that already exist
# (the storage check runs regardless of IF NOT EXISTS). So we check
# existence first via SDK, and only try CREATE if it really is missing.
from databricks.sdk import WorkspaceClient

_ws = WorkspaceClient()
_existing_catalogs = [c.name for c in _ws.catalogs.list()]

if catalog in _existing_catalogs:
    print(f"Catalog '{catalog}' already exists, skipping creation.")
else:
    print(f"Catalog '{catalog}' does not exist, creating...")
    try:
        spark.sql(f"CREATE CATALOG {catalog}")
        print(f"Catalog '{catalog}' created (via SQL).")
    except Exception as cat_err:
        err_str = str(cat_err)
        is_default_storage = "storage root URL" in err_str or "Default Storage" in err_str
        if is_default_storage:
            # Try SDK path. On Default Storage this usually also fails,
            # but worth a shot on workspaces with a configured fallback.
            try:
                _ws.catalogs.create(name=catalog, comment="CoCo cohort copilot data")
                print(f"Catalog '{catalog}' created (via SDK).")
            except Exception:
                avail = ", ".join(c for c in _existing_catalogs if c not in ("system", "samples"))
                msg = (
                    f"Catalog '{catalog}' does not exist and cannot be auto-created on this "
                    f"workspace (Default Storage is enabled, so CREATE CATALOG needs an "
                    f"explicit MANAGED LOCATION).\n\n"
                    f"Fix one of two ways:\n\n"
                    f"1. Pre-create the catalog in the UI, then re-run the job:\n"
                    f"   Catalog > + > Create catalog > name it '{catalog}'\n\n"
                    f"2. Re-deploy the bundle pointing at an existing catalog you have "
                    f"CREATE SCHEMA on:\n"
                    f"   databricks bundle deploy -t demo -p <profile> --var catalog=<name>\n\n"
                    f"Available catalogs on this workspace: {avail}"
                )
                raise RuntimeError(msg) from None
        else:
            raise cat_err

# Create schema
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
print(f"Schema '{catalog}.{schema}' ensured.")

# Create volumes
knowledge_vol = "coco_knowledge"
artifacts_vol = "coco_artifacts"

spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.{knowledge_vol}")
print(f"Volume '{catalog}.{schema}.{knowledge_vol}' ensured.")

spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.{artifacts_vol}")
print(f"Volume '{catalog}.{schema}.{artifacts_vol}' ensured.")

print("\nUC structure created successfully.")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 3: Generate Synthetic RWD Data
# MAGIC
# MAGIC Generate 10,000 synthetic patients with realistic clinical data:
# MAGIC - Patients (demographics, age, state)
# MAGIC - Diagnoses (ICD-10 codes with clinical correlations)
# MAGIC - Prescriptions (NDC codes with drug classes)
# MAGIC - Procedures (CPT codes)
# MAGIC - Claims (cost, date range, utilization)
# MAGIC - Suppliers (provider/facility data)

# COMMAND ----------
from coco.data_generator.generate import generate_all_tables
from coco.data_generator.spark_writer import write_tables_to_catalog

# Generate synthetic data (deterministic with seed=42)
print("Generating synthetic RWD data for 10,000 patients...")
tables = generate_all_tables(
    num_patients=10000, num_suppliers=25, seed=42, start_date="2020-01-01", end_date="2025-12-31"
)

print(f"Generated tables: {list(tables.keys())}")
for table_name, rows in tables.items():
    print(f"  {table_name}: {len(rows)} rows")

# Write to Databricks UC
print(f"\nWriting tables to {catalog}.{schema}...")
write_tables_to_catalog(tables, catalog, schema, spark)

# Verify and print row counts
print("\nVerifying row counts in UC:")
for table_name in ["patients", "diagnoses", "prescriptions", "procedures", "claims", "suppliers"]:
    count = spark.sql(f"SELECT COUNT(*) as cnt FROM {catalog}.{schema}.{table_name}").collect()[0][
        "cnt"
    ]
    print(f"  {table_name}: {count} rows")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 4: Upload Knowledge Docs and Create Knowledge Chunks Table
# MAGIC
# MAGIC Upload markdown files from the repo to the knowledge volume and create
# MAGIC a `knowledge_chunks` table with CDF enabled for Vector Search synchronization.

# COMMAND ----------
import json
import os
from uuid import uuid4

# Find all markdown files in knowledge directory
knowledge_dir = f"{agent_repo_volume}/src/coco/knowledge"
markdown_files = []

for root, dirs, files in os.walk(knowledge_dir):
    for file in files:
        if file.endswith(".md"):
            markdown_files.append(os.path.join(root, file))

print(f"Found {len(markdown_files)} markdown files:")
for file in sorted(markdown_files):
    print(f"  {file}")

# Read and upload each file to UC volume
knowledge_vol_path = f"/Volumes/{catalog}/{schema}/{knowledge_vol}"
os.makedirs(knowledge_vol_path, exist_ok=True)

# Also collect all content for chunking
all_docs = {}
for file_path in markdown_files:
    with open(file_path, "r") as f:
        content = f.read()

    # Get relative path for doc_name
    doc_name = os.path.relpath(file_path, knowledge_dir)
    all_docs[doc_name] = content

    # Upload to volume
    vol_dest = os.path.join(knowledge_vol_path, doc_name)
    os.makedirs(os.path.dirname(vol_dest), exist_ok=True)
    with open(vol_dest, "w") as f:
        f.write(content)

    print(f"Uploaded {doc_name}")

print(f"\nKnowledge docs uploaded to {knowledge_vol_path}")

# COMMAND ----------
# Create knowledge_chunks table by splitting markdown files into chunks
# Each chunk is ~512 tokens (approximate: 1 token ≈ 4 chars)


def chunk_markdown(content, doc_name, chunk_size=2000):
    """Split markdown by headings into semantic chunks (~512 tokens)."""
    chunks = []
    lines = content.split("\n")
    current_chunk = []
    current_size = 0

    for line in lines:
        line_size = len(line)

        # Start new chunk at headings if current chunk is substantial
        if line.startswith("#") and current_size > chunk_size and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_size = line_size
        else:
            current_chunk.append(line)
            current_size += line_size

    # Add final chunk
    if current_chunk:
        chunks.append("\n".join(current_chunk))

    # Create chunk objects with metadata
    chunk_objects = []
    for i, chunk_text in enumerate(chunks):
        if chunk_text.strip():  # Skip empty chunks
            # Flatten metadata into scalar columns — Databricks Vector Search
            # rejects map<string,string> columns on the source table, so the
            # chunk table stores metadata as int / string fields directly.
            chunk_obj = {
                "chunk_id": str(uuid4()),
                "doc_name": doc_name,
                "content": chunk_text.strip(),
                "chunk_order": i,
                "chunk_size": len(chunk_text),
                "language": "markdown",
            }
            chunk_objects.append(chunk_obj)

    return chunk_objects


# Generate all chunks
all_chunks = []
for doc_name, content in all_docs.items():
    chunks = chunk_markdown(content, doc_name)
    all_chunks.extend(chunks)
    print(f"{doc_name}: {len(chunks)} chunks")

print(f"\nTotal chunks: {len(all_chunks)}")

# Create DataFrame and write to UC. No explicit path — UC managed tables
# own their storage location. overwriteSchema=true lets re-runs swap
# the column layout (the old version of this notebook wrote a
# metadata<map> column that Vector Search rejects — we now store
# chunk_order / chunk_size / language as scalars).
chunks_df = spark.createDataFrame(all_chunks)
chunks_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{catalog}.{schema}.knowledge_chunks",
)

print(f"knowledge_chunks table created with {len(all_chunks)} chunks")

# COMMAND ----------
# Enable Change Data Feed on knowledge_chunks table (required for Vector Search)
spark.sql(
    f"ALTER TABLE {catalog}.{schema}.knowledge_chunks SET TBLPROPERTIES (delta.enableChangeDataFeed = true)"
)
print("Change Data Feed enabled on knowledge_chunks table.")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 5: Create Vector Search Endpoint and Index
# MAGIC
# MAGIC Create a Databricks Vector Search endpoint and Delta Sync index
# MAGIC with managed embeddings using `databricks-bge-large-en`.

# COMMAND ----------
# Use the databricks-sdk (always available) instead of the separate
# databricks-vectorsearch package, which has a Python namespace
# collision with databricks-sdk on serverless after kernel restart.
from databricks.sdk import WorkspaceClient as _VSWorkspaceClient
from databricks.sdk.service.vectorsearch import EndpointType

_vs_ws = _VSWorkspaceClient()

# Create endpoint (idempotent)
print(f"Provisioning Vector Search endpoint: {vs_endpoint}")
try:
    _vs_ws.vector_search_endpoints.get_endpoint(vs_endpoint)
    print(f"Endpoint '{vs_endpoint}' already exists.")
except Exception:
    print(f"Creating endpoint '{vs_endpoint}'...")
    _vs_ws.vector_search_endpoints.create_endpoint_and_wait(
        name=vs_endpoint,
        endpoint_type=EndpointType.STANDARD,
    )
    print("Endpoint created.")

# COMMAND ----------
# Create the Delta Sync index over knowledge_chunks.
vs_index_name = f"{catalog}.{schema}.coco_knowledge_idx"
vs_source_table = f"{catalog}.{schema}.knowledge_chunks"
index_name = vs_index_name  # used downstream in setup_output regardless

if minimal:
    print("minimal=true: skipping Vector Search index creation.")
else:
    print(f"Provisioning Vector Search index: {vs_index_name}")
    print(f"  source: {vs_source_table}")
    print("  primary_key: chunk_id, embedding_source: content")

    from coco.config import get_config as _get_coco_config

    _vs_cfg = _get_coco_config().vector_search
    _embed_model = _vs_cfg.embedding_model

    print(f"  embedding model: {_embed_model}")

    try:
        _vs_ws.vector_search_indexes.get_index(index_name=vs_index_name)
        print(f"Index '{vs_index_name}' already exists.")
    except Exception:
        # SDK versions differ in their API shapes. Use the REST API
        # directly for maximum compatibility across workspace runtimes.
        import json

        _vs_body = {
            "name": vs_index_name,
            "endpoint_name": vs_endpoint,
            "primary_key": "chunk_id",
            "index_type": "DELTA_SYNC",
            "delta_sync_index_spec": {
                "source_table": vs_source_table,
                "pipeline_type": "TRIGGERED",
                "embedding_source_columns": [
                    {
                        "name": "content",
                        "embedding_model_endpoint_name": _embed_model,
                    }
                ],
            },
        }
        _vs_resp = _vs_ws.api_client.do(
            "POST",
            "/api/2.0/vector-search/indexes",
            body=_vs_body,
        )
        print(f"Index creation initiated: {_vs_resp.get('name', vs_index_name)}")
        print("It will sync in the background.")

    # Describe the final state so the notebook output captures it.
    print("\nIndex describe():")
    try:
        _idx_info = _vs_ws.vector_search_indexes.get_index(index_name=vs_index_name)
        _idx_status = getattr(_idx_info, "status", None)
        if _idx_status:
            print(f"  ready: {getattr(_idx_status, 'ready', '?')}")
            print(f"  indexed_rows: {getattr(_idx_status, 'indexed_row_count', '?')}")
        else:
            print(f"  index found: {vs_index_name}")
    except Exception as e:
        print(f"  describe() failed (non-fatal): {e}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 6: Provision Lakebase Instance and Run Schema
# MAGIC
# MAGIC Provision a Lakebase (Postgres) instance via the Databricks SDK,
# MAGIC wait for it to reach AVAILABLE, generate a short-lived database
# MAGIC credential, and run the session-state DDL (threads, messages, runs,
# MAGIC feedback). All steps are idempotent.

# COMMAND ----------
# Use REST API for Lakebase operations to avoid SDK version mismatches
# on serverless (databricks.sdk.service.database may not exist in the
# pre-installed SDK version).
import time

import psycopg
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

if not lakebase_instance or not lakebase_instance.strip():
    raise ValueError(
        "lakebase_instance is empty. Pass --var lakebase_instance=<name> "
        "to the bundle deploy/run command."
    )

print(f"Checking Lakebase instance: {lakebase_instance}")

lakebase_dns = None


def _lb_get(name):
    return w.api_client.do("GET", f"/api/2.0/database/instances/{name}")


def _lb_create(name, capacity="CU_1"):
    return w.api_client.do(
        "POST",
        "/api/2.0/database/instances",
        body={
            "name": name,
            "capacity": capacity,
        },
    )


def _lb_start(name):
    return w.api_client.do(
        "PATCH",
        f"/api/2.0/database/instances/{name}",
        body={
            "stopped": False,
        },
    )


try:
    inst = _lb_get(lakebase_instance)
    print(f"Found existing instance '{lakebase_instance}' state={inst.get('state')}")
    if inst.get("effective_stopped"):
        print("Instance is stopped; starting it...")
        _lb_start(lakebase_instance)
    lakebase_dns = inst.get("read_write_dns")
except Exception as e:
    print(f"Instance not found ({e.__class__.__name__}); creating '{lakebase_instance}' (CU_1)...")
    try:
        _lb_create(lakebase_instance)
        print("Create request submitted.")
    except Exception as create_err:
        print(
            f"Could not create Lakebase instance automatically: {create_err}\n"
            f"Ask a workspace admin to create a CU_1 Lakebase instance "
            f"named '{lakebase_instance}' and re-run this cell."
        )
        raise

# Wait for AVAILABLE
deadline = time.time() + 300
while time.time() < deadline:
    inst = _lb_get(lakebase_instance)
    state = inst.get("state", "")
    if state == "AVAILABLE":
        lakebase_dns = inst.get("read_write_dns")
        print(f"Instance AVAILABLE: {lakebase_dns}")
        break
    print(f"  state={state}; waiting...")
    time.sleep(10)
else:
    raise RuntimeError(
        f"Lakebase instance '{lakebase_instance}' did not reach AVAILABLE within 5 minutes"
    )

# COMMAND ----------
# Create the Postgres database. We deliberately DO NOT create the
# `coco_sessions` schema or tables here.
#
# Why: Databricks Apps binds the app's SP to this database with
# CAN_CONNECT_AND_CREATE, which translates to CONNECT + CREATE on the
# database itself. On first request, the app runs `ensure_schema()`
# which does `CREATE SCHEMA IF NOT EXISTS coco_sessions` — and because
# the SP creates it, the SP owns it, and every subsequent
# `CREATE TABLE` / `CREATE INDEX IF NOT EXISTS` inside that schema
# succeeds without further grants.
#
# If we pre-create the schema here as the workshop user, the SP inherits
# USAGE but not OWNERSHIP, so `CREATE INDEX IF NOT EXISTS` fails with
# "must be owner of table threads". Transferring ownership after the
# fact requires ADMIN OPTION on the SP role, which the workshop user
# doesn't have. So the turnkey path is: provision the database only,
# let the app do its own schema bootstrap.

lakebase_db_name = "coco"

admin_connstr_defaults = f"host={lakebase_dns} port=5432 sslmode=require"
pg_user = w.current_user.me().user_name
print(f"Postgres user: {pg_user}")

# Use REST API for credential generation (avoids SDK database module)
_cred_resp = w.api_client.do(
    "POST",
    "/api/2.0/database/credentials",
    body={
        "instance_names": [lakebase_instance],
        "request_id": str(uuid4()),
    },
)
_pg_token = _cred_resp.get("token", "")
if not _pg_token:
    raise RuntimeError("generate_database_credential returned empty token")
print("Database credential minted.")

# Create the 'coco' database if missing (connect to the default 'postgres')
with psycopg.connect(
    f"{admin_connstr_defaults} dbname=postgres user={pg_user} password={_pg_token}",
    autocommit=True,
) as admin_conn:
    exists = admin_conn.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s",
        (lakebase_db_name,),
    ).fetchone()
    if not exists:
        print(f"Creating database '{lakebase_db_name}'...")
        admin_conn.execute(f'CREATE DATABASE "{lakebase_db_name}"')
    else:
        print(f"Database '{lakebase_db_name}' already exists")

# If a prior run of this notebook (or a manual debug session) created
# `coco_sessions` owned by the workshop user, the app SP will hit
# "must be owner" errors on startup. Drop it so the SP can recreate
# it cleanly from scratch. Safe because all session state (threads,
# messages, feedback) is recoverable from MLflow traces + the UI is
# brand-new per workshop.
#
# Use try/except instead of comparing nspowner::regrole::text to
# pg_user, because the regrole textual form quotes emails ('"user@x"')
# but pg_user does not, which makes exact-string matches brittle.
# Semantics: DROP succeeds if we own the schema (broken state → clean
# up); fails with InsufficientPrivilege if we don't (healthy state,
# schema owned by the SP → leave it); fails with InvalidSchemaName if
# it doesn't exist yet (first-time deploy → app will create it).
with psycopg.connect(
    f"{admin_connstr_defaults} dbname={lakebase_db_name} user={pg_user} password={_pg_token}",
    autocommit=True,
) as cleanup_conn:
    try:
        cleanup_conn.execute("DROP SCHEMA coco_sessions CASCADE")
        print(
            "Dropped stale coco_sessions schema (previously owned by the "
            "workshop user). App SP will recreate it on first request."
        )
    except psycopg.errors.InsufficientPrivilege:
        print(
            "coco_sessions exists and is owned by another role (likely the "
            "app SP); leaving it in place."
        )
    except psycopg.errors.InvalidSchemaName:
        print("No pre-existing coco_sessions schema; app SP will create it.")

print(f"Lakebase ready: {lakebase_dns}/{lakebase_db_name}")
print("Session schema will be created by the app SP on first request.")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 7: Deploy Agent to Model Serving
# MAGIC
# MAGIC Deploy the CoCo agent to a Databricks Model Serving endpoint.
# MAGIC This endpoint will serve inference requests during the workshop.

# COMMAND ----------
# Run the agent deploy IN-PROCESS inside the notebook kernel. The earlier
# subprocess version broke MLflow auth: child processes don't inherit the
# notebook's implicit Databricks credential context, so mlflow.set_experiment
# fails with "Reading Databricks credential configuration failed". In-process
# inherits the notebook's credentials for free and is simpler.
# Register default prompts to MLflow Prompt Registry. Existing prompts
# are skipped, so this is idempotent. The agent loads instructions from
# the registry at runtime, allowing prompt updates without redeploying.
import mlflow

mlflow.set_tracking_uri("databricks")
mlflow.set_registry_uri("databricks-uc")

from coco.agent.prompts import register_defaults

registered = register_defaults()
print(f"Prompt Registry: {len(registered)} prompts registered: {list(registered.values())}")

# COMMAND ----------
print(f"Deploying agent to Model Serving endpoint: {agent_endpoint}")
print(f"Using codebase from: {agent_repo_volume}")

from coco.agent.deploy import deploy_agent

deploy_agent()

print(f"\nAgent endpoint name: {agent_endpoint}")

# COMMAND ----------
# Wait for the CoCo agent endpoint to reach READY, then smoke-test it.
import time

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

print(f"Waiting for Model Serving endpoint '{agent_endpoint}' to be ready...")
max_wait = 1800  # up to 30 minutes — first-build serving containers with
# heavy pip_requirements (mlflow, dspy, pyarrow, pandas, databricks-agents)
# regularly take 15-25 min to compile the base image. Earlier 600s ceiling
# was too aggressive and produced false negatives.
start_time = time.time()
endpoint = None

while time.time() - start_time < max_wait:
    try:
        endpoint = w.serving_endpoints.get(agent_endpoint)
        # EndpointState.ready is an enum: READY | NOT_READY
        ready_value = getattr(endpoint.state.ready, "value", str(endpoint.state.ready))
        if ready_value == "READY":
            print("Endpoint is READY.")
            break
        print(
            f"  state.ready={ready_value}; state.config_update={endpoint.state.config_update}; waiting..."
        )
    except Exception as e:
        print(f"  checking endpoint status: {e.__class__.__name__}: {e}")
    time.sleep(15)
else:
    raise RuntimeError(
        f"Model Serving endpoint '{agent_endpoint}' did not reach READY within {max_wait}s. "
        f"Check the Model Serving page in the Databricks UI."
    )

# Build the real invocation URL. Serving endpoints are always at
# https://{host}/serving-endpoints/{name}/invocations — the workload_size
# field on served_entities is just a sizing label ("Small", "Medium"), NOT a URL.
workspace_host = w.config.host.rstrip("/")
if not workspace_host.startswith("http"):
    workspace_host = f"https://{workspace_host}"
agent_endpoint_url = f"{workspace_host}/serving-endpoints/{agent_endpoint}/invocations"
print(f"Agent endpoint URL: {agent_endpoint_url}")

# Smoke test — call the LLM route (not the agent endpoint) via the
# reconciled GatewayClient. With the workshop config, gateway_route is
# the Claude Sonnet 4.5 serving endpoint name, so this exercises the
# same path the agent itself uses at runtime.
print("\nSmoke test: calling LLM via GatewayClient.call_llm...")
import os as _os

_os.environ.setdefault("DATABRICKS_HOST", workspace_host)
_os.environ.setdefault("COCO_CONFIG_PATH", f"{agent_repo_volume}/config/default.yaml")

try:
    from coco.gateway.client import GatewayClient

    gateway = GatewayClient()
    reply = gateway.call_llm(
        system_prompt="You are a terse health informatics assistant.",
        user_message="Reply with exactly the single word OK.",
        max_tokens=10,
    )
    print(f"  LLM reply: {reply!r}")
    print("Smoke test passed.")
except Exception as e:
    # Don't fail the notebook on smoke test — the agent endpoint itself
    # is still deployed. Log and let the deployer investigate.
    print(f"Smoke test failed (not fatal): {e.__class__.__name__}: {e}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 9: Create and Deploy the Databricks App
# MAGIC
# MAGIC The FastAPI + HTMX front-end that users click to use CoCo.
# MAGIC The App was deliberately NOT included in the bundle-level resources
# MAGIC because it binds to the coco-agent serving endpoint, which doesn't
# MAGIC exist until Step 7 creates it. Now that the endpoint is live, we can
# MAGIC create the App with the right typed resource bindings.

# COMMAND ----------
from databricks.sdk.service.apps import (
    App,
    AppDeployment,
    AppDeploymentMode,
    AppResource,
    AppResourceDatabase,
    AppResourceDatabaseDatabasePermission,
    AppResourceServingEndpoint,
    AppResourceServingEndpointServingEndpointPermission,
    AppResourceSqlWarehouse,
    AppResourceSqlWarehouseSqlWarehousePermission,
)

# app_name is read from the widget declared at the top of the notebook.
# source_code_path is the repo root (where app.yaml + requirements.txt
# live). Databricks Apps auto-installs from requirements.txt and the
# app.yaml command uses `--app-dir src` to add the coco package root
# to sys.path.
app_source_code_path = agent_repo_volume

app_resources = [
    AppResource(
        name="warehouse_id",
        description="SQL Warehouse for the Statement Execution API",
        sql_warehouse=AppResourceSqlWarehouse(
            id=warehouse_id,
            permission=AppResourceSqlWarehouseSqlWarehousePermission.CAN_USE,
        ),
    ),
    AppResource(
        name="agent_endpoint_url",
        description="CoCo agent Model Serving endpoint",
        serving_endpoint=AppResourceServingEndpoint(
            name=agent_endpoint,
            permission=AppResourceServingEndpointServingEndpointPermission.CAN_QUERY,
        ),
    ),
    # Lakebase session store via the typed database binding. At deploy
    # time, the Apps platform creates a Postgres role for the app's SP
    # and injects PG* env vars into the container. The resource name
    # `postgres` matches the Autoscaling default per the docs.
    #
    # NOTE: the user running this notebook must have CAN_MANAGE on the
    # Lakebase instance (Step 6 created it under their identity, so this
    # is automatic for deployers).
    AppResource(
        name="postgres",
        description="Lakebase Postgres for thread/message state",
        database=AppResourceDatabase(
            instance_name=lakebase_instance,
            database_name=lakebase_db_name,
            permission=AppResourceDatabaseDatabasePermission.CAN_CONNECT_AND_CREATE,
        ),
    ),
]

# CoCo does not use on-behalf-of (OBO) user tokens — every data access
# is made by the app's SP, whose permissions are granted explicitly
# through the `resources` list above (warehouse CAN_USE, endpoint
# CAN_QUERY, database CAN_CONNECT_AND_CREATE). So we ship the app
# WITHOUT `user_api_scopes`.
#
# Why this matters for the workshop: including `user_api_scopes`
# triggers the OAuth consent flow on the first page load, which on
# workspaces without token-passthrough enabled (some
# deployments) fails with an opaque "Something went wrong" screen.
# Skipping scopes makes the app loadable on every workspace where the
# Databricks Apps feature is enabled at all.
#
# If you later add an OBO-dependent feature (e.g., querying UC tables
# AS the end user instead of as the SP), add the needed scopes to
# `user_api_scopes` below AND ensure the target workspace has token
# passthrough turned on in admin settings.

app_spec = App(
    name=app_name,
    description="CoCo - Cohort Copilot for healthcare RWD",
    default_source_code_path=app_source_code_path,
    resources=app_resources,
)

app_url = None
print(f"Ensuring Databricks App: {app_name}")
try:
    try:
        existing = w.apps.get(name=app_name)
        print(
            f"App '{app_name}' already exists (status={existing.app_status}); updating source path."
        )
        w.apps.update(name=app_name, app=app_spec)
    except Exception as e:
        print(f"App not found ({e.__class__.__name__}); creating...")
        w.apps.create_and_wait(app=app_spec)
        print(f"App '{app_name}' created.")

    print(f"Deploying source from: {app_source_code_path}")
    deployment = w.apps.deploy_and_wait(
        app_name=app_name,
        app_deployment=AppDeployment(
            source_code_path=app_source_code_path,
            mode=AppDeploymentMode.SNAPSHOT,
        ),
    )
    print(f"App deployment complete: id={deployment.deployment_id}, status={deployment.status}")

    final_app = w.apps.get(name=app_name)
    app_url = final_app.url
    print(f"\nApp URL: {app_url}")
except Exception as app_err:
    print(
        f"\nWARNING: Could not deploy Databricks App: {app_err}\n"
        f"This is usually a workspace feature flag issue (token passthrough).\n"
        f"The agent endpoint is deployed and working -- you can query it directly:\n"
        f"  POST {agent_endpoint_url}\n"
        f"To deploy the UI app, ask your workspace admin to enable Databricks Apps.\n"
    )
    app_url = "(app not deployed -- see warning above)"

# COMMAND ----------
# MAGIC %md
# MAGIC ## Setup Complete
# MAGIC
# MAGIC All infrastructure is provisioned. Next steps:
# MAGIC 1. Open the App URL from `setup_complete.json` in your browser
# MAGIC 2. Ask a cohort question (e.g. "Type 2 diabetes patients on metformin")
# MAGIC 3. View the MLflow trace for your query under `/Users/<your-email>/coco-agent`

# COMMAND ----------
from datetime import datetime

# Collect all outputs. workspace_host, lakebase_dns, and agent_endpoint_url
# were set in earlier cells (Steps 6 and 7).
setup_output = {
    "catalog": catalog,
    "schema": schema,
    "warehouse_id": warehouse_id,
    "workspace_host": workspace_host,
    "lakebase_instance": lakebase_instance,
    "lakebase_host": lakebase_dns,
    "lakebase_database": lakebase_db_name,
    "lakebase_schema": "coco_sessions",  # created by the app SP on first request
    "vs_endpoint": vs_endpoint,
    "vs_index": index_name,
    "agent_endpoint_name": agent_endpoint,
    "agent_endpoint_url": agent_endpoint_url,
    "app_name": app_name,
    "app_url": app_url,
    "knowledge_chunks_count": len(all_chunks),
    "patients_count": 10000,
    "setup_ts": datetime.utcnow().isoformat() + "Z",
}

# Write to UC artifacts volume
artifacts_path = f"/Volumes/{catalog}/{schema}/{artifacts_vol}"
os.makedirs(artifacts_path, exist_ok=True)

setup_json_path = os.path.join(artifacts_path, "setup_complete.json")
with open(setup_json_path, "w") as f:
    json.dump(setup_output, f, indent=2)

print("Setup complete! Configuration saved to setup_complete.json")
print("\n" + "=" * 60)
print("SETUP_COMPLETE.JSON")
print("=" * 60)
print(json.dumps(setup_output, indent=2))
print("=" * 60)

print(f"\nFile location: {setup_json_path}")
print("Share this configuration with the Databricks platform team.")
print("\nNext steps:")
print("  1. Dry-run workshop call Monday 4/21 afternoon")
print("  2. Workshop Tuesday 4/22")
