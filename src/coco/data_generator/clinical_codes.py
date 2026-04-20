"""
Reference data for clinical coding systems.

Contains standardized medical codes and descriptions for:
- ICD-10: Diagnosis codes
- NDC: Drug codes
- CPT: Procedure codes
- LOINC: Laboratory test codes
- Supplier types: Healthcare provider organization classifications

All data is based on actual coding standards but not required to be exhaustive.
Generated data selects randomly from these codes to create realistic claims.
"""

from typing import Dict, List

# ICD-10 Diagnosis Codes (~50 codes across major categories)
ICD10_CODES: Dict[str, str] = {
    # Diabetes mellitus
    "E10.9": "Type 1 diabetes mellitus without complications",
    "E11.9": "Type 2 diabetes mellitus without complications",
    "E11.21": "Type 2 diabetes mellitus with diabetic neuropathy",
    "E11.22": "Type 2 diabetes mellitus with diabetic chronic kidney disease",
    "E11.23": "Type 2 diabetes mellitus with diabetic retinopathy",
    "E13.9": "Other specified diabetes mellitus without complications",

    # Cardiovascular
    "I10": "Essential (primary) hypertension",
    "I11.0": "Hypertensive chronic kidney disease with stage 1 through stage 4 chronic kidney disease, or unspecified chronic kidney disease",
    "I50.9": "Heart failure, unspecified",
    "I50.1": "Left ventricular systolic heart failure",
    "I50.2": "Left ventricular diastolic heart failure",
    "I21.9": "ST elevation (STEMI) myocardial infarction of unspecified site",
    "I21.01": "ST elevation (STEMI) myocardial infarction of left main coronary artery",
    "I21.11": "ST elevation (STEMI) myocardial infarction of left anterior descending coronary artery",
    "I63.9": "Cerebral infarction, unspecified",
    "I64": "Stroke, not specified as hemorrhage or infarction",
    "I71.9": "Aortic aneurysm of unspecified site",
    "I73.9": "Peripheral vascular disease, unspecified",

    # Oncology
    "C34.90": "Unspecified part of unspecified side of lung, malignant neoplasm",
    "C50.91": "Unspecified site of right breast, malignant neoplasm",
    "C50.92": "Unspecified site of left breast, malignant neoplasm",
    "C61": "Malignant neoplasm of prostate",
    "C64.1": "Malignant neoplasm of left kidney, except renal pelvis",
    "C34.11": "Malignant neoplasm of upper lobe, right lung",
    "C80.1": "Malignant (primary) neoplasm, unspecified",

    # Respiratory
    "J44.9": "Chronic obstructive pulmonary disease, unspecified",
    "J44.0": "Chronic obstructive pulmonary disease with (acute) lower respiratory infection",
    "J45.9": "Asthma, unspecified",
    "J45.901": "Unspecified asthma with (acute) exacerbation",
    "J43.9": "Emphysema, unspecified",

    # Musculoskeletal
    "M79.3": "Panniculitis, unspecified",
    "M17.11": "Primary osteoarthritis, right knee",
    "M17.12": "Primary osteoarthritis, left knee",
    "M19.90": "Unspecified osteoarthritis, unspecified site",
    "M54.5": "Low back pain",
    "M79.65": "Pain in limb, foot",
    "M25.5": "Pain in joint",

    # Mental health
    "F32.9": "Major depressive disorder, single episode, unspecified",
    "F33.9": "Major depressive disorder, recurrent, unspecified",
    "F41.1": "Generalized anxiety disorder",
    "F20.9": "Schizophrenia, unspecified",
    "F31.9": "Bipolar disorder, unspecified",

    # Renal
    "N18.3": "Chronic kidney disease, stage 3a",
    "N18.4": "Chronic kidney disease, stage 4",
    "N18.5": "Chronic kidney disease, stage 5",
    "N18.9": "Chronic kidney disease, unspecified",
    "N01.9": "Rapidly progressive nephritic syndrome with unspecified morphologic changes",

    # Infectious diseases
    "B20": "Human immunodeficiency virus (HIV) disease",
    "A41.9": "Sepsis, unspecified",
    "J09.X9": "Influenza due to identified novel influenza A virus with unspecified manifestations",

    # Endocrine
    "E03.9": "Hypothyroidism, unspecified",
    "E05.00": "Thyrotoxicosis with diffuse goiter without thyroid storm",
    "E78.5": "Hyperlipidemia, unspecified",
    "E78.1": "Pure hyperglyceridemia",

    # Other common codes
    "Z79.4": "Long term (current) use of insulin",
    "Z79.01": "Long term (current) use of anticoagulants",
    "R07.9": "Chest pain, unspecified",
}

