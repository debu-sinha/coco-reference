"""MLflow Inference Tables for Model Serving endpoint monitoring.

Queries auto-captured inference logs from a Model Serving endpoint
to analyze model behavior, latency, and feature drift.
"""
from __future__ import annotations

import logging
from typing import Optional

from coco.sql import StatementClient

logger = logging.getLogger(__name__)


async def query_recent_inferences(
    endpoint_name: str,
    hours: int = 24,
    limit: int = 1000,
) -> list[dict]:
    """Query recent inference logs from endpoint.

    MLflow Model Serving automatically logs inferences to
    inference tables. This helper queries them for analysis.

    Args:
        endpoint_name: Name of Model Serving endpoint
        hours: Look back N hours (default 24)
        limit: Max rows (default 1000)

    Returns:
        List of inference dicts with inputs, outputs, latency, etc.

    Raises:
        StatementFailed: If query fails
    """
    try:
        client = StatementClient()

        # Inference table naming convention:
        # ai.databricks_model_serving.{endpoint_name}
        inference_table = (
            f"ai.databricks_model_serving.{endpoint_name}"
        )

        sql = f"""
            SELECT
                *
            FROM {inference_table}
            WHERE timestamp > NOW() - INTERVAL {hours} HOUR
            ORDER BY timestamp DESC
            LIMIT {limit}
        """

        logger.debug(
            "Querying inference table %s; hours=%d",
            inference_table,
            hours,
        )

        statement_id = await client.submit(sql)

        # Poll for completion
        from coco.sql import StatementStatus

        status = await client.poll(statement_id)

        if status != StatementStatus.SUCCEEDED:
            logger.warning(
                "Inference query failed; status=%s",
                status.value,
            )
            return []

        # Fetch and convert results
        inferences = []
        async for batch in client.fetch_results(statement_id):
            for record in batch.to_pylist():
                inferences.append(record)

        logger.debug(
            "Retrieved %d inference records", len(inferences)
        )

        return inferences

    except Exception as e:
        logger.warning(
            "Failed to query inference table %s: %s",
            endpoint_name,
            e,
        )
        return []


async def analyze_inference_latency(
    endpoint_name: str,
    hours: int = 24,
) -> dict:
    """Analyze latency distribution from inference logs.

    Computes percentiles (p50, p95, p99) and identifies
    slow requests for debugging.

    Args:
        endpoint_name: Model Serving endpoint name
        hours: Look back N hours

    Returns:
        Dict with latency stats: p50, p95, p99, max, min, mean
    """
    try:
        client = StatementClient()

        inference_table = (
            f"ai.databricks_model_serving.{endpoint_name}"
        )

        sql = f"""
            SELECT
                percentile_cont(0.5) OVER () as p50,
                percentile_cont(0.95) OVER () as p95,
                percentile_cont(0.99) OVER () as p99,
                MAX(execution_time_ms) as max_latency,
                MIN(execution_time_ms) as min_latency,
                AVG(execution_time_ms) as mean_latency,
                COUNT(*) as num_requests
            FROM {inference_table}
            WHERE timestamp > NOW() - INTERVAL {hours} HOUR
            LIMIT 1
        """

        statement_id = await client.submit(sql)

        from coco.sql import StatementStatus
        status = await client.poll(statement_id)

        if status != StatementStatus.SUCCEEDED:
            return {}

        results = []
        async for batch in client.fetch_results(statement_id):
            results.extend(batch.to_pylist())

        if results:
            return results[0]

        return {}

    except Exception as e:
        logger.warning(
            "Failed to analyze latency for %s: %s",
            endpoint_name,
            e,
        )
        return {}
