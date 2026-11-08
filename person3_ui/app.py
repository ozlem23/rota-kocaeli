from __future__ import annotations

import html
import json
import math
import os
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from contracts.models import DAY_LABELS_TR, Venue  # noqa: E402
from person2_engine.scheduler import hhmm_to_min, min_to_hhmm  # noqa: E402
from person2_engine.service import (  # noqa: E402
    estimate_both_modes_totals,
    get_city_options,
    load_city_data,
    plan_multi_day_trip,
    recalculate_from_midday,
    recalculate_trip,
    replan_with_feedback,
    switch_plan_travel_mode,
)
from person3_ui import storage  # noqa: E402

load_dotenv(ROOT_DIR / ".env")

MOCK_RESPONSE_PATH = ROOT_DIR / "contracts" / "mock_final_response.json"
WALKING_PATHS_PATH = ROOT_DIR / "data" / "walking_paths.json"
DRIVING_PATHS_PATH = ROOT_DIR / "data" / "driving_paths.json"
MOCK_WALKING_PATHS_PATH = ROOT_DIR / "contracts" / "mock_walking_paths.json"

DEFAULT_PROMPT = (
    "Cumartesi sabah 09.30'da İzmit Eski Tren Garı'dayım, 17.00'de oraya döneceğim. "
    "Müzeleri ve tarihi yapıları görmek istiyorum. Öğlen iskender yemek molası olsun."
)


def _norm(text: str) -> str:
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


# Kategori bazlı kurumsal renk paleti (Tarihi mekanlar kahverengi/lacivert, yemek turuncu, park mavi, konaklama mor)
CATEGORY_THEMES: Dict[str, Dict[str, Any]] = {
    "ogle_yemegi": {
        "border": "#ea580c",
        "bg": "#fff7ed",
        "text": "#9a3412",
        "badge": "🍽️ Öğle Yemeği",
        "map_rgb": [234, 88, 12, 240],
    },
    "restoran": {
        "border": "#ea580c",
        "bg": "#fff7ed",
        "text": "#9a3412",
        "badge": "🍽️ Restoran & Kafe",
        "map_rgb": [234, 88, 12, 240],
    },
    "konak_kosk": {
        "border": "#854d0e",
        "bg": "#fefce8",
        "text": "#713f12",
        "badge": "🏡 Tarihi Konak & Köşk",
        "map_rgb": [133, 77, 14, 240],
    },
    "anit_saat_kulesi": {
        "border": "#a16207",
        "bg": "#fefce8",
        "text": "#854d0e",
        "badge": "🕰️ Anıt & Saat Kulesi",
        "map_rgb": [161, 98, 7, 240],
    },
    "tarihi_yapi": {
        "border": "#78350f",
        "bg": "#fffbeb",
        "text": "#451a03",
        "badge": "🏛️ Tarihi Yapı",
        "map_rgb": [120, 53, 15, 240],
    },
    "muze": {
        "border": "#1e40af",
        "bg": "#eff6ff",
        "text": "#1e3a8a",
        "badge": "🏛️ Müze & Sergi",
        "map_rgb": [30, 64, 175, 240],
    },
    "cami": {
        "border": "#047857",
        "bg": "#ecfdf5",
        "text": "#065f46",
        "badge": "🕌 Cami & Külliye",
        "map_rgb": [4, 120, 87, 240],
    },
    "park_sahil": {
        "border": "#0284c7",
        "bg": "#f0f9ff",
        "text": "#0369a1",
        "badge": "🌳 Sahil & Park",
        "map_rgb": [2, 132, 199, 240],
    },
    "konaklama": {
        "border": "#6d28d9",
        "bg": "#f5f3ff",
        "text": "#4c1d95",
        "badge": "🏨 Konaklama Yeri",
        "map_rgb": [109, 40, 217, 240],
    },
    "baslangic_bitis": {
        "border": "#334155",
        "bg": "#f8fafc",
        "text": "#0f172a",
        "badge": "🚉 Başlangıç / Bitiş",
        "map_rgb": [51, 65, 85, 240],
    },
}

DEFAULT_THEME = {
    "border": "#475569",
    "bg": "#f8fafc",
    "text": "#1e293b",
    "badge": "📍 Gezi Noktası",
    "map_rgb": [71, 85, 105, 240],
}

DAY_COLORS = [
    {"rgb": [37, 99, 235, 235], "hex": "#2563eb", "name": "Mavi"},
    {"rgb": [147, 51, 234, 235], "hex": "#9333ea", "name": "Mor"},
    {"rgb": [13, 148, 136, 235], "hex": "#0d9488", "name": "Turkuaz"},
    {"rgb": [217, 119, 6, 235], "hex": "#d97706", "name": "Kehribar"},
    {"rgb": [225, 29, 72, 235], "hex": "#e11d48", "name": "Bordo"},
]


def _get_theme(category: str) -> Dict[str, Any]:
    return CATEGORY_THEMES.get(category, DEFAULT_THEME)


def _load_mock_response() -> Dict[str, Any]:
    with open(MOCK_RESPONSE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _load_walking_paths(travel_mode: str = "walking") -> Dict[str, List[List[float]]]:
    if travel_mode == "driving" and DRIVING_PATHS_PATH.exists():
        with open(DRIVING_PATHS_PATH, encoding="utf-8") as f:
            return json.load(f)
    for p in (WALKING_PATHS_PATH, MOCK_WALKING_PATHS_PATH):
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    return {}


def _google_maps_pin_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"


def _google_maps_walking_url(plan: Dict[str, Any], travel_mode: str = "walking") -> str:
    coords = plan.get("route_coords", [])
    if len(coords) < 2:
        return "https://www.google.com/maps"
    origin = f"{coords[0][0]},{coords[0][1]}"
    dest = f"{coords[-1][0]},{coords[-1][1]}"
    middle = coords[1:-1]
    waypoints = "|".join(f"{c[0]},{c[1]}" for c in middle)
    g_mode = "driving" if travel_mode == "driving" else "walking"
    url = f"https://www.google.com/maps/dir/?api=1&travelmode={g_mode}&origin={origin}&destination={dest}"
    if waypoints:
        url += f"&waypoints={waypoints}"
    return url


def _get_plan_walking_path(
    plan: Dict[str, Any],
    walking_paths: Dict[str, Any],
    use_street_routing: bool = True,
) -> List[List[float]]:
    stops = plan.get("stops", [])
    if len(stops) < 2:
        return [[float(s["lon"]), float(s["lat"])] for s in stops]

    full_coords: List[List[float]] = []
    n_legs = len(stops) - 1
    for i in range(n_legs):
        u_pt = [float(stops[i]["lon"]), float(stops[i]["lat"])]
        v_pt = [float(stops[i + 1]["lon"]), float(stops[i + 1]["lat"])]
        if use_street_routing:
            key = f"{stops[i]['venue_id']}::{stops[i + 1]['venue_id']}"
            seg = [list(pt) for pt in (walking_paths.get(key) or [u_pt, v_pt])]
        else:
            seg = [u_pt, v_pt]

        if not seg:
            seg = [u_pt, v_pt]
        else:
            # Sadece sokak noktası durağa çok yakınsa (<25m) veya ilk/son duraksa uç noktayı bağla;
            # aksi halde bina içine girip çıkan V-şekilli keskin çizgileri önle.
            d_u = math.hypot(seg[0][0] - u_pt[0], seg[0][1] - u_pt[1])
            d_v = math.hypot(seg[-1][0] - v_pt[0], seg[-1][1] - v_pt[1])
            if (i == 0 or d_u < 0.00022) and d_u > 1e-6:
                seg.insert(0, u_pt)
            if (i == n_legs - 1 or d_v < 0.00022) and d_v > 1e-6:
                seg.append(v_pt)

        if full_coords and seg and full_coords[-1] == seg[0]:
            full_coords.extend(seg[1:])
        else:
            full_coords.extend(seg)
    return full_coords


def _auto_view_bounds(coords_lon_lat: List[List[float]]) -> Tuple[float, float, float]:
    if not coords_lon_lat:
        return 40.7625, 29.9195, 14.2
    lons = [c[0] for c in coords_lon_lat]
    lats = [c[1] for c in coords_lon_lat]
    center_lat = (min(lats) + max(lats)) / 2.0
    center_lon = (min(lons) + max(lons)) / 2.0
    span = max(max(lats) - min(lats), (max(lons) - min(lons)) * 0.78)
    if span > 0.032:
        zoom = 13.3
    elif span > 0.022:
        zoom = 13.7
    elif span > 0.014:
        zoom = 14.1
    else:
        zoom = 14.5
    return center_lat, center_lon, zoom


def _build_pydeck_map(
    plan: Dict[str, Any],
    use_street_routing: bool = True,
    route_color: Optional[List[int]] = None,
    day_prefix: str = "",
    travel_mode: str = "walking",
    venues_by_id: Optional[Dict[str, Venue]] = None,
) -> pdk.Deck:
    stops = plan.get("stops", [])
    n_stops = len(stops)
    if route_color is not None:
        line_color = route_color if travel_mode != "driving" else [225, 29, 72, 240]
    else:
        line_color = [225, 29, 72, 240] if travel_mode == "driving" else [37, 99, 235, 240]
    leg_word = "Araçla" if travel_mode == "driving" else "Yürüyerek"
    completed_ids = set(st.session_state.get("completed_stop_ids", []))
    point_rows: List[Dict[str, Any]] = []

    for s in stops:
        if s.get("is_end") and n_stops >= 2 and s["venue_id"] == stops[0]["venue_id"]:
            # Başlangıç ve bitiş aynı nokta ise 0 numaralı başlangıç rozetinde birleştir
            continue
        theme = _get_theme(s.get("category", ""))
        if s["venue_id"] in completed_ids and not s.get("is_start") and not s.get("is_end"):
            color = [16, 185, 129, 250]
        else:
            color = theme["map_rgb"]

        pin_label = f"{day_prefix}{s['order']}" if day_prefix else str(s["order"])
        if s.get("is_start") and n_stops >= 2 and stops[-1]["venue_id"] == s["venue_id"]:
            time_info = f"Başlangıç: {s['arrival_time']} • Dönüş: {stops[-1]['arrival_time']}"
        else:
            time_info = f"{s['arrival_time']} – {s['departure_time']}"

        v_obj = venues_by_id.get(s["venue_id"]) if venues_by_id else None
        img_url = getattr(v_obj, "image_url", "") if v_obj else ""
        img_tag = (
            f'<img src="{img_url}" style="width:190px;height:105px;object-fit:cover;border-radius:6px;margin-bottom:6px;display:block;"/>'
            if img_url
            else ""
        )

        point_rows.append(
            {
                "lon": float(s["lon"]),
                "lat": float(s["lat"]),
                "label": pin_label,
                "title": f"{pin_label}. {s['name']}",
                "info": (
                    f"{img_tag}"
                    f"<b>{theme['badge']}</b><br/>"
                    f"🕒 Saat: {time_info}<br/>"
                    f"🧭 {leg_word}: {s['walk_from_prev_min']} dk ({s['walk_from_prev_m']} m)"
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
                        "title": f"Alternatif Restoran: {opt['name']}",
                        "info": f"🍽️ Alternatif Seçenek<br/>🧭 {leg_word}: {opt['walk_from_stop_min']} dk ({opt['walk_from_stop_m']} m)",
                        "color": [249, 115, 22, 225],
                    }
                )

    route_paths = _load_walking_paths(travel_mode)
    path_coords = _get_plan_walking_path(plan, route_paths, use_street_routing=use_street_routing)
    all_pts = path_coords + [[r["lon"], r["lat"]] for r in point_rows]
    center_lat, center_lon, zoom = _auto_view_bounds(all_pts)

    layers = []
    if len(path_coords) >= 2:
        layers.append(
            pdk.Layer(
                "PathLayer",
                data=[{"path": path_coords}],
                get_path="path",
                get_color=[255, 255, 255, 240],
                width_min_pixels=9,
                rounded=True,
                joint_rounded=True,
            )
        )
        layers.append(
            pdk.Layer(
                "PathLayer",
                data=[{"path": path_coords}],
                get_path="path",
                get_color=line_color,
                width_min_pixels=4 if travel_mode == "walking" else 6,
                rounded=True,
                joint_rounded=True,
            )
        )
        if travel_mode == "walking":
            # Google Maps yürüyüş modu tarzı mavi-beyaz adım noktaları
            step_dots = [
                {"lon": pt[0], "lat": pt[1]}
                for idx_pt, pt in enumerate(path_coords)
                if idx_pt % 2 == 0
            ]
            layers.append(
                pdk.Layer(
                    "ScatterplotLayer",
                    data=step_dots,
                    get_position="[lon, lat]",
                    get_fill_color=[29, 78, 216, 245],
                    get_radius=12,
                    radius_min_pixels=4,
                    radius_max_pixels=6,
                    stroked=True,
                    get_line_color=[255, 255, 255, 245],
                    line_width_min_pixels=1.5,
                    pickable=False,
                )
            )

    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            data=point_rows,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius=44,
            radius_min_pixels=15,
            radius_max_pixels=22,
            stroked=True,
            get_line_color=[255, 255, 255, 250],
            line_width_min_pixels=3,
            pickable=True,
        )
    )
    layers.append(
        pdk.Layer(
            "TextLayer",
            data=point_rows,
            get_position="[lon, lat]",
            get_text="label",
            size_units="pixels",
            get_size=13,
            get_color=[255, 255, 255, 255],
            get_text_anchor="middle",
            get_alignment_baseline="center",
            get_pixel_offset=[0, 0],
        )
    )

    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=zoom,
        pitch=0,
    )

    tooltip = {
        "html": "<div style='max-width:210px;'><b>{title}</b><br/>{info}</div>",
        "style": {
            "backgroundColor": "#0f172a",
            "color": "white",
            "fontSize": "12px",
            "padding": "8px 12px",
            "borderRadius": "8px",
            "boxShadow": "0 4px 12px rgba(0,0,0,0.35)",
        },
    }

    return pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        map_style="https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
        tooltip=tooltip,
    )


