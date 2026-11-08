from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from contracts.models import CalculatedPlan, FinalResponse, ParsedRequest, Venue
from person1_data_ai.llm_narrator import narrate_plan
from person1_data_ai.llm_parser import parse_user_request, update_request_with_feedback
from person2_engine.scheduler import build_schedule, hhmm_to_min

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CONTRACTS_DIR = ROOT_DIR / "contracts"

_NEXT_DAY_MAP = {
    "Mon": "Tue",
    "Tue": "Wed",
    "Wed": "Thu",
    "Thu": "Fri",
    "Fri": "Sat",
    "Sat": "Sun",
    "Sun": "Mon",
}
_HUB_CATEGORIES = {"baslangic_bitis", "konaklama"}


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
    """Arayüz için başlangıç/bitiş/konaklama noktalarını, mekanları ve ilgi kategorilerini döndürür."""
    venues, _, _ = load_city_data()
    non_restaurants = [v for v in venues if not v.is_restaurant]
    interests = sorted({tag for v in non_restaurants for tag in v.tags})
    return {
        "city": venues[0].city if venues else "Kocaeli",
        "venues": [{"id": v.id, "name": v.name, "category": v.category} for v in non_restaurants],
        "hotels": [
            {"id": v.id, "name": v.name, "category": v.category}
            for v in non_restaurants
            if v.category == "konaklama"
        ],
        "interests": interests,
    }


def _resolve_plan_days(parsed: ParsedRequest, num_days: int) -> List[str]:
    valid_days = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
    days: List[str] = [d for d in parsed.plan_days if d in valid_days]
    if not days:
        days = [parsed.day_of_week]
    cur = days[-1]
    while len(days) < num_days:
        cur = _NEXT_DAY_MAP.get(cur, "Sun")
        days.append(cur)
    return days[:num_days]


def _partition_pois_for_days(
    candidate_ids: List[str],
    day_codes: List[str],
    venues_by_id: Dict[str, Venue],
) -> List[List[str]]:
    """
    Seçilen durakları coğrafi koridor (batı -> doğu boylam sırası) ve açık gün kurallarına göre
    günlere tekrar etmeyecek şekilde dengeli böler.
    """
    num_days = max(1, len(day_codes))
    unique_ids = [
        vid
        for vid in dict.fromkeys(candidate_ids)
        if vid in venues_by_id
        and not venues_by_id[vid].is_restaurant
        and venues_by_id[vid].category not in _HUB_CATEGORIES
    ]
    # Coğrafi kümeler oluşturmak için boylama (batı -> doğu) göre sırala
    ordered_geo = sorted(unique_ids, key=lambda vid: (venues_by_id[vid].lon, venues_by_id[vid].lat))

    buckets: List[List[str]] = [[] for _ in range(num_days)]
    if not ordered_geo:
        return buckets

    n = len(ordered_geo)
    base, rem = divmod(n, num_days)
    idx = 0
    for d in range(num_days):
        take = base + (1 if d < rem else 0)
        buckets[d] = ordered_geo[idx : idx + take]
        idx += take

    # Eğer günlerden biri Pazartesi (Mon) ise ve başka açık gün varsa, Pazartesi kapalı mekanları diğer günlerle takas et
    non_mon_days = [i for i, dc in enumerate(day_codes) if dc != "Mon"]
    for d, dc in enumerate(day_codes):
        if dc != "Mon" or not non_mon_days:
            continue
        target_d = non_mon_days[0]
        closed_on_mon = [
            vid
            for vid in buckets[d]
            if venues_by_id[vid].opening_hours and "Mon" in venues_by_id[vid].opening_hours.closed_days
        ]
        open_on_mon_elsewhere = [
            vid
            for vid in buckets[target_d]
            if not (venues_by_id[vid].opening_hours and "Mon" in venues_by_id[vid].opening_hours.closed_days)
        ]
        for cvid in closed_on_mon:
            if not open_on_mon_elsewhere:
                break
            swap_vid = open_on_mon_elsewhere.pop(0)
            buckets[d].remove(cvid)
            buckets[d].append(swap_vid)
            buckets[target_d].remove(swap_vid)
            buckets[target_d].append(cvid)

    return buckets


def _attach_narrations(
    calculated: CalculatedPlan,
    venues_dicts: List[Dict[str, object]],
    venues_by_id: Dict[str, Venue],
    allow_llm: bool,
    used_parser_llm: bool,
) -> FinalResponse:
    narration, used_narrator_llm = narrate_plan(
        calculated.model_dump(), venues_dicts, allow_llm=allow_llm
    )
    stop_explanations = narration.get("stop_explanations", {})
    for stop in calculated.stops:
        if stop.venue_id in stop_explanations:
            stop.explanation = stop_explanations[stop.venue_id]
        elif stop.venue_id in venues_by_id:
            stop.explanation = venues_by_id[stop.venue_id].description_short
        if stop.venue_id in venues_by_id and not stop.source_url:
            stop.source_url = venues_by_id[stop.venue_id].source_url

    return FinalResponse(
        **calculated.model_dump(),
        summary_text=narration.get("summary_text", ""),
        used_llm=bool(used_parser_llm or used_narrator_llm),
    )


