# Prescriptions Table Schema

## Overview
The `prescriptions` table contains all recorded medication prescriptions for patients. This is the primary source for medication therapy analysis, treatment patterns, and medication adherence studies.

## Columns

### patient_id
- **Type**: STRING
- **Description**: Foreign key linking to the `patients` table.
- **Constraints**: NOT NULL, references `patients(patient_id)`
- **Notes**: De-identified surrogate key. Use for joins with patient demographics.

### rx_date
- **Type**: DATE or TIMESTAMP
- **Description**: Date the prescription was written/issued.
- **Constraints**: NOT NULL
- **Notes**: Different from fill date. Represents when prescription was created, not when patient obtained medication.

### ndc_code
- **Type**: STRING
- **Description**: National Drug Code identifier.
- **Format**: 10-11 digit code, often represented as "XXXXX-XXXX-XX" (5-4-2) or "XXXXXX-XXXX-X" (6-4-1) format
- **Constraints**: NOT NULL
- **Notes**: Uniquely identifies drug product including strength, form, and packaging. Primary key for medication identification.

### drug_name
- **Type**: STRING
- **Description**: Brand name of the medication (if brand name available).
- **Constraints**: May be NULL
- **Notes**: Proprietary name. Examples: "Metformin HCl" (brand: "Glucophage"), "Lisinopril" (sometimes generic only).

### generic_name
- **Type**: STRING
- **Description**: FDA-standard generic name for the active ingredient(s).
- **Constraints**: NOT NULL
- **Notes**: International Nonproprietary Name (INN) standard. Examples: "metformin hydrochloride", "lisinopril".

### quantity
- **Type**: INTEGER
- **Description**: Number of medication units dispensed (tablets, capsules, mL, etc.).
- **Constraints**: NOT NULL, > 0
- **Notes**: Depends on form; 30 tablets, 1 vial, etc. Combined with `days_supply` to calculate daily dose.

### days_supply
- **Type**: INTEGER
- **Description**: Number of days the prescription was written to cover.
- **Constraints**: NOT NULL, > 0
- **Examples**: 30, 60, 90 (common for maintenance medications)
- **Notes**: Used to calculate adherence and refill frequency. Critical for lines of therapy analysis.

### refills
- **Type**: INTEGER
- **Description**: Number of additional fills authorized on the original prescription.
- **Constraints**: >= 0 (0 means no refills)
- **Examples**: 0, 11 (typical for monthly fills = 12 months supply authorized)
- **Notes**: Indicates expected duration of therapy. NULL may mean unlimited or data not captured.

### prescriber_id
- **Type**: STRING
- **Description**: De-identified identifier for the healthcare provider who wrote the prescription.
- **Constraints**: May be NULL (e.g., from pharmacy claims without prescriber detail)
- **Notes**: Links to provider master if available. Useful for identifying prescribing patterns.

## NDC Code Format

National Drug Code (NDC) is the unique identifier assigned by the FDA to all drugs approved for human use in the United States.

### Standard Format
NDC codes are typically 10 digits in the format:
- **XXXXX-XXXX-XX** (5-4-2): Labeler-Product-Package Size
- **XXXXXX-XXXX-X** (6-4-1): Alternative labeler encoding
- **XXXX-XXXX-XX** (4-4-2): Older 10-digit format

### Example NDC Codes
```
00069-0147-50  Metformin HCl 500mg tablet (Merck)
00781-1503-01  Lisinopril 10mg tablet (Sandoz)
25000-0001-30  Metformin generic (various manufacturers)
```

### Validation
- NDC with leading zeros: Ensure consistent formatting (may appear as "00069-0147-50" or "69-147-50")
- 9-digit codes: Some systems strip leading zeros; standardize to 10-digit format
- Invalid codes: Flag NDCs not in FDA database; may indicate data quality issues

## Data Quality Notes

1. **Fill Date vs. Prescription Date**: This table contains `rx_date` (written). For claims analysis, you may need fill_date from claims data.
2. **Generic vs. Brand**: Always use `generic_name` for therapeutic comparison, as patients may switch between manufacturers.
3. **Strength and Form**: Not explicitly in this schema; derive from NDC code via lookup table.
4. **Duplicate Records**: Same prescription may appear multiple times if filled at different pharmacies or if system has data duplication.
5. **Over-the-Counter (OTC)**: Some systems may include OTC medications; others exclude them. Clarify in your analysis.

## Common Query Patterns

### Medications by Patient
```sql
SELECT 
  p.patient_id,
  rx.generic_name,
  rx.ndc_code,
  rx.rx_date,
  rx.days_supply,
  rx.quantity
FROM patients p
JOIN prescriptions rx ON p.patient_id = rx.patient_id
WHERE p.patient_id = 'P000001'
ORDER BY rx.rx_date DESC
```

