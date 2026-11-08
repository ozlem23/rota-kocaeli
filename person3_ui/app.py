from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pydeck as pdk
import requests
import streamlit as st
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from contracts.models import DAY_LABELS_TR, FinalResponse  # noqa: E402
from person2_engine.scheduler import hhmm_to_min, min_to_hhmm  # noqa: E402
from person2_engine.service import (  # noqa: E402
    get_city_options,
    plan_trip,
    recalculate_trip,
)

load_dotenv(ROOT_DIR / ".env")

MOCK_RESPONSE_PATH = ROOT_DIR / "contracts" / "mock_final_response.json"
DEFAULT_PROMPT = (
    "Cumartesi sabah 09.30'da İzmit Eski Tren Garı'dayım, 17.00'de oraya döneceğim. "
    "Müzeleri ve tarihi yapıları görmek istiyorum. Öğlen köfte veya ev yemekleri molası olsun."
)


def _load_mock_response() -> Dict[str, Any]:
    with open(MOCK_RESPONSE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _fetch_osrm_street_geometry(coords: List[List[float]]) -> List[List[float]]:
    """
    Duraklar arasındaki yürüyüş rotasını OSRM yaya servisinden gerçek sokak kıvrımlarıyla çeker.
    Çevrimdışı veya zaman aşımı durumunda düz çizgi koordinatlarına geri döner.
    """
    if len(coords) < 2:
        return [[float(c[1]), float(c[0])] for c in coords]

    cache_store = st.session_state.setdefault("osrm_geom_cache", {})
    key = ";".join(f"{c[1]:.5f},{c[0]:.5f}" for c in coords)
    if key in cache_store:
        return cache_store[key]

    fallback = [[float(c[1]), float(c[0])] for c in coords]
    if os.getenv("DISABLE_LIVE_OSRM_GEOM", "false").lower() == "true":
        return fallback

    try:
        url = f"https://router.project-osrm.org/route/v1/foot/{key}?overview=full&geometries=geojson"
        resp = requests.get(url, timeout=2.0)
        if resp.status_code == 200:
            data = resp.json()
            routes = data.get("routes", [])
            if routes and routes[0].get("geometry", {}).get("coordinates"):
                geom = routes[0]["geometry"]["coordinates"]
                cache_store[key] = geom
                return geom
    except Exception:
        pass

    cache_store[key] = fallback
    return fallback


def _build_pydeck_map(plan: Dict[str, Any], use_street_routing: bool = False) -> pdk.Deck:
    stops = plan.get("stops", [])
    coords = plan.get("route_coords", [])
    if coords:
        center_lat = sum(c[0] for c in coords) / len(coords)
        center_lon = sum(c[1] for c in coords) / len(coords)
    else:
        center_lat, center_lon = 40.7645, 29.9210

    completed_ids = set(st.session_state.get("completed_stop_ids", []))
    point_rows: List[Dict[str, Any]] = []
    for s in stops:
        if s["venue_id"] in completed_ids and not s.get("is_start") and not s.get("is_end"):
            color = [16, 185, 129, 230]
        elif s.get("is_start") or s.get("is_end"):
            color = [30, 41, 59, 230]
        elif s.get("is_lunch"):
            color = [22, 163, 74, 230]
        elif s.get("opening_hours_status") == "unknown":
            color = [234, 88, 12, 230]
        else:
            color = [37, 99, 235, 230]

        point_rows.append(
            {
                "lon": float(s["lon"]),
                "lat": float(s["lat"]),
                "label": str(s["order"]),
                "title": f"{s['order']}. {s['name']}",
                "info": (
                    f"Varış: {s['arrival_time']} | Kalış: {s['stay_min']} dk | "
                    f"Yürüme: {s['walk_from_prev_min']} dk ({s['walk_from_prev_m']} m)"
                ),
                "color": color,
            }
        )

        if s.get("is_lunch"):
            for opt in s.get("restaurant_options", [])[1:]:
                point_rows.append(
                    {
                        "lon": float(opt["lon"]),
                        "lat": float(opt["lat"]),
                        "label": "Y",
                        "title": f"Alternatif: {opt['name']}",
                        "info": f"Yürüme: {opt['walk_from_stop_min']} dk ({opt['walk_from_stop_m']} m)",
                        "color": [74, 222, 128, 210],
                    }
                )

    layers = []
    if len(coords) >= 2:
        if use_street_routing:
            path_coords = _fetch_osrm_street_geometry(coords)
        else:
            path_coords = [[float(c[1]), float(c[0])] for c in coords]
        path_data = [{"path": path_coords}]
        layers.append(
            pdk.Layer(
                "PathLayer",
                data=path_data,
                get_path="path",
                get_color=[37, 99, 235, 210],
                width_min_pixels=4,
            )
        )

    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            data=point_rows,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius=45,
            radius_min_pixels=10,
            radius_max_pixels=18,
            pickable=True,
        )
    )
    layers.append(
        pdk.Layer(
            "TextLayer",
            data=point_rows,
            get_position="[lon, lat]",
            get_text="label",
            get_size=14,
            get_color=[255, 255, 255, 255],
            get_alignment_baseline="'center'",
        )
    )

    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=14.2,
        pitch=0,
    )
    return pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        tooltip={"text": "{title}\n{info}"},
    )


