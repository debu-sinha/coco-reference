-- Per-serving-endpoint cost, grouped by endpoint name + workload.
--
-- Relevant once you move DSPy LLM calls from an external provider
-- (e.g. enterprise OpenAI) to a Databricks-hosted Foundation Model
-- API endpoint like `databricks-claude-sonnet-4-6` (see
-- docs/examples/databricks_hosted_claude_for_dspy.py). Before that
-- switch this query returns nothing for DSPy spend because the
-- DSPy calls never hit Databricks serving. After the switch it
-- becomes the single authoritative view of LLM-call cost for DSPy
-- workloads.
--
-- Also picks up the CoCo agent endpoint (coco-agent) directly if
-- the Mosaic AI Agent Framework deploy attached workload tags
-- via AppResourceServingEndpoint or via the model resources list.
-- As of 2026-04 the Agent Framework deploy does not propagate
-- custom tags the same way cluster policies do, so per-endpoint
-- attribution may have to fall back to the endpoint name column
-- only. We return both flavors so either path works.

SELECT
    usage.usage_metadata.endpoint_name               AS endpoint_name,
    usage.custom_tags.workload                       AS workload,
    usage.custom_tags.env                            AS env,
    usage.billing_origin_product                     AS product,
    usage.sku_name                                   AS sku,
    SUM(usage.usage_quantity)                        AS dbu_consumed,
    ROUND(SUM(usage.usage_quantity * COALESCE(list.pricing.default, 0)), 2) AS approx_usd,
    MIN(usage.usage_start_time)                      AS first_billed_at,
    MAX(usage.usage_end_time)                        AS last_billed_at
FROM system.billing.usage AS usage
LEFT JOIN system.billing.list_prices AS list
    ON usage.sku_name = list.sku_name
    AND usage.cloud = list.cloud
    AND usage.usage_start_time >= list.price_start_time
    AND (list.price_end_time IS NULL OR usage.usage_start_time < list.price_end_time)
WHERE
    usage.usage_date >= DATE_SUB(CURRENT_DATE(), 30)
    AND (
        usage.usage_metadata.endpoint_name IS NOT NULL
        OR usage.billing_origin_product = 'MODEL_SERVING'
    )
GROUP BY
    usage.usage_metadata.endpoint_name,
    usage.custom_tags.workload,
    usage.custom_tags.env,
    usage.billing_origin_product,
    usage.sku_name
ORDER BY approx_usd DESC NULLS LAST;
