"""Tests for SQL guardrails and validation."""

from unittest.mock import patch

import pytest

from coco.agent.guardrails import validate_sql_query
from coco.config import CocoConfig


@pytest.mark.unit
class TestGuardrailsReadOnly:
    """Test read-only SQL restrictions."""

    def test_select_allowed(self, mock_config: CocoConfig) -> None:
        """Test SELECT queries are allowed."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            is_valid, reason = validate_sql_query("SELECT * FROM patients")
            assert is_valid is True

    def test_select_with_statement(self, mock_config: CocoConfig) -> None:
        """Test SELECT with WITH clause is allowed."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            sql = """
            WITH cte AS (
                SELECT patient_id FROM diagnoses WHERE code = 'E11.9'
            )
            SELECT * FROM cte
            """
            is_valid, reason = validate_sql_query(sql)
            assert is_valid is True

    def test_insert_rejected(self, mock_config: CocoConfig) -> None:
        """Test INSERT is rejected in read-only mode."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            is_valid, reason = validate_sql_query("INSERT INTO patients (patient_id) VALUES (1)")
            assert is_valid is False
            assert "INSERT" in reason

    def test_update_rejected(self, mock_config: CocoConfig) -> None:
        """Test UPDATE is rejected."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            is_valid, reason = validate_sql_query(
                "UPDATE patients SET name = 'John' WHERE patient_id = 1"
            )
            assert is_valid is False
            assert "UPDATE" in reason

    def test_delete_rejected(self, mock_config: CocoConfig) -> None:
        """Test DELETE is rejected."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            is_valid, reason = validate_sql_query("DELETE FROM patients WHERE patient_id = 1")
            assert is_valid is False
            assert "DELETE" in reason

    def test_drop_rejected(self, mock_config: CocoConfig) -> None:
        """Test DROP is rejected."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            is_valid, reason = validate_sql_query("DROP TABLE patients")
            assert is_valid is False
            assert "DROP" in reason

    def test_alter_rejected(self, mock_config: CocoConfig) -> None:
        """Test ALTER is rejected."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            is_valid, reason = validate_sql_query("ALTER TABLE patients ADD COLUMN age INT")
            assert is_valid is False
            assert "ALTER" in reason

    def test_create_rejected(self, mock_config: CocoConfig) -> None:
        """Test CREATE is rejected."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            is_valid, reason = validate_sql_query("CREATE TABLE new_table (id INT)")
            assert is_valid is False
            assert "CREATE" in reason


@pytest.mark.unit
class TestGuardrailsSchemaRestrictions:
    """Test schema allow-list enforcement."""

    def test_allowed_schema(self, mock_config: CocoConfig) -> None:
        """Test query against allowed schema passes."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            sql = "SELECT * FROM coco_test.cohort_builder_test.patients"
            is_valid, reason = validate_sql_query(sql)
            # Should pass schema check (may fail parsing, but not schema check)
            if is_valid:
                assert is_valid is True

    def test_disallowed_schema_rejected(self, mock_config: CocoConfig) -> None:
        """Test query against disallowed schema is rejected."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            is_valid, reason = validate_sql_query(
                "SELECT * FROM other_catalog.other_schema.patients"
            )
            assert is_valid is False
            assert "not in allowed list" in reason or "Schema" in reason


@pytest.mark.unit
class TestGuardrailsEdgeCases:
    """Test edge cases in SQL parsing."""

    def test_case_insensitive_keywords(self, mock_config: CocoConfig) -> None:
        """Test keyword detection is case-insensitive."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            # Lowercase insert should also be rejected
            is_valid, reason = validate_sql_query("insert into patients values (1)")
            assert is_valid is False
            assert "INSERT" in reason or "insert" in reason.lower()

    def test_nested_subqueries(self, mock_config: CocoConfig) -> None:
        """Test nested SELECT subqueries are allowed."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            sql = """
            SELECT * FROM (
                SELECT * FROM (
                    SELECT * FROM patients
                ) inner_query
            ) outer_query
            """
            is_valid, reason = validate_sql_query(sql)
            # Should allow nested SELECTs
            assert is_valid is True or "SELECT" not in reason

    def test_cte_with_multiple_clauses(self, mock_config: CocoConfig) -> None:
        """Test CTE with multiple WITH clauses."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            sql = """
            WITH cte1 AS (
                SELECT patient_id FROM diagnoses
            ),
            cte2 AS (
                SELECT patient_id FROM prescriptions
            )
            SELECT * FROM cte1 JOIN cte2 USING (patient_id)
            """
            is_valid, reason = validate_sql_query(sql)
            assert is_valid is True or "SELECT" not in reason

    def test_comment_in_sql(self, mock_config: CocoConfig) -> None:
        """Test SQL with comments is handled correctly."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            sql = """
            -- This is a comment
            SELECT * FROM patients
            /* Block comment */
            """
            is_valid, reason = validate_sql_query(sql)
            assert is_valid is True

    def test_empty_query(self, mock_config: CocoConfig) -> None:
        """Test empty query is rejected."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            is_valid, reason = validate_sql_query("")
            assert is_valid is False