def _apply_restaurant_choice(plan: Dict[str, Any], chosen_venue_id: str) -> Dict[str, Any]:
    """Kullanıcı öğle yemeği için 2. veya 3. restoranı seçtiğinde planı ve saatleri günceller."""
    new_plan = json.loads(json.dumps(plan))
    stops = new_plan.get("stops", [])
    for idx, s in enumerate(stops):
        if not s.get("is_lunch"):
            continue
        options = s.get("restaurant_options", [])
        chosen = next((o for o in options if o["venue_id"] == chosen_venue_id), None)
        if not chosen or chosen["venue_id"] == s["venue_id"]:
            return new_plan

        old_walk_min = int(s["walk_from_prev_min"])
        old_walk_m = int(s["walk_from_prev_m"])
        new_walk_min = int(chosen["walk_from_stop_min"])
        new_walk_m = int(chosen["walk_from_stop_m"])
        delta_min = new_walk_min - old_walk_min
        delta_m = new_walk_m - old_walk_m

        s["venue_id"] = chosen["venue_id"]
        s["name"] = f"Öğle Yemeği — {chosen['name']}"
        s["lat"] = chosen["lat"]
        s["lon"] = chosen["lon"]
        s["walk_from_prev_min"] = new_walk_min
        s["walk_from_prev_m"] = new_walk_m
        s["opening_hours_status"] = (
            "open" if chosen["opening_hours_status"] == "open" else "unknown"
        )
        s["opening_hours_label"] = chosen["opening_hours_label"]
        s["arrival_time"] = min_to_hhmm(hhmm_to_min(s["arrival_time"]) + delta_min)
        s["departure_time"] = min_to_hhmm(hhmm_to_min(s["departure_time"]) + delta_min)

        for later in stops[idx + 1 :]:
            later["arrival_time"] = min_to_hhmm(hhmm_to_min(later["arrival_time"]) + delta_min)
            later["departure_time"] = min_to_hhmm(
                hhmm_to_min(later["departure_time"]) + delta_min
            )

        if idx < len(new_plan.get("route_coords", [])):
            new_plan["route_coords"][idx] = [chosen["lat"], chosen["lon"]]

        new_plan["total_walk_min"] = max(0, int(new_plan["total_walk_min"]) + delta_min)
        new_plan["total_walk_m"] = max(0, int(new_plan["total_walk_m"]) + delta_m)
        new_plan["total_walk_km"] = round(new_plan["total_walk_m"] / 1000.0, 2)
        new_plan["actual_end_time"] = stops[-1]["arrival_time"]
        break
    return new_plan


