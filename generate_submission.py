from __future__ import annotations
import json
from pathlib import Path
from bot import compose_for_test

ROOT = Path(__file__).parent
DATA = ROOT / "data"

def load_json(name):
    with open(DATA / name, encoding="utf-8") as f:
        return json.load(f)

def main():
    categories = {}
    # The challenge package may contain all five category JSON files.
    for p in (DATA / "categories").glob("*.json"):
        obj = load_json("categories/" + p.name)
        categories[obj["slug"]] = obj

    merchants = load_json("merchants_seed.json").get("merchants", [])
    customers = load_json("customers_seed.json").get("customers", [])
    triggers = load_json("triggers_seed.json").get("triggers", [])

    merchants_by_id = {m["merchant_id"]: m for m in merchants}
    customers_by_id = {c["customer_id"]: c for c in customers}

    # Use the trigger set as the portable source of candidate examples.
    # If a supplied challenge package contains a canonical 30-pair list,
    # replace/select from that list here.
    rows = []
    for i, trg in enumerate(triggers[:30], 1):
        mid = trg.get("merchant_id")
        merchant = merchants_by_id.get(mid)
        if not merchant:
            continue
        slug = merchant.get("category_slug")
        category = categories.get(slug)
        if not category:
            continue
        customer = customers_by_id.get(trg.get("customer_id"))
        result = compose_for_test(category, merchant, trg, customer)
        rows.append({
            "test_id": f"T{i:02d}",
            "body": result["body"],
            "cta": result["cta"],
            "send_as": result["send_as"],
            "suppression_key": result["suppression_key"],
            "rationale": result["rationale"]
        })

    with open(ROOT / "submission.jsonl", "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Wrote {len(rows)} submission rows.")

if __name__ == "__main__":
    main()
