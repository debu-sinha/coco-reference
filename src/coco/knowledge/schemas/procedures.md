# Procedures Table Schema

## Overview
The `procedures` table contains all recorded medical procedures for patients, coded using Current Procedural Terminology (CPT) codes. This table is essential for understanding treatments, interventions, and healthcare utilization patterns.

## Columns

### patient_id
- **Type**: STRING
- **Description**: Foreign key linking to the `patients` table.
- **Constraints**: NOT NULL, references `patients(patient_id)`
- **Notes**: De-identified surrogate key. Use for joins with patient demographics.

### procedure_date
- **Type**: DATE or TIMESTAMP
- **Description**: Date the procedure was performed.
- **Constraints**: NOT NULL
- **Notes**: The actual service date. Critical for temporal analysis and procedure sequencing.

### cpt_code
- **Type**: STRING
- **Description**: Current Procedural Terminology code.
- **Format**: 5-digit numeric code (e.g., "99213", "70450", "27447")
- **Constraints**: NOT NULL
- **Notes**: Uniquely identifies the type of procedure. Some codes include modifiers (e.g., "27447-LT" for left side).

### cpt_description
- **Type**: STRING
- **Description**: Plain-English description of the CPT code.
- **Constraints**: NOT NULL
- **Notes**: Populated from official AMA CPT codebook. Helpful for validation and readability.

### provider_id
- **Type**: STRING
- **Description**: De-identified identifier for the healthcare provider who performed the procedure.
- **Constraints**: May be NULL
- **Notes**: Links to provider master if available. Useful for identifying surgical teams or specialists.

### facility_id
- **Type**: STRING
- **Description**: De-identified identifier for the healthcare facility where procedure was performed.
- **Constraints**: May be NULL
- **Notes**: Links to facility master. Useful for facility-level analysis and surgical center comparisons.

## CPT Code Format and Categories

CPT codes are 5-digit codes used to identify medical services and procedures. They're maintained by the American Medical Association (AMA).

### Code Categories

#### Evaluation and Management (E/M) Codes: 99000-99607
- Office visits, consultations, hospital visits
- **Examples**: 
  - `99213` - Office visit, established patient, low complexity
  - `99385` - Preventive medicine visit, established patient, age 18-39

#### Anesthesia Codes: 00000-01999
- Anesthesia services for procedures
- **Examples**:
  - `00100` - Anesthesia for minor procedures on integumentary system
  - `01232` - Anesthesia for hip arthroplasty

#### Surgery Codes: 10000-69999
- Surgical procedures organized by body system
- **Examples**:
  - `27447` - Total knee arthroplasty
  - `33510` - Coronary artery bypass graft (CABG)
  - `70450` - Head CT with and without contrast

#### Pathology/Laboratory: 80000-89999
- Lab tests, blood work, pathology services
- **Examples**:
  - `80053` - Comprehensive metabolic panel
  - `85025` - Complete blood count with differential

#### Medicine/Diagnostic Services: 90000-99199
- Non-surgical procedures, imaging, diagnostics
- **Examples**:
  - `93000` - Electrocardiogram (ECG)
  - `76700` - Abdominal ultrasound

### CPT Modifiers

Modifiers are 2-character additions to CPT codes that describe circumstances affecting the procedure:
- `-LT` (Left side), `-RT` (Right side), `-50` (Bilateral)
- `-26` (Professional component only), `-TC` (Technical component only)
- `-59` (Distinct procedural service)
- **Example**: `27447-LT` = Total knee arthroplasty, left side

## Data Quality Considerations

1. **Modifier Handling**: Some systems include modifiers in `cpt_code`; others in separate fields. Check for "-LT", "-RT", "-50" suffixes.
2. **Bundled Codes**: Higher-level codes sometimes include smaller procedures. Avoid double-counting when analyzing procedure patterns.
3. **Missing Facilities**: May be NULL for office-based or outpatient procedures. Don't assume missing facility means ambulatory.
4. **Valid Code Check**: Validate CPT codes against current AMA database. Legacy codes may appear in historical data.
5. **RVU (Relative Value Unit)**: Not in this schema, but needed for cost analysis. Join with RVU master data if cost analysis required.

## Common Query Patterns

### All Procedures for a Patient
```sql
SELECT 
  p.patient_id,
  pr.procedure_date,
  pr.cpt_code,
  pr.cpt_description,
  pr.facility_id
FROM patients p
JOIN procedures pr ON p.patient_id = pr.patient_id
WHERE p.patient_id = 'P000001'
ORDER BY pr.procedure_date DESC
```

### Procedure Prevalence
```sql
SELECT 
  pr.cpt_code,
  pr.cpt_description,
  COUNT(DISTINCT pr.patient_id) as patient_count,
  COUNT(*) as procedure_count
FROM procedures pr
WHERE pr.procedure_date >= '2023-01-01'
GROUP BY pr.cpt_code, pr.cpt_description
ORDER BY patient_count DESC
LIMIT 30
```

