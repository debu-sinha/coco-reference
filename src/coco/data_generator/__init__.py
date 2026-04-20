"""
Synthetic RWD (Real-World Data) generator for CoCo Agent.

This package generates realistic, de-identified healthcare data suitable for
testing and development in any Databricks workspace without privacy concerns.

Modules:
    clinical_codes: Reference data for medical coding systems (ICD-10, NDC, CPT, LOINC)
    generate: Core data generation functions for patients, diagnoses, prescriptions, etc.
    spark_writer: Utilities to write generated data to Unity Catalog Delta tables

Example:
    >>> from coco.data_generator.generate import generate_all_tables
    >>> tables = generate_all_tables(num_patients=10000, seed=42)
    >>> print(tables.keys())
    dict_keys(['patients', 'diagnoses', 'prescriptions', 'procedures', 'claims', 'suppliers'])
"""

__version__ = "1.0.0"
__author__ = "CoCo Team"

from coco.data_generator.generate import generate_all_tables

__all__ = ["generate_all_tables"]
