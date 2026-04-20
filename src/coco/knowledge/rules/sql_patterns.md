# SQL Patterns for CoCo Schema

## Foundational Concepts

### CoCo Data Model
The CoCo schema represents a longitudinal healthcare dataset with:
- **Patients table**: Demographic and enrollment foundation
- **Clinical tables**: Diagnoses, Procedures
- **Prescription table**: Medication therapy
- **Claims table**: Healthcare utilization and costs
- **Suppliers table**: Provider/facility reference data

All clinical events are linked via `patient_id` and date columns for temporal analysis.

### Key Design Principles
1. **Temporal Integrity**: Always validate enrollment periods
2. **Explicitness**: Use explicit JOINs; avoid implicit relationships
3. **De-identification**: All PHI removed; use surrogate keys confidently
4. **Aggregation Strategy**: Define measurement periods clearly before grouping

## Temporal Joins and Windows

### Checking Continuous Enrollment
Essential for cohort definition. Ensures patient was eligible for observation.

```sql
-- Check enrollment at specific date
SELECT p.patient_id, p.enrollment_start, p.enrollment_end
FROM patients p
WHERE p.enrollment_start <= '2024-01-01'
  AND (p.enrollment_end IS NULL OR p.enrollment_end >= '2024-01-01')

-- Check continuous enrollment for period
SELECT p.patient_id
FROM patients p
WHERE p.enrollment_start <= '2023-01-01'
  AND (p.enrollment_end IS NULL OR p.enrollment_end >= '2023-12-31')

-- Exclude gaps (if enrollment can span multiple records per patient)
WITH enrollment_periods AS (
  SELECT 
    patient_id, 
    enrollment_start, 
    enrollment_end,
    LEAD(enrollment_start) OVER (PARTITION BY patient_id ORDER BY enrollment_start) as next_start
  FROM patients
)
SELECT patient_id
FROM enrollment_periods
WHERE DATEDIFF(next_start, enrollment_end) <= 30  -- Allow 30-day gap tolerance
```

### Active Medications at a Point in Time
Determine which medications patient was actively taking on a specific date.

```sql
-- Simple version: medication prescribed and not yet expired
SELECT DISTINCT
  p.patient_id,
  rx.generic_name,
  rx.rx_date,
  rx.days_supply,
  DATE_ADD(rx.rx_date, rx.days_supply) as coverage_end
FROM patients p
JOIN prescriptions rx ON p.patient_id = rx.patient_id
WHERE rx.rx_date <= '2024-01-15'  -- Prescribed by target date
  AND DATE_ADD(rx.rx_date, rx.days_supply) >= '2024-01-15'  -- Still active
  AND p.enrollment_start <= '2024-01-15'
  AND (p.enrollment_end IS NULL OR p.enrollment_end >= '2024-01-15')

-- Advanced: with refill count to extend coverage
WITH medication_coverage AS (
  SELECT 
    patient_id,
    generic_name,
    rx_date,
    days_supply,
    COALESCE(refills, 0) as refill_count,
    DATE_ADD(rx_date, days_supply * (1 + COALESCE(refills, 0))) as max_coverage_date
  FROM prescriptions
)
SELECT DISTINCT
  p.patient_id,
  mc.generic_name,
  mc.rx_date,
  mc.max_coverage_date
FROM patients p
JOIN medication_coverage mc ON p.patient_id = mc.patient_id
WHERE mc.rx_date <= '2024-01-15'
  AND mc.max_coverage_date >= '2024-01-15'
```

### Time Between Events (diagnostic lookback)
Find events within N days of a reference date (e.g., procedure after diagnosis).

```sql
-- Procedures within 90 days of T2DM diagnosis
SELECT 
  p.patient_id,
  d.diagnosis_date,
  d.icd10_code,
  pr.procedure_date,
  pr.cpt_code,
  pr.cpt_description,
  DATEDIFF(pr.procedure_date, d.diagnosis_date) as days_after_diagnosis
FROM patients p
JOIN diagnoses d ON p.patient_id = d.patient_id
LEFT JOIN procedures pr ON p.patient_id = pr.patient_id
  AND pr.procedure_date BETWEEN d.diagnosis_date AND DATE_ADD(d.diagnosis_date, 90)
WHERE d.icd10_code = 'E11.9'
  AND d.diagnosis_date >= '2023-01-01'
  AND d.diagnosis_date = (
    -- Ensure this is the first T2DM diagnosis
    SELECT MIN(d2.diagnosis_date) 
    FROM diagnoses d2 
    WHERE d2.patient_id = d.patient_id 
      AND d2.icd10_code = 'E11.9'
  )
ORDER BY p.patient_id, d.diagnosis_date

-- Medications prescribed near claim date
SELECT 
  c.claim_id,
  c.patient_id,
  c.service_date,
  rx.generic_name,
  rx.rx_date,
  DATEDIFF(c.service_date, rx.rx_date) as days_from_prescription
FROM claims c
LEFT JOIN prescriptions rx ON c.patient_id = rx.patient_id
  AND rx.rx_date BETWEEN DATE_SUB(c.service_date, 30) AND c.service_date
WHERE c.service_date >= '2023-01-01'
```

