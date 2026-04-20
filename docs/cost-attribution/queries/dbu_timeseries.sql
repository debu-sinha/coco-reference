-- Daily DBU spend time series per workload tag.
--
-- The base view for any "are we trending up or down" conversation
-- and for week-over-week chargeback reporting.
--
-- One row per (usage_date, workload) tuple. A dashboard widget
-- that plots this as a stacked bar chart with `workload` on the
-- color axis gives the RWDS team a clean "cost per day per
-- workload" view in one glance.
--
-- Default window: 90 days. Adjust as needed for longer baselines.

SELECT
    usage.usage_date                                   AS day,
    usage.custom_tags.workload                         AS workload,
    usage.custom_tags.env                              AS env,
    SUM(usage.usage_quantity)                          AS dbu_consumed,
    ROUND(SUM(usage.usage_quantity * COALESCE(list.pricing.default, 0)), 2) AS approx_usd
FROM system.billing.usage AS usage
LEFT JOIN system.billing.list_prices AS list
    ON usage.sku_name = list.sku_name
    AND usage.cloud = list.cloud
    AND usage.usage_start_time >= list.price_start_time
    AND (list.price_end_time IS NULL OR usage.usage_start_time < list.price_end_time)
WHERE
    usage.usage_date >= DATE_SUB(CURRENT_DATE(), 90)
    AND usage.custom_tags.workload IS NOT NULL
GROUP BY
    usage.usage_date,
    usage.custom_tags.workload,
    usage.custom_tags.env
ORDER BY day ASC, workload ASC;
