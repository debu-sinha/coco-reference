# CoCo v2 Deployment Guide

This guide explains how to deploy CoCo v2 to Databricks workspaces using Databricks Asset Bundles (DABs).

## Prerequisites

1. **Databricks workspace** (AWS/Azure/GCP, version 2024.01+)
2. **Databricks CLI** v0.220+
   ```bash
   pip install databricks-cli>=0.220
   ```
3. **Repository cloned** locally
4. **Permissions in workspace:**
   - Create UC catalogs/schemas
   - Create SQL warehouses
   - Create Model Serving endpoints
   - Deploy apps

## Architecture Targets

Four deployment targets are defined in `databricks.yml`:

### `demo` (Default, Development)
- User-based authentication (your Databricks user)
- App uses SSO/token from workspace
- Scale-to-zero **disabled** (keeps endpoint warm)
- Good for: Workshops, demos, single-user testing
- Cost: Higher (always-on endpoint)

### `dev` (Development with Auto-scaling)
- User-based authentication
- Scale-to-zero **enabled** (costs less)
- Auto-scaling (1-4 replicas)
- Good for: Team development, testing
- Cost: Lower (scales down idle time)

### `staging` (Pre-production)
- User-based authentication
- Full auto-scaling
- Good for: Integration testing, load testing
- Cost: Pay-per-use

### `prod` (Production)
- **Service principal authentication** (requires setup)
- Auto-scaling enabled
- All jobs run as service principal
- Good for: Production deployments
- Cost: Pay-per-use, but more secure

## Initial Setup

### 1. Clone Repository

```bash
git clone <repo-url> coco-reference
cd coco-reference
```

### 2. Install Databricks CLI

```bash
pip install databricks-cli>=0.220
```

### 3. Configure Databricks Connection

```bash
# Interactive login
databricks auth login

# Or set via environment
export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
export DATABRICKS_TOKEN=dapi...
```

## Deploying to `demo` (Recommended First)

### Step 1: Configure Variables

Edit `databricks.yml` or override via CLI:

```bash
# Option A: Edit databricks.yml directly
# Change warehouse_id, lakebase_instance, agent_endpoint, vs_endpoint

# Option B: Use CLI (recommended)
export COCO_WAREHOUSE_ID="<your-warehouse-id>"
export COCO_LAKEBASE_INSTANCE="coco-sessions"
export COCO_VS_ENDPOINT="coco-vs"
```

### Step 2: Run Setup Notebook

Before deploying the DAB, provision the workspace once:

```bash
# In Databricks workspace UI:
# 1. Create new notebook
# 2. Import: notebooks/00_setup_workspace.py
# 3. Attach to 2-worker i3.xlarge cluster
# 4. Run all cells
# 5. Save setup_complete.json
```

The notebook:
- Creates UC catalog + schema + volumes
- Generates 10k synthetic patients
- Creates Vector Search index
- Creates Lakebase database
- Returns resource IDs in `setup_complete.json`

### Step 3: Deploy DAB

```bash
# Deploy to demo target
databricks bundle deploy -t demo

# Enter configuration values when prompted:
# - catalog: coco_demo (from setup_complete.json)
# - schema: cohort_builder (from setup_complete.json)
# - warehouse_id: sql-xxx (from setup_complete.json)
# - agent_endpoint_url: https://.../endpoints/coco-agent
```

Output:
```
Deploying resources...
- app coco_app
- job setup_workspace
- job run_evaluation   (notebook 02, mlflow.genai.evaluate)
- job optimize_dspy       (notebook 03, mlflow.genai.optimize_prompts + GEPA against Lakebase feedback)
- job teardown_workspace  (notebook 99, removes every per-user resource)
Deployment successful!
```

### Step 4: Access App

```bash
# Get app URL
databricks bundle get-summary -t demo | grep app_url

# Or in Databricks workspace:
# Workspace > Apps > CoCo - Cohort Copilot
```

## Deploying to `prod`

### Prerequisites for Production

1. **Create service principal in workspace:**
   ```bash
   # In Databricks workspace > Admin Console > Service Principals
   # Create: coco-service-principal
   # Note: client_id and client_secret
   ```

2. **Grant service principal permissions:**
   - UC catalog owner
   - SQL warehouse user
   - Vector Search admin
   - Model Serving admin
   - Apps deployer

3. **Store credentials securely:**
   ```bash
   export DATABRICKS_CLIENT_ID="<service-principal-id>"
   export DATABRICKS_CLIENT_SECRET="<service-principal-secret>"
   ```

### Deploy to Production

```bash
# With service principal credentials set
databricks bundle deploy -t prod

# All jobs now run as service principal
# App still uses user authentication (SSO)
```

## Post-Deployment

### 1. Verify Deployment

```bash
# Check resources were created
databricks bundle validate -t demo

# View deployment status
databricks bundle get-summary -t demo
```

### 2. Run Setup Job (One-time)

```bash
# Trigger manually (or wait for schedule)
databricks jobs run --job-name setup_workspace

# Check status
databricks jobs get-run --run-id <run-id>
```

