from __future__ import annotations

import json
from pathlib import Path

from contracts.models import ParsedRequest, Venue
from person2_engine.optimizer import rank_candidate_orders
from person2_engine.scheduler import build_schedule, hhmm_to_min
from person2_engine.service import (
    estimate_both_modes_totals,
    plan_multi_day_trip,
    plan_trip,
    recalculate_from_midday,
    replan_with_feedback,
    switch_plan_travel_mode,
)

ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_mock():
    with open(ROOT_DIR / "contracts" / "mock_venues.json", encoding="utf-8") as f:
        venues = [Venue.model_validate(x) for x in json.load(f)]
    with open(ROOT_DIR / "contracts" / "mock_walking_matrix.json", encoding="utf-8") as f:
        matrix = json.load(f)
    with open(ROOT_DIR / "contracts" / "mock_parsed_request.json", encoding="utf-8") as f:
        req = ParsedRequest.model_validate(json.load(f))
    return venues, {v.id: v for v in venues}, matrix, req


def test_slide9_exact_shortest_order():
    _, _, matrix, _ = _load_mock()
    five_stops = [
        "saat_kulesi",
        "arkeoloji_muzesi",
        "sirri_pasa_konagi",
        "seka_kagit_muzesi",
        "kasri_humayun",
    ]
    ranked = rank_candidate_orders("eski_gar", five_stops, "eski_gar", matrix)
    best_min, _, best_seq = ranked[0]
    assert best_min == 49
    assert best_seq == [
        "saat_kulesi",
        "sirri_pasa_konagi",
        "kasri_humayun",
        "arkeoloji_muzesi",
        "seka_kagit_muzesi",
    ]


def test_monday_closed_museums_excluded():
    _, venues_by_id, matrix, req = _load_mock()
    req.day_of_week = "Mon"
    plan = build_schedule(req, venues_by_id, matrix)
    active_ids = {s.venue_id for s in plan.stops}
    assert "arkeoloji_muzesi" not in active_ids
    assert "seka_kagit_muzesi" not in active_ids
    assert "kasri_humayun" not in active_ids
    assert any(d.venue_id == "arkeoloji_muzesi" for d in plan.dropped_venues)


def test_unknown_opening_hours_warning_and_lunch_proximity():
    _, venues_by_id, matrix, req = _load_mock()
    plan = build_schedule(req, venues_by_id, matrix)
    saat_stop = next((s for s in plan.stops if s.venue_id == "saat_kulesi"), None)
    assert saat_stop is not None
    assert saat_stop.opening_hours_status == "unknown"
    assert "Açılış saati bilinmiyor" in saat_stop.opening_hours_label

    lunch_stops = [s for s in plan.stops if s.is_lunch]
    assert len(lunch_stops) == 1
    for opt in lunch_stops[0].restaurant_options:
        assert opt.walk_from_stop_min <= 10
        assert opt.venue_id in venues_by_id


def test_tight_end_time_prunes_overflow_stops():
    _, venues_by_id, matrix, req = _load_mock()
    req.start_time = "09:30"
    req.end_time = "13:00"
    plan = build_schedule(req, venues_by_id, matrix)
    assert hhmm_to_min(plan.actual_end_time) <= hhmm_to_min("13:00")
    assert len(plan.dropped_venues) >= 1


def test_custom_stay_duration_changes_schedule():
    _, venues_by_id, matrix, req = _load_mock()
    plan_default = build_schedule(req, venues_by_id, matrix)
    plan_custom = build_schedule(
        req, venues_by_id, matrix, custom_durations={"saat_kulesi": 45}
    )
    saat_def = next(s for s in plan_default.stops if s.venue_id == "saat_kulesi")
    saat_cus = next(s for s in plan_custom.stops if s.venue_id == "saat_kulesi")
    assert saat_def.stay_min == 15
    assert saat_cus.stay_min == 45


