import json
from bot import compose_for_test

category = {
    "slug": "dentists",
    "voice": {"tone": "peer_clinical"},
    "peer_stats": {"avg_ctr": 0.030},
    "digest": [{
        "id": "d1",
        "title": "3-mo fluoride recall cuts caries 38% better than 6-mo",
        "source": "JIDA Oct 2026, p.14",
        "trial_n": 2100,
        "patient_segment": "high_risk_adults"
    }]
}
merchant = {
    "merchant_id": "m1",
    "category_slug": "dentists",
    "identity": {"name": "Dr. Meera's Dental Clinic", "owner_first_name": "Meera",
                 "languages": ["en", "hi"]},
    "performance": {"ctr": 0.021},
    "signals": ["high_risk_adult_cohort", "ctr_below_peer_median"]
}
trigger = {
    "id": "t1",
    "kind": "research_digest",
    "scope": "merchant",
    "payload": {"category": "dentists", "top_item_id": "d1"},
    "suppression_key": "research:test"
}
print(json.dumps(compose_for_test(category, merchant, trigger), indent=2, ensure_ascii=False))
