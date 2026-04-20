# Diagnoses Table Schema

## Overview
The `diagnoses` table contains all recorded diagnoses for patients, coded using the International Classification of Diseases, 10th Revision, Clinical Modification (ICD-10-CM). This table is central to condition-based cohort identification.

## Columns

### patient_id
- **Type**: STRING
- **Description**: Foreign key linking to the `patients` table.
- **Constraints**: NOT NULL, references `patients(patient_id)`
- **Notes**: De-identified surrogate key.

### diagnosis_date
- **Type**: DATE or TIMESTAMP
- **Description**: Date the diagnosis was recorded in the medical record.
- **Constraints**: NOT NULL
- **Notes**: Typically the date of the encounter when diagnosis was documented. May differ from onset date.

### icd10_code
- **Type**: STRING
- **Description**: ICD-10-CM diagnosis code.
- **Format**: 3-7 character alphanumeric (e.g., "E11.9", "I10", "M79.3")
- **Constraints**: NOT NULL
- **Notes**: Includes decimal point after the 3rd character per ICD-10-CM standard. Check for validity against official CMS code set.

### icd10_description
- **Type**: STRING
- **Description**: Plain-English description of the ICD-10 code.
- **Constraints**: NOT NULL
- **Notes**: Populated from official ICD-10-CM code mapping. Helpful for readability and validation.

### diagnosis_type
- **Type**: STRING
- **Description**: Classification of the diagnosis from the medical record perspective.
- **Valid Values**: 
  - "Encounter Diagnosis": Diagnosis made during the visit/encounter
  - "Secondary Diagnosis": Comorbidity or additional diagnosis
  - "POA (Present on Admission)": Diagnosis present at time of hospital admission
  - "Active": Ongoing chronic condition
  - "Historical": Past medical history
  - "Suspected": Rule-out diagnosis
- **Constraints**: NOT NULL
- **Notes**: Critical for distinguishing incident diagnoses from pre-existing conditions.

### provider_id
- **Type**: STRING
- **Description**: De-identified identifier for the provider who documented the diagnosis.
- **Constraints**: May be NULL (e.g., for claims-based diagnoses without specific provider)
- **Notes**: Links to provider master data if needed. Useful for understanding diagnosis source.

## ICD-10-CM Code Format

ICD-10-CM codes are 3-7 characters long with specific structure:

### Structure
- **Characters 1-3**: Diagnosis category (always 1 letter + 2 digits, e.g., "E11", "I10", "M79")
- **Character 4**: Subcategory (digit or X for extension, added after decimal)
- **Characters 5-7**: Additional specificity and laterality

### Examples
```
E11.9           Type 2 diabetes mellitus without complications
E11.22          Type 2 diabetes with diabetic chronic kidney disease with stage 2 or stage 3 CKD
I10             Essential (primary) hypertension
F41.1           Generalized anxiety disorder
M79.3           Panniculitis, unspecified
M79.32          Panniculitis, unspecified, left upper limb
```

### Important Patterns
- Codes ending in ".9" are "unspecified" versions (less specific)
- Codes with specific laterality (right/left/bilateral) are more specific
- Codes with complication status are more specific than those without
- "X" is often a placeholder to allow additional characters for specificity

## Data Quality and Validation

### Common Issues
1. **Truncated codes**: Some systems record "E11" instead of "E11.9" (unspecified). Standardize if analyzing.
2. **Legacy ICD-9 codes**: Confirm no ICD-9 codes exist (3-5 characters without decimal). Convert if found.
3. **Invalid codes**: Validate against current CMS code set; payers sometimes use non-standard codes.
4. **Duplicate diagnoses**: Same diagnosis may appear multiple times on same date (EHR data quality). Consider de-duplication.

## Common Query Patterns

### Patients with Specific Condition
```sql
SELECT DISTINCT p.patient_id, p.age, p.gender
FROM patients p
JOIN diagnoses d ON p.patient_id = d.patient_id
WHERE d.icd10_code = 'E11.9'  -- Type 2 diabetes
  AND d.diagnosis_date >= '2023-01-01'
  AND p.enrollment_start <= '2023-01-01'
```