### Lookback for Historical Conditions
Determine if patient had condition in previous period (for exclusion criteria).

```sql
-- Check if patient had Type 1 diabetes diagnosis in prior year
SELECT 
  p.patient_id,
  CASE 
    WHEN EXISTS (
      SELECT 1 FROM diagnoses d 
      WHERE d.patient_id = p.patient_id 
        AND d.icd10_code LIKE 'E10%'
        AND d.diagnosis_date >= DATE_SUB('2024-01-01', 365)
    ) THEN 'YES'
    ELSE 'NO'
  END as has_type1_diabetes
FROM patients p
WHERE p.enrollment_start <= DATE_SUB('2024-01-01', 365)

-- Baseline comorbidity index (Charlson CCI approximation)
SELECT 
  p.patient_id,
  COUNT(DISTINCT 
    CASE 
      WHEN d.icd10_code LIKE 'I21%' THEN 'MI'
      WHEN d.icd10_code LIKE 'I50%' THEN 'HF'
      WHEN d.icd10_code LIKE 'I63%' THEN 'STROKE'
      WHEN d.icd10_code LIKE 'N18.4%' THEN 'CKDSTAGE4'
      WHEN d.icd10_code LIKE 'C%' THEN 'CANCER'
    END
  ) as baseline_comorbidity_count
FROM patients p
LEFT JOIN diagnoses d ON p.patient_id = d.patient_id
  AND d.diagnosis_date < '2024-01-01'
GROUP BY p.patient_id
```

## Rolling Windows and Period Analysis

### Monthly Patient Counts
Count unique patients observed in each month.

```sql
-- Monthly unique patients with claims
SELECT 
  DATE_TRUNC(c.service_date, MONTH) as service_month,
  COUNT(DISTINCT c.patient_id) as unique_patients,
  COUNT(c.claim_id) as claim_count
FROM claims c
WHERE c.status = 'Paid'
  AND c.service_date >= '2023-01-01'
GROUP BY DATE_TRUNC(c.service_date, MONTH)
ORDER BY service_month

-- Quarterly utilization trends
SELECT 
  CONCAT(YEAR(c.service_date), '-Q', QUARTER(c.service_date)) as quarter,
  c.claim_type,
  COUNT(DISTINCT c.patient_id) as active_patients,
  ROUND(AVG(c.paid_amount), 2) as avg_claim_cost,
  SUM(c.paid_amount) as total_cost
FROM claims c
WHERE c.status = 'Paid'
GROUP BY YEAR(c.service_date), QUARTER(c.service_date), c.claim_type
ORDER BY quarter, claim_type
```

### Annualized Metrics
Calculate annual metrics with flexible look-back window.

```sql
-- Annual medication cost per patient
SELECT 
  c.patient_id,
  YEAR(c.service_date) as service_year,
  SUM(c.paid_amount) as annual_cost,
  COUNT(c.claim_id) as claim_count,
  COUNT(DISTINCT c.cpt_code) as unique_procedures
FROM claims c
WHERE c.status = 'Paid'
  AND c.claim_type IN ('Pharmacy', 'Professional', 'Outpatient')
GROUP BY c.patient_id, YEAR(c.service_date)
ORDER BY c.patient_id, service_year

-- High-cost patient identification (top 10% by annual spend)
WITH annual_costs AS (
  SELECT 
    c.patient_id,
    SUM(c.paid_amount) as annual_spend
  FROM claims c
  WHERE c.status = 'Paid'
    AND c.service_date BETWEEN '2023-01-01' AND '2023-12-31'
  GROUP BY c.patient_id
),
cost_percentiles AS (
  SELECT 
    ac.patient_id,
    ac.annual_spend,
    PERCENTILE_CONT(0.90) OVER () as p90_cost
  FROM annual_costs ac
)
SELECT 
  cp.patient_id,
  cp.annual_spend,
  cp.p90_cost,
  CASE WHEN cp.annual_spend >= cp.p90_cost THEN 'HIGH_COST' ELSE 'NOT_HIGH_COST' END as cost_tier
FROM cost_percentiles cp
```

