# Cost attribution dashboard

A Lakeview dashboard built from the seven validated queries in [`queries/`](queries). Every query has been run against a real `system.billing` + `system.query.history` workspace and returns the schema documented below. If a query fails on your workspace, check that [system tables are enabled](https://docs.databricks.com/aws/en/admin/system-tables/enable-system-tables.html) for your account.

Two ways to stand the dashboard up:

1. **DABs deploy (recommended)** - `databricks bundle deploy` wires it up as part of the bundle, along with the jobs and the app.
2. **Lakeview UI recipe** - paste the queries into a new dashboard by hand.

## Option 1: Deploy via Databricks Asset Bundles

The bundle already declares a `coco_cost_attribution` dashboard resource ([databricks.yml](../../databricks.yml)):

```yaml
resources:
  dashboards:
    coco_cost_attribution:
      display_name: CoCo Cost Attribution (${var.unique_id})
      file_path: ./docs/cost-attribution/coco_cost_attribution.lvdash.json
      warehouse_id: ${var.warehouse_id}
      parent_path: /Workspace/Users/${workspace.current_user.userName}/.bundle/${bundle.name}/${bundle.target}/dashboards
```

Deploy:

```bash
databricks bundle deploy -t demo -p feai
```

The dashboard lands under `/Workspace/Users/<you>/.bundle/coco-agent/demo/dashboards/` with all seven datasets pre-wired. Open it and drag each dataset onto the canvas to build widgets. See the [DABs dashboard resource docs](https://docs.databricks.com/aws/en/dev-tools/bundles/resources#dashboard) for the gotchas: UI changes need a manual export back to `.lvdash.json` or `--force` on the next deploy will overwrite them.

The shipped `coco_cost_attribution.lvdash.json` includes only the datasets and an intro text widget - widget layout is left for you to build in the UI. The reason: the full Lakeview widget schema is workspace-dependent enough that a hand-crafted JSON breaks on import in subtle ways. Ship datasets, let the UI handle layout, export once the layout is good.

## Option 2: Build in the Databricks UI

If you don't want DABs in the loop, build the dashboard directly:

1. Open **SQL -> Dashboards -> Create dashboard** ([Lakeview tutorial](https://docs.databricks.com/aws/en/dashboards/tutorials/create-dashboard.html)).
2. On the **Data** tab, add seven datasets by pasting the SQL from each file in `docs/cost-attribution/queries/`. Name each dataset after its file.
3. On the **Canvas** tab, add widgets (see the recipe below).
4. Publish and share with your FinOps team.

## Recipe - seven widgets, seven FinOps questions

| Widget | Question it answers | Dataset | Widget type | Axes |
|---|---|---|---|---|
| Spend by workload | "What did CoCo cost this month?" | `dbu_by_workload.sql` | **Counter** + **Bar** | x = `workload`, y = `approx_usd`, color = `product` |
| Daily spend time series | "Is spend trending up or down?" | `dbu_timeseries.sql` | **Area / stacked bar** | x = `day`, y = `approx_usd`, color = `workload` |
| Cost spike alerts | "Did anything blow up in the last 7 days?" | `cost_spikes.sql` | **Table** with conditional formatting | row = spike, highlight = `pct_vs_baseline > 0.5` |
| Per-endpoint cost | "Which serving endpoint costs most?" | `serving_endpoint_cost.sql` | **Bar** | x = `endpoint`, y = `approx_usd` |
| Warehouse utilization | "Are my warehouses paid-but-idle?" | `warehouse_utilization.sql` | **Scatter** or **Table** | x = `warehouse_id`, y = `utilization_ratio` (flag <0.3) |
| Top expensive queries | "Which single queries dominate the bill?" | `top_cost_queries.sql` | **Table** | sorted by `cost_score` desc, preview = `statement_preview` |
| Cost per user | "Who on my team is driving the cost?" | `cost_per_user.sql` | **Bar** + **Table** | x = `user_id`, y = `approx_usd_14d` |

The `cost_per_user` widget is new and depends on the agent's per-request tagging. The SQL statement client prepends `/* coco_user_id=<id>, coco_thread_id=<id> */` to every query ([`src/coco/sql/statement_client.py`](../../src/coco/sql/statement_client.py)); the dashboard query regex-extracts the id from `system.query.history.statement_text`. Only tagged queries are counted - ad-hoc SQL run by a human in the SQL editor will not show up per-user, only under the warehouse total.

## Widget parameters to expose

- `date_window` (default: 30 days) - bind to every dataset's `usage_date` filter
- `workload_filter` (default: all) - bind to `workload` column on the relevant datasets
- `env_filter` (default: all) - bind to `env` column on time-series and spike widgets

Lakeview dashboard parameters propagate to every bound dataset, so changing the date window in the header updates all seven widgets. See the [parameters docs](https://docs.databricks.com/aws/en/dashboards/dashboard-parameters.html).

## Query compatibility

Every query reads only from [`system.billing.*`](https://docs.databricks.com/aws/en/admin/system-tables/billing.html) and [`system.query.history`](https://docs.databricks.com/aws/en/admin/system-tables/query-history.html). Both require [system tables enabled](https://docs.databricks.com/aws/en/admin/system-tables/enable-system-tables.html) at the account level. If you see `TABLE_OR_VIEW_NOT_FOUND` on any query, ask your account admin to enable the relevant system schema.

The queries use standard ANSI SQL plus Databricks-specific column paths (e.g. `compute.warehouse_id` on `system.query.history`). They were validated against the schemas published at the doc URLs above on 2026-04-19.

## Trusting the numbers

Every widget shows USD values computed as `usage_quantity * list_prices.pricing.default` from the official system tables. This is list price, not your negotiated price. If you have a commitment discount, apply it in the widget formula or the derived dataset.

Treat `system.billing` as the source of truth for spend, and [`system.query.history.total_task_duration_ms`](https://docs.databricks.com/aws/en/admin/system-tables/query-history.html) as the source of truth for per-query work. The top-queries widget's `cost_score` is a relative ranking, not an absolute dollar figure - use it to find the expensive queries, then pull their stats directly if you need to quote actual cost.

The cost-per-user widget uses task-duration-proportion allocation: a user's share of a warehouse's 14-day USD spend equals `user_task_seconds / all_users_task_seconds * warehouse_usd`. This is an approximation because warehouse DBUs bill on active cluster time (including idle), not per-query task time. For workloads with many concurrent users it is close. For a sparse workload treat it as relative spend share rather than absolute dollars.

## Refresh frequency

System tables refresh on the schedule documented at the [system tables docs page](https://docs.databricks.com/aws/en/admin/system-tables/billing.html#data-refresh-frequency):

- `system.billing.usage` - updated roughly every 60 minutes
- `system.billing.list_prices` - updated when pricing changes (rare)
- `system.query.history` - updated every few minutes

Your dashboard can set auto-refresh to 15-minute increments. Tighter refresh does not surface fresher data.
