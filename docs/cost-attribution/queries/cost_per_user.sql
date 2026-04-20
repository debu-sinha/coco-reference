-- Per-user cost approximation from tagged agent queries.
--
-- Relies on the SQL comment prefix that the agent's statement client
-- prepends to every query:
--     /* coco_user_id=<id>, coco_thread_id=<id> */
-- which lands in system.query.history.statement_text. We regex the
-- user_id back out and aggregate task-duration as a proxy for the
-- user's share of warehouse DBU cost.
--
-- This is an approximation: warehouse DBUs bill on active cluster time,
-- not per-query task time, so a user running queries on an otherwise
-- idle warehouse bears the full idle overhead. For loads with many
-- concurrent users the approximation is close. For a sparse workload
-- treat it as "relative spend share", not dollars.
--
-- Default window: last 14 days. Adjust as needed.

WITH tagged AS (
    SELECT
        REGEXP_EXTRACT(qh.statement_text, 'coco_user_id=([^,\\s*]+)', 1) AS user_id,
        qh.compute.warehouse_id                              AS warehouse_id,
        COUNT(*)                                              AS query_count,
        SUM(qh.total_duration_ms) / 1000.0                    AS total_duration_s,
        SUM(qh.total_task_duration_ms) / 1000.0               AS total_task_s,
        SUM(qh.read_bytes) / 1024.0 / 1024.0 / 1024.0         AS read_gb
    FROM system.query.history qh
    WHERE qh.start_time >= CURRENT_TIMESTAMP() - INTERVAL 14 DAYS
        AND qh.statement_text LIKE '%coco_user_id=%'
        AND qh.compute.warehouse_id IS NOT NULL
        AND qh.execution_status = 'FINISHED'
    GROUP BY 1, 2
),
warehouse_spend AS (
    SELECT
        usage.usage_metadata.warehouse_id              AS warehouse_id,
        SUM(usage.usage_quantity * lp.pricing.default) AS warehouse_usd,
        SUM(usage.usage_quantity)                      AS warehouse_dbu
    FROM system.billing.usage usage
    LEFT JOIN system.billing.list_prices lp
        ON usage.cloud = lp.cloud
       AND usage.sku_name = lp.sku_name
       AND usage.usage_start_time BETWEEN lp.price_start_time
                                      AND COALESCE(lp.price_end_time, current_timestamp())
    WHERE usage.usage_date >= DATE_SUB(CURRENT_DATE(), 14)
        AND usage.usage_metadata.warehouse_id IS NOT NULL
    GROUP BY 1
)
SELECT
    t.user_id,
    SUM(t.query_count)                                    AS query_count_14d,
    ROUND(SUM(t.total_task_s), 1)                         AS task_seconds_14d,
    ROUND(SUM(t.read_gb), 2)                              AS read_gb_14d,
    -- Proportional cost: user's task seconds / all users' task seconds
    -- on the same warehouse, times the warehouse's 14-day USD spend.
    ROUND(
        SUM(
            t.total_task_s * ws.warehouse_usd
            / NULLIF(
                SUM(t.total_task_s) OVER (PARTITION BY t.warehouse_id),
                0
            )
        ),
        4
    )                                                     AS approx_usd_14d
FROM tagged t
LEFT JOIN warehouse_spend ws USING (warehouse_id)
GROUP BY t.user_id
ORDER BY approx_usd_14d DESC NULLS LAST;
