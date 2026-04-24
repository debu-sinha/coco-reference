-- Widget 5: Top CoCo line items.
--
-- Answers "which single resource is the biggest line item?" Returns
-- per-resource rollup so a leader can immediately see, for example,
-- that coco-agent-<user> at $26 is driving more than coco-<user> App.
--
-- Ideal rendering: table. Suggested columns:
--   resource_name, coco_service, sku_name, usd, dbu, billing_rows.

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
  COALESCE(
    c.usage_metadata.endpoint_name,
    c.usage_metadata.app_name,
    CASE WHEN c.billing_origin_product = 'LAKEBASE'
         THEN CONCAT('coco-lb-', COALESCE(c.custom_tags['unique_id'], '?')) END,
    '(other)'
  ) AS resource_name,
  c.coco_service,
  c.sku_name,
  ROUND(SUM(c.usage_quantity * COALESCE(lp.pricing.default, 0)), 2) AS usd,
  ROUND(SUM(c.usage_quantity), 2)                                  AS dbu,
  COUNT(*)                                                         AS billing_rows
FROM coco_usage c
LEFT JOIN system.billing.list_prices lp
  ON c.sku_name = lp.sku_name
  AND c.cloud = lp.cloud
  AND c.usage_start_time BETWEEN lp.price_start_time
                             AND COALESCE(lp.price_end_time, current_timestamp())
GROUP BY 1, 2, 3
ORDER BY usd DESC
LIMIT 20;
