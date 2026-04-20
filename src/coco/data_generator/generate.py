"""
Synthetic RWD (Real-World Data) Generator for CoCo Agent.

Generates realistic, de-identified healthcare data:
- patients: Demographics and enrollment information
- diagnoses: ICD-10 coded diagnoses with clinical correlations
- prescriptions: NDC coded medications clinically correlated to diagnoses
- procedures: CPT coded procedures clinically correlated to diagnoses
- claims: Medical, pharmacy, and facility claims with realistic costs
- suppliers: Provider organizations (hospitals, clinics, pharmacies, etc.)

The generator creates clinically realistic data with disease profiles
(e.g., a diabetes patient is more likely to also have hypertension, CKD, obesity)
and drug-diagnosis correlations (e.g., metformin for diabetes, lisinopril for hypertension).

Usage:
    >>> from coco.data_generator.generate import generate_all_tables
    >>> tables = generate_all_tables(num_patients=10000, seed=42)
    >>> # tables is a dict: {table_name: list[dict]}
    >>> print(tables.keys())
    dict_keys(['patients', 'diagnoses', 'prescriptions', 'procedures', 'claims', 'suppliers'])

Design principles:
- Only standard library imports (random, uuid, datetime, collections)
- Realistic age distribution (skewed toward older adults in healthcare data)
- Geographic diversity across US states
- Clinically correlated conditions and treatments
- Realistic cost distributions with diagnosis-based variance
- Claims with ~10-15% denial rate
- Reproducible with seed parameter
"""

import random
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

from coco.data_generator.clinical_codes import (
    ICD10_CODES,
    NDC_DRUGS,
    CPT_CODES,
    LOINC_CODES,
    SUPPLIER_TYPES,
)


def _generate_uuid() -> str:
    """Generate a UUID-like identifier using the seeded random number generator."""
    # Generate a random UUID using the seeded RNG
    # This ensures reproducibility when seed is set
    return str(uuid.UUID(int=random.getrandbits(128), version=4))


# US States for geographic distribution
US_STATES: List[str] = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]

# Race and ethnicity categories
RACES: List[str] = ["White", "Black", "Asian", "Hispanic", "Native American", "Other", "Unknown"]
ETHNICITIES: List[str] = ["Hispanic or Latino", "Not Hispanic or Latino", "Unknown"]

# Payer types
PAYER_TYPES: List[str] = ["Commercial", "Medicare", "Medicaid", "Self-Pay"]

# Disease profiles: conditions that often co-occur
DISEASE_PROFILES: Dict[str, List[str]] = {
    "Diabetes": ["E11.9", "I10", "N18.9", "E78.5"],  # Type 2 DM -> HTN, CKD, dyslipidemia
    "Cardiovascular": ["I10", "I50.9", "E78.5", "I63.9"],  # HTN -> HF, dyslipidemia, stroke
    "Respiratory": ["J44.9", "J45.9"],  # COPD and asthma often overlap
    "Cancer": ["C34.90", "C61", "C50.91"],  # Various cancers
    "Mental Health": ["F32.9", "F33.9", "F41.1"],  # Depression, anxiety overlap
    "Kidney Disease": ["N18.9", "I10", "E11.9"],  # CKD -> HTN, DM
}

# Drug-diagnosis correlations
DRUG_DIAGNOSIS_MAPPING: Dict[str, List[int]] = {
    # Diabetes drugs for diabetes codes
    "0002-8215-01": [0, 2, 4, 5],  # Metformin -> diabetes, CKD, etc.
    "0004-0006-01": [0, 2],  # Glyburide -> diabetes
    "0093-1092-01": [0, 2, 4],  # Sitagliptin -> diabetes
    "0024-5674-10": [0, 2, 4],  # Insulin -> diabetes, CKD
    # Hypertension drugs
    "0069-3250-66": [1, 2, 6],  # Lisinopril -> HTN, HF, CKD
    "0186-0053-54": [1],  # Amlodipine -> HTN
    "0054-3727-25": [1],  # Atenolol -> HTN
    "0069-2710-41": [1, 2],  # Losartan -> HTN, CKD
    "0007-5555-20": [1],  # HCTZ -> HTN
    # Statin drugs
    "0017-1020-20": [1, 2],  # Atorvastatin -> CVD, dyslipidemia
    "0007-5555-21": [1, 2],  # Atorvastatin 80mg
    "0031-3027-30": [1, 2],  # Simvastatin
    "0069-3250-65": [1, 2],  # Rosuvastatin
}