### Condition Prevalence
```sql
SELECT 
  d.icd10_code, 
  d.icd10_description,
  COUNT(DISTINCT d.patient_id) as patient_count,
  COUNT(*) as diagnosis_records
FROM diagnoses d
WHERE d.diagnosis_date >= DATE_SUB(CURRENT_DATE(), 365)
GROUP BY d.icd10_code, d.icd10_description
ORDER BY patient_count DESC
LIMIT 20
```

### Comorbidity Analysis (Conditions in Same Patient)
```sql
SELECT DISTINCT
  d1.icd10_code as condition_1,
  d1.icd10_description as condition_1_desc,
  d2.icd10_code as condition_2,
  d2.icd10_description as condition_2_desc,
  COUNT(DISTINCT d1.patient_id) as patient_count
FROM diagnoses d1
JOIN diagnoses d2 ON d1.patient_id = d2.patient_id
WHERE d1.icd10_code = 'E11.9'  -- Type 2 diabetes
  AND d1.diagnosis_date >= '2023-01-01'
  AND d2.diagnosis_date >= '2023-01-01'
  AND d1.icd10_code < d2.icd10_code  -- Avoid duplicates
GROUP BY d1.icd10_code, d1.icd10_description, d2.icd10_code, d2.icd10_description
ORDER BY patient_count DESC
```

### Diagnosis Timeline (Incident Conditions)
```sql
SELECT 
  d.patient_id,
  d.diagnosis_date,
  d.icd10_code,
  d.icd10_description,
  d.diagnosis_type
FROM diagnoses d
JOIN patients p ON d.patient_id = p.patient_id
WHERE d.icd10_code LIKE 'I10%'  -- Hypertension codes
  AND d.diagnosis_date >= p.enrollment_start
  AND d.diagnosis_date = (
    SELECT MIN(d2.diagnosis_date)
    FROM diagnoses d2
    WHERE d2.patient_id = d.patient_id
      AND d2.icd10_code LIKE 'I10%'
  )
ORDER BY d.diagnosis_date
```

### Diagnosis Clustering (ICD-10 Category)
```sql
SELECT 
  SUBSTRING(d.icd10_code, 1, 3) as icd10_category,
  COUNT(DISTINCT d.patient_id) as unique_patients
FROM diagnoses d
WHERE d.diagnosis_date >= '2023-01-01'
GROUP BY SUBSTRING(d.icd10_code, 1, 3)
ORDER BY unique_patients DESC
```

## Example Records

```
patient_id | diagnosis_date | icd10_code | icd10_description                     | diagnosis_type       | provider_id
-----------|----------------|------------|---------------------------------------|----------------------|------------
P000001    | 2023-05-12     | E11.9      | Type 2 diabetes mellitus NOS          | Active               | PRV000123
P000001    | 2023-05-12     | I10        | Essential hypertension                | Active               | PRV000123
P000002    | 2023-06-01     | E11.22     | T2DM w/ diabetic CKD, stage 3 CKD    | Encounter Diagnosis  | PRV000456
P000003    | 2023-04-15     | F41.1      | Generalized anxiety disorder          | Active               | PRV000789
P000001    | 2023-09-20     | E11.65     | T2DM w/ hypoglycemia with coma       | Historical           | PRV000123
```

## Performance Considerations

- Index on `patient_id` for joins with patients table
- Index on `icd10_code` for condition lookups
- Index on `diagnosis_date` for temporal queries
- Consider composite index on `(patient_id, diagnosis_date)` for common queries
- Partition by `diagnosis_date` (year or quarter) for large datasets

## ICD-10-CM Reference Resources

- **CMS ICD-10-CM Code Descriptions**: Available at https://www.cms.gov/Medicare/Coding/ICD10
- **Elixhauser Comorbidity Software**: Maps ICD-10 codes to comorbidity categories
- **AHRQ Comorbidity Software**: Clinical classification for outcomes research

## Related Tables

- `patients`: Patient demographics via `patient_id`
- `procedures`: May have related diagnosis on same encounter date
- `prescriptions`: May correlate with diagnoses (treatment patterns)
- `claims`: Diagnoses associated with healthcare claims
