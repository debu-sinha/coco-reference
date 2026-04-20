"""JSON API routes.

Thread/message CRUD, feedback, archival.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from pydantic import BaseModel

from coco.app.auth import UserIdentity, extract_user_identity
from coco.app.sessions.feedback import set_feedback
from coco.app.sessions.messages import add_message, get_messages
from coco.app.sessions.threads import (
    archive_thread,
    create_thread,
    get_thread,
    list_threads,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


class CreateThreadRequest(BaseModel):
    """Request to create a new thread."""

    title: Optional[str] = None


class CreateThreadResponse(BaseModel):
    """Response from thread creation."""

    id: str
    user_id: str
    title: Optional[str]
    created_at: str


class ListThreadsResponse(BaseModel):
    """Response from thread listing."""

    threads: list[dict]


class AddMessageRequest(BaseModel):
    """Request to add a user message."""

    content: str


class AddMessageResponse(BaseModel):
    """Response from message addition."""

    message_id: str
    created_at: str


class AddFeedbackRequest(BaseModel):
    """Request to set a feedback rating.

    rating = 1 thumbs-up, -1 thumbs-down, 0 clears an existing rating.
    """

    rating: int
    comment: Optional[str] = None


@router.post("/threads", response_model=CreateThreadResponse)
async def create_thread_endpoint(
    req: CreateThreadRequest, request: Request, user: UserIdentity = Depends(extract_user_identity)
) -> CreateThreadResponse:
    """Create new thread.

    Args:
        req: CreateThreadRequest
        request: FastAPI request (contains db client)
        user: Extracted user identity

    Returns:
        CreateThreadResponse
    """
    db = request.app.state.db
    thread = await create_thread(db, user.user_id, req.title)

    return CreateThreadResponse(
        id=str(thread.id),
        user_id=thread.user_id,
        title=thread.title,
        created_at=thread.created_at.isoformat(),
    )


@router.get("/threads", response_model=ListThreadsResponse)
async def list_threads_endpoint(
    request: Request, user: UserIdentity = Depends(extract_user_identity), limit: int = 50
) -> ListThreadsResponse:
    """List threads for current user.

    Args:
        request: FastAPI request
        user: Extracted user identity
        limit: Maximum threads to return

    Returns:
        ListThreadsResponse
    """
    db = request.app.state.db
    threads = await list_threads(db, user.user_id, limit=limit)

    return ListThreadsResponse(
        threads=[
            {
                "id": str(t.id),
                "user_id": t.user_id,
                "title": t.title or f"Thread {str(t.id)[:8]}",
                "created_at": t.created_at.isoformat(),
                "updated_at": t.updated_at.isoformat(),
            }
            for t in threads
        ]
    )


@router.post("/threads/{thread_id}/messages", response_model=AddMessageResponse)
async def add_message_endpoint(
    thread_id: UUID,
    req: AddMessageRequest,
    request: Request,
    user: UserIdentity = Depends(extract_user_identity),
) -> AddMessageResponse:
    """Add user message to thread.

    This endpoint does NOT stream the agent response.
    The agent should be called via SSE endpoint in separate request.

    Args:
        thread_id: Thread ID
        req: AddMessageRequest
        request: FastAPI request
        user: Extracted user identity

    Returns:
        AddMessageResponse

    Raises:
        HTTPException(404) if thread not found or not owned by user
    """
    db = request.app.state.db

    # Verify ownership
    thread = await get_thread(db, thread_id, user.user_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Add user message
    message = await add_message(db, thread_id, "user", req.content)

    return AddMessageResponse(message_id=str(message.id), created_at=message.created_at.isoformat())


@router.get("/threads/{thread_id}/messages")
async def get_messages_endpoint(
    thread_id: UUID,
    request: Request,
    user: UserIdentity = Depends(extract_user_identity),
    limit: int = 100,
) -> dict:
    """Load message history for thread.

    Args:
        thread_id: Thread ID
        request: FastAPI request
        user: Extracted user identity
        limit: Maximum messages to return

    Returns:
        Dict with messages list

    Raises:
        HTTPException(404) if thread not found or not owned by user
    """
    db = request.app.state.db

    # Verify ownership
    thread = await get_thread(db, thread_id, user.user_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Load messages
    messages = await get_messages(db, thread_id, limit=limit)

    return {
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "tool_calls": m.tool_calls,
                "trace_id": m.trace_id,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]
    }


@router.post("/messages/{message_id}/feedback")
async def add_feedback_endpoint(
    message_id: UUID,
    request: Request,
    rating: int = Form(...),
    comment: Optional[str] = Form(None),
    user: UserIdentity = Depends(extract_user_identity),
):
    """Set the user's rating for a message.

    Body is `application/x-www-form-urlencoded` because HTMX's hx-vals
    sends form-encoded by default (the htmx-ext-json-enc extension isn't
    loaded in base.html, so the previous JSON-body Pydantic model
    produced 422 Unprocessable Content on every click). Accepting form
    data directly avoids loading another vendor script.

    rating = 1 thumbs-up, -1 thumbs-down, 0 clears the rating. Returns
    an HTML fragment re-rendering the .message-actions block so the
    buttons stay in place with the correct filled/unfilled state.
    """
    db = request.app.state.db
    try:
        effective = await set_feedback(db, message_id, user.user_id, rating, comment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    from coco.app.routes.pages import get_template_env

    env = get_template_env()
    template = env.get_template("_feedback_buttons.html")
    html = template.render(msg_id=str(message_id), rating=effective)
    from fastapi.responses import HTMLResponse

    return HTMLResponse(html)


@router.delete("/threads/{thread_id}")
async def delete_thread_endpoint(
    thread_id: UUID,
    request: Request,
    user: UserIdentity = Depends(extract_user_identity),
) -> dict:
    """Archive thread (soft delete) — JSON API path."""
    db = request.app.state.db

    try:
        await archive_thread(db, thread_id, user.user_id)
        return {"status": "archived"}
    except ValueError:
        raise HTTPException(status_code=404, detail="Thread not found")


@router.post("/threads/{thread_id}/archive")
async def archive_thread_post(
    thread_id: UUID,
    request: Request,
    user: UserIdentity = Depends(extract_user_identity),
):
    """Archive thread via POST (for HTML form submissions).

    HTML forms can only send GET and POST, not DELETE. The thread
    page's Archive button is a plain <form method=post> that lands
    here. After archiving, redirect to the index page.
    """
    from fastapi.responses import RedirectResponse

    db = request.app.state.db
    try:
        await archive_thread(db, thread_id, user.user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Thread not found")
    return RedirectResponse(url="/", status_code=303)
