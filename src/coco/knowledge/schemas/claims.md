# Claims Table Schema

## Overview
The `claims` table contains healthcare claims submitted to payers for reimbursement. This is the primary source for cost analysis, utilization patterns, and claims-based quality metrics.

## Columns

### claim_id
- **Type**: STRING
- **Description**: Unique identifier for each claim.
- **Constraints**: Primary key, NOT NULL
- **Notes**: De-identified. Links to a single service date and patient.

### patient_id
- **Type**: STRING
- **Description**: Foreign key linking to the `patients` table.
- **Constraints**: NOT NULL, references `patients(patient_id)`
- **Notes**: De-identified surrogate key.

### service_date
- **Type**: DATE
- **Description**: Date the healthcare service was provided.
- **Constraints**: NOT NULL
- **Notes**: When the procedure/service/visit occurred. Different from claim submission date.

### claim_type
- **Type**: STRING
- **Description**: Category of healthcare service type.
- **Valid Values**: "Inpatient", "Outpatient", "Professional", "Pharmacy", "Dental", "Vision", "Mental Health"
- **Constraints**: NOT NULL
- **Notes**: Indicates line of business and typical processing rules.

### icd10_code
- **Type**: STRING
- **Description**: Primary or principal diagnosis code for the claim (ICD-10-CM).
- **Constraints**: May be NULL (some claims don't require diagnosis, e.g., preventive visits)
- **Notes**: Diagnosis associated with this claim. Multiple diagnoses on one claim may be in separate records or columns.

### cpt_code
- **Type**: STRING
- **Description**: Procedure code (CPT) for the service rendered.
- **Constraints**: May be NULL (e.g., inpatient claims use different coding)
- **Notes**: What service was billed. Multiple procedures on one claim may be separate claim records.

### ndc_code
- **Type**: STRING
- **Description**: National Drug Code for pharmacy claims.
- **Constraints**: Only populated for claim_type = "Pharmacy"
- **Notes**: NULL for non-pharmacy claims.

### billed_amount
- **Type**: DECIMAL(12,2)
- **Description**: Total amount provider billed to the payer.
- **Constraints**: >= 0
- **Notes**: What provider sent invoice for. May be higher than allowed or paid.

### allowed_amount
- **Type**: DECIMAL(12,2)
- **Description**: Amount payer contractually allows for this service.
- **Constraints**: >= 0, usually <= billed_amount
- **Notes**: Fee schedule amount. Determines patient responsibility and provider adjustment.

### paid_amount
- **Type**: DECIMAL(12,2)
- **Description**: Amount payer actually paid for the claim.
- **Constraints**: >= 0, usually <= allowed_amount
- **Notes**: After deductible, coinsurance, or plan limits. What provider actually receives (minus patient responsibility).

### status
- **Type**: STRING
- **Description**: Current status of the claim.
- **Valid Values**: "Paid", "Denied", "Pending", "Rejected", "Adjusted"
- **Constraints**: NOT NULL
- **Notes**: Use to filter analysis. "Paid" claims most reliable for utilization. "Denied" important for access analysis.

### payer
- **Type**: STRING
- **Description**: Name or identifier of the insurance payer/plan.
- **Constraints**: NOT NULL
- **Notes**: Which insurance company processed the claim. Use for plan comparisons.

## Data Quality and Interpretation

### Cost Metrics
- **Billed vs. Allowed vs. Paid**: 
  - Billed = What provider asked for (often discounted)
  - Allowed = Contractual rate under payer agreement
  - Paid = Actual disbursement (after deductibles, denials)
  - Provider adjustment = Billed - Allowed (written off)

### Claim Scenarios
```
Scenario 1: Covered service under insurance
  Billed: $500 | Allowed: $400 | Paid: $320 (payer covers 80%)
  Patient owes: $80 | Provider adjustment: $100

Scenario 2: Denied claim
  Billed: $200 | Allowed: $0 | Paid: $0 | Status: Denied
  Reason: Not medically necessary (example)

Scenario 3: Subject to deductible
  Billed: $300 | Allowed: $300 | Paid: $0 | Status: Paid
  Note: Paid by patient as deductible hasn't met. May see $0 paid amount.
```

### Important Considerations
1. **Multiple Records per Claim**: Some systems break out multiple procedures/diagnoses as separate records
2. **Inpatient Grouping**: Hospital claims may be aggregated by admission, not by individual service
3. **Paid Status Lag**: Claims take time to process; recent dates may show "Pending" even if eligible
4. **Denials**: Missing records don't mean no claim submitted; check status = "Denied"

## Common Query Patterns

### Total Cost by Patient
```sql
SELECT 
  c.patient_id,
  SUM(c.allowed_amount) as total_allowed,
  SUM(c.paid_amount) as total_paid,
  COUNT(c.claim_id) as claim_count
FROM claims c
WHERE c.status = 'Paid'
  AND c.service_date >= '2023-01-01'
  AND c.service_date <= '2023-12-31'
GROUP BY c.patient_id
ORDER BY total_paid DESC
```

### Cost by Diagnosis
```sql
SELECT 
  c.icd10_code,
  COUNT(DISTINCT c.patient_id) as patient_count,
  COUNT(c.claim_id) as claim_count,
  SUM(c.allowed_amount) as total_allowed,
  ROUND(AVG(c.paid_amount), 2) as avg_paid_per_claim,
  SUM(c.paid_amount) as total_paid
FROM claims c
WHERE c.status = 'Paid'
  AND c.service_date >= '2023-01-01'
GROUP BY c.icd10_code
ORDER BY total_paid DESC
LIMIT 30
```

### Inpatient vs. Outpatient Cost Comparison
```sql
SELECT 
  c.claim_type,
  COUNT(DISTINCT c.patient_id) as unique_patients,
  COUNT(c.claim_id) as claim_count,
  ROUND(AVG(c.paid_amount), 2) as avg_cost_per_claim,
  SUM(c.paid_amount) as total_cost,
  ROUND(SUM(c.paid_amount) / COUNT(DISTINCT c.patient_id), 2) as cost_per_patient
FROM claims c
WHERE c.status = 'Paid'
  AND c.service_date BETWEEN '2023-01-01' AND '2023-12-31'
GROUP BY c.claim_type
ORDER BY total_cost DESC
```

### Denied Claims Analysis
```sql
SELECT 
  c.claim_type,
  c.icd10_code,
  c.cpt_code,
  COUNT(c.claim_id) as denied_claim_count,
  ROUND(SUM(c.billed_amount), 2) as total_denied_amount
FROM claims c
WHERE c.status = 'Denied'
  AND c.service_date >= '2023-01-01'
GROUP BY c.claim_type, c.icd10_code, c.cpt_code
HAVING COUNT(c.claim_id) > 5
ORDER BY denied_claim_count DESC
```

### Utilization Trends (claims per patient per month)
```sql
SELECT 
  DATE_TRUNC(c.service_date, MONTH) as service_month,
  c.claim_type,
  COUNT(DISTINCT c.patient_id) as unique_patients,
  COUNT(c.claim_id) as claim_count,
  ROUND(COUNT(c.claim_id) / COUNT(DISTINCT c.patient_id), 2) as avg_claims_per_patient
FROM claims c
WHERE c.status = 'Paid'
  AND c.service_date >= '2023-01-01'
GROUP BY DATE_TRUNC(c.service_date, MONTH), c.claim_type
ORDER BY service_month, claim_type
```

### High-Cost Patients
```sql
WITH patient_costs AS (
  SELECT 
    c.patient_id,
    SUM(c.paid_amount) as annual_cost
  FROM claims c
  WHERE c.status = 'Paid'
    AND c.service_date BETWEEN '2023-01-01' AND '2023-12-31'
  GROUP BY c.patient_id
)
SELECT 
  p.patient_id,
  p.age,
  p.gender,
  p.payer_type,
  pc.annual_cost,
  ROUND(pc.annual_cost / 12, 2) as avg_monthly_cost
FROM patient_costs pc
JOIN patients p ON pc.patient_id = p.patient_id
WHERE pc.annual_cost > 50000
ORDER BY pc.annual_cost DESC
```

### Pharmacy vs. Medical Cost Split
```sql
SELECT 
  c.patient_id,
  SUM(CASE WHEN c.claim_type = 'Pharmacy' THEN c.paid_amount ELSE 0 END) as pharmacy_cost,
  SUM(CASE WHEN c.claim_type != 'Pharmacy' THEN c.paid_amount ELSE 0 END) as medical_cost,
  SUM(c.paid_amount) as total_cost,
  ROUND(SUM(CASE WHEN c.claim_type = 'Pharmacy' THEN c.paid_amount ELSE 0 END) / SUM(c.paid_amount) * 100, 2) as pharmacy_percent
FROM claims c
WHERE c.status = 'Paid'
  AND c.service_date BETWEEN '2023-01-01' AND '2023-12-31'
GROUP BY c.patient_id
HAVING SUM(c.paid_amount) > 10000
ORDER BY total_cost DESC
```

## Example Records

```
claim_id   | patient_id | service_date | claim_type   | icd10_code | cpt_code | ndc_code | billed_amount | allowed_amount | paid_amount | status | payer
-----------|------------|--------------|--------------|------------|----------|----------|---------------|----------------|-------------|--------|---------------
CLM000001  | P000001    | 2024-01-15   | Professional | E11.9      | 99213    | NULL     | 150.00        | 120.00         | 96.00       | Paid   | Aetna
CLM000002  | P000002    | 2023-12-20   | Inpatient    | I10        | NULL     | NULL     | 25000.00      | 18000.00       | 14400.00    | Paid   | United
CLM000003  | P000001    | 2024-02-01   | Pharmacy     | NULL       | NULL     | 00069-0147 | 45.00         | 35.00          | 35.00       | Paid   | Aetna
CLM000004  | P000003    | 2024-02-10   | Professional | F41.1      | 99214    | NULL     | 175.00        | 140.00         | 112.00      | Paid   | Cigna
CLM000005  | P000001    | 2024-01-10   | Professional | NULL       | 99213    | NULL     | 150.00        | 120.00         | 0.00        | Denied | Aetna
```

## Performance Considerations

- Index on `patient_id` for patient-level cost analysis
- Index on `service_date` for temporal analysis
- Index on `icd10_code` and `cpt_code` for service-level analysis
- Composite index on `(patient_id, service_date)` for common lookups
- Index on `status` to filter paid vs. denied claims efficiently
- Partition by `service_date` (year/quarter) for very large datasets

## Cost Analysis Best Practices

1. **Filter by Status**: Always include "WHERE status = 'Paid'" for cost analysis unless studying denials
2. **Use Allowed Amount**: For benchmarking costs, use allowed_amount (not billed, which varies by provider)
3. **Use Paid Amount**: For actual payer cost, use paid_amount
4. **Lag for Recent Data**: Claims submitted within last 30-60 days may still be pending; lag data for accurate trending
5. **Plan-Specific Metrics**: Consider plan design (deductible, coinsurance) when interpreting paid vs. allowed

## Related Tables

- `patients`: Patient demographics via `patient_id`
- `diagnoses`: Diagnosis codes matching icd10_code
- `procedures`: Procedure codes matching cpt_code
- `prescriptions`: Drug codes matching ndc_code (pharmacy claims)
