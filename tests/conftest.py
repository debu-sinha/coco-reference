"""Pytest configuration and shared fixtures for CoCo tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock

import pytest

from coco.config import (
    AgentEndpointConfig,
    AppConfig,
    CatalogConfig,
    CocoConfig,
    DataGeneratorConfig,
    DeploymentConfig,
    EvaluationConfig,
    GuardrailsConfig,
    LakebaseConfig,
    LLMConfig,
    MLFlowConfig,
    PromptRegistryConfig,
    SQLWarehouseConfig,
    TablesConfig,
    VectorSearchConfig,
    WorkspaceConfig,
)


@pytest.fixture
def mock_config() -> CocoConfig:
    """Return a safe test configuration."""
    return CocoConfig(
        deployment=DeploymentConfig(mode="test"),
        workspace=WorkspaceConfig(
            host="https://test.cloud.databricks.com",
            client_id="test-client-id",
            client_secret="test-client-secret",
        ),
        catalog=CatalogConfig(
            name="coco_test",
            schema="cohort_builder_test",
            volumes={"knowledge": "coco_knowledge_test", "artifacts": "coco_artifacts_test"},
        ),
        tables=TablesConfig(
            patients="patients",
            diagnoses="diagnoses",
            prescriptions="prescriptions",
            procedures="procedures",
            claims="claims",
            suppliers="suppliers",
            agent_inference_table="coco_agent_inference_test",
        ),
        llm=LLMConfig(
            endpoint="databricks-claude-sonnet-4-5",
            gateway_route="coco-llm-test",
            temperature=0.0,
            max_tokens=4096,
        ),
        sql_warehouse=SQLWarehouseConfig(
            id="test-warehouse-id",
            wait_timeout="0s",
            on_wait_timeout="CONTINUE",
            result_disposition="EXTERNAL_LINKS",
            result_format="ARROW_STREAM",
        ),
        lakebase=LakebaseConfig(
            instance="coco-sessions-test",
            database="coco_test",
            schema="sessions",
            pool={"min_conns": 1, "max_conns": 5, "max_idle_seconds": 300},
        ),
        vector_search=VectorSearchConfig(
            endpoint_name="coco-vs-test",
            index_name="coco_knowledge_idx_test",
            embedding_model="databricks-bge-large-en",
            source_table="knowledge_chunks",
            primary_key="chunk_id",
            text_column="content",
            hybrid=True,
        ),
        agent_endpoint=AgentEndpointConfig(
            name="coco-agent-test",
            scale_to_zero=True,
            min_provisioned_concurrency=1,
            max_provisioned_concurrency=2,
            workload_size="Small",
        ),
        mlflow=MLFlowConfig(
            experiment_name="/Shared/coco-agent-test",
            prompt_registry=PromptRegistryConfig(
                cohort_query="coco.cohort_query_test",
                sql_generator="coco.sql_generator_test",
                clinical_codes="coco.clinical_codes_test",
                response_synthesizer="coco.response_synthesizer_test",
            ),
        ),
        app=AppConfig(
            title="CoCo - Cohort Copilot (Test)",
            max_message_tokens=4000,
            sse_heartbeat_seconds=10,
            polling_fallback_after_seconds=180,
            agent_endpoint_url="http://localhost:8000",
        ),
        guardrails=GuardrailsConfig(
            sql_read_only=True,
            allowed_schemas=["coco_test.cohort_builder_test"],
            max_result_rows=100000,
        ),
        evaluation=EvaluationConfig(
            scenarios_file="evaluation/scenarios.yaml",
            scorers=[
                "sql_validity",
                "clinical_code_accuracy",
                "response_relevance",
                "phi_leak_check",
            ],
        ),
        data_generator=DataGeneratorConfig(
            num_patients=100,
            num_suppliers=5,
            start_date="2020-01-01",
            end_date="2025-12-31",
            seed=42,
        ),
    )


@pytest.fixture
def mock_statement_client() -> AsyncMock:
    """Mock Statement Execution API client."""
    client = AsyncMock()

    # Mock submit: returns statement_id
    client.submit = AsyncMock(return_value="stmt-test-123")

    # Mock poll: simulates state transitions
    poll_states = ["PENDING", "RUNNING", "SUCCEEDED"]
    poll_call_count = {"count": 0}

    async def mock_poll(statement_id: str) -> dict[str, Any]:
        poll_call_count["count"] += 1
        state = poll_states[min(poll_call_count["count"] - 1, len(poll_states) - 1)]
        return {
            "statement_id": statement_id,
            "state": state,
            "result": {
                "result_type": "ARROW_STREAM",
                "file_link": {"file_path": "s3://test/result.arrow"},
            }
            if state == "SUCCEEDED"
            else None,
        }

    client.poll = mock_poll

    # Mock fetch_results: returns presigned URL or data
    client.fetch_results = AsyncMock(
        return_value={
            "columns": ["patient_id", "condition"],
            "data": [
                {"patient_id": 1, "condition": "T2DM"},
                {"patient_id": 2, "condition": "HTN"},
            ],
        }
    )

    # Mock explain: returns validation result
    client.explain = AsyncMock(return_value=(True, "Valid SQL"))

    return client


@pytest.fixture
def mock_gateway_client() -> AsyncMock:
    """Mock Mosaic AI Gateway client."""
    client = AsyncMock()

    # Mock chat endpoint
    client.chat = AsyncMock(
        return_value={
            "choices": [
                {
                    "message": {
                        "content": "Based on your request, I found 42 patients with Type 2 diabetes."
                    }
                }
            ]
        }
    )

    # Mock streaming
    async def mock_stream(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
        yield 'data: {"choices":[{"delta":{"content":"Found"}}]}\n\n'
        yield 'data: {"choices":[{"delta":{"content":" patients"}}]}\n\n'
        yield "data: [DONE]\n\n"

    client.stream = mock_stream

    return client


@pytest.fixture
def mock_lakebase() -> dict[str, Any]:
    """In-memory stub of Lakebase client."""
    store: dict[str, Any] = {
        "threads": {},
        "messages": {},
        "runs": {},
        "feedback": {},
    }

    class MockLakebase:
        async def create_thread(self, user_id: str, title: str) -> str:
            thread_id = f"thread_{len(store['threads'])}"
            store["threads"][thread_id] = {
                "id": thread_id,
                "user_id": user_id,
                "title": title,
                "created_at": datetime.utcnow().isoformat(),
            }
            return thread_id

        async def get_thread(self, thread_id: str, user_id: str) -> dict[str, Any]:
            thread = store["threads"].get(thread_id)
            if thread and thread["user_id"] == user_id:
                return thread
            raise ValueError(f"Thread {thread_id} not found or unauthorized")

        async def list_threads(self, user_id: str) -> list[dict[str, Any]]:
            return [t for t in store["threads"].values() if t["user_id"] == user_id]

        async def create_message(self, thread_id: str, role: str, content: str) -> str:
            msg_id = f"msg_{len(store['messages'])}"
            store["messages"][msg_id] = {
                "id": msg_id,
                "thread_id": thread_id,
                "role": role,
                "content": content,
                "created_at": datetime.utcnow().isoformat(),
            }
            return msg_id

        async def get_messages(self, thread_id: str) -> list[dict[str, Any]]:
            return [m for m in store["messages"].values() if m["thread_id"] == thread_id]

        async def create_run(self, thread_id: str, state: str) -> str:
            run_id = f"run_{len(store['runs'])}"
            store["runs"][run_id] = {
                "id": run_id,
                "thread_id": thread_id,
                "state": state,
                "created_at": datetime.utcnow().isoformat(),
            }
            return run_id

        async def update_run(self, run_id: str, state: str) -> None:
            if run_id in store["runs"]:
                store["runs"][run_id]["state"] = state

    return {"client": MockLakebase(), "store": store}


@pytest.fixture
def mock_vector_search() -> AsyncMock:
    """Mock vector search client."""
    client = AsyncMock()

    client.search = AsyncMock(
        return_value={
            "results": [
                {
                    "id": "chunk_1",
                    "text": "Type 2 Diabetes is a metabolic disorder characterized by high blood glucose.",
                    "score": 0.95,
                },
                {
                    "id": "chunk_2",
                    "text": "Metformin is a first-line medication for T2DM management.",
                    "score": 0.87,
                },
            ]
        }
    )

    return client


@pytest.fixture
def sample_patient_data() -> list[dict[str, Any]]:
    """Return 10 rows of synthetic RWD."""
    return [
        {
            "patient_id": 1,
            "date_of_birth": "1965-03-15",
            "gender": "M",
            "race": "Caucasian",
        },
        {
            "patient_id": 2,
            "date_of_birth": "1972-07-22",
            "gender": "F",
            "race": "African American",
        },
        {
            "patient_id": 3,
            "date_of_birth": "1958-11-08",
            "gender": "M",
            "race": "Hispanic",
        },
        {
            "patient_id": 4,
            "date_of_birth": "1980-01-30",
            "gender": "F",
            "race": "Asian",
        },
        {
            "patient_id": 5,
            "date_of_birth": "1975-05-12",
            "gender": "M",
            "race": "Caucasian",
        },
        {
            "patient_id": 6,
            "date_of_birth": "1968-09-25",
            "gender": "F",
            "race": "African American",
        },
        {
            "patient_id": 7,
            "date_of_birth": "1955-12-03",
            "gender": "M",
            "race": "Hispanic",
        },
        {
            "patient_id": 8,
            "date_of_birth": "1982-04-18",
            "gender": "F",
            "race": "Caucasian",
        },
        {
            "patient_id": 9,
            "date_of_birth": "1970-08-27",
            "gender": "M",
            "race": "Asian",
        },
        {
            "patient_id": 10,
            "date_of_birth": "1960-06-14",
            "gender": "F",
            "race": "African American",
        },
    ]