## Cohort Builder Patterns

### Incident Cohort (First Occurrence)
Identify patients at their disease onset.

```sql
-- Type 2 diabetes incident cohort
WITH t2dm_diagnoses AS (
  SELECT 
    d.patient_id,
    d.diagnosis_date,
    ROW_NUMBER() OVER (PARTITION BY d.patient_id ORDER BY d.diagnosis_date) as diagnosis_order
  FROM diagnoses d
  WHERE d.icd10_code LIKE 'E11%'
    AND d.diagnosis_date >= '2023-01-01'
)
SELECT 
  p.patient_id,
  p.age,
  p.gender,
  p.payer_type,
  td.diagnosis_date as index_date
FROM patients p
JOIN t2dm_diagnoses td ON p.patient_id = td.patient_id
WHERE td.diagnosis_order = 1  -- Only first diagnosis
  AND p.enrollment_start <= td.diagnosis_date
  AND (p.enrollment_end IS NULL OR p.enrollment_end >= DATE_ADD(td.diagnosis_date, 365))
```

### Prevalent Cohort (Point-in-Time Snapshot)
Identify patients with active condition at measurement date.

```sql
-- Prevalent hypertension cohort as of 2024-01-01
SELECT 
  p.patient_id,
  p.age,
  p.gender,
  MAX(d.diagnosis_date) as most_recent_htn_date
FROM patients p
JOIN diagnoses d ON p.patient_id = d.patient_id
WHERE d.icd10_code LIKE 'I10%'
  AND d.diagnosis_date <= '2024-01-01'
  AND p.enrollment_start <= '2024-01-01'
  AND (p.enrollment_end IS NULL OR p.enrollment_end >= '2024-01-01')
GROUP BY p.patient_id, p.age, p.gender
```

### Multi-Condition Cohort
Patients with multiple concurrent conditions.

```sql
-- Patients with both T2DM and HTN
SELECT 
  p.patient_id,
  p.age,
  p.gender,
  MIN(CASE WHEN d1.icd10_code LIKE 'E11%' THEN d1.diagnosis_date END) as t2dm_date,
  MIN(CASE WHEN d1.icd10_code LIKE 'I10%' THEN d1.diagnosis_date END) as htn_date
FROM patients p
JOIN diagnoses d1 ON p.patient_id = d1.patient_id
WHERE d1.icd10_code LIKE 'E11%'
  AND EXISTS (
    SELECT 1 FROM diagnoses d2 
    WHERE d2.patient_id = p.patient_id 
      AND d2.icd10_code LIKE 'I10%'
      AND d2.diagnosis_date <= CURRENT_DATE()
  )
GROUP BY p.patient_id, p.age, p.gender
```

### Medication-Initiated Cohort
Patients starting new therapy.

```sql
-- New metformin initiators (first prescription)
WITH ranked_metformin AS (
  SELECT 
    rx.patient_id,
    rx.rx_date,
    ROW_NUMBER() OVER (PARTITION BY rx.patient_id ORDER BY rx.rx_date) as rx_order
  FROM prescriptions rx
  WHERE rx.generic_name = 'metformin'
    AND rx.rx_date >= '2023-01-01'
)
SELECT 
  p.patient_id,
  p.age,
  p.gender,
  rm.rx_date as metformin_start_date,
  CASE WHEN d.icd10_code LIKE 'E11%' THEN 'YES' ELSE 'NO' END as has_t2dm_diagnosis
FROM patients p
JOIN ranked_metformin rm ON p.patient_id = rm.patient_id
LEFT JOIN diagnoses d ON p.patient_id = d.patient_id
  AND d.diagnosis_date <= rm.rx_date
  AND d.icd10_code LIKE 'E11%'
WHERE rm.rx_order = 1
  AND p.enrollment_start <= rm.rx_date
  AND (p.enrollment_end IS NULL OR p.enrollment_end >= DATE_ADD(rm.rx_date, 365))
```

## How to Query: Common Patterns

### Patients with Condition X Who Received Treatment Y Within N Days