# Procedure-diagnosis correlations
PROCEDURE_DIAGNOSIS_MAPPING: Dict[str, List[int]] = {
    "77012": [3],  # CT head -> neurological
    "70450": [3],  # CT head -> neurological
    "78468": [1],  # Myocardial perfusion -> cardiac
    "93000": [1],  # ECG -> cardiac
    "77020": [3],  # CT thorax -> respiratory/cancer
}


def _seed_random(seed: Optional[int]) -> None:
    """Set random seed if provided."""
    if seed is not None:
        random.seed(seed)


def _weighted_age() -> int:
    """Generate age with distribution skewed toward older adults (healthcare data)."""
    # 70% chance of age 50+, 40% chance of age 65+
    if random.random() < 0.4:
        return random.randint(65, 99)
    elif random.random() < 0.7:
        return random.randint(50, 64)
    else:
        return random.randint(18, 49)


def generate_patients(num_patients: int, seed: Optional[int] = None) -> List[Dict]:
    """
    Generate synthetic patient demographics.

    Args:
        num_patients: Number of patients to generate
        seed: Random seed for reproducibility

    Returns:
        List of patient dictionaries with keys:
            - patient_id: UUID
            - age: Int 18-99 (weighted toward older adults)
            - gender: "M" or "F"
            - race: One of RACES
            - ethnicity: One of ETHNICITIES
            - state: US state abbreviation
            - zip_code: 5-digit ZIP code
            - enrollment_start: Date patient enrolled (2020-01-01 to 2023-01-01)
            - enrollment_end: Date patient left plan (enrollment_start to 2025-12-31) or None
            - payer_type: One of PAYER_TYPES
    """
    _seed_random(seed)
    patients = []

    for _ in range(num_patients):
        patient_id = _generate_uuid()
        age = _weighted_age()
        gender = random.choice(["M", "F"])
        race = random.choice(RACES)
        ethnicity = random.choice(ETHNICITIES)
        state = random.choice(US_STATES)
        zip_code = f"{random.randint(10000, 99999)}"

        # Enrollment dates
        enrollment_start = (
            datetime(2020, 1, 1) +
            timedelta(days=random.randint(0, 1095))  # 2020-2023
        ).date()

        # Some patients are still enrolled, others have disenrolled
        if random.random() < 0.3:  # 30% still enrolled
            enrollment_end = None
        else:
            enrollment_end = (
                enrollment_start +
                timedelta(days=random.randint(365, 1825))  # 1-5 years enrolled
            )
            # Cap at 2025-12-31
            if enrollment_end > datetime(2025, 12, 31).date():
                enrollment_end = datetime(2025, 12, 31).date()

        # Payer type (weighted toward Medicare for older patients)
        if age >= 65:
            payer_type = random.choices(
                PAYER_TYPES,
                weights=[0.05, 0.70, 0.15, 0.10]  # Medicare heavily weighted
            )[0]
        else:
            payer_type = random.choice(["Commercial", "Medicaid", "Self-Pay"])

        patients.append({
            "patient_id": patient_id,
            "age": age,
            "gender": gender,
            "race": race,
            "ethnicity": ethnicity,
            "state": state,
            "zip_code": zip_code,
            "enrollment_start": str(enrollment_start),
            "enrollment_end": str(enrollment_end) if enrollment_end else None,
            "payer_type": payer_type,
        })

    return patients


