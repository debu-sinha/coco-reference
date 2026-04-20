"""Schema inspection tool for table and column metadata.

Iterates the expected tables from `config.tables` and probes each one
with `SELECT * FROM <fq_name> LIMIT 0` via the Databricks Statement
Execution API. Reads the statement manifest's `schema.columns` block
for column name + type metadata. Zero rows returned, but the manifest
carries the schema, so a LIMIT 0 probe is the cheapest way to confirm
a table exists AND get its columns at the same time.

Why not `system.information_schema.tables`: that view is filtered by
`USE_CATALOG + USE_SCHEMA` on the querying principal. The Mosaic AI
Agent Framework serving container only gets the grants you declare
via typed `resources` on the logged model, and `DatabricksTable(...)`
grants SELECT on the specific table, not USE_SCHEMA on its parent.
So the information_schema path returned zero rows from inside the
serving container even though the tables exist and the SP can
SELECT from them.

Why not `client.tables.list(...)`: same reason, worse. The UC metadata
API requires BROWSE or USE_SCHEMA.

The `SELECT * LIMIT 0` path uses only the grants the serving SP
actually has (DatabricksSQLWarehouse + DatabricksTable), so it works
without any additional permission plumbing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

from coco.agent.models import SchemaInspectorResult
from coco.config import get_config

logger = logging.getLogger(__name__)

# Expected cohort tables. Order matters for display consistency in
# agent output.
_COHORT_TABLE_ATTRS = (
    "patients",
    "diagnoses",
    "prescriptions",
    "procedures",
    "claims",
    "suppliers",
)


def _probe_table_sync(
    ws: WorkspaceClient,
    warehouse_id: str,
    full_name: str,
) -> tuple[list[dict], str | None]:
    """Run `SELECT * FROM <full_name> LIMIT 0` and return column metadata.

    Returns a `(columns, error)` tuple. On success, `error` is None and
    `columns` is a list of `{name, type, comment, nullable}` dicts.
    On failure (table doesn't exist, permission denied, warehouse
    busy), returns `([], <error_message>)` rather than raising, so one
    missing table doesn't kill the whole inspection.
    """
    try:
        r = ws.statement_execution.execute_statement(
            statement=f"SELECT * FROM {full_name} LIMIT 0",
            warehouse_id=warehouse_id,
            wait_timeout="30s",
        )
        # Poll until terminal state
        terminal = {StatementState.SUCCEEDED, StatementState.FAILED, StatementState.CANCELED}
        deadline = time.monotonic() + 30.0
        while r.status and r.status.state not in terminal:
            if time.monotonic() > deadline:
                return [], f"timed out polling {full_name}"
            time.sleep(0.5)
            r = ws.statement_execution.get_statement(r.statement_id)

        if not r.status or r.status.state != StatementState.SUCCEEDED:
            err = (r.status.error.message if r.status and r.status.error else None) or str(
                r.status.state if r.status else "unknown"
            )
            return [], err

        if not (r.manifest and r.manifest.schema and r.manifest.schema.columns):
            return [], "no schema columns in manifest"

        cols: list[dict] = []
        for c in r.manifest.schema.columns:
            cols.append(
                {
                    "name": c.name or "",
                    "type": c.type_text or "STRING",
                    "comment": "",
                    "nullable": True,
                }
            )
        return cols, None
    except Exception as e:
        logger.exception("Probe of %s failed: %s", full_name, e)
        return [], f"{type(e).__name__}: {e}"


async def inspect_schema(tables: list[str] | None = None) -> SchemaInspectorResult:
    """Return table + column metadata for the configured cohort schema.

    Args:
        tables: Optional list of table names to restrict the probe to.
            If None, probes every table listed under `config.tables`
            that matches one of the known cohort attributes.

    Returns:
        SchemaInspectorResult with a `tables` list and a `columns`
        dict keyed by table name. Unreachable tables are silently
        omitted (the agent treats an absent entry as "I don't have
        access to this one"), which matches the behavior of the
        prior information_schema approach when grants were wrong.
    """
    try:
        config = get_config()
        catalog = config.catalog.name
        schema = config.catalog.schema
        warehouse_id = config.sql_warehouse.id
        if not warehouse_id:
            logger.error("inspect_schema: no warehouse id in config")
            return SchemaInspectorResult(tables=[], columns={})

        # Build the set of table names to probe. Default is every
        # known cohort table from config; caller can narrow it.
        candidates: list[str] = []
        for attr in _COHORT_TABLE_ATTRS:
            name = getattr(config.tables, attr, None)
            if name:
                candidates.append(name)
        if tables:
            wanted = set(tables)
            candidates = [c for c in candidates if c in wanted]
            # Also include any caller-supplied names not already in the
            # default list, in case the agent knows about extras.
            for t in tables:
                if t not in candidates:
                    candidates.append(t)

        ws = WorkspaceClient()
        table_list: list[dict] = []
        columns_by_table: dict[str, list[dict]] = {}

        def _probe_all() -> list[tuple[str, list[dict], Any]]:
            results: list[tuple[str, list[dict], Any]] = []
            for name in candidates:
                full_name = f"{catalog}.{schema}.{name}"
                cols, err = _probe_table_sync(ws, warehouse_id, full_name)
                results.append((name, cols, err))
            return results

        # The SDK's statement_execution API is synchronous, so park the
        # whole loop on a worker thread to avoid blocking the agent
        # event loop. Sequential probes are fine for 6 tables.
        probe_results = await asyncio.to_thread(_probe_all)

        for name, cols, err in probe_results:
            if err:
                logger.warning("inspect_schema: skipping %s (%s)", name, err)
                continue
            table_list.append(
                {
                    "name": name,
                    "full_name": f"{catalog}.{schema}.{name}",
                    "comment": "",
                    "table_type": "TABLE",
                }
            )
            columns_by_table[name] = cols

        logger.info(
            "inspect_schema: %d tables, %d columns total",
            len(table_list),
            sum(len(v) for v in columns_by_table.values()),
        )
        return SchemaInspectorResult(tables=table_list, columns=columns_by_table)

    except Exception as e:
        logger.exception("Schema inspection failed: %s", e)
        return SchemaInspectorResult(tables=[], columns={})