def _format_slide5_schedule(plan: Dict[str, Any]) -> str:
    """Slayt 5'teki örnek çıktı formatında sade metin tablosu üretir."""
    lines: List[str] = []
    for s in plan.get("stops", []):
        if s.get("is_start"):
            lines.append(f"{s['arrival_time']}  {s['name']:<38} başlangıç")
        elif s.get("is_end"):
            lines.append(
                f"{s['arrival_time']}  {s['name']:<38} dönüş         önceki duraktan {s['walk_from_prev_min']:>2} dk yürüme ({s['walk_from_prev_m']} m)"
            )
        elif s.get("is_lunch"):
            opt_cnt = len(s.get("restaurant_options", []))
            lines.append(
                f"{s['arrival_time']}  Öğle yemeği ({opt_cnt} restoran önerisi)       {s['stay_min']:>2} dk mola    önceki duraktan {s['walk_from_prev_min']:>2} dk yürüme ({s['walk_from_prev_m']} m)"
            )
            for opt in s.get("restaurant_options", []):
                lines.append(f"       • {opt['name']} ({opt['walk_from_stop_min']} dk yürüme)")
        else:
            lines.append(
                f"{s['arrival_time']}  {s['name']:<38} {s['stay_min']:>2} dk kalış   önceki duraktan {s['walk_from_prev_min']:>2} dk yürüme ({s['walk_from_prev_m']} m)"
            )
    lines.append(f"\nToplam yürüme: {plan['total_walk_min']} dk, {plan['total_walk_km']} km")
    return "\n".join(lines)


def _google_maps_walking_url(plan: Dict[str, Any]) -> str:
    coords = plan.get("route_coords", [])
    if len(coords) < 2:
        return "https://www.google.com/maps"
    origin = f"{coords[0][0]},{coords[0][1]}"
    dest = f"{coords[-1][0]},{coords[-1][1]}"
    middle = coords[1:-1]
    waypoints = "|".join(f"{c[0]},{c[1]}" for c in middle)
    url = f"https://www.google.com/maps/dir/?api=1&travelmode=walking&origin={origin}&destination={dest}"
    if waypoints:
        url += f"&waypoints={waypoints}"
    return url


