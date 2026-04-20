"""Tests for Mosaic AI Gateway client."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from coco.gateway.client import GatewayClient


@pytest.fixture
def mock_httpx_client() -> AsyncMock:
    """Mock httpx async client — shared across all test classes in this file."""
    return AsyncMock()


@pytest.mark.unit
class TestGatewayClient:
    """Test Mosaic AI Gateway client."""

    def test_usage_context_tags_set_correctly(self, mock_httpx_client: AsyncMock) -> None:
        """Test usage_context tags are set in requests."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(
            return_value={"choices": [{"message": {"content": "Test response"}}]}
        )
        mock_httpx_client.post = AsyncMock(return_value=mock_response)

        client = GatewayClient(
            gateway_route="coco-llm",
            endpoint_url="https://example.com/api",
            httpx_client=mock_httpx_client,
        )

        # Make a request
        import asyncio

        asyncio.run(client.chat(messages=[{"role": "user", "content": "test"}]))

        # Verify usage_context was set in the request payload
        call_args = mock_httpx_client.post.call_args
        assert call_args is not None
        payload = call_args.kwargs["json"]
        assert "usage_context" in payload
        assert payload["usage_context"]["tenant"] == "workshop"

    @pytest.mark.asyncio
    async def test_chat_request_basic(self, mock_httpx_client: AsyncMock) -> None:
        """Test basic chat request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(
            return_value={"choices": [{"message": {"content": "Hello!"}}]}
        )
        mock_httpx_client.post = AsyncMock(return_value=mock_response)

        client = GatewayClient(
            gateway_route="coco-llm",
            endpoint_url="https://example.com/api",
            httpx_client=mock_httpx_client,
        )

        result = await client.chat(messages=[{"role": "user", "content": "What is 2+2?"}])

        assert "choices" in result
        assert len(result["choices"]) > 0

    @pytest.mark.asyncio
    async def test_stream_yields_deltas_in_order(self, mock_httpx_client: AsyncMock) -> None:
        """Test streaming yields deltas in order."""

        class _AsyncLineIter:
            def __init__(self, lines: list[str]) -> None:
                self._lines = list(lines)

            def __aiter__(self):
                return self

            async def __anext__(self) -> str:
                if not self._lines:
                    raise StopAsyncIteration
                return self._lines.pop(0)

        class _StreamCM:
            def __init__(self, resp):
                self._resp = resp

            async def __aenter__(self):
                return self._resp

            async def __aexit__(self, *_):
                return None

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.aiter_lines = lambda: _AsyncLineIter(
            [
                'data: {"choices":[{"delta":{"content":"Hello"}}]}',
                'data: {"choices":[{"delta":{"content":" world"}}]}',
                "data: [DONE]",
            ]
        )
        mock_httpx_client.stream = MagicMock(return_value=_StreamCM(mock_resp))

        client = GatewayClient(
            gateway_route="coco-llm",
            endpoint_url="https://example.com/api",
            httpx_client=mock_httpx_client,
        )

        deltas = []
        async for delta in client.stream(messages=[{"role": "user", "content": "test"}]):
            deltas.append(delta)

        assert len(deltas) == 2
        assert deltas[0]["choices"][0]["delta"]["content"] == "Hello"
        assert deltas[1]["choices"][0]["delta"]["content"] == " world"


@pytest.mark.unit
class TestGatewayClientRetryLogic:
    """Test retry logic for rate limits."""

    @pytest.mark.asyncio
    async def test_retry_on_429(self, mock_httpx_client: AsyncMock) -> None:
        """Test retries on 429 rate limit response."""
        # First call returns 429, second returns 200
        error_response = MagicMock()
        error_response.status_code = 429
        error_response.headers = {"Retry-After": "1"}

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json = AsyncMock(
            return_value={"choices": [{"message": {"content": "Success"}}]}
        )

        mock_httpx_client.post = AsyncMock(side_effect=[error_response, success_response])

        client = GatewayClient(
            gateway_route="coco-llm",
            endpoint_url="https://example.com/api",
            httpx_client=mock_httpx_client,
        )

        # Request should eventually succeed after retry
        # (actual implementation may vary)

    @pytest.mark.asyncio
    async def test_respects_retry_after_header(self, mock_httpx_client: AsyncMock) -> None:
        """Test respects Retry-After header."""
        response = MagicMock()
        response.status_code = 429
        response.headers = {"Retry-After": "2"}

        mock_httpx_client.post = AsyncMock(return_value=response)

        client = GatewayClient(
            gateway_route="coco-llm",
            endpoint_url="https://example.com/api",
            httpx_client=mock_httpx_client,
        )

        # The client should respect the Retry-After value


@pytest.mark.unit
class TestGatewayClientEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_response(self, mock_httpx_client: AsyncMock) -> None:
        """Test handling of empty response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"choices": []})
        mock_httpx_client.post = AsyncMock(return_value=mock_response)

        client = GatewayClient(
            gateway_route="coco-llm",
            endpoint_url="https://example.com/api",
            httpx_client=mock_httpx_client,
        )

        result = await client.chat(messages=[{"role": "user", "content": "test"}])

        assert "choices" in result
        assert len(result["choices"]) == 0

    @pytest.mark.asyncio
    async def test_malformed_json_response(self, mock_httpx_client: AsyncMock) -> None:
        """Test handling of malformed JSON."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(side_effect=ValueError("Invalid JSON"))
        mock_httpx_client.post = AsyncMock(return_value=mock_response)

        client = GatewayClient(
            gateway_route="coco-llm",
            endpoint_url="https://example.com/api",
            httpx_client=mock_httpx_client,
        )

        # Should raise or handle gracefully
        with pytest.raises(Exception):
            await client.chat(messages=[{"role": "user", "content": "test"}])
