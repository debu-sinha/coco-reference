# Cost attribution dashboard

A Lakeview dashboard built from the six validated queries in [`queries/`](queries). Every query has been run against a real `system.billing` + `system.query.history` workspace and returns the schema documented below. If a query fails on your workspace, check that [system tables are enabled](https://docs.databricks.com/aws/en/admin/system-tables/enable-system-tables.html) for your account.

## Build it in the Databricks UI

The fastest path that doesn't require shipping a brittle hand-crafted JSON: create the dashboard through the Lakeview UI using the six queries as datasets.

1. Open **SQL → Dashboards → Create dashboard** ([Lakeview tutorial](https://docs.databricks.com/aws/en/dashboards/tutorials/create-dashboard.html)).
2. On the **Data** tab, add six datasets by pasting the SQL from each file in `docs/cost-attribution/queries/`. Name each dataset after its file.
3. On the **Canvas** tab, add widgets (see the recipe below).
4. Publish and share with your FinOps team.

## Recipe — six widgets that map to one question each

| Widget | Question it answers | Dataset | Widget type | Axes |
|---|---|---|---|---|
| Spend by workload | "What did CoCo cost this month?" | `dbu_by_workload.sql` | **Counter** + **Bar** | x = `workload`, y = `approx_usd`, color = `product` |
| Daily spend time series | "Is spend trending up or down?" | `dbu_timeseries.sql` | **Area / stacked bar** | x = `day`, y = `approx_usd`, color = `workload` |
| Cost spike alerts | "Did anything blow up in the last 7 days?" | `cost_spikes.sql` | **Table** with conditional formatting | row = spike, highlight = `pct_vs_baseline > 0.5` |
| Per-endpoint cost | "Which serving endpoint costs most?" | `serving_endpoint_cost.sql` | **Bar** | x = `endpoint`, y = `approx_usd` |
| Warehouse utilization | "Are my warehouses paid-but-idle?" | `warehouse_utilization.sql` | **Scatter** or **Table** | x = `warehouse_id`, y = `utilization_ratio` (flag <0.3) |
| Top expensive queries | "Which single queries dominate the bill?" | `top_cost_queries.sql` | **Table** | sorted by `cost_score` desc, preview = `statement_preview` |

## Widget parameters to expose

- `date_window` (default: 30 days) — bind to every dataset's `usage_date` filter
- `workload_filter` (default: all) — bind to `workload` column on the relevant datasets
- `env_filter` (default: all) — bind to `env` column on time-series and spike widgets

Lakeview dashboard parameters propagate to every bound dataset, so changing the date window in the header updates all six widgets. See the [parameters docs](https://docs.databricks.com/aws/en/dashboards/dashboard-parameters.html).

## Query compatibility

Every query reads only from [`system.billing.*`](https://docs.databricks.com/aws/en/admin/system-tables/billing.html) and [`system.query.history`](https://docs.databricks.com/aws/en/admin/system-tables/query-history.html). Both require [system tables enabled](https://docs.databricks.com/aws/en/admin/system-tables/enable-system-tables.html) at the account level. If you see `TABLE_OR_VIEW_NOT_FOUND` on any query, ask your account admin to enable the relevant system schema.

The queries use standard ANSI SQL plus Databricks-specific column paths (e.g. `compute.warehouse_id` on `system.query.history`). They were validated against the schemas published at the doc URLs above on 2026-04-19.

## Why not ship a Lakeview JSON file

Lakeview dashboards serialize to a workspace-specific JSON format that includes dataset IDs Databricks generates on import. A JSON file exported from one workspace does not round-trip cleanly to another workspace without hand-editing the dataset IDs.

The recipe above is more portable. Build the dashboard once in the workspace you care about and the queries keep working as long as the system tables are enabled. For teams that want a one-click import, take the finished dashboard, **File → Export → JSON**, store it under `docs/cost-attribution/dashboard.lakeview.json`, and import per [these docs](https://docs.databricks.com/aws/en/dashboards/clone-dashboard.html).

## Trusting the numbers

Every widget above shows USD values computed as `usage_quantity * list_prices.pricing.default` from the official system tables. This is list price, not your negotiated price. If you have a commitment discount, apply it in the widget formula or the derived dataset. Do not eyeball.

Treat `system.billing` as the source of truth for spend, and [`system.query.history.total_task_duration_ms`](https://docs.databricks.com/aws/en/admin/system-tables/query-history.html) as the source of truth for per-query work. The top-queries widget's `cost_score` is a relative ranking, not an absolute dollar figure — use it to find the expensive queries, then pull their stats directly if you need to quote actual cost.

## Refresh frequency

System tables refresh on the schedule documented at the [system tables docs page](https://docs.databricks.com/aws/en/admin/system-tables/billing.html#data-refresh-frequency):

- `system.billing.usage` — updated roughly every 60 minutes
- `system.billing.list_prices` — updated when pricing changes (rare)
- `system.query.history` — updated every few minutes

Your dashboard can set auto-refresh to 15-minute increments; tighter refresh does not surface fresher data.
