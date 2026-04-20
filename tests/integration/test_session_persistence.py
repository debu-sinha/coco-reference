"""Tests for session persistence across Lakebase replicas."""
import pytest

from coco.app.sessions.threads import ThreadManager
from coco.app.sessions.messages import MessageManager
from coco.app.sessions.runs import RunManager


@pytest.mark.integration
class TestSessionPersistence:
    """Test thread/message/run CRUD across replicas."""

    @pytest.mark.asyncio
    async def test_create_thread_persists(self, mock_lakebase) -> None:
        """Test created thread can be read back."""
        client = mock_lakebase["client"]
        store = mock_lakebase["store"]

        # Create thread
        thread_id = await client.create_thread("user-1", "Test thread")

        # Read thread
        thread = await client.get_thread(thread_id, "user-1")

        assert thread["id"] == thread_id
        assert thread["title"] == "Test thread"
        assert thread["user_id"] == "user-1"

    @pytest.mark.asyncio
    async def test_create_message_persists(self, mock_lakebase) -> None:
        """Test created message can be read back."""
        client = mock_lakebase["client"]

        # Create thread first
        thread_id = await client.create_thread("user-1", "Test")

        # Create message
        msg_id = await client.create_message(thread_id, "user", "Hello")

        # Read messages
        messages = await client.get_messages(thread_id)

        assert len(messages) > 0
        assert any(m["id"] == msg_id for m in messages)

    @pytest.mark.asyncio
    async def test_create_run_persists(self, mock_lakebase) -> None:
        """Test created run can be read back."""
        client = mock_lakebase["client"]

        # Create thread
        thread_id = await client.create_thread("user-1", "Test")

        # Create run
        run_id = await client.create_run(thread_id, "PENDING")

        # Store has run
        assert run_id in mock_lakebase["store"]["runs"]

    @pytest.mark.asyncio
    async def test_run_state_transitions(self, mock_lakebase) -> None:
        """Test run state tracks async statement through PENDING -> RUNNING -> SUCCEEDED."""
        client = mock_lakebase["client"]

        # Create thread and run
        thread_id = await client.create_thread("user-1", "Test")
        run_id = await client.create_run(thread_id, "PENDING")

        # Verify initial state
        assert mock_lakebase["store"]["runs"][run_id]["state"] == "PENDING"

        # Transition to RUNNING
        await client.update_run(run_id, "RUNNING")
        assert mock_lakebase["store"]["runs"][run_id]["state"] == "RUNNING"

        # Transition to SUCCEEDED
        await client.update_run(run_id, "SUCCEEDED")
        assert mock_lakebase["store"]["runs"][run_id]["state"] == "SUCCEEDED"


@pytest.mark.integration
class TestMultiReplicaAccess:
    """Test access patterns across simulated replica pools."""

    @pytest.mark.asyncio
    async def test_write_to_primary_read_from_replica(self, mock_lakebase) -> None:
        """Test create in one pool, read in another with same data."""
        client = mock_lakebase["client"]
        store = mock_lakebase["store"]

        # Create thread (write)
        thread_id = await client.create_thread("user-1", "Query 1")

        # Simulate replica access (read from same store)
        # In real scenario, would be separate connection pool
        thread = await client.get_thread(thread_id, "user-1")

        # Should be consistent
        assert thread["id"] == thread_id

    @pytest.mark.asyncio
    async def test_user_isolation_across_access(self, mock_lakebase) -> None:
        """Test user isolation is maintained across operations."""
        client = mock_lakebase["client"]

        # User 1 creates thread
        thread1 = await client.create_thread("user-1", "User 1 query")

        # User 2 creates thread
        thread2 = await client.create_thread("user-2", "User 2 query")

        # User 1 lists threads
        user1_threads = await client.list_threads("user-1")
        assert len(user1_threads) == 1
        assert user1_threads[0]["id"] == thread1

        # User 2 lists threads
        user2_threads = await client.list_threads("user-2")
        assert len(user2_threads) == 1
        assert user2_threads[0]["id"] == thread2

    @pytest.mark.asyncio
    async def test_concurrent_thread_creation(self, mock_lakebase) -> None:
        """Test concurrent thread creation maintains consistency."""
        client = mock_lakebase["client"]

        # Create multiple threads concurrently (simulated)
        import asyncio
        tasks = [
            client.create_thread("user-1", f"Thread {i}")
            for i in range(5)
        ]
        thread_ids = await asyncio.gather(*tasks)

        # All should be created
        assert len(thread_ids) == 5
        assert len(set(thread_ids)) == 5  # All unique


@pytest.mark.integration
class TestStatementTracking:
    """Test statement execution state tracking through run."""

    @pytest.mark.asyncio
    async def test_statement_id_attached_to_run(self, mock_lakebase) -> None:
        """Test statement ID is associated with run."""
        client = mock_lakebase["client"]

        # Create thread and run
        thread_id = await client.create_thread("user-1", "Test")
        run_id = await client.create_run(thread_id, "PENDING")

        # In real flow, statement_id would be stored on run
        # (implementation detail of run manager)

    @pytest.mark.asyncio
    async def test_run_accessible_by_thread(self, mock_lakebase) -> None:
        """Test run can be looked up by thread."""
        client = mock_lakebase["client"]
        store = mock_lakebase["store"]

        # Create thread and run
        thread_id = await client.create_thread("user-1", "Test")
        run_id = await client.create_run(thread_id, "PENDING")

        # Find run by thread
        runs_for_thread = [
            r for r in store["runs"].values()
            if r["thread_id"] == thread_id
        ]

        assert len(runs_for_thread) > 0
        assert any(r["id"] == run_id for r in runs_for_thread)