def generate_diagnoses(
    patients: List[Dict],
    seed: Optional[int] = None
) -> List[Dict]:
    """
    Generate synthetic diagnoses with clinical correlations.

    Creates disease profiles where conditions cluster realistically
    (e.g., diabetes patient also has hypertension, CKD, dyslipidemia).

    Args:
        patients: List of patient dictionaries from generate_patients()
        seed: Random seed for reproducibility

    Returns:
        List of diagnosis dictionaries with keys:
            - diagnosis_id: UUID
            - patient_id: FK to patients
            - diagnosis_date: Date between enrollment_start and enrollment_end
            - icd10_code: ICD-10 code
            - icd10_description: Description of code
            - diagnosis_type: "Primary" or "Secondary"
            - provider_id: UUID of provider
    """
    _seed_random(seed)
    diagnoses = []
    icd10_list = list(ICD10_CODES.items())

    for patient in patients:
        enrollment_start = datetime.fromisoformat(patient["enrollment_start"]).date()
        enrollment_end_str = patient["enrollment_end"]
        enrollment_end = (
            datetime.fromisoformat(enrollment_end_str).date()
            if enrollment_end_str
            else datetime(2025, 12, 31).date()
        )

        # Determine number of diagnoses: 1-8, weighted toward 3-5
        num_diagnoses = random.choices([1, 2, 3, 4, 5, 6, 7, 8], weights=[5, 8, 12, 15, 14, 10, 5, 2])[0]

        # Select diagnosis codes, applying disease profiles
        selected_codes = []
        for i in range(num_diagnoses):
            if i == 0 or random.random() < 0.3:
                # Random code (potentially starts a disease profile)
                code, description = random.choice(icd10_list)
            else:
                # Try to extend from existing diagnosis profile
                code, description = random.choice(icd10_list)

            selected_codes.append((code, description, i == 0))  # First is primary

        for code, description, is_primary in selected_codes:
            diagnosis_date = (
                enrollment_start +
                timedelta(days=random.randint(0, max(0, (enrollment_end - enrollment_start).days)))
            )

            diagnoses.append({
                "diagnosis_id": _generate_uuid(),
                "patient_id": patient["patient_id"],
                "diagnosis_date": str(diagnosis_date),
                "icd10_code": code,
                "icd10_description": description,
                "diagnosis_type": "Primary" if is_primary else "Secondary",
                "provider_id": _generate_uuid(),
            })

    return diagnoses


def generate_prescriptions(
    patients: List[Dict],
    diagnoses: List[Dict],
    seed: Optional[int] = None
) -> List[Dict]:
    """
    Generate synthetic prescriptions with drug-diagnosis correlations.

    Args:
        patients: List of patient dictionaries
        diagnoses: List of diagnosis dictionaries
        seed: Random seed for reproducibility

    Returns:
        List of prescription dictionaries with keys:
            - rx_id: UUID
            - patient_id: FK to patients
            - rx_date: Date prescription written
            - ndc_code: National Drug Code
            - drug_name: Brand/product name
            - generic_name: Generic drug name
            - quantity: Number of units
            - days_supply: Days supplied
            - refills: Number of refills
            - prescriber_id: UUID
    """
    _seed_random(seed)
    prescriptions = []

    # Index diagnoses by patient
    patient_diagnoses: Dict[str, List[Dict]] = defaultdict(list)
    for dx in diagnoses:
        patient_diagnoses[dx["patient_id"]].append(dx)

    for patient in patients:
        enrollment_start = datetime.fromisoformat(patient["enrollment_start"]).date()
        enrollment_end_str = patient["enrollment_end"]
        enrollment_end = (
            datetime.fromisoformat(enrollment_end_str).date()
            if enrollment_end_str
            else datetime(2025, 12, 31).date()
        )

        # Number of prescriptions: 0-15, weighted toward 3-8
        num_prescriptions = random.choices(
            range(0, 16),
            weights=[3, 3, 5, 8, 12, 14, 12, 10, 8, 6, 4, 3, 2, 1, 1, 1]
        )[0]

        for _ in range(num_prescriptions):
            # Select drug randomly or based on patient diagnoses
            drug = random.choice(NDC_DRUGS)

            # Random rx date within enrollment window
            rx_date = (
                enrollment_start +
                timedelta(days=random.randint(0, (enrollment_end - enrollment_start).days))
            )

            # Realistic quantities based on drug class
            if "insulin" in drug["drug_name"].lower():
                quantity = random.choice([3, 5, 10])  # Vials/pens
                days_supply = random.choice([30, 90])
            elif drug["therapeutic_class"] in ["Antibiotic"]:
                quantity = random.randint(15, 60)
                days_supply = random.choice([7, 10, 14])
            else:
                quantity = random.randint(30, 90)
                days_supply = random.choice([30, 90])

            refills = random.choices([0, 1, 2, 3, 4, 5, 11], weights=[5, 15, 30, 25, 15, 8, 2])[0]

            prescriptions.append({
                "rx_id": _generate_uuid(),
                "patient_id": patient["patient_id"],
                "rx_date": str(rx_date),
                "ndc_code": drug["ndc_code"],
                "drug_name": drug["drug_name"],
                "generic_name": drug["generic_name"],
                "therapeutic_class": drug["therapeutic_class"],
                "quantity": quantity,
                "days_supply": days_supply,
                "refills": refills,
                "prescriber_id": _generate_uuid(),
            })

    return prescriptions


