-- Widget 2: CoCo spend decomposed by Databricks service.
--
-- Answers "where did the money go?" Breaks the total from widget 1
-- into LLM Agent Serving, Vector Search, App runtime, and any other
-- service CoCo touches. Ideal rendering: bar chart (service on x,
-- USD on y) or donut.
--
-- Uses the same scope CTE as widget 1 so totals reconcile.

WITH coco_usage AS (
  SELECT
    u.*,
    CASE
      WHEN u.usage_metadata.endpoint_name LIKE 'coco-agent%' THEN 'LLM / Agent Serving'
      WHEN u.usage_metadata.endpoint_name LIKE 'coco-vs%'    THEN 'Vector Search'
      WHEN u.usage_metadata.app_name      LIKE 'coco-%'      THEN 'App (runtime)'
      WHEN u.billing_origin_product = 'LAKEBASE'             THEN 'Lakebase'
      WHEN u.billing_origin_product = 'JOBS'                 THEN 'Jobs / Notebooks'
      ELSE 'Other'
    END AS coco_service
  FROM system.billing.usage u
  WHERE u.usage_date >= DATE_SUB(CURRENT_DATE(), :lookback_days)
    AND (
      u.usage_metadata.app_name = CONCAT('coco-', :unique_id)
      OR u.usage_metadata.endpoint_name = CONCAT('coco-agent-', :unique_id)
      OR u.usage_metadata.endpoint_name = CONCAT('coco-vs-', :unique_id)
      OR (u.billing_origin_product = 'LAKEBASE' AND u.custom_tags['unique_id'] = :unique_id)
      OR (
        :unique_id = 'all' AND (
          u.usage_metadata.app_name LIKE 'coco-%'
          OR u.usage_metadata.endpoint_name LIKE 'coco-%'
          OR (u.billing_origin_product = 'LAKEBASE' AND u.custom_tags['workload'] = 'coco')
        )
      )
    )
)
SELECT
  coco_service,
  ROUND(SUM(c.usage_quantity * COALESCE(lp.pricing.default, 0)), 2) AS usd,
  ROUND(SUM(c.usage_quantity), 2)                                  AS dbu,
  COUNT(*)                                                         AS billing_rows
FROM coco_usage c
LEFT JOIN system.billing.list_prices lp
  ON c.sku_name = lp.sku_name
  AND c.cloud = lp.cloud
  AND c.usage_start_time BETWEEN lp.price_start_time
                             AND COALESCE(lp.price_end_time, current_timestamp())
GROUP BY coco_service
ORDER BY usd DESC;
