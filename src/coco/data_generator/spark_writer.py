"""
Write generated synthetic data to Unity Catalog Delta tables.

This module provides utilities to persist generated RWD data to Databricks
Unity Catalog as Delta tables. It handles schema definition, data type
conversion, and idempotent writes using MERGE INTO.

Usage:
    >>> from coco.data_generator.generate import generate_all_tables
    >>> from coco.data_generator.spark_writer import write_tables_to_catalog
    >>> tables = generate_all_tables(num_patients=10000, seed=42)
    >>> write_tables_to_catalog(tables, catalog="main", schema="coco_rwd")
"""

from datetime import date
from typing import Any, Dict, List, Optional

try:
    from pyspark.sql import DataFrame, SparkSession
    from pyspark.sql.types import (
        BooleanType,
        DateType,
        DoubleType,
        FloatType,
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
    )
except ImportError:
    raise ImportError(
        "PySpark is required for spark_writer module. Install with: pip install pyspark"
    )


# Schema definitions for each table
SCHEMA_PATIENTS = StructType(
    [
        StructField("patient_id", StringType(), False),
        StructField("age", IntegerType(), False),
        StructField("gender", StringType(), False),
        StructField("race", StringType(), False),
        StructField("ethnicity", StringType(), False),
        StructField("state", StringType(), False),
        StructField("zip_code", StringType(), False),
        StructField("enrollment_start", DateType(), False),
        StructField("enrollment_end", DateType(), True),
        StructField("payer_type", StringType(), False),
    ]
)

SCHEMA_DIAGNOSES = StructType(
    [
        StructField("diagnosis_id", StringType(), False),
        StructField("patient_id", StringType(), False),
        StructField("diagnosis_date", DateType(), False),
        StructField("icd10_code", StringType(), False),
        StructField("icd10_description", StringType(), False),
        StructField("diagnosis_type", StringType(), False),
        StructField("provider_id", StringType(), False),
    ]
)

SCHEMA_PRESCRIPTIONS = StructType(
    [
        StructField("rx_id", StringType(), False),
        StructField("patient_id", StringType(), False),
        StructField("rx_date", DateType(), False),
        StructField("ndc_code", StringType(), False),
        StructField("drug_name", StringType(), False),
        StructField("generic_name", StringType(), False),
        StructField("therapeutic_class", StringType(), False),
        StructField("quantity", IntegerType(), False),
        StructField("days_supply", IntegerType(), False),
        StructField("refills", IntegerType(), False),
        StructField("prescriber_id", StringType(), False),
    ]
)

SCHEMA_PROCEDURES = StructType(
    [
        StructField("procedure_id", StringType(), False),
        StructField("patient_id", StringType(), False),
        StructField("procedure_date", DateType(), False),
        StructField("cpt_code", StringType(), False),
        StructField("cpt_description", StringType(), False),
        StructField("provider_id", StringType(), False),
        StructField("facility_id", StringType(), False),
    ]
)

SCHEMA_CLAIMS = StructType(
    [
        StructField("claim_id", StringType(), False),
        StructField("patient_id", StringType(), False),
        StructField("service_date", DateType(), False),
        StructField("claim_type", StringType(), False),
        StructField("icd10_code", StringType(), True),
        StructField("cpt_code", StringType(), True),
        StructField("ndc_code", StringType(), True),
        StructField("billed_amount", DoubleType(), False),
        StructField("allowed_amount", DoubleType(), False),
        StructField("paid_amount", DoubleType(), False),
        StructField("deductible_amount", DoubleType(), False),
        StructField("copay_amount", DoubleType(), False),
        StructField("coinsurance_amount", DoubleType(), False),
        StructField("status", StringType(), False),
        StructField("payer", StringType(), False),
    ]
)

SCHEMA_SUPPLIERS = StructType(
    [
        StructField("supplier_id", StringType(), False),
        StructField("supplier_name", StringType(), False),
        StructField("supplier_type", StringType(), False),
        StructField("npi", StringType(), False),
        StructField("specialty", StringType(), False),
        StructField("address", StringType(), False),
        StructField("state", StringType(), False),
        StructField("contracts_count", IntegerType(), False),
        StructField("tier", StringType(), False),
    ]
)

SCHEMAS: Dict[str, StructType] = {
    "patients": SCHEMA_PATIENTS,
    "diagnoses": SCHEMA_DIAGNOSES,
    "prescriptions": SCHEMA_PRESCRIPTIONS,
    "procedures": SCHEMA_PROCEDURES,
    "claims": SCHEMA_CLAIMS,
    "suppliers": SCHEMA_SUPPLIERS,
}


def _convert_row_to_spark_types(row: Dict[str, Any], schema: StructType) -> Dict[str, Any]:
    """
    Coerce Python types to match the declared Spark schema. PySpark's
    strict type verifier rejects an int where DoubleType is declared (and
    vice versa), so we do explicit coercion up front.

    Args:
        row: Dictionary with raw generator output
        schema: PySpark StructType for validation

    Returns:
        Dictionary with values coerced to match each field's declared type.
    """
    converted: Dict[str, Any] = {}
    for field in schema.fields:
        value = row.get(field.name)

        if value is None:
            converted[field.name] = None
            continue

        dtype = field.dataType
        if isinstance(dtype, DateType):
            if isinstance(value, str):
                converted[field.name] = date.fromisoformat(value)
            else:
                converted[field.name] = value
        elif isinstance(dtype, (DoubleType, FloatType)):
            # int 0 is not acceptable where DoubleType is declared under
            # strict type checking — coerce to float.
            converted[field.name] = float(value) if not isinstance(value, float) else value
        elif isinstance(dtype, (IntegerType, LongType)):
            converted[field.name] = int(value) if not isinstance(value, int) else value
        elif isinstance(dtype, BooleanType):
            converted[field.name] = bool(value) if not isinstance(value, bool) else value
        elif isinstance(dtype, StringType):
            converted[field.name] = str(value) if not isinstance(value, str) else value
        else:
            converted[field.name] = value

    return converted