```sql
-- Patients with HF who received heart failure drug within 30 days of diagnosis
SELECT 
  p.patient_id,
  p.age,
  d.diagnosis_date as hf_diagnosis_date,
  rx.rx_date as medication_start_date,
  rx.generic_name,
  DATEDIFF(rx.rx_date, d.diagnosis_date) as days_to_treatment
FROM patients p
JOIN diagnoses d ON p.patient_id = d.patient_id
LEFT JOIN prescriptions rx ON p.patient_id = rx.patient_id
  AND rx.rx_date BETWEEN d.diagnosis_date AND DATE_ADD(d.diagnosis_date, 30)
  AND rx.generic_name IN ('carvedilol', 'metoprolol', 'lisinopril', 'enalapril', 'dapagliflozin')
WHERE d.icd10_code LIKE 'I50%'
  AND d.diagnosis_date >= '2023-01-01'
  AND d.diagnosis_date = (
    SELECT MIN(diagnosis_date) 
    FROM diagnoses 
    WHERE patient_id = d.patient_id 
      AND icd10_code LIKE 'I50%'
  )
ORDER BY p.patient_id, d.diagnosis_date

-- Count patients by treatment receipt within timeframe
SELECT 
  COUNT(DISTINCT p.patient_id) as total_hf_patients,
  COUNT(DISTINCT CASE WHEN rx.generic_name IS NOT NULL THEN p.patient_id END) as treated_within_30_days,
  ROUND(100.0 * COUNT(DISTINCT CASE WHEN rx.generic_name IS NOT NULL THEN p.patient_id END) / 
    COUNT(DISTINCT p.patient_id), 2) as treatment_rate_pct
FROM patients p
JOIN diagnoses d ON p.patient_id = d.patient_id
LEFT JOIN prescriptions rx ON p.patient_id = rx.patient_id
  AND rx.rx_date BETWEEN d.diagnosis_date AND DATE_ADD(d.diagnosis_date, 30)
  AND rx.generic_name IN ('carvedilol', 'metoprolol')
WHERE d.icd10_code LIKE 'I50%'
```

### Medication Progression (Lines of Therapy)

```sql
-- Track medication sequence for a patient
WITH ranked_prescriptions AS (
  SELECT 
    patient_id,
    generic_name,
    rx_date,
    ROW_NUMBER() OVER (PARTITION BY patient_id ORDER BY rx_date) as therapy_line,
    LAG(generic_name) OVER (PARTITION BY patient_id ORDER BY rx_date) as prior_medication
  FROM prescriptions
  WHERE generic_name IN ('metformin', 'sitagliptin', 'insulin glargine', 'glipizide')
    AND rx_date >= '2023-01-01'
)
SELECT 
  patient_id,
  therapy_line,
  prior_medication,
  generic_name,
  rx_date
FROM ranked_prescriptions
ORDER BY patient_id, therapy_line

-- Count progression patterns
SELECT 
  rp.prior_medication as first_line,
  rp.generic_name as second_line,
  COUNT(DISTINCT rp.patient_id) as patient_count
FROM ranked_prescriptions rp
WHERE rp.prior_medication IS NOT NULL
  AND rp.therapy_line = 2
GROUP BY rp.prior_medication, rp.generic_name
ORDER BY patient_count DESC
```

## Therapy Query Index

### ACE Inhibitor Therapy Queries
```sql
-- Active ACE inhibitor users
SELECT DISTINCT patient_id, generic_name, rx_date
FROM prescriptions
WHERE generic_name IN ('lisinopril', 'enalapril', 'ramipril', 'perindopril')
  AND rx_date <= '2024-01-01'
  AND DATE_ADD(rx_date, days_supply) >= '2024-01-01'

-- ACE inhibitor initiation rate
SELECT 
  YEAR(rx_date) as year,
  COUNT(DISTINCT patient_id) as new_users
FROM prescriptions
WHERE generic_name LIKE '%pril%'
  AND rx_date = (
    SELECT MIN(rx_date) FROM prescriptions rx2 
    WHERE rx2.patient_id = prescriptions.patient_id 
      AND rx2.generic_name LIKE '%pril%'
  )
GROUP BY YEAR(rx_date)
```

### Statin Therapy Queries
```sql
-- High-intensity statin therapy adherence
WITH statin_fills AS (
  SELECT 
    patient_id,
    YEAR(rx_date) as year,
    COUNT(*) as fill_count,
    SUM(days_supply) as total_supply_days
  FROM prescriptions
  WHERE generic_name IN ('atorvastatin', 'rosuvastatin')
    AND CAST(SUBSTR(generic_name, INSTR(generic_name, ' ')+1), INTEGER) >= 40
  GROUP BY patient_id, YEAR(rx_date)
)
SELECT 
  patient_id,
  year,
  fill_count,
  total_supply_days,
  ROUND(total_supply_days / 365, 2) as medication_possession_ratio
FROM statin_fills
WHERE total_supply_days >= 270  -- >= 270 days = acceptable adherence
```

