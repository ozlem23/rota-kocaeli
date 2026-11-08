"""
Kişi 1 — Slayt 15: 20 İsteklik Otomatik Sistem Sınaması
Kullanım:
    python -m person1_data_ai.eval_20
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from person2_engine.scheduler import check_opening_hours, hhmm_to_min
from person2_engine.service import load_city_data, plan_trip

HERE = Path(__file__).resolve().parent


def evaluate_single(case: Dict[str, Any], venues_by_id: Dict[str, Any]) -> Dict[str, Any]:
    res = plan_trip(case["prompt"])
    exp = case["expected"]
    stops = res.stops

    # 1. Başlangıç ve bitiş eşleşiyor mu?
    start_ok = bool(stops) and stops[0].venue_id == res.parsed_request.start_venue_id
    end_ok = bool(stops) and stops[-1].venue_id == res.parsed_request.end_venue_id

    # 2. Dönüş saati istenen bitiş saatinden önce/eşit mi?
    time_ok = hhmm_to_min(res.actual_end_time) <= hhmm_to_min(res.requested_end_time)

    # 3. Uydurma mekan yok mu?
    no_hallucination = all(s.venue_id in venues_by_id for s in stops)

    # 4. Kapalı mekan yok mu? (Slayt 11 kritik başarısı)
    no_closed = True
    for s in stops:
        if s.is_start or s.is_end or s.is_lunch:
            continue
        v = venues_by_id[s.venue_id]
        status, _, _ = check_opening_hours(
            v, hhmm_to_min(s.arrival_time), s.stay_min, res.day_of_week
        )
        if status == "closed":
            no_closed = False
            break

    # 5. Yemek önerisi kontrolü (listede var mı & <= 10 dk yürüme mesafesinde mi?)
    lunch_ok = True
    if res.parsed_request.want_lunch and not any(s.is_lunch for s in stops):
        lunch_ok = False
    for s in stops:
        if s.is_lunch:
            if not s.restaurant_options:
                lunch_ok = False
            for opt in s.restaurant_options:
                if opt.venue_id not in venues_by_id or opt.walk_from_stop_min > 10:
                    lunch_ok = False

    # 6. Anlatılan sayılar hesaplananla tutarlı mı?
    numbers_ok = str(res.total_walk_min) in res.summary_text and res.actual_end_time in res.summary_text

    passed = all([start_ok, end_ok, time_ok, no_hallucination, no_closed, lunch_ok, numbers_ok])
    return {
        "id": case["id"],
        "passed": passed,
        "start_end_ok": start_ok and end_ok,
        "time_ok": time_ok,
        "no_hallucination": no_hallucination,
        "no_closed": no_closed,
        "lunch_ok": lunch_ok,
        "numbers_ok": numbers_ok,
        "stops_count": len(stops),
        "walk_min": res.total_walk_min,
        "dropped_count": len(res.dropped_venues),
    }


def main() -> None:
    _, venues_by_id, _ = load_city_data()
    with open(HERE / "test_requests_20.json", encoding="utf-8") as f:
        cases = json.load(f)

    results: List[Dict[str, Any]] = []
    for case in cases:
        r = evaluate_single(case, venues_by_id)
        results.append(r)
        badge = "PASS" if r["passed"] else "FAIL"
        print(
            f"[{badge}] {r['id']} | durak={r['stops_count']} | yurume={r['walk_min']}dk | "
            f"kapali_yok={r['no_closed']} | uydurma_yok={r['no_hallucination']} | yemek={r['lunch_ok']}"
        )

    passed_total = sum(1 for r in results if r["passed"])
    print(f"\nTOPLAM SKOR: {passed_total}/{len(results)} test geçti.")
    if passed_total != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
