"""MLflow models-from-code entry point for the CoCo ResponsesAgent.

`mlflow.pyfunc.log_model` cannot cloudpickle `CocoResponsesAgent`
because the inner `CocoAgent` holds `httpx` async clients and other
non-picklable state. Models-from-code sidesteps pickling entirely:
MLflow copies this file into the model artifacts, and at load time it
runs the script and registers whatever instance was passed to
`mlflow.models.set_model(...)`.

Referenced by `coco.agent.deploy.deploy_agent()` via `python_model=<this
file>`. The coco package must also be on the model's `code_paths` so
this script's imports resolve at both save and load time.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Generator, Iterable
from uuid import uuid4

import mlflow  # noqa: F401 — used as mlflow.models.set_model(...) at bottom
import mlflow.models  # noqa: F401
from mlflow.pyfunc.model import ResponsesAgent
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
)

from coco.agent.models import Message, MessageRole
from coco.agent.responses_agent import CocoAgent

logger = logging.getLogger(__name__)


class CocoResponsesAgent(ResponsesAgent):
    """MLflow ResponsesAgent wrapper around the internal CocoAgent."""

    def load_context(self, context: Any) -> None:  # type: ignore[override]
        """Instantiate the inner agent once when the container starts.

        The Model Serving container has the coco package (via code_paths)
        but not the config YAML on its normal search path. We ship the
        config as an artifact and point COCO_CONFIG_PATH at it before
        building the agent so `get_config()` resolves correctly.

        DATABRICKS_HOST is required by GatewayClient to build the
        invocations URL, but isn't always present in the serving
        container's env at load time. Resolve it from the workload
        identity's WorkspaceClient and stuff it into os.environ before
        instantiating CocoAgent.
        """
        artifacts = getattr(context, "artifacts", None) or {}
        config_path = artifacts.get("coco_config")
        if config_path:
            os.environ["COCO_CONFIG_PATH"] = config_path

        if not os.environ.get("DATABRICKS_HOST"):
            try:
                from databricks.sdk import WorkspaceClient

                host = WorkspaceClient().config.host
                if host:
                    os.environ["DATABRICKS_HOST"] = host
            except Exception as e:
                logger.warning("Could not resolve DATABRICKS_HOST from SDK: %s", e)

        # Belt-and-suspenders: resolve COCO_WAREHOUSE_ID from the
        # model's MLmodel resources block if the config artifact's
        # ${COCO_WAREHOUSE_ID} template didn't resolve (which happens
        # when the artifact upload fails or the S3 object is lost).
        # The resources.databricks.sql_warehouse list always carries
        # the warehouse name (= id) that was declared at log_model
        # time, and it's embedded in the MLmodel YAML that lives
        # alongside the entry script — no S3 download needed.
        if not os.environ.get("COCO_WAREHOUSE_ID"):
            try:
                import yaml as _yaml

                mlmodel_path = os.path.join(os.path.dirname(__file__), "MLmodel")
                if os.path.exists(mlmodel_path):
                    with open(mlmodel_path) as _f:
                        mlmodel = _yaml.safe_load(_f)
                    resources = (mlmodel.get("resources") or {}).get("databricks") or {}
                    wh_list = resources.get("sql_warehouse") or []
                    if wh_list:
                        wh_id = wh_list[0].get("name", "")
                        if wh_id:
                            os.environ["COCO_WAREHOUSE_ID"] = wh_id
                            logger.info("Resolved COCO_WAREHOUSE_ID from MLmodel: %s", wh_id)
            except Exception as e:
                logger.warning("Could not resolve COCO_WAREHOUSE_ID from MLmodel: %s", e)

        self.agent = CocoAgent()

    def _to_coco_messages(self, inputs: Iterable[Any]) -> list[Message]:
        """Map MLflow request.input entries to coco Messages."""
        messages: list[Message] = []
        for entry in inputs:
            role = getattr(entry, "role", None)
            content = getattr(entry, "content", None)
            if role is None or content is None:
                continue
            if isinstance(content, list):
                content = "".join(
                    getattr(c, "text", "") or ""
                    for c in content
                    if getattr(c, "text", None) is not None
                )
            if not isinstance(content, str):
                continue
            try:
                role_enum = MessageRole(str(role))
            except ValueError:
                role_enum = MessageRole.USER
            messages.append(Message(role=role_enum, content=content))
        return messages

    @staticmethod
    def _extract_final_content(events: list[Any]) -> str:
        """Pull the final assistant text out of coco stream events."""
        for event in reversed(events):
            if getattr(event, "event_type", None) != "assistant":
                continue
            payload = getattr(event, "content", None)
            if isinstance(payload, dict):
                text = payload.get("content")
                if isinstance(text, str):
                    return text
            elif isinstance(payload, str):
                return payload
        return "(no response)"

    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        """Non-streaming prediction — collects the full response.

        Wrapped in try/except so MLflow's signature inference (which
        invokes this with the example input during log_model) always
        produces a valid response shape even if the underlying tool
        loop blows up. Legitimate runtime errors still surface via
        MLflow traces at serving time.
        """
        try:
            messages = self._to_coco_messages(request.input)
            events = list(self.agent.predict_stream(messages))
            text = self._extract_final_content(events)
        except Exception as e:
            logger.exception("CocoResponsesAgent.predict failed: %s", e)
            text = f"(error: {e.__class__.__name__}: {e})"
        item = self.create_text_output_item(
            text=text,
            id=f"msg_{uuid4().hex}",
        )
        return ResponsesAgentResponse(output=[item])  # type: ignore[arg-type]

    def predict_stream(
        self, request: ResponsesAgentRequest
    ) -> Generator[dict[str, Any], None, None]:
        """Streaming prediction — emits text deltas as the agent progresses."""
        item_id = f"msg_{uuid4().hex}"
        final_text = ""
        try:
            messages = self._to_coco_messages(request.input)
            for event in self.agent.predict_stream(messages):
                if getattr(event, "event_type", None) != "assistant":
                    continue
                payload = getattr(event, "content", None)
                if isinstance(payload, dict):
                    text = payload.get("content") or ""
                elif isinstance(payload, str):
                    text = payload
                else:
                    text = ""
                if text:
                    final_text = text
                    yield self.create_text_delta(delta=text, item_id=item_id)
        except Exception as e:
            logger.exception("CocoResponsesAgent.predict_stream failed: %s", e)
            final_text = f"(error: {e.__class__.__name__}: {e})"

        yield {
            "type": "response.output_item.done",
            "item": self.create_text_output_item(
                text=final_text or "(no response)",
                id=item_id,
            ),
        }


# Register the instance so MLflow picks it up at load time. This is the
# `models-from-code` contract: whatever you pass to set_model is the
# object exposed via `mlflow.pyfunc.load_model(...)`.
mlflow.models.set_model(CocoResponsesAgent())
