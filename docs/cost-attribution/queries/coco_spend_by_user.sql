-- Widget 3: CoCo spend per user.
--
-- Answers "who's driving the cost?" Attribution is inferred from
-- the per-user resource naming convention the bundle uses:
--   coco-<unique_id>          -> the app for that user
--   coco-agent-<unique_id>    -> their agent serving endpoint
--   coco-vs-<unique_id>       -> their vector search endpoint
--
-- When :unique_id is a specific value, this widget returns a single
-- row (that user's spend). When :unique_id = 'all', it returns one
-- row per attendee.
--
-- Ideal rendering: bar chart (user on x, USD on y) when in 'all' mode.

WITH coco_usage AS (
  SELECT
    u.*,
    COALESCE(
      REGEXP_EXTRACT(u.usage_metadata.endpoint_name, '^coco-(?:agent|vs)-(.+)$', 1),
      REGEXP_EXTRACT(u.usage_metadata.app_name,      '^coco-(.+)$',              1),
      u.custom_tags['unique_id'],
      '(shared)'
    ) AS coco_user
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
  coco_user,
  ROUND(SUM(c.usage_quantity * COALESCE(lp.pricing.default, 0)), 2) AS usd,
  ROUND(SUM(c.usage_quantity), 2)                                  AS dbu,
  COUNT(DISTINCT
    CASE
      WHEN c.usage_metadata.endpoint_name LIKE 'coco-agent%' THEN 'agent'
      WHEN c.usage_metadata.endpoint_name LIKE 'coco-vs%'    THEN 'vs'
      WHEN c.usage_metadata.app_name      LIKE 'coco-%'      THEN 'app'
      ELSE 'other'
    END
  )                                                                AS services_used
FROM coco_usage c
LEFT JOIN system.billing.list_prices lp
  ON c.sku_name = lp.sku_name
  AND c.cloud = lp.cloud
  AND c.usage_start_time BETWEEN lp.price_start_time
                             AND COALESCE(lp.price_end_time, current_timestamp())
GROUP BY coco_user
ORDER BY usd DESC NULLS LAST;
