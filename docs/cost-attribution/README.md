# Cost Attribution for a Databricks AI Workload

A skeleton set of policies, queries, and a warehouse-provisioning
template for wiring per-workload cost visibility into a Databricks
deployment. Useful for any onsite or workshop where the customer
team will be setting up cost tracking for CoCo and adjacent
AI workloads.

## What's here

```
docs/cost-attribution/
├── README.md                 <- you are here
├── policy.md                 <- tagging policy draft
├── warehouse_setup.sql       <- CREATE WAREHOUSE template with tags
└── queries/
    ├── dbu_by_workload.sql      DBU spend grouped by workload tag
    ├── dbu_timeseries.sql       Daily DBU spend time series
    ├── top_cost_queries.sql     Most expensive SQL queries
    ├── warehouse_utilization.sql warehouse idle vs query time
    ├── serving_endpoint_cost.sql  per-endpoint serving spend
    └── cost_spikes.sql          Daily deltas flagged by percentage
```

## How to use this

1. **Read `policy.md` first.** The queries assume every cluster,
   warehouse, and serving endpoint carries a consistent set of
   tags. Without the tags, `system.billing.usage.custom_tags` is
   empty and the grouping columns return `NULL` across the board.
2. **Create a dedicated SQL warehouse for the workload** you want
   to attribute, using `warehouse_setup.sql` as a template. Give
   it the workshop-agreed tag values up front so billing rows
   start getting tagged from the first query.
3. **Run the queries against any serverless SQL warehouse** that
   has `SELECT` on `system.billing` and `system.compute`. The
   `system` catalog is world-readable inside Databricks by default
   but some workspaces have restricted it; if a query fails with
   "relation does not exist," check
   [the system tables enablement doc](https://docs.databricks.com/aws/en/admin/system-tables/).
4. **Wire the queries into a Databricks SQL dashboard or AI/BI
   dashboard** so the RWDS team can see the attribution over time
   without re-running ad-hoc SQL. The SQL files are independent on
   purpose - each one is a widget.

## The six queries, in order of workshop value

1. **`dbu_by_workload.sql`** - the single most important view.
   Groups DBU spend by the `workload` tag across all compute
   types (clusters, warehouses, serving, jobs). If the customer walks away
   from the onsite with only this one working, it was worth the
   afternoon. Answers the question "how much did CoCo cost this
   month."
2. **`warehouse_utilization.sql`** - shows idle vs. query time on
   each warehouse. Directly addresses the "a cluster is sitting
   there waiting and racking up cost" concern, and makes the case
   for auto-stop / serverless warehouses
   over long-lived clusters.
3. **`top_cost_queries.sql`** - ranks queries by DBU consumed.
   Surfaces the pathological cohort queries that dominate the
   bill (expensive joins, full table scans on unpartitioned
   tables, runaway CTEs from the LLM) so they can be fixed
   individually rather than by blanket rate limiting.
4. **`serving_endpoint_cost.sql`** - per-serving-endpoint spend.
   Relevant once your team moves DSPy LLM calls from an external
   provider to `databricks-claude-sonnet-4-6` (see `docs/examples/
   databricks_hosted_claude_for_dspy.py`). Until then this returns
   empty for the DSPy workload.
5. **`dbu_timeseries.sql`** - daily DBU spend per workload tag.
   The baseline for "are we trending up or down" and for
   week-over-week chargeback reporting.
6. **`cost_spikes.sql`** - flags day-over-day cost increases above
   a threshold. Less useful on day 1 (no history yet) but worth
   wiring up for when the workload has been running long enough
   to have a baseline.

## What's NOT here

- **A packaged dashboard export**. Each query is a `SELECT` you
  can point a dashboard widget at. Packaging them into a single
  exported dashboard JSON is a day-of-onsite task once we know
  the target workspace.
- **Budget alerts**. Databricks supports budget alerts on the
  account console; adding those is a 10-minute job that needs
  an account-admin to click through the UI. See the policy doc
  for the recommended thresholds.
- **Per-user attribution via `system.access.audit`**. Useful for
  "who ran this query" chargeback but out of scope for the
  workload-level view.
- **Inference Table cost attribution**. Inference tables are
  written by Mosaic AI Agent Framework serving and consume
  storage + compute when they're aggregated. That's a follow-up
  conversation, not a day-one deliverable.

## Related artifacts

- `docs/examples/databricks_hosted_claude_for_dspy.py` - the
  Python snippet that lets you move your DSPy modules onto
  Databricks-hosted Claude, which is the precondition for having
  the serving-endpoint-cost query mean anything.
- `docs/design/apps-mosaic-ai-agent-reference.md` - the
  reference architecture writeup. Mentions cost attribution in
  the non-goals and points here.
