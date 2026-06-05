"""Request-scoped user context for cost attribution.

The agent entry point (`responses_agent.predict_stream`) extracts user_id
and thread_id from the system-message meta header the App prepends, then
sets these ContextVars. Downstream tools (SQL executor, knowledge RAG,
DSPy LM) read them to tag their requests so `system.billing.usage` and
`system.query.history` can be joined back to a user.

ContextVars are preferred over module globals because dspy.ReAct can run
tool functions on the same thread sequentially, and asyncio tasks inherit
the active context. No thread-affinity gymnastics required.
"""

from __future__ import annotations

import contextvars

current_user_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "coco_user_id", default="unknown"
)
current_thread_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "coco_thread_id", default="unknown"
)
# User's OBO access token forwarded from the Databricks App via
# x-forwarded-access-token. Empty when the request did not carry one
# (e.g., direct invokes from a notebook or SDK). Tools that need
# to call SQL warehouse / UC APIs as the requesting user check this
# first and fall back to the platform System SP only when it is empty.
current_user_token: contextvars.ContextVar[str] = contextvars.ContextVar(
    "coco_user_token", default=""
)


def set_user_context(user_id: str, thread_id: str, user_token: str = "") -> None:
    """Set the request-scoped context vars. Safe to call repeatedly."""
    current_user_id.set(user_id or "unknown")
    current_thread_id.set(thread_id or "unknown")
    current_user_token.set(user_token or "")


def get_user_context() -> tuple[str, str]:
    """Return (user_id, thread_id) from the current request context."""
    return current_user_id.get(), current_thread_id.get()


def get_user_token() -> str:
    """Return the forwarded OBO access token, empty string if none."""
    return current_user_token.get()
