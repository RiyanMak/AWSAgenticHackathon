"""Deterministic rule tables for the Lab and Radiology agents.

Critical limits are ILLUSTRATIVE, not an institutional standard (docs/SAFETY.md section 3).
Specialty hints and imaging severity rules are a prototype rule set, not a guideline.
"""

import re

# normalized key -> aliases as they appear on lab reports (lowercase)
ANALYTE_ALIASES: dict[str, list[str]] = {
    "sodium": ["sodium", "na"],
    "potassium": ["potassium", "k"],
    "chloride": ["chloride", "cl"],
    "bicarbonate": ["bicarbonate", "co2", "carbon dioxide", "total co2", "hco3"],
    "bun": ["bun", "urea nitrogen", "blood urea nitrogen"],
    "creatinine": ["creatinine", "creat"],
    "egfr": ["egfr", "estimated gfr", "gfr"],
    "glucose": ["glucose", "glucose, fasting", "fasting glucose", "glu"],
    "hba1c": ["hemoglobin a1c", "hba1c", "a1c", "glycated hemoglobin"],
    "calcium": ["calcium", "ca"],
    "magnesium": ["magnesium", "mg"],
    "total_protein": ["total protein", "protein, total"],
    "albumin": ["albumin"],
    "bilirubin_total": ["total bilirubin", "bilirubin, total", "bilirubin"],
    "alk_phos": ["alkaline phosphatase", "alk phos", "alp"],
    "alt": ["alt", "alanine aminotransferase", "sgpt"],
    "ast": ["ast", "aspartate aminotransferase", "sgot"],
    "lipase": ["lipase"],
    "wbc": ["wbc", "white blood cells", "white blood cell count", "leukocytes"],
    "rbc": ["rbc", "red blood cells", "red blood cell count"],
    "hemoglobin": ["hemoglobin", "hgb", "hb"],
    "hematocrit": ["hematocrit", "hct"],
    "mcv": ["mcv"],
    "platelets": ["platelets", "platelet count", "plt"],
    "pt": ["pt", "prothrombin time"],
    "inr": ["inr"],
    "d_dimer": ["d-dimer", "d dimer"],
    "troponin": ["troponin", "troponin i", "troponin t", "hs-troponin t", "hs troponin t", "hs-troponin i"],
    "bnp": ["bnp", "nt-probnp"],
    "lactate": ["lactate", "lactic acid"],
    "crp": ["crp", "c-reactive protein"],
    "esr": ["esr", "sedimentation rate"],
    "tsh": ["tsh", "thyroid stimulating hormone"],
    "ldl": ["ldl", "ldl cholesterol", "ldl-c"],
    "hdl": ["hdl", "hdl cholesterol", "hdl-c"],
    "triglycerides": ["triglycerides", "trig"],
    "cholesterol_total": ["total cholesterol", "cholesterol", "cholesterol, total"],
    "hcg": ["hcg, serum", "hcg", "hcg, qualitative"],
    "influenza_a": ["influenza a"],
    "influenza_b": ["influenza b"],
    "sars_cov_2": ["sars-cov-2", "covid-19"],
    "rsv": ["rsv"],
    "urine_blood": ["blood, urine", "urine blood"],
    "urine_rbc": ["rbc, urine", "urine rbc"],
    "urine_wbc": ["wbc, urine", "urine wbc"],
    "urine_protein": ["protein, urine", "urine protein"],
    "urine_glucose": ["glucose, urine", "urine glucose"],
    "urine_ketones": ["ketones"],
    "urine_leuk_esterase": ["leukocyte esterase"],
    "urine_nitrite": ["nitrite"],
}

_ALIAS_TO_KEY = {alias: key for key, aliases in ANALYTE_ALIASES.items() for alias in aliases}


def normalize_analyte(name: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9,\- ]", " ", name.lower())).strip(" ,")
    if cleaned in _ALIAS_TO_KEY:
        return _ALIAS_TO_KEY[cleaned]
    # "Potassium, Serum" -> "potassium"
    head = cleaned.split(",")[0].strip()
    return _ALIAS_TO_KEY.get(head)


