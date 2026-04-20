"""Lakebase (Postgres) connection pool for session state.

Databricks Apps + Lakebase is a typed resource binding. When the app's
`resources:` list includes `AppResourceDatabase(...)`, Databricks:

  1. Creates a Postgres role named after the app's SP client id.
  2. Grants that role CONNECT + CREATE on the selected database.
  3. Injects the connection details as env vars:
        PGHOST, PGPORT, PGUSER, PGDATABASE, PGSSLMODE, PGAPPNAME
        (NOT PGPASSWORD - see `_resolve_pgpassword`)

The client here reads those env vars, mints a short-lived OAuth token
as the password, and opens a psycopg pool. Because the token is
~1h TTL but the app container lives much longer, the pool is NOT a
static object - it's rotated via `get_pool()` whenever the token is
near expiry, so query helpers never get handed a pool with stale
credentials.

Override for local development / unit tests: set `COCO_LAKEBASE_CONNSTR`
to a full psycopg connection string and the env-var path is skipped.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Awaitable, Callable, Optional

from psycopg_pool import AsyncConnectionPool, PoolTimeout

from .schema import COCO_APP_SCHEMA, SCHEMA_DDL  # noqa: F401

# Lakebase `generate_database_credential` returns a short-lived OAuth
# token. The documented TTL is ~1h. We model it as a fixed 60min TTL
# with a 5min safety margin, meaning `get_pool()` will proactively
# rebuild the pool with a fresh credential once the token has less
# than 5min of remaining life. If Lakebase ever exposes an explicit
# `expires_in` on the credential response, switch this to read that
# field instead of assuming.
_TOKEN_TTL_S = 60 * 60
_TOKEN_SAFETY_MARGIN_S = 5 * 60

logger = logging.getLogger(__name__)


def _resolve_pgpassword() -> str:
    """Mint a fresh Lakebase OAuth token to use as PGPASSWORD.

    Databricks Apps auto-injects PGHOST/PGUSER/PGDATABASE/PGPORT/
    PGSSLMODE/PGAPPNAME from the database resource binding, but
    deliberately does NOT inject PGPASSWORD - the password is a
    short-lived OAuth credential that would be stale the moment the
    container starts. The app is expected to mint it on demand using
    the service principal credentials (DATABRICKS_CLIENT_ID /
    DATABRICKS_CLIENT_SECRET, also auto-injected).
    """
    # Local dev / tests can override with a static password.
    if os.environ.get("PGPASSWORD"):
        return os.environ["PGPASSWORD"]

    from uuid import uuid4

    from databricks.sdk import WorkspaceClient

    pghost = os.environ.get("PGHOST", "")
    ws = WorkspaceClient()

    instance_name = os.environ.get("COCO_LAKEBASE_INSTANCE")
    if not instance_name:
        # Fall back to scanning the workspace's instances and matching
        # by read_write_dns. Works without knowing the name up front
        # but adds one API call to cold start.
        for inst in ws.database.list_database_instances():
            if getattr(inst, "read_write_dns", None) == pghost:
                instance_name = inst.name
                break
    if not instance_name:
        raise RuntimeError(
            f"Could not find Lakebase instance for PGHOST={pghost}. "
            f"Set COCO_LAKEBASE_INSTANCE explicitly or verify the app's "
            f"database resource binding."
        )

    cred = ws.database.generate_database_credential(
        instance_names=[instance_name],
        request_id=str(uuid4()),
    )
    if not cred.token:
        raise RuntimeError("generate_database_credential returned empty token")
    return cred.token


def _build_connstr_from_env() -> str:
    """Assemble a keyword-form connstr from PG* env vars + minted token.

    Keyword form avoids URL-escaping the password and matches what
    psycopg expects by default. Called once per pool rebuild so the
    fresh token is picked up.
    """
    override = os.environ.get("COCO_LAKEBASE_CONNSTR")
    if override:
        return override

    required = ("PGHOST", "PGUSER", "PGDATABASE")
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise RuntimeError(
            f"Lakebase env vars missing: {missing}. Expected the app's "
            f"database resource binding to inject PG* env vars at "
            f"deploy time. Check the app's Resources tab."
        )

    password = _resolve_pgpassword()

    parts = [
        f"host={os.environ['PGHOST']}",
        f"port={os.environ.get('PGPORT', '5432')}",
        f"user={os.environ['PGUSER']}",
        f"password={password}",
        f"dbname={os.environ['PGDATABASE']}",
        f"sslmode={os.environ.get('PGSSLMODE', 'require')}",
    ]
    app_name = os.environ.get("PGAPPNAME")
    if app_name:
        parts.append(f"application_name={app_name}")
    return " ".join(parts)


def _is_probable_auth_expiry(e: BaseException) -> bool:
    """Heuristic: is this exception likely a Lakebase auth-expiry failure?

    `psycopg_pool` surfaces auth failures as `PoolTimeout` because its
    background workers retry silently and the user-visible error is
    "couldn't get a connection after Xs". So we treat PoolTimeout as
    likely-auth and force a rebuild. We also look for auth-like
    keywords in the exception message for operational errors surfacing
    directly (e.g. `psycopg.OperationalError`).
    """
    if isinstance(e, PoolTimeout):
        return True
    msg = str(e).lower()
    return any(kw in msg for kw in ("password", "auth", "expired", "token"))


class LakebaseClient:
    """Async Postgres connection pool with short-lived OAuth credentials.

    Reads connection details from the PG* env vars the Databricks Apps
    runtime injects when the app has a database resource binding. The
    password is minted per-pool-lifetime via the Databricks SDK and
    the pool is proactively rotated before the token expires.

    Usage: all callers go through the query helpers (`execute`,
    `execute_one`, `execute_scalar`, `insert`), which internally route
    every checkout through `get_pool()` to ensure the pool's credentials
    are still valid before handing out a connection.
    """

    def __init__(
        self,
        min_conns: int = 1,
        max_conns: int = 10,
    ) -> None:
        """Initialize (does not open the pool)."""
        self.min_conns = min_conns
        self.max_conns = max_conns
        self.pool: Optional[AsyncConnectionPool] = None
        self._connstr: Optional[str] = None
        # Wall-clock epoch seconds when the current token is expected
        # to expire. 0.0 means no live token. Checked by `get_pool()`
        # against `time.time() + _TOKEN_SAFETY_MARGIN_S` to decide
        # whether a proactive rebuild is needed.
        self._expires_at: float = 0.0
        # Lock so concurrent requests don't race on pool rotation.
        self._refresh_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Factories (kept for backward compatibility with the FastAPI app
    # startup code; both return the same env-var-driven client)
    # ------------------------------------------------------------------

    @classmethod
    def for_service(cls) -> "LakebaseClient":
        """Client for the app's own service principal (via PG* env vars)."""
        return cls()

    @classmethod
    def for_user(cls, access_token: str) -> "LakebaseClient":
        """Retained for API compatibility.

        Lakebase OBO auth isn't available via Databricks Apps OAuth
        scopes, so we fall back to the same SP-backed env-var connection.
        The `access_token` argument is ignored.
        """
        del access_token
        return cls()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the async connection pool with a freshly-minted token."""
        if self.pool is not None:
            return

        if self._connstr is None:
            self._connstr = _build_connstr_from_env()

        # Pin search_path to our SP-owned schema for every libpq
        # connection, via the PGOPTIONS env var. The SP has CREATE on
        # the database (from the Apps database resource binding) but
        # NOT on `public` (Postgres 15+). ensure_schema() creates
        # `coco_app` and owns it, and PGOPTIONS makes every new pooled
        # connection default to it so query helpers can keep writing
        # unqualified table names.
        existing_pgoptions = os.environ.get("PGOPTIONS", "")
        want = f"-c search_path={COCO_APP_SCHEMA},public"
        if want not in existing_pgoptions:
            os.environ["PGOPTIONS"] = (
                f"{existing_pgoptions} {want}".strip() if existing_pgoptions else want
            )

        logger.info(
            "Opening Lakebase pool: min=%d max=%d PGOPTIONS=%s",
            self.min_conns,
            self.max_conns,
            os.environ.get("PGOPTIONS"),
        )
        self.pool = AsyncConnectionPool(
            self._connstr,
            min_size=self.min_conns,
            max_size=self.max_conns,
            timeout=10.0,
            open=False,
        )
        # wait=True forces the real libpq connect error to surface here
        # instead of showing up later as an opaque PoolTimeout.
        await self.pool.open(wait=True, timeout=30.0)
        self._expires_at = time.time() + _TOKEN_TTL_S
        logger.info(
            "Lakebase pool opened; credential expires_at=%s",
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._expires_at)),
        )

    async def close(self) -> None:
        """Close the async connection pool."""
        if self.pool is not None:
            await self.pool.close()
            self.pool = None
            self._connstr = None
            self._expires_at = 0.0
            logger.info("Lakebase pool closed")

    async def _force_rebuild(self) -> None:
        """Tear down the current pool and re-open with a fresh credential.

        Caller must already hold `self._refresh_lock`.
        """
        if self.pool is not None:
            try:
                await self.pool.close()
            except Exception as e:
                logger.warning("Error closing stale Lakebase pool during rebuild: %s", e)
        self.pool = None
        self._connstr = None
        self._expires_at = 0.0
        await self.connect()

    async def get_pool(self) -> AsyncConnectionPool:
        """Return the current pool, proactively rotating if needed.

        Every query helper goes through this method. If the token is
        fresh, this is a single wall-clock comparison. If the token is
        within `_TOKEN_SAFETY_MARGIN_S` of expiry (or already expired),
        the pool is torn down under a lock and rebuilt with a fresh
        credential before the pool is returned.

        Raises:
            RuntimeError if the pool cannot be built.
        """
        now = time.time()
        if self.pool is not None and now < self._expires_at - _TOKEN_SAFETY_MARGIN_S:
            return self.pool

        async with self._refresh_lock:
            # Re-check under the lock; another task may have already
            # rotated the pool while we were waiting for the lock.
            now = time.time()
            if self.pool is not None and now < self._expires_at - _TOKEN_SAFETY_MARGIN_S:
                return self.pool

            if self.pool is None:
                logger.info("Opening Lakebase pool (first connect)")
            else:
                remaining = self._expires_at - now
                logger.info(
                    "Refreshing Lakebase DB token and recreating pool "
                    "(token %0.0fs from expiry, safety margin %ds)",
                    remaining,
                    _TOKEN_SAFETY_MARGIN_S,
                )
            await self._force_rebuild()
            if self.pool is None:
                raise RuntimeError("Connection pool not initialized after rebuild")
            return self.pool

    async def _run(
        self,
        fn: Callable[[AsyncConnectionPool], Awaitable[Any]],
    ) -> Any:
        """Run a pool-accepting async callable with one auth-failure retry.

        The happy path: grab the current (fresh) pool via get_pool(),
        call `fn(pool)`, return the result.

        The failure path: if the call raises an exception that looks
        like an auth expiry (PoolTimeout, or operational error with
        auth keywords), force-rebuild the pool with a fresh credential
        and retry the callable exactly once. Any other exception
        propagates immediately.

        This catches edge cases the proactive `get_pool()` staleness
        check misses, like clock skew or a credential being revoked
        server-side.
        """
        pool = await self.get_pool()
        try:
            return await fn(pool)
        except Exception as e:
            if not _is_probable_auth_expiry(e):
                raise
            logger.warning(
                "Lakebase checkout/query failed with likely auth expiry. "
                "Rebuilding pool and retrying once. Error: %s",
                e,
            )
            async with self._refresh_lock:
                await self._force_rebuild()
            if self.pool is None:
                raise RuntimeError("Connection pool not initialized after rebuild")
            return await fn(self.pool)

    async def health(self) -> bool:
        """Check database connectivity with a trivial query."""
        if self.pool is None:
            return False
        try:

            async def _probe(pool: AsyncConnectionPool) -> None:
                async with pool.connection() as conn:
                    await conn.execute("SELECT 1")

            await self._run(_probe)
            return True
        except Exception as e:
            logger.error("Health check failed: %s", e)
            return False

    async def ensure_schema(self) -> None:
        """Create tables and indexes idempotently. Call once at startup."""
        logger.info("Ensuring session schema")

        async def _apply(pool: AsyncConnectionPool) -> None:
            async with pool.connection() as conn:
                async with conn.transaction():
                    await conn.execute(SCHEMA_DDL)

        await self._run(_apply)
        logger.info("Session schema ready")

    # ------------------------------------------------------------------
    # Query helpers used by threads.py / messages.py / runs.py / feedback.py
    # ------------------------------------------------------------------

    async def execute(
        self,
        query: str,
        params: Optional[tuple] = None,
    ) -> list[tuple]:
        """Execute a query and return all rows."""

        async def _inner(pool: AsyncConnectionPool) -> list[tuple]:
            async with pool.connection() as conn:
                result = await conn.execute(query, params)
                return await result.fetchall()

        return await self._run(_inner)

    async def execute_one(
        self,
        query: str,
        params: Optional[tuple] = None,
    ) -> Optional[tuple]:
        """Execute a query and return the first row, or None."""

        async def _inner(pool: AsyncConnectionPool) -> Optional[tuple]:
            async with pool.connection() as conn:
                result = await conn.execute(query, params)
                return await result.fetchone()

        return await self._run(_inner)

    async def execute_scalar(
        self,
        query: str,
        params: Optional[tuple] = None,
    ) -> Any:
        """Execute a query and return the first column of the first row."""

        async def _inner(pool: AsyncConnectionPool) -> Any:
            async with pool.connection() as conn:
                result = await conn.execute(query, params)
                row = await result.fetchone()
                return row[0] if row else None

        return await self._run(_inner)

    async def insert(
        self,
        query: str,
        params: Optional[tuple] = None,
    ) -> None:
        """Execute an insert/update/delete inside a transaction."""

        async def _inner(pool: AsyncConnectionPool) -> None:
            async with pool.connection() as conn:
                async with conn.transaction():
                    await conn.execute(query, params)

        await self._run(_inner)
