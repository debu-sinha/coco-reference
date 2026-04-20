"""CoCo agent: dspy.ReAct with native tool calling.

Replaces the previous keyword-matched planner loop with dspy.ReAct,
which uses the LLM's native function-calling capability to decide
which tools to call and what arguments to pass. This is architecturally
identical to how Claude Code / MCP works: the model sees tool
definitions, returns structured tool_use blocks, the runtime executes
them, and the model decides next steps. No separate "planner" prompt,
no keyword matching, no fragile token parsing.

The tools are plain Python functions with docstrings. dspy.ReAct
introspects the function name, docstring, and parameter annotations
to build the tool schemas the LLM sees. Each function returns a
string result that feeds back into the model's context for the next
reasoning step.

DSPy's LM is configured to point at databricks-claude-sonnet-4-5
via the Mosaic AI Foundation Model API. The configuration happens
once at CocoAgent.__init__ time using the serving container's SP
credentials (WorkspaceClient with workload identity).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
from datetime import datetime
from typing import Any, Awaitable, Iterator, Optional, TypeVar

import dspy
import mlflow
import mlflow.dspy

from coco.agent.guardrails import validate_sql_query
from coco.agent.models import Message
from coco.agent.prompts import load_prompt
from coco.agent.signatures import (
    ClinicalCodeSignature,
    CohortQuerySignature,
    SQLGeneratorSignature,
)
from coco.config import get_config
from coco.observability.user_context import set_user_context

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Enable MLflow DSPy autologging so every dspy.Predict / dspy.ReAct
# call produces an MLflow trace with inputs, outputs, and latency.
mlflow.dspy.autolog()


def _run_coro_sync(coro: Awaitable[T]) -> T:
    """Run an async coroutine from sync code, regardless of loop state."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # type: ignore[arg-type]
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()  # type: ignore[arg-type]


# -----------------------------------------------------------------------
# Tool functions for dspy.ReAct
#
# Each function is a plain sync Python function. dspy.ReAct reads the
# function name, docstring, and parameter type hints to build the JSON
# schema the LLM sees as a tool definition. The return value (always a
# string) feeds back into the model's context for the next step.
#
# The functions call into the existing async tool implementations via
# _run_coro_sync. The async layer handles the actual SDK / HTTP work.
# -----------------------------------------------------------------------


# Process-wide schema cache. Schema doesn't change mid-conversation
# (or even mid-hour), and the eval showed the agent calls inspect_schema
# every turn even when it just called it 5s ago. Cache the rendered
# string indefinitely within a serving-container lifetime — a fresh
# deploy or container restart flushes it. Keyed as a single entry
# because the agent is pinned to one (catalog, schema) via config.
_SCHEMA_CACHE: dict[str, str] = {}


@mlflow.trace
def inspect_schema() -> str:
    """List all tables and their columns in the configured Unity Catalog schema.

    Call this FIRST when you need to know what data is available before
    writing SQL. Returns fully-qualified table names (catalog.schema.table)
    with column names and types — use those exact names in generated SQL.
    """
    # Cache hit: the agent spec has the planner re-inspect schema on
    # every turn, which wasted ~2-3s per repeat call during eval.
    # Schema is stable so the first call's output is reusable.
    if "rendered" in _SCHEMA_CACHE:
        return _SCHEMA_CACHE["rendered"]

    from coco.agent.tools.schema_inspector import inspect_schema as _inspect

    try:
        result = _run_coro_sync(_inspect())
    except Exception as e:
        # Don't cache failures - try again next turn.
        return f"Schema inspection failed: {e}"

    if not result.tables:
        return "No tables found in the schema. It may be empty or inaccessible."

    lines = []
    for t in result.tables:
        cols = result.columns.get(t["name"], [])
        col_str = ", ".join(f"{c['name']} ({c['type']})" for c in cols)
        lines.append(f"  {t['full_name']}: {col_str}")
    rendered = "Available tables:\n" + "\n".join(lines)
    _SCHEMA_CACHE["rendered"] = rendered
    return rendered


