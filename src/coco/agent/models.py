"""Pydantic data models for agent communication.

Defines request/response types, tool calls, and state objects
for the CoCo agent interface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    """Message role enumeration."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Message(BaseModel):
    """A single message in the conversation."""
    role: MessageRole
    content: str


class ToolCallType(str, Enum):
    """Supported tool types."""
    CLINICAL_CODES = "clinical_codes"
    SQL_GENERATOR = "sql_generator"
    SQL_EXECUTOR = "sql_executor"
    KNOWLEDGE_RAG = "knowledge_rag"
    SCHEMA_INSPECTOR = "schema_inspector"


class ToolCall(BaseModel):
    """A tool invocation with input parameters."""
    tool_type: ToolCallType
    tool_name: str
    input_params: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: Optional[str] = None


class ToolResult(BaseModel):
    """Result from a tool execution."""
    tool_call_id: Optional[str] = None
    tool_type: ToolCallType
    tool_name: str
    success: bool
    result: Any
    error: Optional[str] = None
    execution_time_ms: float = 0.0


class ClinicalCode(BaseModel):
    """A clinical code with confidence."""
    code: str
    type: str  # ICD-10, NDC, CPT, etc.
    description: str
    confidence: float = Field(ge=0.0, le=1.0)


class ClinicalCodeResult(BaseModel):
    """Results from clinical code identification."""
    codes: list[ClinicalCode] = Field(default_factory=list)
    query: str = ""
    model_used: str = ""


class SQLGeneratorResult(BaseModel):
    """Results from SQL generation."""
    sql: str = ""
    rationale: str = ""
    schema_context: str = ""
    valid: bool = True
    validation_error: Optional[str] = None


class SQLExecutorResult(BaseModel):
    """Results from SQL execution."""
    statement_id: Optional[str] = None
    row_count: int = 0
    columns: list[str] = Field(default_factory=list)
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)
    result_path: Optional[str] = None
    execution_time_ms: float = 0.0


class KnowledgeRAGResult(BaseModel):
    """Results from knowledge base retrieval."""
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    total_chunks: int = 0
    search_query: str = ""


class SchemaInspectorResult(BaseModel):
    """Results from schema inspection."""
    tables: list[dict[str, Any]] = Field(default_factory=list)
    columns: dict[str, list[dict[str, Any]]] = Field(
        default_factory=dict
    )


class CohortResult(BaseModel):
    """Final cohort definition and result."""
    cohort_id: str = ""
    patient_count: int = 0
    sql: str = ""
    cohort_criteria: str = ""
    created_at: Optional[datetime] = None


@dataclass
class AgentState:
    """Internal agent state during a conversation turn."""
    conversation_id: str
    turn_number: int
    user_message: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    current_cohort: Optional[CohortResult] = None
    thoughts: str = ""
    next_action: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ChatRequest(BaseModel):
    """Request to the agent."""
    conversation_id: str
    messages: list[Message]
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    """Response from the agent."""
    conversation_id: str
    message: Message
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    cohort_result: Optional[CohortResult] = None
    response_time_ms: float = 0.0