# NDC Drug Codes (~40 common medications)
NDC_DRUGS: List[Dict[str, str]] = [
    # Antidiabetic agents
    {"ndc_code": "0002-8215-01", "drug_name": "Metformin 500mg", "generic_name": "metformin hydrochloride", "therapeutic_class": "Antidiabetic Agent"},
    {"ndc_code": "0004-0006-01", "drug_name": "Glyburide 5mg", "generic_name": "glyburide", "therapeutic_class": "Antidiabetic Agent"},
    {"ndc_code": "0093-1092-01", "drug_name": "Sitagliptin 100mg", "generic_name": "sitagliptin phosphate", "therapeutic_class": "Antidiabetic Agent"},
    {"ndc_code": "0024-5674-10", "drug_name": "Insulin Glargine 100 unit/mL", "generic_name": "insulin glargine (rDNA origin)", "therapeutic_class": "Antidiabetic Agent"},

    # Antihypertensive agents
    {"ndc_code": "0069-3250-66", "drug_name": "Lisinopril 10mg", "generic_name": "lisinopril", "therapeutic_class": "ACE Inhibitor"},
    {"ndc_code": "0186-0053-54", "drug_name": "Amlodipine 5mg", "generic_name": "amlodipine besylate", "therapeutic_class": "Calcium Channel Blocker"},
    {"ndc_code": "0054-3727-25", "drug_name": "Atenolol 50mg", "generic_name": "atenolol", "therapeutic_class": "Beta Blocker"},
    {"ndc_code": "0069-2710-41", "drug_name": "Losartan 50mg", "generic_name": "losartan potassium", "therapeutic_class": "ARB"},
    {"ndc_code": "0007-5555-20", "drug_name": "Hydrochlorothiazide 25mg", "generic_name": "hydrochlorothiazide", "therapeutic_class": "Thiazide Diuretic"},

    # Antilipidemic agents
    {"ndc_code": "0017-1020-20", "drug_name": "Atorvastatin 20mg", "generic_name": "atorvastatin calcium", "therapeutic_class": "Statin"},
    {"ndc_code": "0007-5555-21", "drug_name": "Atorvastatin 80mg", "generic_name": "atorvastatin calcium", "therapeutic_class": "Statin"},
    {"ndc_code": "0031-3027-30", "drug_name": "Simvastatin 20mg", "generic_name": "simvastatin", "therapeutic_class": "Statin"},
    {"ndc_code": "0069-3250-65", "drug_name": "Rosuvastatin 20mg", "generic_name": "rosuvastatin calcium", "therapeutic_class": "Statin"},

    # Anticoagulants and antiplatelet
    {"ndc_code": "0056-0313-70", "drug_name": "Warfarin 5mg", "generic_name": "warfarin sodium", "therapeutic_class": "Anticoagulant"},
    {"ndc_code": "0007-3327-20", "drug_name": "Aspirin 81mg", "generic_name": "aspirin", "therapeutic_class": "Antiplatelet"},
    {"ndc_code": "0004-0001-11", "drug_name": "Clopidogrel 75mg", "generic_name": "clopidogrel bisulfate", "therapeutic_class": "Antiplatelet"},
    {"ndc_code": "0597-0051-05", "drug_name": "Apixaban 5mg", "generic_name": "apixaban", "therapeutic_class": "DOAC"},

    # Respiratory agents
    {"ndc_code": "0173-0689-00", "drug_name": "Albuterol HFA inhaler", "generic_name": "albuterol sulfate", "therapeutic_class": "Beta 2 Agonist"},
    {"ndc_code": "0173-0681-00", "drug_name": "Fluticasone/Salmeterol inhaler", "generic_name": "fluticasone propionate/salmeterol xinafoate", "therapeutic_class": "ICS/LABA"},
    {"ndc_code": "0173-0699-00", "drug_name": "Tiotropium inhaler", "generic_name": "tiotropium bromide", "therapeutic_class": "LAMA"},

    # Psychiatric medications
    {"ndc_code": "0078-0267-05", "drug_name": "Sertraline 50mg", "generic_name": "sertraline hydrochloride", "therapeutic_class": "SSRI"},
    {"ndc_code": "0172-3701-30", "drug_name": "Escitalopram 10mg", "generic_name": "escitalopram oxalate", "therapeutic_class": "SSRI"},
    {"ndc_code": "0046-1015-25", "drug_name": "Amitriptyline 25mg", "generic_name": "amitriptyline hydrochloride", "therapeutic_class": "TCA"},
    {"ndc_code": "0781-3062-01", "drug_name": "Quetiapine 100mg", "generic_name": "quetiapine fumarate", "therapeutic_class": "Atypical Antipsychotic"},

    # Pain management
    {"ndc_code": "0362-1700-16", "drug_name": "Ibuprofen 400mg", "generic_name": "ibuprofen", "therapeutic_class": "NSAID"},
    {"ndc_code": "0245-0091-11", "drug_name": "Acetaminophen 500mg", "generic_name": "acetaminophen", "therapeutic_class": "Analgesic"},
    {"ndc_code": "0406-0012-01", "drug_name": "Tramadol 50mg", "generic_name": "tramadol hydrochloride", "therapeutic_class": "Opioid"},
    {"ndc_code": "0597-0146-05", "drug_name": "Gabapentin 300mg", "generic_name": "gabapentin", "therapeutic_class": "Neuropathic Pain Agent"},

    # Thyroid agents
    {"ndc_code": "0591-2876-59", "drug_name": "Levothyroxine 75mcg", "generic_name": "levothyroxine sodium", "therapeutic_class": "Thyroid Replacement"},

    # Immunosuppressants and biologics
    {"ndc_code": "0001-2567-50", "drug_name": "Pembrolizumab 100mg vial", "generic_name": "pembrolizumab", "therapeutic_class": "Monoclonal Antibody - Oncology"},
    {"ndc_code": "0075-0646-10", "drug_name": "Trastuzumab 440mg vial", "generic_name": "trastuzumab", "therapeutic_class": "Monoclonal Antibody - Oncology"},
    {"ndc_code": "0074-2248-05", "drug_name": "Adalimumab 40mg prefilled syringe", "generic_name": "adalimumab", "therapeutic_class": "TNF Inhibitor"},

    # Antibiotic
    {"ndc_code": "0028-3162-01", "drug_name": "Amoxicillin 500mg", "generic_name": "amoxicillin trihydrate", "therapeutic_class": "Antibiotic"},
    {"ndc_code": "0007-4107-20", "drug_name": "Ciprofloxacin 500mg", "generic_name": "ciprofloxacin hydrochloride", "therapeutic_class": "Antibiotic"},
]

