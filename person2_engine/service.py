from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from contracts.models import FinalResponse, ParsedRequest, Venue
from person1_data_ai.llm_narrator import narrate_plan
from person1_data_ai.llm_parser import parse_user_request
from person2_engine.scheduler import build_schedule

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CONTRACTS_DIR = ROOT_DIR / "contracts"


def load_city_data() -> Tuple[List[Venue], Dict[str, Venue], Dict[str, Dict[str, Dict[str, int]]]]:
    """Önce data/ klasöründen, yoksa contracts/ altından şehir verisini ve yürüme matrisini yükler."""
    venues_path = DATA_DIR / "venues.json"
    matrix_path = DATA_DIR / "walking_matrix.json"
    if not venues_path.exists():
        venues_path = CONTRACTS_DIR / "mock_venues.json"
    if not matrix_path.exists():
        matrix_path = CONTRACTS_DIR / "mock_walking_matrix.json"

    with open(venues_path, encoding="utf-8") as f:
        raw_venues = json.load(f)
    with open(matrix_path, encoding="utf-8") as f:
        matrix = json.load(f)

    venues = [Venue.model_validate(item) for item in raw_venues]
    venues_by_id = {v.id: v for v in venues}
    return venues, venues_by_id, matrix


def get_city_options() -> Dict[str, object]:
    """Arayüz için başlangıç/bitiş noktaları ve ilgi kategorilerini döndürür."""
    venues, _, _ = load_city_data()
    non_restaurants = [v for v in venues if not v.is_restaurant]
    interests = sorted({tag for v in non_restaurants for tag in v.tags})
    return {
        "city": venues[0].city if venues else "Kocaeli",
        "venues": [{"id": v.id, "name": v.name, "category": v.category} for v in non_restaurants],
        "interests": interests,
    }


def plan_trip(user_text: str, overrides: Optional[Dict[str, object]] = None) -> FinalResponse:
    """
    Arayüzün (Kişi 3) ve testlerin (Kişi 1) çağırdığı TEK ana giriş noktası:
    1. Kişi 1 LLM Ayrıştırıcı -> ParsedRequest
    2. Kişi 2 Optimizasyon & Zamanlama Motoru -> CalculatedPlan
    3. Kişi 1 LLM Anlatıcı -> FinalResponse
    """
    venues, venues_by_id, matrix = load_city_data()
    venues_dicts = [v.model_dump() for v in venues]

    parsed_dict, used_parser_llm = parse_user_request(
        user_text=user_text,
        venues=venues_dicts,
        overrides=overrides,
    )
    parsed = ParsedRequest.model_validate(parsed_dict)

    custom_durations: Dict[str, int] = {}
    if overrides and isinstance(overrides.get("custom_durations"), dict):
        custom_durations = {
            str(k): int(v) for k, v in overrides["custom_durations"].items()
        }

    # 2 Günlük / Çoklu Günlük Planlama Desteği
    if parsed.num_days == 2:
        # Mekanları iki güne dengeli paylaştır (Müzeler/Batı koridoru 1. gün, Konaklar/Camiler/Sahil 2. gün)
        all_pois = list(parsed.selected_venue_ids)
        half = (len(all_pois) + 1) // 2
        day1_pois = all_pois[:half]
        day2_pois = all_pois[half:]

        day1_req = parsed.model_copy(update={"selected_venue_ids": day1_pois, "num_days": 1})
        calculated = build_schedule(day1_req, venues_by_id, matrix, custom_durations)

        next_day_map = {
            "Mon": "Tue", "Tue": "Wed", "Wed": "Thu", "Thu": "Fri", "Fri": "Sat", "Sat": "Sun", "Sun": "Mon"
        }
        day2_day = (
            parsed.plan_days[1]
            if len(parsed.plan_days) >= 2
            else next_day_map.get(parsed.day_of_week, "Sun")
        )

        day2_req = parsed.model_copy(
            update={
                "day_of_week": day2_day,
                "num_days": 1,
                "plan_days": [day2_day],
                "selected_venue_ids": day2_pois,
            }
        )
        day2_calculated = build_schedule(day2_req, venues_by_id, matrix, custom_durations)
        calculated.day2_plan = day2_calculated
    else:
        calculated = build_schedule(parsed, venues_by_id, matrix, custom_durations)

    # LLM kullanımını minimize etmek için anlatım katmanı varsayılan olarak
    # önceden indirilmiş Wikipedia/OSM açıklamalarını ve kesin hesaplanan sayıları kullanır (0 LLM çağrısı).
    use_narrator_llm = os.getenv("ENABLE_NARRATOR_LLM", "false").lower() == "true"
    narration, used_narrator_llm = narrate_plan(
        calculated.model_dump(), venues_dicts, allow_llm=use_narrator_llm
    )

    stop_explanations = narration.get("stop_explanations", {})
    for stop in calculated.stops:
        if stop.venue_id in stop_explanations:
            stop.explanation = stop_explanations[stop.venue_id]
        elif stop.venue_id in venues_by_id:
            stop.explanation = venues_by_id[stop.venue_id].description_short

    return FinalResponse(
        **calculated.model_dump(),
        summary_text=narration.get("summary_text", ""),
        used_llm=bool(used_parser_llm or used_narrator_llm),
    )


def recalculate_trip(
    parsed_request_dict: Dict[str, object],
    custom_durations: Dict[str, int],
    removed_venue_ids: Optional[List[str]] = None,
) -> FinalResponse:
    """
    Arayüzde kalış süresi değiştirildiğinde veya durak çıkarıldığında
    LLM'e tekrar gitmeden milisaniyede rotayı ve saatleri yeniden hesaplar.
    """
    venues, venues_by_id, matrix = load_city_data()
    venues_dicts = [v.model_dump() for v in venues]

    parsed = ParsedRequest.model_validate(parsed_request_dict)
    if removed_venue_ids:
        removed_set = set(removed_venue_ids)
        parsed.selected_venue_ids = [
            vid for vid in parsed.selected_venue_ids if vid not in removed_set
        ]

    calculated = build_schedule(parsed, venues_by_id, matrix, custom_durations)
    narration, _ = narrate_plan(calculated.model_dump(), venues_dicts, allow_llm=False)
    stop_explanations = narration.get("stop_explanations", {})
    for stop in calculated.stops:
        if stop.venue_id in stop_explanations:
            stop.explanation = stop_explanations[stop.venue_id]
        elif stop.venue_id in venues_by_id:
            stop.explanation = venues_by_id[stop.venue_id].description_short

    return FinalResponse(
        **calculated.model_dump(),
        summary_text=narration.get("summary_text", ""),
        used_llm=False,
    )

