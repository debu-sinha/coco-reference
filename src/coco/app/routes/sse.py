"""Server-Sent Events (SSE) streaming endpoint.

One SSE connection per user message. The flow:

    1. User hits Send.
    2. POST /threads/{id}/send (see pages.py) saves the user message
       and returns an HTML fragment containing:
         - the user's message bubble
         - an empty assistant bubble whose inner content element opens
           an SSE connection to this route.
    3. This route calls the agent endpoint non-streaming, persists the
       full assistant reply to Lakebase, renders the reply markdown to
       HTML, and emits ONE SSE `message` frame containing the full
       rendered HTML. HTMX appends that frame into the assistant bubble
       in a single swap, so we get correct markdown rendering without
       worrying about chunking partial HTML across frame boundaries.
    4. Finally emits a `close` event so the HTMX SSE extension tears
       the connection down instead of auto-reconnecting.

The visible "loading" state while the agent runs is handled by CSS
(`.message-content:empty::before`), so we don't need to pre-emit a
"Thinking..." marker and later try to clear it. The agent call
itself is the bottleneck (~10-60s), and the browser shows the empty
placeholder with a CSS animation during that time.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
from typing import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from markdown_it import MarkdownIt

from coco.app.agent_client import AgentClient
from coco.app.auth import UserIdentity, extract_user_identity
from coco.app.sessions.lakebase import LakebaseClient
from coco.app.sessions.messages import Message, add_message, get_messages  # noqa: F401
from coco.app.sessions.threads import get_thread
from coco.config import get_config

logger = logging.getLogger(__name__)

router = APIRouter()

# Shared markdown renderer. `commonmark` is the safe default profile;
# `table` enables GitHub-style tables which cohort queries frequently
# return ("patient_id | age | condition").
_md = MarkdownIt("commonmark", {"html": False, "linkify": True}).enable("table")


# Per-thread asyncio lock registry. Prevents the race where two
# concurrent /stream connections both read the thread before either
# persists the assistant reply, slip past the "last message is
# assistant" guard, and trigger two agent invocations for the same
# user turn. One replica only; if the App ever scales to multiple
# replicas, replace with a Postgres advisory lock or a UNIQUE
# constraint on runs(thread_id, message_id).
_thread_locks: dict[str, asyncio.Lock] = {}
_thread_locks_gate = asyncio.Lock()


async def _get_thread_lock(thread_id: str) -> asyncio.Lock:
    """Return (creating if missing) the asyncio.Lock for one thread."""
    async with _thread_locks_gate:
        lock = _thread_locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            _thread_locks[thread_id] = lock
        return lock


def _sse(event: str, data: str) -> str:
    """Format an SSE frame.

    SSE has an oddity: a literal `\\n` inside `data:` terminates the
    field. Multi-line data requires repeating `data:` on every line
    or squashing newlines to spaces. Since we ship one atomic frame
    per reply (not chunked text), the content IS a multi-line HTML
    string, so we emit each line of the payload as its own `data:`
    line per the SSE spec. The client re-joins them with `\\n`.
    """
    # Strip stray \r and split on \n; re-emit each line as `data: <line>`.
    lines = data.replace("\r", "").split("\n")
    body = "\n".join(f"data: {line}" for line in lines)
    return f"event: {event}\n{body}\n\n"


def _render_trajectory_html(trajectory_text: str) -> str:
    """Convert the plaintext trajectory block into a collapsible HTML panel.

    The trajectory text looks like:
        STEP 1: inspect_schema
          Thought: ...
          Result: ...
        STEP 2: execute_sql(SELECT ...)
          Thought: ...
          Result: ...

    We render it as an HTML <details> element that the user can click
    to expand. The <details> element is natively collapsible in every
    browser without JavaScript.
    """
    lines = trajectory_text.strip().split("\n")
    step_count = sum(1 for ln in lines if ln.startswith("STEP "))

    items = []
    current_step = []
    for line in lines:
        if line.startswith("STEP ") and current_step:
            items.append(_format_step_html(current_step))
            current_step = []
        current_step.append(line)
    if current_step:
        items.append(_format_step_html(current_step))

    if not items:
        return ""

    body = "\n".join(items)
    return (
        f'<details class="trajectory-panel">\n'
        f"<summary>Agent Reasoning ({step_count} steps)</summary>\n"
        f'<ol class="trajectory-steps">\n{body}\n</ol>\n'
        f"</details>\n"
    )


def _format_step_html(lines: list[str]) -> str:
    """Format a single trajectory step as an <li> element."""
    if not lines:
        return ""

    header = html.escape(lines[0])
    thought = ""
    result = ""
    for ln in lines[1:]:
        stripped = ln.strip()
        if stripped.startswith("Thought:"):
            thought = html.escape(stripped[8:].strip())
        elif stripped.startswith("Result:"):
            result = html.escape(stripped[7:].strip())

    parts = [f"<strong>{header}</strong>"]
    if thought:
        parts.append(f'<div class="trajectory-thought">{thought}</div>')
    if result:
        parts.append(f'<div class="trajectory-result">{result}</div>')

    return f"<li>{''.join(parts)}</li>"


def _render_feedback_buttons_html(msg_id: str) -> str:
    """Build the thumbs-up/down pill group for a freshly-persisted reply.

    Mirrors `_feedback_buttons.html` but is emitted inline via the SSE
    stream because the template layer isn't reachable from here, and
    the browser needs the buttons the moment the answer lands — not on
    the next page reload. HTMX picks up the `hx-*` attributes as soon
    as the swap lands, so the buttons are clickable immediately.
    """
    return (
        '<div class="message-actions">'
        f'<button class="btn-feedback btn-feedback-up" type="button" '
        f'aria-label="Helpful" aria-pressed="false" '
        f'hx-post="/api/messages/{msg_id}/feedback" '
        f'hx-vals=\'{{"rating": 1}}\' hx-swap="outerHTML" '
        f'hx-target="closest .message-actions">'
        '<svg class="icon" width="18" height="18" viewBox="0 0 24 24" '
        'aria-hidden="true" focusable="false">'
        '<path fill="currentColor" d="M14 9V5a3 3 0 0 0-3-3l-1 1v5H5.5A2.5 '
        "2.5 0 0 0 3 10.5v7A2.5 2.5 0 0 0 5.5 20h12.16a2 2 0 0 0 1.97-1.66l1.2-7"
        'A2 2 0 0 0 18.86 9H14Z"/></svg>'
        '<span class="btn-label">Helpful</span></button>'
        f'<button class="btn-feedback btn-feedback-down" type="button" '
        f'aria-label="Not helpful" aria-pressed="false" '
        f'hx-post="/api/messages/{msg_id}/feedback" '
        f'hx-vals=\'{{"rating": -1}}\' hx-swap="outerHTML" '
        f'hx-target="closest .message-actions">'
        '<svg class="icon" width="18" height="18" viewBox="0 0 24 24" '
        'aria-hidden="true" focusable="false">'
        '<path fill="currentColor" d="M10 15v4a3 3 0 0 0 3 3l1-1v-5h4.5A2.5 '
        "2.5 0 0 0 21 13.5v-7A2.5 2.5 0 0 0 18.5 4H6.34a2 2 0 0 0-1.97 1.66l-1.2 7"
        'A2 2 0 0 0 5.14 15H10Z"/></svg>'
        '<span class="btn-label">Not helpful</span></button>'
        "</div>"
    )


def _render_markdown(text: str) -> str:
    """Render the agent reply from markdown to sanitized HTML.

    `html=False` is critical: it disables raw HTML pass-through in
    the source, so even if the agent tries to emit a `<script>` tag
    in its reply the renderer treats it as literal text. Combined
    with `html.escape` of any stray bracket in the fallback error
    path, this is enough to stop XSS for internal-use demos.
    """
    return _md.render(text or "")


async def _agent_sse_stream(
    thread_id: UUID,
    user_id: str,
    db: LakebaseClient,
    agent_client: AgentClient,
) -> AsyncGenerator[str, None]:
    """Generate the SSE event stream for one assistant turn.

    Yields exactly two SSE frames on the happy path:
      - `event: message` with the rendered HTML of the full reply
      - `event: close` so HTMX drops the connection

    On error, yields a message frame with an escaped error string
    and then a close.
    """
    # Ownership check
    thread = await get_thread(db, thread_id, user_id)
    if thread is None:
        yield _sse("message", "<em>Thread not found.</em>")
        yield _sse("close", "")
        return

    # Concurrency guard. If another /stream connection for this thread
    # is already invoking the agent (e.g., HTMX's SSE extension
    # reconnected mid-invoke, or the browser re-opened the stream),
    # the Lakebase reconnect-loop guard alone is not enough: it reads
    # the persisted state, which does not update until the first
    # invocation finishes 20-40 seconds later. Without this check both
    # connections slip past the guard and produce two agent calls +
    # two assistant rows for the same user turn.
    lock = await _get_thread_lock(str(thread_id))
    if lock.locked():
        logger.info(
            "Concurrent /stream for thread %s; another invocation in progress, emitting close.",
            thread_id,
        )
        yield _sse("close", "")
        return

    async with lock:
        async for frame in _invoke_one_turn(thread_id, user_id, db, agent_client):
            yield frame


async def _invoke_one_turn(
    thread_id: UUID,
    user_id: str,
    db: LakebaseClient,
    agent_client: AgentClient,
) -> AsyncGenerator[str, None]:
    """Body of one assistant turn, guaranteed serialized per thread."""
    # Pull history in OpenAI shape for the agent call
    try:
        messages_rows = await get_messages(db, thread_id, limit=100)
    except Exception as e:
        logger.exception("get_messages failed: %s", e)
        yield _sse(
            "message",
            f"<p class='error'>Could not load thread history: {html.escape(str(e))}</p>",
        )
        yield _sse("close", "")
        return

    history = [{"role": row.role, "content": row.content} for row in messages_rows if row.content]

    # Prepend a system message with user_id + thread_id so the agent
    # can set them as MLflow trace tags. This makes every trace
    # attributable to a specific user and conversation thread,
    # which is essential for per-user cost tracking and audit.
    history.insert(
        0,
        {
            "role": "system",
            "content": f"[coco_meta: user_id={user_id}, thread_id={thread_id}]",
        },
    )

    if not history:
        yield _sse("message", "<em>No user message to respond to.</em>")
        yield _sse("close", "")
        return

    # Reconnect-loop guard. HTMX's SSE extension auto-reconnects when
    # an EventSource closes, and a buggy/old client that ignores our
    # `sse-close="close"` attribute will hit /stream again, again,
    # and again. Without this guard we would cheerfully generate a
    # new agent reply on every reconnect, blow up the thread with
    # dozens of duplicate "Welcome" messages, and poison the
    # conversation context. So: if the most recent message in the
    # thread is already an assistant message, there is no pending
    # user turn to respond to. Emit a close frame and return.
    last = messages_rows[-1] if messages_rows else None
    if last is not None and (last.role or "").lower() == "assistant":
        logger.info(
            "Reconnect-loop guard: last message in thread %s is already "
            "an assistant message, refusing to invoke agent again",
            thread_id,
        )
        yield _sse("close", "")
        return

    # Call the agent AND persist the reply as one coroutine, then wrap
    # the whole thing in asyncio.shield so that if the browser closes
    # the SSE connection mid-call (tab close, navigation, reload) the
    # inner work still completes and the reply still lands in Lakebase.
    # Without this, a mid-query navigation left an orphan user message
    # with no assistant turn — confusing on reload and breaks any
    # "try again" follow-up because there's no prior assistant context.
    async def _invoke_and_persist() -> tuple[Message | None, str, str | None]:
        try:
            reply = await agent_client.invoke(history)
            err: str | None = None
        except asyncio.CancelledError:
            # The invoke call itself was torn down (app shutdown, agent
            # endpoint closed the connection). Persist a marker instead
            # of an orphan user turn.
            reply = "_(query cancelled before the agent could respond)_"
            err = "cancelled"
        except Exception as invoke_err:  # noqa: BLE001
            logger.exception("Agent invoke failed: %s", invoke_err)
            reply = f"_(agent error: {type(invoke_err).__name__})_"
            err = str(invoke_err)[:400]
        try:
            saved = await add_message(db, thread_id, "assistant", reply)
        except Exception as save_err:  # noqa: BLE001
            logger.error("Failed to persist assistant message: %s", save_err)
            saved = None
        return saved, reply, err

    work = asyncio.ensure_future(_invoke_and_persist())
    try:
        assistant_msg, reply_text, agent_err = await asyncio.shield(work)
    except asyncio.CancelledError:
        # Browser navigated away. The shielded task keeps running and
        # will persist the reply on its own. Let Starlette tear down.
        logger.info(
            "SSE stream cancelled for thread %s; background save continues",
            thread_id,
        )
        raise

    if agent_err:
        yield _sse(
            "message",
            f"<p class='error'>Agent call failed: {html.escape(agent_err)}</p>",
        )
        yield _sse("close", "")
        return

    # Split the reply into answer + trajectory (if the agent embedded
    # a trajectory block). Render the answer as markdown, then append
    # the trajectory as a collapsible <details> HTML block.
    _TRAJ_DELIM = "<!-- COCO_TRAJECTORY -->"
    answer_text = reply_text
    trajectory_text = ""
    if _TRAJ_DELIM in reply_text:
        answer_text, trajectory_text = reply_text.split(_TRAJ_DELIM, 1)

    rendered = _render_markdown(answer_text.strip())

    if trajectory_text.strip():
        rendered += _render_trajectory_html(trajectory_text.strip())

    if assistant_msg is not None:
        rendered += _render_feedback_buttons_html(str(assistant_msg.id))

    yield _sse("message", rendered)
    yield _sse("close", "")


@router.get("/threads/{thread_id}/stream")
async def stream_endpoint(
    thread_id: UUID,
    request: Request,
    user: UserIdentity = Depends(extract_user_identity),
) -> StreamingResponse:
    """SSE endpoint - one connection per assistant turn."""
    db = request.app.state.db
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Session store unavailable - Lakebase is not initialized.",
        )

    config = get_config()
    endpoint_name = config.app.agent_endpoint_url
    if not endpoint_name:
        raise HTTPException(
            status_code=503,
            detail=(
                "Agent endpoint not configured. "
                "COCO_AGENT_ENDPOINT_URL is not set - check the app's "
                "Resources tab for the serving endpoint binding."
            ),
        )

    agent_client = AgentClient(
        endpoint_name=endpoint_name,
        timeout=config.app.polling_fallback_after_seconds or 120.0,
    )

    return StreamingResponse(
        _agent_sse_stream(thread_id, user.user_id, db, agent_client),
        media_type="text/event-stream",
        headers={
            # Disable proxy buffering so the frame actually reaches the
            # browser in real time. Databricks Apps passes these
            # through to its edge; without them the response is
            # buffered until the generator finishes.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# Unused suppressor - `json` is kept for future use when we switch to
# agent-side streaming. Prevents the ruff/formatter from stripping it
# and creating churn on the next edit.
_ = json
