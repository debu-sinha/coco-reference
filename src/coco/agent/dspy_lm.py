"""DSPy language model configuration for coco tools.

The clinical code identifier and SQL generator are DSPy modules that
need `dspy.configure(lm=...)` to have been called before any inference.
This helper lazily configures DSPy once per process against the same
Claude Sonnet Model Serving endpoint the rest of the agent uses.
"""

from __future__ import annotations

import logging
import os

import dspy

from coco.config import get_config

logger = logging.getLogger(__name__)

_CONFIGURED = False


def ensure_dspy_configured() -> None:
    """Configure DSPy with a Databricks-backed LM if it hasn't been yet.

    Safe to call on every tool invocation — the work happens once per
    process. Uses LiteLLM's databricks provider under the hood, which
    DSPy picks up via `databricks/<endpoint_name>` model strings.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    config = get_config()
    endpoint = config.llm.gateway_route or config.llm.endpoint

    # Resolve a workspace host for LiteLLM. In Databricks runtimes
    # DATABRICKS_HOST is injected automatically; locally it must be set.
    workspace_host = (config.workspace.host or os.environ.get("DATABRICKS_HOST", "")).rstrip("/")
    if workspace_host and not workspace_host.startswith("http"):
        workspace_host = f"https://{workspace_host}"
    if workspace_host:
        os.environ.setdefault("DATABRICKS_HOST", workspace_host)

    lm = dspy.LM(
        f"databricks/{endpoint}",
        temperature=config.llm.temperature,
        max_tokens=config.llm.max_tokens,
    )
    dspy.configure(lm=lm)
    _CONFIGURED = True
    logger.info("DSPy configured with LM databricks/%s", endpoint)
