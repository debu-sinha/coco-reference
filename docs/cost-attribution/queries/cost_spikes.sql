-- Day-over-day cost spikes per workload.
--
-- Flags days where a workload's DBU spend jumped by more than
-- a threshold percentage compared to its 7-day trailing average.
-- Useful as an "alert" widget on a dashboard, not as a hard
-- budget alert (those live in the account console).
--
-- Less useful on day 1 with no history. Once a workload has
-- been tagged for 2+ weeks, this view surfaces new cost patterns
-- (e.g. "someone added a cross-join on Tuesday night") before
-- they compound over a full billing cycle.
--
-- Default threshold: 50% increase vs. the trailing 7-day mean.
-- Change the WHERE clause to tune sensitivity.

WITH daily AS (
    SELECT
        usage.usage_date                             AS day,
        usage.custom_tags.workload                   AS workload,
        SUM(usage.usage_quantity)                    AS dbu
    FROM system.billing.usage AS usage
    WHERE usage.usage_date >= DATE_SUB(CURRENT_DATE(), 60)
        AND usage.custom_tags.workload IS NOT NULL
    GROUP BY usage.usage_date, usage.custom_tags.workload
),
windowed AS (
    SELECT
        day,
        workload,
        dbu,
        AVG(dbu) OVER (
            PARTITION BY workload
            ORDER BY day
            ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING
        )                                            AS trailing_7d_mean,
        LAG(dbu, 1) OVER (
            PARTITION BY workload
            ORDER BY day
        )                                            AS prev_day_dbu
    FROM daily
)
SELECT
    day,
    workload,
    ROUND(dbu, 2)                                    AS dbu,
    ROUND(trailing_7d_mean, 2)                       AS trailing_7d_mean,
    ROUND(prev_day_dbu, 2)                           AS prev_day_dbu,
    ROUND(
        (dbu - trailing_7d_mean) / NULLIF(trailing_7d_mean, 0) * 100,
        1
    )                                                AS pct_increase_vs_7d
FROM windowed
WHERE
    trailing_7d_mean IS NOT NULL
    AND trailing_7d_mean > 0
    -- Only flag if the workload spent at least a meaningful
    -- baseline. Without this, a workload that spent 0.01 DBU
    -- yesterday and 0.03 today shows as a 200% spike, which is
    -- noise.
    AND trailing_7d_mean > 1.0
    AND (dbu - trailing_7d_mean) / trailing_7d_mean > 0.5
ORDER BY pct_increase_vs_7d DESC;