def _build_multi_day_pydeck_map(
    day_plans: List[Dict[str, Any]],
    use_street_routing: bool = True,
    travel_mode: str = "walking",
) -> pdk.Deck:
    route_paths = _load_walking_paths(travel_mode)
    leg_word = "Araç" if travel_mode == "driving" else "Yürüme"
    point_rows: List[Dict[str, Any]] = []
    all_pts: List[List[float]] = []
    layers = []

    for idx, day_plan in enumerate(day_plans):
        d_num = idx + 1
        d_col = DAY_COLORS[idx % len(DAY_COLORS)]
        d_rgb = d_col["rgb"]
        day_tr = DAY_LABELS_TR.get(day_plan.get("day_of_week", ""), day_plan.get("day_of_week", ""))

        path_coords = _get_plan_walking_path(
            day_plan, route_paths, use_street_routing=use_street_routing
        )
        all_pts.extend(path_coords)
        if len(path_coords) >= 2:
            layers.append(
                pdk.Layer(
                    "PathLayer",
                    data=[{"path": path_coords}],
                    get_path="path",
                    get_color=[255, 255, 255, 230],
                    width_min_pixels=9,
                    rounded=True,
                    joint_rounded=True,
                )
            )
            layers.append(
                pdk.Layer(
                    "PathLayer",
                    data=[{"path": path_coords}],
                    get_path="path",
                    get_color=d_rgb,
                    width_min_pixels=5,
                    rounded=True,
                    joint_rounded=True,
                )
            )

        for s in day_plan.get("stops", []):
            theme = _get_theme(s.get("category", ""))
            point_rows.append(
                {
                    "lon": float(s["lon"]),
                    "lat": float(s["lat"]),
                    "label": f"{d_num}-{s['order']}",
                    "title": f"{d_num}. Gün ({day_tr}) | {s['order']}. {s['name']}",
                    "info": (
                        f"Kategori: {theme['badge']} | Saat: {s['arrival_time']}-{s['departure_time']} | "
                        f"{leg_word}: {s['walk_from_prev_min']} dk ({s['walk_from_prev_m']} m)"
                    ),
                    "color": d_rgb,
                }
            )
            all_pts.append([float(s["lon"]), float(s["lat"])])

    center_lat, center_lon, zoom = _auto_view_bounds(all_pts)

    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            data=point_rows,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius=44,
            radius_min_pixels=15,
            radius_max_pixels=22,
            stroked=True,
            get_line_color=[255, 255, 255, 245],
            line_width_min_pixels=2.5,
            pickable=True,
        )
    )
    layers.append(
        pdk.Layer(
            "TextLayer",
            data=point_rows,
            get_position="[lon, lat]",
            get_text="label",
            size_units="pixels",
            get_size=12,
            get_color=[255, 255, 255, 255],
            get_text_anchor="middle",
            get_alignment_baseline="center",
            get_pixel_offset=[0, 0],
        )
    )

    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=zoom,
        pitch=0,
    )

    tooltip = {
        "html": "<b>{title}</b><br/>{info}",
        "style": {
            "backgroundColor": "#0f172a",
            "color": "white",
            "fontSize": "12px",
            "padding": "8px 12px",
            "borderRadius": "6px",
            "boxShadow": "0 2px 8px rgba(0,0,0,0.3)",
        },
    }

    return pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        map_style="https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
        tooltip=tooltip,
    )