### Active Medications at a Date (30-day lookback)
```sql
SELECT 
  rx.patient_id,
  rx.generic_name,
  rx.rx_date,
  rx.days_supply,
  DATE_ADD(rx.rx_date, rx.days_supply) as coverage_end_date
FROM prescriptions rx
WHERE rx.rx_date >= DATE_SUB('2024-01-01', 30)
  AND rx.rx_date <= '2024-01-01'
  AND DATE_ADD(rx.rx_date, rx.days_supply) >= '2024-01-01'
```

### Drug Class Prevalence (using generic_name patterns)
```sql
SELECT 
  CASE 
    WHEN rx.generic_name LIKE '%metformin%' THEN 'Biguanides'
    WHEN rx.generic_name LIKE '%lisinopril%' THEN 'ACE Inhibitors'
    WHEN rx.generic_name LIKE '%atorvastatin%' THEN 'Statins'
    ELSE 'Other'
  END as drug_class,
  COUNT(DISTINCT rx.patient_id) as patient_count
FROM prescriptions rx
WHERE rx.rx_date >= '2023-01-01'
GROUP BY drug_class
ORDER BY patient_count DESC
```

### Lines of Therapy (Sequential Medications)
```sql
WITH ranked_drugs AS (
  SELECT
    patient_id,
    generic_name,
    rx_date,
    RANK() OVER (PARTITION BY patient_id, generic_name ORDER BY rx_date) as prescription_number,
    LAG(generic_name) OVER (PARTITION BY patient_id ORDER BY rx_date) as previous_drug
  FROM prescriptions
  WHERE generic_name IN ('metformin', 'sitagliptin', 'insulin')
)
SELECT
  patient_id,
  previous_drug,
  generic_name as current_drug,
  COUNT(*) as transitions
FROM ranked_drugs
WHERE previous_drug IS NOT NULL AND previous_drug != generic_name
GROUP BY patient_id, previous_drug, generic_name
```

### Medication Adherence (using days_supply)
```sql
SELECT
  rx.patient_id,
  rx.generic_name,
  COUNT(*) as fill_count,
  SUM(rx.days_supply) as total_days_supply,
  MAX(rx.rx_date) - MIN(rx.rx_date) as days_spanned,
  ROUND(SUM(rx.days_supply) / (MAX(rx.rx_date) - MIN(rx.rx_date)) * 100, 2) as medication_possession_ratio
FROM prescriptions rx
WHERE rx.rx_date BETWEEN '2023-01-01' AND '2023-12-31'
GROUP BY rx.patient_id, rx.generic_name
HAVING COUNT(*) > 1
ORDER BY medication_possession_ratio DESC
```

### Polypharmacy Analysis
```sql
SELECT
  rx.patient_id,
  COUNT(DISTINCT rx.generic_name) as unique_medications,
  STRING_AGG(DISTINCT rx.generic_name, ', ' ORDER BY rx.generic_name) as medication_list
FROM prescriptions rx
WHERE rx.rx_date >= DATE_SUB(CURRENT_DATE(), 90)
GROUP BY rx.patient_id
HAVING COUNT(DISTINCT rx.generic_name) >= 5
ORDER BY unique_medications DESC
```

## Example Records

```
patient_id | rx_date    | ndc_code      | drug_name        | generic_name              | quantity | days_supply | refills | prescriber_id
-----------|------------|---------------|------------------|---------------------------|----------|-------------|---------|---------------
P000001    | 2024-01-15 | 00069-0147-50 | Glucophage       | metformin hydrochloride   | 30       | 30          | 11      | PRV000123
P000001    | 2024-01-15 | 25000-0001-30 | (generic)        | lisinopril                | 30       | 30          | 11      | PRV000123
P000002    | 2023-12-20 | 00781-1503-01 | Prinivil         | lisinopril                | 30       | 30          | 3       | PRV000456
P000003    | 2024-02-01 | 75014-0501-01 | Zoloft           | sertraline hydrochloride  | 30       | 30          | 11      | PRV000789
```

## Performance Considerations

- Index on `patient_id` for patient-based queries
- Index on `ndc_code` for medication lookups
- Index on `rx_date` for temporal queries
- Composite index on `(patient_id, rx_date)` for common lookups
- Partition by `rx_date` (year/month) for very large datasets

## Drug Classification Resources

- **RxNorm**: Normalized naming system for drugs (www.nlm.nih.gov/research/umls/rxnorm)
- **ChEBI**: Chemical Entities of Biological Interest (database for molecular entities)
- **DrugBank**: Comprehensive drug database with detailed information
- **FDA Orange Book**: Approved drugs and generic names

## Related Tables

- `patients`: Patient demographics via `patient_id`
- `diagnoses`: Clinical conditions treated with medications (correlative)
- `claims`: Medication claims with pricing information
- `procedures`: May have medications administered during procedures
