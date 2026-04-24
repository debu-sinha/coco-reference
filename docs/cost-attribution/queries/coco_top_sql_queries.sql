-- Widget 6: Top CoCo SQL queries (warehouse cost per query).
--
-- Answers "which individual cohort query is burning warehouse time?"
-- Relies on the SQL comment prefix the agent's statement client
-- prepends to every query:
--     /* coco_user_id=<id>, coco_thread_id=<id> */
-- which lands in system.query.history.statement_text. The LIKE
-- anchor is the OPENING of the comment, which avoids the "query
-- that mentions the prefix in its own body" self-match pitfall.
--
-- Ideal rendering: table sorted by cost_score desc. Suggested columns:
--   start_time, user_id, duration_s, read_gb, cost_score, statement_preview.

SELECT
  qh.start_time,
  REGEXP_EXTRACT(qh.statement_text, 'coco_user_id=([^,\\s*]+)', 1) AS coco_user_id,
  REGEXP_EXTRACT(qh.statement_text, 'coco_thread_id=([^,\\s*]+)', 1) AS coco_thread_id,
  qh.compute.warehouse_id                                          AS warehouse_id,
  qh.statement_type,
  ROUND(qh.total_duration_ms / 1000.0, 1)                          AS duration_s,
  ROUND(COALESCE(qh.read_bytes, 0) / 1024.0 / 1024.0 / 1024.0, 2)  AS read_gb,
  qh.read_rows,
  -- Normalized relative cost score (long + heavy = expensive).
  ROUND(
    (COALESCE(qh.total_task_duration_ms, 0) / 1000.0) *
    (COALESCE(qh.read_bytes, 0) / 1024.0 / 1024.0 / 1024.0 + 1),
    2
  )                                                                AS cost_score,
  SUBSTRING(qh.statement_text, 1, 200)                             AS statement_preview
FROM system.query.history qh
WHERE qh.start_time >= CAST(DATE_SUB(CURRENT_DATE(), :lookback_days) AS TIMESTAMP)
  AND qh.statement_text LIKE '/* coco_user_id=%'
  AND qh.execution_status = 'FINISHED'
  AND qh.statement_type IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'MERGE')
  AND (
    :unique_id = 'all'
    OR qh.statement_text LIKE CONCAT('/* coco_user_id=', :unique_id, ',%')
  )
ORDER BY cost_score DESC
LIMIT 50;
