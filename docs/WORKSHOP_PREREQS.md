# Workshop Prerequisites - Platform Checklist

This document is for the customer's Databricks platform team. Every item below must be true on the workshop workspace **48 hours before** the onsite so attendees can clone the repo, run the setup notebook, and reach the definition-of-done inside the 2-hour breakout.

If any item is unclear or blocked, reach out to the workshop facilitator and we will sort it out before workshop day.

## Workspace fundamentals

- [ ] Workspace is **on AWS**. Lakebase on Azure is still in public preview, so only the AWS workspace path is supported for the workshop.
- [ ] Workspace region has **Lakebase** generally available. If you're not sure, confirm via the Databricks Apps > Databases UI - you should see a "Create database instance" button.
- [ ] **Compliance Security Profile** set to HIPAA. Lakebase inherits HIPAA availability from the workspace-level profile. Without it, Lakebase cannot legally host PHI and the agent's session store is not HIPAA-covered. The workshop won't use real PHI, but the platform setting must still be in place because the arch doc bills CoCo as HIPAA-auditable.
- [ ] **Unity Catalog** is the metastore on the workspace (it almost certainly is; just confirming).
- [ ] **Databricks Apps** is enabled on the workspace.
- [ ] **Model Serving** is enabled (needed for the agent endpoint).
- [ ] **Vector Search** is enabled (needed for the knowledge index).

## Shared warehouse

The workshop runs cohort queries through a serverless SQL warehouse via the Statement Execution API.

- [ ] A **serverless SQL warehouse** is provisioned and running in the workspace.
- [ ] The warehouse is sized **Small or larger** (X-Small works for data generation and light cohort queries but will feel sluggish for 10k patient joins).
- [ ] Warehouse auto-stop is set to **60 minutes** for the workshop (not the default 10 minutes) so it doesn't go cold between attendees' demos.
- [ ] Pre-warm the warehouse **10 minutes before the workshop** by running a trivial `SELECT 1` through it. Cold starts are 60-90 seconds and will burn workshop time.
- [ ] Share the **warehouse id** (the hex string in the warehouse URL, e.g. `abcdef0123456789`) with the workshop facilitator and the attendees so they can pass it to `databricks bundle deploy --var warehouse_id=...`.

## LLM endpoint

- [ ] `databricks-claude-sonnet-4-5` Model Serving endpoint is **served** in the workspace. You can verify with `databricks serving-endpoints get databricks-claude-sonnet-4-5` - it should return `state.ready = READY`.
- [ ] If your region ships Claude Sonnet 4.6 instead of 4.5, update `config/default.yaml` to point `llm.endpoint` and `llm.gateway_route` at the actual endpoint name available in your workspace.
- [ ] Pre-invoke the endpoint **15 minutes before the workshop** with a warm-up prompt (`{"messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}`). Serving endpoints cold-start is ~1-2 minutes.

## Attendee identities and permissions

Each of the 4 attendees needs:

- [ ] Their own Databricks workspace user account (email-backed, SCIM or manual provisioning).
- [ ] `ALL PRIVILEGES` on the Unity Catalog metastore OR at minimum:
  - [ ] `CREATE CATALOG` on the metastore (setup notebook creates `coco_demo`)
  - [ ] `CREATE SCHEMA` on the new catalog
  - [ ] `CREATE VOLUME` on the new schema
  - [ ] `CREATE TABLE` on the new schema
- [ ] Ability to **create Lakebase instances**. At the time of writing this is granted via the workspace-level "Databases" feature flag; the Databricks Apps team can confirm the exact permission.
- [ ] Ability to **create Vector Search endpoints**.
- [ ] Ability to **deploy Model Serving endpoints** (the agent registers to UC and calls `databricks.agents.deploy()`).
- [ ] `CAN_USE` on the shared serverless warehouse.
- [ ] `CAN_QUERY` on the `databricks-claude-sonnet-4-5` endpoint.

The simplest path is to put all 4 attendees into a `coco-workshop` workspace group and grant the group everything above in one shot. You can drop the group after the workshop.

## Attendee local environment

Each attendee laptop needs:

- [ ] **Databricks CLI v0.240+** installed (`brew install databricks` on macOS, `winget install Databricks.CLI` on Windows, or direct download from the docs).
- [ ] CLI profile configured for the target workspace (`databricks auth login --host https://<your-workspace>.cloud.databricks.com`).
- [ ] **git** installed (for `git clone`).
- [ ] **Python 3.11+** (only for running `pytest` locally if they want to validate before deploying - the setup notebook itself runs on Databricks compute, not locally).

Attendees do **not** need local Databricks credentials beyond the CLI profile, and they do **not** need to pip-install anything. The setup notebook handles all dependency installation on the cluster.

## Pre-workshop dry run

The workshop facilitator should run the full clone -> deploy -> setup -> query flow against the target workspace on the **day before the workshop** (morning if possible) to verify:

1. Bundle deploy succeeds with the shared warehouse id
2. Setup notebook completes in < 25 minutes
3. `setup_complete.json` lands in the `coco_artifacts` UC volume with real resource URLs
4. The deployed Databricks App loads and can make one full cohort query end-to-end
5. The MLflow trace for that query is visible in the Experiments UI

If any of these fail, debug and either re-run or escalate to the platform team for missing permissions or feature flags.

## Workshop-day fallback

Even with everything green in the dry run, a single attendee's deploy can stall on cluster queue or a transient permissions issue and derail the breakout. The mitigation:

- [ ] The workshop facilitator pre-deploys a **shared CoCo instance** the day before under a service account that all attendees have `CAN_USE` on. Attendees who lose time on their own deploy can click the shared URL and still complete the definition-of-done (2 cohort queries + viewing an MLflow trace + editing a config value).
- [ ] The shared instance URL is listed on a paper handout at the start of the workshop so no one has to ask for it.

## Contact

Questions, blockers, or anything you want sanity-checked before workshop day:

- **Workshop facilitator** - <facilitator-email> - workshop author and lead facilitator
- **Customer-side sponsor** - handles escalations to customer IT and account ops

Please confirm this checklist is complete **at least 3 business days before the workshop** so there is time to unblock anything that slipped.
