"""Clinical code identifier tool.

Wraps a DSPy ChainOfThought over ClinicalCodeSignature to turn natural
language medical descriptions into ICD-10 / NDC / CPT codes with
confidence scores.
"""

from __future__ import annotations

import json
import logging

import dspy

from coco.agent.dspy_lm import ensure_dspy_configured
from coco.agent.models import ClinicalCode, ClinicalCodeResult
from coco.agent.signatures import ClinicalCodeSignature

logger = logging.getLogger(__name__)


async def identify_clinical_codes(
    query: str,
    context: str = "",
) -> ClinicalCodeResult:
    """Identify clinical codes from natural language.

    Args:
        query: Natural language description
        context: Optional clinical background

    Returns:
        ClinicalCodeResult with parsed codes and metadata
    """
    try:
        ensure_dspy_configured()
        # dspy.ChainOfThought(signature) wraps the signature with
        # automatic rationale generation. Call it directly — no
        # subclass required.
        identifier = dspy.ChainOfThought(ClinicalCodeSignature)

        prediction = identifier(query=query, context=context)

        # Parse codes from output
        codes: list[ClinicalCode] = []
        try:
            codes_data = json.loads(prediction.codes)
            if isinstance(codes_data, list):
                for code_obj in codes_data:
                    codes.append(
                        ClinicalCode(
                            code=code_obj.get("code", ""),
                            type=code_obj.get("type", "UNKNOWN"),
                            description=code_obj.get("description", ""),
                            confidence=float(code_obj.get("confidence", 0.5)),
                        )
                    )
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse codes JSON: {e}")

        return ClinicalCodeResult(codes=codes, query=query, model_used="ClinicalCodeIdentifier")

    except Exception as e:
        logger.error(f"Clinical code identification failed: {e}")
        return ClinicalCodeResult(codes=[], query=query, model_used="ClinicalCodeIdentifier")
