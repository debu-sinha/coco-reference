"""MLflow observability and tracing for CoCo agent.

Provides tracing initialization, custom scorers, prompt registry,
and feedback logging. All integrated with Databricks MLflow 3.
"""
from __future__ import annotations

from coco.observability.feedback import log_feedback
from coco.observability.prompts import load_prompt, register_prompt
from coco.observability.tracing import (
    initialize_tracing,
    trace_tool_call,
)

__all__ = [
    "initialize_tracing",
    "trace_tool_call",
    "register_prompt",
    "load_prompt",
    "log_feedback",
]
