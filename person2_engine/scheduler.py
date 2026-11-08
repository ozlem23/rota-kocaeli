from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from contracts.models import (
    CATEGORY_DEFAULT_STAY_MIN,
    DAY_LABELS_TR,
    CalculatedPlan,
    DroppedVenue,
    ParsedRequest,
    RestaurantOption,
    StopSchedule,
    Venue,
)
from person2_engine.optimizer import get_leg, rank_candidate_orders


def hhmm_to_min(hhmm: str) -> int:
    parts = hhmm.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def min_to_hhmm(total_min: int) -> str:
    total_min = max(0, int(total_min))
    h = (total_min // 60) % 24
    m = total_min % 60
    return f"{h:02d}:{m:02d}"


def _norm_tr(text: str) -> str:
    return (
        text.lower()
        .replace("ı", "i")
        .replace("İ", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )


def check_opening_hours(
    venue: Venue,
    arrival_min: int,
    stay_min: int,
    day_of_week: str,
) -> Tuple[str, str, Optional[str]]:
    """
    Mekanın açılış saati uygunluğunu kontrol eder.
    Dönüş: (status, label, fail_reason_or_none)
      status: 'open' | 'unknown' | 'closed'
    """
    if venue.opening_hours is None:
        return "unknown", "Açılış saati bilinmiyor", None

    oh = venue.opening_hours
    if day_of_week in oh.closed_days:
        day_tr = DAY_LABELS_TR.get(day_of_week, day_of_week)
        return "closed", f"{oh.open_time} - {oh.close_time}", f"{day_tr} günü kapalı"

    open_m = hhmm_to_min(oh.open_time)
    close_m = hhmm_to_min(oh.close_time)
    if arrival_min < open_m:
        return (
            "closed",
            f"{oh.open_time} - {oh.close_time}",
            f"Açılış saati ({oh.open_time}) öncesinde varılıyor",
        )
    if arrival_min + stay_min > close_m:
        return (
            "closed",
            f"{oh.open_time} - {oh.close_time}",
            f"Ziyaret kapanış saatini ({oh.close_time}) aşıyor",
        )
    return "open", f"{oh.open_time} - {oh.close_time}", None


def find_nearby_restaurants(
    anchor_venue_id: str,
    venues_by_id: Dict[str, Venue],
    matrix: Dict[str, Dict[str, Dict[str, int]]],
    food_preference: Optional[str],
    day_of_week: str,
    lunch_arrival_est_min: int,
    lunch_duration_min: int,
    max_walk_min: int = 10,
    limit: int = 3,
) -> List[RestaurantOption]:
    """Öğle saatine denk gelen duraktan <= 10 dk yürüme mesafesindeki restoranları seçer."""
    pref_tokens = [
        _norm_tr(tok)
        for tok in (food_preference or "").replace(",", " ").split()
        if len(tok.strip()) >= 3 and _norm_tr(tok) not in {"veya", "yada", "olsun", "yemek"}
    ]

    candidates: List[Tuple[int, int, RestaurantOption]] = []
    for v in venues_by_id.values():
        if not v.is_restaurant:
            continue
        walk_min, walk_m = get_leg(matrix, anchor_venue_id, v.id)
        if walk_min > max_walk_min:
            continue

        est_arrival = lunch_arrival_est_min + walk_min
        oh_status, oh_label, fail_reason = check_opening_hours(
            v, est_arrival, lunch_duration_min, day_of_week
        )
        if oh_status == "closed":
            continue

        searchable = _norm_tr(
            " ".join([v.name, v.description_short, *v.tags])
        )
        match_score = sum(1 for tok in pref_tokens if tok in searchable)
        option = RestaurantOption(
            venue_id=v.id,
            name=v.name,
            cuisine_tags=v.tags,
            walk_from_stop_min=walk_min,
            walk_from_stop_m=walk_m,
            opening_hours_status=oh_status if oh_status in ("open", "unknown") else "unknown",
            opening_hours_label=oh_label,
            price_range=v.price_range,
            description_short=v.description_short,
            source_url=v.source_url,
            lat=v.lat,
            lon=v.lon,
        )
        # Önce mutfak eşleşmesi yüksek olanlar, sonra yürüme süresi en az olanlar
        candidates.append((-match_score, walk_min, option))

    candidates.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in candidates[:limit]]


def _simulate_order(
    order: List[str],
    parsed: ParsedRequest,
    venues_by_id: Dict[str, Venue],
    matrix: Dict[str, Dict[str, Dict[str, int]]],
    custom_durations: Dict[str, int],
) -> Tuple[bool, Optional[CalculatedPlan], Optional[str], Optional[str]]:
    """
    Belirli bir durak sırasını saat saat simüle eder.
    Dönüş: (basarili_mi, plan, hata_sebebi, sorunlu_venue_id)
    """
    start_v = venues_by_id[parsed.start_venue_id]
    end_v = venues_by_id[parsed.end_venue_id]

    start_min = hhmm_to_min(parsed.start_time)
    end_limit_min = hhmm_to_min(parsed.end_time)
    lunch_win_start = hhmm_to_min(parsed.lunch_window_start)
    lunch_win_end = hhmm_to_min(parsed.lunch_window_end)
    lunch_mid = (lunch_win_start + lunch_win_end) // 2

    def stay_for(v: Venue) -> int:
        if v.id in custom_durations:
            return max(5, int(custom_durations[v.id]))
        return v.default_stay_min or CATEGORY_DEFAULT_STAY_MIN.get(v.category, 30)

    # Eğer öğle yemeği isteniyorsa, [lunch_win_start, lunch_win_end] penceresi içinde
    # öğle ortasına en yakın ve mutfak tercihine uyan duraktan sonrayı seç
    lunch_after_idx: Optional[int] = None
    if parsed.want_lunch:
        t_probe = start_min
        prev_probe = start_v.id
        scored_candidates: List[Tuple[int, int, int, int]] = []
        for idx, vid in enumerate(order):
            w_min, _ = get_leg(matrix, prev_probe, vid)
            t_probe += w_min + stay_for(venues_by_id[vid])
            in_window_rank = 0 if (lunch_win_start <= t_probe <= lunch_win_end) else 1
            time_dist = abs(t_probe - lunch_mid)
            nearby = find_nearby_restaurants(
                anchor_venue_id=vid,
                venues_by_id=venues_by_id,
                matrix=matrix,
                food_preference=parsed.food_preference,
                day_of_week=parsed.day_of_week,
                lunch_arrival_est_min=t_probe,
                lunch_duration_min=parsed.lunch_duration_min,
                max_walk_min=10,
                limit=3,
            )
            pref_penalty = 0 if nearby else 2
            if nearby and parsed.food_preference:
                pref_toks = [_norm_tr(t) for t in parsed.food_preference.split() if len(t) >= 3]
                has_match = any(
                    any(tok in _norm_tr(" ".join([r.name, *r.cuisine_tags])) for tok in pref_toks)
                    for r in nearby
                )
                pref_penalty = 0 if has_match else 1
            scored_candidates.append((in_window_rank, pref_penalty, time_dist, idx))
            prev_probe = vid

        if scored_candidates:
            scored_candidates.sort(key=lambda x: (x[0], x[1], x[2]))
            lunch_after_idx = scored_candidates[0][3]
        else:
            lunch_after_idx = -1

    stops: List[StopSchedule] = []
    warnings: List[str] = []
    route_coords: List[List[float]] = [[start_v.lat, start_v.lon]]
    total_walk_min = 0
    total_walk_m = 0

    # Başlangıç durağı (Order 0)
    stops.append(
        StopSchedule(
            order=0,
            venue_id=start_v.id,
            name=start_v.name,
            category=start_v.category,
            lat=start_v.lat,
            lon=start_v.lon,
            arrival_time=min_to_hhmm(start_min),
            departure_time=min_to_hhmm(start_min),
            stay_min=0,
            walk_from_prev_min=0,
            walk_from_prev_m=0,
            opening_hours_status="start_end",
            opening_hours_label="Başlangıç noktası",
            is_start=True,
            source_name=start_v.source_name,
            source_url=start_v.source_url,
        )
    )

    current_time = start_min
    prev_id = start_v.id
    lunch_inserted = False

    def insert_lunch_step(anchor_id: str) -> Optional[str]:
        nonlocal current_time, prev_id, total_walk_min, total_walk_m, lunch_inserted
        est_lunch_time = current_time
        if current_time < lunch_win_start and (
            lunch_win_start + parsed.lunch_duration_min + 20 <= end_limit_min
        ):
            est_lunch_time = lunch_win_start

        options = find_nearby_restaurants(
            anchor_venue_id=anchor_id,
            venues_by_id=venues_by_id,
            matrix=matrix,
            food_preference=parsed.food_preference,
            day_of_week=parsed.day_of_week,
            lunch_arrival_est_min=est_lunch_time,
            lunch_duration_min=parsed.lunch_duration_min,
            max_walk_min=10,
            limit=3,
        )
        if not options:
            warnings.append(
                f"{venues_by_id[anchor_id].name} çevresinde 10 dk yürüme mesafesinde uygun restoran bulunamadı."
            )
            lunch_inserted = True
            return None

        top_rest = options[0]
        if parsed.food_preference:
            pref_toks = [
                _norm_tr(t)
                for t in parsed.food_preference.replace(",", " ").split()
                if len(t.strip()) >= 3 and _norm_tr(t) not in {"veya", "yada", "olsun", "yemek"}
            ]
            if pref_toks:
                any_matched = any(
                    any(
                        tok in _norm_tr(" ".join([r.name, r.description_short, *r.cuisine_tags]))
                        for tok in pref_toks
                    )
                    for r in options
                )
                if not any_matched:
                    warnings.append(
                        f"Öğle durağının 10 dk yürüme çevresinde '{parsed.food_preference}' tercihine uyan kayıtlı mekan bulunamadığı için en yakın restoranlar önerildi."
                    )

        w_min = top_rest.walk_from_stop_min
        w_m = top_rest.walk_from_stop_m
        arr = max(current_time + w_min, est_lunch_time)
        dep = arr + parsed.lunch_duration_min
        total_walk_min += w_min
        total_walk_m += w_m

        if arr < lunch_win_start or arr > lunch_win_end:
            warnings.append(
                f"Öğle yemeği ({min_to_hhmm(arr)}) istenen {parsed.lunch_window_start}-{parsed.lunch_window_end} aralığının biraz dışına kaydı."
            )

        stops.append(
            StopSchedule(
                order=len(stops),
                venue_id=top_rest.venue_id,
                name=f"Öğle Yemeği — {top_rest.name}",
                category="ogle_yemegi",
                lat=top_rest.lat,
                lon=top_rest.lon,
                arrival_time=min_to_hhmm(arr),
                departure_time=min_to_hhmm(dep),
                stay_min=parsed.lunch_duration_min,
                walk_from_prev_min=w_min,
                walk_from_prev_m=w_m,
                opening_hours_status=(
                    "open" if top_rest.opening_hours_status == "open" else "unknown"
                ),
                opening_hours_label=top_rest.opening_hours_label,
                is_lunch=True,
                restaurant_options=options,
                source_name="OpenStreetMap",
                source_url=top_rest.source_url,
            )
        )
        route_coords.append([top_rest.lat, top_rest.lon])
        current_time = dep
        prev_id = top_rest.venue_id
        lunch_inserted = True
        return None

    if parsed.want_lunch and lunch_after_idx == -1 and not order:
        insert_lunch_step(start_v.id)

    for idx, vid in enumerate(order):
        v = venues_by_id[vid]
        w_min, w_m = get_leg(matrix, prev_id, vid)
        arr = current_time + w_min
        s_min = stay_for(v)
        dep = arr + s_min

        oh_status, oh_label, fail_reason = check_opening_hours(
            v, arr, s_min, parsed.day_of_week
        )
        if oh_status == "closed":
            return False, None, fail_reason, vid

        if oh_status == "unknown":
            warnings.append(f"{v.name}: Açılış saati bilinmiyor")

        total_walk_min += w_min
        total_walk_m += w_m
        stops.append(
            StopSchedule(
                order=len(stops),
                venue_id=v.id,
                name=v.name,
                category=v.category,
                lat=v.lat,
                lon=v.lon,
                arrival_time=min_to_hhmm(arr),
                departure_time=min_to_hhmm(dep),
                stay_min=s_min,
                walk_from_prev_min=w_min,
                walk_from_prev_m=w_m,
                opening_hours_status=oh_status,
                opening_hours_label=oh_label,
                source_name=v.source_name,
                source_url=v.source_url,
            )
        )
        route_coords.append([v.lat, v.lon])
        current_time = dep
        prev_id = v.id

        if parsed.want_lunch and not lunch_inserted and lunch_after_idx == idx:
            insert_lunch_step(v.id)

    if parsed.want_lunch and not lunch_inserted:
        insert_lunch_step(prev_id)

    # Dönüş ayağı
    ret_min, ret_m = get_leg(matrix, prev_id, end_v.id)
    final_arr = current_time + ret_min
    total_walk_min += ret_min
    total_walk_m += ret_m

    if final_arr > end_limit_min:
        last_poi = order[-1] if order else None
        return (
            False,
            None,
            f"Dönüş saati ({min_to_hhmm(final_arr)}) istenen bitiş saatini ({parsed.end_time}) aşıyor",
            last_poi,
        )

    stops.append(
        StopSchedule(
            order=len(stops),
            venue_id=end_v.id,
            name=end_v.name,
            category=end_v.category,
            lat=end_v.lat,
            lon=end_v.lon,
            arrival_time=min_to_hhmm(final_arr),
            departure_time=min_to_hhmm(final_arr),
            stay_min=0,
            walk_from_prev_min=ret_min,
            walk_from_prev_m=ret_m,
            opening_hours_status="start_end",
            opening_hours_label="Dönüş / bitiş noktası",
            is_end=True,
            source_name=end_v.source_name,
            source_url=end_v.source_url,
        )
    )
    route_coords.append([end_v.lat, end_v.lon])

    if parsed.unmatched_notes:
        warnings.extend(parsed.unmatched_notes)

    plan = CalculatedPlan(
        city=parsed.city,
        day_of_week=parsed.day_of_week,
        requested_start_time=parsed.start_time,
        requested_end_time=parsed.end_time,
        actual_end_time=min_to_hhmm(final_arr),
        stops=stops,
        total_walk_min=total_walk_min,
        total_walk_m=total_walk_m,
        total_walk_km=round(total_walk_m / 1000.0, 2),
        warnings=list(dict.fromkeys(warnings)),
        dropped_venues=[],
        route_coords=route_coords,
        parsed_request=parsed,
    )
    return True, plan, None, None


def build_schedule(
    parsed: ParsedRequest,
    venues_by_id: Dict[str, Venue],
    matrix: Dict[str, Dict[str, Dict[str, int]]],
    custom_durations: Optional[Dict[str, int]] = None,
) -> CalculatedPlan:
    """
    Seçilen durakları en kısa yürüyüş sırasına koyar, açılış saatleri ve bitiş saati
    kısıtlarına uymayan durakları çıkararak deterministik planı üretir.
    """
    durations = custom_durations or {}
    dropped: List[DroppedVenue] = []
    global_warnings: List[str] = []

    if parsed.start_venue_id not in venues_by_id:
        parsed.start_venue_id = next(iter(venues_by_id.keys()))
    if parsed.end_venue_id not in venues_by_id:
        parsed.end_venue_id = parsed.start_venue_id

    active_ids: List[str] = []
    for vid in parsed.selected_venue_ids:
        v = venues_by_id.get(vid)
        if not v or v.is_restaurant or vid in (parsed.start_venue_id, parsed.end_venue_id):
            continue
        if v.opening_hours and parsed.day_of_week in v.opening_hours.closed_days:
            day_tr = DAY_LABELS_TR.get(parsed.day_of_week, parsed.day_of_week)
            reason = f"{day_tr} günü kapalı olduğu için rotaya alınmadı"
            dropped.append(DroppedVenue(venue_id=vid, name=v.name, reason=reason))
            global_warnings.append(f"{v.name}: {reason}")
            continue
        if vid not in active_ids:
            active_ids.append(vid)

    # En fazla 8 durak ile sınırla ki gün gerçekçi kalsın; fazlası sığmaz uyarısına düşer
    if len(active_ids) > 8:
        for extra_id in active_ids[8:]:
            ev = venues_by_id[extra_id]
            reason = "Günlük maksimum durak sınırını aştığı için çıkarıldı"
            dropped.append(DroppedVenue(venue_id=extra_id, name=ev.name, reason=reason))
            global_warnings.append(f"{ev.name}: {reason}")
        active_ids = active_ids[:8]

    while True:
        orders = rank_candidate_orders(
            parsed.start_venue_id, active_ids, parsed.end_venue_id, matrix, top_k=50
        )
        best_plan: Optional[CalculatedPlan] = None
        last_fail_reason: Optional[str] = None
        last_fail_vid: Optional[str] = None

        for _, _, order in orders:
            ok, plan, fail_reason, fail_vid = _simulate_order(
                order, parsed, venues_by_id, matrix, durations
            )
            if ok and plan is not None:
                best_plan = plan
                break
            if last_fail_reason is None:
                last_fail_reason = fail_reason
                last_fail_vid = fail_vid

        if best_plan is not None:
            best_plan.dropped_venues = dropped
            best_plan.warnings = list(dict.fromkeys([*global_warnings, *best_plan.warnings]))
            return best_plan

        if not active_ids:
            # Durak kalmadıysa zorunlu başlangıç -> (öğle yemeği) -> bitiş planı
            ok_fb, fallback_plan, _, _ = _simulate_order(
                [], parsed, venues_by_id, matrix, durations
            )
            if not ok_fb or fallback_plan is None:
                no_lunch_req = parsed.model_copy(update={"want_lunch": False})
                _, fallback_plan, _, _ = _simulate_order(
                    [], no_lunch_req, venues_by_id, matrix, durations
                )
                if fallback_plan is not None:
                    global_warnings.append(
                        "Seçilen saat aralığı öğle yemeği molası için yeterli olmadığından mola çıkarıldı."
                    )
            if fallback_plan is not None:
                fallback_plan.dropped_venues = dropped
                fallback_plan.warnings = list(
                    dict.fromkeys([*global_warnings, *fallback_plan.warnings])
                )
                return fallback_plan
            raise RuntimeError("Başlangıç ve bitiş saati aralığı hiç durak için yeterli değil.")

        # Sorunlu durağı çıkar ve yeniden optimize et
        to_remove = last_fail_vid if last_fail_vid in active_ids else active_ids[-1]
        rv = venues_by_id[to_remove]
        reason_text = last_fail_reason or "Güne sığmadığı için çıkarıldı"
        dropped.append(DroppedVenue(venue_id=to_remove, name=rv.name, reason=reason_text))
        global_warnings.append(f"{rv.name}: {reason_text}")
        active_ids.remove(to_remove)
