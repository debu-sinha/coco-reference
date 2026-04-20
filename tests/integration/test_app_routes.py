"""Integration tests for FastAPI app routes."""
import json

import pytest
from httpx import AsyncClient

from coco.app.main import create_app
from coco.config import CocoConfig


@pytest.mark.integration
class TestAppRoutes:
    """Test FastAPI app routes."""

    @pytest.fixture
    async def app_client(self, mock_config: CocoConfig, mock_lakebase):
        """Create FastAPI test client."""
        app = create_app(config=mock_config, lakebase_client=mock_lakebase["client"])
        async with AsyncClient(app=app, base_url="http://test") as client:
            yield client

    @pytest.mark.asyncio
    async def test_create_thread(self, app_client: AsyncClient) -> None:
        """Test POST /api/threads creates a thread."""
        response = await app_client.post(
            "/api/threads",
            json={"title": "Test cohort query"},
            headers={"X-User-ID": "user-1"},
        )

        assert response.status_code == 201
        data = response.json()
        assert "thread_id" in data
        assert data["title"] == "Test cohort query"

    @pytest.mark.asyncio
    async def test_get_threads_list(self, app_client: AsyncClient) -> None:
        """Test GET /api/threads lists user's threads."""
        # Create a thread first
        await app_client.post(
            "/api/threads",
            json={"title": "Query 1"},
            headers={"X-User-ID": "user-1"},
        )

        # List threads
        response = await app_client.get(
            "/api/threads",
            headers={"X-User-ID": "user-1"},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    @pytest.mark.asyncio
    async def test_user_isolation(self, app_client: AsyncClient) -> None:
        """Test GET /api/threads enforces user isolation."""
        # Create thread as user-1
        thread_response = await app_client.post(
            "/api/threads",
            json={"title": "User 1 Query"},
            headers={"X-User-ID": "user-1"},
        )
        thread_id = thread_response.json()["thread_id"]

        # Try to access as user-2
        response = await app_client.get(
            f"/api/threads/{thread_id}",
            headers={"X-User-ID": "user-2"},
        )

        # Should be forbidden or not found
        assert response.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_post_message_starts_sse_stream(self, app_client: AsyncClient) -> None:
        """Test POST /api/threads/{id}/messages returns SSE stream."""
        # Create thread
        thread_response = await app_client.post(
            "/api/threads",
            json={"title": "Test"},
            headers={"X-User-ID": "user-1"},
        )
        thread_id = thread_response.json()["thread_id"]

        # Post message
        response = await app_client.post(
            f"/api/threads/{thread_id}/messages",
            json={"content": "Find diabetes patients"},
            headers={"X-User-ID": "user-1"},
        )

        # Should return streaming response or event stream
        assert response.status_code in (200, 202)

    @pytest.mark.asyncio
    async def test_message_feedback_endpoint(self, app_client: AsyncClient) -> None:
        """Test POST /api/messages/{id}/feedback writes feedback."""
        # Create thread and message first
        thread_response = await app_client.post(
            "/api/threads",
            json={"title": "Test"},
            headers={"X-User-ID": "user-1"},
        )
        thread_id = thread_response.json()["thread_id"]

        # Post message
        msg_response = await app_client.post(
            f"/api/threads/{thread_id}/messages",
            json={"content": "test query"},
            headers={"X-User-ID": "user-1"},
        )
        message_id = "test-msg-id"  # Would come from response

        # Send feedback
        feedback_response = await app_client.post(
            f"/api/messages/{message_id}/feedback",
            json={"rating": "thumbs_up", "comment": "Good result"},
            headers={"X-User-ID": "user-1"},
        )

        assert feedback_response.status_code in (200, 201)


@pytest.mark.integration
class TestAppErrorHandling:
    """Test app error handling."""

    @pytest.fixture
    async def app_client(self, mock_config: CocoConfig, mock_lakebase):
        """Create FastAPI test client."""
        app = create_app(config=mock_config, lakebase_client=mock_lakebase["client"])
        async with AsyncClient(app=app, base_url="http://test") as client:
            yield client

    @pytest.mark.asyncio
    async def test_missing_user_id_header(self, app_client: AsyncClient) -> None:
        """Test request without X-User-ID header is rejected."""
        response = await app_client.post(
            "/api/threads",
            json={"title": "Test"},
        )

        # Should require authentication
        assert response.status_code in (400, 401, 403)

    @pytest.mark.asyncio
    async def test_invalid_thread_id(self, app_client: AsyncClient) -> None:
        """Test request with invalid thread ID."""
        response = await app_client.get(
            "/api/threads/invalid-id-12345",
            headers={"X-User-ID": "user-1"},
        )

        assert response.status_code in (404, 400)

    @pytest.mark.asyncio
    async def test_message_content_required(self, app_client: AsyncClient) -> None:
        """Test message endpoint requires content."""
        # Create thread
        thread_response = await app_client.post(
            "/api/threads",
            json={"title": "Test"},
            headers={"X-User-ID": "user-1"},
        )
        thread_id = thread_response.json()["thread_id"]

        # Post empty message
        response = await app_client.post(
            f"/api/threads/{thread_id}/messages",
            json={},
            headers={"X-User-ID": "user-1"},
        )

        assert response.status_code in (400, 422)
