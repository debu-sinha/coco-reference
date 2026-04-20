"""Run (async SQL execution) tracking.

Tracks Statement Execution API calls and their status.
"""
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
class Run:
    """Async SQL execution run."""
    id: UUID
    thread_id: UUID
    message_id: UUID
    statement_id: Optional[str] = None
    status: str = "pending"  # pending | running | succeeded | failed
    error: Optional[str] = None
    result_metadata: Optional[dict] = None
    created_at: datetime = None
    updated_at: datetime = None


async def create_run(
    client: LakebaseClient,
    thread_id: UUID,
    message_id: UUID,
    statement_id: Optional[str] = None
) -> Run:
    """Create new run.

    Args:
        client: Lakebase client
        thread_id: Parent thread ID
        message_id: Associated message ID
        statement_id: Optional Statement Execution API ID

    Returns:
        Created Run object
    """
    query = """
    INSERT INTO runs (thread_id, message_id, statement_id)
    VALUES (%s, %s, %s)
    RETURNING id, thread_id, message_id, statement_id, status,
              error, result_metadata, created_at, updated_at
    """
    row = await client.execute_one(query, (thread_id, message_id, statement_id))
    return _row_to_run(row)


async def update_run_status(
    client: LakebaseClient,
    run_id: UUID,
    status: str,
    error: Optional[str] = None,
    result_metadata: Optional[dict] = None
) -> None:
    """Update run status.

    Args:
        client: Lakebase client
        run_id: Run ID
        status: New status
        error: Optional error message
        result_metadata: Optional result metadata dict

    Raises:
        ValueError: If run not found
    """
    result_metadata_json = (
        json.dumps(result_metadata) if result_metadata else None
    )

    query = """
    UPDATE runs
    SET status = %s, error = %s, result_metadata = %s, updated_at = NOW()
    WHERE id = %s
    """
    await client.insert(
        query,
        (status, error, result_metadata_json, run_id)
    )
    logger.debug(f"Updated run {run_id} status to {status}")


async def get_pending_runs_for_thread(
    client: LakebaseClient,
    thread_id: UUID
) -> list[Run]:
    """Get all pending runs for a thread.

    Args:
        client: Lakebase client
        thread_id: Thread ID

    Returns:
        List of pending Run objects
    """
    query = """
    SELECT id, thread_id, message_id, statement_id, status,
           error, result_metadata, created_at, updated_at
    FROM runs
    WHERE thread_id = %s AND status = 'pending'
    ORDER BY created_at ASC
    """
    rows = await client.execute(query, (thread_id,))
    return [_row_to_run(row) for row in rows]


async def get_run(
    client: LakebaseClient,
    run_id: UUID
) -> Optional[Run]:
    """Get run by ID.

    Args:
        client: Lakebase client
        run_id: Run ID

    Returns:
        Run object or None if not found
    """
    query = """
    SELECT id, thread_id, message_id, statement_id, status,
           error, result_metadata, created_at, updated_at
    FROM runs
    WHERE id = %s
    """
    row = await client.execute_one(query, (run_id,))
    return _row_to_run(row) if row else None


def _row_to_run(row: tuple | None) -> Optional[Run]:
    """Convert database row to Run object."""
    if not row:
        return None

    result_metadata = None
    if row[6]:  # result_metadata column
        try:
            result_metadata = json.loads(row[6])
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse result_metadata JSON for run {row[0]}")

    return Run(
        id=row[0],
        thread_id=row[1],
        message_id=row[2],
        statement_id=row[3],
        status=row[4],
        error=row[5],
        result_metadata=result_metadata,
        created_at=row[7],
        updated_at=row[8]
    )
