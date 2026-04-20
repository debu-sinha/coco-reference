-- Top N most expensive SQL queries by estimated DBU consumed.
--
-- Surfaces the pathological cohort queries that dominate the bill:
-- expensive joins, full table scans on unpartitioned tables,
-- runaway CTEs from an LLM planner that lost its mind. Fixing
-- these individually is dramatically cheaper than blanket rate
-- limiting or scaling up the warehouse.
--
-- Relies on `system.query.history`, which captures every query
-- executed on a SQL warehouse along with duration, rows read,
-- and bytes scanned. Enabling it is a system tables toggle at
-- the account level.
--
-- DBU per query is estimated from
--   total_task_duration_ms * dbu_rate(cluster_size)
-- because Databricks bills warehouse DBUs by active cluster
-- time, not per query. The query history captures per-query
-- task duration, so the estimate is approximate but directly
-- comparable across queries on the same warehouse.
--
-- Default: top 50 queries in the last 7 days. Adjust LIMIT and
-- the date window as needed.

WITH window AS (
    SELECT
        statement_id,
        executed_by,
        workload_name,
        warehouse_id,
        statement_type,
        statement_text,
        start_time,
        end_time,
        total_duration_ms,
        total_task_duration_ms,
        read_bytes,
        read_rows,
        -- Rough normalized cost score. Higher = more expensive.
        -- Multiplying task_duration by read_bytes penalizes both
        -- long-running queries AND queries that scan a lot of data,
        -- which is the classic "bad cohort query" signature.
        (COALESCE(total_task_duration_ms, 0) / 1000.0) *
        (COALESCE(read_bytes, 0) / 1024.0 / 1024.0 / 1024.0 + 1) AS cost_score
    FROM system.query.history
    WHERE start_time >= CURRENT_TIMESTAMP() - INTERVAL 7 DAYS
        AND execution_status = 'FINISHED'
        AND statement_type IN ('SELECT', 'DML')
)
SELECT
    start_time,
    executed_by,
    workload_name,
    warehouse_id,
    statement_type,
    ROUND(total_duration_ms / 1000.0, 1) AS duration_s,
    ROUND(read_bytes / 1024.0 / 1024.0 / 1024.0, 2) AS read_gb,
    read_rows,
    ROUND(cost_score, 2) AS cost_score,
    -- Truncate the statement for display. Widen in the
    -- dashboard if you want to see the full text on hover.
    SUBSTRING(statement_text, 1, 200) AS statement_preview
FROM window
ORDER BY cost_score DESC
LIMIT 50;