# CPT Procedure Codes (~30 common procedures)
CPT_CODES: Dict[str, str] = {
    # Office visits
    "99203": "Office visit - established patient, low complexity",
    "99204": "Office visit - established patient, moderate complexity",
    "99205": "Office visit - established patient, high complexity",
    "99213": "Office visit - established patient, low to moderate complexity",
    "99214": "Office visit - established patient, moderate to high complexity",
    "99215": "Office visit - established patient, high complexity",
    "99291": "Critical care, first hour",
    "99292": "Critical care, each additional hour",

    # Laboratory tests
    "80053": "Comprehensive metabolic panel",
    "80055": "Obstetric panel",
    "85025": "Complete blood count with differential",
    "85027": "Complete blood count, automated",
    "82465": "Cholesterol, serum or whole blood total",

    # Imaging
    "71020": "Chest X-ray, 2 views, frontal and lateral",
    "71046": "Chest X-ray, 4 views",
    "73610": "Ankle X-rays, 3 views",
    "76700": "Abdominal ultrasound, real time with image documentation, complete",
    "76705": "Abdominal ultrasound, real time with image documentation, limited",
    "77012": "Computed tomography, head or brain; without contrast material",
    "77013": "Computed tomography, head or brain; with contrast material",
    "70450": "Computed tomography, head or brain; without contrast material",
    "70553": "Magnetic resonance imaging, brain, including brain stem; without contrast material",

    # Cardiac procedures
    "93000": "Electrocardiogram, complete, with interpretation and report",
    "93005": "Electrocardiogram tracing only, without interpretation and report",
    "93040": "Rhythm ECG, 1-3 leads; with interpretation and report",
    "78468": "Myocardial perfusion imaging, stress and rest, single study",

    # Surgery codes
    "99602": "Home visit for the evaluation and management of an established patient",
    "99606": "Home visit for the evaluation and management of a patient",
    "99500": "Home visit for the evaluation and management of a patient",
    "27447": "Total knee replacement with prosthesis",
    "27130": "Total hip replacement with prosthesis",
    "47562": "Laparoscopic cholecystectomy",
}

