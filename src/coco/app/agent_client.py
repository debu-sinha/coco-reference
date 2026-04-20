"""Client for the Databricks Model Serving agent endpoint.

Calls the CoCo agent serving endpoint as the app's service principal
(NOT on behalf of the user). Databricks Apps `user_api_scopes` does
not include a scope that would let the app forward the user's OBO
token to a Model Serving endpoint, so the app SP is the only path
that works end-to-end. The SP gets CAN_QUERY on the endpoint via the
AppResourceServingEndpoint binding declared at app-create time.

We use WorkspaceClient.serving_endpoints.query() directly. The SDK
handles URL resolution, SP authentication (via the auto-injected
DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET / DATABRICKS_HOST env
vars), and response parsing. The endpoint is called non-streaming
and the SSE route in sse.py chunks the full response back to the
browser for a streaming UI feel.

The Apps AppResourceServingEndpoint resource binding sets the
injected env var (COCO_AGENT_ENDPOINT_URL) to the endpoint NAME, not
a URL, so this client takes a name.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)


class AgentClient:
    """Client to the CoCo agent serving endpoint.

    CoCo is deployed as a Mosaic AI `ResponsesAgent` (Responses API
    shape), not a ChatAgent (ChatCompletion shape). The SDK's
    `serving_endpoints.query(messages=[...])` builds a ChatCompletion
    payload and fails schema enforcement on a ResponsesAgent. So we
    POST directly to `/serving-endpoints/<name>/invocations` with the
    Responses API payload shape:

        {"input": [{"role": "user", "content": "..."}]}

    Auth and host resolution come from WorkspaceClient, which picks
    up the SP credentials that Databricks Apps injects into the
    container (DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET /
    DATABRICKS_HOST).
    """

    def __init__(self, endpoint_name: str, timeout: float = 300.0) -> None:
        # 300s default (up from 120s). Prior evaluation showed 44% of
        # scenarios timed out at the old 120s ceiling — p50 latency is
        # ~73s and complex cohort queries that need 5+ tools regularly
        # push past 2 minutes. The agent serving endpoint also has its
        # own ~300s hard ceiling, so we can't go higher without that
        # side also timing out first.
        self.endpoint_name = endpoint_name
        self.timeout = timeout

    async def invoke(self, messages: list[dict]) -> str:
        """Call the agent endpoint and return the final assistant text."""
        return await asyncio.to_thread(self._invoke_sync, messages)

    _MAX_INPUT_CHARS = 200_000  # ~50k tokens

    def _invoke_sync(self, messages: list[dict]) -> str:
        total_chars = sum(len(str(m.get("content") or "")) for m in messages)
        if total_chars > self._MAX_INPUT_CHARS:
            raise ValueError(
                f"Input too large ({total_chars:,} chars, limit is "
                f"{self._MAX_INPUT_CHARS:,}). Shorten the conversation or "
                f"start a new thread."
            )

        ws = WorkspaceClient()
        host = ws.config.host.rstrip("/")
        url = f"{host}/serving-endpoints/{self.endpoint_name}/invocations"
        auth_headers = ws.config.authenticate()
        headers = {
            "Authorization": auth_headers["Authorization"],
            "Content-Type": "application/json",
        }
        payload = {
            "input": [
                {
                    "role": (m.get("role") or "user"),
                    "content": str(m.get("content") or ""),
                }
                for m in messages
            ]
        }
        logger.info(
            "Calling agent endpoint url=%s items=%d",
            url,
            len(payload["input"]),
        )
        resp = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
        if resp.status_code >= 400:
            raise RuntimeError(f"Agent endpoint returned {resp.status_code}: {resp.text[:1200]}")
        data = resp.json()
        return _extract_assistant_text(data)


def _extract_assistant_text(data: dict) -> str:
    """Pull the user-visible assistant text out of a serving response.

    Handles three possible shapes:
      1. Mosaic AI ResponsesAgent: `{"output": [{"type":"message","content":[{"type":"output_text","text":"..."}]}, ...]}`
         This is what `ResponsesAgentResponse` serializes to and it's
         what CoCo's `predict()` returns.
      2. OpenAI ChatCompletion: `{"choices": [{"message":{"content":"..."}}]}`
      3. MLflow pyfunc predictions: `{"predictions": [...]}`
    """
    # 1) Responses API output
    output = data.get("output")
    if isinstance(output, list):
        for item in reversed(output):
            if not isinstance(item, dict):
                continue
            # text_output_item shape: {"type": "message", "content": [{"type":"output_text","text":"..."}]}
            content_list = item.get("content")
            if isinstance(content_list, list):
                for c in content_list:
                    if isinstance(c, dict):
                        t = c.get("text")
                        if isinstance(t, str) and t:
                            return t
            # Sometimes flattened to item.text
            t = item.get("text")
            if isinstance(t, str) and t:
                return t

    # 2) OpenAI-style chat completion
    choices = data.get("choices") or []
    if choices:
        first = choices[0] or {}
        msg = first.get("message") or {}
        content = msg.get("content")
        if content:
            return str(content)

    # 3) pyfunc predictions list
    predictions = data.get("predictions")
    if isinstance(predictions, list) and predictions:
        for pred in reversed(predictions):
            if isinstance(pred, dict):
                if isinstance(pred.get("content"), str):
                    return pred["content"]
                inner = pred.get("data")
                if isinstance(inner, dict) and isinstance(inner.get("content"), str):
                    return inner["content"]

    logger.warning("Unrecognized agent response shape; returning raw json")
    return json.dumps(data, indent=2)[:4000]
