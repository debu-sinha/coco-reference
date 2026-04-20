-- Warehouse utilization: active query time vs. idle time.
--
-- Directly addresses the "a warehouse is sitting there waiting and
-- racking up cost" concern that surfaces in most cost reviews.
-- Makes the case for aggressive auto-stop (or serverless
-- entirely) by showing exactly how much of the billed window was
-- actually doing useful work.
--
-- Method:
--   1. Bucket each warehouse's billing rows into the time window.
--   2. Sum the total billed DBU per warehouse.
--   3. Separately count the duration of actually-executing queries
--      from system.query.history (idle time = billed time minus
--      query time, roughly).
--   4. Compute a utilization ratio per warehouse.
--
-- Default window: last 14 days. Adjust as needed.

WITH billed AS (
    SELECT
        usage.usage_metadata.warehouse_id            AS warehouse_id,
        usage.custom_tags.workload                   AS workload,
        SUM(usage.usage_quantity)                    AS billed_dbu,
        -- billed_seconds: DBUs roughly correspond to the warehouse
        -- running for some number of seconds. We can't recover
        -- seconds exactly without the cluster size, but for
        -- relative utilization this is fine.
        SUM(usage.usage_quantity) * 3600             AS billed_seconds_est
    FROM system.billing.usage AS usage
    WHERE usage.usage_date >= DATE_SUB(CURRENT_DATE(), 14)
        AND usage.usage_metadata.warehouse_id IS NOT NULL
    GROUP BY
        usage.usage_metadata.warehouse_id,
        usage.custom_tags.workload
),
queried AS (
    SELECT
        compute.warehouse_id                         AS warehouse_id,
        COUNT(*)                                     AS query_count,
        SUM(total_duration_ms) / 1000.0              AS query_seconds
    FROM system.query.history
    WHERE start_time >= CURRENT_TIMESTAMP() - INTERVAL 14 DAYS
        AND compute.warehouse_id IS NOT NULL
    GROUP BY compute.warehouse_id
)
SELECT
    b.warehouse_id,
    b.workload,
    b.billed_dbu,
    COALESCE(q.query_count, 0)                       AS query_count,
    COALESCE(q.query_seconds, 0.0)                   AS query_seconds,
    b.billed_seconds_est,
    -- Ratio of actually-used time to billed time. Values close
    -- to 0 mean the warehouse sat idle for most of its billed
    -- window (strong signal to cut auto-stop-mins or move to
    -- serverless). Values above 0.8 mean the warehouse is
    -- saturated and may need scale-out.
    ROUND(
        COALESCE(q.query_seconds, 0.0) / NULLIF(b.billed_seconds_est, 0),
        3
    )                                                AS utilization_ratio
FROM billed b
LEFT JOIN queried q USING (warehouse_id)
ORDER BY utilization_ratio ASC NULLS FIRST;
