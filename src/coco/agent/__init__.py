"""CoCo agent package.

Healthcare cohort-building AI agent built on Databricks ML.

CocoAgent is deliberately NOT re-exported at package level. Pulling it
in here forces ``coco.agent.responses_agent`` to load on every
``from coco.agent.* import ...``, which in turn imports
``mlflow.dspy``. That submodule does not exist on every runtime's
preloaded mlflow, and trying to flush+reimport mlflow triggers the
protobuf descriptor-pool duplicate-file error. Notebooks that only
need signatures, prompts, or models should not pay for the agent
runtime's import cost. Import CocoAgent directly from its module:

    from coco.agent.responses_agent import CocoAgent
"""

from __future__ import annotations

__version__ = "2.0.0"
__author__ = "Databricks"

from coco.agent.models import (
    AgentState,
    ChatRequest,
    ChatResponse,
    CohortResult,
    Message,
    MessageRole,
    ToolCall,
    ToolCallType,
    ToolResult,
)

__all__ = [
    "ChatRequest",
    "ChatResponse",
    "Message",
    "MessageRole",
    "ToolCall",
    "ToolCallType",
    "ToolResult",
    "AgentState",
    "CohortResult",
]