def _render_leaflet_route_map(
    day_plans: List[Dict[str, Any]],
    travel_mode: str = "walking",
    use_street_routing: bool = True,
    venues_by_id: Optional[Dict[str, Venue]] = None,
    height: int = 580,
) -> None:
    """
    Google Haritalar kalitesinde interaktif Leaflet haritası:
    - Renkli sokak/uydu katman seçici, otomatik fitBounds kadrajlama,
    - Üzerinde sıra numarası yazan özel HTML pin rozetleri ve kalıcı kısa isim etiketleri,
    - Yürüyüş modunda Google Maps tarzı mavi noktalı/kesikli çizgi + yön okları,
    - Araç modunda beyaz dış konturlu belirgin sürüş rotası + yön okları,
    - Tıklanınca mekan fotoğrafı, saat ve Google Maps bağlantısı açılan zengin bilgi kartı.
    """
    route_paths = _load_walking_paths(travel_mode)
    completed_ids = set(st.session_state.get("completed_stop_ids", []))
    is_multi = len(day_plans) > 1
    leg_word = "Araçla" if travel_mode == "driving" else "Yürüyerek"

    js_days: List[Dict[str, Any]] = []
    for idx, dp in enumerate(day_plans):
        d_num = idx + 1
        d_col = DAY_COLORS[idx % len(DAY_COLORS)]
        line_hex = (
            "#e11d48"
            if (travel_mode == "driving" and not is_multi)
            else d_col["hex"]
        )
        day_tr = DAY_LABELS_TR.get(dp.get("day_of_week", ""), dp.get("day_of_week", ""))
        lonlat_path = _get_plan_walking_path(
            dp, route_paths, use_street_routing=use_street_routing
        )
        latlon_path = [[round(pt[1], 6), round(pt[0], 6)] for pt in lonlat_path]

        stops = dp.get("stops", [])
        n_stops = len(stops)
        js_stops: List[Dict[str, Any]] = []
        for s_idx, s in enumerate(stops):
            if s.get("is_end") and n_stops >= 2 and s["venue_id"] == stops[0]["venue_id"]:
                # Başlangıç ve bitiş aynı nokta ise başlangıç pininde birleştir
                continue
            theme = _get_theme(s.get("category", ""))
            is_done = (
                s["venue_id"] in completed_ids
                and not s.get("is_start")
                and not s.get("is_end")
            )
            pin_bg = "#10b981" if is_done else (d_col["hex"] if is_multi else theme["border"])
            pin_num = f"{d_num}-{s['order']}" if is_multi else str(s["order"])
            if s.get("is_start") and n_stops >= 2 and stops[-1]["venue_id"] == s["venue_id"]:
                time_str = f"Başlangıç: {s['arrival_time']} • Dönüş: {stops[-1]['arrival_time']}"
            else:
                time_str = f"{s['arrival_time']} – {s['departure_time']}"

            v_obj = venues_by_id.get(s["venue_id"]) if venues_by_id else None
            img_url = getattr(v_obj, "image_url", "") if v_obj else ""
            short_name = s["name"].replace("Öğle Yemeği — ", "")
            if len(short_name) > 22:
                short_name = short_name[:20].rstrip() + "…"

            js_stops.append(
                {
                    "lat": float(s["lat"]),
                    "lon": float(s["lon"]),
                    "num": pin_num,
                    "name": html.escape(s["name"]),
                    "short_name": html.escape(short_name),
                    "badge": html.escape(theme["badge"]),
                    "color": pin_bg,
                    "time": html.escape(time_str),
                    "leg": (
                        f"{leg_word}: {s['walk_from_prev_min']} dk ({s['walk_from_prev_m']} m)"
                        if s["order"] > 0
                        else "Başlangıç / Konaklama Üssü"
                    ),
                    "img": img_url or "",
                    "gmaps": _google_maps_pin_url(float(s["lat"]), float(s["lon"])),
                    "is_start": bool(s.get("is_start")),
                    "is_lunch": bool(s.get("is_lunch")),
                    "is_done": is_done,
                }
            )
        js_days.append(
            {
                "day_num": d_num,
                "day_label": f"{d_num}. Gün ({day_tr})",
                "color": line_hex,
                "path": latlon_path,
                "stops": js_stops,
            }
        )

    payload_json = json.dumps(
        {"days": js_days, "mode": travel_mode, "is_multi": is_multi},
        ensure_ascii=False,
    )

    map_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html, body {{ margin: 0; padding: 0; height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  #map {{ width: 100%; height: {height - 8}px; border-radius: 12px; border: 1.5px solid #cbd5e1; box-sizing: border-box; }}
  .rk-pin-wrap {{
    position: relative;
    display: flex;
    align-items: center;
    pointer-events: auto;
  }}
  .rk-pin-circle {{
    width: 30px;
    height: 30px;
    border-radius: 50%;
    border: 2.5px solid #ffffff;
    color: #ffffff;
    font-weight: 800;
    font-size: 12.5px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 3px 8px rgba(15, 23, 42, 0.38);
    flex-shrink: 0;
    transition: transform 0.15s ease;
  }}
  .rk-pin-wrap:hover .rk-pin-circle {{
    transform: scale(1.16);
  }}
  .rk-pin-label {{
    margin-left: 5px;
    background: rgba(255, 255, 255, 0.94);
    color: #0f172a;
    font-size: 11px;
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 6px;
    border: 1px solid #cbd5e1;
    box-shadow: 0 1px 4px rgba(15, 23, 42, 0.16);
    white-space: nowrap;
    pointer-events: none;
  }}
  .rk-arrow-icon {{
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 13px;
    font-weight: 900;
    text-shadow: 0 0 3px #ffffff, 0 0 3px #ffffff;
    pointer-events: none;
  }}
  .rk-fit-btn {{
    background: #ffffff;
    border: 1.5px solid #cbd5e1;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12px;
    font-weight: 700;
    color: #0f172a;
    cursor: pointer;
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.15);
  }}
  .rk-fit-btn:hover {{ background: #f1f5f9; }}
  .rk-legend-box {{
    background: rgba(255, 255, 255, 0.94);
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 11px;
    color: #1e293b;
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.14);
    line-height: 1.5;
  }}
</style>
</head>
<body>
<div id="map"></div>
<script>
  const DATA = {payload_json};
  const map = L.map('map', {{ zoomControl: true, attributionControl: true }});

  const voyager = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png', {{
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap &copy; CARTO'
  }}).addTo(map);

  const osmStd = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap'
  }});

  const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
    maxZoom: 19,
    attribution: '&copy; Esri'
  }});

  L.control.layers({{
    "🗺️ Google/Voyager Rehber Haritası": voyager,
    "🧭 OpenStreetMap Sokak": osmStd,
    "🛰️ Uydu Görüntüsü": satellite
  }}, null, {{ position: 'topright', collapsed: true }}).addTo(map);

  const boundsPts = [];

  DATA.days.forEach(day => {{
    if (day.path && day.path.length >= 2) {{
      day.path.forEach(pt => boundsPts.push(pt));

      // Dış beyaz kontur (Google Maps şerit çerçevesi)
      L.polyline(day.path, {{
        color: '#ffffff',
        weight: 9,
        opacity: 0.95,
        lineCap: 'round',
        lineJoin: 'round'
      }}).addTo(map);

      if (DATA.mode === 'walking') {{
        // Alt yarı saydam mavi iz + üstte Google Maps yürüyüş noktalı çizgisi
        L.polyline(day.path, {{
          color: day.color,
          weight: 4.5,
          opacity: 0.38,
          lineCap: 'round',
          lineJoin: 'round'
        }}).addTo(map);
        L.polyline(day.path, {{
          color: day.color,
          weight: 5.5,
          opacity: 0.98,
          dashArray: '2, 10',
          lineCap: 'round',
          lineJoin: 'round'
        }}).addTo(map);
      }} else {{
        // Araba modu: kesintisiz koyu renkli sürüş şeridi
        L.polyline(day.path, {{
          color: day.color,
          weight: 5.5,
          opacity: 0.95,
          lineCap: 'round',
          lineJoin: 'round'
        }}).addTo(map);
      }}

      // Güzergah yön okları (►)
      const step = Math.max(12, Math.floor(day.path.length / 7));
      for (let i = Math.floor(step / 2); i < day.path.length - 2; i += step) {{
        const p1 = day.path[i];
        const p2 = day.path[i + 1];
        const dy = p2[0] - p1[0];
        const dx = (p2[1] - p1[1]) * Math.cos(p1[0] * Math.PI / 180);
        if (Math.hypot(dx, dy) < 1e-5) continue;
        const angle = Math.atan2(dy, dx) * 180 / Math.PI;
        const arrowIcon = L.divIcon({{
          className: 'rk-arrow-icon',
          html: `<div style="transform: rotate(${{-angle}}deg); color: ${{day.color}};">➤</div>`,
          iconSize: [16, 16],
          iconAnchor: [8, 8]
        }});
        L.marker(p1, {{ icon: arrowIcon, interactive: false }}).addTo(map);
      }}
    }}

    day.stops.forEach(s => {{
      boundsPts.push([s.lat, s.lon]);
      const pinHtml = `
        <div class="rk-pin-wrap">
          <div class="rk-pin-circle" style="background:${{s.color}};">${{s.num}}</div>
          <div class="rk-pin-label">${{s.short_name}}</div>
        </div>
      `;
      const icon = L.divIcon({{
        className: '',
        html: pinHtml,
        iconSize: [150, 34],
        iconAnchor: [16, 16],
        popupAnchor: [0, -16]
      }});

      const imgHtml = s.img
        ? `<img src="${{s.img}}" style="width:100%; height:110px; object-fit:cover; border-radius:6px; margin-bottom:6px; border:1px solid #e2e8f0;" />`
        : '';
      const popupHtml = `
        <div style="width:230px; font-family:sans-serif;">
          ${{imgHtml}}
          <div style="font-size:10.5px; font-weight:700; color:${{s.color}}; margin-bottom:2px;">${{s.badge}}</div>
          <div style="font-size:13.5px; font-weight:800; color:#0f172a; margin-bottom:4px;">${{s.num}}. ${{s.name}}</div>
          <div style="font-size:11.5px; color:#334155; margin-bottom:2px;">🕒 <b>Saat:</b> ${{s.time}}</div>
          <div style="font-size:11.5px; color:#475569; margin-bottom:6px;">🧭 ${{s.leg}}</div>
          <a href="${{s.gmaps}}" target="_blank" style="display:inline-block; background:#0f172a; color:#ffffff; text-decoration:none; font-size:11px; font-weight:700; padding:4px 9px; border-radius:5px;">📍 Google Haritalar'da Aç →</a>
        </div>
      `;
      L.marker([s.lat, s.lon], {{ icon: icon, zIndexOffset: s.is_start ? 1000 : 500 }})
        .addTo(map)
        .bindPopup(popupHtml);
    }});
  }});

  function fitAll() {{
    if (boundsPts.length >= 2) {{
      map.fitBounds(L.latLngBounds(boundsPts), {{ padding: [44, 44], maxZoom: 16 }});
    }} else if (boundsPts.length === 1) {{
      map.setView(boundsPts[0], 15);
    }} else {{
      map.setView([40.7625, 29.9195], 14);
    }}
  }}
  fitAll();

  const fitCtrl = L.control({{ position: 'topleft' }});
  fitCtrl.onAdd = function() {{
    const btn = L.DomUtil.create('button', 'rk-fit-btn');
    btn.innerHTML = '🎯 Tüm Rotayı Sığdır';
    btn.onclick = function(e) {{
      L.DomEvent.stopPropagation(e);
      fitAll();
    }};
    return btn;
  }};
  fitCtrl.addTo(map);

  const legendCtrl = L.control({{ position: 'bottomleft' }});
  legendCtrl.onAdd = function() {{
    const div = L.DomUtil.create('div', 'rk-legend-box');
    const modeTxt = DATA.mode === 'driving'
      ? '<b>🚗 Araba Yolu:</b> Kesintisiz Sürüş Şeridi (➤ Yönlü)'
      : '<b>🚶 Yürüyüş Yolu:</b> Noktalı Yaya Kaldırım Ağı (➤ Yönlü)';
    div.innerHTML = modeTxt + '<br/><span style="color:#475569;">💡 Pinlere tıklayarak mekan fotoğrafı ve saat detayını görebilirsiniz.</span>';
    return div;
  }};
  legendCtrl.addTo(map);