def _solve_days_from_parsed(
    parsed: ParsedRequest,
    venues: List[Venue],
    venues_by_id: Dict[str, Venue],
    matrix: Dict[str, Dict[str, Dict[str, int]]],
    custom_durations: Optional[Dict[str, int]] = None,
    used_parser_llm: bool = False,
    fill_multi_day_pool: bool = True,
) -> List[FinalResponse]:
    durations = custom_durations or {}
    venues_dicts = [v.model_dump() for v in venues]
    use_narrator_llm = os.getenv("ENABLE_NARRATOR_LLM", "false").lower() == "true"

    num_days = max(1, min(5, int(parsed.num_days or 1)))
    day_codes = _resolve_plan_days(parsed, num_days)

    if num_days == 1:
        calculated = build_schedule(parsed, venues_by_id, matrix, durations)
        return [
            _attach_narrations(
                calculated, venues_dicts, venues_by_id, use_narrator_llm, used_parser_llm
            )
        ]

    all_pois = list(
        vid
        for vid in parsed.selected_venue_ids
        if vid in venues_by_id
        and not venues_by_id[vid].is_restaurant
        and venues_by_id[vid].category not in _HUB_CATEGORIES
    )
    if fill_multi_day_pool and len(all_pois) < num_days * 3:
        for v in venues:
            if not v.is_restaurant and v.category not in _HUB_CATEGORIES and v.id not in all_pois:
                all_pois.append(v.id)

    day_buckets = _partition_pois_for_days(all_pois, day_codes, venues_by_id)

    responses: List[FinalResponse] = []
    # Çok günlük rotada konaklama / başlangıç noktası her günün başlangıç ve bitişi olur
    loop_hub = parsed.start_venue_id
    if venues_by_id.get(parsed.end_venue_id) and venues_by_id[parsed.end_venue_id].category == "konaklama":
        loop_hub = parsed.end_venue_id

    for day_idx, day_code in enumerate(day_codes):
        day_pois = day_buckets[day_idx]
        day_req = parsed.model_copy(
            update={
                "day_of_week": day_code,
                "num_days": num_days,
                "plan_days": day_codes,
                "start_venue_id": loop_hub,
                "end_venue_id": loop_hub,
                "selected_venue_ids": day_pois,
            }
        )
        calc = build_schedule(day_req, venues_by_id, matrix, durations)
        resp = _attach_narrations(
            calc, venues_dicts, venues_by_id, use_narrator_llm, used_parser_llm
        )
        responses.append(resp)

    if len(responses) >= 2:
        responses[0].day2_plan = CalculatedPlan.model_validate(responses[1].model_dump())

    return responses


def plan_multi_day_trip(
    user_text: str, overrides: Optional[Dict[str, object]] = None
) -> List[FinalResponse]:
    """
    1, 2 veya 3+ günlük yürüyüş planlarını liste halinde üretir.
    Her gün aynı optimizasyon ve zamanlama motoru (build_schedule) ile çözülür.
    """
    venues, venues_by_id, matrix = load_city_data()
    venues_dicts = [v.model_dump() for v in venues]

    parsed_dict, used_parser_llm = parse_user_request(
        user_text=user_text,
        venues=venues_dicts,
        overrides=overrides,
    )
    if overrides and overrides.get("accommodation_id"):
        acc_id = str(overrides["accommodation_id"])
        if acc_id in venues_by_id:
            parsed_dict["start_venue_id"] = acc_id
            parsed_dict["end_venue_id"] = acc_id

    parsed = ParsedRequest.model_validate(parsed_dict)

    custom_durations: Dict[str, int] = {}
    if overrides and isinstance(overrides.get("custom_durations"), dict):
        custom_durations = {
            str(k): int(v) for k, v in overrides["custom_durations"].items()
        }

    return _solve_days_from_parsed(
        parsed=parsed,
        venues=venues,
        venues_by_id=venues_by_id,
        matrix=matrix,
        custom_durations=custom_durations,
        used_parser_llm=used_parser_llm,
        fill_multi_day_pool=True,
    )


