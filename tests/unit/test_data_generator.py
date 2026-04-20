"""Tests for synthetic data generation.

Exercises the module-level function API in coco.data_generator.generate.
The generator exposes generate_patients / generate_all_tables / ... as
top-level functions (not a class), so the tests call them directly.
"""

import pytest

from coco.data_generator.generate import (
    generate_all_tables,
    generate_patients,
)

EXPECTED_TABLES = {
    "patients",
    "diagnoses",
    "prescriptions",
    "procedures",
    "claims",
    "suppliers",
}

REQUIRED_PATIENT_FIELDS = {
    "patient_id",
    "age",
    "gender",
    "race",
    "state",
    "zip_code",
    "enrollment_start",
    "payer_type",
}


@pytest.mark.unit
class TestGeneratePatients:
    """Basic patient generation."""

    def test_count_matches_requested(self) -> None:
        patients = generate_patients(num_patients=100, seed=42)
        assert len(patients) == 100

    def test_required_fields_present(self) -> None:
        patients = generate_patients(num_patients=10, seed=42)
        assert REQUIRED_PATIENT_FIELDS.issubset(patients[0].keys())

    def test_patient_id_is_unique(self) -> None:
        patients = generate_patients(num_patients=50, seed=42)
        ids = [p["patient_id"] for p in patients]
        assert len(set(ids)) == len(ids)

    def test_age_in_adult_range(self) -> None:
        patients = generate_patients(num_patients=100, seed=42)
        ages = [p["age"] for p in patients]
        assert all(18 <= a <= 99 for a in ages)


@pytest.mark.unit
class TestGenerateAllTables:
    """End-to-end orchestrator."""

    def test_returns_all_expected_tables(self) -> None:
        tables = generate_all_tables(
            num_patients=50,
            num_suppliers=5,
            seed=42,
            start_date="2020-01-01",
            end_date="2025-12-31",
        )
        assert set(tables.keys()) == EXPECTED_TABLES

    def test_patients_table_has_requested_count(self) -> None:
        tables = generate_all_tables(
            num_patients=75,
            num_suppliers=5,
            seed=42,
            start_date="2020-01-01",
            end_date="2025-12-31",
        )
        assert len(tables["patients"]) == 75

    def test_suppliers_table_has_requested_count(self) -> None:
        tables = generate_all_tables(
            num_patients=50,
            num_suppliers=7,
            seed=42,
            start_date="2020-01-01",
            end_date="2025-12-31",
        )
        assert len(tables["suppliers"]) == 7

    def test_diagnoses_non_empty_with_realistic_patients(self) -> None:
        tables = generate_all_tables(
            num_patients=100,
            num_suppliers=5,
            seed=42,
            start_date="2020-01-01",
            end_date="2025-12-31",
        )
        assert len(tables["diagnoses"]) > 0
        diag = tables["diagnoses"][0]
        assert "patient_id" in diag
        assert "icd10_code" in diag


@pytest.mark.unit
class TestDeterminism:
    """Seed reproducibility."""

    def test_same_seed_produces_same_patient_ids(self) -> None:
        a = generate_patients(num_patients=50, seed=42)
        b = generate_patients(num_patients=50, seed=42)
        assert [p["patient_id"] for p in a] == [p["patient_id"] for p in b]

    def test_different_seeds_diverge(self) -> None:
        a = generate_patients(num_patients=50, seed=42)
        b = generate_patients(num_patients=50, seed=123)
        a_ids = [p["patient_id"] for p in a]
        b_ids = [p["patient_id"] for p in b]
        assert a_ids != b_ids
