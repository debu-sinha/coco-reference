# Patients Table Schema

## Overview
The `patients` table contains demographic and enrollment information for all patients in the cohort analysis system. This is the foundational table that connects to all clinical and claims data.

## Columns

### patient_id
- **Type**: STRING
- **Description**: Unique identifier for each patient. De-identified surrogate key.
- **Constraints**: Primary key, NOT NULL
- **Notes**: Never contains PHI. Safe to use in all contexts.

### age
- **Type**: INTEGER
- **Description**: Patient's age in years at the index date (or at enrollment start).
- **Range**: 0-120
- **Constraints**: NOT NULL, >= 0
- **Notes**: Recalculated based on data reference date. Use for age-based cohort filtering.

### gender
- **Type**: STRING
- **Description**: Patient's biological sex at birth.
- **Valid Values**: "M" (Male), "F" (Female), "U" (Unknown)
- **Constraints**: NOT NULL
- **Notes**: Not the same as gender identity. Standard for clinical analysis.

### race
- **Type**: STRING
- **Description**: Patient's race as reported in EHR system.
- **Valid Values**: "White", "Black", "Asian", "Native American", "Pacific Islander", "Unknown", "Other"
- **Constraints**: NOT NULL
- **Notes**: Used for health equity analysis. May be incomplete in data.

### ethnicity
- **Type**: STRING
- **Description**: Patient's ethnicity (primarily used for Hispanic/Latino classification).
- **Valid Values**: "Hispanic", "Non-Hispanic", "Unknown"
- **Constraints**: NOT NULL
- **Notes**: Independent of race field. Census Bureau standard.

### state
- **Type**: STRING
- **Description**: Two-letter state abbreviation where patient resides.
- **Format**: Upper case, standard USPS abbreviations (e.g., "CA", "NY")
- **Constraints**: NOT NULL, 2 characters
- **Notes**: Used for geographic segmentation and compliance checks.

### zip_code
- **Type**: STRING
- **Description**: Patient's postal code (5-digit format, or ZIP+4 where available).
- **Format**: Typically "12345" format, may contain "+4" extension
- **Constraints**: NOT NULL
- **Notes**: Can be used for geographic analysis and SES proxies (Area Deprivation Index).

### enrollment_start
- **Type**: DATE or TIMESTAMP
- **Description**: Date when patient's continuous enrollment period began.
- **Constraints**: NOT NULL
- **Notes**: Use for temporal filtering. Marks when patient became eligible for observation.

### enrollment_end
- **Type**: DATE or TIMESTAMP
- **Description**: Date when patient's continuous enrollment period ended.
- **Constraints**: May be NULL (ongoing enrollment)
- **Notes**: If NULL, assume continuous enrollment to present. Use for active patient lists.

### payer_type
- **Type**: STRING
- **Description**: Type of insurance payer or coverage.
- **Valid Values**: "Commercial", "Medicare", "Medicaid", "Military", "Self-Pay", "Unknown"
- **Constraints**: NOT NULL
- **Notes**: Important for compliance analysis and cost metrics interpretation.

## Data Quality Notes

1. **De-identification**: All personally identifiable information (name, SSN, medical record number) removed. Safe for analysis.
2. **Temporal Validity**: Always filter by `enrollment_start` and `enrollment_end` to ensure continuous enrollment during analysis window.
3. **Age Accuracy**: Age is calculated; be aware of potential mismatches if data source updates birthdate retroactively.
4. **Race/Ethnicity**: Data completeness varies. "Unknown" may represent missing data or patient choice.

## Common Query Patterns

### Active Patients at a Date
```sql
SELECT patient_id 
FROM patients 
WHERE enrollment_start <= '2024-01-01' 
  AND (enrollment_end IS NULL OR enrollment_end >= '2024-01-01')
```

### Age-Based Cohort
```sql
SELECT patient_id, age 
FROM patients 
WHERE age >= 65 AND age <= 75
  AND enrollment_start <= '2024-01-01'
  AND (enrollment_end IS NULL OR enrollment_end >= '2024-12-31')
```

### Geographic Analysis
```sql
SELECT state, COUNT(*) as patient_count 
FROM patients 
GROUP BY state
HAVING COUNT(*) > 100
```

### Demographic Breakdown
```sql
SELECT gender, race, ethnicity, COUNT(*) as count
FROM patients
GROUP BY gender, race, ethnicity
ORDER BY count DESC
```

## Example Records

```
patient_id | age | gender | race       | ethnicity     | state | zip_code | enrollment_start | enrollment_end | payer_type
-----------|-----|--------|------------|---------------|-------|----------|------------------|----------------|------------
P000001    | 45  | M      | White      | Non-Hispanic  | CA    | 90210    | 2020-01-15       | NULL           | Commercial
P000002    | 72  | F      | Black      | Non-Hispanic  | NY    | 10001    | 2019-03-22       | 2024-06-30     | Medicare
P000003    | 28  | F      | Asian      | Non-Hispanic  | WA    | 98101    | 2021-06-01       | NULL           | Commercial
```

## Performance Considerations

- Index on `patient_id` (automatic as PK)
- Index on `enrollment_start`, `enrollment_end` for temporal queries
- Consider partitioning by `state` or `payer_type` for large datasets
- Clustering by `enrollment_start` improves time-range queries

## Related Tables

- `diagnoses`: Patient clinical conditions via `patient_id` foreign key
- `prescriptions`: Medication history via `patient_id` foreign key
- `procedures`: Procedural records via `patient_id` foreign key
- `claims`: Claims data via `patient_id` foreign key