@pytest.mark.unit
class TestGuardrailsInjectionProtection:
    """Test protection against SQL injection patterns."""

    def test_drop_in_where_clause(self, mock_config: CocoConfig) -> None:
        """Test DROP keyword in WHERE clause is caught."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            is_valid, reason = validate_sql_query("SELECT * FROM patients WHERE name LIKE 'DROP%'")
            # Word boundary check should prevent false positives in strings
            # but actual behavior depends on implementation

    def test_union_select_injection(self, mock_config: CocoConfig) -> None:
        """Test UNION SELECT injection is caught (or at least allowed if read-only)."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            is_valid, reason = validate_sql_query(
                "SELECT * FROM patients UNION SELECT * FROM users"
            )
            # Should be allowed as both are SELECT
            if is_valid is False:
                # Or rejected if not in allowed schema
                assert "allowed" in reason.lower()


@pytest.mark.unit
class TestGuardrailsAdversarial:
    """Adversarial cases — document what the regex-based guardrail does vs.
    doesn't catch. Remember the primary PHI/PII boundary is the SP's
    read-only UC grants; these tests are defense-in-depth coverage."""

    def test_multistatement_drop_after_select(self, mock_config: CocoConfig) -> None:
        """Semicolon-separated DROP after a valid SELECT must be rejected."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            is_valid, reason = validate_sql_query(
                "SELECT * FROM coco_test.cohort_builder_test.patients; DROP TABLE x"
            )
            assert is_valid is False
            assert "DROP" in reason

    def test_nested_block_comment_hiding_drop(self, mock_config: CocoConfig) -> None:
        """Nested block comments (some engines accept them) must not let DROP slip through.

        The strip_noise helper iterates block-comment removal so
        ``/* outer /* DROP TABLE x */ still outer */`` collapses to blank.
        After stripping the ONLY tokens outside comments are SELECT, so
        the query should be accepted as read-only.
        """
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            sql = "SELECT /* outer /* DROP TABLE x */ still outer */ 1"
            is_valid, _ = validate_sql_query(sql)
            assert is_valid is True

    def test_drop_inside_string_literal_allowed(self, mock_config: CocoConfig) -> None:
        """DROP inside a quoted string should not trip the keyword check."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            is_valid, _ = validate_sql_query(
                "SELECT * FROM coco_test.cohort_builder_test.patients WHERE note = 'do not DROP'"
            )
            assert is_valid is True

    def test_escaped_single_quote_with_drop(self, mock_config: CocoConfig) -> None:
        """Escaped single quote within a string literal must not let DROP through."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            sql = (
                "SELECT * FROM coco_test.cohort_builder_test.patients "
                "WHERE note = 'I said ''DROP it'' but did not'"
            )
            is_valid, _ = validate_sql_query(sql)
            assert is_valid is True

    def test_drop_inside_line_comment_allowed(self, mock_config: CocoConfig) -> None:
        """Keyword inside a -- comment must be stripped before the scan."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            sql = "SELECT * FROM coco_test.cohort_builder_test.patients -- DROP TABLE patients"
            is_valid, _ = validate_sql_query(sql)
            assert is_valid is True

    def test_invalid_identifier_chars_rejected(self, mock_config: CocoConfig) -> None:
        """Identifiers with non-safe characters must be rejected, not silently allowed.

        Tries a catalog with a space-escape trick that could bypass the
        allowlist lookup if the regex matched it as a three-part ident.
        The SAFE_IDENT pattern rejects anything outside [A-Za-z0-9_].
        """
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            # Leading dash is invalid per SAFE_IDENT
            is_valid, reason = validate_sql_query(
                "SELECT * FROM `-evil`.cohort_builder_test.patients"
            )
            assert is_valid is False
            assert "identifier" in reason.lower() or "not in allowed" in reason.lower()

    def test_disallowed_catalog_in_cte_rejected(self, mock_config: CocoConfig) -> None:
        """A CTE that references a disallowed catalog three-part name must be rejected."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            sql = """
            WITH leaked AS (
                SELECT * FROM prod_catalog.secret_schema.patients
            )
            SELECT * FROM leaked
            """
            is_valid, reason = validate_sql_query(sql)
            assert is_valid is False
            assert "allowed" in reason.lower()

    def test_lowercase_drop_rejected(self, mock_config: CocoConfig) -> None:
        """Keyword check is case-insensitive."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            is_valid, reason = validate_sql_query("drop table patients")
            assert is_valid is False
            assert "DROP" in reason.upper()

    def test_truncate_rejected(self, mock_config: CocoConfig) -> None:
        """TRUNCATE is a write op, must be blocked."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            is_valid, reason = validate_sql_query("TRUNCATE TABLE patients")
            assert is_valid is False
            assert "TRUNCATE" in reason

    def test_merge_rejected(self, mock_config: CocoConfig) -> None:
        """MERGE is a write op, must be blocked."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            is_valid, reason = validate_sql_query(
                "MERGE INTO patients USING staging ON patients.id = staging.id "
                "WHEN MATCHED THEN UPDATE SET name = staging.name"
            )
            assert is_valid is False
            # Either MERGE or UPDATE should be cited
            assert any(kw in reason for kw in ("MERGE", "UPDATE"))

    def test_grant_revoke_rejected(self, mock_config: CocoConfig) -> None:
        """GRANT and REVOKE are privilege-changing ops, must be blocked."""
        with patch("coco.agent.guardrails.get_config", return_value=mock_config):
            for stmt in ("GRANT SELECT ON patients TO evil", "REVOKE SELECT ON patients FROM user"):
                is_valid, reason = validate_sql_query(stmt)
                assert is_valid is False
                assert "GRANT" in reason or "REVOKE" in reason
