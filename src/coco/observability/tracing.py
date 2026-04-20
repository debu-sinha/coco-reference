"""MLflow tracing and observability initialization.

Sets up experiment, autolog for dspy and OpenAI, and provides
context manager for tracing tool calls.
"""
from __future__ import annotations

import contextlib
import logging
from typing import Any, Optional

import mlflow
from databricks.sdk import WorkspaceClient

from coco.config import get_config

logger = logging.getLogger(__name__)


def initialize_tracing(experiment_name: str | None = None) -> None:
    """Initialize MLflow tracing and autologging.

    Sets tracking URI to Databricks workspace, creates or reuses
    experiment, and enables autolog for dspy and OpenAI calls.

    Args:
        experiment_name: MLflow experiment path. If None, reads from
                        config.mlflow.experiment_name

    Raises:
        ValueError: If Databricks workspace not configured
    """
    config = get_config()

    exp_name = experiment_name or config.mlflow.experiment_name
    if not exp_name:
        raise ValueError(
            "experiment_name required; set mlflow.experiment_name"
            " in config"
        )

    # Connect to Databricks MLflow
    workspace_host = config.workspace.host
    if not workspace_host:
        raise ValueError(
            "workspace.host required; set DATABRICKS_HOST"
        )

    mlflow_uri = f"databricks://{workspace_host}"
    mlflow.set_tracking_uri(mlflow_uri)

    # Set or create experiment
    try:
        experiment = mlflow.get_experiment_by_name(exp_name)
        if experiment:
            mlflow.set_experiment(exp_name)
            logger.info(
                "Using MLflow experiment: %s (id=%s)",
                exp_name,
                experiment.experiment_id,
            )
        else:
            experiment = mlflow.create_experiment(exp_name)
            mlflow.set_experiment(exp_name)
            logger.info(
                "Created MLflow experiment: %s (id=%s)",
                exp_name,
                experiment,
            )
    except Exception as e:
        logger.warning(
            "Failed to set experiment %s: %s", exp_name, e
        )

    # Enable autolog for dspy and OpenAI
    try:
        mlflow.dspy.autolog()
        logger.info("Enabled MLflow dspy autolog")
    except Exception as e:
        logger.warning("Failed to enable dspy autolog: %s", e)

    try:
        mlflow.openai.autolog()
        logger.info("Enabled MLflow OpenAI autolog")
    except Exception as e:
        logger.warning("Failed to enable OpenAI autolog: %s", e)


@contextlib.contextmanager
def trace_tool_call(
    tool_name: str,
    inputs: dict[str, Any],
):
    """Context manager for tracing tool invocations.

    Records tool inputs, outputs, and any errors to the active
    MLflow trace. Automatically captures execution time.

    Args:
        tool_name: Name of the tool being invoked
        inputs: Input dict (logged as span inputs)

    Yields:
        None (use for context manager block)

    Example:
        with trace_tool_call("sql_executor", {"sql": "SELECT ..."}):
            # Execute tool
            result = await executor.run(sql)
    """
    with mlflow.start_span(
        name=tool_name,
        attributes={
            "tool": tool_name,
            "input_keys": list(inputs.keys()),
        },
    ) as span:
        mlflow.log_dict(
            inputs,
            artifact_path=f"inputs",
        )
        try:
            yield
        except Exception as e:
            span.set_attribute("error", str(e))
            mlflow.log_param("error", str(e))
            raise


def emit_feedback_to_trace(
    trace_id: str,
    rating: int,
    comment: str | None = None,
) -> None:
    """Emit user feedback to current MLflow trace.

    Records rating (1 or -1) and optional comment as trace metadata.

    Args:
        trace_id: MLflow trace ID
        rating: 1 (thumbs up) or -1 (thumbs down)
        comment: Optional user comment

    Raises:
        ValueError: If rating not in {-1, 1}
    """
    if rating not in (-1, 1):
        raise ValueError("rating must be 1 or -1")

    params = {
        "feedback_rating": str(rating),
    }
    if comment:
        params["feedback_comment"] = comment

    try:
        mlflow.log_params(params)
        logger.debug(
            "Emitted feedback to trace %s; rating=%d",
            trace_id,
            rating,
        )
    except Exception as e:
        logger.warning(
            "Failed to emit feedback to trace: %s", e
        )
