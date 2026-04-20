"""Mosaic AI Gateway / Model Serving client for LLM calls.

The URL pattern /serving-endpoints/{name}/invocations works for both raw
Model Serving endpoints and Mosaic AI Gateway routes, so `gateway_route`
can be either a Gateway route name or a direct endpoint name.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Optional

import httpx
from databricks.sdk import WorkspaceClient

from coco.config import get_config
from coco.gateway.errors import (
    GatewayBackendError,
    GatewayRateLimited,
    GatewaySafetyBlocked,
)

logger = logging.getLogger(__name__)


class GatewayClient:
    """Client for Databricks Model Serving / Mosaic AI Gateway endpoints.

    Supports three construction styles:
      - `GatewayClient()` — reads route and workspace from config.
      - `GatewayClient(gateway_route, endpoint_url, httpx_client=...)` —
        explicit, used by tests to inject a mocked httpx client.
      - `GatewayClient(access_token="...")` — OBO flow in the app.

    Exposes:
      - `chat(messages, ...)` — async, returns full OpenAI-style response.
      - `stream(messages, ...)` — async generator yielding SSE deltas.
      - `call_llm(system_prompt, user_message, ...)` — sync convenience
        wrapper that returns the assistant content string. Used by the
        agent orchestrator's synchronous planning and synthesis loops.
    """

    def __init__(
        self,
        gateway_route: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        httpx_client: Optional[httpx.AsyncClient] = None,
        access_token: Optional[str] = None,
    ) -> None:
        """Initialize Gateway client.

        Args:
            gateway_route: Model Serving endpoint or Gateway route name. Used
                as the `model` field in request payloads. Defaults to
                config.llm.gateway_route.
            endpoint_url: Full URL for POST invocations. Defaults to
                `https://{workspace_host}/serving-endpoints/{gateway_route}/invocations`.
            httpx_client: Optional injectable async client. Primarily for
                unit tests.
            access_token: Optional OBO token. If None, falls back to service
                principal auth via databricks-sdk.
        """
        # Resolve gateway_route and endpoint_url, falling back to config
        if gateway_route is None or endpoint_url is None:
            config = get_config()
            if gateway_route is None:
                gateway_route = config.llm.gateway_route
            if endpoint_url is None:
                workspace_host = config.workspace.host or ""
                workspace_host = workspace_host.rstrip("/")
                if not workspace_host:
                    raise ValueError(
                        "workspace.host is required to build endpoint_url; "
                        "set DATABRICKS_HOST or pass endpoint_url explicitly"
                    )
                if not workspace_host.startswith("http"):
                    workspace_host = f"https://{workspace_host}"
                endpoint_url = f"{workspace_host}/serving-endpoints/{gateway_route}/invocations"
            self._temperature = config.llm.temperature
            self._max_tokens = config.llm.max_tokens
        else:
            # Explicit construction path (tests). Don't require config.
            try:
                config = get_config()
                self._temperature = config.llm.temperature
                self._max_tokens = config.llm.max_tokens
            except Exception:
                self._temperature = 0.0
                self._max_tokens = 4096

        if not gateway_route:
            raise ValueError("gateway_route is required")
        if not endpoint_url:
            raise ValueError("endpoint_url is required")

        self.gateway_route = gateway_route
        self.endpoint_url = endpoint_url
        self.access_token = access_token

        # Injectable async client (tests), else default
        self._http_client = httpx_client or httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            follow_redirects=True,
        )
        # Lazy sync client for call_llm (avoids event-loop coupling)
        self._sync_http_client: Optional[httpx.Client] = None

    # ------------------------------------------------------------------
    # Auth + payload helpers
    # ------------------------------------------------------------------

    def _build_auth_headers(self) -> dict[str, str]:
        """Build authorization headers.

        Uses OBO token if provided, else falls back to service principal
        auth via databricks-sdk.
        """
        if self.access_token:
            return {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            }
        # Fall back to whatever auth the workspace SDK resolves (PAT, OAuth,
        # or workload identity). config.authenticate() returns a full header
        # dict uniformly across auth methods. If SDK auth can't resolve
        # (typical in unit tests with a mocked httpx client), return a
        # placeholder — production requests will 401 at the endpoint, which
        # is louder than a stack trace here.
        try:
            ws = WorkspaceClient()
            headers: dict[str, str] = dict(ws.config.authenticate() or {})
        except Exception as e:
            logger.debug("SDK auth unavailable, using placeholder: %s", e)
            headers = {"Authorization": "Bearer unresolved"}
        headers["Content-Type"] = "application/json"
        return headers

    def _build_payload(
        self,
        messages: list[dict],
        tools: Optional[list[dict]],
        user_id: Optional[str],
        thread_id: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
        stream: bool,
        **kwargs: Any,
    ) -> dict:
        """Build the OpenAI-compatible request payload."""
        payload: dict[str, Any] = {
            "messages": messages,
            "temperature": (temperature if temperature is not None else self._temperature),
            "max_tokens": (max_tokens if max_tokens is not None else self._max_tokens),
            "model": self.gateway_route,
            "usage_context": {
                "user_id": user_id or "unknown",
                "thread_id": thread_id or "unknown",
                "tenant": "workshop",
            },
        }
        if stream:
            payload["stream"] = True
        if tools:
            payload["tools"] = tools
        payload.update(kwargs)
        return payload

    @staticmethod
    def _extract_error_detail(resp: Any) -> Optional[str]:
        """Extract a short error message from a 4xx response."""
        try:
            data = resp.json()
            if callable(getattr(data, "__await__", None)):
                return None
            return data.get("error", {}).get("message")
        except Exception:
            text = getattr(resp, "text", None)
            return text[:100] if isinstance(text, str) else None

    # ------------------------------------------------------------------
    # Async API — used by the FastAPI app, tests, and scorers
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        user_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> dict:
        """Async chat completion.

        Returns the full OpenAI-style response dict (`choices`, `usage`, ...).

        Raises:
            GatewayRateLimited: on 429.
            GatewaySafetyBlocked: on 401/403 (safety filter).
            GatewayBackendError: on 4xx (non-auth) or 5xx.
        """
        payload = self._build_payload(
            messages,
            tools,
            user_id,
            thread_id,
            temperature,
            max_tokens,
            stream=False,
            **kwargs,
        )
        headers = self._build_auth_headers()

        max_retries = 3
        backoff_seconds = 1.0

        for attempt in range(max_retries):
            try:
                resp = await self._http_client.post(
                    self.endpoint_url,
                    json=payload,
                    headers=headers,
                )

                status_code = getattr(resp, "status_code", 200)

                if status_code == 429:
                    retry_after = None
                    try:
                        retry_after = int(resp.headers.get("Retry-After", "0") or "0")
                    except (ValueError, TypeError):
                        pass
                    raise GatewayRateLimited(retry_after_seconds=retry_after)

                if 400 <= status_code < 500:
                    detail = self._extract_error_detail(resp)
                    if status_code in (401, 403):
                        raise GatewaySafetyBlocked(detail=detail)
                    raise GatewayBackendError(
                        status_code=status_code,
                        response_text=detail,
                    )

                if status_code >= 500:
                    if attempt < max_retries - 1:
                        import asyncio

                        await asyncio.sleep(backoff_seconds)
                        backoff_seconds *= 2
                        continue
                    raise GatewayBackendError(
                        status_code=status_code,
                        response_text=getattr(resp, "text", "")[:200],
                    )

                data = resp.json()
                # Support both sync dict-returning mocks and async mocks
                if hasattr(data, "__await__"):
                    data = await data  # type: ignore[misc]
                logger.debug(
                    "Gateway call succeeded; usage=%s",
                    data.get("usage") if isinstance(data, dict) else None,
                )
                return data

            except (
                GatewayRateLimited,
                GatewaySafetyBlocked,
                GatewayBackendError,
            ):
                raise
            except httpx.HTTPError as e:
                raise GatewayBackendError(status_code=0, response_text=str(e))

        raise GatewayBackendError(
            status_code=503,
            response_text="Max retries exceeded",
        )

    async def stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        user_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict]:
        """Stream chat completion deltas.

        Yields parsed SSE event dicts (OpenAI format).
        """
        payload = self._build_payload(
            messages,
            tools,
            user_id,
            thread_id,
            temperature,
            max_tokens,
            stream=True,
            **kwargs,
        )
        headers = self._build_auth_headers()

        try:
            async with self._http_client.stream(
                "POST",
                self.endpoint_url,
                json=payload,
                headers=headers,
            ) as resp:
                status_code = getattr(resp, "status_code", 200)

                if status_code == 429:
                    retry_after = None
                    try:
                        retry_after = int(resp.headers.get("Retry-After", "0") or "0")
                    except (ValueError, TypeError):
                        pass
                    raise GatewayRateLimited(retry_after_seconds=retry_after)

                if 400 <= status_code < 500:
                    detail = None
                    try:
                        body = await resp.aread()
                        detail = body.decode("utf-8", errors="replace")[:200]
                    except Exception:
                        pass
                    if status_code in (401, 403):
                        raise GatewaySafetyBlocked(detail=detail)
                    raise GatewayBackendError(
                        status_code=status_code,
                        response_text=detail,
                    )

                if status_code >= 500:
                    raise GatewayBackendError(
                        status_code=status_code,
                        response_text=None,
                    )

                async for line in resp.aiter_lines():
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            yield json.loads(data_str)
                        except Exception as e:
                            logger.warning("Failed to parse SSE line: %s", e)

        except (GatewayRateLimited, GatewaySafetyBlocked, GatewayBackendError):
            raise
        except httpx.HTTPError as e:
            raise GatewayBackendError(status_code=0, response_text=str(e))

    # ------------------------------------------------------------------
    # Sync API — used by the agent orchestrator's sync planner/synthesizer
    # ------------------------------------------------------------------

    def call_llm(
        self,
        system_prompt: str,
        user_message: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Synchronous single-turn call. Returns the assistant content string.

        Uses a dedicated sync httpx.Client so it can be called from inside
        agent orchestration code that is not itself async (and so it won't
        fight a running event loop if one exists).
        """
        if self._sync_http_client is None:
            self._sync_http_client = httpx.Client(
                timeout=httpx.Timeout(60.0, connect=10.0),
                follow_redirects=True,
            )

        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": (temperature if temperature is not None else self._temperature),
            "max_tokens": (max_tokens if max_tokens is not None else self._max_tokens),
            "model": self.gateway_route,
        }
        headers = self._build_auth_headers()

        resp = self._sync_http_client.post(
            self.endpoint_url,
            json=payload,
            headers=headers,
        )

        if resp.status_code == 429:
            retry_after = None
            try:
                retry_after = int(resp.headers.get("Retry-After", "0") or "0")
            except (ValueError, TypeError):
                pass
            raise GatewayRateLimited(retry_after_seconds=retry_after)

        if 400 <= resp.status_code < 500:
            detail = self._extract_error_detail(resp)
            if resp.status_code in (401, 403):
                raise GatewaySafetyBlocked(detail=detail)
            raise GatewayBackendError(
                status_code=resp.status_code,
                response_text=detail,
            )

        if resp.status_code >= 500:
            raise GatewayBackendError(
                status_code=resp.status_code,
                response_text=resp.text[:200],
            )

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise GatewayBackendError(
                status_code=resp.status_code,
                response_text=f"unexpected response shape: {e}",
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "GatewayClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the async HTTP client."""
        if self._http_client is not None:
            await self._http_client.aclose()
        if self._sync_http_client is not None:
            self._sync_http_client.close()
            self._sync_http_client = None
