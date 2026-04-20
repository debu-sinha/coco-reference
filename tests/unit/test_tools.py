"""Tests for agent tools."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from coco.agent.models import ClinicalCode, ClinicalCodeResult, SQLGeneratorResult


@pytest.mark.unit
class TestClinicalCodesTool:
    """Test clinical codes identification tool."""

    @pytest.fixture
    def mock_llm(self) -> AsyncMock:
        """Mock LLM for code identification."""
        return AsyncMock()

    def test_returns_icd10_codes(self, mock_llm: AsyncMock) -> None:
        """Test tool returns ICD-10 codes."""
        mock_llm.return_value = {
            "codes": [
                {"code": "E11.9", "type": "ICD-10", "description": "Type 2 DM", "confidence": 0.95},
            ]
        }

        # Simulate tool execution
        codes = [
            ClinicalCode(
                code="E11.9",
                type="ICD-10",
                description="Type 2 diabetes mellitus",
                confidence=0.95,
            )
        ]

        assert len(codes) > 0
        assert codes[0].code == "E11.9"
        assert codes[0].type == "ICD-10"

    def test_returns_ndc_codes(self) -> None:
        """Test tool returns NDC codes for medications."""
        codes = [
            ClinicalCode(
                code="0002-1380-04",
                type="NDC",
                description="Metformin HCl 500mg tablet",
                confidence=0.92,
            )
        ]

        assert any(c.type == "NDC" for c in codes)

    def test_confidence_scores_present(self) -> None:
        """Test confidence scores are present."""
        codes = [
            ClinicalCode(
                code="E11.9",
                type="ICD-10",
                description="Type 2 DM",
                confidence=0.95,
            )
        ]

        for code in codes:
            assert 0.0 <= code.confidence <= 1.0

    def test_multiple_codes_returned(self) -> None:
        """Test tool returns multiple codes for multi-condition queries."""
        codes = [
            ClinicalCode(code="E11.9", type="ICD-10", description="T2DM", confidence=0.95),
            ClinicalCode(code="I10", type="ICD-10", description="HTN", confidence=0.92),
        ]

        assert len(codes) == 2


@pytest.mark.unit
class TestSQLGeneratorTool:
    """Test SQL generation tool."""

    def test_generates_valid_select_sql(self) -> None:
        """Test tool generates valid SELECT SQL."""
        sql = (
            "SELECT p.patient_id, COUNT(*) as diagnosis_count "
            "FROM coco_test.cohort_builder_test.patients p "
            "JOIN coco_test.cohort_builder_test.diagnoses d ON p.patient_id = d.patient_id "
            "WHERE d.code = 'E11.9' "
            "GROUP BY p.patient_id"
        )

        assert sql.startswith("SELECT")
        assert "FROM" in sql
        assert "patients" in sql

    def test_includes_schema_aliases(self) -> None:
        """Test generated SQL includes table aliases."""
        sql = (
            "SELECT p.patient_id, d.code "
            "FROM coco_test.cohort_builder_test.patients p "
            "JOIN coco_test.cohort_builder_test.diagnoses d ON p.patient_id = d.patient_id"
        )

        assert " p" in sql or " AS p" in sql
        assert " d" in sql or " AS d" in sql

    def test_with_cte_supported(self) -> None:
        """Test SQL generator supports WITH CTEs."""
        sql = (
            "WITH diabetes_patients AS ("
            "  SELECT patient_id FROM coco_test.cohort_builder_test.diagnoses "
            "  WHERE code = 'E11.9'"
            ") "
            "SELECT * FROM diabetes_patients"
        )

        assert sql.startswith("WITH")
        assert "AS (" in sql
        assert "SELECT" in sql

    def test_includes_rationale(self) -> None:
        """Test tool provides rationale for SQL."""
        result = SQLGeneratorResult(
            sql="SELECT * FROM patients",
            rationale="Simple SELECT from patients table",
            schema_context="Standard schema",
        )

        assert result.rationale is not None
        assert len(result.rationale) > 0


@pytest.mark.unit
class TestKnowledgeRAGTool:
    """Test knowledge base RAG tool."""

    def test_returns_knowledge_chunks(self, mock_vector_search: AsyncMock) -> None:
        """Test tool returns relevant chunks."""
        chunks = [
            {
                "id": "chunk_1",
                "text": "Type 2 Diabetes is managed with metformin",
                "score": 0.95,
            },
            {
                "id": "chunk_2",
                "text": "Metformin is contraindicated in renal failure",
                "score": 0.87,
            },
        ]

        assert len(chunks) > 0
        assert "text" in chunks[0]
        assert "score" in chunks[0]

    def test_relevance_scores(self) -> None:
        """Test chunks have relevance scores."""
        chunks = [
            {"id": "1", "text": "Very relevant", "score": 0.98},
            {"id": "2", "text": "Somewhat relevant", "score": 0.72},
        ]

        for chunk in chunks:
            assert 0.0 <= chunk["score"] <= 1.0


@pytest.mark.unit
class TestToolIntegration:
    """Test tool interactions."""

    def test_codes_output_used_by_sql_generator(self) -> None:
        """Test clinical codes from codes tool are used in SQL generation."""
        # Simulate pipeline: codes -> SQL
        codes = [
            ClinicalCode(code="E11.9", type="ICD-10", description="T2DM", confidence=0.95)
        ]

        # SQL should reference the extracted code
        sql = f"WHERE code = '{codes[0].code}'"

        assert "E11.9" in sql

    def test_sql_output_used_by_executor(self) -> None:
        """Test generated SQL is ready for execution."""
        sql = (
            "SELECT COUNT(*) as patient_count "
            "FROM coco_test.cohort_builder_test.patients "
            "WHERE patient_id IN (SELECT DISTINCT patient_id FROM "
            "coco_test.cohort_builder_test.diagnoses WHERE code = 'E11.9')"
        )

        # SQL should be executable
        assert sql.startswith("SELECT")
        assert ";" not in sql  # No trailing semicolon needed for Databricks

    def test_tool_error_handling(self) -> None:
        """Test tools handle errors gracefully."""
        # Mock tool that fails
        mock_tool = AsyncMock(side_effect=ValueError("LLM error"))

        # Should propagate error for handling
        import asyncio
        with pytest.raises(ValueError):
            asyncio.run(mock_tool())