### 3. Test Agent Endpoint

```bash
# Query the agent
curl https://<workspace>/api/2.0/endpoints/coco-agent/invocations \
  -H "Authorization: Bearer $DATABRICKS_TOKEN" \
  -d '{"messages": [{"role": "user", "content": "Find diabetes patients"}]}'
```

### 4. Check Logs

```bash
# App logs (in workspace > Apps > CoCo)
# Job logs (in workspace > Jobs > setup_workspace)
# MLflow runs (in workspace > Experiments > /Users/<email>/coco-agent, or /Shared/coco-agent fallback)
```

## Scaling Configurations

### For Small Cohorts (100-1000 patients)

```yaml
# databricks.yml
agent_endpoint:
  min_provisioned_concurrency: 1
  max_provisioned_concurrency: 2
  workload_size: "Small"  # 1 vCPU, 2 GB RAM

sql_warehouse:
  id: <your-pro-warehouse>  # Minimum Pro tier
```

### For Medium Cohorts (1k-100k patients)

```yaml
agent_endpoint:
  min_provisioned_concurrency: 2
  max_provisioned_concurrency: 4
  workload_size: "Medium"  # 2 vCPU, 4 GB RAM

sql_warehouse:
  id: <your-pro-warehouse>  # Pro tier, 1-4 clusters
```

### For Large Cohorts (100k+ patients)

```yaml
agent_endpoint:
  min_provisioned_concurrency: 4
  max_provisioned_concurrency: 8
  workload_size: "Large"  # 4 vCPU, 8 GB RAM

sql_warehouse:
  id: <your-pro-warehouse>  # Pro tier, 2-8 clusters
```

## Troubleshooting

### "Warehouse not found"

```
Error: Warehouse <id> not found or not authorized

Solution:
1. Verify warehouse_id in databricks.yml
2. Check your user has access to the warehouse
3. Run: databricks sql get-warehouse --warehouse-id <id>
```

### "Catalog already exists"

```
Error: RESOURCE_ALREADY_EXISTS: Catalog coco_demo

Solution:
1. Change catalog name in databricks.yml
2. Or: databricks sql delete-catalog --name coco_demo
3. Re-run: databricks bundle deploy -t demo
```

### "App deployment failed"

```
Error: Failed to deploy app: INVALID_PARAMETER_VALUE

Solution:
1. Check agent_endpoint_url is set correctly
2. Verify Model Serving endpoint exists and is running
3. Check app config syntax in databricks.yml
```

### "Job failed to run"

```
Error: Task failed: Setup workspace

Solution:
1. Check job logs in workspace > Jobs > setup_workspace > Runs
2. Verify warehouse is running
3. Check notebook path is correct in databricks.yml
4. Re-run: databricks jobs run --job-name setup_workspace
```

### "Rate limited"

```
Error: 429 Too Many Requests from agent endpoint

Solution:
1. Increase max_provisioned_concurrency in databricks.yml
2. Reduce request rate from clients
3. Implement backoff logic in client code
```

## Updating Deployment

### Update Configuration

```bash
# Edit databricks.yml, then:
databricks bundle deploy -t demo --force-overwrite
```

### Update App Code

```bash
# Edit src/coco/app/*, then:
databricks bundle deploy -t demo
```

### Update Notebooks

```bash
# Edit notebooks/00_setup_workspace.py, then:
databricks bundle deploy -t demo
# Re-run jobs to pick up new notebook version
```

## Rollback

### Rollback to Previous Deployment

```bash
# DAB tracks deployments, but Git is primary source of truth
git checkout <previous-commit>
databricks bundle deploy -t demo
```

### Delete Deployment

```bash
# Remove all deployed resources
databricks bundle destroy -t demo

# WARNING: This deletes apps, jobs, and schedules
# (Does NOT delete UC catalog/data)
```

## Monitoring

### View Logs

```bash
# App logs
databricks workspace get-status /Users/<your-id>/Workspace/coco-app.log

# Job logs
databricks jobs get-run-output --run-id <run-id>
```

### Check Metrics

```bash
# In Databricks workspace:
# 1. Go to Apps > CoCo - Cohort Copilot > Logs
# 2. Go to Jobs > run_evaluation > Latest Run
# 3. Go to Experiments > /Users/<email>/coco-agent > Runs (shared fallback: /Shared/coco-agent)
```

### Monitor Costs

```bash
# SQL Warehouse usage
# Check workspace > SQL > Warehouses > <warehouse> > Query History

# Model Serving endpoint
# Check workspace > Model Serving > coco-agent > Metrics
```

## Security Best Practices

1. **Use service principals for production** (not user credentials)
2. **Enable SQL warehouse IP access lists** (if available in region)
3. **Use Unity Catalog** for fine-grained data access control
4. **Enable audit logging** in workspace settings
5. **Rotate service principal secrets** regularly
6. **Restrict Gateway route access** to authenticated users only

## Support

For issues, check:
- `docs/ARCHITECTURE.md` - System design details
- `README.md` - Configuration reference
- Databricks documentation - Platform-specific features
- `tests/README.md` - Testing configuration files
