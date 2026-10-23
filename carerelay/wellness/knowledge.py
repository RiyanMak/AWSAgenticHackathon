"""Hand-authored rule tables for the Wellness Agent.

These are prototype rules, not a clinical standard (SAFETY.md). Every table here is
deterministic input to `rules.py`; the LLM never reads or edits them.
"""

from __future__ import annotations

# --- OTC -------------------------------------------------------------------

# Symptom keyword (matched against visit_reason) -> openFDA generic names to consider.
OTC_CANDIDATES: dict[str, list[str]] = {
    "pain": ["ACETAMINOPHEN", "IBUPROFEN", "NAPROXEN SODIUM", "ASPIRIN"],
    "ache": ["ACETAMINOPHEN", "IBUPROFEN", "NAPROXEN SODIUM", "ASPIRIN"],
    "headache": ["ACETAMINOPHEN", "IBUPROFEN", "NAPROXEN SODIUM", "ASPIRIN"],
    "fever": ["ACETAMINOPHEN", "IBUPROFEN"],
    "heartburn": ["FAMOTIDINE", "CALCIUM CARBONATE"],
    "indigestion": ["FAMOTIDINE", "CALCIUM CARBONATE"],
    "cough": ["DEXTROMETHORPHAN HYDROBROMIDE", "GUAIFENESIN"],
}

# Visit-reason words checked against the label's "do not use" text (e.g. dextromethorphan:
# "do not use for persistent or chronic cough such as occurs with smoking ... or emphysema").
VISIT_LABEL_TERMS = ("persistent", "chronic")

# Visit-reason phrases where symptoms need a clinician, not self-care OTC (prototype rule).
# Also switch activity to gentle. Matched as whole words/phrases, case-insensitive.
CARE_FIRST_SYMPTOMS = (
    "chest pain", "pleuritic", "shortness of breath", "short of breath", "dyspnea",
    "head strike", "head injury", "fall", "collision", "trauma", "injury",
    "bleeding", "numbness", "weakness", "fainting", "syncope",
)

# Ingredient -> drug classes it belongs to (used by allergy and class rules).
INGREDIENT_CLASSES: dict[str, set[str]] = {
    "ACETAMINOPHEN": {"acetaminophen"},
    "IBUPROFEN": {"nsaid"},
    "NAPROXEN SODIUM": {"nsaid"},
    "ASPIRIN": {"nsaid", "salicylate", "antiplatelet"},
    "FAMOTIDINE": {"h2_blocker"},
    "CALCIUM CARBONATE": {"antacid"},
    "DEXTROMETHORPHAN HYDROBROMIDE": {"antitussive"},
    "GUAIFENESIN": {"expectorant"},
}

# Allergy keyword (lowercased substring of HistoryProfile.allergies[].display) -> excluded classes.
# Aspirin/NSAID allergy also excludes all NSAIDs: the ibuprofen and naproxen labels warn about
# severe reactions "especially in people allergic to aspirin". Conservative prototype rule.
ALLERGY_CLASSES: dict[str, set[str]] = {
    "aspirin": {"salicylate", "nsaid"},
    "salicylate": {"salicylate", "nsaid"},
    "nsaid": {"nsaid"},
    "ibuprofen": {"nsaid"},
    "naproxen": {"nsaid"},
    "acetaminophen": {"acetaminophen"},
    "paracetamol": {"acetaminophen"},
    "famotidine": {"h2_blocker"},
    "dextromethorphan": {"antitussive"},
    "guaifenesin": {"expectorant"},
}

# Medication keyword (substring of HistoryProfile.medications[].display) -> terms searched for
# in the label's do_not_use / ask_doctor / ask_doctor_or_pharmacist / drug_interactions text.
MEDICATION_LABEL_TERMS: dict[str, list[str]] = {
    "warfarin": ["anticoagulant", "blood thinning"],
    "apixaban": ["anticoagulant", "blood thinning"],
    "rivaroxaban": ["anticoagulant", "blood thinning"],
    "dabigatran": ["anticoagulant", "blood thinning"],
    "heparin": ["anticoagulant", "blood thinning"],
    "enoxaparin": ["anticoagulant", "blood thinning"],
    "clopidogrel": ["anticoagulant", "blood thinning"],
    "aspirin": ["aspirin"],
    "prednisone": ["steroid"],
    "methylprednisolone": ["steroid"],
    "dexamethasone": ["steroid"],
    "furosemide": ["diuretic"],
    "hydrochlorothiazide": ["diuretic"],
    "chlorthalidone": ["diuretic"],
    "spironolactone": ["diuretic"],
    # Class terms only: "blood pressure" would match the label's condition text, which
    # CONDITION_LABEL_TERMS already handles.
    "lisinopril": ["ace inhibitor"],
    "enalapril": ["ace inhibitor"],
    "losartan": ["angiotensin"],
    "lithium": ["lithium"],
    "methotrexate": ["methotrexate"],
}

# Condition keyword (substring of conditions[].display, or a risk flag) -> terms searched in the
# label's "ask a doctor" text. A hit means the label itself says to ask a doctor first.
CONDITION_LABEL_TERMS: dict[str, list[str]] = {
    "hypertension": ["high blood pressure"],
    "high blood pressure": ["high blood pressure"],
    "heart failure": ["heart disease"],
    "coronary": ["heart disease"],
    "heart disease": ["heart disease"],
    "stroke": ["stroke"],
    "asthma": ["asthma"],
    "ulcer": ["stomach", "ulcer"],
    "gastrointestinal bleed": ["stomach bleeding", "bleeding"],
    "kidney": ["kidney disease"],
    "liver": ["liver disease"],
    "cirrhosis": ["liver"],
    "emphysema": ["emphysema"],
    "copd": ["emphysema", "chronic bronchitis"],
    "chronic obstructive": ["emphysema", "chronic bronchitis"],
    "nicotine": ["smoking"],
    "tobacco": ["smoking"],
    "smok": ["smoking"],
}