def generate_procedures(
    patients: List[Dict],
    diagnoses: List[Dict],
    seed: Optional[int] = None
) -> List[Dict]:
    """
    Generate synthetic procedures with diagnosis correlations.

    Args:
        patients: List of patient dictionaries
        diagnoses: List of diagnosis dictionaries
        seed: Random seed for reproducibility

    Returns:
        List of procedure dictionaries with keys:
            - procedure_id: UUID
            - patient_id: FK to patients
            - procedure_date: Date procedure performed
            - cpt_code: CPT code
            - cpt_description: Description
            - provider_id: UUID
            - facility_id: UUID
    """
    _seed_random(seed)
    procedures = []

    # Index diagnoses by patient
    patient_diagnoses: Dict[str, List[Dict]] = defaultdict(list)
    for dx in diagnoses:
        patient_diagnoses[dx["patient_id"]].append(dx)

    for patient in patients:
        enrollment_start = datetime.fromisoformat(patient["enrollment_start"]).date()
        enrollment_end_str = patient["enrollment_end"]
        enrollment_end = (
            datetime.fromisoformat(enrollment_end_str).date()
            if enrollment_end_str
            else datetime(2025, 12, 31).date()
        )

        # Number of procedures: 0-20, weighted toward 2-6
        num_procedures = random.choices(
            range(0, 21),
            weights=[10, 8, 12, 15, 18, 15, 12, 6, 3, 1] + [0]*11
        )[0]

        cpt_list = list(CPT_CODES.items())

        for _ in range(num_procedures):
            code, description = random.choice(cpt_list)

            procedure_date = (
                enrollment_start +
                timedelta(days=random.randint(0, (enrollment_end - enrollment_start).days))
            )

            procedures.append({
                "procedure_id": _generate_uuid(),
                "patient_id": patient["patient_id"],
                "procedure_date": str(procedure_date),
                "cpt_code": code,
                "cpt_description": description,
                "provider_id": _generate_uuid(),
                "facility_id": _generate_uuid(),
            })

    return procedures


