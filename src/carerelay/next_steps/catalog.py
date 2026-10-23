"""Finding -> follow-up services, and triage -> due window. A labeled PROTOTYPE rule set, not a guideline.

Patterns are matched against the finding label, site and recommendation (lowercase), most specific first.
Findings no rule matches are left for the Next Steps model (validated against the catalog) or a PCP visit.
"""

from __future__ import annotations

import re

from carerelay.network import net

from .schema import RoutedFinding

FOLLOW_UP_RULES: list[tuple[str, list[str]]] = [
    (r"nonobstructing|non-obstructing", []),   # small stone, no obstruction: known, nothing to book
    (r"adrenal", ["ct_adrenal_protocol", "lab_aldo_renin", "lab_metanephrines", "lab_dex_suppression",
                  "visit_endocrinology"]),
    (r"thyroid", ["us_thyroid", "lab_tsh", "visit_endocrinology"]),
    (r"lung-rads|screening|stable .*nodule", ["ldct_lung_screening"]),
    (r"nodule|lung mass|pulmonary mass", ["ct_chest_wo", "visit_pulmonology"]),
    (r"coronary", ["visit_primary_care", "lab_lipid"]),
    (r"emphysema|hyperinflation|copd", ["pft"]),
    (r"meningioma|extra-axial", ["mri_brain_w_wo"]),
    (r"ascending aort|thoracic aort|aortic root", ["visit_cardiology", "echo_tte", "ct_chest_w"]),
    (r"abdominal aort|aortic aneurysm|aortic ectasia|infrarenal", ["us_aorta", "visit_vascular_surgery"]),
    (r"renal mass|kidney mass|solid.*(renal|kidney)", ["mri_abdomen_renal", "visit_urology"]),
    (r"ovar|adnex", ["us_pelvis", "visit_gynecology"]),
    (r"ureter|uvj|obstructing", ["visit_urology"]),
    (r"cholelithiasis|gallstone|gallbladder", ["visit_general_surgery"]),
    (r"stenosis|anterolisthesis|spondylolisthesis|disc herniation|radiculopathy", ["visit_neurosurgery"]),
    (r"hypercalc|calcium", ["lab_pth_calcium", "visit_primary_care"]),
    (r"steatosis|hypokal|potassium|hyponat|sodium|anemia|hemoglobin|a1c|prediabet|diabet|glucose|ldl|cholesterol"
     r"|lipid|triglycer|blood pressure|hypertension|no pcp|egfr|kidney function|ckd|alt\b|liver enzyme", ["visit_primary_care"]),
]

# Triage -> days from today to the latest acceptable appointment. Watch/none are not booked.
DUE_DAYS = {"urgent": 14, "soon": 60}
TRIAGE_ORDER = ["urgent", "soon", "watch", "none"]


def services_for(finding: RoutedFinding) -> list[str] | None:
    """Services for a finding; [] means a rule matched and nothing is needed, None means no rule matched."""
    text = " ".join(filter(None, [finding.label, finding.site, finding.recommendation])).lower()
    for pattern, services in FOLLOW_UP_RULES:
        if re.search(pattern, text):
            return list(services)
    return None


def catalog() -> dict[str, dict]:
    return net().services()


def valid_services(services: list[str]) -> tuple[list[str], list[str]]:
    """Split into (known, unknown) service ids, keeping order and dropping duplicates."""
    known_ids = catalog()
    known, unknown = [], []
    for s in dict.fromkeys(services):
        (known if s in known_ids else unknown).append(s)
    return known, unknown
