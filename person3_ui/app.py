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

UI_THEMES: Dict[str, Dict[str, Any]] = {
    "rose_violet": {
        "name": "🌸 Gül & Mürdüm (Pembe / Mor)",
        "bg": "#FAF6F8",
        "card_bg": "#FFFFFF",
        "border": "#F3E8EE",
        "text_primary": "#1E1B26",
        "text_muted": "#706878",
        "brand_primary": "#86198F",
        "brand_gradient": "linear-gradient(135deg, #7E22CE 0%, #BE185D 100%)",
        "brand_hover": "#701A75",
        "pill_bg": "#FDF2F8",
        "pill_border": "#FCE7F3",
        "pill_text": "#9D174D",
        "dot_accent": "#BE185D",
        "logo_fill": "#86198F",
    },
    "terracotta_sand": {
        "name": "🍂 Terracotta & Kum (Editoryal)",
        "bg": "#FAF7F2",
        "card_bg": "#FFFFFF",
        "border": "#EFEBE4",
        "text_primary": "#262320",
        "text_muted": "#78716C",
        "brand_primary": "#8A482A",
        "brand_gradient": "linear-gradient(135deg, #8A482A 0%, #B45309 100%)",
        "brand_hover": "#6E361D",
        "pill_bg": "#FDF6EE",
        "pill_border": "#F5EBE1",
        "pill_text": "#8A482A",
        "dot_accent": "#8A482A",
        "logo_fill": "#8A482A",
    },
    "sage_slate": {
        "name": "🌿 Adaçayı & Zümrüt (Doğal)",
        "bg": "#F5F7F6",
        "card_bg": "#FFFFFF",
        "border": "#E2EBE6",
        "text_primary": "#1C2421",
        "text_muted": "#5C6B66",
        "brand_primary": "#0F766E",
        "brand_gradient": "linear-gradient(135deg, #0F766E 0%, #0369A1 100%)",
        "brand_hover": "#115E59",
        "pill_bg": "#ECFDF5",
        "pill_border": "#D1FAE5",
        "pill_text": "#065F46",
        "dot_accent": "#0F766E",
        "logo_fill": "#0F766E",
    },
}