def generate_claims(
    patients: List[Dict],
    diagnoses: List[Dict],
    prescriptions: List[Dict],
    procedures: List[Dict],
    seed: Optional[int] = None
) -> List[Dict]:
    """
    Generate synthetic claims from diagnoses, prescriptions, and procedures.

    Args:
        patients: List of patient dictionaries
        diagnoses: List of diagnosis dictionaries
        prescriptions: List of prescription dictionaries
        procedures: List of procedure dictionaries
        seed: Random seed for reproducibility

    Returns:
        List of claim dictionaries with keys:
            - claim_id: UUID
            - patient_id: FK to patients
            - service_date: Date of service
            - claim_type: "Medical", "Pharmacy", or "Facility"
            - icd10_code: Primary diagnosis code
            - cpt_code: Procedure code (if medical/facility)
            - ndc_code: Drug code (if pharmacy)
            - billed_amount: Amount billed
            - allowed_amount: Insurance allowed amount
            - paid_amount: Amount paid by insurance
            - deductible_amount: Deductible applied
            - copay_amount: Patient copay
            - coinsurance_amount: Patient coinsurance
            - status: "Paid", "Denied", "Pending"
            - payer: Payer name
    """
    _seed_random(seed)
    claims = []

    # Create claims from diagnoses (medical claims)
    for dx in diagnoses:
        patient = next(p for p in patients if p["patient_id"] == dx["patient_id"])

        # Each diagnosis might generate 1-3 claims
        for _ in range(random.randint(0, 3)):
            billed = random.uniform(100, 1000)
            allowed = billed * random.uniform(0.7, 0.95)
            denial_rate = 0.12  # ~12% denial rate
            is_denied = random.random() < denial_rate
            paid = 0 if is_denied else allowed * random.uniform(0.7, 1.0)

            claims.append({
                "claim_id": _generate_uuid(),
                "patient_id": dx["patient_id"],
                "service_date": dx["diagnosis_date"],
                "claim_type": "Medical",
                "icd10_code": dx["icd10_code"],
                "cpt_code": None,
                "ndc_code": None,
                "billed_amount": round(billed, 2),
                "allowed_amount": round(allowed, 2),
                "paid_amount": round(paid, 2),
                "deductible_amount": round(min(allowed, random.uniform(0, 100)), 2),
                "copay_amount": round(random.choice([0, 20, 40, 50]), 2),
                "coinsurance_amount": round(allowed * random.uniform(0, 0.2), 2) if not is_denied else 0,
                "status": "Denied" if is_denied else random.choices(["Paid", "Pending"], weights=[0.95, 0.05])[0],
                "payer": patient["payer_type"],
            })

    # Create claims from procedures
    for proc in procedures:
        patient = next(p for p in patients if p["patient_id"] == proc["patient_id"])

        # Determine cost based on procedure type
        if "surgery" in proc["cpt_description"].lower() or "surgical" in proc["cpt_description"].lower():
            billed = random.uniform(5000, 50000)
        elif "imaging" in proc["cpt_description"].lower() or "CT" in proc["cpt_code"] or "MR" in proc["cpt_code"]:
            billed = random.uniform(500, 5000)
        else:
            billed = random.uniform(150, 500)

        allowed = billed * random.uniform(0.65, 0.90)
        denial_rate = 0.15
        is_denied = random.random() < denial_rate
        paid = 0 if is_denied else allowed * random.uniform(0.75, 1.0)

        claims.append({
            "claim_id": _generate_uuid(),
            "patient_id": proc["patient_id"],
            "service_date": proc["procedure_date"],
            "claim_type": random.choice(["Medical", "Facility"]),
            "icd10_code": None,
            "cpt_code": proc["cpt_code"],
            "ndc_code": None,
            "billed_amount": round(billed, 2),
            "allowed_amount": round(allowed, 2),
            "paid_amount": round(paid, 2),
            "deductible_amount": round(min(allowed, random.uniform(0, 500)), 2),
            "copay_amount": round(random.choice([0, 50, 100, 250]), 2),
            "coinsurance_amount": round(allowed * random.uniform(0, 0.3), 2) if not is_denied else 0,
            "status": "Denied" if is_denied else random.choices(["Paid", "Pending"], weights=[0.92, 0.08])[0],
            "payer": patient["payer_type"],
        })

    # Create claims from prescriptions
    for rx in prescriptions:
        patient = next(p for p in patients if p["patient_id"] == rx["patient_id"])

        # Pharmacy claims cost less
        billed = random.uniform(20, 300)
        allowed = billed * random.uniform(0.7, 0.95)
        denial_rate = 0.08  # Lower denial rate for pharmacy
        is_denied = random.random() < denial_rate
        paid = 0 if is_denied else allowed * random.uniform(0.80, 1.0)

        claims.append({
            "claim_id": _generate_uuid(),
            "patient_id": rx["patient_id"],
            "service_date": rx["rx_date"],
            "claim_type": "Pharmacy",
            "icd10_code": None,
            "cpt_code": None,
            "ndc_code": rx["ndc_code"],
            "billed_amount": round(billed, 2),
            "allowed_amount": round(allowed, 2),
            "paid_amount": round(paid, 2),
            "deductible_amount": round(min(allowed, random.uniform(0, 50)), 2),
            "copay_amount": round(random.choice([0, 5, 10, 20, 30]), 2),
            "coinsurance_amount": round(allowed * random.uniform(0, 0.1), 2) if not is_denied else 0,
            "status": "Denied" if is_denied else random.choices(["Paid", "Pending"], weights=[0.95, 0.05])[0],
            "payer": patient["payer_type"],
        })

    return claims


