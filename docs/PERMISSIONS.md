# Permissions Required for End-to-End CoCo Deployment

This document lists every permission your identity (user or service
principal) needs to run `databricks bundle deploy` + `bundle run
setup_workspace` and get a working CoCo app from a clean workspace.

If any of these are missing, the setup notebook will fail at a
specific step. The table below maps each permission to the step
that needs it so you can request exactly what you need from your
workspace admin.

## Quick checklist

Before running the setup, confirm you have:

- [ ] Workspace admin OR the specific permissions listed below
- [ ] A serverless SQL warehouse (note the ID)
- [ ] `databricks-claude-sonnet-4-6` (or equivalent) FMAPI endpoint available
- [ ] Databricks CLI installed + profile configured (`databricks auth login`)

## Permissions by resource

### Unity Catalog

| Permission | What it allows | Setup step | How to grant |
|-----------|---------------|------------|-------------|
| `CREATE CATALOG` | Create the `coco_demo` catalog | Step 2 | Account admin grants on the metastore |
| `USE CATALOG` on `coco_demo` | Access the catalog after creation | Step 2+ | Auto-granted to creator |
| `CREATE SCHEMA` in `coco_demo` | Create `cohort_builder_<id>` schema | Step 2 | Auto-granted to catalog creator |
| `CREATE TABLE` in the schema | Create patient/diagnosis/claims tables | Step 3 | Auto-granted to schema creator |
| `CREATE VOLUME` in the schema | Create `coco_knowledge` + `coco_artifacts` volumes | Step 2 | Auto-granted to schema creator |
| `CREATE FUNCTION` in the schema | Register UC functions (if used) | Optional | Auto-granted to schema creator |

**If you cannot create catalogs:** Ask your admin to create `coco_demo` for you and grant you `USE CATALOG` + `CREATE SCHEMA` on it. Then pass `--var catalog=coco_demo` to the bundle commands.

### SQL Warehouse

| Permission | What it allows | Setup step |
|-----------|---------------|------------|
| `CAN_USE` on the serverless warehouse | Run SQL queries via Statement Execution API | Step 3 (data gen), Step 7 (agent) |

**How to grant:** Workspace UI -> SQL Warehouses -> select warehouse -> Permissions -> add your user with "Can Use"

### Model Serving (FMAPI)

| Permission | What it allows | Setup step |
|-----------|---------------|------------|
| `CAN_QUERY` on `databricks-claude-sonnet-4-6` | LLM calls from the agent | Step 7 (agent deploy) |
| `CAN_MANAGE` serving endpoints (or workspace admin) | Create the `coco-agent-<id>` endpoint | Step 7 |

**How to grant:** ML -> Serving -> endpoint -> Permissions -> add your user

### MLflow

| Permission | What it allows | Setup step |
|-----------|---------------|------------|
| Create experiments under `/Shared/` | Log agent model + traces | Step 7 |
| Register models in UC | `coco_demo.cohort_builder_<id>.coco_agent_<id>` | Step 7 |

**Usually auto-granted.** MLflow experiment creation and UC model registration are available to all workspace users by default.

### Lakebase (Managed Postgres)

| Permission | What it allows | Setup step |
|-----------|---------------|------------|
| Create database instances | Provision a new Lakebase instance | Step 6 |
| Create databases on the instance | Create the `coco_<id>` database | Step 6 |

**How to grant:** This requires the `databricks.database` API permission. On some workspaces, only admins can create Lakebase instances. Ask your admin to either:
- Grant you Lakebase instance creation permission, OR
- Create the instance for you and pass `--var lakebase_instance=<name>` to the bundle commands

### Vector Search

| Permission | What it allows | Setup step |
|-----------|---------------|------------|
| Create VS endpoints | Provision a new `coco-vs-<id>` endpoint | Step 5 |
| Create VS indexes | Create the `coco_knowledge_idx` delta sync index | Step 5 |

**How to grant:** Usually available to all workspace users. If restricted, ask admin to create the endpoint and pass `--var vs_endpoint=<name>`.

### Databricks Apps

| Permission | What it allows | Setup step |
|-----------|---------------|------------|
| Create Apps | Create the `coco-<id>` Databricks App | Step 9 |
| Deploy Apps | Deploy source snapshots | Step 9 |

**How to grant:** Usually available to all workspace users. If restricted, ask admin to create the App shell and pass `--var app_name=<name>`.

**OBO / user authorization NOT required.** Earlier versions of CoCo listed `user_api_scopes` on the app spec to enable on-behalf-of user token passthrough. The current version does all data access as the app's service principal through typed resource bindings (SQL warehouse `CAN_USE`, agent endpoint `CAN_QUERY`, Lakebase `CAN_CONNECT_AND_CREATE`). So the "User authorization for Databricks Apps" preview flag is **not** a prerequisite for this deployment.

### Workspace Files

| Permission | What it allows | Setup step |
|-----------|---------------|------------|
| Write to `/Workspace/Users/<you>/.bundle/` | Bundle deploy uploads source files | Step 2 (deploy) |

**Auto-granted.** Every user can write to their own workspace directory.

## Minimum viable permissions (if you are NOT an admin)

If your workspace admin is restrictive, the absolute minimum you
need them to pre-provision:

1. **A catalog** (`coco_demo`) with `USE CATALOG` + `CREATE SCHEMA` granted to you
2. **A serverless SQL warehouse** with `CAN_USE` granted to you
3. **`CAN_QUERY` on `databricks-claude-sonnet-4-6`** serving endpoint
4. **A Lakebase instance** (if you can't create one yourself)

Everything else (schema, tables, volumes, VS endpoint, agent
endpoint, app) is created by the setup notebook using your identity.

## Service principal permissions (for production)

For `prod` target deployments, the service principal
(`coco-service-principal`) needs the same permissions listed above,
plus:

- `CAN_MANAGE` on the serving endpoint (to deploy new model versions)
- `CAN_MANAGE` on the Databricks App (to deploy source snapshots)
- `USE CATALOG` + `USE SCHEMA` + `SELECT` on all cohort tables

## Verifying your permissions

Run this from your terminal to check the basics:

```bash
# Replace PROFILE with your CLI profile name
databricks current-user me -p PROFILE          # should show your username
databricks catalogs list -p PROFILE            # should include your catalogs
databricks warehouses list -p PROFILE          # should show your warehouse
databricks serving-endpoints list -p PROFILE   # should show FMAPI endpoints
```

If any of these fail with 403/permission errors, contact your
workspace admin with the specific permission from the table above.
