-- DBU spend grouped by the `workload` tag.
--
-- The single most important attribution view. Answers "how much
-- did CoCo cost this month" across every compute type (clusters,
-- warehouses, jobs, serving endpoints) in one SELECT.
--
-- Reads from `system.billing.usage` which requires system tables
-- enablement on the account. See the Databricks docs for
-- enabling system tables if `relation does not exist` fires.
--
-- Default window: last 30 days. Adjust the DATE_SUB if you need
-- a longer baseline or a narrower drill-down. The grouping is by
-- workload first, then by compute type, so each row answers "how
-- much did the <workload> spend on <compute type>".

SELECT
    usage.custom_tags.workload                         AS workload,
    usage.custom_tags.team                             AS team,
    usage.custom_tags.env                              AS env,
    usage.billing_origin_product                       AS product,
    usage.sku_name                                     AS sku,
    SUM(usage.usage_quantity)                          AS dbu_consumed,
    -- list_price.default is the on-demand DBU rate for the SKU.
    -- For a rough dollar estimate multiply DBU by that rate.
    -- For exact billing, join against system.billing.list_prices
    -- separately on sku_name and the usage date.
    ROUND(SUM(usage.usage_quantity * COALESCE(list.pricing.default, 0)), 2) AS approx_usd
FROM system.billing.usage AS usage
LEFT JOIN system.billing.list_prices AS list
    ON usage.sku_name = list.sku_name
    AND usage.cloud = list.cloud
    AND usage.usage_start_time >= list.price_start_time
    AND (list.price_end_time IS NULL OR usage.usage_start_time < list.price_end_time)
WHERE
    usage.usage_date >= DATE_SUB(CURRENT_DATE(), 30)
    AND usage.custom_tags.workload IS NOT NULL
    -- To include everything (including the unattributed bucket),
    -- delete the line above and the grouping will pick up NULL
    -- as a workload value. Leaving it in focuses the view on
    -- tagged workloads only.
GROUP BY
    usage.custom_tags.workload,
    usage.custom_tags.team,
    usage.custom_tags.env,
    usage.billing_origin_product,
    usage.sku_name
ORDER BY approx_usd DESC NULLS LAST;
