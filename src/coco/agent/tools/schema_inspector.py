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
from typing import Any

from databricks.sdk import WorkspaceClient

from coco.agent.models import SchemaInspectorResult
from coco.config import get_config

logger = logging.getLogger(__name__)

# Domain-specific table names are NOT hardcoded here anymore. The agent
# reads the active domain spec (domains/<your-domain>/domain.yaml) and
# uses the tables listed there. The healthcare reference domain still
# lists patients/diagnoses/etc; see domains/healthcare/domain.yaml.


def _probe_table_sync(
    ws: WorkspaceClient,
    warehouse_id: str,
    full_name: str,
) -> tuple[list[dict], str | None]:
    """Fetch table column metadata via the UC `tables.get` API.

    Returns a `(columns, error)` tuple. On success, `error` is None and
    `columns` is a list of `{name, type, comment, nullable}` dicts.
    On failure (table doesn't exist, no UC access), returns
    `([], <error_message>)` rather than raising.

    Why UC metadata API and not `SELECT * LIMIT 0`: the Mosaic AI Agent
    Framework serving container runs as a platform-managed System
    Service Principal that admins cannot modify, so it cannot be
    granted the `databricks-sql-access` workspace entitlement that the
    Statement Execution API requires. UC `tables.get` works with only
    USE_CATALOG, USE_SCHEMA, and SELECT on the table (or BROWSE), which
    the framework auto-grants through the `DatabricksTable(...)`
    resource declaration on the logged model.
    """
    # warehouse_id is intentionally unused now (UC metadata API doesn't
    # need a warehouse). Kept in the signature so callers don't have to
    # change.
    del warehouse_id
    try:
        t = ws.tables.get(full_name)
        cols: list[dict] = []
        for c in t.columns or []:
            cols.append(
                {
                    "name": c.name or "",
                    "type": c.type_text or "STRING",
                    "comment": c.comment or "",
                    "nullable": c.nullable if c.nullable is not None else True,
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
        # table the active domain spec declares; caller can narrow it.
        from coco.domain import get_domain

        domain = get_domain()
        candidates: list[str] = list(domain.table_names)
        if tables:
            wanted = set(tables)
            candidates = [c for c in candidates if c in wanted]
            # Also include any caller-supplied names not already in the
            # default list, in case the agent knows about extras.
            for t in tables:
                if t not in candidates:
                    candidates.append(t)

        # For UC metadata reads (tables.get), use the System SP via the
        # default WorkspaceClient. The model is logged with
        # DatabricksTable(...) resources, and the agent framework
        # auto-grants the System SP SELECT/BROWSE on those tables, which
        # is what tables.get needs. The forwarded user OBO token does NOT
        # need the unity-catalog OAuth scope for this path because we
        # are not using it. OBO is reserved for execute_sql where the
        # user's sql scope is what matters.
        ws = WorkspaceClient()
        # Log the identity the agent authenticates as so workspace
        # entitlement issues (e.g. missing databricks-sql-access on the
        # served-entity SP) can be diagnosed without container access.
        try:
            _me = ws.current_user.me()
            _identity = f"{_me.user_name} (id={getattr(_me, 'id', '?')})"
            logger.info("inspect_schema: runtime identity = %s", _identity)
        except Exception as _id_err:
            _identity = f"resolution failed: {_id_err}"
            logger.warning(
                "inspect_schema: could not resolve runtime identity: %s",
                _id_err,
            )
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

        errors: dict[str, str] = {}
        for name, cols, err in probe_results:
            if err:
                logger.warning("inspect_schema: skipping %s (%s)", name, err)
                errors[name] = str(err)
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
            "inspect_schema: %d tables, %d columns, %d errors",
            len(table_list),
            sum(len(v) for v in columns_by_table.values()),
            len(errors),
        )
        if not table_list and errors:
            # Inject the runtime identity into the first error so the
            # agent's user-facing response reveals exactly which principal
            # is missing the workspace entitlements.
            first_key = next(iter(errors))
            errors[first_key] = f"[runtime identity: {_identity}] {errors[first_key]}"
        return SchemaInspectorResult(tables=table_list, columns=columns_by_table, errors=errors)

    except Exception as e:
        logger.exception("Schema inspection failed: %s", e)
        return SchemaInspectorResult(tables=[], columns={})
