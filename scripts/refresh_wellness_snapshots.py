"""Refresh the bundled openFDA label and FoodData Central snapshots used as offline fallbacks.

Run from the repo root:  python scripts/refresh_wellness_snapshots.py [--force]
Incremental: foods already in the snapshot are skipped unless --force. FoodData Central's
DEMO_KEY allows about 30 requests/hour; set FDC_API_KEY (free from api.data.gov) for more.
"""

import json
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from carerelay.wellness.clients import DATA_DIR, TIMEOUT, fetch_otc_label_live, search_food_live
from carerelay.wellness.knowledge import OTC_CANDIDATES, STAPLES


def main(force: bool = False) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    label_path = DATA_DIR / "openfda_labels.json"
    food_path = DATA_DIR / "fdc_staples.json"
    with httpx.Client(timeout=TIMEOUT) as c:
        labels = json.loads(label_path.read_text()) if label_path.exists() and not force else {}
        for name in sorted({n for names in OTC_CANDIDATES.values() for n in names}):
            if name in labels:
                continue
            label = fetch_otc_label_live(name, c)
            print(f"label {name}: {'ok' if label else 'MISSING'}")
            if label:
                labels[name] = label
        label_path.write_text(json.dumps(labels, indent=1))

        foods = json.loads(food_path.read_text()) if food_path.exists() and not force else {"foods": {}}
        for key, (query, _, _) in STAPLES.items():
            if key in foods["foods"] and foods["foods"][key].get("query") == query:
                continue
            try:
                food = search_food_live(query, c)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    print("FoodData Central rate limit hit; saved progress, rerun later or set FDC_API_KEY")
                    break
                raise
            print(f"food {key}: {food['description'] if food else 'MISSING'}")
            if food:
                foods["foods"][key] = {**food, "query": query}
        foods["retrieved"] = date.today().isoformat()
        food_path.write_text(json.dumps(foods, indent=1))
    missing = [k for k in STAPLES if k not in foods["foods"]]
    print(f"labels: {len(labels)}, foods: {len(foods['foods'])}/{len(STAPLES)}, missing: {missing}")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