# key -> (critical_low, critical_high). Crossing one makes the finding "urgent".
CRITICAL_LIMITS: dict[str, tuple[float | None, float | None]] = {
    "sodium": (120, 160),
    "potassium": (2.8, 6.2),
    "glucose": (50, 400),
    "calcium": (6.5, 13.0),
    "hemoglobin": (7.0, 20.0),
    "platelets": (20, 1000),
    "wbc": (2.0, 30.0),
    "inr": (None, 5.0),
    "creatinine": (None, 5.0),
    "lactate": (None, 4.0),
    "troponin": (None, 52),
}

# key -> (red_flag_low, red_flag_high). Severe values that stop wellness output entirely.
RED_FLAG_LIMITS: dict[str, tuple[float | None, float | None]] = {
    "sodium": (115, 165),
    "potassium": (2.5, 6.5),
    "glucose": (40, 500),
    "hemoglobin": (6.0, None),
    "platelets": (10, None),
}

LAB_SPECIALTY: dict[str, str] = {
    "potassium": "nephrology", "sodium": "nephrology", "creatinine": "nephrology",
    "egfr": "nephrology", "bun": "nephrology", "bicarbonate": "nephrology", "urine_protein": "nephrology",
    "glucose": "endocrinology", "hba1c": "endocrinology", "tsh": "endocrinology", "calcium": "endocrinology",
    "hemoglobin": "hematology", "hematocrit": "hematology", "platelets": "hematology", "rbc": "hematology",
    "wbc": "hematology", "inr": "hematology", "pt": "hematology", "d_dimer": "hematology",
    "alt": "gastroenterology", "ast": "gastroenterology", "alk_phos": "gastroenterology",
    "bilirubin_total": "gastroenterology", "albumin": "gastroenterology", "lipase": "gastroenterology",
    "troponin": "cardiology", "bnp": "cardiology",
    "ldl": "primary_care", "hdl": "primary_care", "triglycerides": "primary_care", "cholesterol_total": "primary_care",
    "urine_blood": "urology", "urine_rbc": "urology",
}

SPECIALTIES = [
    "primary_care", "cardiology", "pulmonology", "endocrinology", "nephrology", "urology", "gastroenterology",
    "hematology", "neurology", "neurosurgery", "orthopedics", "gynecology", "vascular_surgery", "oncology",
    "dermatology", "emergency",
]


# Radiology severity. Matched against the finding's label + site + quote (lowercase), positive findings only.
RADIOLOGY_RED_FLAG_TERMS = [
    "tension pneumothorax", "aortic dissection", "intracranial hemorrhage", "subdural hematoma",
    "epidural hematoma", "subarachnoid hemorrhage", "pneumoperitoneum", "free intraperitoneal air",
    "free air", "ruptured", "midline shift",
]
RADIOLOGY_URGENT_TERMS = [
    "pneumothorax", "pulmonary embolism", "pulmonary emboli", "appendicitis", "cholecystitis",
    "bowel obstruction", "acute infarct", "pulmonary edema", "obstructing", "abscess",
    "hydronephrosis", "hydroureteronephrosis",
]


RADIOLOGY_FOLLOW_UP_TERMS = [
    "nodule", "mass", "lesion", "cyst", "aneurysm", "aort", "coronary", "emphysema", "meningioma",
    "stenosis", "hypodens", "adrenal", "thyroid", "stone", "calculus", "steatosis", "consolidation",
    "pneumonia", "effusion", "cardiomegaly", "fracture", "hernia", "hydronephrosis", "enlarged",
]


def _has_term(text: str, term: str) -> bool:
    # term at a word start, so "nonobstructing" / "non-obstructing" do not match "obstructing"
    return re.search(rf"(?<![a-z-]){re.escape(term)}", text) is not None