@mlflow.trace
def execute_sql(sql: str) -> str:
    """Execute a SQL query against the Databricks warehouse and return results.

    The SQL must be a read-only statement (SELECT, SHOW, DESCRIBE, WITH).
    Always reference tables with the fully-qualified names (catalog.schema.table)
    that inspect_schema reported; do not substitute a different catalog or
    schema. INSERT, UPDATE, DELETE, and DDL statements are rejected by
    the guardrails.
    """
    valid, reason = validate_sql_query(sql)
    if not valid:
        return f"SQL validation failed: {reason}. Fix the query and try again."

    from coco.agent.tools.sql_executor import execute_sql as _exec

    try:
        result = _run_coro_sync(_exec(sql))
    except Exception as e:
        return f"SQL execution failed: {e}"

    if result.row_count == 0 and not result.columns:
        return "Query returned 0 rows and no column metadata. The table may not exist or be empty."
    if result.row_count == 0:
        return f"Query returned 0 rows. Columns: {result.columns}"

    sample = json.dumps(result.sample_rows[:10], default=str, indent=2)
    return (
        f"Query returned {result.row_count} rows.\n"
        f"Columns: {result.columns}\n"
        f"Sample rows (up to 10):\n{sample}"
    )


@mlflow.trace
def identify_clinical_codes(condition: str) -> str:
    """Look up ICD-10, NDC, or CPT codes for a medical condition, medication, or procedure.

    Example: identify_clinical_codes("Type 2 diabetes") returns E11.* ICD-10 codes.
    Use this when the user mentions a clinical concept by name and you need
    the standardized codes to filter data.
    """
    try:
        sig = ClinicalCodeSignature.with_instructions(load_prompt("clinical_codes"))
        predictor = dspy.ChainOfThought(sig)
        result = predictor(query=condition, context="")
        return f"Clinical codes: {result.codes}\nRationale: {result.rationale}"
    except Exception as e:
        return f"Clinical code lookup failed: {e}"


@mlflow.trace
def generate_sql(criteria: str, schema_context: str = "", clinical_codes: str = "") -> str:
    """Generate a Databricks SQL query from natural language criteria.

    Pass the schema context from inspect_schema and clinical codes from
    identify_clinical_codes so the generated SQL uses real table and column
    names. The SQL is validated against guardrails before being returned.
    """
    try:
        sig = SQLGeneratorSignature.with_instructions(load_prompt("sql_generator"))
        predictor = dspy.ChainOfThought(sig)
        result = predictor(
            user_query=criteria,
            schema_context=schema_context or "(call inspect_schema first to get the real schema)",
            clinical_codes=clinical_codes or "(no codes identified yet)",
        )
        sql = (result.sql or "").strip()
        if not sql:
            return "SQL generator produced empty output. Try rephrasing the criteria."

        valid, reason = validate_sql_query(sql)
        if not valid:
            return f"Generated SQL failed validation: {reason}\nSQL was: {sql}"

        return f"Generated SQL:\n```sql\n{sql}\n```\nRationale: {result.rationale}"
    except Exception as e:
        return f"SQL generation failed: {e}"


@mlflow.trace
def retrieve_knowledge(query: str) -> str:
    """Search the clinical knowledge base for background information about a topic.

    Use this when you need clinical context, coding guidelines, or
    domain-specific information before answering a question.
    """
    from coco.agent.tools.knowledge_rag import retrieve_knowledge as _rag

    try:
        result = _run_coro_sync(_rag(query=query))
        data = result.model_dump(mode="json")
        chunks = data.get("chunks", [])
        if not chunks:
            return "No relevant knowledge found for this query."
        texts = [c.get("text", "") for c in chunks[:5]]
        return "Relevant knowledge:\n" + "\n---\n".join(texts)
    except Exception as e:
        return f"Knowledge retrieval failed: {e}"


# -----------------------------------------------------------------------
# Stream event (kept for backward compat with the entry wrapper)
# -----------------------------------------------------------------------