# Medication keyword -> classes, for duplicate-therapy exclusion (do not add a second NSAID).
MEDICATION_CLASSES: dict[str, set[str]] = {
    "ibuprofen": {"nsaid"},
    "naproxen": {"nsaid"},
    "meloxicam": {"nsaid"},
    "celecoxib": {"nsaid"},
    "diclofenac": {"nsaid"},
    "aspirin": {"nsaid", "salicylate", "antiplatelet"},
    "acetaminophen": {"acetaminophen"},
    "famotidine": {"h2_blocker"},
}

# Lab finding labels (lowercased substrings). SAFETY.md rules 2 and 3.
KIDNEY_LABS = ("creatinine", "egfr", "bun", "urea nitrogen")
LIVER_LABS = ("alt", "ast", "bilirubin", "alkaline phosphatase", "alanine", "aspartate")
NSAID_BLOCKING_LABS = KIDNEY_LABS + ("potassium",)

# HistoryProfile.risk_flags that switch OTC output to "talk to a pharmacist or clinician" only.
OTC_BLOCKING_FLAGS = {"ckd", "liver", "pregnancy", "anticoagulant"}

MIN_OTC_AGE = 18  # prototype rule: pediatric dosing differs per label, so route minors to a pharmacist

# --- Nutrition --------------------------------------------------------------

# Budget staples: shelf-stable, frozen or long-keeping. "Budget" is qualitative; no verified
# price source was reachable (USDA Thrifty Food Plan page, see research report section 7).
# key -> (FoodData Central search query, allergen tags, food group)
STAPLES: dict[str, tuple[str, set[str], str]] = {
    "dried lentils": ("lentils raw", set(), "protein"),
    "dried black beans": ("beans black mature seeds raw", set(), "protein"),
    "eggs": ("egg whole raw fresh", {"egg"}, "protein"),
    "canned tuna in water": ("fish tuna light canned in water drained", {"fish"}, "protein"),
    "firm tofu": ("tofu raw firm", {"soy"}, "protein"),
    "peanut butter, no salt added": ("peanut butter smooth without salt", {"peanut"}, "protein"),
    "rolled oats": ("cereals oats regular and quick not fortified dry", set(), "grain"),
    "brown rice": ("rice brown long-grain raw", set(), "grain"),
    "whole-wheat pasta": ("pasta whole-wheat dry", {"wheat", "gluten"}, "grain"),
    "frozen mixed vegetables": ("vegetables mixed frozen unprepared", set(), "vegetable"),
    "frozen spinach": ("spinach frozen chopped unprepared", set(), "vegetable"),
    "carrots": ("carrots raw", set(), "vegetable"),
    "cabbage": ("cabbage raw", set(), "vegetable"),
    "sweet potatoes": ("sweet potato raw unprepared", set(), "vegetable"),
    "bananas": ("bananas raw", set(), "fruit"),
    "apples": ("apples raw with skin", set(), "fruit"),
    "plain low-fat yogurt": ("yogurt plain low fat", {"milk"}, "dairy"),
}

# Allergy keyword -> allergen tag used in STAPLES.
FOOD_ALLERGENS: dict[str, str] = {
    "peanut": "peanut",
    "egg": "egg",
    "fish": "fish",
    "tuna": "fish",
    "milk": "milk",
    "lactose": "milk",
    "dairy": "milk",
    "soy": "soy",
    "wheat": "wheat",
    "gluten": "gluten",
    "shellfish": "shellfish",  # no staple contains shellfish; mapped so the allergy is still recorded
    "shrimp": "shellfish",
}

HIGH_POTASSIUM_MG_PER_100G = 300  # prototype threshold for the CKD / potassium caution
DASH_SODIUM_MG = 2300
DASH_SODIUM_LOWER_MG = 1500

# --- Activity ---------------------------------------------------------------

# Imaging labels / conditions where we advise only gentle activity until a clinician clears more.
CARDIOPULMONARY_TERMS = (
    "cardiomegaly",
    "effusion",
    "edema",
    "pneumothorax",
    "consolidation",
    "pneumonia",
    "heart failure",
    "angina",
    "arrhythmia",
    "atrial fibrillation",
)

BASE_EXERCISES = [
    {"name": "Walking", "type": "aerobic",
     "how": "Start with 10 minutes at a pace where you can still talk, up to 3 times a day."},
    {"name": "Sit-to-stand", "type": "strength",
     "how": "Stand up from a sturdy chair and sit back down slowly, 8 to 12 times."},
    {"name": "Wall push-ups", "type": "strength",
     "how": "Hands on a wall at shoulder height, bend and straighten the elbows, 8 to 12 times."},
    {"name": "Heel raises", "type": "strength",
     "how": "Holding a counter for balance, rise onto your toes and lower slowly, 10 to 15 times."},
]

SOURCES = {
    "dash": "https://www.nhlbi.nih.gov/education/dash-eating-plan",
    "cdc_activity": "https://www.cdc.gov/physical-activity-basics/guidelines/adults.html",
    "openfda_label": "https://open.fda.gov/apis/drug/label/",
    "fooddata_central": "https://fdc.nal.usda.gov/",
    "orthoinfo_back_pain": "https://www.orthoinfo.org/en/diseases--conditions/low-back-pain/",
}