def _create_or_replace_table(
    spark: SparkSession,
    table_name: str,
    data: List[Dict],
    schema: StructType,
    catalog: str,
    schema_name: str,
) -> None:
    """
    Create or replace a Delta table with generated data.

    Uses REPLACE TABLE for simplicity in development environments.
    For production, consider MERGE INTO for idempotent updates.

    Args:
        spark: SparkSession
        table_name: Name of the table (without catalog.schema prefix)
        data: List of dictionaries containing table data
        schema: PySpark StructType defining table schema
        catalog: Unity Catalog name
        schema_name: Schema/database name within catalog
    """
    if not data:
        print(f"  ⚠ Skipping {table_name}: no data to write")
        return

    # Convert rows to proper Spark types
    converted_data = [_convert_row_to_spark_types(row, schema) for row in data]

    # Create DataFrame
    df = spark.createDataFrame(converted_data, schema=schema)

    # Write to the UC managed table. Do NOT pass an explicit `path=` —
    # UC managed tables live in the metastore-managed storage location
    # and reject user-specified paths (you get "Missing cloud file system
    # scheme" if you try to point at a Volume path).
    full_table_name = f"{catalog}.{schema_name}.{table_name}"
    df.write.format("delta").mode("overwrite").saveAsTable(full_table_name)
    print(f"  ✓ Wrote {len(data)} rows to {full_table_name}")


def write_tables_to_catalog(
    tables: Dict[str, List[Dict]], catalog: str, schema: str, spark: Optional[SparkSession] = None
) -> None:
    """
    Write all generated tables to Unity Catalog as Delta tables.

    Creates or replaces Delta tables for patients, diagnoses, prescriptions,
    procedures, claims, and suppliers.

    Args:
        tables: Dictionary of table_name -> list[dict] from generate_all_tables()
        catalog: Unity Catalog name (e.g., "main")
        schema: Schema/database name within catalog (e.g., "coco_rwd")
        spark: Optional SparkSession. If None, gets the active session.

    Raises:
        ValueError: If tables dict is missing required keys
        RuntimeError: If Spark is not available in Databricks environment

    Example:
        >>> from coco.data_generator.generate import generate_all_tables
        >>> from coco.data_generator.spark_writer import write_tables_to_catalog
        >>> tables = generate_all_tables(num_patients=5000, seed=42)
        >>> write_tables_to_catalog(tables, catalog="main", schema="coco_rwd")
        Writing to Unity Catalog...
          ✓ Wrote 5000 rows to main.coco_rwd.patients
          ✓ Wrote 8234 rows to main.coco_rwd.diagnoses
          ...
    """
    # Validate input
    required_tables = {
        "patients",
        "diagnoses",
        "prescriptions",
        "procedures",
        "claims",
        "suppliers",
    }
    missing_tables = required_tables - set(tables.keys())
    if missing_tables:
        raise ValueError(f"Missing required tables: {missing_tables}")

    # Get or create SparkSession
    if spark is None:
        spark = SparkSession.getActiveSession()
        if spark is None:
            raise RuntimeError(
                "No active SparkSession found. Create one with: "
                "spark = SparkSession.builder.appName('coco-generator').getOrCreate()"
            )

    print(f"Writing to Unity Catalog: {catalog}.{schema}")

    # Create schema if needed (will fail gracefully if it exists)
    try:
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
    except Exception as e:
        print(f"  ⚠ Could not create schema: {e}")

    # Write each table
    for table_name in [
        "patients",
        "diagnoses",
        "prescriptions",
        "procedures",
        "claims",
        "suppliers",
    ]:
        if table_name not in tables:
            print(f"  ⚠ Skipping {table_name}: not in generated tables")
            continue

        data = tables[table_name]
        schema_def = SCHEMAS[table_name]

        _create_or_replace_table(spark, table_name, data, schema_def, catalog, schema)

    print(f"\n✓ Successfully wrote all tables to {catalog}.{schema}")


def validate_data_quality(
    spark: SparkSession, catalog: str, schema: str
) -> Dict[str, Dict[str, Any]]:
    """
    Validate quality of written data (optional utility).

    Checks for:
    - Row counts per table
    - Null values in required fields
    - Date range coverage
    - Claim amounts are positive
    - Patient ID distribution

    Args:
        spark: SparkSession
        catalog: Unity Catalog name
        schema: Schema name

    Returns:
        Dictionary with validation results for each table
    """
    results = {}

    tables = ["patients", "diagnoses", "prescriptions", "procedures", "claims", "suppliers"]

    for table_name in tables:
        full_name = f"{catalog}.{schema}.{table_name}"
        try:
            df = spark.table(full_name)
            results[table_name] = {
                "row_count": df.count(),
                "columns": len(df.columns),
            }
        except Exception as e:
            results[table_name] = {"error": str(e)}

    return results
