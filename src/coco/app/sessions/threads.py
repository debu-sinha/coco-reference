"""Thread (conversation) CRUD operations."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

from .lakebase import LakebaseClient

logger = logging.getLogger(__name__)


@dataclass
class Thread:
    """Conversation thread."""

    id: UUID
    user_id: str
    title: Optional[str] = None
    archived: bool = False
    created_at: datetime = None
    updated_at: datetime = None


async def create_thread(
    client: LakebaseClient, user_id: str, title: Optional[str] = None
) -> Thread:
    """Create new thread.

    Args:
        client: Lakebase client
        user_id: Owner user ID
        title: Optional thread title

    Returns:
        Created Thread object
    """
    query = """
    INSERT INTO threads (user_id, title)
    VALUES (%s, %s)
    RETURNING id, user_id, title, archived, created_at, updated_at
    """
    row = await client.execute_one(query, (user_id, title))
    return _row_to_thread(row)


async def get_thread(client: LakebaseClient, thread_id: UUID, user_id: str) -> Optional[Thread]:
    """Get thread by ID (enforces user ownership).

    Args:
        client: Lakebase client
        thread_id: Thread ID
        user_id: Expected owner user ID

    Returns:
        Thread object or None if not found or user mismatch
    """
    query = """
    SELECT id, user_id, title, archived, created_at, updated_at
    FROM threads
    WHERE id = %s AND user_id = %s
    """
    row = await client.execute_one(query, (thread_id, user_id))
    return _row_to_thread(row) if row else None


async def list_threads(client: LakebaseClient, user_id: str, limit: int = 50) -> list[Thread]:
    """List threads for user, most recently updated first.

    Args:
        client: Lakebase client
        user_id: User ID
        limit: Maximum threads to return

    Returns:
        List of Thread objects
    """
    query = """
    SELECT id, user_id, title, archived, created_at, updated_at
    FROM threads
    WHERE user_id = %s AND archived = FALSE
    ORDER BY updated_at DESC
    LIMIT %s
    """
    rows = await client.execute(query, (user_id, limit))
    return [_row_to_thread(row) for row in rows]


async def update_thread_title(
    client: LakebaseClient, thread_id: UUID, user_id: str, title: str
) -> None:
    """Update thread title (enforces user ownership).

    Args:
        client: Lakebase client
        thread_id: Thread ID
        user_id: Expected owner user ID
        title: New title

    Raises:
        ValueError: If thread not found or user mismatch
    """
    # First verify ownership
    thread = await get_thread(client, thread_id, user_id)
    if thread is None:
        raise ValueError(f"Thread {thread_id} not found or not owned by {user_id}")

    query = """
    UPDATE threads
    SET title = %s, updated_at = NOW()
    WHERE id = %s AND user_id = %s
    """
    await client.insert(query, (title, thread_id, user_id))
    logger.debug(f"Updated thread {thread_id} title")


async def archive_thread(client: LakebaseClient, thread_id: UUID, user_id: str) -> None:
    """Archive thread (soft delete).

    Args:
        client: Lakebase client
        thread_id: Thread ID
        user_id: Expected owner user ID

    Raises:
        ValueError: If thread not found or user mismatch
    """
    # First verify ownership
    thread = await get_thread(client, thread_id, user_id)
    if thread is None:
        raise ValueError(f"Thread {thread_id} not found or not owned by {user_id}")

    query = """
    UPDATE threads
    SET archived = TRUE, updated_at = NOW()
    WHERE id = %s AND user_id = %s
    """
    await client.insert(query, (thread_id, user_id))
    logger.debug(f"Archived thread {thread_id}")


async def list_archived_threads(
    client: LakebaseClient,
    user_id: str,
    limit: int = 50,
) -> list[Thread]:
    """List archived threads for user, most recently archived first."""
    query = """
    SELECT id, user_id, title, archived, created_at, updated_at
    FROM threads
    WHERE user_id = %s AND archived = TRUE
    ORDER BY updated_at DESC
    LIMIT %s
    """
    rows = await client.execute(query, (user_id, limit))
    return [_row_to_thread(row) for row in rows]


async def restore_thread(
    client: LakebaseClient,
    thread_id: UUID,
    user_id: str,
) -> None:
    """Restore an archived thread."""
    thread = await get_thread(client, thread_id, user_id)
    if thread is None:
        raise ValueError(f"Thread {thread_id} not found or not owned by {user_id}")
    await client.insert(
        "UPDATE threads SET archived = FALSE, updated_at = NOW() WHERE id = %s AND user_id = %s",
        (thread_id, user_id),
    )


async def delete_thread_permanently(
    client: LakebaseClient,
    thread_id: UUID,
    user_id: str,
) -> None:
    """Permanently delete a thread and all its messages."""
    thread = await get_thread(client, thread_id, user_id)
    if thread is None:
        raise ValueError(f"Thread {thread_id} not found or not owned by {user_id}")
    await client.insert("DELETE FROM threads WHERE id = %s AND user_id = %s", (thread_id, user_id))


def _row_to_thread(row: tuple | None) -> Optional[Thread]:
    """Convert database row to Thread object."""
    if not row:
        return None
    return Thread(
        id=row[0],
        user_id=row[1],
        title=row[2],
        archived=row[3],
        created_at=row[4],
        updated_at=row[5],
    )