def plan_trip(user_text: str, overrides: Optional[Dict[str, object]] = None) -> FinalResponse:
    """
    Tek günlük veya 2 günlük ana giriş noktası (Eval 20 ve geriye dönük uyumluluk için).
    Çok günlük tüm planlara erişmek için plan_multi_day_trip() kullanılabilir.
    """
    day_plans = plan_multi_day_trip(user_text, overrides=overrides)
    return day_plans[0]


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
    return _attach_narrations(
        calculated, venues_dicts, venues_by_id, allow_llm=False, used_parser_llm=False
    )


def replan_with_feedback(
    current_parsed_dict: Dict[str, object],
    feedback_text: str,
    custom_durations: Optional[Dict[str, int]] = None,
    removed_venue_ids: Optional[List[str]] = None,
    num_days_override: Optional[int] = None,
    accommodation_id: Optional[str] = None,
) -> List[FinalResponse]:
    """
    Slayt 4 (Alternatif plan): Kullanıcının 'daha az müze, daha çok park' gibi geri bildirimine
    göre kısıtları günceller ve motoru yeniden çalıştırır.
    """
    venues, venues_by_id, matrix = load_city_data()
    venues_dicts = [v.model_dump() for v in venues]

    updated_dict, used_llm = update_request_with_feedback(
        current_parsed_dict, feedback_text, venues_dicts
    )
    if removed_venue_ids:
        rm_set = set(removed_venue_ids)
        updated_dict["selected_venue_ids"] = [
            vid for vid in updated_dict.get("selected_venue_ids", []) if vid not in rm_set
        ]
    if num_days_override is not None:
        updated_dict["num_days"] = max(1, min(5, int(num_days_override)))
    if accommodation_id and accommodation_id in venues_by_id:
        updated_dict["start_venue_id"] = accommodation_id
        updated_dict["end_venue_id"] = accommodation_id

    parsed = ParsedRequest.model_validate(updated_dict)
    return _solve_days_from_parsed(
        parsed=parsed,
        venues=venues,
        venues_by_id=venues_by_id,
        matrix=matrix,
        custom_durations=custom_durations,
        used_parser_llm=used_llm,
        fill_multi_day_pool=False,
    )


def recalculate_from_midday(
    parsed_request_dict: Dict[str, object],
    current_venue_id: str,
    current_time: str,
    completed_venue_ids: List[str],
    custom_durations: Optional[Dict[str, int]] = None,
    removed_venue_ids: Optional[List[str]] = None,
    want_lunch_remaining: Optional[bool] = None,
) -> FinalResponse:
    """
    Slayt 4 (Tamamlandı işareti & Gün ortasında yeni plan):
    Kullanıcının o anki konumunu ve saatini yeni başlangıç noktası yapar,
    tamamlanan/çıkarılan yerleri düşer ve kalan günü aynı hedef bitişe kadar yeniden planlar.
    """
    venues, venues_by_id, matrix = load_city_data()
    venues_dicts = [v.model_dump() for v in venues]

    parsed = ParsedRequest.model_validate(parsed_request_dict)
    if current_venue_id in venues_by_id:
        parsed.start_venue_id = current_venue_id

    clean_time = current_time.strip()
    if not re.match(r"^\d{1,2}:\d{2}$", clean_time):
        clean_time = parsed.start_time
    else:
        hh, mm = clean_time.split(":")
        clean_time = f"{max(0, min(23, int(hh))):02d}:{max(0, min(59, int(mm))):02d}"

    cur_min = hhmm_to_min(clean_time)
    end_min = hhmm_to_min(parsed.end_time)
    if cur_min >= end_min:
        # Gün bitmişse kullanıcıya anlamlı hata yerine 60 dk esnek uzatma veya net uyarı ver
        raise ValueError(
            f"Belirtilen anlık saat ({clean_time}) planlanan bitiş saatinden ({parsed.end_time}) ileri veya eşit."
        )

    parsed.start_time = clean_time

    # Tamamlanan ve çıkarılan durakları kalan listeden temizle
    excluded = set(completed_venue_ids or []) | set(removed_venue_ids or [])
    parsed.selected_venue_ids = [
        vid
        for vid in parsed.selected_venue_ids
        if vid not in excluded and vid not in (parsed.start_venue_id, parsed.end_venue_id)
    ]

    # Öğle yemeği daha önce gezildiyse veya saat öğle penceresini çok geçtiyse tekrar yemek koyma
    already_ate = any(
        vid in venues_by_id and venues_by_id[vid].is_restaurant for vid in (completed_venue_ids or [])
    )
    if want_lunch_remaining is not None:
        parsed.want_lunch = bool(want_lunch_remaining)
    elif already_ate or cur_min > hhmm_to_min(parsed.lunch_window_end) + 15:
        parsed.want_lunch = False

    calculated = build_schedule(parsed, venues_by_id, matrix, custom_durations or {})
    return _attach_narrations(
        calculated, venues_dicts, venues_by_id, allow_llm=False, used_parser_llm=False
    )