def main() -> None:
    st.set_page_config(
        page_title="Kocaeli Rota Planlayıcı",
        page_icon="🗺️",
        layout="wide",
    )

    st.session_state.setdefault("plan_cache", {})
    st.session_state.setdefault("request_count", 0)
    st.session_state.setdefault("current_plan", None)
    st.session_state.setdefault("day2_plan", None)
    st.session_state.setdefault("removed_stop_ids", [])
    st.session_state.setdefault("completed_stop_ids", [])

    daily_limit = int(os.getenv("DAILY_LIMIT_PER_SESSION", "15"))

    st.title("🗺️ Kocaeli (İzmit) Akıllı Yürüyüş Rota Planlayıcı")
    st.caption(
        "Dil modeli isteği anlar ve kaynak göstererek anlatır; sıra, yürüyüş süresi ve saatler deterministik kod ile hesaplanır."
    )

    with st.sidebar:
        st.header("Ayarlar ve Kota")
        default_mock = os.getenv("USE_MOCK_UI", "false").lower() == "true"
        use_mock = st.toggle(
            "Mock (Demo) Modu",
            value=default_mock,
            help="Diğer modüller olmadan contracts/mock_final_response.json ile arayüzü test et.",
        )
        use_street_geom = st.toggle(
            "Sokak Kıvrımlı Harita (OSRM)",
            value=False,
            help="Açıldığında harita çizgisi gerçek yaya kaldırımlarını takip eder.",
        )
        st.metric("Oturum İstek Kotası", f"{st.session_state['request_count']} / {daily_limit}")

        st.subheader("Hızlı Örnek İstekler")
        presets = {
            "Klasik İzmit Kültür Turu": DEFAULT_PROMPT,
            "Pazartesi (Kapalı Müze Testi)": (
                "Pazartesi 09:30 - 16:30 arası İzmit Eski Tren Garı'ndan başlayıp müzeleri ve tarihi konakları gezmek istiyorum."
            ),
            "Kısa Tur (Sığmayan Mekan Testi)": (
                "Cumartesi 09:30 - 13:00 arası müze ve tarihi yapıları görmek istiyorum, öğle yemeği olsun."
            ),
            "Sahil ve Balık Turu": (
                "Salı 10:00 - 17:00 arası Seka Park ve sahil yürüyüşü yapıp öğlen balık yemek istiyorum."
            ),
        }
        chosen_preset = st.selectbox("Hazır senaryo seç", list(presets.keys()))
        if st.button("Örneği Kutuya Aktar", width="stretch"):
            st.session_state["prompt_box"] = presets[chosen_preset]

        st.divider()
        st.info(
            "**Kapsam Dışı:** Toplu taşıma ve bilet satın alma desteklenmez. Tüm rotalar Kocaeli (İzmit) içi yaya rotalarıdır."
        )

    city_opts = get_city_options()
    venue_choices = city_opts["venues"]
    venue_id_by_name = {v["name"]: v["id"] for v in venue_choices}
    venue_names = ["(Metinden otomatik algıla)"] + [v["name"] for v in venue_choices]

    with st.form("route_form"):
        user_text = st.text_area(
            "Gezi isteğinizi yazın:",
            value=st.session_state.get("prompt_box", DEFAULT_PROMPT),
            height=90,
        )
        with st.expander("İsteğe Bağlı Detaylı Filtreler (Gün Sayısı, Başlangıç, Saat, Yemek)"):
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                day_choice = st.selectbox(
                    "Haftanın Günü",
                    ["(Metinden)", *list(DAY_LABELS_TR.keys())],
                    format_func=lambda x: DAY_LABELS_TR.get(x, x),
                )
            with c2:
                start_choice = st.selectbox("Başlangıç Noktası", venue_names)
            with c3:
                end_choice = st.selectbox("Bitiş Noktası", venue_names)
            with c4:
                food_override = st.text_input("Yemek Tercihi", placeholder="Örn: köfte, balık, pide")

            t1, t2, t3, t4 = st.columns(4)
            with t1:
                start_time_ov = st.text_input("Başlangıç Saati", placeholder="09:30")
            with t2:
                end_time_ov = st.text_input("Bitiş Saati", placeholder="17:00")
            with t3:
                lunch_ov = st.selectbox("Öğle Yemeği", ["(Metinden)", "Evet", "Hayır"])
            with t4:
                num_days = st.selectbox("Gün Sayısı", [1, 2], index=0)

        submitted = st.form_submit_button("Rota Oluştur", type="primary", width="stretch")

    # Hızlı alternatif plan kısayolları (Slayt 4: Alternatif Plan)
    alt_col1, alt_col2 = st.columns(2)
    alt_mode: Optional[str] = None
    if alt_col1.button("🍃 Alternatif: Daha Çok Park & Sahil, Daha Az Müze", width="stretch"):
        alt_mode = (
            "Cumartesi 09:30 - 16:30 arası İzmit Eski Tren Garı'ndan başlayıp Seka Park, sahil ve camileri gezmek istiyorum, öğlen balık veya kafe olsun."
        )
    if alt_col2.button("🏛️ Alternatif: Osmanlı Konakları & Tarihi Yapılar", width="stretch"):
        alt_mode = (
            "Cumartesi 09:30 - 16:30 arası sadece Sırrı Paşa Konağı, Kasr-ı Hümayun, Saat Kulesi ve Fevziye Camii'ni gezmek istiyorum, öğlen köfte olsun."
        )

    if submitted or alt_mode:
        active_prompt = alt_mode if alt_mode else user_text
        st.session_state["prompt_box"] = active_prompt
        st.session_state["removed_stop_ids"] = []
        st.session_state["completed_stop_ids"] = []
        st.session_state["day2_plan"] = None

        if use_mock and not alt_mode:
            st.session_state["current_plan"] = _load_mock_response()
        else:
            cache_key = json.dumps(
                {
                    "text": active_prompt.strip(),
                    "day": day_choice,
                    "start": start_choice,
                    "end": end_choice,
                    "st": start_time_ov,
                    "et": end_time_ov,
                    "food": food_override,
                    "lunch": lunch_ov,
                    "days": num_days,
                },
                sort_keys=True,
                ensure_ascii=False,
            )
            if cache_key in st.session_state["plan_cache"]:
                cached_bundle = st.session_state["plan_cache"][cache_key]
                st.session_state["current_plan"] = cached_bundle["day1"]
                st.session_state["day2_plan"] = cached_bundle.get("day2")
                st.toast("Aynı istek önbellekten getirildi (API kotası korundu).")
            elif st.session_state["request_count"] >= daily_limit:
                st.error(
                    f"Oturum günlük istek sınırına ({daily_limit}) ulaşıldı. Daha önce üretilen bir planı veya Demo Modu'nu deneyebilirsiniz."
                )
            else:
                overrides: Dict[str, Any] = {}
                if day_choice != "(Metinden)":
                    overrides["day_of_week"] = day_choice
                if start_choice != "(Metinden otomatik algıla)":
                    overrides["start_venue_id"] = venue_id_by_name[start_choice]
                if end_choice != "(Metinden otomatik algıla)":
                    overrides["end_venue_id"] = venue_id_by_name[end_choice]
                if start_time_ov.strip():
                    overrides["start_time"] = start_time_ov.strip()
                if end_time_ov.strip():
                    overrides["end_time"] = end_time_ov.strip()
                if food_override.strip():
                    overrides["food_preference"] = food_override.strip()
                if lunch_ov != "(Metinden)":
                    overrides["want_lunch"] = lunch_ov == "Evet"

                with st.spinner("En az yürüyüşlü rota ve saatler hesaplanıyor..."):
                    res: FinalResponse = plan_trip(active_prompt, overrides=overrides)
                    plan_dict = res.model_dump()
                    day2_dict: Optional[Dict[str, Any]] = None

                    if num_days == 2:
                        day1_pois = {
                            s["venue_id"]
                            for s in plan_dict["stops"]
                            if not s.get("is_start") and not s.get("is_end") and not s.get("is_lunch")
                        }
                        remaining_ids = [
                            v["id"]
                            for v in venue_choices
                            if v["id"] not in day1_pois
                            and v["id"]
                            not in (
                                plan_dict["parsed_request"]["start_venue_id"],
                                plan_dict["parsed_request"]["end_venue_id"],
                            )
                        ]
                        if remaining_ids:
                            day2_req = dict(plan_dict["parsed_request"])
                            day2_req["selected_venue_ids"] = remaining_ids
                            day2_res = recalculate_trip(day2_req, custom_durations={})
                            day2_dict = day2_res.model_dump()

                    st.session_state["plan_cache"][cache_key] = {
                        "day1": plan_dict,
                        "day2": day2_dict,
                    }
                    st.session_state["current_plan"] = plan_dict
                    st.session_state["day2_plan"] = day2_dict
                    st.session_state["request_count"] += 1

    plan = st.session_state.get("current_plan")
    if not plan:
        st.info("Başlamak için yukarıdan **Rota Oluştur** butonuna tıklayın.")
        return

    # Özet metrikler
    m1, m2, m3, m4 = st.columns(4)
    poi_count = sum(
        1
        for s in plan["stops"]
        if not s.get("is_start") and not s.get("is_end") and not s.get("is_lunch")
    )
    m1.metric("Toplam Yürüme", f"{plan['total_walk_min']} dk")
    m2.metric("Toplam Mesafe", f"{plan['total_walk_km']} km")
    m3.metric("Gezilecek Durak", f"{poi_count} mekan")
    m4.metric("Bitiş Saati", f"{plan['actual_end_time']} / {plan['requested_end_time']}")

    if plan.get("summary_text"):
        st.success(plan["summary_text"])

    if plan.get("warnings"):
        warnings_md = "\n".join(f"- {w}" for w in plan["warnings"])
        st.warning(f"⚠️ **Dikkat Edilmesi Gerekenler ve Saat Uyarıları**\n\n{warnings_md}")

    if plan.get("dropped_venues"):
        with st.expander(f"Rotaya Alınamayan / Güne Sığmayan Mekanlar ({len(plan['dropped_venues'])})"):
            for d in plan["dropped_venues"]:
                st.write(f"- **{d['name']}**: {d['reason']}")

    tab_cards, tab_slide5, tab_day2 = st.tabs(
        [
            "🗺️ İnteraktif Plan ve Harita",
            "📋 Slayt 5 Kompakt Çizelge ve Paylaşım",
            "📅 2. Gün Planı (Çoklu Gün)",
        ]
    )

    with tab_cards:
        left_col, right_col = st.columns([1.18, 1.0])

        with left_col:
            st.subheader("🕒 Saat Saat Gezi Planı")
            updated_durations: Dict[str, int] = {}
            completed_ids: List[str] = st.session_state.get("completed_stop_ids", [])

            for idx, s in enumerate(plan["stops"]):
                is_poi = not s.get("is_start") and not s.get("is_end") and not s.get("is_lunch")
                is_done = s["venue_id"] in completed_ids

                with st.container(border=True):
                    top_a, top_b, top_c = st.columns([2.7, 1.1, 1.1])
                    icon = (
                        "✅"
                        if is_done and is_poi
                        else (
                            "🚩"
                            if s.get("is_start")
                            else ("🏁" if s.get("is_end") else ("🍽️" if s.get("is_lunch") else "📍"))
                        )
                    )
                    with top_a:
                        title_str = f"**{s['arrival_time']} – {s['departure_time']} | {icon} {s['name']}**"
                        if is_done and is_poi:
                            st.markdown(f"~~{title_str}~~ *(Tamamlandı)*")
                        else:
                            st.markdown(title_str)
                        walk_txt = (
                            f"Önceki duraktan: **{s['walk_from_prev_min']} dk** ({s['walk_from_prev_m']} m)"
                            if s["order"] > 0
                            else "Başlangıç noktası"
                        )
                        st.caption(f"{walk_txt} • Açılış: `{s['opening_hours_label']}`")

                    with top_b:
                        if is_poi:
                            updated_durations[s["venue_id"]] = st.number_input(
                                "Kalış (dk)",
                                min_value=5,
                                max_value=240,
                                step=5,
                                value=int(s["stay_min"]),
                                key=f"stay_{s['venue_id']}_{s['order']}",
                            )
                        elif s.get("is_lunch"):
                            st.caption(f"Mola: {s['stay_min']} dk")

                    with top_c:
                        if is_poi and not use_mock:
                            done_label = "↩️ Geri Al" if is_done else "✅ Gezdim"
                            if st.button(
                                done_label,
                                key=f"done_{s['venue_id']}_{s['order']}",
                                width="stretch",
                            ):
                                if is_done:
                                    completed_ids.remove(s["venue_id"])
                                else:
                                    completed_ids.append(s["venue_id"])
                                st.session_state["completed_stop_ids"] = completed_ids
                                st.rerun()

                            if st.button(
                                "🗑️ Çıkar",
                                key=f"rm_{s['venue_id']}_{s['order']}",
                                width="stretch",
                            ):
                                removed = list(st.session_state.get("removed_stop_ids", []))
                                removed.append(s["venue_id"])
                                st.session_state["removed_stop_ids"] = removed
                                new_res = recalculate_trip(
                                    parsed_request_dict=plan["parsed_request"],
                                    custom_durations=updated_durations,
                                    removed_venue_ids=removed,
                                )
                                st.session_state["current_plan"] = new_res.model_dump()
                                st.rerun()

                    if s.get("explanation"):
                        src_url = s.get("source_url", "")
                        if src_url:
                            st.write(f"{s['explanation']} [Kaynak]({src_url})")
                        else:
                            st.write(s["explanation"])

                    if s.get("is_lunch") and s.get("restaurant_options"):
                        st.markdown("**🍽️ Öğle Yemeği Yeri Seçimi (≤ 10 dk yürüme):**")
                        opts = s["restaurant_options"]
                        opt_labels = {
                            o["venue_id"]: (
                                f"{o['name']} — {o['walk_from_stop_min']} dk ({o['walk_from_stop_m']} m) "
                                f"• {', '.join(o.get('cuisine_tags', [])[:2])}"
                                f"{' • ' + o['price_range'] if o.get('price_range') else ''}"
                            )
                            for o in opts
                        }
                        current_rest_id = (
                            s["venue_id"] if s["venue_id"] in opt_labels else opts[0]["venue_id"]
                        )
                        chosen_rest_id = st.radio(
                            "Restoran alternatifleri:",
                            options=list(opt_labels.keys()),
                            index=list(opt_labels.keys()).index(current_rest_id),
                            format_func=lambda vid: opt_labels[vid],
                            key=f"lunch_radio_{s['order']}",
                            label_visibility="collapsed",
                        )
                        if chosen_rest_id != s["venue_id"]:
                            st.session_state["current_plan"] = _apply_restaurant_choice(
                                plan, chosen_rest_id
                            )
                            st.rerun()

            if not use_mock and updated_durations:
                bcol1, bcol2 = st.columns(2)
                if bcol1.button(
                    "⏱️ Kalış Sürelerini Güncelle ve Yeniden Hesapla",
                    width="stretch",
                ):
                    new_res = recalculate_trip(
                        parsed_request_dict=plan["parsed_request"],
                        custom_durations=updated_durations,
                        removed_venue_ids=st.session_state.get("removed_stop_ids", []),
                    )
                    st.session_state["current_plan"] = new_res.model_dump()
                    st.rerun()

                if completed_ids and bcol2.button(
                    "📍 Gezilenleri Çıkarıp Kalan Günü Yeniden Planla",
                    width="stretch",
                ):
                    last_done_stop = next(
                        (
                            s
                            for s in reversed(plan["stops"])
                            if s["venue_id"] in completed_ids
                        ),
                        None,
                    )
                    mod_req = dict(plan["parsed_request"])
                    if last_done_stop:
                        mod_req["start_venue_id"] = last_done_stop["venue_id"]
                        mod_req["start_time"] = last_done_stop["departure_time"]
                    all_excluded = list(
                        set(completed_ids + st.session_state.get("removed_stop_ids", []))
                    )
                    new_res = recalculate_trip(
                        parsed_request_dict=mod_req,
                        custom_durations=updated_durations,
                        removed_venue_ids=all_excluded,
                    )
                    st.session_state["completed_stop_ids"] = []
                    st.session_state["current_plan"] = new_res.model_dump()
                    st.rerun()

        with right_col:
            st.subheader("🗺️ Yürüyüş Haritası")
            deck = _build_pydeck_map(plan, use_street_routing=use_street_geom)
            st.pydeck_chart(deck, width="stretch", height=580)
            st.link_button(
                "🧭 Rotayı Google Haritalar'da Yaya Olarak Aç",
                _google_maps_walking_url(plan),
                width="stretch",
            )

    with tab_slide5:
        st.subheader("Slayt 5 Formatında Kompakt Zaman Çizelgesi")
        slide5_text = _format_slide5_schedule(plan)
        st.code(slide5_text, language="text")
        st.download_button(
            "📥 Gezi Planını Metin (.txt) Olarak İndir",
            data=slide5_text,
            file_name="kocaeli_gezi_plani.txt",
            mime="text/plain",
        )

    with tab_day2:
        day2_plan = st.session_state.get("day2_plan")
        if not day2_plan:
            st.info(
                "2 günlük rota görmek için yukarıdaki formda **İsteğe Bağlı Detaylı Filtreler → Gün Sayısı: 2** seçip **Rota Oluştur** butonuna tıklayın."
            )
        else:
            st.subheader("📅 2. Gün Gezi Planı (1. Gün Gezilen Mekanlar Hariç)")
            st.code(_format_slide5_schedule(day2_plan), language="text")
            deck2 = _build_pydeck_map(day2_plan, use_street_routing=use_street_geom)
            st.pydeck_chart(deck2, width="stretch", height=480)


if __name__ == "__main__":
    main()