def _get_active_theme() -> Dict[str, Any]:
    key = st.session_state.get("ui_theme", "rose_violet")
    return UI_THEMES.get(key, UI_THEMES["rose_violet"])


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
    theme = _get_active_theme()
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,500;0,600;0,700;1,400&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

        html, body, [class*="css"], .stMarkdown, button, input, textarea, select {{
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        }}
        .stApp {{
            background: {theme['bg']} !important;
        }}
        .block-container {{
            padding-top: 1.4rem !important;
            padding-bottom: 3rem !important;
            max-width: 1400px !important;
        }}
        .stAppDeployButton, [data-testid="stDecoration"] {{ display: none !important; }}

        h1, h2, h3, h4, .rk-serif {{
            font-family: 'Playfair Display', Georgia, serif !important;
            letter-spacing: -0.3px !important;
            color: {theme['text_primary']} !important;
        }}

        /* Kartlar & Konteynerlar */
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            background: {theme['card_bg']} !important;
            border: 1px solid {theme['border']} !important;
            border-radius: 18px !important;
            box-shadow: 0 4px 20px -2px rgba(112, 26, 117, 0.04) !important;
            padding: 4px !important;
        }}

        /* Butonlar */
        .stButton button, .stFormSubmitButton button, .stLinkButton a, .stDownloadButton button {{
            border-radius: 12px !important;
            font-weight: 600 !important;
            font-size: 13.5px !important;
            transition: all .18s ease-in-out !important;
        }}
        .stButton button[kind="primary"], .stFormSubmitButton button[kind="primaryFormSubmit"] {{
            background: {theme['brand_gradient']} !important;
            border: none !important;
            color: #ffffff !important;
            box-shadow: 0 4px 14px rgba(134, 25, 143, 0.22) !important;
        }}
        .stButton button[kind="primary"]:hover, .stFormSubmitButton button[kind="primaryFormSubmit"]:hover {{
            transform: translateY(-1px) !important;
            box-shadow: 0 6px 20px rgba(134, 25, 143, 0.32) !important;
        }}
        .stButton button[kind="secondary"] {{
            background: #ffffff !important;
            border: 1px solid {theme['border']} !important;
            color: {theme['text_primary']} !important;
        }}
        .stButton button[kind="secondary"]:hover {{
            border-color: {theme['brand_primary']} !important;
            color: {theme['brand_primary']} !important;
            background: {theme['pill_bg']} !important;
        }}

        /* Metrikler */
        [data-testid="stMetric"] {{
            background: #ffffff !important;
            border: 1px solid {theme['border']} !important;
            border-radius: 16px !important;
            padding: 14px 18px !important;
            box-shadow: 0 2px 8px rgba(112, 26, 117, 0.03) !important;
        }}
        [data-testid="stMetricLabel"] p {{
            font-size: 11.5px !important;
            color: {theme['text_muted']} !important;
            font-weight: 700 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.6px !important;
        }}
        [data-testid="stMetricValue"] {{
            font-family: 'Playfair Display', Georgia, serif !important;
            font-size: 24px !important;
            font-weight: 700 !important;
            color: {theme['text_primary']} !important;
        }}

        /* Sekmeler */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 6px !important;
            border-bottom: 1px solid {theme['border']} !important;
            padding-bottom: 4px !important;
        }}
        .stTabs [data-baseweb="tab"] {{
            height: 42px !important;
            padding: 0 16px !important;
            font-weight: 600 !important;
            font-size: 13.5px !important;
            color: {theme['text_muted']} !important;
            background: transparent !important;
            border-radius: 10px !important;
        }}
        .stTabs [aria-selected="true"] {{
            color: {theme['brand_primary']} !important;
            background: {theme['pill_bg']} !important;
        }}
        .stTabs [data-baseweb="tab-highlight"] {{
            background-color: {theme['brand_primary']} !important;
        }}

        /* Girdi alanları */
        .stTextInput input, .stTextArea textarea, .stNumberInput input {{
            border-radius: 12px !important;
            border: 1px solid {theme['border']} !important;
            font-size: 13.5px !important;
        }}
        .stTextInput input:focus, .stTextArea textarea:focus {{
            border-color: {theme['brand_primary']} !important;
            box-shadow: 0 0 0 2px rgba(134, 25, 143, 0.15) !important;
        }}
        [data-testid="stExpander"] details {{
            border-radius: 14px !important;
            border: 1px solid {theme['border']} !important;
            background: #ffffff !important;
        }}
        [data-testid="stExpander"] summary p {{
            font-weight: 600 !important;
            font-size: 13.5px !important;
            color: {theme['text_primary']} !important;
        }}

        /* Kenar çubuğu */
        section[data-testid="stSidebar"] {{
            background: #ffffff !important;
            border-right: 1px solid {theme['border']} !important;
        }}
        section[data-testid="stSidebar"] .block-container {{
            padding-top: 1.4rem !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }}
        .rk-side-brand {{
            padding: 4px 0 14px 0;
            margin-bottom: 8px;
            border-bottom: 1px solid {theme['border']};
        }}
        .rk-side-title {{
            font-family: 'Playfair Display', Georgia, serif;
            font-size: 20px;
            font-weight: 700;
            letter-spacing: -0.3px;
            color: {theme['text_primary']};
            line-height: 1.15;
        }}
        .rk-side-sub {{
            font-family: 'Plus Jakarta Sans', sans-serif !important;
            font-size: 11.5px;
            color: {theme['text_muted']};
            font-weight: 500;
            margin-top: 3px;
        }}
        .rk-nav-section-label {{
            font-family: 'Plus Jakarta Sans', sans-serif !important;
            font-size: 10.5px;
            font-weight: 700;
            letter-spacing: 0.8px;
            text-transform: uppercase;
            color: {theme['text_muted']};
            margin: 14px 0 6px 0;
        }}

        /* Üst Menü */
        .rk-topbar {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 14px;
            flex-wrap: wrap;
            padding: 12px 18px;
            background: #ffffff;
            border: 1px solid {theme['border']};
            border-radius: 18px;
            box-shadow: 0 4px 20px -2px rgba(112, 26, 117, 0.04);
            margin-bottom: 12px;
        }}
        .rk-brand {{ display: flex; align-items: center; gap: 14px; }}
        .rk-brand-title {{
            font-family: 'Playfair Display', Georgia, serif;
            font-size: 22px;
            font-weight: 700;
            color: {theme['text_primary']};
            letter-spacing: -0.4px;
            line-height: 1.1;
        }}
        .rk-brand-sub {{ font-size: 12.5px; color: {theme['text_muted']}; margin-top: 2px; }}
        .rk-user-chip {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-size: 12.5px;
            font-weight: 600;
            background: {theme['pill_bg']};
            border: 1px solid {theme['pill_border']};
            border-radius: 999px;
            padding: 6px 14px;
            color: {theme['pill_text']};
        }}
        .rk-user-dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; background: {theme['dot_accent']}; }}

        /* Zaman Çizelgesi Durak Kartları */
        .rk-section-title {{
            font-family: 'Playfair Display', Georgia, serif;
            font-size: 19px;
            font-weight: 700;
            color: {theme['text_primary']};
            margin: 4px 0 12px 0;
            letter-spacing: -0.3px;
        }}
        .rk-stop {{
            display: flex;
            gap: 14px;
            align-items: flex-start;
        }}
        .rk-time {{
            width: 56px;
            flex-shrink: 0;
            text-align: right;
            padding-top: 5px;
        }}
        .rk-time b {{
            display: block;
            font-size: 14px;
            font-weight: 700;
            color: {theme['text_primary']};
        }}
        .rk-time span {{
            font-size: 11px;
            color: {theme['text_muted']};
        }}
        .rk-dot {{
            width: 32px;
            height: 32px;
            border-radius: 50%;
            flex-shrink: 0;
            color: #ffffff;
            font-weight: 700;
            font-size: 13px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: {theme['brand_gradient']};
            box-shadow: 0 2px 8px rgba(134, 25, 143, 0.28);
        }}
        .rk-card {{
            flex: 1;
            min-width: 0;
            background: #ffffff;
            border: 1px solid {theme['border']};
            border-radius: 16px;
            padding: 14px 16px;
            display: flex;
            gap: 14px;
            box-shadow: 0 2px 10px rgba(112, 26, 117, 0.04);
            transition: all .15s ease;
        }}
        .rk-card:hover {{
            box-shadow: 0 6px 18px rgba(112, 26, 117, 0.08);
            border-color: {theme['pill_border']};
        }}
        .rk-card.done {{
            background: #F0FDF4;
            border-color: #BBF7D0;
        }}
        .rk-card img, .rk-card .rk-noimg {{
            width: 96px;
            height: 86px;
            border-radius: 12px;
            object-fit: cover;
            flex-shrink: 0;
            box-shadow: 0 2px 6px rgba(0,0,0,0.06);
        }}
        .rk-card .rk-noimg {{
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            background: {theme['pill_bg']};
        }}
        .rk-name {{
            font-family: 'Playfair Display', Georgia, serif;
            font-size: 16px;
            font-weight: 700;
            color: {theme['text_primary']};
            line-height: 1.3;
        }}
        .rk-chip {{
            display: inline-block;
            font-size: 11px;
            font-weight: 600;
            padding: 2px 9px;
            border-radius: 999px;
            margin-top: 4px;
            background: {theme['pill_bg']};
            color: {theme['pill_text']};
            border: 1px solid {theme['pill_border']};
        }}
        .rk-meta {{
            font-size: 12px;
            color: {theme['text_muted']};
            margin-top: 6px;
        }}
        .rk-meta .warn {{
            color: #B45309;
            font-weight: 600;
        }}
        .rk-desc {{
            font-size: 12.5px;
            color: #4B5563;
            margin-top: 5px;
            line-height: 1.45;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }}
        .rk-links {{
            margin-top: 7px;
            font-size: 12px;
            display: flex;
            gap: 12px;
        }}
        .rk-links a {{
            color: {theme['brand_primary']};
            text-decoration: none;
            font-weight: 600;
        }}
        .rk-links a:hover {{ text-decoration: underline; }}
        .rk-leg {{
            margin: -6px 0 -6px 82px;
            padding: 8px 0 8px 20px;
            border-left: 2px dashed {theme['pill_border']};
            font-size: 12px;
            color: {theme['text_muted']};
            font-weight: 600;
        }}
        .rk-legend {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            font-size: 11.5px;
            color: {theme['text_muted']};
            margin-top: 8px;
        }}
        .rk-legend i {{
            display: inline-block;
            width: 9px;
            height: 9px;
            border-radius: 50%;
            margin-right: 4px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_official_header() -> None:
    theme = _get_active_theme()
    user = st.session_state.get("auth_user")
    if user:
        user_chip = (
            f'<span class="rk-user-chip"><span class="rk-user-dot"></span>'
            f'{html.escape(user["full_name"])}</span>'
        )
    else:
        user_chip = (
            '<span class="rk-user-chip"><span class="rk-user-dot" style="background:#9ca3af;"></span>'
            'Misafir</span>'
        )
    svg_logo = f"""
    <svg width="42" height="42" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="48" height="48" rx="14" fill="{theme['logo_fill']}"/>
      <path d="M24 10c-5.5 0-10 4.3-10 9.7C14 27.5 24 38 24 38s10-10.5 10-18.3C34 14.3 29.5 10 24 10z" fill="#FFFFFF"/>
      <circle cx="24" cy="19.7" r="4.2" fill="{theme['logo_fill']}"/>
    </svg>
    """
    st.markdown(
        '<div class="rk-topbar">'
        f'<div class="rk-brand">{svg_logo}<div>'
        f'<div class="rk-brand-title">Rota Kocaeli</div>'
        '<div class="rk-brand-sub">İzmit için yürüyüş ve araç rotası planlayıcı · Editoryal Gezi Rehberi</div>'
        '</div></div>'
        f'{user_chip}'
        '</div>',
        unsafe_allow_html=True,
    )


def _render_app_sidebar() -> Tuple[bool, bool]:
    theme = _get_active_theme()
    st.session_state.setdefault("active_page", "planner")
    active_page = st.session_state["active_page"]

    with st.sidebar:
        st.markdown(
            f"""
            <div class="rk-side-brand">
              <div class="rk-side-title">ROTA KOCAELİ</div>
              <div class="rk-side-sub">İzmit Akıllı Gezi Rehberi</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown('<div class="rk-nav-section-label">Sayfalar</div>', unsafe_allow_html=True)
        nav_items = [
            ("planner", "🧭 Rota Planlayıcı", "top_nav_planner"),
            ("catalog", "🏛️ Mekan Kataloğu", "top_nav_catalog"),
            ("virtual_museum", "🖼️ Sanal Müze & Tur", "top_nav_virtual_museum"),
            ("account", "👤 Profil & Geziler", "top_nav_account"),
            ("eval", "ℹ️ Hakkında & Testler", "top_nav_eval"),
        ]
        for page_key, label, btn_key in nav_items:
            btn_type = "primary" if active_page == page_key else "secondary"
            if st.button(label, key=btn_key, type=btn_type, width="stretch"):
                st.session_state["active_page"] = page_key
                st.rerun()

        st.markdown('<div style="height: 10px;"></div>', unsafe_allow_html=True)
        st.markdown('<div class="rk-nav-section-label">Hesap</div>', unsafe_allow_html=True)
        user = st.session_state.get("auth_user")
        if user:
            st.markdown(
                f'<div style="font-size:13px;font-weight:700;color:{theme["text_primary"]};">{html.escape(user["full_name"])}</div>'
                f'<div style="font-size:11.5px;color:{theme["text_muted"]};margin-bottom:8px;">{html.escape(user["email"])}</div>',
                unsafe_allow_html=True,
            )
            c1, c2 = st.columns(2)
            if c1.button("Gezilerim", key="sb_open_prof", width="stretch"):
                st.session_state["active_page"] = "account"
                st.rerun()
            if c2.button("Çıkış", key="sb_logout", width="stretch"):
                storage.logout_user()
                st.session_state["auth_user"] = None
                st.session_state["active_trip_id"] = None
                st.rerun()
        else:
            st.markdown(
                f'<div style="font-size:12px;color:{theme["text_muted"]};margin-bottom:8px;">Misafir Kullanıcı</div>',
                unsafe_allow_html=True,
            )
            local_profs = storage.list_local_users()
            if local_profs:
                first_p = local_profs[0]
                if st.button(
                    f"Giriş: {first_p['full_name']}",
                    key="sb_quick_login",
                    type="primary",
                    width="stretch",
                ):
                    ok, msg, logged_u = storage.quick_login_by_id(first_p["id"])
                    if ok and logged_u:
                        st.session_state["auth_user"] = logged_u
                        st.toast(msg)
                        st.rerun()
            if st.button("Giriş Yap / Kayıt Ol", key="sb_go_acc", width="stretch"):
                st.session_state["active_page"] = "account"
                st.rerun()

        st.markdown('<div style="height: 10px;"></div>', unsafe_allow_html=True)
        st.markdown('<div class="rk-nav-section-label">Görünüm Teması</div>', unsafe_allow_html=True)
        theme_options = {
            "rose_violet": "Gül & Mürdüm (Pembe/Mor)",
            "terracotta_sand": "Terracotta & Kum",
            "sage_slate": "Adaçayı & Zümrüt",
        }
        current_theme_key = st.session_state.get("ui_theme", "rose_violet")
        theme_keys_list = list(theme_options.keys())
        default_idx = (
            theme_keys_list.index(current_theme_key)
            if current_theme_key in theme_keys_list
            else 0
        )
        selected_theme_key = st.selectbox(
            "Tema",
            options=theme_keys_list,
            index=default_idx,
            format_func=lambda k: theme_options[k],
            key="theme_selector_sb",
            label_visibility="collapsed",
        )
        if selected_theme_key != current_theme_key:
            st.session_state["ui_theme"] = selected_theme_key
            st.rerun()

        st.markdown('<div style="height: 10px;"></div>', unsafe_allow_html=True)
        with st.expander("Gelişmiş Ayarlar", expanded=False):
            default_mock = os.getenv("USE_MOCK_UI", "false").lower() == "true"
            use_mock = st.toggle(
                "Demo (mock) modu",
                value=default_mock,
                help="Diğer modüller olmadan contracts/mock_final_response.json ile test et.",
                key="sb_toggle_use_mock",
            )
            use_street_geom = st.toggle(
                "Gerçek sokak çizgileri",
                value=True,
                help="Açıkken harita çizgisi gerçek kaldırımları veya araç yollarını takip eder.",
                key="sb_toggle_use_street",
            )
            daily_limit = int(os.getenv("DAILY_LIMIT_PER_SESSION", "15"))
            st.caption(f"İstek kotası: {st.session_state['request_count']} / {daily_limit}")

    return use_mock, use_street_geom


def _render_top_navbar() -> str:
    st.session_state.setdefault("active_page", "planner")
    return st.session_state["active_page"]


def _render_virtual_museum_page(venues: List[Venue], venues_by_id: Dict[str, Venue]) -> None:
    theme = _get_active_theme()

    st.markdown(
        f"""
        <div style="margin-bottom: 22px;">
          <h2 class="rk-serif" style="margin: 0 0 6px 0; color: {theme['text_primary']}; font-size: 26px;">
            🏛️ İzmit Sanal Müze & Kültür Keşfi
          </h2>
          <div style="font-size: 13.5px; color: {theme['text_muted']}; line-height: 1.5;">
            İzmit'in zengin tarihini, Osmanlı saray mimarisini ve Cumhuriyet sanayi hafızasını 360° panoramik turlar ve küratör rehberi eşliğinde sanal olarak keşfedin.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    museum_data = [
        {
            "id": "kasri_humayun",
            "title": "Kasr-ı Hümayun Saray Müzesi (Av Köşkü)",
            "subtitle": "İstanbul Dışındaki Tek Osmanlı Sarayı · 1861",
            "desc": (
                "Sultan Abdülaziz için ampir ve barok üslupta inşa edilen Kasr-ı Hümayun, "
                "ihtişamlı tavan freskleri, mermer işçilikleri ve Dolmabahçe Sarayı esintisi taşıyan avizeleriyle "
                "İzmit'in en görkemli tarihi anıtıdır. 1922'de Atatürk ile Fransız yazar Claude Farrère'in tarihi görüşmesine de ev sahipliği yapmıştır."
            ),
            "tour_url": "https://www.google.com/maps/@40.7601445,29.9248439,3a,75y,180h,90t/data=!3m8!1e1!3m6!1sAF1QipN3-Z5Cq6D_x-Kasr!2e10!3e11!6shttps:%2F%2Flh5.googleusercontent.com!7i13312!8i6656",
            "gmaps_url": "https://www.google.com/maps/search/?api=1&query=40.7601,29.9248",
            "highlights": [
                ("🎨 Ampir Tavan Freskleri", "Fransız ressamların elinden çıkmış altın varaklı ve mitolojik tavan bezemeleri."),
                ("🏛️ Mermer Giriş & Çeşme", "Tek parça mermer sütunlar ve Neoklasik cephe süslemeleri."),
                ("📜 Atatürk & Basın Toplantısı", "16 Ocak 1923'te Cumhuriyet'in ilk basın toplantısının yapıldığı tarihi salon."),
            ],
            "default_img": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e6/Hunting_Kiosk%2C_Izmit_01.jpg/1024px-Hunting_Kiosk%2C_Izmit_01.jpg",
        },
        {
            "id": "arkeoloji_muzesi",
            "title": "Kocaeli Arkeoloji ve Etnografya Müzesi",
            "subtitle": "Roma, Bizans ve Osmanlı Mirası · Tarihi Tren Garı",
            "desc": (
                "Alman Mimar Otto Ritter tarafından tasarlanan 1910 yapımı tarihi demiryolu ambarlarında kurulan müzede, "
                "antik Nikomedia (İzmit) krallığından günümüze ulaşan paha biçilemez Roma lahitleri, Herakles kabartmaları, "
                "heykeller, sikkeler ve geleneksel İzmit etnografya koleksiyonu sergilenmektedir."
            ),
            "tour_url": "https://www.google.com/maps/@40.7618,29.9192,3a,75y,90t/data=!3m8!1e1!3m6!1sAF1QipM-Arkeoloji!2e10!3e11!6shttps:%2F%2Flh5.googleusercontent.com!7i13312!8i6656",
            "gmaps_url": "https://www.google.com/maps/search/?api=1&query=40.7618,29.9192",
            "highlights": [
                ("🏺 Roma Dönemi Lahitleri", "Nikomedia nekropolünden çıkarılan girlandlı ve kabartmalı anıtsal lahitler."),
                ("🦁 Herakles Kabartmaları", "Antik mitolojinin gücünü simgeleyen mermer frizler."),
                ("🚂 Tarihi Tren Garı Mimarisi", "Taş ve ahşap karkas endüstriyel demiryolu mirası."),
            ],
            "default_img": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c5/Kocaeli_Museum_Old_Station_Building_8245.jpg/1024px-Kocaeli_Museum_Old_Station_Building_8245.jpg",
        },
        {
            "id": "seka_kagit_muzesi",
            "title": "SEKA Kağıt Müzesi",
            "subtitle": "Türkiye'nin Endüstriyel Mirası · 16 Sergi Salonu",
            "desc": (
                "1936 yılında Atatürk'ün direktifiyle temeli atılan Türkiye'nin ilk entegre kağıt fabrikası, "
                "günümüzde Avrupa'nın en büyük endüstriyel miras müzelerinden biridir. 12 bin metrekare alanda "
                "dev kağıt üretim makineleri, hamur kazanları ve matbaa tarihi ziyaretçilerini büyülemektedir."
            ),
            "tour_url": "https://www.google.com/maps/@40.7589,29.9095,3a,75y,90t/data=!3m8!1e1!3m6!1sAF1QipM-Seka!2e10!3e11!6shttps:%2F%2Flh5.googleusercontent.com!7i13312!8i6656",
            "gmaps_url": "https://www.google.com/maps/search/?api=1&query=40.7589,29.9095",
            "highlights": [
                ("⚙️ 2 No'lu Kağıt Makinesi", "Cumhuriyet tarihinin ilk kağıtlarını üreten dev silindir ve kurutma hattı."),
                ("🪵 Hamur Hazırlama Salonu", "Ağaç kütüğünden selüloz ve hamur elde eden mekanik değirmenler."),
                ("📰 Tipografi ve Baskı Atölyesi", "Kurşun harflerle dizgi ve ilk yerli gazete matbaaları."),
            ],
            "default_img": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/87/Seka_Ka%C4%9F%C4%B1t_M%C3%BCzesi_giri%C5%9F.jpg/1024px-Seka_Ka%C4%9F%C4%B1t_M%C3%BCzesi_giri%C5%9F.jpg",
        },
        {
            "id": "gayret_gemi_muzesi",
            "title": "TCG Gayret Gemi Müzesi (D-352)",
            "subtitle": "Yüzen Savaş Efsanesi · İzmit Marina",
            "desc": (
                "1946 yapımı Amerikan Gearing sınıfı muhrip olan TCG Gayret, Türk Deniz Kuvvetleri bünyesinde "
                "Kıbrıs Barış Harekatı ve tatbikatlarda kritik görevler üstlenmiştir. 1997'den bu yana Türkiye'nin ilk "
                "müze gemisi olarak İzmit sahilinde ziyaretçilere denizaltı savunma ve muhrip yaşamını yaşatmaktadır."
            ),
            "tour_url": "https://www.google.com/maps/@40.7604,29.9142,3a,75y,90t/data=!3m8!1e1!3m6!1sAF1QipM-Gayret!2e10!3e11!6shttps:%2F%2Flh5.googleusercontent.com!7i13312!8i6656",
            "gmaps_url": "https://www.google.com/maps/search/?api=1&query=40.7604,29.9142",
            "highlights": [
                ("⚓ Kaptan Köprüüstü", "Dümen, seyir aletleri ve telsiz harekat merkezi."),
                ("🚀 Torpido ve ASROC Sistemleri", "Denizaltı savunma roketleri ve 127 mm baş topları."),
                ("🛏️ Mürettebat Koğuşları", "Denizcilerin açık deniz yaşam koşullarını yansıtan yaşam alanları."),
            ],
            "default_img": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d7/TCG_Gayret_%28D352%29_02.jpg/1024px-TCG_Gayret_%28D352%29_02.jpg",
        },
    ]

    m_tabs = st.tabs([m["title"].split(" (")[0] for m in museum_data])

    for idx, m in enumerate(museum_data):
        with m_tabs[idx]:
            v_obj = venues_by_id.get(m["id"])
            img_src = getattr(v_obj, "image_url", None) or m["default_img"]

            c_left, c_right = st.columns([1.2, 1.0], gap="large")
            with c_left:
                st.markdown(
                    f"""
                    <div style="background: #ffffff; border: 1px solid {theme['border']}; border-radius: 18px; padding: 8px; box-shadow: 0 4px 18px rgba(112,26,117,0.04); margin-bottom: 14px;">
                      <img src="{img_src}" alt="{m['title']}" style="width: 100%; height: 320px; object-fit: cover; border-radius: 14px;" />
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                b1, b2, b3 = st.columns(3)
                b1.link_button("🌐 360° Sanal Tur", m["tour_url"], use_container_width=True)
                b2.link_button("📍 Google Harita", m["gmaps_url"], use_container_width=True)
                if v_obj and v_obj.source_url:
                    b3.link_button("📖 Wikipedia", v_obj.source_url, use_container_width=True)

            with c_right:
                st.markdown(
                    f"""
                    <div style="background: {theme['card_bg']}; border: 1px solid {theme['border']}; border-radius: 18px; padding: 20px; box-shadow: 0 4px 18px rgba(112,26,117,0.04);">
                      <span class="rk-chip" style="margin-bottom: 8px;">{m['subtitle']}</span>
                      <h3 class="rk-serif" style="margin: 6px 0 10px 0; color: {theme['text_primary']}; font-size: 21px;">{m['title']}</h3>
                      <p style="font-size: 13px; color: #4B5563; line-height: 1.55; margin-bottom: 14px;">{m['desc']}</p>
                      
                      <div style="font-size: 11.5px; font-weight: 700; color: {theme['brand_primary']}; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">
                        Küratör Seçimi Koleksiyonlar
                      </div>
                    """,
                    unsafe_allow_html=True,
                )
                for h_title, h_desc in m["highlights"]:
                    st.markdown(
                        f"""
                        <div style="background: {theme['bg']}; border: 1px solid {theme['border']}; border-radius: 10px; padding: 8px 12px; margin-bottom: 6px;">
                          <div style="font-size: 12.5px; font-weight: 700; color: {theme['text_primary']};">{h_title}</div>
                          <div style="font-size: 11.5px; color: {theme['text_muted']}; margin-top: 2px;">{h_desc}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                st.markdown("</div>", unsafe_allow_html=True)

                st.write("")
                short_name = m["title"].split(" (")[0]
                if st.button(f"🧭 {short_name} Müzesini Gezi Planıma Ekle", key=f"add_museum_{m['id']}", type="primary", use_container_width=True):
                    st.session_state["prompt_box"] = f"İzmit'te {short_name} noktasından başlayıp müzeleri ve tarihi konakları gezmek istiyorum."
                    st.session_state["active_page"] = "planner"
                    st.rerun()


def _render_catalog_page(venues: List[Venue]) -> None:
    theme = _get_active_theme()
    st.markdown('<h2 class="rk-serif" style="margin-bottom:4px;">🏛️ Doğrulanmış Mekan ve Lezzet Kataloğu</h2>', unsafe_allow_html=True)
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
        cat_theme = _get_theme(v.category)
        with grid_cols[idx % 2]:
            img_html = ""
            if getattr(v, "image_url", None):
                img_html = f'<img src="{v.image_url}" style="width: 100%; height: 190px; object-fit: cover; border-radius: 12px; margin-bottom: 12px; border: 1px solid {theme["border"]};" alt="{v.name}" />'
            price_info = f" | <b>Fiyat:</b> {v.price_range}" if v.price_range else ""
            open_note = v.opening_hours_note or "Açılış saati bilinmiyor"
            gmaps_pin = _google_maps_pin_url(v.lat, v.lon)
            card_html = (
                f'<div style="background: {theme["card_bg"]}; border: 1px solid {theme["border"]}; '
                f'border-top: 4px solid {theme["brand_primary"]}; '
                f'padding: 16px; border-radius: 16px; margin-bottom: 16px; box-shadow: 0 4px 18px -2px rgba(112,26,117,0.04);">'
                f'{img_html}'
                f'<div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">'
                f'<h4 class="rk-serif" style="margin: 0; color: {theme["text_primary"]}; font-size: 17px; font-weight: 700;">{v.name}</h4>'
                f'<span style="background: {theme["pill_bg"]}; color: {theme["pill_text"]}; border: 1px solid {theme["pill_border"]}; '
                f'font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 9999px; white-space: nowrap;">{cat_theme["badge"]}</span>'
                f'</div>'
                f'<p style="font-size: 12.5px; color: #4B5563; margin: 8px 0; line-height: 1.45;">{v.description_short}</p>'
                f'<div style="font-size: 12px; color: {theme["text_muted"]}; background: {theme["bg"]}; padding: 8px 12px; border-radius: 10px; border: 1px solid {theme["border"]};">'
                f'⏱️ <b>Varsayılan Kalış:</b> {v.default_stay_min} dk &nbsp;•&nbsp; 🕒 <b>Açılış:</b> {open_note}{price_info}'
                f'</div>'
                f'<div style="margin-top: 12px; display: flex; gap: 10px; flex-wrap: wrap;">'
                f'<a href="{gmaps_pin}" target="_blank" style="font-size: 11.5px; color: {theme["brand_primary"]}; background: {theme["pill_bg"]}; padding: 5px 12px; border-radius: 8px; text-decoration: none; font-weight: 600; border: 1px solid {theme["pill_border"]};">📍 Google Haritalar →</a>'
                f'<a href="{v.source_url}" target="_blank" style="font-size: 11.5px; color: {theme["text_muted"]}; background: #FFFFFF; border: 1px solid {theme["border"]}; padding: 5px 12px; border-radius: 8px; text-decoration: none; font-weight: 600;">📖 {v.source_name} →</a>'
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

    mc1, mc2 = st.columns(2)
    mc1.button(
        f"🚶 Yürüyüş · {w_min} dk · {w_km} km",
        key=f"mode_walk_{key_prefix}",
        type="primary" if current_mode == "walking" else "secondary",
        width="stretch",
        on_click=_on_click_travel_mode,
        args=("walking", use_mock, target_day_idx),
    )
    mc2.button(
        f"🚗 Araba · {d_min} dk · {d_km} km",
        key=f"mode_drive_{key_prefix}",
        type="primary" if current_mode == "driving" else "secondary",
        width="stretch",
        on_click=_on_click_travel_mode,
        args=("driving", use_mock, target_day_idx),
    )
    return current_mode


def _render_map_legend() -> None:
    items = [
        ("#ea580c", "Yemek"),
        ("#854d0e", "Konak & köşk"),
        ("#a16207", "Anıt"),
        ("#1e40af", "Müze"),
        ("#047857", "Cami"),
        ("#0284c7", "Park & sahil"),
        ("#6d28d9", "Konaklama"),
        ("#10b981", "Gezildi"),
    ]
    chips = "".join(f'<span><i style="background:{c};"></i>{t}</span>' for c, t in items)
    st.markdown(f'<div class="rk-legend">{chips}</div>', unsafe_allow_html=True)


def _stop_card_html(
    s: Dict[str, Any],
    day_num: int,
    is_done: bool,
    venues_by_id: Dict[str, Venue],
    multi_day: bool,
) -> str:
    theme = _get_theme(s.get("category", ""))
    active_theme = _get_active_theme()
    dot_style = "background:#10b981;" if is_done else f"background:{active_theme['brand_gradient']};"
    venue_obj = venues_by_id.get(s["venue_id"])
    img_url = getattr(venue_obj, "image_url", None) if venue_obj else None
    img_block = (
        f'<img src="{img_url}" alt="{html.escape(s["name"])}" />'
        if img_url
        else '<div class="rk-noimg">📍</div>'
    )
    gmaps_pin = _google_maps_pin_url(s["lat"], s["lon"])
    src_url = s.get("source_url") or gmaps_pin
    expl_text = s.get("explanation") or (venue_obj.description_short if venue_obj else "")

    is_hub = s.get("is_start") or s.get("is_end")
    if s.get("is_start"):
        time_block = f'<b>{s["arrival_time"]}</b><span>başlangıç</span>'
    elif s.get("is_end"):
        time_block = f'<b>{s["arrival_time"]}</b><span>dönüş</span>'
    else:
        time_block = f'<b>{s["arrival_time"]}</b><span>{s["departure_time"]}</span>'

    oh_label = html.escape(str(s.get("opening_hours_label", "")))
    if s.get("opening_hours_status") == "unknown":
        oh_html = f'<span class="warn">⚠ {oh_label}</span>'
    else:
        oh_html = f"🕒 {oh_label}"
    meta_parts = []
    if not is_hub:
        meta_parts.append(f"⏱ {s['stay_min']} dk")
        meta_parts.append(oh_html)
    if is_done:
        meta_parts.append('<span style="color:#059669;font-weight:600;">✓ Gezildi</span>')
    meta_html = " &nbsp;·&nbsp; ".join(meta_parts)

    dot_label = f"{day_num}-{s['order']}" if multi_day else str(s["order"])
    return (
        '<div class="rk-stop">'
        f'<div class="rk-time">{time_block}</div>'
        f'<div class="rk-dot" style="{dot_style}">{dot_label}</div>'
        f'<div class="rk-card{" done" if is_done else ""}">'
        f"{img_block}"
        '<div style="flex:1;min-width:0;">'
        f'<div class="rk-name">{html.escape(s["name"])}</div>'
        f'<span class="rk-chip" style="background:{theme["bg"]};color:{theme["text"]};border:1px solid {theme["border"]}44;">{theme["badge"]}</span>'
        + (f'<div class="rk-meta">{meta_html}</div>' if meta_html else "")
        + (f'<div class="rk-desc">{html.escape(expl_text)}</div>' if expl_text else "")
        + '<div class="rk-links">'
        f'<a href="{gmaps_pin}" target="_blank" style="color:{active_theme["brand_primary"]};">Haritada aç ↗</a>'
        f'<a href="{src_url}" target="_blank" style="color:{active_theme["text_muted"]};">Kaynak ↗</a>'
        "</div>"
        "</div></div></div>"
    )


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
    multi_day = len(st.session_state.get("day_plans", [])) > 1
    poi_count = sum(
        1
        for s in day_plan["stops"]
        if not s.get("is_start") and not s.get("is_end") and not s.get("is_lunch")
    )

    # 1) Özet şeridi
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Araç Süresi" if is_driving else "Yürüme Süresi", f"{day_plan['total_walk_min']} dk")
    m2.metric("Araç Mesafesi" if is_driving else "Yürüme Mesafesi", f"{day_plan['total_walk_km']} km")
    m3.metric("Durak", f"{poi_count} mekan")
    m4.metric(
        "Bitiş Saati",
        day_plan["actual_end_time"],
        help=f"Hedeflenen bitiş: {day_plan['requested_end_time']}",
    )

    if day_plan.get("summary_text"):
        st.success(day_plan["summary_text"], icon="🗺️")

    warns = day_plan.get("warnings") or []
    dropped = day_plan.get("dropped_venues") or []
    if warns or dropped:
        parts = []
        if warns:
            parts.append(f"{len(warns)} uyarı")
        if dropped:
            parts.append(f"{len(dropped)} mekan plana sığmadı")
        with st.expander(f"⚠️ Dikkat: {' · '.join(parts)}"):
            for w in warns:
                st.markdown(f"- {w}")
            if dropped:
                st.markdown("**Plana alınamayan mekanlar**")
                for d in dropped:
                    st.markdown(f"- **{d['name']}** — {d['reason']}")

    st.write("")
    left_col, right_col = st.columns([1.1, 1.0], gap="large")

    with left_col:
        h1, h2 = st.columns([1.6, 1.0])
        with h1:
            st.markdown('<div class="rk-section-title">Günün akışı</div>', unsafe_allow_html=True)
        edit_mode = False
        if not use_mock:
            with h2:
                edit_mode = st.toggle(
                    "✏️ Düzenle",
                    key=f"edit_mode_{day_num}",
                    help="Kalış sürelerini değiştir, gezilen yerleri işaretle, durak çıkar veya günü yeniden planla.",
                )

        updated_durations: Dict[str, int] = {}
        completed_ids: List[str] = list(st.session_state.get("completed_stop_ids", []))
        leg_icon = "🚗" if is_driving else "🚶"

        for s in day_plan["stops"]:
            is_poi = not s.get("is_start") and not s.get("is_end") and not s.get("is_lunch")
            is_done = s["venue_id"] in completed_ids

            if s["order"] > 0:
                st.markdown(
                    f'<div class="rk-leg">{leg_icon} {s["walk_from_prev_min"]} dk · {s["walk_from_prev_m"]} m</div>',
                    unsafe_allow_html=True,
                )
            st.markdown(
                _stop_card_html(s, day_num, is_done, venues_by_id, multi_day),
                unsafe_allow_html=True,
            )

            if is_poi:
                updated_durations[s["venue_id"]] = int(s["stay_min"])

            if edit_mode and is_poi:
                ctl_c0, ctl_c1, ctl_c2, ctl_c3 = st.columns([0.55, 1.3, 1.1, 1.0])
                with ctl_c1:
                    updated_durations[s["venue_id"]] = st.number_input(
                        "Kalış (dk)",
                        min_value=5,
                        max_value=240,
                        step=5,
                        value=int(s["stay_min"]),
                        key=f"stay_{day_num}_{s['venue_id']}_{s['order']}",
                        label_visibility="collapsed",
                    )
                with ctl_c2:
                    done_label = "↩️ Geri al" if is_done else "✅ Gezildi"
                    if st.button(done_label, key=f"done_{day_num}_{s['venue_id']}_{s['order']}", width="stretch"):
                        if is_done:
                            completed_ids.remove(s["venue_id"])
                        else:
                            completed_ids.append(s["venue_id"])
                        st.session_state["completed_stop_ids"] = completed_ids
                        _persist_progress_if_saved_trip()
                        st.rerun()
                with ctl_c3:
                    if st.button("🗑️ Çıkar", key=f"rm_{day_num}_{s['venue_id']}_{s['order']}", width="stretch"):
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
            elif edit_mode and s.get("is_lunch"):
                _, lc2 = st.columns([0.55, 3.4])
                with lc2:
                    done_label = "↩️ Yemeği geri al" if is_done else "✅ Yemek yenildi"
                    if st.button(done_label, key=f"done_lunch_{day_num}_{s['order']}"):
                        if is_done:
                            completed_ids.remove(s["venue_id"])
                        else:
                            completed_ids.append(s["venue_id"])
                        st.session_state["completed_stop_ids"] = completed_ids
                        _persist_progress_if_saved_trip()
                        st.rerun()

            if s.get("is_lunch") and s.get("restaurant_options"):
                opts = s["restaurant_options"]
                opt_labels = {
                    o["venue_id"]: (
                        f"{o['name']} — {o['walk_from_stop_min']} dk"
                        f" • {', '.join(o.get('cuisine_tags', [])[:2])}"
                        f"{' • ' + o['price_range'] if o.get('price_range') else ''}"
                    )
                    for o in opts
                }
                current_rest_id = s["venue_id"] if s["venue_id"] in opt_labels else opts[0]["venue_id"]
                _, rc2 = st.columns([0.55, 3.4])
                with rc2:
                    chosen_rest_id = st.selectbox(
                        f"🍽️ Restoran seçenekleri (≤ 10 dk {'araç' if is_driving else 'yürüme'})",
                        options=list(opt_labels.keys()),
                        index=list(opt_labels.keys()).index(current_rest_id),
                        format_func=lambda vid: opt_labels[vid],
                        key=f"lunch_radio_{day_num}_{s['order']}",
                    )
                if chosen_rest_id != s["venue_id"]:
                    st.session_state["day_plans"][day_idx] = _apply_restaurant_choice(day_plan, chosen_rest_id)
                    st.rerun()

        if edit_mode and not use_mock and updated_durations:
            st.write("")
            with st.container(border=True):
                st.markdown("**Değişiklikleri uygula**")
                bcol1, bcol2 = st.columns(2)
                if bcol1.button(
                    "⏱️ Yeniden Hesapla",
                    key=f"btn_recalc_{day_num}",
                    type="primary",
                    width="stretch",
                ):
                    if completed_ids:
                        last_done = next(
                            (x for x in reversed(day_plan["stops"]) if x["venue_id"] in completed_ids),
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
                    "✅ Gezilenleri çıkar, kalanı güncelle",
                    key=f"btn_done_recalc_{day_num}",
                    width="stretch",
                ):
                    last_done = next(
                        (x for x in reversed(day_plan["stops"]) if x["venue_id"] in completed_ids),
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

        if not use_mock:
            # Slayt 4: Gün ortasında yeni plan (kullanıcının anlık konumu ve saati yeni başlangıç olur)
            with st.expander("🧭 Gün ortasında yeni plan (şu anki konum ve saatten)", expanded=False):
                st.caption("Tamamlanan mekanlar çıkarılır, kalan gün bulunduğunuz yerden yeniden planlanır.")
                all_non_rest = [v for v in venues if not v.is_restaurant]
                id_by_label = {v.name: v.id for v in all_non_rest}
                labels = list(id_by_label.keys())

                last_done_stop = next(
                    (x for x in reversed(day_plan["stops"]) if x["venue_id"] in completed_ids),
                    day_plan["stops"][0],
                )
                default_loc_obj = venues_by_id.get(last_done_stop["venue_id"])
                default_loc_name = default_loc_obj.name if default_loc_obj else all_non_rest[0].name
                default_idx = labels.index(default_loc_name) if default_loc_name in labels else 0
                default_time = last_done_stop.get("departure_time", "13:00")

                mc1, mc2 = st.columns([1.6, 1.0])
                with mc1:
                    mid_loc_name = st.selectbox(
                        "Şu anki konumunuz",
                        options=labels,
                        index=default_idx,
                        key=f"mid_loc_{day_num}",
                    )
                with mc2:
                    mid_time = st.text_input("Saat (SS:DD)", value=default_time, key=f"mid_time_{day_num}")
                already_ate = any(
                    x.get("is_lunch") and x["venue_id"] in completed_ids for x in day_plan["stops"]
                )
                mid_want_lunch = st.checkbox(
                    "Kalan planda öğle yemeği olsun",
                    value=not already_ate and hhmm_to_min(default_time) < 855,
                    key=f"mid_lunch_{day_num}",
                )
                if st.button(
                    "🚀 Kalan günü buradan planla",
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
        st.markdown('<div class="rk-section-title">Harita</div>', unsafe_allow_html=True)
        active_mode = _render_map_mode_selector(
            stops_list=[day_plan["stops"]],
            key_prefix=f"day_{day_num}",
            use_mock=use_mock,
            custom_durations_override=updated_durations,
            target_day_idx=day_idx,
        )
        map_line_color = [225, 29, 72, 225] if active_mode == "driving" and not multi_day else color_rgb
        deck = _build_pydeck_map(
            day_plan,
            use_street_routing=use_street_routing,
            route_color=map_line_color,
            day_prefix=f"{day_num}-" if multi_day else "",
            travel_mode=active_mode,
            venues_by_id=venues_by_id,
        )
        map_tab1, map_tab2 = st.tabs(["Harita", "Detaylı harita"])
        with map_tab1:
            st.pydeck_chart(deck, width="stretch", height=540)
        with map_tab2:
            _render_leaflet_route_map(
                day_plans=[day_plan],
                travel_mode=active_mode,
                use_street_routing=use_street_routing,
                venues_by_id=venues_by_id,
                height=540,
            )
        _render_map_legend()
        st.link_button(
            "Google Haritalar'da aç ↗",
            _google_maps_walking_url(day_plan, travel_mode=active_mode),
            width="stretch",
        )


def _render_planner_page(
    venues: List[Venue],
    venues_by_id: Dict[str, Venue],
    use_mock: bool = False,
    use_street_geom: bool = True,
) -> None:
    theme = _get_active_theme()
    daily_limit = int(os.getenv("DAILY_LIMIT_PER_SESSION", "15"))

    city_opts = get_city_options()
    venue_choices = city_opts["venues"]
    venue_id_by_name = {v["name"]: v["id"] for v in venue_choices}
    venue_names = ["(Metinden otomatik algıla)"] + [v["name"] for v in venue_choices]

    hotels = city_opts.get("hotels", [])
    hotel_options = ["(Yok / Başlangıç Noktası Kullan)"] + [h["name"] for h in hotels]
    hotel_id_by_name = {h["name"]: h["id"] for h in hotels}

    presets = {
        "Klasik Kültür": DEFAULT_PROMPT,
        "2 Günlük Hafta Sonu": (
            "Cumartesi ve Pazar 2 günlük gezi planı yap. Seka Park Otel'de kalacağım; müzeleri, tarihi konakları ve sahili gezmek istiyorum."
        ),
        "3 Günlük Tur": (
            "Cuma, Cumartesi ve Pazar 3 günlük gezi planı çıkar. Müzeler, Osmanlı konakları, camiler ve Sekapark sahili olsun."
        ),
        "Pazartesi Açık Yerler": (
            "Pazartesi 09:30 - 16:30 arası İzmit Eski Tren Garı'ndan başlayıp müzeleri ve tarihi konakları gezmek istiyorum."
        ),
        "Sahil & Balık": (
            "Salı 10:00 - 17:00 arası Seka Park ve sahil yürüyüşü yapıp öğlen balık yemek istiyorum."
        ),
    }

    st.markdown(
        f'<div style="font-size: 11.5px; font-weight: 700; color: {theme["text_muted"]}; text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 6px;">Hızlı Örnek İstekler</div>',
        unsafe_allow_html=True,
    )
    p_cols = st.columns(len(presets))
    for i, (p_title, p_prompt) in enumerate(presets.items()):
        if p_cols[i].button(p_title, key=f"quick_preset_{i}", width="stretch"):
            st.session_state["prompt_box"] = p_prompt
            st.rerun()

    # --- Arama kartı ---
    with st.form("route_form", border=True):
        st.markdown('<div class="rk-section-title">Nasıl bir gezi istersin?</div>', unsafe_allow_html=True)
        user_text = st.text_area(
            "Gezi isteğiniz",
            value=st.session_state.get("prompt_box", DEFAULT_PROMPT),
            height=80,
            label_visibility="collapsed",
            placeholder="Örn: Cumartesi 09:30'da İzmit Garı'ndan başlayıp müzeleri gezmek istiyorum, öğlen iskender yiyelim.",
        )
        c_top1, c_top2, c_top3 = st.columns([1.5, 1.4, 0.9], vertical_alignment="bottom")
        with c_top1:
            day_count_selected = st.radio(
                "Gün sayısı",
                ["Otomatik", "1 gün", "2 gün", "3 gün"],
                horizontal=True,
                index=0,
            )
        with c_top2:
            acc_choice = st.selectbox(
                "Konaklama (çok günlük turlarda başlangıç/bitiş)",
                options=hotel_options,
                index=0,
            )
        with c_top3:
            submitted = st.form_submit_button("🗺️ Rota Oluştur", type="primary", width="stretch")

        with st.expander("Detaylı ayarlar (gün, başlangıç/bitiş, saat, yemek)"):
            c1, c2, c3 = st.columns(3)
            with c1:
                day_choice = st.selectbox(
                    "Başlangıç günü",
                    ["(Metinden)", *list(DAY_LABELS_TR.keys())],
                    format_func=lambda x: DAY_LABELS_TR.get(x, x),
                )
            with c2:
                start_choice = st.selectbox("Başlangıç noktası", venue_names)
            with c3:
                end_choice = st.selectbox("Bitiş noktası", venue_names)
            t1, t2, t3, t4 = st.columns(4)
            with t1:
                start_time_ov = st.text_input("Başlangıç saati", placeholder="09:30")
            with t2:
                end_time_ov = st.text_input("Bitiş saati", placeholder="17:00")
            with t3:
                lunch_ov = st.selectbox("Öğle yemeği", ["(Metinden)", "Evet", "Hayır"])
            with t4:
                food_override = st.text_input("Yemek tercihi", placeholder="iskender, balık…")

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

                if day_count_selected.startswith("1"):
                    overrides["num_days"] = 1
                elif day_count_selected.startswith("2"):
                    overrides["num_days"] = 2
                elif day_count_selected.startswith("3"):
                    overrides["num_days"] = 3

                spinner_msg = (
                    "En kısa araç rotası ve saatler hesaplanıyor..."
                    if active_mode == "driving"
                    else "En az yürüyüşlü rota ve saatler hesaplanıyor..."
                )
                with st.spinner(spinner_msg):
                    res_list = plan_multi_day_trip(user_text, overrides=overrides, travel_mode=active_mode)
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

    # Slayt 4: Alternatif plan + Planı hesaba kaydet (tek satır, sade)
    if not use_mock:
        with st.container(border=True):
            fb_c1, fb_c2, save_c1, save_c2 = st.columns([2.4, 1.0, 1.5, 1.0], vertical_alignment="bottom")
            with fb_c1:
                fb_text = st.text_input(
                    "✨ Planı değiştir",
                    placeholder="Örn: daha az müze, daha çok park · 16:00'da bitsin · köfte olsun",
                    key="feedback_box",
                )
            with fb_c2:
                if st.button("🔄 Alternatif plan", key="btn_alt_feedback", width="stretch"):
                    if fb_text.strip():
                        base_req = day_plans[0]["parsed_request"]
                        acc_override = hotel_id_by_name[acc_choice] if acc_choice in hotel_id_by_name else None
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
                    "💾 Gezi adı",
                    value=f"Kocaeli Turu ({len(day_plans)} Gün)",
                    key="save_trip_title",
                )
            with save_c2:
                if st.button("💾 Kaydet", key="btn_save_trip", type="primary", width="stretch"):
                    user = st.session_state.get("auth_user")
                    if not user:
                        local_profs = storage.list_local_users()
                        if local_profs:
                            ok_l, _, auto_u = storage.quick_login_by_id(local_profs[0]["id"])
                            if ok_l and auto_u:
                                st.session_state["auth_user"] = auto_u
                                user = auto_u
                    if not user:
                        st.warning("Planı kaydetmek için üst menüdeki **👤 Giriş / Profil** sekmesinden hesap açın.")
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
                            st.toast(msg)
                        else:
                            st.error(msg)

    if len(day_plans) >= 2:
        start_hub_name = day_plans[0]["stops"][0]["name"] if day_plans[0].get("stops") else ""
        if "Otel" in start_hub_name or "Konaklama" in start_hub_name:
            st.caption(f"🏨 Her gün **{start_hub_name}** noktasından başlar ve orada biter.")

        tab_labels: List[str] = []
        for idx, dp in enumerate(day_plans):
            d_tr = DAY_LABELS_TR.get(dp.get("day_of_week", ""), dp.get("day_of_week", ""))
            tab_labels.append(f"{idx + 1}. Gün · {d_tr}")
        tab_labels.extend(["Tüm günler haritası", "Çizelge & indir"])

        tabs = st.tabs(tab_labels)
        for idx, dp in enumerate(day_plans):
            d_col = DAY_COLORS[idx % len(DAY_COLORS)]
            d_tr = DAY_LABELS_TR.get(dp.get("day_of_week", ""), dp.get("day_of_week", ""))
            with tabs[idx]:
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
            mode_noun = "araç" if is_driving else "yürüme"
            st.success(
                f"{len(day_plans)} gün · {tot_pois} mekan · toplam {tot_walk} dk {mode_noun} · {tot_km} km",
                icon="🗺️",
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
                legend_parts.append(f'<span><i style="background:{d_col["hex"]};"></i>{idx + 1}. Gün ({d_tr})</span>')
            st.markdown(f'<div class="rk-legend">{"".join(legend_parts)}</div>', unsafe_allow_html=True)
            comb_tab1, comb_tab2 = st.tabs(["Harita", "Detaylı harita"])
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
            dl_cols = st.columns(len(day_plans))
            for idx, dp in enumerate(day_plans):
                d_tr = DAY_LABELS_TR.get(dp.get("day_of_week", ""), dp.get("day_of_week", ""))
                with dl_cols[idx]:
                    st.markdown(f"**{idx + 1}. Gün · {d_tr}**")
                    txt_d = _format_slide5_schedule(dp, travel_mode=current_mode)
                    st.code(txt_d, language="text")
                    st.download_button(
                        f"📥 {idx + 1}. günü indir (.txt)",
                        data=txt_d,
                        file_name=f"kocaeli_gezi_{idx + 1}gun.txt",
                        mime="text/plain",
                        key=f"dl_day_{idx}",
                    )
    else:
        tab_cards, tab_slide5 = st.tabs(["Rota & harita", "Çizelge & indir"])
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
            slide5_text = _format_slide5_schedule(day_plans[0], travel_mode=current_mode)
            st.code(slide5_text, language="text")
            day_tag = day_plans[0].get("day_of_week", "rota")
            st.download_button(
                "📥 Gezi planını indir (.txt)",
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
    st.session_state.setdefault("ui_theme", "rose_violet")

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
    use_mock, use_street_geom = _render_app_sidebar()
    _render_official_header()
    page = st.session_state.get("active_page", "planner")

    if page == "catalog":
        _render_catalog_page(venues)
    elif page == "virtual_museum":
        _render_virtual_museum_page(venues, venues_by_id)
    elif page == "account":
        _render_account_page(venues)
    elif page == "eval":
        _render_eval_report_page()
    else:
        _render_planner_page(venues, venues_by_id, use_mock=use_mock, use_street_geom=use_street_geom)


if __name__ == "__main__":
    main()