def generate_suppliers(
    num_suppliers: int = 25,
    seed: Optional[int] = None
) -> List[Dict]:
    """
    Generate synthetic healthcare supplier/provider organizations.

    Args:
        num_suppliers: Number of suppliers to generate
        seed: Random seed for reproducibility

    Returns:
        List of supplier dictionaries with keys:
            - supplier_id: UUID
            - supplier_name: Organization name
            - supplier_type: One of SUPPLIER_TYPES
            - npi: 10-digit NPI number
            - specialty: Medical specialty (variable)
            - address: Street address
            - state: US state
            - contracts_count: Number of contracts with payers
            - tier: "Tier1" (preferred), "Tier2" (standard), or "Tier3" (limited)
    """
    _seed_random(seed)
    suppliers = []

    supplier_names = [
        "Metropolitan Health", "Sunrise Medical Center", "Valley Hospital",
        "City General Hospital", "Community Care Clinic", "Advanced Specialty Services",
        "Integrated Health Solutions", "Regional Medical Network", "Prime Care Providers",
        "Excellence Healthcare Group", "Connected Care System", "Paramount Health",
        "Heritage Medical Center", "Innovative Health Partners", "Unified Care Providers",
        "Summit Healthcare Group", "Compass Medical Systems", "Alliance Care Network",
        "Beacon Health Services", "Cornerstone Medical", "Progress Healthcare",
        "Harmony Health Systems", "Pacific Medical Group", "Quality Care Partners",
        "Guardian Health Network", "Crown Healthcare Services",
    ]

    specialties = [
        "General Practice", "Cardiology", "Orthopedics", "Oncology", "Neurology",
        "Pulmonology", "Nephrology", "Gastroenterology", "Dermatology", "Psychiatry",
        "Pediatrics", "Obstetrics", "Urology", "Rheumatology", "Endocrinology",
        "Emergency Medicine", "Radiology", "Pathology", "Surgery", "Anesthesiology",
    ]

    for i in range(num_suppliers):
        supplier_id = _generate_uuid()
        name = supplier_names[i % len(supplier_names)] if i < len(supplier_names) else f"Provider {i}"
        supplier_type = random.choice(SUPPLIER_TYPES)
        npi = f"{random.randint(1000000000, 9999999999)}"
        specialty = random.choice(specialties) if supplier_type not in ["DME Supplier", "Diagnostic Laboratory"] else "Medical Supplies"
        address = f"{random.randint(100, 9999)} {random.choice(['Main', 'Oak', 'Elm', 'Healthcare', 'Medical'])} St"
        state = random.choice(US_STATES)
        contracts_count = random.randint(1, 20)
        tier = random.choices(["Tier1", "Tier2", "Tier3"], weights=[0.5, 0.35, 0.15])[0]

        suppliers.append({
            "supplier_id": supplier_id,
            "supplier_name": name,
            "supplier_type": supplier_type,
            "npi": npi,
            "specialty": specialty,
            "address": address,
            "state": state,
            "contracts_count": contracts_count,
            "tier": tier,
        })

    return suppliers


def generate_all_tables(
    num_patients: int = 10000,
    num_suppliers: int = 25,
    seed: Optional[int] = None,
    start_date: str = "2020-01-01",
    end_date: str = "2025-12-31"
) -> Dict[str, List[Dict]]:
    """
    Generate all synthetic RWD tables.

    This is the main entry point for data generation. It orchestrates
    generation of all tables with proper dependencies and correlations.

    Args:
        num_patients: Number of patients to generate
        num_suppliers: Number of suppliers to generate
        seed: Random seed for reproducibility (recommended for testing)
        start_date: Start date for enrollment window (YYYY-MM-DD)
        end_date: End date for data (YYYY-MM-DD)

    Returns:
        Dictionary with keys:
            - 'patients': Patient demographics
            - 'diagnoses': Diagnoses with ICD-10 codes
            - 'prescriptions': Prescriptions with NDC codes
            - 'procedures': Procedures with CPT codes
            - 'claims': Medical, pharmacy, facility claims
            - 'suppliers': Provider organizations

    Example:
        >>> tables = generate_all_tables(num_patients=10000, seed=42)
        >>> print(f"Generated {len(tables['patients'])} patients")
        Generated 10000 patients
        >>> print(f"Generated {len(tables['claims'])} claims")
        Generated 127845 claims
    """
    _seed_random(seed)

    print(f"Generating {num_patients} patients...")
    patients = generate_patients(num_patients, seed)

    print(f"Generating diagnoses...")
    diagnoses = generate_diagnoses(patients, seed)

    print(f"Generating prescriptions...")
    prescriptions = generate_prescriptions(patients, diagnoses, seed)

    print(f"Generating procedures...")
    procedures = generate_procedures(patients, diagnoses, seed)

    print(f"Generating claims...")
    claims = generate_claims(patients, diagnoses, prescriptions, procedures, seed)

    print(f"Generating {num_suppliers} suppliers...")
    suppliers = generate_suppliers(num_suppliers, seed)

    print(f"✓ Data generation complete:")
    print(f"  - {len(patients)} patients")
    print(f"  - {len(diagnoses)} diagnoses")
    print(f"  - {len(prescriptions)} prescriptions")
    print(f"  - {len(procedures)} procedures")
    print(f"  - {len(claims)} claims")
    print(f"  - {len(suppliers)} suppliers")

    return {
        "patients": patients,
        "diagnoses": diagnoses,
        "prescriptions": prescriptions,
        "procedures": procedures,
        "claims": claims,
        "suppliers": suppliers,
    }
