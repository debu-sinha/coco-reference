"""Feedback (thumbs up/down) operations."""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from .lakebase import LakebaseClient

logger = logging.getLogger(__name__)


async def set_feedback(
    client: LakebaseClient,
    message_id: UUID,
    user_id: str,
    rating: int,
    comment: Optional[str] = None,
) -> Optional[int]:
    """Set the user's rating for a message.

    rating = 1 → thumbs up, -1 → thumbs down, 0 → clear the rating.
    Idempotent: repeat clicks upsert via the UNIQUE (message_id, user_id)
    constraint so the optimizer's training set never double-counts.

    Returns the rating that is now in effect for that (message, user),
    or None if no row exists (after a clear).
    """
    if rating not in (-1, 0, 1):
        raise ValueError(f"Rating must be -1, 0, or 1, got {rating}")

    if rating == 0:
        await client.insert(
            "DELETE FROM feedback WHERE message_id = %s AND user_id = %s",
            (message_id, user_id),
        )
        logger.debug("Cleared feedback: message_id=%s user_id=%s", message_id, user_id)
        return None

    # Requires the UNIQUE(message_id, user_id) constraint added in schema.py.
    query = """
    INSERT INTO feedback (message_id, user_id, rating, comment)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (message_id, user_id) DO UPDATE
      SET rating = EXCLUDED.rating,
          comment = EXCLUDED.comment,
          updated_at = NOW()
    """
    await client.insert(query, (message_id, user_id, rating, comment))
    logger.debug(
        "Upserted feedback: message_id=%s rating=%s has_comment=%s",
        message_id,
        rating,
        bool(comment),
    )
    return rating


# Kept for backward-compat with older callers that pass 1 or -1 only.
async def add_feedback(
    client: LakebaseClient,
    message_id: UUID,
    user_id: str,
    rating: int,
    comment: Optional[str] = None,
) -> None:
    await set_feedback(client, message_id, user_id, rating, comment)
