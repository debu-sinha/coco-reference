-- CREATE WAREHOUSE template for a per-workload dedicated SQL warehouse.
--
-- Fill in the four placeholder values below, paste this into a SQL
-- editor as a workspace admin, and run. The resulting warehouse
-- will carry consistent tags from the first query, so every row
-- in system.billing.usage.custom_tags for this warehouse can be
-- joined on the workload/team/env/owner tags.
--
-- Why dedicated, not shared: see docs/cost-attribution/policy.md
-- "Principle: a dedicated SQL warehouse per workload".
--
-- Why serverless, not classic: sub-second startup lets auto_stop_mins
-- be aggressive without hurting user-visible latency, which is pure
-- cost saving.
--
-- The statement below uses the Databricks SQL CREATE WAREHOUSE
-- syntax (not CREATE SQL WAREHOUSE, which is the older flavor).
-- If your workspace rejects CREATE WAREHOUSE, use the REST API
-- directly (POST /api/2.0/sql/warehouses) or the SDK path -
-- `databricks-sdk` exposes warehouses.create().

-- -----------------------------------------------------------------------
-- Placeholder values - REPLACE BEFORE RUNNING
-- -----------------------------------------------------------------------
--   ${WORKLOAD_NAME}    e.g. coco, ehr_etl
--   ${TEAM_NAME}        e.g. rwds, platform
--   ${ENV}              one of: dev, stg, prd
--   ${OWNER_EMAIL}      e.g. owner@example.com

CREATE OR REPLACE WAREHOUSE ${WORKLOAD_NAME}_${ENV} WITH
  -- Small is plenty for cohort-scoped queries on the 10k-patient
  -- synthetic schema. Bump to Medium or Large only after the
  -- `warehouse_utilization.sql` query shows you are saturating.
  WAREHOUSE_SIZE = 'Small',
  -- Serverless: sub-second cold start, fair billing granularity,
  -- plays well with Mosaic AI Gateway serving.
  SERVERLESS = TRUE,
  -- Auto-stop aggressively on serverless. 5 minutes is the
  -- minimum allowed; dropping to 1-5 min is the single biggest
  -- cost saving after tagging itself.
  AUTO_STOP_MINS = 5,
  -- Cap the cluster scale-out. Prevents a runaway LLM planner
  -- (see the CoCo "keyword planner exhausted 10
  -- iterations" bug) from triggering unlimited warehouse scale.
  MIN_NUM_CLUSTERS = 1,
  MAX_NUM_CLUSTERS = 2,
  -- Photon is effectively free on serverless and strictly
  -- faster for analytical queries.
  ENABLE_PHOTON = TRUE,
  -- Channel: stay on CURRENT (the default) unless you have a
  -- specific preview feature you need.
  CHANNEL = (NAME = 'CHANNEL_NAME_CURRENT'),
  -- Tags: the load-bearing part of the whole file. These values
  -- propagate into system.billing.usage.custom_tags once the
  -- warehouse starts serving queries. Every query in
  -- `docs/cost-attribution/queries/` groups or filters by these.
  TAGS (
    workload = '${WORKLOAD_NAME}',
    team     = '${TEAM_NAME}',
    env      = '${ENV}',
    owner    = '${OWNER_EMAIL}'
  )
;

-- After the warehouse is created, grant CAN_USE to the workload's
-- service principal (not to specific users). This makes the
-- billing attribution reflect the APPLICATION that ran the query,
-- not the individual human who happened to hit run.
--
-- Replace ${SP_APPLICATION_ID} with the SP's client id.
--
-- GRANT CAN_USE ON WAREHOUSE ${WORKLOAD_NAME}_${ENV} TO `${SP_APPLICATION_ID}`;