def radiology_severity(label: str, context: str, size_mm: float | None, recommended: bool = False) -> str:
    """Prototype rules, labeled as ours. The model never sets severity."""
    text = f"{label} {context}".lower()
    if any(_has_term(text, t) for t in RADIOLOGY_RED_FLAG_TERMS):
        return "red_flag"
    if any(_has_term(text, t) for t in RADIOLOGY_URGENT_TERMS):
        return "urgent"
    # solid enhancing/vascular masses: possible malignancy, prompt workup
    if "mass" in text and any(w in text for w in ("solid", "vascular", "enhancing")):
        return "urgent"
    # lung nodule >= 15 mm: high-risk size (our rule; Fleischner covers CT, not radiographs)
    if "nodule" in text and size_mm and size_mm >= 15 and "thyroid" not in text \
            and any(w in text for w in ("lung", "lobe", "pulmonary")):
        return "urgent"
    if any(w in text for w in ("aneurysm", "dilated", "dilatation", "ectasia")) and "aort" in text:
        return "urgent" if size_mm and size_mm >= 55 else "follow_up"
    if recommended or any(_has_term(text, t) for t in RADIOLOGY_FOLLOW_UP_TERMS):
        return "follow_up"
    return "info"


# Local fallback vocabulary: label -> trigger phrases (lowercase, matched on word boundaries).
RADIOLOGY_TERMS: dict[str, list[str]] = {
    "Pneumothorax": ["pneumothorax", "pneumothoraces"],
    "Tension pneumothorax": ["tension pneumothorax"],
    "Intracranial hemorrhage": ["intracranial hemorrhage", "subdural hematoma", "subarachnoid hemorrhage"],
    "Pneumoperitoneum": ["pneumoperitoneum", "free air under the diaphragm", "free intraperitoneal air"],
    "Pulmonary embolism": ["pulmonary embolism", "pulmonary emboli", "filling defect"],
    "Nodule": ["nodule", "nodules", "nodular opacity"],
    "Mass": ["mass", "masses"],
    "Lesion": ["lesion", "lesions", "hypodensity", "hypodensities"],
    "Cyst": ["cyst", "cysts", "cystic"],
    "Stone": ["stone", "stones", "calculus", "calculi", "cholelithiasis", "nephrolithiasis"],
    "Consolidation": ["consolidation", "airspace opacity", "airspace disease"],
    "Pneumonia": ["pneumonia"],
    "Effusion": ["pleural effusion", "pleural effusions", "pericardial effusion", "effusion"],
    "Edema": ["pulmonary edema", "interstitial edema"],
    "Cardiomegaly": ["cardiomegaly", "enlarged cardiac silhouette", "heart is enlarged"],
    "Atelectasis": ["atelectasis"],
    "Emphysema": ["emphysema", "hyperinflation", "hyperinflated"],
    "Bronchial wall thickening": ["bronchial wall thickening"],
    "Fibrosis": ["fibrosis", "interstitial lung disease"],
    "Calcification": ["coronary artery calcification", "calcification", "calcified"],
    "Aortic dilation": ["aneurysm", "dilated", "dilatation", "ectatic", "measures up to"],
    "Steatosis": ["steatosis", "fatty infiltration"],
    "Hematoma": ["hematoma"],
    "Fracture": ["fracture", "fractures"],
    "Stenosis": ["stenosis", "narrowing"],
    "Anterolisthesis": ["anterolisthesis", "spondylolisthesis"],
    "Small vessel ischemic change": ["small vessel ischemic"],
    "Hernia": ["hernia"],
    "Hydronephrosis": ["hydronephrosis", "hydroureter"],
}

# NegEx-lite triggers: these before a term in the same clause negate it.
NEGATION_PRE = [
    "no", "not", "without", "negative for", "free of", "no evidence of", "no signs of",
    "absence of", "resolved", "resolution of", "rules out", "ruled out", "no acute", "no new",
    "clear of", "no focal", "nor", "no other", "no suspicious",
]
# these after a term negate it ("pneumothorax is not seen")
NEGATION_POST = ["is not seen", "are not seen", "not identified", "is absent", "are absent", "has resolved",
                 "have resolved", "not present", "is excluded"]
UNCERTAINTY = ["possible", "possibly", "may represent", "cannot be excluded", "cannot exclude", "can't exclude",
               "suggestive of", "suspicious for", "questionable", "likely", "probable", "probably",
               "concerning for", "versus", "could represent", "equivocal", "not excluded", "most consistent with"]
# clause breakers: a negation does not carry past these
CLAUSE_BREAKS = [" but ", " however ", " although ", " except ", "; ", " which ", " with the exception of ",
                 ". "]