def test_multi_day_accommodation_loop_and_no_duplicates():
    plans = plan_multi_day_trip(
        "Cuma, Cumartesi ve Pazar 3 günlük kültür gezisi yapmak istiyorum.",
        overrides={"num_days": 3, "accommodation_id": "hotel_sekapark"},
    )
    assert len(plans) == 3
    seen_pois = []
    for day_plan in plans:
        assert day_plan.stops[0].venue_id == "hotel_sekapark"
        assert day_plan.stops[-1].venue_id == "hotel_sekapark"
        pois = [
            s.venue_id
            for s in day_plan.stops
            if not s.is_start and not s.is_end and not s.is_lunch
        ]
        assert len(pois) >= 1
        seen_pois.extend(pois)
    assert len(seen_pois) == len(set(seen_pois))


def test_replan_with_feedback_fewer_museums_more_parks():
    initial = plan_trip(
        "Cumartesi 09:30 - 17:00 arası müzeleri gezmek istiyorum."
    )
    alts = replan_with_feedback(
        initial.parsed_request.model_dump(),
        "daha az müze, daha çok park",
    )
    assert len(alts) == 1
    poi_ids = {s.venue_id for s in alts[0].stops}
    assert "sekapark_sahil" in poi_ids


def test_recalculate_from_midday_excludes_completed():
    initial = plan_trip(
        "Cumartesi 09:30 - 17:30 arası müzeleri ve tarihi yapıları görmek istiyorum."
    )
    done_ids = ["arkeoloji_muzesi", "seka_kagit_muzesi", "rest_kultur_tepesi"]
    updated = recalculate_from_midday(
        parsed_request_dict=initial.parsed_request.model_dump(),
        current_venue_id="saat_kulesi",
        current_time="13:30",
        completed_venue_ids=done_ids,
    )
    assert updated.stops[0].venue_id == "saat_kulesi"
    assert updated.stops[0].arrival_time == "13:30"
    stop_ids = {s.venue_id for s in updated.stops}
    assert "arkeoloji_muzesi" not in stop_ids
    assert "seka_kagit_muzesi" not in stop_ids
    assert not any(s.is_lunch for s in updated.stops)


def test_travel_mode_switching_between_walking_and_driving():
    walking_plan = plan_trip(
        "Cumartesi sabah 09:30'da İzmit Eski Tren Garı'ndan başlayıp 17:00'de döneceğim. Müzeleri ve tarihi yapıları görmek istiyorum.",
        overrides={"custom_durations": {"saat_kulesi": 40}},
    )
    assert walking_plan.stops[0].venue_id == "eski_gar"
    assert "yürüme" in walking_plan.summary_text.lower()

    both = estimate_both_modes_totals([s.model_dump() for s in walking_plan.stops])
    assert both["walking"]["duration_min"] == walking_plan.total_walk_min
    assert both["driving"]["duration_min"] > 0
    assert both["driving"]["duration_min"] < both["walking"]["duration_min"]

    driving_plan = switch_plan_travel_mode(walking_plan.model_dump(), "driving")
    assert "araç (araba)" in driving_plan.summary_text.lower()
    assert driving_plan.total_walk_min < walking_plan.total_walk_min
    saat_stop_d = next((s for s in driving_plan.stops if s.venue_id == "saat_kulesi"), None)
    assert saat_stop_d is not None and saat_stop_d.stay_min == 40

    # Geri yürüyüş moduna dönüşte süreler tekrar yürüyüş matrisine döner
    back_to_walk = switch_plan_travel_mode(driving_plan.model_dump(), "walking")
    assert "yürüme" in back_to_walk.summary_text.lower()
    assert back_to_walk.total_walk_min > driving_plan.total_walk_min


def test_driving_mode_still_excludes_monday_closed_museums():
    plans = plan_multi_day_trip(
        "Pazartesi 09:30 - 16:30 arası İzmit Eski Tren Garı'ndan müzeler ve tarihi konakları gezmek istiyorum.",
        travel_mode="driving",
    )
    assert len(plans) == 1
    active_ids = {s.venue_id for s in plans[0].stops}
    assert "arkeoloji_muzesi" not in active_ids
    assert "seka_kagit_muzesi" not in active_ids
    assert "kasri_humayun" not in active_ids
    assert any(d.venue_id == "arkeoloji_muzesi" for d in plans[0].dropped_venues)



