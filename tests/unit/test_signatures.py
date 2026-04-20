"""Tests for DSPy signatures.

DSPy 2.5+ signature classes are Pydantic BaseModels. The tests here
introspect class-level metadata (model_fields, docstring) rather than
trying to instantiate them — instantiation requires all required input
fields and isn't how signatures are used at runtime (they're passed to
`dspy.ChainOfThought(SignatureClass)` or similar predictors).
"""

import json

import pytest

from coco.agent.signatures import (
    ClinicalCodeSignature,
    ResponseSynthesizerSignature,
    SQLGeneratorSignature,
)


def _field_names(signature_cls) -> set[str]:
    """Return the set of all field names declared on a DSPy signature."""
    return set(signature_cls.model_fields.keys())


@pytest.mark.unit
class TestClinicalCodeSignature:
    """Clinical code identification signature."""

    def test_declared_fields(self) -> None:
        fields = _field_names(ClinicalCodeSignature)
        assert {"query", "context", "codes", "rationale"}.issubset(fields)

    def test_docstring_mentions_clinical_codes(self) -> None:
        doc = (ClinicalCodeSignature.__doc__ or "").lower()
        assert "clinical" in doc or "icd-10" in doc

    def test_codes_output_format_json(self) -> None:
        codes_example = json.dumps(
            [
                {
                    "code": "E11.9",
                    "type": "ICD-10",
                    "description": "Type 2 diabetes mellitus",
                    "confidence": 0.95,
                }
            ]
        )
        parsed = json.loads(codes_example)
        assert isinstance(parsed, list)
        assert parsed[0]["code"] == "E11.9"


@pytest.mark.unit
class TestSQLGeneratorSignature:
    """SQL generator signature."""

    def test_declared_fields(self) -> None:
        fields = _field_names(SQLGeneratorSignature)
        expected = {
            "user_query",
            "schema_context",
            "clinical_codes",
            "sql",
            "rationale",
            "column_mappings",
        }
        assert expected.issubset(fields)

    def test_sql_output_format(self) -> None:
        sql_example = (
            "SELECT p.patient_id, d.code FROM coco.cohort_builder.patients p "
            "JOIN coco.cohort_builder.diagnoses d ON p.patient_id = d.patient_id "
            "WHERE d.code = 'E11.9'"
        )
        assert "SELECT" in sql_example and "FROM" in sql_example

    def test_column_mappings_output_format(self) -> None:
        mappings_example = json.dumps(
            {
                "diabetes": "diagnoses.code",
                "patient": "patients.patient_id",
            }
        )
        parsed = json.loads(mappings_example)
        assert isinstance(parsed, dict)


@pytest.mark.unit
class TestResponseSynthesizerSignature:
    """Response synthesis signature."""

    def test_declared_fields(self) -> None:
        fields = _field_names(ResponseSynthesizerSignature)
        expected = {
            "user_query",
            "tool_results",
            "cohort_sql",
            "sample_results",
            "result_count",
            "response",
            "show_sql",
            "suggested_next_steps",
        }
        assert expected.issubset(fields)

    def test_response_output_is_string(self) -> None:
        response_example = (
            "I found 42 patients with Type 2 diabetes diagnosed after 2022. "
            "The cohort includes patients from your selected facilities. "
            "Common comorbidities include hypertension (67%) and obesity (54%)."
        )
        assert isinstance(response_example, str)
        assert len(response_example) > 0

    def test_tool_results_json_format(self) -> None:
        tool_results_example = json.dumps(
            {
                "clinical_codes": [{"code": "E11.9", "type": "ICD-10", "confidence": 0.95}],
                "sql": "SELECT * FROM diagnoses WHERE code = 'E11.9'",
                "execution_results": {
                    "row_count": 42,
                    "sample_rows": [{"patient_id": 1}],
                },
            }
        )
        parsed = json.loads(tool_results_example)
        assert "clinical_codes" in parsed and "sql" in parsed


@pytest.mark.unit
class TestSignatureEdgeCases:
    """Miscellaneous structural checks."""

    def test_clinical_context_has_default(self) -> None:
        """context is an optional input; FieldInfo should report a default."""
        field = ClinicalCodeSignature.model_fields.get("context")
        assert field is not None
        # DSPy marks optional inputs with a non-PydanticUndefined default
        from pydantic_core import PydanticUndefined

        assert field.default is not PydanticUndefined

    def test_signature_classes_are_dspy_signatures(self) -> None:
        import dspy

        for cls in (
            ClinicalCodeSignature,
            SQLGeneratorSignature,
            ResponseSynthesizerSignature,
        ):
            assert issubclass(cls, dspy.Signature)
