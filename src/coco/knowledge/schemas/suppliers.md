# Suppliers Table Schema

## Overview
The `suppliers` table contains reference data about healthcare providers, facilities, and suppliers. This is used for provider-level analysis, network contracting, and supply chain management.

## Columns

### supplier_id
- **Type**: STRING
- **Description**: Unique identifier for each supplier/provider/facility.
- **Constraints**: Primary key, NOT NULL
- **Notes**: De-identified surrogate key. Links to procedures and claims data.

### supplier_name
- **Type**: STRING
- **Description**: Name of the supplier, provider, or facility.
- **Constraints**: NOT NULL
- **Notes**: May be a hospital system, clinic, individual provider, or pharmacy. Examples: "Memorial Hospital", "Dr. Jane Smith, MD", "CVS Pharmacy #4521".

### supplier_type
- **Type**: STRING
- **Description**: Category of supplier.
- **Valid Values**: "Hospital", "Clinic", "Physician", "Pharmacist", "Medical Center", "Urgent Care", "Lab", "DME Supplier", "Pharmacy"
- **Constraints**: NOT NULL
- **Notes**: Indicates business model and contracting approach.

### npi
- **Type**: STRING
- **Description**: National Provider Identifier (if applicable).
- **Constraints**: May be NULL (e.g., facilities may have NPI Organization ID instead of individual NPI)
- **Notes**: 10-digit identifier assigned by CMS. Used for credentialing and contracting. May be de-identified in this table.

### specialty
- **Type**: STRING
- **Description**: Primary clinical specialty or service line.
- **Valid Values**: "Cardiology", "Orthopedics", "Internal Medicine", "General Surgery", "Pharmacy", "Oncology", "Radiology", "Pediatrics", "Primary Care", "Mental Health", "Urgent Care", "Emergency Medicine", etc.
- **Constraints**: NOT NULL
- **Notes**: Highest-value or primary specialty if provider covers multiple areas.

### address
- **Type**: STRING
- **Description**: Street address of the supplier location (no city/state/zip in this field for de-identification).
- **Constraints**: May be NULL (de-identification sometimes omits street-level detail)
- **Notes**: Full address included when available for network analysis.

### state
- **Type**: STRING
- **Description**: State where supplier is located (2-letter abbreviation).
- **Constraints**: NOT NULL
- **Notes**: USPS state codes. Use for geographic network analysis.

### contracts_count
- **Type**: INTEGER
- **Description**: Number of active payer contracts this supplier has.
- **Constraints**: >= 0
- **Notes**: Higher count indicates broader network participation. Useful for network adequacy analysis.

### tier
- **Type**: STRING
- **Description**: Provider tier/status in network (based on contracts and performance).
- **Valid Values**: "In-Network", "Preferred", "Non-Preferred", "Out-of-Network", "Unknown"
- **Constraints**: May be NULL
- **Notes**: Indicates cost-sharing and reimbursement expectations. Affects patient out-of-pocket costs.

## Data Quality Notes

1. **Deidentification**: Some fields like full address or NPI may be partially de-identified or NULL
2. **Duplicate Entries**: Provider may appear under multiple names (e.g., "Memorial Hospital" vs. "Memorial Medical Center")
3. **Stale Data**: Specialist lists and contract counts updated periodically; may lag current reality
4. **Facility vs. Individual**: "Physician" type suppliers are individuals; "Hospital" type are organizations
5. **Tier Variations**: Tier may vary by payer. This field represents most common tier, not necessarily accurate for all payers

## Common Query Patterns

### All Suppliers in a Specialty
```sql
SELECT 
  s.supplier_id,
  s.supplier_name,
  s.supplier_type,
  s.specialty,
  s.state,
  s.contracts_count,
  s.tier
FROM suppliers s
WHERE s.specialty = 'Cardiology'
  AND s.state IN ('CA', 'NY', 'TX')
ORDER BY s.contracts_count DESC
```

### Network Adequacy (Providers per Specialty per State)
```sql
SELECT 
  s.state,
  s.specialty,
  COUNT(DISTINCT s.supplier_id) as provider_count,
  ROUND(AVG(s.contracts_count), 2) as avg_contracts_per_provider
FROM suppliers s
WHERE s.supplier_type IN ('Hospital', 'Clinic', 'Physician')
GROUP BY s.state, s.specialty
HAVING COUNT(DISTINCT s.supplier_id) > 5
ORDER BY s.state, provider_count DESC
```