def _format_trajectory(traj: dict) -> str:
    """Format the dspy.ReAct trajectory dict as a readable text block.

    The trajectory dict has keys like thought_0, tool_name_0,
    tool_args_0, observation_0, thought_1, tool_name_1, ... and
    the final step uses tool_name_N = "finish".

    Output is a simple numbered list:
      STEP 1: inspect_schema()
        Thought: I need to see what data is available...
        Result: 6 tables found (truncated)
      STEP 2: execute_sql(SELECT COUNT(*)...)
        Thought: Now I can count the patients...
        Result: 10,000 rows (truncated)
    """
    if not traj:
        return ""

    steps = []
    i = 0
    while f"tool_name_{i}" in traj:
        tool = traj.get(f"tool_name_{i}", "")
        args = traj.get(f"tool_args_{i}", {})
        thought = traj.get(f"thought_{i}", "")
        obs = traj.get(f"observation_{i}", "")

        if tool == "finish":
            i += 1
            continue

        args_str = ""
        if isinstance(args, dict) and args:
            first_val = str(list(args.values())[0])
            if len(first_val) > 80:
                first_val = first_val[:77] + "..."
            args_str = f"({first_val})"

        obs_short = obs[:150].replace("\n", " ")
        if len(obs) > 150:
            obs_short += "..."

        thought_short = thought[:200].replace("\n", " ")
        if len(thought) > 200:
            thought_short += "..."

        steps.append(
            f"STEP {i + 1}: {tool}{args_str}\n  Thought: {thought_short}\n  Result: {obs_short}"
        )
        i += 1

    if not steps:
        return ""

    return "\n".join(steps)