### Diabetes Medication Query Patterns
```sql
-- Glycemic control medication class usage
SELECT 
  YEAR(rx.rx_date) as year,
  CASE 
    WHEN rx.generic_name LIKE '%metformin%' THEN 'Biguanide'
    WHEN rx.generic_name LIKE '%pril%' OR rx.generic_name LIKE '%glitazone%' THEN 'TZD'
    WHEN rx.generic_name LIKE '%glipt%' THEN 'DPP-4i'
    WHEN rx.generic_name LIKE '%flozin%' THEN 'SGLT-2i'
    WHEN rx.generic_name LIKE '%tidu%' OR rx.generic_name LIKE '%tide%' THEN 'GLP-1RA'
    ELSE 'Other'
  END as drug_class,
  COUNT(DISTINCT rx.patient_id) as patient_count
FROM prescriptions rx
GROUP BY YEAR(rx.rx_date), drug_class
ORDER BY year, patient_count DESC
```

## Performance Optimization Tips

### Index Strategy for Common Queries
```sql
-- Primary indexes (create if not exist)
CREATE INDEX idx_patients_enrollment ON patients(patient_id, enrollment_start, enrollment_end)
CREATE INDEX idx_diagnoses_patient_date ON diagnoses(patient_id, diagnosis_date, icd10_code)
CREATE INDEX idx_prescriptions_patient_date ON prescriptions(patient_id, rx_date, generic_name)
CREATE INDEX idx_procedures_patient_date ON procedures(patient_id, procedure_date, cpt_code)
CREATE INDEX idx_claims_patient_date ON claims(patient_id, service_date, status)

-- Secondary indexes for aggregations
CREATE INDEX idx_diagnoses_code ON diagnoses(icd10_code, diagnosis_date)
CREATE INDEX idx_prescriptions_generic ON prescriptions(generic_name, rx_date)
CREATE INDEX idx_claims_cost ON claims(status, paid_amount) WHERE status = 'Paid'
```

### Query Optimization Patterns
```sql
-- Avoid: SELECT * with WHERE
-- Use: Explicit column selection with targeted WHERE
SELECT p.patient_id, p.age, p.gender
FROM patients p
WHERE p.enrollment_start <= '2024-01-01'

-- Avoid: Multiple LEFT JOINs without cardinality control
-- Use: CTEs with pre-aggregation
WITH patient_diagnoses AS (
  SELECT patient_id, COUNT(*) as diagnosis_count
  FROM diagnoses
  GROUP BY patient_id
)
SELECT p.patient_id, pd.diagnosis_count
FROM patients p
LEFT JOIN patient_diagnoses pd ON p.patient_id = pd.patient_id
```

## Reference: Common CoCo Queries Library

### Patient Counts by Condition
```sql
SELECT 
  d.icd10_code,
  d.icd10_description,
  COUNT(DISTINCT d.patient_id) as patient_count
FROM diagnoses d
GROUP BY d.icd10_code, d.icd10_description
ORDER BY patient_count DESC
```

### Cost by Condition
```sql
SELECT 
  d.icd10_code,
  d.icd10_description,
  COUNT(DISTINCT d.patient_id) as patients,
  SUM(c.paid_amount) as total_cost,
  ROUND(AVG(c.paid_amount), 2) as avg_cost_per_claim
FROM diagnoses d
JOIN claims c ON d.patient_id = c.patient_id 
  AND d.diagnosis_date <= c.service_date
WHERE c.status = 'Paid'
GROUP BY d.icd10_code, d.icd10_description
ORDER BY total_cost DESC
```

### Polypharmacy Analysis
```sql
SELECT 
  rx.patient_id,
  COUNT(DISTINCT rx.generic_name) as unique_medications,
  STRING_AGG(rx.generic_name, ', ') as medication_list
FROM prescriptions rx
WHERE rx.rx_date >= DATE_SUB(CURRENT_DATE(), 90)
GROUP BY rx.patient_id
HAVING COUNT(DISTINCT rx.generic_name) >= 10
ORDER BY COUNT(DISTINCT rx.generic_name) DESC
```