### Surgical Procedures Only (CPT range 10000-69999)
```sql
SELECT 
  pr.patient_id,
  pr.procedure_date,
  pr.cpt_code,
  pr.cpt_description,
  pr.facility_id
FROM procedures pr
WHERE CAST(pr.cpt_code AS INTEGER) BETWEEN 10000 AND 69999
  AND pr.procedure_date >= '2023-01-01'
ORDER BY pr.patient_id, pr.procedure_date
```

### Procedure Sequences (surgical progression)
```sql
WITH procedures_ranked AS (
  SELECT
    patient_id,
    procedure_date,
    cpt_code,
    cpt_description,
    ROW_NUMBER() OVER (PARTITION BY patient_id ORDER BY procedure_date) as procedure_order,
    LAG(cpt_code) OVER (PARTITION BY patient_id ORDER BY procedure_date) as prior_procedure
  FROM procedures
  WHERE procedure_date >= '2023-01-01'
)
SELECT
  patient_id,
  prior_procedure,
  cpt_code as current_procedure,
  COUNT(*) as transition_count
FROM procedures_ranked
WHERE procedure_order > 1 AND prior_procedure IS NOT NULL
GROUP BY patient_id, prior_procedure, cpt_code
ORDER BY transition_count DESC
```

### Procedures Within N Days of Diagnosis
```sql
SELECT 
  pr.patient_id,
  d.diagnosis_date,
  d.icd10_code,
  pr.procedure_date,
  pr.cpt_code,
  pr.cpt_description,
  DATEDIFF(pr.procedure_date, d.diagnosis_date) as days_after_diagnosis
FROM diagnoses d
JOIN procedures pr ON d.patient_id = pr.patient_id
WHERE d.icd10_code LIKE 'E11%'  -- Type 2 diabetes
  AND d.diagnosis_date >= '2023-01-01'
  AND pr.procedure_date BETWEEN d.diagnosis_date AND DATE_ADD(d.diagnosis_date, 90)
ORDER BY d.patient_id, d.diagnosis_date, pr.procedure_date
```

### Facility-Level Procedure Comparison
```sql
SELECT 
  pr.facility_id,
  pr.cpt_code,
  pr.cpt_description,
  COUNT(DISTINCT pr.patient_id) as patient_count,
  COUNT(*) as procedure_count,
  ROUND(COUNT(*) / COUNT(DISTINCT pr.patient_id), 2) as avg_procedures_per_patient
FROM procedures pr
WHERE pr.procedure_date >= '2023-01-01'
  AND pr.facility_id IS NOT NULL
GROUP BY pr.facility_id, pr.cpt_code, pr.cpt_description
HAVING COUNT(DISTINCT pr.patient_id) >= 10
ORDER BY pr.facility_id, procedure_count DESC
```

### E/M Visit Frequency
```sql
SELECT
  pr.patient_id,
  YEAR(pr.procedure_date) as visit_year,
  COUNT(*) as visit_count
FROM procedures pr
WHERE CAST(pr.cpt_code AS INTEGER) BETWEEN 99200 AND 99499  -- E/M codes
  AND pr.procedure_date >= '2023-01-01'
GROUP BY pr.patient_id, YEAR(pr.procedure_date)
ORDER BY pr.patient_id, visit_year
```

## Example Records

```
patient_id | procedure_date | cpt_code | cpt_description                    | provider_id | facility_id
-----------|----------------|----------|------------------------------------|-----------  |------------
P000001    | 2024-01-15     | 99213    | Office visit, established, moderate| PRV000123   | FAC000456
P000002    | 2023-12-20     | 27447    | Total knee arthroplasty, left      | PRV000789   | FAC000789
P000001    | 2023-06-01     | 93000    | Electrocardiogram                  | PRV000123   | NULL
P000003    | 2024-02-10     | 80053    | Comprehensive metabolic panel      | PRV000456   | LAB000001
P000002    | 2023-11-05     | 70450    | Head CT with and without contrast  | PRV001001   | FAC000123
```

## Performance Considerations

- Index on `patient_id` for patient-based lookups
- Index on `cpt_code` for procedure lookups
- Index on `procedure_date` for temporal queries
- Composite index on `(patient_id, procedure_date)` for sequential analysis
- Partition by `procedure_date` (year) for very large datasets

## CPT Code Resources

- **AMA CPT Codebook**: Official source (published annually)
- **CMS CPT Code Lookup**: https://www.cms.gov/Medicare/Coding/CPT
- **Optum/UnitedHealth RVU Files**: Relative value units for cost estimation
- **Crosswalk Tools**: ICD-10 to CPT and CPT to revenue code mappings

## Related Tables

- `patients`: Patient demographics via `patient_id`
- `diagnoses`: Clinical conditions treated with procedures (temporal correlation)
- `claims`: Claims data with pricing and allowed amounts
- `prescriptions`: Medications prescribed during or after procedures
