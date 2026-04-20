"""DSPy signatures for the CoCo agent.

The main signature (`CohortQuerySignature`) is used by `dspy.ReAct`
as the top-level reasoning target. The sub-signatures
(`ClinicalCodeSignature`, `SQLGeneratorSignature`) are used inside
specific tool functions for structured LLM reasoning.

`ResponseSynthesizerSignature` is kept for the optimization notebook
(`03_optimize_dspy.py`) which can tune the synthesizer independently.
"""

from __future__ import annotations

import dspy


class CohortQuerySignature(dspy.Signature):
    """You are a clinical data analyst for a healthcare real-world data
    platform. Answer questions about patient cohorts by querying the
    Unity Catalog tables on Databricks.

    You have tools for inspecting the database schema, looking up
    clinical codes (ICD-10, NDC, CPT), generating SQL, executing SQL,
    and searching a clinical knowledge base.

    ALWAYS call inspect_schema first so you know the real fully-qualified
    table names (catalog.schema.table) and column types. Use EXACTLY the
    fully-qualified names that inspect_schema returns — do not swap them
    for any other catalog or schema. ALWAYS pass generated SQL through
    execute_sql to get real results before answering.
    """

    question: str = dspy.InputField(desc="The user's clinical data question in plain English")
    answer: str = dspy.OutputField(
        desc="A clear markdown-formatted answer with: the result, "
        "the SQL query used, and 2-3 suggested follow-up questions"
    )


class ClinicalCodeSignature(dspy.Signature):
    """Identify clinical codes from natural language.

    Converts user input describing a medical condition, medication, or
    procedure into standardized codes (ICD-10, NDC, CPT) with confidence.
    """

    query: str = dspy.InputField(
        desc="Natural language description of clinical concept "
        "(e.g., 'Type 2 diabetes', 'metformin 500mg', 'left knee MRI')"
    )
    context: str = dspy.InputField(desc="Optional clinical context or domain knowledge", default="")
    codes: str = dspy.OutputField(
        desc="JSON array of clinical codes with format: "
        '[{"code": "E11.9", "type": "ICD-10", '
        '"description": "Type 2 diabetes", "confidence": 0.95}]'
    )
    rationale: str = dspy.OutputField(desc="Explanation of how codes were selected")


class SQLGeneratorSignature(dspy.Signature):
    """Generate SQL for cohort queries.

    Takes natural language cohort criteria and schema context,
    produces executable SQL and validation rationale.
    """

    user_query: str = dspy.InputField(
        desc="Natural language cohort definition "
        "(e.g., 'patients with type 2 diabetes diagnosed after 2022')"
    )
    schema_context: str = dspy.InputField(desc="Available table and column metadata as reference")
    clinical_codes: str = dspy.InputField(
        desc="Resolved clinical codes to include in WHERE clauses", default=""
    )
    sql: str = dspy.OutputField(
        desc="Valid SELECT or WITH...SELECT SQL for Databricks. "
        "Use ONLY the fully-qualified table names (catalog.schema.table) "
        "provided in schema_context — do not substitute any other catalog "
        "or schema. Include table aliases and proper joins."
    )
    rationale: str = dspy.OutputField(desc="Explanation of SQL logic and design choices")


class ResponseSynthesizerSignature(dspy.Signature):
    """Synthesize final response to user.

    Takes user query, tool results, and execution context,
    produces natural language response with sample data and SQL.
    """

    user_query: str = dspy.InputField(desc="Original user question or cohort request")
    tool_results: str = dspy.InputField(
        desc="JSON summary of all tool outputs (clinical codes, SQL, execution results)"
    )
    cohort_sql: str = dspy.InputField(desc="Final SQL query that was executed", default="")
    sample_results: str = dspy.InputField(
        desc="Sample rows from query result as JSON", default="[]"
    )
    result_count: int = dspy.InputField(
        desc="Total number of rows matching cohort criteria", default=0
    )
    response: str = dspy.OutputField(
        desc="Natural language response summarizing cohort and findings"
    )
    suggested_next_steps: str = dspy.OutputField(
        desc="Suggestions for follow-up analysis or refinement", default=""
    )
