"""Read-only clients for openFDA drug labels and USDA FoodData Central.

Only ingredient and food names are sent; never patient identifiers (ARCHITECTURE.md,
"Data flow and PHI handling"). Each client falls back to a bundled snapshot so the
demo still works offline or when the DEMO_KEY rate limit is hit.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
OPENFDA_BASE = os.getenv("OPENFDA_BASE", "https://api.fda.gov")
FDC_BASE = os.getenv("FDC_BASE", "https://api.nal.usda.gov/fdc/v1")
TIMEOUT = httpx.Timeout(15.0)

LABEL_FIELDS = (
    "active_ingredient",
    "purpose",
    "do_not_use",
    "ask_doctor",
    "ask_doctor_or_pharmacist",
    "drug_interactions",
    "when_using",
    "stop_use",
    "pregnancy_or_breast_feeding",
    "warnings",
    "dosage_and_administration",
)


def _trim_label(raw: dict) -> dict:
    openfda = raw.get("openfda", {})
    out = {k: raw[k][0] for k in LABEL_FIELDS if raw.get(k)}
    out.update(
        set_id=raw.get("set_id"),
        effective_time=raw.get("effective_time"),
        brand_name=(openfda.get("brand_name") or [None])[0],
        generic_name=(openfda.get("generic_name") or [None])[0],
        substance_name=openfda.get("substance_name", []),
    )
    return out


def fetch_otc_label_live(generic_name: str, client: httpx.Client | None = None) -> dict | None:
    """Return a trimmed single-ingredient OTC label for `generic_name`, or None."""
    params = {
        # .exact avoids combination products ranking first on the tokenized field
        "search": f'openfda.generic_name.exact:"{generic_name}" AND openfda.product_type:"HUMAN OTC DRUG"',
        "limit": 25,
    }
    if key := os.getenv("OPENFDA_API_KEY"):
        params["api_key"] = key
    c = client or httpx.Client(timeout=TIMEOUT)
    r = c.get(f"{OPENFDA_BASE}/drug/label.json", params=params)
    if r.status_code == 404:  # openFDA returns 404 for no matches
        return None
    r.raise_for_status()
    results = r.json().get("results", [])
    # Prefer single-ingredient labels that carry dosing and "do not use" text
    for raw in results:
        subs = raw.get("openfda", {}).get("substance_name", [])
        if len(subs) == 1 and raw.get("dosage_and_administration") and raw.get("do_not_use"):
            return _trim_label(raw)
    return None


@lru_cache(maxsize=1)
def _label_snapshot() -> dict:
    path = DATA_DIR / "openfda_labels.json"
    return json.loads(path.read_text()) if path.exists() else {}


@lru_cache(maxsize=64)
def get_otc_label(generic_name: str) -> dict | None:
    """Bundled snapshot by default (pinned set_ids: reproducible demos and tests, no egress needed in Lambda).
    CARERELAY_LIVE_APIS=1 tries openFDA live first; CARERELAY_OFFLINE=1 always forces the snapshot."""
    if os.getenv("CARERELAY_LIVE_APIS") == "1" and os.getenv("CARERELAY_OFFLINE") != "1":
        try:
            label = fetch_otc_label_live(generic_name)
            if label:
                label["provenance"] = "openFDA live"
                return label
        except (httpx.HTTPError, ValueError) as e:
            log.warning("openFDA lookup failed for %s, using snapshot: %s", generic_name, e)
    label = _label_snapshot().get(generic_name.upper())
    if label:
        return {**label, "provenance": "openFDA snapshot"}
    return None


FDC_NUTRIENTS = {"208": "kcal", "203": "protein_g", "205": "carbs_g", "291": "fiber_g",
                 "307": "sodium_mg", "306": "potassium_mg"}


def search_food_live(query: str, client: httpx.Client | None = None) -> dict | None:
    """Top Foundation/SR Legacy match for `query`, nutrients per 100 g."""
    params = {"query": query, "pageSize": 1, "dataType": "Foundation,SR Legacy",
              "api_key": os.getenv("FDC_API_KEY", "DEMO_KEY")}
    c = client or httpx.Client(timeout=TIMEOUT)
    r = c.get(f"{FDC_BASE}/foods/search", params=params)
    r.raise_for_status()
    foods = r.json().get("foods", [])
    if not foods:
        return None
    f = foods[0]
    nutrients = {}
    for n in f.get("foodNutrients", []):
        key = FDC_NUTRIENTS.get(str(n.get("nutrientNumber")))
        if key and n.get("value") is not None and n.get("unitName", "").upper() != "KJ":
            nutrients[key] = n["value"]
    return {"fdc_id": f["fdcId"], "description": f["description"], "data_type": f["dataType"],
            "per_100g": nutrients}


@lru_cache(maxsize=1)
def food_snapshot() -> dict:
    """Pinned FoodData Central nutrients for the staple list (see scripts/refresh_wellness_snapshots.py)."""
    path = DATA_DIR / "fdc_staples.json"
    return json.loads(path.read_text()) if path.exists() else {}
