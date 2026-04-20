"""FastAPI application factory and startup/shutdown hooks.

Server-rendered HTMX frontend with async Postgres backend.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from starlette.middleware.base import BaseHTTPMiddleware

from coco.config import get_config

from .routes import api, pages, sse
from .sessions.lakebase import LakebaseClient

logger = logging.getLogger(__name__)

# Sliding-window rate limiter: 10 requests/minute per user on the
# /threads/{id}/send endpoint. Stores timestamps of recent requests
# per user_id and rejects with 429 when the window is full.
_RATE_LIMIT = 10
_RATE_WINDOW_SECONDS = 60.0
_send_timestamps: dict[str, list[float]] = defaultdict(list)

# Pattern to match the send endpoint path: /threads/<uuid>/send
import re as _re

_SEND_PATH_RE = _re.compile(r"^/threads/[^/]+/send$")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-user sliding-window rate limiter for the send endpoint."""

    async def dispatch(self, request, call_next):
        if request.method != "POST" or not _SEND_PATH_RE.match(request.url.path):
            return await call_next(request)

        # Extract user_id the same way auth.py does: header -> env -> fallback
        token = request.headers.get("x-forwarded-access-token")
        user_id = os.environ.get("COCO_USER_ID", "anonymous@example.com")
        if token:
            # Grab sub from JWT payload without full decode
            try:
                import base64
                import json

                parts = token.split(".")
                if len(parts) == 3:
                    payload = parts[1]
                    pad = 4 - (len(payload) % 4)
                    if pad != 4:
                        payload += "=" * pad
                    claims = json.loads(base64.urlsafe_b64decode(payload))
                    user_id = claims.get("sub") or claims.get("preferred_username") or user_id
            except Exception:
                pass

        now = time.monotonic()
        cutoff = now - _RATE_WINDOW_SECONDS
        # Prune old entries and check count
        timestamps = _send_timestamps[user_id]
        timestamps[:] = [t for t in timestamps if t > cutoff]

        if len(timestamps) >= _RATE_LIMIT:
            logger.warning("Rate limit hit for user %s (%d in window)", user_id, len(timestamps))
            return JSONResponse(
                status_code=429,
                content={"error": "Too many requests. Limit is 10 per minute."},
            )

        timestamps.append(now)
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log incoming requests and responses."""

    async def dispatch(self, request, call_next):
        """Log request and response."""
        logger.debug(f"{request.method} {request.url.path}")
        response = await call_next(request)
        logger.debug(f"{request.method} {request.url.path} -> {response.status_code}")
        return response


def create_app() -> FastAPI:
    """Create and configure FastAPI application.

    Sets up:
    - Connection to Lakebase Postgres
    - Jinja2 template environment
    - Static files
    - Route handlers
    - CORS and logging middleware
    - Exception handlers

    Returns:
        Configured FastAPI application
    """
    config = get_config()

    app = FastAPI(title=config.app.title, version="2.0.0")

    # CORS — restrict to Databricks Apps domains and localhost for dev.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https://.*\.databricksapps\.com$",
        allow_origins=[
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Per-user rate limiting on the send endpoint
    app.add_middleware(RateLimitMiddleware)

    # Request logging
    app.add_middleware(RequestLoggingMiddleware)

    # Static files and templates
    app_dir = Path(__file__).parent
    static_dir = app_dir / "static"
    template_dir = app_dir / "templates"

    # Mount static directory
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Initialize template environment with a `markdown` filter so
    # stored assistant messages render correctly on page refresh
    # (not just when they arrive via SSE).
    from markdown_it import MarkdownIt

    _md = MarkdownIt("commonmark", {"html": False, "linkify": True}).enable("table")
    _TRAJ_DELIM = "<!-- COCO_TRAJECTORY -->"

    def _md_filter(text: str) -> str:
        """Jinja2 filter: render markdown to HTML, split off trajectory."""
        if not text:
            return ""
        # Split answer from trajectory if present
        answer = text
        trajectory_html = ""
        if _TRAJ_DELIM in text:
            answer, traj_text = text.split(_TRAJ_DELIM, 1)
            from coco.app.routes.sse import _render_trajectory_html

            trajectory_html = _render_trajectory_html(traj_text.strip())
        return _md.render(answer.strip()) + trajectory_html

    jinja_env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    jinja_env.filters["markdown"] = _md_filter
    pages.set_template_env(jinja_env)

    # Startup hook — fail-soft on Lakebase so the container boots even
    # when the app service principal can't reach the database. Routes
    # that need sessions will 503 on first use rather than preventing
    # the whole app from starting. This is how we avoid the chicken-
    # and-egg between app deploy and Lakebase credential provisioning.
    @app.on_event("startup")
    async def startup():
        """Initialize Lakebase connection pool (best-effort)."""
        logger.info("Starting CoCo app...")
        app.state.app_title = config.app.title
        app.state.db = None
        app.state.lakebase_error = None

        try:
            db = LakebaseClient.for_service()
            await db.connect()
            # Skip the wrapping health() call — it swallows the real
            # exception. Do the probe inline so any connection error
            # propagates into app.state.lakebase_error with a trace.
            async with db.pool.connection() as _conn:  # type: ignore[union-attr]
                await _conn.execute("SELECT 1")
            await db.ensure_schema()
            app.state.db = db
            logger.info("CoCo app started successfully with Lakebase")
        except Exception as e:
            import traceback as _tb

            app.state.lakebase_error = f"{e.__class__.__name__}: {e}\n{_tb.format_exc()[-2000:]}"
            logger.warning(
                "Lakebase unavailable at startup (%s). App will boot in "
                "degraded mode; session-dependent routes will 503 until "
                "Lakebase is reachable.",
                e,
            )

    # Shutdown hook
    @app.on_event("shutdown")
    async def shutdown():
        """Close Lakebase connection pool."""
        logger.info("Shutting down CoCo app...")

        try:
            if hasattr(app.state, "db"):
                await app.state.db.close()
            logger.info("CoCo app shut down successfully")
        except Exception as e:
            logger.error(f"Shutdown error: {e}")

    # Exception handler for 404s
    @app.exception_handler(404)
    async def not_found(request, exc):
        """Return 404 for missing routes."""

        return JSONResponse(status_code=404, content={"error": "Not found"})

    # Include routers
    app.include_router(pages.router)
    app.include_router(api.router)
    app.include_router(sse.router)

    logger.info("FastAPI app created")
    return app


# Create app instance for uvicorn to discover
app = create_app()


if __name__ == "__main__":
    # For local development
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("coco.app.main:app", host="0.0.0.0", port=port, reload=True, log_level="debug")
