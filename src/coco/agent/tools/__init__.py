"""Tool registry for the CoCo agent.

Exports all available tool functions for use in agent orchestration.
"""
from __future__ import annotations

from coco.agent.tools.clinical_codes import (
    identify_clinical_codes,
)
from coco.agent.tools.knowledge_rag import retrieve_knowledge
from coco.agent.tools.schema_inspector import inspect_schema
from coco.agent.tools.sql_executor import execute_sql
from coco.agent.tools.sql_generator import generate_sql

__all__ = [
    "identify_clinical_codes",
    "retrieve_knowledge",
    "inspect_schema",
    "generate_sql",
    "execute_sql",
]