### Preferred Provider Analysis
```sql
SELECT 
  s.supplier_type,
  s.specialty,
  COUNT(CASE WHEN s.tier = 'Preferred' THEN 1 END) as preferred_count,
  COUNT(CASE WHEN s.tier = 'In-Network' THEN 1 END) as in_network_count,
  COUNT(CASE WHEN s.tier = 'Non-Preferred' THEN 1 END) as non_preferred_count,
  COUNT(DISTINCT s.supplier_id) as total_suppliers
FROM suppliers s
GROUP BY s.supplier_type, s.specialty
ORDER BY s.supplier_type, total_suppliers DESC
```

### High-Volume Prescribers (join with prescriptions)
```sql
SELECT 
  s.supplier_id,
  s.supplier_name,
  s.specialty,
  COUNT(DISTINCT rx.patient_id) as unique_patients,
  COUNT(rx.patient_id) as prescription_count
FROM suppliers s
JOIN prescriptions rx ON s.supplier_id = rx.prescriber_id
WHERE rx.rx_date >= '2023-01-01'
GROUP BY s.supplier_id, s.supplier_name, s.specialty
ORDER BY prescription_count DESC
LIMIT 30
```

### Facility Usage by Claim Volume
```sql
SELECT 
  s.supplier_id,
  s.supplier_name,
  s.supplier_type,
  s.state,
  COUNT(DISTINCT c.patient_id) as unique_patients,
  COUNT(c.claim_id) as total_claims,
  SUM(c.paid_amount) as total_cost
FROM suppliers s
JOIN claims c ON s.supplier_id = c.claim_id  -- Simplified; actual join depends on schema
WHERE c.status = 'Paid'
  AND c.service_date >= '2023-01-01'
GROUP BY s.supplier_id, s.supplier_name, s.supplier_type, s.state
ORDER BY total_cost DESC
LIMIT 30
```

### Specialists by Network Tier
```sql
SELECT 
  s.specialty,
  s.tier,
  COUNT(DISTINCT s.supplier_id) as provider_count,
  ROUND(AVG(s.contracts_count), 2) as avg_contracts,
  STRING_AGG(DISTINCT s.state, ',' ORDER BY s.state) as states_represented
FROM suppliers s
WHERE s.supplier_type = 'Physician'
GROUP BY s.specialty, s.tier
HAVING COUNT(DISTINCT s.supplier_id) > 5
ORDER BY s.specialty, COUNT(DISTINCT s.supplier_id) DESC
```

## Example Records

```
supplier_id | supplier_name                | supplier_type | npi        | specialty            | address              | state | contracts_count | tier
------------|------------------------------|---------------|------------|----------------------|----------------------|-------|-----------------|---------------
SUP000001   | Memorial Hospital             | Hospital      | 1234567890 | General Surgery      | 100 Main St          | CA    | 12              | In-Network
SUP000002   | Dr. Sarah Chen, MD            | Physician     | 0987654321 | Cardiology           | 200 Oak Ave          | CA    | 8               | Preferred
SUP000003   | CVS Pharmacy #4521            | Pharmacy      | NULL       | Pharmacy             | 300 Pine Rd          | NY    | 15              | In-Network
SUP000004   | Advanced Orthopedic Center    | Clinic        | 5555555555 | Orthopedics          | 400 Elm St           | TX    | 6               | Preferred
SUP000005   | Regional Medical Lab          | Lab           | 3333333333 | Laboratory Services  | 500 Birch Ln         | WA    | 4               | In-Network
```

## Performance Considerations

- Index on `supplier_id` (automatic as PK)
- Index on `specialty` for specialty-based lookups
- Index on `state` for geographic queries
- Index on `supplier_type` for provider type analysis
- Index on `tier` for network tier analysis
- Composite index on `(state, specialty)` for network adequacy queries

## Provider Reference Data

### National Provider Identifier (NPI)
- **Type**: 10-digit unique identifier
- **Source**: CMS National Plan and Provider Enumeration System (NPPES)
- **Used for**: Provider identification, credentialing, claims submission
- **Lookup**: https://npiregistry.cms.hhs.gov/ (public tool)

### Healthcare Provider Taxonomy
- **Source**: NUCC (National Uniform Claim Committee)
- **Format**: 10-character code representing specialty and role
- **Example**: "208D00000X" = Psychiatry (general)

## Related Tables

- `procedures`: Procedures performed by suppliers (via provider_id or facility_id)
- `prescriptions`: Prescriptions written by suppliers (via prescriber_id)
- `claims`: Claims submitted by suppliers
- `patients`: Patient demographics (geographic alignment with suppliers)