# LOINC Codes for Laboratory Tests (~20 common tests)
LOINC_CODES: Dict[str, str] = {
    "4548-4": "Hemoglobin A1c [Percent] in Blood",
    "2339-0": "Glucose [Mass/volume] in Blood",
    "2345-7": "Glucose [Mass/volume] in Serum or Plasma",
    "718-7": "Hemoglobin [Mass/volume] in Blood",
    "789-8": "Erythrocyte [Entitic volume] by Automated count",
    "4511-1": "Albumin [Mass/volume] in Serum or Plasma",
    "2160-0": "Creatinine [Mass/volume] in Serum or Plasma",
    "3094-0": "Urea nitrogen [Mass/volume] in Serum or Plasma",
    "2951-2": "Sodium [Moles/volume] in Serum or Plasma",
    "2823-3": "Potassium [Moles/volume] in Serum or Plasma",
    "1975-2": "Bilirubin.total [Mass/volume] in Serum or Plasma",
    "1742-6": "Alanine aminotransferase [Catalytic activity/volume] in Serum or Plasma",
    "1920-8": "Aspartate aminotransferase [Catalytic activity/volume] in Serum or Plasma",
    "2085-9": "Cholesterol [Mass/volume] in Serum or Plasma",
    "2571-8": "Triglyceride [Mass/volume] in Serum or Plasma",
    "18262-6": "Low Density Lipoprotein Cholesterol [Mass/volume] in Serum or Plasma",
    "2093-3": "Cholesterol in High Density Lipoprotein [Mass/volume] in Serum or Plasma",
    "1558-6": "Thyroid stimulating hormone [Moles/volume] in Serum or Plasma",
    "6299-2": "Urine dipstick [Interpretation] in Urine by Automated test strip",
    "5902-2": "Prothrombin time (PT) in Blood",
}

# Supplier/Provider Types
SUPPLIER_TYPES: List[str] = [
    "Hospital System",
    "Specialty Pharmacy",
    "Primary Care Clinic",
    "Specialty Clinic",
    "DME Supplier",
    "Diagnostic Laboratory",
    "Imaging Center",
    "Ambulatory Surgical Center",
    "Urgent Care Center",
    "Emergency Department",
    "Rehabilitation Center",
    "Home Health Agency",
    "Infusion Center",
    "Physical Therapy Clinic",
    "Mental Health Clinic",
    "Retail Pharmacy",
    "Mail Order Pharmacy",
    "Specialty Medical Device",
    "Oncology Center",
    "Cardiology Clinic",
]


def get_icd10_code() -> tuple[str, str]:
    """Return a random ICD-10 code and description."""
    code, description = next(iter(ICD10_CODES.items()))
    return code, description


def get_ndc_drug() -> Dict[str, str]:
    """Return a random NDC drug entry."""
    return NDC_DRUGS[0]


def get_cpt_code() -> tuple[str, str]:
    """Return a random CPT code and description."""
    code, description = next(iter(CPT_CODES.items()))
    return code, description


def get_loinc_code() -> tuple[str, str]:
    """Return a random LOINC code and description."""
    code, description = next(iter(LOINC_CODES.items()))
    return code, description


def get_supplier_type() -> str:
    """Return a random supplier type."""
    return SUPPLIER_TYPES[0]