class ResponsesAgentStreamEvent:
    """Represents a stream event from the agent."""

    def __init__(
        self,
        event_type: str,
        content: Any = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        self.event_type = event_type
        self.content = content
        self.metadata = metadata or {}
        self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


# -----------------------------------------------------------------------
# CocoAgent: the dspy.ReAct-based agent
# -----------------------------------------------------------------------


class CocoAgent:
    """Mosaic AI agent for healthcare cohort queries.

    Uses dspy.ReAct with native tool calling. The LLM (Claude via FMAPI)
    sees tool definitions derived from the function docstrings above and
    decides which tools to call on each reasoning step. No separate
    planner prompt, no keyword matching. The model IS the planner.
    """

    # Maximum reasoning iterations for the ReAct loop. Each iteration
    # is one LLM call that may or may not invoke a tool. 7 iterations
    # is enough for: inspect_schema + identify_codes + generate_sql +
    # execute_sql + synthesize = 5 steps, with 2 spare for retries.
    MAX_ITERS = 7

    def __init__(self) -> None:
        self.config = get_config()
        self._configure_dspy_lm()
        sig = CohortQuerySignature.with_instructions(load_prompt("cohort_query"))
        self.react = dspy.ReAct(
            sig,
            tools=[
                inspect_schema,
                execute_sql,
                identify_clinical_codes,
                generate_sql,
                retrieve_knowledge,
            ],
            max_iters=self.MAX_ITERS,
        )

    def _configure_dspy_lm(self) -> None:
        """Point DSPy at databricks-claude-sonnet-4-5 via FMAPI.

        The serving container's workload identity (SP credentials) is
        used to mint a short-lived Bearer token. DSPy's LiteLLM backend
        uses the `databricks/` provider prefix to route the call through
        the Databricks serving endpoint format.
        """
        try:
            from databricks.sdk import WorkspaceClient

            ws = WorkspaceClient()
            host = (ws.config.host or "").rstrip("/")
            token = ws.config.authenticate().get("Authorization", "").split(" ", 1)[-1]
        except Exception as e:
            logger.warning("Could not resolve Databricks auth for DSPy LM: %s", e)
            host = ""
            token = ""

        endpoint = self.config.llm.endpoint
        if not host or not token:
            logger.error(
                "DSPy LM not configured: host=%s endpoint=%s token_present=%s",
                host,
                endpoint,
                bool(token),
            )
            return

        lm = dspy.LM(
            f"databricks/{endpoint}",
            api_base=f"{host}/serving-endpoints",
            api_key=token,
            max_tokens=4000,
            temperature=0.0,
        )
        dspy.configure(lm=lm)
        logger.info(
            "DSPy LM configured: databricks/%s via %s",
            endpoint,
            host,
        )

    def predict(self, messages: list[Message]) -> list[ResponsesAgentStreamEvent]:
        """Synchronous prediction (non-streaming)."""
        return list(self.predict_stream(messages))

    def _refresh_lm_token(self) -> None:
        """Refresh the FMAPI Bearer token on the existing DSPy LM.

        dspy.configure() can only be called from the thread that
        originally ran it (DSPy enforces thread affinity on settings).
        The request handler runs on a different thread, so calling
        _configure_dspy_lm() here raises RuntimeError. Instead, we
        directly update the api_key on the existing LM object. This
        mutates the credentials without touching dspy.settings.
        """
        try:
            from databricks.sdk import WorkspaceClient

            ws = WorkspaceClient()
            token = ws.config.authenticate().get("Authorization", "").split(" ", 1)[-1]
            lm = dspy.settings.lm
            if lm and hasattr(lm, "kwargs"):
                lm.kwargs["api_key"] = token
        except Exception as e:
            logger.warning("Could not refresh DSPy LM token: %s", e)

    def predict_stream(self, messages: list[Message]) -> Iterator[ResponsesAgentStreamEvent]:
        # Re-mint the FMAPI token on every request (~100ms). The token
        # from WorkspaceClient is ~1h TTL but the container lives longer.
        self._refresh_lm_token()
        """Run the dspy.ReAct loop and yield the final assistant event.

        The ReAct module handles tool calling internally. We get one
        final answer string at the end. Intermediate tool calls are
        logged to MLflow traces via mlflow.dspy.autolog() but are not
        surfaced as separate stream events (the UI shows "Thinking..."
        during the loop and the full rendered response when it finishes).
        """
        # Extract user_id + thread_id from the system message the App
        # prepends to every request. Set them as MLflow trace tags so
        # traces are attributable to a specific user and conversation.
        user_id = "unknown"
        thread_id = "unknown"
        for msg in messages:
            if msg.role.value == "system" and "[coco_meta:" in (msg.content or ""):
                meta = msg.content.split("[coco_meta:", 1)[1].split("]", 1)[0]
                for pair in meta.split(","):
                    k, _, v = pair.strip().partition("=")
                    if k.strip() == "user_id":
                        user_id = v.strip()
                    elif k.strip() == "thread_id":
                        thread_id = v.strip()
                break

        user_msg = ""
        if messages:
            # Skip the system meta message when extracting the user query
            for msg in reversed(messages):
                if msg.role.value != "system":
                    user_msg = msg.content or ""
                    break

        if not user_msg.strip():
            yield ResponsesAgentStreamEvent(
                "assistant",
                {
                    "content": "I did not receive a question. Please ask me about the patient cohort."
                },
            )
            return

        # Publish user_id + thread_id as request-scoped context so the SQL
        # statement client and other tools can tag their requests for
        # per-user cost attribution in system.billing + system.query.history.
        set_user_context(user_id, thread_id)

        # Inject the same attribution into the LM request so it lands in
        # the serving endpoint inference table. LiteLLM forwards
        # extra_headers to the upstream HTTP call.
        try:
            lm = dspy.settings.lm
            if lm is not None and hasattr(lm, "kwargs"):
                headers = dict(lm.kwargs.get("extra_headers") or {})
                headers["X-Databricks-Usage-Context"] = f"user_id={user_id},thread_id={thread_id}"
                lm.kwargs["extra_headers"] = headers
        except Exception as e:
            logger.debug("Could not set LM usage-context header: %s", e)

        trajectory = {}
        with mlflow.start_span("react_agent") as span:
            span.set_attributes(
                {
                    "user_id": user_id,
                    "thread_id": thread_id,
                    "user_message": user_msg[:500],
                    "max_iters": self.MAX_ITERS,
                }
            )
            try:
                result = self.react(question=user_msg)
                answer = result.answer or "(The agent did not produce an answer.)"
                trajectory = getattr(result, "trajectory", {}) or {}
            except Exception as e:
                logger.exception("ReAct agent failed: %s", e)
                answer = f"I encountered an error while processing your request: {e}"
                span.set_attributes({"error": str(e)[:500]})

        # Embed the trajectory as a plaintext block appended to the
        # answer, separated by a known delimiter. The serving endpoint
        # serializes this as one string. The App's SSE endpoint splits
        # on the delimiter and renders the two parts differently:
        # answer as markdown, trajectory as an HTML <details> block.
        trajectory_text = _format_trajectory(trajectory)
        full_content = answer
        if trajectory_text:
            full_content = answer + "\n\n<!-- COCO_TRAJECTORY -->\n" + trajectory_text

        yield ResponsesAgentStreamEvent("assistant", {"content": full_content})
