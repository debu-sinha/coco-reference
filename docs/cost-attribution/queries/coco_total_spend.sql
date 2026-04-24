-- Widget 1: Total CoCo spend (single number tile).
--
-- Answers "what did my CoCo deployment cost me?" in one USD figure.
-- Scoped strictly to the current deployment via the :unique_id
-- dashboard parameter; defaults to the bundle's var.unique_id so
-- each attendee sees only their own spend after `bundle deploy`.
--
-- Pass :unique_id = 'all' to aggregate across every coco-* resource
-- visible to this workspace (instructor / admin view).
--
-- Data sources: system.billing.usage + system.billing.list_prices.
-- No custom tables, no hardcoded ids.

WITH coco_usage AS (
  SELECT u.*
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
  ROUND(SUM(c.usage_quantity * COALESCE(lp.pricing.default, 0)), 2) AS total_usd,
  ROUND(SUM(c.usage_quantity), 2)                                  AS total_dbu,
  COUNT(*)                                                         AS billing_rows
FROM coco_usage c
LEFT JOIN system.billing.list_prices lp
  ON c.sku_name = lp.sku_name
  AND c.cloud = lp.cloud
  AND c.usage_start_time BETWEEN lp.price_start_time
                             AND COALESCE(lp.price_end_time, current_timestamp());
