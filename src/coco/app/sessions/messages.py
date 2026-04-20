"""Message CRUD operations."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

from .lakebase import LakebaseClient

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """Chat message (user or assistant)."""

    id: UUID
    thread_id: UUID
    role: str  # 'user' or 'assistant'
    content: str
    tool_calls: Optional[list[dict]] = None
    trace_id: Optional[str] = None
    created_at: datetime = None
    # 1 = thumbs up, -1 = thumbs down, None = not yet rated.
    # Populated by get_messages when a user_id is supplied; always None
    # from add_message (a newly-created row has no feedback yet).
    feedback_rating: Optional[int] = None


async def add_message(
    client: LakebaseClient,
    thread_id: UUID,
    role: str,
    content: str,
    tool_calls: Optional[list[dict]] = None,
    trace_id: Optional[str] = None,
) -> Message:
    """Add message to thread.

    Args:
        client: Lakebase client
        thread_id: Parent thread ID
        role: 'user' or 'assistant'
        content: Message text
        tool_calls: Optional tool invocations
        trace_id: Optional trace ID for observability

    Returns:
        Created Message object
    """
    tool_calls_json = json.dumps(tool_calls) if tool_calls else None

    query = """
    INSERT INTO messages (thread_id, role, content, tool_calls, trace_id)
    VALUES (%s, %s, %s, %s, %s)
    RETURNING id, thread_id, role, content, tool_calls, trace_id, created_at
    """
    row = await client.execute_one(query, (thread_id, role, content, tool_calls_json, trace_id))

    # Also update thread.updated_at
    await client.insert("UPDATE threads SET updated_at = NOW() WHERE id = %s", (thread_id,))

    return _row_to_message(row)


async def get_messages(
    client: LakebaseClient,
    thread_id: UUID,
    limit: int = 100,
    user_id: Optional[str] = None,
) -> list[Message]:
    """Get messages for thread, oldest first.

    When user_id is supplied, each assistant message is LEFT JOINed to
    its feedback row (if any) so the UI can render the correct thumb
    state instead of showing unvoted buttons after a reload.
    """
    if user_id is None:
        query = """
        SELECT id, thread_id, role, content, tool_calls, trace_id, created_at, NULL
        FROM messages
        WHERE thread_id = %s
        ORDER BY created_at ASC
        LIMIT %s
        """
        params: tuple = (thread_id, limit)
    else:
        query = """
        SELECT m.id, m.thread_id, m.role, m.content, m.tool_calls,
               m.trace_id, m.created_at, f.rating
        FROM messages m
        LEFT JOIN feedback f
            ON f.message_id = m.id AND f.user_id = %s
        WHERE m.thread_id = %s
        ORDER BY m.created_at ASC
        LIMIT %s
        """
        params = (user_id, thread_id, limit)
    rows = await client.execute(query, params)
    return [_row_to_message(row) for row in rows]


async def get_history_for_agent(
    client: LakebaseClient, thread_id: UUID, max_tokens: int = 4000
) -> list[dict]:
    """Get message history formatted for agent input.

    Trims from oldest messages to fit within max_tokens.
    Returns OpenAI-compatible format: [{"role": "...", "content": "..."}]

    Args:
        client: Lakebase client
        thread_id: Thread ID
        max_tokens: Maximum tokens (rough estimate: 4 chars per token)

    Returns:
        List of formatted messages
    """
    messages = await get_messages(client, thread_id, limit=100)

    # Build messages in reverse (newest first) and trim
    result: list[dict] = []
    char_count = 0
    chars_per_token = 4

    for msg in reversed(messages):
        formatted = {"role": msg.role, "content": msg.content}

        msg_chars = len(msg.content)
        if char_count + msg_chars > (max_tokens * chars_per_token):
            logger.debug(f"Trimming message history at {len(result)} messages, {char_count} chars")
            break

        result.insert(0, formatted)
        char_count += msg_chars

    return result


def _row_to_message(row: tuple | None) -> Optional[Message]:
    """Convert database row to Message object."""
    if not row:
        return None

    tool_calls = None
    if row[4]:  # tool_calls column
        try:
            tool_calls = json.loads(row[4])
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse tool_calls JSON for message {row[0]}")

    feedback_rating = row[7] if len(row) > 7 and row[7] is not None else None
    return Message(
        id=row[0],
        thread_id=row[1],
        role=row[2],
        content=row[3],
        tool_calls=tool_calls,
        trace_id=row[5],
        created_at=row[6],
        feedback_rating=feedback_rating,
    )