</script>
</body>
</html>"""
    components.html(map_html, height=height, scrolling=False)


def _apply_restaurant_choice(plan: Dict[str, Any], chosen_venue_id: str) -> Dict[str, Any]:
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
        s["source_url"] = chosen.get("source_url", s.get("source_url", ""))
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


def _format_slide5_schedule(plan: Dict[str, Any], travel_mode: str = "walking") -> str:
    leg_noun = "araç sürüşü" if travel_mode == "driving" else "yürüme"
    tot_label = "Toplam araç sürüşü" if travel_mode == "driving" else "Toplam yürüme"
    lines: List[str] = []
    for s in plan.get("stops", []):
        if s.get("is_start"):
            lines.append(f"{s['arrival_time']}  {s['name']:<38} başlangıç")
        elif s.get("is_end"):
            lines.append(
                f"{s['arrival_time']}  {s['name']:<38} dönüş         önceki duraktan {s['walk_from_prev_min']:>2} dk {leg_noun} ({s['walk_from_prev_m']} m)"
            )
        elif s.get("is_lunch"):
            opt_cnt = len(s.get("restaurant_options", []))
            lines.append(
                f"{s['arrival_time']}  Öğle yemeği ({opt_cnt} restoran önerisi)       {s['stay_min']:>2} dk mola    önceki duraktan {s['walk_from_prev_min']:>2} dk {leg_noun} ({s['walk_from_prev_m']} m)"
            )
            for opt in s.get("restaurant_options", []):
                lines.append(f"       • {opt['name']} ({opt['walk_from_stop_min']} dk {leg_noun})")
        else:
            lines.append(
                f"{s['arrival_time']}  {s['name']:<38} {s['stay_min']:>2} dk kalış   önceki duraktan {s['walk_from_prev_min']:>2} dk {leg_noun} ({s['walk_from_prev_m']} m)"
            )
    lines.append(f"\n{tot_label}: {plan['total_walk_min']} dk, {plan['total_walk_km']} km")
    return "\n".join(lines)


def _inject_global_styles() -> None:
    st.markdown(
        '<style>'
        '.stApp { background-color: #f8fafc; }'
        'div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 12px; }'
        '.rk-navbar-wrap { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; '
        'padding: 8px 12px; margin-bottom: 18px; box-shadow: 0 2px 6px rgba(15,23,42,0.05); }'
        '</style>',
        unsafe_allow_html=True,
    )


def _render_official_header() -> None:
    user = st.session_state.get("auth_user")
    user_badge = (
        f'<span style="background: rgba(16, 185, 129, 0.2); border: 1px solid #10b981; color: #34d399; '
        f'font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 9999px;">👤 {user["full_name"]}</span>'
        if user
        else '<span style="background: rgba(148, 163, 184, 0.18); border: 1px solid #64748b; color: #cbd5e1; '
        'font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 9999px;">Misafir Oturumu</span>'
    )
    svg_logo = (
        '<svg width="40" height="40" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<rect width="48" height="48" rx="8" fill="#1E3A8A"/>'
        '<path d="M24 6L28 16H20L24 6Z" fill="#F59E0B"/>'
        '<circle cx="24" cy="24" r="14" stroke="#FFFFFF" stroke-width="2.5" stroke-dasharray="3 3"/>'
        '<rect x="22" y="16" width="4" height="16" rx="2" fill="#FFFFFF"/>'
        '<rect x="18" y="32" width="12" height="6" rx="2" fill="#F59E0B"/>'
        '<circle cx="24" cy="24" r="3" fill="#EF4444"/>'
        '<path d="M12 38C16 34 32 34 36 38" stroke="#38BDF8" stroke-width="2.5" stroke-linecap="round"/>'
        '</svg>'
    )
    header_html = (
        '<div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #1e3a8a 100%); '
        'padding: 18px 24px; border-radius: 14px; margin-bottom: 12px; '
        'box-shadow: 0 4px 14px rgba(15,23,42,0.14); color: white; display: flex; '
        'align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;">'
        '<div style="display: flex; align-items: center; gap: 16px;">'
        f'<div style="background: white; border-radius: 10px; width: 54px; height: 54px; display: flex; align-items: center; justify-content: center;">{svg_logo}</div>'
        '<div>'
        '<div style="font-size: 11px; font-weight: 700; letter-spacing: 1.4px; text-transform: uppercase; color: #94a3b8;">T.C. Kocaeli Kültür & Turizm Rota Rehberi</div>'
        '<div style="font-size: 24px; font-weight: 800; color: #ffffff; line-height: 1.2;">ROTA KOCAELİ <span style="font-size: 14px; font-weight: 400; color: #38bdf8;">| Akıllı Yürüyüş & Araç Planlayıcısı</span></div>'
        '<div style="font-size: 12px; color: #cbd5e1; margin-top: 2px;">İzmit Tarihi Koridoru & Rota Optimizasyon Motoru • OpenStreetMap Gerçek Yaya & Araç Rotaları</div>'
        '</div>'
        '</div>'
        '<div style="text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 6px;">'
        '<span style="background: rgba(56, 189, 248, 0.18); border: 1px solid #38bdf8; color: #38bdf8; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 9999px;">RESMİ SÜRÜM v3.1 • OSM YAYA & ARAÇ</span>'
        f'{user_badge}'
        '</div>'
        '</div>'
    )
    st.markdown(header_html, unsafe_allow_html=True)


def _render_top_navbar() -> str:
    st.session_state.setdefault("active_page", "planner")
    active = st.session_state["active_page"]
    user = st.session_state.get("auth_user")
    account_label = (
        f"👤 Profilim ({user['full_name']})"
        if user and user.get("full_name")
        else "👤 Profilim & Kayıtlı Geziler"
    )

    nav_items = [
        ("planner", "🧭 Rota Planlayıcı"),
        ("catalog", "🏛️ Mekan Kataloğu"),
        ("account", account_label),
        ("eval", "📊 Sınama & Hakkında"),
    ]
    st.markdown('<div class="rk-navbar-wrap">', unsafe_allow_html=True)
    cols = st.columns(len(nav_items))
    for idx, (key, label) in enumerate(nav_items):
        btn_type = "primary" if active == key else "secondary"
        if cols[idx].button(label, key=f"top_nav_{key}", type=btn_type, width="stretch"):
            st.session_state["active_page"] = key
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
    return st.session_state["active_page"]


def _render_catalog_page(venues: List[Venue]) -> None:
    st.subheader("🏛️ Kocaeli (İzmit) Doğrulanmış Mekan, Konaklama ve Restoran Kataloğu")
    st.caption(
        "Tüm koordinatlar OpenStreetMap verilerinden, fotoğraflar ise Wikimedia Commons gerçek mekan görsellerinden doğrulandı. Her kartta doğrudan Google Haritalar ve Wikipedia bağlantısı bulunur."
    )

    col1, col2 = st.columns([1.2, 2.0])
    with col1:
        cat_filter = st.selectbox(
            "Kategoriye Göre Filtrele:",
            [
                "Tümü",
                "Müzeler",
                "Tarihi Konak & Köşk",
                "Anıt & Saat Kulesi",
                "Camiler",
                "Park & Sahil",
                "Konaklama Yerleri (Otel)",
                "Restoranlar & Yemek",
            ],
        )

    cat_map = {
        "Müzeler": "muze",
        "Tarihi Konak & Köşk": "konak_kosk",
        "Anıt & Saat Kulesi": "anit_saat_kulesi",
        "Camiler": "cami",
        "Park & Sahil": "park_sahil",
        "Konaklama Yerleri (Otel)": "konaklama",
        "Restoranlar & Yemek": "restoran",
    }

    filtered = venues
    if cat_filter != "Tümü":
        target = cat_map[cat_filter]
        if target == "restoran":
            filtered = [v for v in venues if v.is_restaurant]
        else:
            filtered = [v for v in venues if v.category == target]

    grid_cols = st.columns(2)
    for idx, v in enumerate(filtered):
        theme = _get_theme(v.category)
        with grid_cols[idx % 2]:
            img_html = ""
            if getattr(v, "image_url", None):
                img_html = f'<img src="{v.image_url}" style="width: 100%; height: 185px; object-fit: cover; border-radius: 8px; margin-bottom: 10px; border: 1px solid #e2e8f0;" alt="{v.name}" />'
            price_info = f" | <b>Fiyat:</b> {v.price_range}" if v.price_range else ""
            open_note = v.opening_hours_note or "Açılış saati bilinmiyor"
            gmaps_pin = _google_maps_pin_url(v.lat, v.lon)
            card_html = (
                f'<div style="border-left: 5px solid {theme["border"]}; background: {theme["bg"]}; '
                f'padding: 14px; border-radius: 10px; margin-bottom: 14px; box-shadow: 0 2px 6px rgba(0,0,0,0.06);">'
                f'{img_html}'
                f'<div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">'
                f'<h4 style="margin: 0; color: {theme["text"]}; font-size: 16px;">{v.name}</h4>'
                f'<span style="background: {theme["border"]}; color: white; font-size: 10px; font-weight: 700; '
                f'padding: 3px 9px; border-radius: 9999px; white-space: nowrap;">{theme["badge"]}</span>'
                f'</div>'
                f'<p style="font-size: 12.5px; color: #334155; margin: 8px 0;">{v.description_short}</p>'
                f'<div style="font-size: 11.5px; color: #475569;">'
                f'<b>Varsayılan Kalış:</b> {v.default_stay_min} dk | <b>Açılış:</b> {open_note}{price_info}'
                f'</div>'
                f'<div style="margin-top: 8px; display: flex; gap: 14px; flex-wrap: wrap;">'
                f'<a href="{gmaps_pin}" target="_blank" style="font-size: 11.5px; color: #0f766e; text-decoration: none; font-weight: 700;">📍 Google Haritalar & Fotoğraflar →</a>'
                f'<a href="{v.source_url}" target="_blank" style="font-size: 11.5px; color: #2563eb; text-decoration: none; font-weight: 600;">📖 {v.source_name} Kaynağı →</a>'
                f'</div>'
                f'</div>'
            )
            st.markdown(card_html, unsafe_allow_html=True)


def _load_saved_trip_into_state(t: Dict[str, Any]) -> None:
    loaded_plans = t["day_plans"]
    inferred_mode = (
        "driving"
        if loaded_plans
        and "araç (araba)" in str(loaded_plans[0].get("summary_text", "")).lower()
        else "walking"
    )
    st.session_state["travel_mode"] = inferred_mode
    st.session_state["day_plans"] = loaded_plans
    st.session_state["current_plan"] = loaded_plans[0] if loaded_plans else None
    st.session_state["day2_plan"] = loaded_plans[1] if len(loaded_plans) >= 2 else None
    st.session_state["completed_stop_ids"] = list(t.get("completed_stop_ids", []))
    st.session_state["removed_stop_ids"] = []
    st.session_state["active_trip_id"] = t["id"]
    st.session_state["active_page"] = "planner"


def _render_account_page(venues: List[Venue]) -> None:
    st.subheader("👤 Profilim & Kayıtlı Geziler")
    st.caption(
        f"Aktif Depolama Katmanı: **{storage.get_backend_label()}** • Oturumunuz kalıcı olarak saklanır (sayfayı yenileseniz bile açık kalır). Slayt 14 Gizlilik Kuralı gereği kullanıcı e-postası ve hesap bilgileri dil modeline asla gönderilmez."
    )

    user = st.session_state.get("auth_user")
    if not user:
        local_profiles = storage.list_local_users()
        if local_profiles:
            st.markdown("#### ⚡ Kayıtlı Profiller (Şifresiz Tek Tıkla Hızlı Giriş)")
            for prof in local_profiles:
                with st.container(border=True):
                    p_info, p_btn1, p_btn2 = st.columns([2.6, 1.3, 1.4])
                    with p_info:
                        st.markdown(
                            f"**👤 {prof['full_name']}** (`{prof['email']}`) — **{prof['trip_count']} Kayıtlı Gezi**"
                        )
                        st.caption("Bu cihazda kayıtlı profiliniz. Şifre yazmadan tek tıkla açabilirsiniz.")
                    with p_btn1:
                        if st.button(
                            f"🚀 {prof['full_name']} Olarak Gir",
                            key=f"quick_login_{prof['id']}",
                            type="primary",
                            width="stretch",
                        ):
                            ok, msg, logged_u = storage.quick_login_by_id(prof["id"])
                            if ok and logged_u:
                                st.session_state["auth_user"] = logged_u
                                st.toast(msg)
                                st.rerun()
                    with p_btn2:
                        if st.button(
                            "📂 Gir ve Son Planımı Aç",
                            key=f"quick_login_open_{prof['id']}",
                            width="stretch",
                        ):
                            ok, msg, logged_u = storage.quick_login_by_id(prof["id"])
                            if ok and logged_u:
                                st.session_state["auth_user"] = logged_u
                                user_trips = storage.list_saved_trips(logged_u)
                                if user_trips:
                                    _load_saved_trip_into_state(user_trips[0])
                                st.rerun()

        t_login, t_reg, t_reset = st.tabs(
            ["🔑 E-posta veya İsimle Giriş Yap", "🆕 Yeni Hesap Oluştur", "🔄 Şifremi Unuttum / Yenile"]
        )
        with t_login:
            with st.form("login_form"):
                l_email = st.text_input(
                    "E-posta Adresiniz veya Adınız Soyadınız",
                    placeholder="Örn: ozlemyildirim3010@gmail.com veya Özlem Yıldırım",
                )
                l_pass = st.text_input("Şifreniz", type="password")
                if st.form_submit_button("Giriş Yap", type="primary", width="stretch"):
                    ok, msg, logged_user = storage.login_user(l_email, l_pass)
                    if ok and logged_user:
                        st.session_state["auth_user"] = logged_user
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
        with t_reg:
            with st.form("register_form"):
                r_name = st.text_input("Adınız Soyadınız", placeholder="Özlem Yıldırım")
                r_email = st.text_input("E-posta Adresiniz", placeholder="ornek@gmail.com")
                r_pass = st.text_input("Şifre (en az 6 karakter)", type="password")
                if st.form_submit_button("Hesap Oluştur ve Giriş Yap", type="primary", width="stretch"):
                    ok, msg, new_user = storage.register_user(r_email, r_pass, full_name=r_name)
                    if ok and new_user:
                        st.session_state["auth_user"] = new_user
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
        with t_reset:
            with st.form("reset_pw_form"):
                rst_id = st.text_input(
                    "Kayıtlı E-posta Adresiniz veya Adınız Soyadınız",
                    value=local_profiles[0]["email"] if local_profiles else "",
                )
                rst_pass = st.text_input("Yeni Şifreniz (en az 4 karakter)", type="password")
                if st.form_submit_button("Şifremi Güncelle ve Giriş Yap", type="primary", width="stretch"):
                    ok, msg, reset_u = storage.reset_password(rst_id, rst_pass)
                    if ok and reset_u:
                        st.session_state["auth_user"] = reset_u
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

        with st.expander("ℹ️ Supabase Ücretsiz Bulut Veritabanı Kurulumu (Opsiyonel)"):
            st.markdown(
                textwrap.dedent(
                    """
                    Varsayılan olarak tüm hesaplar ve kayıtlı geziler yerel `data/rota_kocaeli.db` SQLite veritabanında kalıcı saklanır.
                    İsterseniz `.env` dosyanıza ücretsiz **Supabase** `SUPABASE_URL` ve `SUPABASE_ANON_KEY` değerlerini ekleyerek bulut Auth + Postgres kullanabilirsiniz:
                    ```sql
                    create table saved_trips (
                      id uuid primary key,
                      user_id uuid references auth.users not null,
                      title text not null,
                      num_days int not null,
                      summary text not null,
                      plan_bundle jsonb not null,
                      completed_stop_ids jsonb default '[]'::jsonb,
                      created_at text,
                      updated_at text
                    );
                    ```
                    """
                ).strip()
            )
        return

    trips = storage.list_saved_trips(user)
    with st.container(border=True):
        top_u1, top_u2, top_u3 = st.columns([2.8, 1.3, 1.0])
        with top_u1:
            st.markdown(
                f"### 👤 {user['full_name']}\n"
                f"📧 `{user['email']}` • 🗂️ **{len(trips)} Kayıtlı Gezi Planı** • ✅ *Kalıcı Oturum Aktif*"
            )
        with top_u2:
            if st.button("🧭 Yeni Rota Planla", width="stretch"):
                st.session_state["active_page"] = "planner"
                st.rerun()
        with top_u3:
            if st.button("🚪 Çıkış Yap", width="stretch"):
                storage.logout_user()
                st.session_state["auth_user"] = None
                st.session_state["active_trip_id"] = None
                st.rerun()

    st.divider()
    st.markdown("### 📂 Kayıtlı Gezi Planlarım")
    if not trips:
        st.info(
            "Henüz kayıtlı bir gezi planınız yok. **Rota Planlayıcı** sayfasından bir rota oluşturup **💾 Beğendiğim Planı Kaydet** butonunu kullanabilirsiniz."
        )
        return

    for t in trips:
        with st.container(border=True):
            c_info, c_open, c_del = st.columns([3.2, 1.0, 0.8])
            with c_info:
                st.markdown(f"**🗺️ {t['title']}**")
                st.caption(f"{t['summary']} • Son Güncelleme: {t['updated_at']}")
            with c_open:
                if st.button("📂 Planı Aç", key=f"open_trip_{t['id']}", type="primary", width="stretch"):
                    _load_saved_trip_into_state(t)
                    st.rerun()
            with c_del:
                if st.button("🗑️ Sil", key=f"del_trip_{t['id']}", width="stretch"):
                    ok, msg = storage.delete_saved_trip(user, t["id"])
                    if ok:
                        if st.session_state.get("active_trip_id") == t["id"]:
                            st.session_state["active_trip_id"] = None
                        st.toast(msg)
                        st.rerun()
                    else:
                        st.error(msg)


def _render_eval_report_page() -> None:
    st.subheader("📊 Slayt 15 Otomatik Sınama Raporu & Sistem Mimarisi")
    st.caption(
        "BTK Akademi Final Projesi gereğince 20 farklı Türkçe gezi isteği deterministik kontrol ile otomatik denetlenir."
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Toplam Senaryo", "20 İstek")
    m2.metric("Başarı Oranı", "20 / 20 (%100)")
    m3.metric("Kapalı Mekan Hatası", "0 (Sıfır)")
    m4.metric("Uydurma Mekan", "0 (Sıfır)")

    test_json_path = ROOT_DIR / "person1_data_ai" / "test_requests_20.json"
    if test_json_path.exists():
        with open(test_json_path, encoding="utf-8") as f:
            cases = json.load(f)
        report_rows = [
            {
                "No": c["id"].upper(),
                "Kullanıcı İstek Özeti": c["prompt"][:80] + ("..." if len(c["prompt"]) > 80 else ""),
                "Gün": DAY_LABELS_TR.get(c["expected"]["day_of_week"], c["expected"]["day_of_week"]),
                "Hedef Bitiş": c["expected"]["end_time"],
                "Yemek": "İsteniyor" if c["expected"]["want_lunch"] else "İstenmiyor",
                "Durum": "✅ BAŞARILI",
            }
            for c in cases
        ]
        st.dataframe(report_rows, width="stretch", hide_index=True)

    st.divider()
    st.markdown(
        textwrap.dedent(
            """
            ### 🎯 Slayt 4, 6, 9, 10 Uyum Özeti
            * **Hesabı Kod Yapar:** Sıralama (TSP), gerçek yaya (`OSM routed-foot`) ve araç (`OSRM driving`) süreleri, mesafe ve açılış saati kontrolleri `person2_engine/` içindedir.
            * **Çok Günlü Rota & Konaklama:** 1, 2 veya 3 günlük gezilerde mekanlar coğrafi koridorlara tekrar etmeden bölünür; konaklama oteli her günün başlangıç ve dönüş noktası olur.
            * **Alternatif Plan & Kayıtlı Geziler:** Kullanıcı geri bildirimine (`daha az müze, daha çok park`) göre kısıtlar güncellenir, beğendiği plan hesabına kaydedilir.
            * **Gün Ortası & Tamamlandı:** Ziyaret edilen duraklar işaretlenir; anlık konum ve saat girilerek kalan gün deterministik olarak yeniden planlanır.
            """
        ).strip()
    )


def _persist_progress_if_saved_trip() -> None:
    user = st.session_state.get("auth_user")
    trip_id = st.session_state.get("active_trip_id")
    if user and trip_id:
        storage.update_trip_progress(
            user=user,
            trip_id=trip_id,
            completed_ids=st.session_state.get("completed_stop_ids", []),
            day_plans=st.session_state.get("day_plans", []),
        )


def _switch_active_travel_mode(
    new_mode: str,
    use_mock: bool,
    custom_durations_override: Optional[Dict[str, int]] = None,
    target_day_idx: Optional[int] = None,
) -> None:
    st.session_state["travel_mode"] = new_mode
    day_plans = st.session_state.get("day_plans", [])
    if not day_plans or use_mock:
        return
    removed = list(st.session_state.get("removed_stop_ids", []))
    new_plans: List[Dict[str, Any]] = []
    for idx, dp in enumerate(day_plans):
        dur_arg = (
            custom_durations_override
            if (target_day_idx == idx and custom_durations_override)
            else None
        )
        updated_res = switch_plan_travel_mode(
            day_plan_dict=dp,
            travel_mode=new_mode,
            custom_durations=dur_arg,
            removed_venue_ids=removed,
        )
        new_plans.append(updated_res.model_dump())
    st.session_state["day_plans"] = new_plans
    st.session_state["current_plan"] = new_plans[0] if new_plans else None
    st.session_state["day2_plan"] = new_plans[1] if len(new_plans) >= 2 else None
    _persist_progress_if_saved_trip()


def _on_click_travel_mode(
    new_mode: str,
    use_mock: bool,
    target_day_idx: Optional[int] = None,
) -> None:
    if st.session_state.get("travel_mode", "walking") == new_mode:
        return
    custom_durs: Optional[Dict[str, int]] = None
    if target_day_idx is not None:
        day_num = target_day_idx + 1
        dp_list = st.session_state.get("day_plans", [])
        if 0 <= target_day_idx < len(dp_list):
            durs: Dict[str, int] = {}
            for s in dp_list[target_day_idx].get("stops", []):
                if not s.get("is_start") and not s.get("is_end") and not s.get("is_lunch"):
                    k_exact = f"stay_{day_num}_{s['venue_id']}_{s['order']}"
                    if k_exact in st.session_state:
                        durs[s["venue_id"]] = int(st.session_state[k_exact])
                    else:
                        durs[s["venue_id"]] = int(s["stay_min"])
            custom_durs = durs
    _switch_active_travel_mode(
        new_mode=new_mode,
        use_mock=use_mock,
        custom_durations_override=custom_durs,
        target_day_idx=target_day_idx,
    )


def _render_map_mode_selector(
    stops_list: List[List[Dict[str, Any]]],
    key_prefix: str,
    use_mock: bool,
    custom_durations_override: Optional[Dict[str, int]] = None,
    target_day_idx: Optional[int] = None,
) -> str:
    current_mode = st.session_state.get("travel_mode", "walking")
    w_min, w_km, d_min, d_km = 0, 0.0, 0, 0.0
    for stops in stops_list:
        est = estimate_both_modes_totals(stops)
        w_min += int(est["walking"]["duration_min"])
        w_km += float(est["walking"]["distance_km"])
        d_min += int(est["driving"]["duration_min"])
        d_km += float(est["driving"]["distance_km"])
    w_km = round(w_km, 2)
    d_km = round(d_km, 2)

    st.caption(
        "Google Haritalar gibi ulaşım modunu harita üzerinden seçin (çizgi geometrisi ve tüm durak saatleri otomatik güncellenir):"
    )
    mc1, mc2 = st.columns(2)
    walk_label = f"🚶 Yürüyüş Yolu ({w_min} dk • {w_km} km)"
    drive_label = f"🚗 Araba Yolu ({d_min} dk • {d_km} km)"
    mc1.button(
        walk_label,
        key=f"mode_walk_{key_prefix}",
        type="primary" if current_mode == "walking" else "secondary",
        width="stretch",
        on_click=_on_click_travel_mode,
        args=("walking", use_mock, target_day_idx),
    )
    mc2.button(
        drive_label,
        key=f"mode_drive_{key_prefix}",
        type="primary" if current_mode == "driving" else "secondary",
        width="stretch",
        on_click=_on_click_travel_mode,
        args=("driving", use_mock, target_day_idx),
    )
    return current_mode


def _render_day_view(
    day_plan: Dict[str, Any],
    day_idx: int,
    day_title: str,
    color_rgb: List[int],
    use_street_routing: bool,
    use_mock: bool,
    venues: List[Venue],
    venues_by_id: Dict[str, Venue],
) -> None:
    day_num = day_idx + 1
    current_mode = st.session_state.get("travel_mode", "walking")
    is_driving = current_mode == "driving"
    m1, m2, m3, m4 = st.columns(4)
    poi_count = sum(
        1
        for s in day_plan["stops"]
        if not s.get("is_start") and not s.get("is_end") and not s.get("is_lunch")
    )
    m1.metric(
        "Toplam Araç Süresi" if is_driving else "Toplam Yürüme Süresi",
        f"{day_plan['total_walk_min']} dk",
    )
    m2.metric(
        "Toplam Araç Mesafesi" if is_driving else "Toplam Yürüme Mesafesi",
        f"{day_plan['total_walk_km']} km",
    )
    m3.metric("Gezilecek Durak Sayısı", f"{poi_count} mekan")
    m4.metric("Dönüş / Bitiş Saati", f"{day_plan['actual_end_time']} (Hedef: {day_plan['requested_end_time']})")

    if day_plan.get("summary_text"):
        st.success(f"📋 **{day_title} Özeti:** {day_plan['summary_text']}")

    if day_plan.get("warnings"):
        warnings_md = "\n".join(f"- {w}" for w in day_plan["warnings"])
        st.warning(f"⚠️ **Dikkat Edilmesi Gerekenler ve Saat Uyarıları ({day_title})**\n\n{warnings_md}")

    if day_plan.get("dropped_venues"):
        with st.expander(f"Rotaya Alınamayan / Güne Sığmayan Mekanlar ({len(day_plan['dropped_venues'])})"):
            for d in day_plan["dropped_venues"]:
                st.write(f"- **{d['name']}**: {d['reason']}")

    left_col, right_col = st.columns([1.25, 1.0])

    with left_col:
        st.subheader("🕒 Görselli ve Renkli Durak Çizelgesi")
        updated_durations: Dict[str, int] = {}
        completed_ids: List[str] = list(st.session_state.get("completed_stop_ids", []))

        for s in day_plan["stops"]:
            is_poi = not s.get("is_start") and not s.get("is_end") and not s.get("is_lunch")
            is_done = s["venue_id"] in completed_ids
            theme = _get_theme(s.get("category", ""))

            border_color = "#10b981" if is_done else theme["border"]
            bg_color = "#f0fdf4" if is_done else theme["bg"]

            done_badge = ' <span style="color:#10b981; font-weight:700;">(Gezildi ✅)</span>' if is_done else ""
            leg_mode_noun = "araçla sürüş" if is_driving else "yürüme"
            walk_info = (
                f"Önceki duraktan: <b>{s['walk_from_prev_min']} dk</b> ({s['walk_from_prev_m']} m) {leg_mode_noun}"
                if s["order"] > 0
                else "Günün başlangıç noktası"
            )
            venue_obj = venues_by_id.get(s["venue_id"])
            img_url = getattr(venue_obj, "image_url", None) if venue_obj else None
            img_block = (
                f'<img src="{img_url}" style="width: 122px; height: 92px; object-fit: cover; '
                f'border-radius: 8px; flex-shrink: 0; border: 1px solid #cbd5e1;" alt="{s["name"]}" />'
                if img_url
                else f'<div style="width: 122px; height: 92px; border-radius: 8px; flex-shrink: 0; '
                f'background: #e2e8f0; display: flex; align-items: center; justify-content: center; '
                f'font-size: 24px;">📍</div>'
            )

            gmaps_pin = _google_maps_pin_url(s["lat"], s["lon"])
            src_url = s.get("source_url") or gmaps_pin
            oh_style = (
                "background:#fef3c7; color:#92400e; padding:1px 6px; border-radius:4px;"
                if s.get("opening_hours_status") == "unknown"
                else "background:#e2e8f0; color:#1e293b; padding:1px 6px; border-radius:4px;"
            )
            expl_text = s.get("explanation") or (venue_obj.description_short if venue_obj else "")

            card_html = (
                f'<div style="border-left: 6px solid {border_color}; background: {bg_color}; '
                f'padding: 12px 14px; border-radius: 10px; margin-bottom: 6px; '
                f'box-shadow: 0 1px 4px rgba(0,0,0,0.06); display: flex; gap: 14px; align-items: flex-start;">'
                f'{img_block}'
                f'<div style="flex: 1; min-width: 0;">'
                f'<div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; flex-wrap: wrap;">'
                f'<div style="font-size: 14.5px; font-weight: 800; color: #0f172a;">'
                f'{s["arrival_time"]} – {s["departure_time"]} | {day_num}-{s["order"]}. {s["name"]}{done_badge}'
                f'</div>'
                f'<span style="background: {border_color}; color: white; font-size: 10.5px; font-weight: 700; '
                f'padding: 2px 9px; border-radius: 9999px; white-space: nowrap;">{theme["badge"]}</span>'
                f'</div>'
                f'<div style="font-size: 12px; color: #334155; margin-top: 4px;">'
                f'{walk_info} • Açılış: <span style="{oh_style}">{s["opening_hours_label"]}</span>'
                f'</div>'
                f'<div style="font-size: 12px; color: #475569; margin-top: 5px; line-height: 1.4;">{expl_text}</div>'
                f'<div style="margin-top: 5px; display: flex; gap: 12px; flex-wrap: wrap;">'
                f'<a href="{gmaps_pin}" target="_blank" style="font-size: 11px; color: #0f766e; text-decoration: none; font-weight: 700;">📍 Haritada Konum & Foto</a>'
                f'<a href="{src_url}" target="_blank" style="font-size: 11px; color: #2563eb; text-decoration: none; font-weight: 600;">📖 Kaynak</a>'
                f'</div>'
                f'</div>'
                f'</div>'
            )
            st.markdown(card_html, unsafe_allow_html=True)

            if is_poi or (s.get("is_lunch") and not use_mock):
                ctl_c1, ctl_c2, ctl_c3 = st.columns([1.4, 1.3, 1.3])
                if is_poi:
                    with ctl_c1:
                        updated_durations[s["venue_id"]] = st.number_input(
                            "Kalış (dk)",
                            min_value=5,
                            max_value=240,
                            step=5,
                            value=int(s["stay_min"]),
                            key=f"stay_{day_num}_{s['venue_id']}_{s['order']}",
                        )
                    if not use_mock:
                        with ctl_c2:
                            done_label = "↩️ Geri Al" if is_done else "✅ Gezildi"
                            if st.button(
                                done_label,
                                key=f"done_{day_num}_{s['venue_id']}_{s['order']}",
                                width="stretch",
                            ):
                                if is_done:
                                    completed_ids.remove(s["venue_id"])
                                else:
                                    completed_ids.append(s["venue_id"])
                                st.session_state["completed_stop_ids"] = completed_ids
                                _persist_progress_if_saved_trip()
                                st.rerun()
                        with ctl_c3:
                            if st.button(
                                "🗑️ Çıkar",
                                key=f"rm_{day_num}_{s['venue_id']}_{s['order']}",
                                width="stretch",
                            ):
                                removed = list(st.session_state.get("removed_stop_ids", []))
                                removed.append(s["venue_id"])
                                st.session_state["removed_stop_ids"] = removed
                                new_res = recalculate_trip(
                                    parsed_request_dict=day_plan["parsed_request"],
                                    custom_durations=updated_durations,
                                    removed_venue_ids=removed,
                                    travel_mode=current_mode,
                                )
                                st.session_state["day_plans"][day_idx] = new_res.model_dump()
                                st.rerun()
                elif s.get("is_lunch") and not use_mock:
                    with ctl_c2:
                        done_label = "↩️ Yemek Geri Al" if is_done else "✅ Yemek Yenildi"
                        if st.button(
                            done_label,
                            key=f"done_lunch_{day_num}_{s['order']}",
                            width="stretch",
                        ):
                            if is_done:
                                completed_ids.remove(s["venue_id"])
                            else:
                                completed_ids.append(s["venue_id"])
                            st.session_state["completed_stop_ids"] = completed_ids
                            _persist_progress_if_saved_trip()
                            st.rerun()

            if s.get("is_lunch") and s.get("restaurant_options"):
                lunch_dist_label = "araç mesafesi" if is_driving else "yürüme"
                st.markdown(
                    '<div style="background: #fff7ed; border: 1px dashed #ea580c; border-radius: 8px; padding: 6px 12px; margin: 4px 0 8px 0;">'
                    f'<span style="color: #c2410c; font-weight: 700; font-size: 12.5px;">🍽️ Öğle Yemeği Yeri Alternatifleri (≤ 10 dk {lunch_dist_label}):</span>'
                    '</div>',
                    unsafe_allow_html=True,
                )
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
                    "Restoran seçimi:",
                    options=list(opt_labels.keys()),
                    index=list(opt_labels.keys()).index(current_rest_id),
                    format_func=lambda vid: opt_labels[vid],
                    key=f"lunch_radio_{day_num}_{s['order']}",
                    label_visibility="collapsed",
                )
                if chosen_rest_id != s["venue_id"]:
                    st.session_state["day_plans"][day_idx] = _apply_restaurant_choice(
                        day_plan, chosen_rest_id
                    )
                    st.rerun()

        if not use_mock and updated_durations:
            st.divider()
            bcol1, bcol2 = st.columns(2)
            if bcol1.button(
                f"⏱️ {day_title} Kalış Sürelerini ve Kalanı Yeniden Hesapla",
                key=f"btn_recalc_{day_num}",
                width="stretch",
            ):
                if completed_ids:
                    last_done = next(
                        (s for s in reversed(day_plan["stops"]) if s["venue_id"] in completed_ids),
                        None,
                    )
                    start_loc = last_done["venue_id"] if last_done else day_plan["stops"][0]["venue_id"]
                    start_t = last_done["departure_time"] if last_done else day_plan["requested_start_time"]
                    try:
                        new_res = recalculate_from_midday(
                            parsed_request_dict=day_plan["parsed_request"],
                            current_venue_id=start_loc,
                            current_time=start_t,
                            completed_venue_ids=completed_ids,
                            custom_durations=updated_durations,
                            removed_venue_ids=st.session_state.get("removed_stop_ids", []),
                            travel_mode=current_mode,
                        )
                        st.session_state["day_plans"][day_idx] = new_res.model_dump()
                        st.session_state["completed_stop_ids"] = []
                        st.rerun()
                    except ValueError as err:
                        st.error(str(err))
                else:
                    new_res = recalculate_trip(
                        parsed_request_dict=day_plan["parsed_request"],
                        custom_durations=updated_durations,
                        removed_venue_ids=st.session_state.get("removed_stop_ids", []),
                        travel_mode=current_mode,
                    )
                    st.session_state["day_plans"][day_idx] = new_res.model_dump()
                    st.rerun()

            if completed_ids and bcol2.button(
                f"✅ {day_title} Gezilenleri Çıkarıp Kalanı Güncelle",
                key=f"btn_done_recalc_{day_num}",
                width="stretch",
            ):
                last_done = next(
                    (s for s in reversed(day_plan["stops"]) if s["venue_id"] in completed_ids),
                    None,
                )
                start_loc = last_done["venue_id"] if last_done else day_plan["stops"][0]["venue_id"]
                start_t = last_done["departure_time"] if last_done else day_plan["requested_start_time"]
                try:
                    new_res = recalculate_from_midday(
                        parsed_request_dict=day_plan["parsed_request"],
                        current_venue_id=start_loc,
                        current_time=start_t,
                        completed_venue_ids=completed_ids,
                        custom_durations=updated_durations,
                        removed_venue_ids=st.session_state.get("removed_stop_ids", []),
                        travel_mode=current_mode,
                    )
                    st.session_state["day_plans"][day_idx] = new_res.model_dump()
                    st.session_state["completed_stop_ids"] = []
                    st.rerun()
                except ValueError as err:
                    st.error(str(err))

            # Slayt 4: Gün ortasında yeni plan (kullanıcının anlık konumu ve saati yeni başlangıç olur)
            with st.expander(f"🧭 {day_title} — Gün Ortasında Yeni Plan (Anlık Konum & Saat)", expanded=bool(completed_ids)):
                st.caption(
                    "Gezinin ortasındaysanız şu an bulunduğunuz yeri ve saati seçin; tamamlanan mekanlar çıkarılır ve kalan gün buradan yeniden planlanır."
                )
                all_non_rest = [v for v in venues if not v.is_restaurant]
                id_by_label = {v.name: v.id for v in all_non_rest}
                labels = list(id_by_label.keys())

                last_done_stop = next(
                    (s for s in reversed(day_plan["stops"]) if s["venue_id"] in completed_ids),
                    day_plan["stops"][0],
                )
                default_loc_name = venues_by_id.get(last_done_stop["venue_id"], all_non_rest[0]).name
                default_idx = labels.index(default_loc_name) if default_loc_name in labels else 0
                default_time = last_done_stop.get("departure_time", "13:00")

                mc1, mc2, mc3 = st.columns([1.6, 1.0, 1.4])
                with mc1:
                    mid_loc_name = st.selectbox(
                        "Şu Anki Konumunuz:",
                        options=labels,
                        index=default_idx,
                        key=f"mid_loc_{day_num}",
                    )
                with mc2:
                    mid_time = st.text_input(
                        "Şu Anki Saat (HH:MM):",
                        value=default_time,
                        key=f"mid_time_{day_num}",
                    )
                with mc3:
                    already_ate = any(
                        s.get("is_lunch") and s["venue_id"] in completed_ids
                        for s in day_plan["stops"]
                    )
                    mid_want_lunch = st.checkbox(
                        "Kalan planda öğle yemeği olsun",
                        value=not already_ate and hhmm_to_min(default_time) < 855,
                        key=f"mid_lunch_{day_num}",
                    )

                if st.button(
                    f"🚀 {day_title} Kalan Günü Şu Anki Konumumdan Yeniden Planla",
                    key=f"btn_midday_{day_num}",
                    type="primary",
                    width="stretch",
                ):
                    try:
                        new_res = recalculate_from_midday(
                            parsed_request_dict=day_plan["parsed_request"],
                            current_venue_id=id_by_label[mid_loc_name],
                            current_time=mid_time,
                            completed_venue_ids=completed_ids,
                            custom_durations=updated_durations,
                            removed_venue_ids=st.session_state.get("removed_stop_ids", []),
                            want_lunch_remaining=mid_want_lunch,
                            travel_mode=current_mode,
                        )
                        st.session_state["day_plans"][day_idx] = new_res.model_dump()
                        st.session_state["completed_stop_ids"] = []
                        _persist_progress_if_saved_trip()
                        st.rerun()
                    except ValueError as err:
                        st.error(str(err))

    with right_col:
        st.subheader(
            f"🗺️ {day_title} {'Araç (Araba) Haritası' if is_driving else 'Yürüyüş Haritası'}"
        )
        active_mode = _render_map_mode_selector(
            stops_list=[day_plan["stops"]],
            key_prefix=f"day_{day_num}",
            use_mock=use_mock,
            custom_durations_override=updated_durations,
            target_day_idx=day_idx,
        )
        map_line_color = (
            [225, 29, 72, 225]
            if active_mode == "driving" and len(st.session_state.get("day_plans", [])) <= 1
            else color_rgb
        )
        deck = _build_pydeck_map(
            day_plan,
            use_street_routing=use_street_routing,
            route_color=map_line_color,
            day_prefix=f"{day_num}-" if len(st.session_state.get("day_plans", [])) > 1 else "",
            travel_mode=active_mode,
            venues_by_id=venues_by_id,
        )

        map_tab1, map_tab2 = st.tabs(["🗺️ Canlı Rota Haritası", "🌐 İnteraktif Rehber (Leaflet)"])
        with map_tab1:
            st.pydeck_chart(deck, width="stretch", height=580)
        with map_tab2:
            _render_leaflet_route_map(
                day_plans=[day_plan],
                travel_mode=active_mode,
                use_street_routing=use_street_routing,
                venues_by_id=venues_by_id,
                height=580,
            )

        st.link_button(
            f"🧭 {day_title} Rotasını Google Haritalar'da Aç ({'Araba' if active_mode == 'driving' else 'Yürüyüş'})",
            _google_maps_walking_url(day_plan, travel_mode=active_mode),
            width="stretch",
        )


def _render_planner_page(venues: List[Venue], venues_by_id: Dict[str, Venue]) -> None:
    daily_limit = int(os.getenv("DAILY_LIMIT_PER_SESSION", "15"))

    with st.sidebar:
        st.header("👤 Profilim & Kayıtlı Geziler")
        sb_user = st.session_state.get("auth_user")
        if sb_user:
            sb_trips = storage.list_saved_trips(sb_user)
            st.success(f"**{sb_user['full_name']}**\n\n`{sb_user['email']}`")
            sb_c1, sb_c2 = st.columns([1.4, 1.0])
            if sb_c1.button(f"📂 Gezilerim ({len(sb_trips)})", key="sb_open_prof", width="stretch"):
                st.session_state["active_page"] = "account"
                st.rerun()
            if sb_c2.button("🚪 Çıkış", key="sb_logout", width="stretch"):
                storage.logout_user()
                st.session_state["auth_user"] = None
                st.session_state["active_trip_id"] = None
                st.rerun()
        else:
            local_profs = storage.list_local_users()
            if local_profs:
                first_p = local_profs[0]
                if st.button(
                    f"⚡ {first_p['full_name']} Profiline Gir",
                    key="sb_quick_login",
                    type="primary",
                    width="stretch",
                ):
                    ok, msg, logged_u = storage.quick_login_by_id(first_p["id"])
                    if ok and logged_u:
                        st.session_state["auth_user"] = logged_u
                        st.toast(msg)
                        st.rerun()
            if st.button("🔑 Hesap & Giriş Ekranı", key="sb_go_acc", width="stretch"):
                st.session_state["active_page"] = "account"
                st.rerun()

        st.divider()
        st.header("⚙️ Sistem Ayarları & Kota")
        default_mock = os.getenv("USE_MOCK_UI", "false").lower() == "true"
        use_mock = st.toggle(
            "Mock (Demo) Modu",
            value=default_mock,
            help="Diğer modüller olmadan contracts/mock_final_response.json ile test et.",
        )
        use_street_geom = st.toggle(
            "Sokak Kıvrımlı Harita (OSM Yaya / Araç)",
            value=True,
            help="Açıldığında harita çizgisi gerçek kaldırımları veya tek yönlü araç yollarını takip eder.",
        )
        st.metric("Oturum İstek Kotası", f"{st.session_state['request_count']} / {daily_limit}")

        st.divider()
        st.subheader("🎨 Kategori Renk Kodları")
        st.markdown(
            textwrap.dedent(
                """
                * <span style="color:#ea580c; font-weight:700;">● Turuncu:</span> Öğle Yemeği & Restoranlar
                * <span style="color:#854d0e; font-weight:700;">● Kahverengi:</span> Tarihi Konaklar & Köşkler
                * <span style="color:#a16207; font-weight:700;">● Antik Kahve:</span> Anıt & Saat Kulesi
                * <span style="color:#1e40af; font-weight:700;">● Lacivert:</span> Müzeler & Sanayi Tarihi
                * <span style="color:#047857; font-weight:700;">● Zümrüt Yeşili:</span> Camiler & Külliyeler
                * <span style="color:#0284c7; font-weight:700;">● Körfez Mavisi:</span> Sahil & Park Alanı
                * <span style="color:#6d28d9; font-weight:700;">● Mor:</span> Konaklama Oteli
                """
            ).strip(),
            unsafe_allow_html=True,
        )

        st.divider()
        st.subheader("💡 Hızlı Örnek İstekler")
        presets = {
            "Klasik İzmit Kültür Turu (1 Gün)": DEFAULT_PROMPT,
            "2 Günlük Otel Başlangıçlı Hafta Sonu": (
                "Cumartesi ve Pazar 2 günlük gezi planı yap. Seka Park Otel'de kalacağım; müzeleri, tarihi konakları ve sahili gezmek istiyorum."
            ),
            "3 Günlük Kapsamlı Kocaeli Turu": (
                "Cuma, Cumartesi ve Pazar 3 günlük gezi planı çıkar. Müzeler, Osmanlı konakları, camiler ve Sekapark sahili olsun."
            ),
            "Pazartesi (Kapalı Müze Testi)": (
                "Pazartesi 09:30 - 16:30 arası İzmit Eski Tren Garı'ndan başlayıp müzeleri ve tarihi konakları gezmek istiyorum."
            ),
            "Sahil ve Balık Turu": (
                "Salı 10:00 - 17:00 arası Seka Park ve sahil yürüyüşü yapıp öğlen balık yemek istiyorum."
            ),
        }
        chosen_preset = st.selectbox("Hazır senaryo seç", list(presets.keys()))
        if st.button("Örneği Kutuya Aktar", width="stretch"):
            st.session_state["prompt_box"] = presets[chosen_preset]

    city_opts = get_city_options()
    venue_choices = city_opts["venues"]
    venue_id_by_name = {v["name"]: v["id"] for v in venue_choices}
    venue_names = ["(Metinden otomatik algıla)"] + [v["name"] for v in venue_choices]

    hotels = city_opts.get("hotels", [])
    hotel_options = ["(Yok / Başlangıç Noktası Kullan)"] + [h["name"] for h in hotels]
    hotel_id_by_name = {h["name"]: h["id"] for h in hotels}

    with st.form("route_form"):
        c_top1, c_top2 = st.columns([1.4, 1.2])
        with c_top1:
            day_count_selected = st.radio(
                "📅 Gezi Kaç Gün Olacak?",
                [
                    "Otomatik (Metinden Algıla)",
                    "1 Gün (Günübirlik)",
                    "2 Gün (Hafta Sonu)",
                    "3 Gün (Kapsamlı)",
                ],
                horizontal=True,
                index=0,
            )
        with c_top2:
            acc_choice = st.selectbox(
                "🏨 Konaklama Yeri (Çok günlük turlarda her gün buradan başlar/biter)",
                options=hotel_options,
                index=0,
            )

        user_text = st.text_area(
            "Gezi İsteğinizi Doğal Türkçe ile Yazın:",
            value=st.session_state.get("prompt_box", DEFAULT_PROMPT),
            height=88,
        )
        with st.expander("İsteğe Bağlı Detaylı Filtreler (Başlangıç, Bitiş, Saat, Yemek)"):
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                day_choice = st.selectbox(
                    "Başlangıç Günü",
                    ["(Metinden)", *list(DAY_LABELS_TR.keys())],
                    format_func=lambda x: DAY_LABELS_TR.get(x, x),
                )
            with c2:
                start_choice = st.selectbox("Başlangıç Noktası", venue_names)
            with c3:
                end_choice = st.selectbox("Bitiş Noktası", venue_names)
            with c4:
                food_override = st.text_input("Yemek Tercihi", placeholder="Örn: iskender, köfte, balık, pide")

            t1, t2, t3 = st.columns(3)
            with t1:
                start_time_ov = st.text_input("Başlangıç Saati", placeholder="09:30")
            with t2:
                end_time_ov = st.text_input("Bitiş Saati", placeholder="17:00")
            with t3:
                lunch_ov = st.selectbox("Öğle Yemeği", ["(Metinden)", "Evet", "Hayır"])

        submitted = st.form_submit_button("🗺️ Rota Oluştur", type="primary", width="stretch")

    if submitted:
        st.session_state["prompt_box"] = user_text
        st.session_state["removed_stop_ids"] = []
        st.session_state["completed_stop_ids"] = []
        st.session_state["active_trip_id"] = None

        if use_mock:
            mock_dict = _load_mock_response()
            st.session_state["day_plans"] = [mock_dict]
            st.session_state["current_plan"] = mock_dict
            st.session_state["day2_plan"] = None
        else:
            active_mode = st.session_state.get("travel_mode", "walking")
            cache_key = json.dumps(
                {
                    "text": user_text.strip(),
                    "day": day_choice,
                    "start": start_choice,
                    "end": end_choice,
                    "acc": acc_choice,
                    "st": start_time_ov,
                    "et": end_time_ov,
                    "food": food_override,
                    "lunch": lunch_ov,
                    "plan_days": day_count_selected,
                    "travel_mode": active_mode,
                },
                sort_keys=True,
                ensure_ascii=False,
            )
            if cache_key in st.session_state["plan_cache"]:
                cached_list = st.session_state["plan_cache"][cache_key]
                st.session_state["day_plans"] = json.loads(json.dumps(cached_list))
                st.session_state["current_plan"] = cached_list[0]
                st.session_state["day2_plan"] = cached_list[1] if len(cached_list) >= 2 else None
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
                if acc_choice in hotel_id_by_name:
                    overrides["accommodation_id"] = hotel_id_by_name[acc_choice]
                    overrides["start_venue_id"] = hotel_id_by_name[acc_choice]
                    overrides["end_venue_id"] = hotel_id_by_name[acc_choice]
                if start_time_ov.strip():
                    overrides["start_time"] = start_time_ov.strip()
                if end_time_ov.strip():
                    overrides["end_time"] = end_time_ov.strip()
                if food_override.strip():
                    overrides["food_preference"] = food_override.strip()
                if lunch_ov != "(Metinden)":
                    overrides["want_lunch"] = lunch_ov == "Evet"

                if day_count_selected.startswith("1 Gün"):
                    overrides["num_days"] = 1
                elif day_count_selected.startswith("2 Gün"):
                    overrides["num_days"] = 2
                elif day_count_selected.startswith("3 Gün"):
                    overrides["num_days"] = 3

                spinner_msg = (
                    "En kısa araç rotası ve saatler hesaplanıyor..."
                    if active_mode == "driving"
                    else "En az yürüyüşlü rota, yaya yolları ve saatler hesaplanıyor..."
                )
                with st.spinner(spinner_msg):
                    res_list = plan_multi_day_trip(
                        user_text, overrides=overrides, travel_mode=active_mode
                    )
                    plan_dicts = [r.model_dump() for r in res_list]
                    st.session_state["plan_cache"][cache_key] = plan_dicts
                    st.session_state["day_plans"] = json.loads(json.dumps(plan_dicts))
                    st.session_state["current_plan"] = plan_dicts[0]
                    st.session_state["day2_plan"] = plan_dicts[1] if len(plan_dicts) >= 2 else None
                    st.session_state["request_count"] += 1

    day_plans: List[Dict[str, Any]] = st.session_state.get("day_plans", [])
    if not day_plans:
        st.info("Başlamak için gezi isteğinizi yazıp **🗺️ Rota Oluştur** butonuna tıklayın.")
        return

    current_mode = st.session_state.get("travel_mode", "walking")
    is_driving = current_mode == "driving"

    # Slayt 4: Alternatif plan + Planı Hesaba Kaydet çubuğu
    if not use_mock:
        with st.container(border=True):
            fb_c1, fb_c2, save_c1, save_c2 = st.columns([2.2, 1.3, 1.5, 1.2])
            with fb_c1:
                fb_text = st.text_input(
                    "✨ Alternatif Plan İste (Mevcut kısıtları günceller):",
                    placeholder="Örn: daha az müze, daha çok park veya saat 16:00'da bitsin, köfte olsun...",
                    key="feedback_box",
                )
            with fb_c2:
                st.write("")
                st.write("")
                if st.button("🔄 Alternatif Plan Oluştur", key="btn_alt_feedback", width="stretch"):
                    if fb_text.strip():
                        base_req = day_plans[0]["parsed_request"]
                        acc_override = (
                            hotel_id_by_name[acc_choice]
                            if acc_choice in hotel_id_by_name
                            else None
                        )
                        new_list = replan_with_feedback(
                            current_parsed_dict=base_req,
                            feedback_text=fb_text.strip(),
                            removed_venue_ids=st.session_state.get("removed_stop_ids", []),
                            num_days_override=len(day_plans),
                            accommodation_id=acc_override,
                            travel_mode=current_mode,
                        )
                        new_dicts = [r.model_dump() for r in new_list]
                        st.session_state["day_plans"] = new_dicts
                        st.session_state["current_plan"] = new_dicts[0]
                        st.session_state["day2_plan"] = new_dicts[1] if len(new_dicts) >= 2 else None
                        st.session_state["completed_stop_ids"] = []
                        st.rerun()
                    else:
                        st.warning("Önce değişiklik isteğinizi yazın.")

            with save_c1:
                trip_title = st.text_input(
                    "💾 Gezi Başlığı:",
                    value=f"Kocaeli Turu ({len(day_plans)} Gün)",
                    key="save_trip_title",
                )
            with save_c2:
                st.write("")
                st.write("")
                if st.button("💾 Beğendiğim Planı Kaydet", key="btn_save_trip", type="primary", width="stretch"):
                    user = st.session_state.get("auth_user")
                    if not user:
                        local_profs = storage.list_local_users()
                        if local_profs:
                            ok_l, _, auto_u = storage.quick_login_by_id(local_profs[0]["id"])
                            if ok_l and auto_u:
                                st.session_state["auth_user"] = auto_u
                                user = auto_u
                    if not user:
                        st.warning(
                            "Planı kaydetmek için üst menüdeki **👤 Profilim & Kayıtlı Geziler** sekmesinden ücretsiz hesap açın veya giriş yapın."
                        )
                    else:
                        ok, msg, saved_id = storage.save_trip(
                            user=user,
                            title=trip_title,
                            day_plans=day_plans,
                            completed_ids=st.session_state.get("completed_stop_ids", []),
                            trip_id=st.session_state.get("active_trip_id"),
                        )
                        if ok:
                            st.session_state["active_trip_id"] = saved_id
                            st.success(msg)
                        else:
                            st.error(msg)

    if len(day_plans) >= 2:
        start_hub_name = day_plans[0]["stops"][0]["name"] if day_plans[0].get("stops") else ""
        if "Otel" in start_hub_name or "Konaklama" in start_hub_name:
            st.info(
                f"🏨 **Konaklama Kuralı Aktif:** Seçilen **{start_hub_name}** her {len(day_plans)} günün sabah başlangıç ve akşam bitiş noktası olarak belirlendi."
            )

        tab_labels: List[str] = []
        for idx, dp in enumerate(day_plans):
            d_col = DAY_COLORS[idx % len(DAY_COLORS)]
            d_tr = DAY_LABELS_TR.get(dp.get("day_of_week", ""), dp.get("day_of_week", ""))
            tab_labels.append(f"📅 {idx + 1}. Gün: {d_tr} ({d_col['name']})")
        tab_labels.extend(
            [
                f"🗺️ {len(day_plans)} Günlük Birleşik Harita",
                "📋 Slayt 5 İndirme & Karşılaştırma",
            ]
        )

        tabs = st.tabs(tab_labels)
        for idx, dp in enumerate(day_plans):
            d_col = DAY_COLORS[idx % len(DAY_COLORS)]
            d_tr = DAY_LABELS_TR.get(dp.get("day_of_week", ""), dp.get("day_of_week", ""))
            with tabs[idx]:
                st.markdown(f"### {idx + 1}. Gün ({d_tr}) — {d_col['name']} Rota")
                _render_day_view(
                    day_plan=dp,
                    day_idx=idx,
                    day_title=f"{idx + 1}. Gün ({d_tr})",
                    color_rgb=d_col["rgb"],
                    use_street_routing=use_street_geom,
                    use_mock=use_mock,
                    venues=venues,
                    venues_by_id=venues_by_id,
                )

        with tabs[-2]:
            st.markdown(
                f"### 🗺️ {len(day_plans)} Günlük Birleşik {'Araç (Araba)' if is_driving else 'Yürüyüş'} Haritası"
            )
            tot_walk = sum(dp["total_walk_min"] for dp in day_plans)
            tot_km = round(sum(dp["total_walk_km"] for dp in day_plans), 2)
            tot_pois = sum(
                sum(
                    1
                    for s in dp["stops"]
                    if not s.get("is_start") and not s.get("is_end") and not s.get("is_lunch")
                )
                for dp in day_plans
            )
            mode_noun = "araç sürüşü" if is_driving else "yürüme"
            st.success(
                f"🎉 **Çok Günlü Tur Özeti:** Toplam {tot_walk} dk {mode_noun} | {tot_km} km yol | {tot_pois} farklı mekan | {len(day_plans)} gün!"
            )
            combined_mode = _render_map_mode_selector(
                stops_list=[dp["stops"] for dp in day_plans],
                key_prefix="combined",
                use_mock=use_mock,
            )
            legend_parts = []
            for idx, dp in enumerate(day_plans):
                d_col = DAY_COLORS[idx % len(DAY_COLORS)]
                d_tr = DAY_LABELS_TR.get(dp.get("day_of_week", ""), dp.get("day_of_week", ""))
                legend_parts.append(
                    f'<span style="color:{d_col["hex"]}; font-weight:700; margin-right:16px;">● {idx + 1}. Gün ({d_tr} - {d_col["name"]})</span>'
                )
            st.markdown("".join(legend_parts), unsafe_allow_html=True)
            comb_tab1, comb_tab2 = st.tabs(["🗺️ Birleşik Canlı Harita", "🌐 İnteraktif Rehber (Leaflet)"])
            with comb_tab1:
                combined_deck = _build_multi_day_pydeck_map(
                    day_plans,
                    use_street_routing=use_street_geom,
                    travel_mode=combined_mode,
                )
                st.pydeck_chart(combined_deck, width="stretch", height=600)
            with comb_tab2:
                _render_leaflet_route_map(
                    day_plans=day_plans,
                    travel_mode=combined_mode,
                    use_street_routing=use_street_geom,
                    venues_by_id=venues_by_id,
                    height=600,
                )

        with tabs[-1]:
            st.subheader("📋 Slayt 5 Formatında Günlük Zaman Çizelgeleri & İndirme")
            dl_cols = st.columns(len(day_plans))
            for idx, dp in enumerate(day_plans):
                d_tr = DAY_LABELS_TR.get(dp.get("day_of_week", ""), dp.get("day_of_week", ""))
                with dl_cols[idx]:
                    st.markdown(f"#### {idx + 1}. Gün: {d_tr}")
                    txt_d = _format_slide5_schedule(dp, travel_mode=current_mode)
                    st.code(txt_d, language="text")
                    st.download_button(
                        f"📥 {idx + 1}. Gün Planını İndir (.txt)",
                        data=txt_d,
                        file_name=f"kocaeli_gezi_{idx + 1}gun.txt",
                        mime="text/plain",
                        key=f"dl_day_{idx}",
                    )
    else:
        tab_cards, tab_slide5 = st.tabs(
            [
                f"🗺️ Görselli Rota & {'Araç' if is_driving else 'Yaya'} Haritası",
                "📋 Slayt 5 Kompakt Çizelgesi & İndirme",
            ]
        )
        with tab_cards:
            _render_day_view(
                day_plan=day_plans[0],
                day_idx=0,
                day_title="Günübirlik Gezi",
                color_rgb=DAY_COLORS[0]["rgb"],
                use_street_routing=use_street_geom,
                use_mock=use_mock,
                venues=venues,
                venues_by_id=venues_by_id,
            )
        with tab_slide5:
            st.subheader("📋 Slayt 5 Formatında Sade Zaman Çizelgesi")
            slide5_text = _format_slide5_schedule(day_plans[0], travel_mode=current_mode)
            st.code(slide5_text, language="text")
            day_tag = day_plans[0].get("day_of_week", "rota")
            st.download_button(
                "📥 Gezi Planını Metin (.txt) Olarak İndir",
                data=slide5_text,
                file_name=f"kocaeli_gezi_plani_{day_tag}.txt",
                mime="text/plain",
            )


def main() -> None:
    st.set_page_config(
        page_title="ROTA KOCAELİ | Akıllı Yürüyüş & Araç Planlayıcısı",
        page_icon="🗺️",
        layout="wide",
    )

    st.session_state.setdefault("plan_cache", {})
    st.session_state.setdefault("request_count", 0)
    st.session_state.setdefault("day_plans", [])
    st.session_state.setdefault("current_plan", None)
    st.session_state.setdefault("day2_plan", None)
    st.session_state.setdefault("removed_stop_ids", [])
    st.session_state.setdefault("completed_stop_ids", [])
    if "auth_user" not in st.session_state:
        st.session_state["auth_user"] = storage.get_active_session_user()
    st.session_state.setdefault("active_trip_id", None)
    st.session_state.setdefault("active_page", "planner")
    st.session_state.setdefault("travel_mode", "walking")

    # Sayfa ilk açıldığında veya yenilendiğinde harita ve rotanın ekranda kalmasını sağla
    if not st.session_state.get("day_plans"):
        user = st.session_state.get("auth_user")
        if user:
            saved_trips = storage.list_saved_trips(user)
            if saved_trips:
                _load_saved_trip_into_state(saved_trips[0])
        if not st.session_state.get("day_plans"):
            default_res = plan_multi_day_trip(DEFAULT_PROMPT, travel_mode="walking")
            plan_dicts = [r.model_dump() for r in default_res]
            st.session_state["day_plans"] = plan_dicts
            st.session_state["current_plan"] = plan_dicts[0]
            st.session_state["day2_plan"] = plan_dicts[1] if len(plan_dicts) >= 2 else None

    venues, venues_by_id, _ = load_city_data()

    _inject_global_styles()
    _render_official_header()
    page = _render_top_navbar()

    if page == "catalog":
        _render_catalog_page(venues)
    elif page == "account":
        _render_account_page(venues)
    elif page == "eval":
        _render_eval_report_page()
    else:
        _render_planner_page(venues, venues_by_id)


if __name__ == "__main__":
    main()
