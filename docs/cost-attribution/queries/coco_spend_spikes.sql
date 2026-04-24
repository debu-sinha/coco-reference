-- Widget 7: Day-over-day CoCo spend spikes.
--
-- Flags days where CoCo spend jumped more than 50% above the trailing
-- 7-day mean. The floor threshold is tuned to CoCo's baseline (at
-- $0.50/day, not the $1 DBU baseline used in account-wide spike
-- dashboards) because CoCo's daily spend can sit in single dollars
-- during quiet periods and a 1 DBU floor would suppress every real
-- spike.
--
-- Ideal rendering: table. Suggested columns:
--   day, usd, trailing_7d_mean, pct_vs_7d.

WITH coco_usage AS (
  SELECT u.usage_date, u.sku_name, u.cloud, u.usage_quantity, u.usage_start_time
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
),
daily AS (
  SELECT
    c.usage_date AS day,
    SUM(c.usage_quantity * COALESCE(lp.pricing.default, 0)) AS usd
  FROM coco_usage c
  LEFT JOIN system.billing.list_prices lp
    ON c.sku_name = lp.sku_name
    AND c.cloud = lp.cloud
    AND c.usage_start_time BETWEEN lp.price_start_time
                               AND COALESCE(lp.price_end_time, current_timestamp())
  GROUP BY c.usage_date
),
windowed AS (
  SELECT
    day,
    usd,
    AVG(usd) OVER (
      ORDER BY day
      ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING
    ) AS trailing_7d_mean
  FROM daily
)
SELECT
  day,
  ROUND(usd, 2)                                                  AS usd,
  ROUND(trailing_7d_mean, 2)                                     AS trailing_7d_mean,
  ROUND((usd - trailing_7d_mean) / NULLIF(trailing_7d_mean, 0) * 100, 1) AS pct_vs_7d
FROM windowed
WHERE trailing_7d_mean IS NOT NULL
  AND trailing_7d_mean > 0.5
  AND (usd - trailing_7d_mean) / trailing_7d_mean > 0.5
ORDER BY pct_vs_7d DESC
LIMIT 20;
