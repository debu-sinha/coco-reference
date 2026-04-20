"""Utilities for converting Arrow record batches to dict format.

Handles Arrow deserialization from streaming result chunks.
Truncates results for LLM consumption.
"""
from __future__ import annotations

from typing import Any, Iterator

try:
    import pyarrow as pa
    import pyarrow.compute as pc
except ImportError:
    pa = None
    pc = None


def record_batch_to_dicts(
    batch: pa.RecordBatch,
    max_rows: int | None = None,
) -> list[dict[str, Any]]:
    """Convert Arrow RecordBatch to list of dicts.

    Truncates to max_rows if specified.

    Args:
        batch: PyArrow RecordBatch
        max_rows: Maximum number of rows to include (None = all)

    Returns:
        List of dicts with column names as keys

    Raises:
        ImportError: If pyarrow is not installed
    """
    if pa is None:
        raise ImportError(
            "pyarrow required; install with 'pip install pyarrow'"
        )

    if max_rows is not None and len(batch) > max_rows:
        batch = batch.slice(0, max_rows)

    # Efficient zero-copy conversion to pandas, then to dicts
    df = batch.to_pandas()
    return df.to_dict(orient="records")


def merge_record_batches(
    batches: Iterator[pa.RecordBatch],
    max_rows: int | None = None,
) -> pa.Table:
    """Combine multiple record batches into Arrow table.

    Useful for complete result reconstruction before LLM processing.

    Args:
        batches: Iterator of RecordBatch objects
        max_rows: Maximum total rows (None = all)

    Returns:
        PyArrow Table

    Raises:
        ImportError: If pyarrow is not installed
    """
    if pa is None:
        raise ImportError(
            "pyarrow required; install with 'pip install pyarrow'"
        )

    batch_list = list(batches)
    if not batch_list:
        raise ValueError("No record batches provided")

    table = pa.concat_tables(batch_list)

    if max_rows is not None and len(table) > max_rows:
        table = table.slice(0, max_rows)

    return table


def truncate_result_for_llm(
    table: pa.Table,
    max_rows: int = 100,
) -> list[dict[str, Any]]:
    """Truncate Arrow table for safe LLM consumption.

    Shows first N rows; useful for prompt context limits.

    Args:
        table: PyArrow Table
        max_rows: Number of rows to show (default 100)

    Returns:
        List of dicts, truncated to max_rows
    """
    if pa is None:
        raise ImportError(
            "pyarrow required; install with 'pip install pyarrow'"
        )

    if len(table) > max_rows:
        table = table.slice(0, max_rows)

    return table.to_pandas().to_dict(orient="records")
