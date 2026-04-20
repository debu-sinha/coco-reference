"""CoCo - Healthcare Cohort Copilot on Databricks.

Complete healthcare cohort-building platform with:
- Agent orchestration (LLM + DSPy)
- SQL generation and validation
- Clinical terminology resolution
- Vector search integration
- Streaming model serving
"""
from __future__ import annotations

__version__ = "2.0.0"
__author__ = "Databricks"

from coco.config import get_config

__all__ = ["get_config"]
