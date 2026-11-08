from __future__ import annotations

import json
from pathlib import Path

from contracts.models import ParsedRequest, Venue
from person2_engine.optimizer import rank_candidate_orders
from person2_engine.scheduler import build_schedule, hhmm_to_min

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

