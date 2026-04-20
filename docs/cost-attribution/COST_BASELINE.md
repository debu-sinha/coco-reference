# Cost baseline — measured numbers

Real costs measured on a single Databricks workspace across one full development day (`2026-04-19`). Every number came from [`system.billing.usage`](https://docs.databricks.com/aws/en/admin/system-tables/billing.html) joined against [`system.billing.list_prices`](https://docs.databricks.com/aws/en/admin/system-tables/pricing.html). No estimates, no marketing numbers.

## What was measured

One attendee's development-and-test loop on a fresh workspace:

- 1 full `setup_workspace` run (UC schema + 10k synthetic patients + Vector Search index + Lakebase instance + agent endpoint + app)
- 1 `run_evaluation` job (19 scenarios × 4 scorers)
- 1 `optimize_dspy` job (GEPA over 3 feedback pairs, 1 new prompt version)
- 1 `teardown_workspace` job
- Manual testing through the live app: ~10 cohort questions, thumbs-up feedback clicks

**Total workspace cost for the day: $19.57**

## Breakdown (USD, grouped by billable product)

| Source | SKU | DBU | USD | % of total |
|---|---|---|---|---|
| Claude Sonnet 4.6 via FMAPI | `ENTERPRISE_ANTHROPIC_MODEL_SERVING` | 130.6 | **$9.14** | 47% |
| SQL Warehouse (cohort queries + data gen) | `ENTERPRISE_SERVERLESS_SQL_COMPUTE_US_EAST` | 6.9 | **$4.80** | 25% |
| Agent Model Serving endpoint | `ENTERPRISE_SERVERLESS_REAL_TIME_INFERENCE_US_EAST` | 25.6 | **$1.79** | 9% |
| All-purpose compute (notebook kernels) | `ENTERPRISE_ALL_PURPOSE_SERVERLESS_COMPUTE_US_EAST` | 1.7 | **$1.58** | 8% |
| Lakebase instance | `ENTERPRISE_DATABASE_SERVERLESS_COMPUTE_US_EAST` | 3.0 | **$1.57** | 8% |
| Jobs compute (setup + eval + optimize notebooks) | `ENTERPRISE_JOBS_SERVERLESS_COMPUTE_US_EAST` | 1.1 | **$0.46** | 2% |
| Data processing + egress + storage | misc | ~3.3 | **$0.15** | <1% |

## How to reproduce this on your own workspace

```sql
SELECT
  COALESCE(u.usage_metadata.job_name,
           u.usage_metadata.warehouse_id,
           u.sku_name)                           AS source,
  u.sku_name,
  SUM(u.usage_quantity)                          AS dbu,
  ROUND(SUM(u.usage_quantity * lp.pricing.default), 4) AS usd
FROM system.billing.usage u
LEFT JOIN system.billing.list_prices lp
  ON u.cloud = lp.cloud
 AND u.sku_name = lp.sku_name
 AND u.usage_start_time BETWEEN lp.price_start_time
                            AND COALESCE(lp.price_end_time, current_timestamp())
WHERE u.usage_date = current_date()
  AND u.workspace_id = (
    SELECT workspace_id FROM system.billing.usage LIMIT 1
  )
GROUP BY 1, 2
ORDER BY usd DESC NULLS LAST;
```

This is what generated the table above. Replace `current_date()` with `DATE '<your-date>'` if you want a specific window, and restrict `workspace_id` manually if you share `system.billing` with other workspaces.

## What this tells you

- **The LLM is the single largest cost driver**, not the platform. 47% of spend goes to Anthropic tokens. This is typical for agentic workloads and is why prompt optimization and retrieval efficiency pay back fast.
- **SQL warehouse spend is concentrated in data generation and the warehouse idle window.** A dedicated per-workload serverless warehouse with 5-minute auto-stop (as described in [`policy.md`](policy.md)) keeps this bounded.
- **Serving endpoint and Lakebase costs are modest at this scale** (~$3.40 combined for a dev day). Both scale-to-zero by default.
- **Per-query cost is dominated by the LLM call.** With roughly 30 agent invocations across the day, each question cost ~$0.30–0.40 end-to-end including warehouse time. Scale that by actual usage.

## Caveats

1. **One workspace, one day, one developer.** This is a baseline, not a forecast. Your per-month number depends on how many queries your users ask and how complex they are.
2. **Anthropic model pricing is bundled into the `ENTERPRISE_ANTHROPIC_MODEL_SERVING` SKU** and doesn't separate input-tokens from output-tokens at the `system.billing.usage` level. For per-call token-level cost you'll want [MLflow traces](https://docs.databricks.com/aws/en/mlflow3/genai/tracing/) with token usage logged.
3. **Network egress numbers in `system.billing.usage` are delayed by up to 24h** per the [Databricks billing docs](https://docs.databricks.com/aws/en/admin/system-tables/billing.html#data-refresh-frequency). Numbers here are consistent across the day but queries run immediately after workload completion may underreport.
4. **`list_prices.pricing.default` is the list price**, not your negotiated price. Divide by a commitment-discount factor if you know it. The `pricing` struct also has a `promotional` field for discounted effective pricing — substitute as needed.

## Source citations

- `system.billing.usage` schema — https://docs.databricks.com/aws/en/admin/system-tables/billing.html
- `system.billing.list_prices` schema — https://docs.databricks.com/aws/en/admin/system-tables/pricing.html
- `system.query.history` schema — https://docs.databricks.com/aws/en/admin/system-tables/query-history.html
- SKU catalog — https://docs.databricks.com/aws/en/admin/system-tables/billing.html#sku-names
- Foundation Model API pricing model — https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/index.html#pricing
- Serving endpoint (real-time inference) pricing — https://www.databricks.com/product/pricing/mosaic-foundation-model-serving
- Lakebase pricing — https://www.databricks.com/product/pricing/lakebase

All numbers above were obtained by running the SQL shown in this doc against `system.billing` on an AWS workspace. The query is idempotent and non-destructive.
