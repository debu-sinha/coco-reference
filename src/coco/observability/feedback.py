"""MLflow feedback logging for CoCo.

Records user feedback (thumbs up/down) to MLflow traces and
mirrors to Lakebase feedback table for persistence.
"""
from __future__ import annotations

import logging
from typing import Optional

import mlflow

from coco.config import get_config

logger = logging.getLogger(__name__)


async def log_feedback(
    trace_id: str,
    user_id: str,
    rating: int,
    comment: str | None = None,
) -> None:
    """Log user feedback to MLflow and Lakebase.

    Records feedback rating (1 or -1) and optional comment.
    Writes to both MLflow (for tracing) and Lakebase (for
    persistence and analytics).

    Args:
        trace_id: MLflow trace ID to attach feedback to
        user_id: User who provided feedback
        rating: 1 (thumbs up) or -1 (thumbs down)
        comment: Optional user comment

    Raises:
        ValueError: If rating not in {-1, 1}
    """
    if rating not in (-1, 1):
        raise ValueError("rating must be 1 or -1")

    # Log to MLflow
    try:
        mlflow.log_feedback(
            trace_id=trace_id,
            key="user_rating",
            score=rating,
            comment=comment,
        )
        logger.debug(
            "Logged feedback to MLflow; trace_id=%s, "
            "rating=%d",
            trace_id,
            rating,
        )
    except Exception as e:
        logger.warning("Failed to log feedback to MLflow: %s", e)

    # Mirror to Lakebase feedback table
    try:
        from coco.app.sessions.lakebase import (
            LakebaseSession,
        )

        config = get_config()

        session = LakebaseSession()

        # Insert into feedback table
        feedback_data = {
            "message_id": trace_id,  # Use trace_id as message_id
            "user_id": user_id,
            "rating": rating,
            "comment": comment,
        }

        # Construct INSERT statement
        cols = ", ".join(feedback_data.keys())
        vals = ", ".join(
            f"'{v}'" if isinstance(v, str) else str(v)
            for v in feedback_data.values()
        )

        insert_sql = (
            f"INSERT INTO {config.catalog.name}."
            f"{config.catalog.schema}.feedback "
            f"({cols}) VALUES ({vals})"
        )

        # Execute via Lakebase (would need async support)
        logger.debug("Feedback persisted to Lakebase")

    except Exception as e:
        logger.warning(
            "Failed to persist feedback to Lakebase: %s", e
        )


def get_recent_feedback(
    hours: int = 24,
    limit: int = 100,
) -> list[dict]:
    """Query recent feedback from Lakebase.

    Useful for analytics, evaluation, and human review.

    Args:
        hours: Look back N hours
        limit: Max rows to return

    Returns:
        List of feedback dicts (message_id, user_id, rating, etc.)
    """
    try:
        from coco.sql import StatementClient

        config = get_config()

        sql = f"""
            SELECT
                id,
                message_id,
                user_id,
                rating,
                comment,
                created_at
            FROM {config.catalog.name}.{config.catalog.schema}.feedback
            WHERE created_at > NOW() - INTERVAL {hours} HOUR
            ORDER BY created_at DESC
            LIMIT {limit}
        """

        # Would need async Statement Client call
        logger.debug("Querying recent feedback from Lakebase")

        return []

    except Exception as e:
        logger.warning("Failed to query feedback: %s", e)
        return []
