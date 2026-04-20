"""HTML page routes (server-rendered HTMX).

Renders Jinja2 templates with thread/message data.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment

from coco.app.auth import UserIdentity, extract_user_identity
from coco.app.sessions.lakebase import LakebaseClient
from coco.app.sessions.messages import add_message, get_messages
from coco.app.sessions.threads import (  # noqa: F401
    create_thread,
    delete_thread_permanently,
    get_thread,
    list_archived_threads,
    list_threads,
    restore_thread,
    update_thread_title,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Template environment (will be initialized by main.py)
_template_env: Environment | None = None


def set_template_env(env: Environment) -> None:
    """Set the global template environment."""
    global _template_env
    _template_env = env


def get_template_env() -> Environment:
    """Get the template environment."""
    if _template_env is None:
        raise RuntimeError("Template environment not initialized")
    return _template_env


@router.get("/debug/env")
async def debug_env(request: Request) -> dict:
    """Expose which env vars the container sees (keys only, no values)
    so we can tell whether the Apps runtime injected the PG* block.

    Returns ONLY the names of env vars relevant to this debug, plus a
    flag for whether app.state.db is set. No secrets leak.
    """
    import os as _os

    interesting_prefixes = ("PG", "DATABRICKS_", "COCO_")
    visible = sorted(
        k for k in _os.environ if k.startswith(interesting_prefixes) or k in ("DATABASE_URL",)
    )
    return {
        "env_var_names": visible,
        "pg_vars_set": {
            v: bool(_os.environ.get(v))
            for v in (
                "PGHOST",
                "PGPORT",
                "PGUSER",
                "PGPASSWORD",
                "PGDATABASE",
                "PGSSLMODE",
                "PGAPPNAME",
            )
        },
        "app_state_db_is_set": getattr(request.app.state, "db", None) is not None,
        "lakebase_error": getattr(request.app.state, "lakebase_error", None),
        "agent_endpoint_url": _os.environ.get("COCO_AGENT_ENDPOINT_URL"),
        "databricks_host": _os.environ.get("DATABRICKS_HOST"),
    }


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    user: UserIdentity = Depends(extract_user_identity),
    client: LakebaseClient = Depends(lambda: None),
) -> str:
    """Render thread list page.

    Args:
        request: FastAPI request
        user: Extracted user identity
        client: Lakebase client (injected by app startup)

    Returns:
        Rendered HTML
    """
    # Use the startup-initialized Lakebase pool (app.state.db). The
    # pool reads PG* env vars injected by the Apps database resource
    # binding — no per-request auth work needed. If the binding isn't
    # set up at deploy time, db will be None and we render in degraded
    # mode with a banner.
    db: LakebaseClient | None = request.app.state.db
    lakebase_status = "ok"
    threads: list = []
    feedback_up = 0
    feedback_down = 0
    if db is None:
        lakebase_status = "session store unavailable"
    else:
        try:
            threads = await list_threads(db, user.user_id, limit=50)
        except Exception as e:
            logger.exception("list_threads failed: %s", e)
            lakebase_status = f"{e.__class__.__name__}: {e}"[:240]
        try:
            row = await db.execute_one(
                "SELECT "
                "COALESCE(SUM(CASE WHEN rating > 0 THEN 1 ELSE 0 END), 0), "
                "COALESCE(SUM(CASE WHEN rating < 0 THEN 1 ELSE 0 END), 0) "
                "FROM feedback WHERE user_id = %s AND created_at > NOW() - INTERVAL '7 days'",
                (user.user_id,),
            )
            if row:
                feedback_up = int(row[0])
                feedback_down = int(row[1])
        except Exception:
            pass

    env = get_template_env()
    template = env.get_template("index.html")

    return template.render(
        app_title=request.app.state.app_title,
        user_id=user.user_id,
        threads=threads,
        lakebase_status=lakebase_status,
        feedback_up=feedback_up,
        feedback_down=feedback_down,
    )


@router.post("/threads/new")
async def create_thread_and_redirect(
    request: Request,
    user: UserIdentity = Depends(extract_user_identity),
) -> RedirectResponse:
    """Create a thread (empty title) and redirect to its chat page.

    Uses the startup-initialized Lakebase pool (app.state.db) which
    connects via the PG* env vars injected by the database resource
    binding.
    """
    db: LakebaseClient | None = request.app.state.db
    if db is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Session store unavailable — the app's Lakebase resource "
                "binding isn't set up. Check the app's Resources tab."
            ),
        )
    try:
        thread = await create_thread(db, user.user_id, title=None)
    except Exception as e:
        logger.exception("create_thread failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail=f"Could not create thread — {e.__class__.__name__}: {e}"[:400],
        )
    return RedirectResponse(url=f"/threads/{thread.id}", status_code=303)


@router.get("/threads/{thread_id}", response_class=HTMLResponse)
async def thread_page(
    thread_id: UUID, request: Request, user: UserIdentity = Depends(extract_user_identity)
) -> str:
    """Render thread chat page.

    Args:
        thread_id: Thread ID
        request: FastAPI request
        user: Extracted user identity

    Returns:
        Rendered HTML

    Raises:
        HTTPException(404) if thread not found or not owned by user
    """
    db = request.app.state.db

    # Verify ownership
    thread = await get_thread(db, thread_id, user.user_id)
    if thread is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Thread not found")

    # Load messages + each message's feedback rating for this user so
    # the thumbs render in the correct state after a reload.
    messages = await get_messages(db, thread_id, limit=100, user_id=user.user_id)

    env = get_template_env()
    template = env.get_template("thread.html")

    return template.render(
        app_title=request.app.state.app_title,
        user_id=user.user_id,
        thread=thread,
        messages=messages,
    )


@router.post("/threads/{thread_id}/send", response_class=HTMLResponse)
async def send_message(
    thread_id: UUID,
    request: Request,
    content: str = Form(...),
    user: UserIdentity = Depends(extract_user_identity),
) -> str:
    """Handle a form submission from the thread compose box.

    Saves the user's message to Lakebase and returns an HTML fragment
    with two bubbles:
      - the user's message, fully rendered
      - an empty assistant placeholder whose inner element opens an
        SSE connection to /threads/{id}/stream so the agent reply
        streams in progressively.

    HTMX appends this fragment to #message-list via hx-swap="beforeend".
    """
    db: LakebaseClient | None = request.app.state.db
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Session store unavailable — Lakebase is not initialized.",
        )

    # Ownership check so a guessed thread_id can't poison another
    # user's history.
    thread = await get_thread(db, thread_id, user.user_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    content = (content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Empty message")

    try:
        user_msg = await add_message(db, thread_id, "user", content)
    except Exception as e:
        logger.exception("add_message failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail=f"Could not save message: {e.__class__.__name__}: {e}"[:400],
        )

    # Auto-title: if the thread has no title yet, set it from the
    # first user message (truncated to 60 chars).
    if not thread.title:
        auto_title = content[:60].strip()
        if len(content) > 60:
            auto_title = auto_title.rsplit(" ", 1)[0] + "..."
        try:
            await update_thread_title(db, thread_id, user.user_id, auto_title)
        except Exception:
            pass

    env = get_template_env()
    template = env.get_template("_compose_response.html")
    return template.render(
        thread_id=thread_id,
        user_msg=user_msg,
    )


@router.get("/archived", response_class=HTMLResponse)
async def archived_threads_page(
    request: Request,
    user: UserIdentity = Depends(extract_user_identity),
) -> str:
    """Show archived threads with restore/delete options."""
    db: LakebaseClient | None = request.app.state.db
    threads: list = []
    if db is not None:
        try:
            threads = await list_archived_threads(db, user.user_id, limit=50)
        except Exception as e:
            logger.exception("list_archived_threads failed: %s", e)

    env = get_template_env()
    template = env.get_template("archived.html")
    return template.render(
        app_title=request.app.state.app_title,
        user_id=user.user_id,
        threads=threads,
    )


@router.post("/threads/{thread_id}/restore")
async def restore_thread_handler(
    thread_id: UUID,
    request: Request,
    user: UserIdentity = Depends(extract_user_identity),
):
    """Restore an archived thread and redirect to index."""
    db: LakebaseClient | None = request.app.state.db
    if db is None:
        raise HTTPException(status_code=503, detail="Session store unavailable.")
    try:
        await restore_thread(db, thread_id, user.user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Thread not found")
    return RedirectResponse(url="/", status_code=303)


@router.post("/threads/{thread_id}/delete")
async def delete_thread_handler(
    thread_id: UUID,
    request: Request,
    user: UserIdentity = Depends(extract_user_identity),
):
    """Permanently delete a thread and redirect to archived page."""
    db: LakebaseClient | None = request.app.state.db
    if db is None:
        raise HTTPException(status_code=503, detail="Session store unavailable.")
    try:
        await delete_thread_permanently(db, thread_id, user.user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Thread not found")
    return RedirectResponse(url="/archived", status_code=303)


@router.post("/threads/{thread_id}/rename")
async def rename_thread_handler(
    thread_id: UUID,
    request: Request,
    title: str = Form(...),
    user: UserIdentity = Depends(extract_user_identity),
):
    """Rename a thread. HTMX requests get 204 (no navigation, so any
    in-flight SSE stream stays alive); plain form POSTs keep the 303
    redirect for progressive-enhancement fallback."""
    db: LakebaseClient | None = request.app.state.db
    if db is None:
        raise HTTPException(status_code=503, detail="Session store unavailable.")
    try:
        await update_thread_title(db, thread_id, user.user_id, title.strip()[:100])
    except ValueError:
        raise HTTPException(status_code=404, detail="Thread not found")
    if request.headers.get("HX-Request") == "true":
        return Response(status_code=204)
    return RedirectResponse(url=f"/threads/{thread_id}", status_code=303)
