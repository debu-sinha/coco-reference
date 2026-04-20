"""SQL generator for cohort queries.

Uses a DSPy ChainOfThought wrapping SQLGeneratorSignature to convert
natural language + clinical codes into Databricks SQL.
"""

from __future__ import annotations

import json
import logging

import dspy

from coco.agent.dspy_lm import ensure_dspy_configured
from coco.agent.models import SQLGeneratorResult
from coco.agent.signatures import SQLGeneratorSignature

logger = logging.getLogger(__name__)


async def generate_sql(
    user_query: str,
    schema_context: str,
    clinical_codes: str = "",
) -> SQLGeneratorResult:
    """Generate SQL for a cohort query.

    Args:
        user_query: Natural language description
        schema_context: Table/column metadata
        clinical_codes: Resolved clinical codes as JSON

    Returns:
        SQLGeneratorResult with SQL, rationale, and validation
    """
    try:
        ensure_dspy_configured()
        generator = dspy.ChainOfThought(SQLGeneratorSignature)

        prediction = generator(
            user_query=user_query,
            schema_context=schema_context,
            clinical_codes=clinical_codes,
        )

        sql = prediction.sql if hasattr(prediction, "sql") else ""
        rationale = prediction.rationale if hasattr(prediction, "rationale") else ""

        # Basic syntax validation (more detailed via EXPLAIN
        # in the executor)
        valid = bool(sql) and "SELECT" in sql.upper()

        # Parse column mappings if present
        column_mappings = "{}"
        if hasattr(prediction, "column_mappings"):
            try:
                column_mappings = json.loads(prediction.column_mappings)
            except (json.JSONDecodeError, TypeError):
                column_mappings = {}

        return SQLGeneratorResult(
            sql=sql,
            rationale=rationale,
            schema_context=schema_context,
            valid=valid,
            validation_error=None if valid else "SQL generation produced invalid result",
        )

    except Exception as e:
        logger.error(f"SQL generation failed: {e}")
        return SQLGeneratorResult(
            sql="",
            rationale=f"Error during generation: {str(e)}",
            valid=False,
            validation_error=str(e),
        )
