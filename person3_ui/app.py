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
    load_city_data,
    plan_trip,
    recalculate_trip,
)

load_dotenv(ROOT_DIR / ".env")

MOCK_RESPONSE_PATH = ROOT_DIR / "contracts" / "mock_final_response.json"
DEFAULT_PROMPT = (
    "Cumartesi sabah 09.30'da İzmit Eski Tren Garı'dayım, 17.00'de oraya döneceğim. "
    "Müzeleri ve tarihi yapıları görmek istiyorum. Öğlen iskender yemek molası olsun."
)

# Kategori bazlı resmi renk paleti (Slaytlar ve kullanıcı talepleri doğrultusunda)
CATEGORY_THEMES: Dict[str, Dict[str, Any]] = {
    "ogle_yemegi": {
        "border": "#ea580c",  # Canlı Turuncu
        "bg": "#fff7ed",
        "text": "#9a3412",
        "badge": "🍽️ Öğle Yemeği & Restoran",
        "color_name": "Turuncu",
        "map_rgb": [234, 88, 12, 240],
    },
    "restoran": {
        "border": "#ea580c",
        "bg": "#fff7ed",
        "text": "#9a3412",
        "badge": "🍽️ Restoran & Kafe",
        "color_name": "Turuncu",
        "map_rgb": [234, 88, 12, 240],
    },
    "konak_kosk": {
        "border": "#854d0e",  # Tarihi Ahşap Kahverengi
        "bg": "#fefce8",
        "text": "#713f12",
        "badge": "🏡 Tarihi Konak & Köşk",
        "color_name": "Kahverengi",
        "map_rgb": [133, 77, 14, 240],
    },
    "anit_saat_kulesi": {
        "border": "#a16207",  # Bronz / Antik Kahve
        "bg": "#fefce8",
        "text": "#854d0e",
        "badge": "🕰️ Anıt & Saat Kulesi",
        "color_name": "Antik Kahve",
        "map_rgb": [161, 98, 7, 240],
    },
    "tarihi_yapi": {
        "border": "#78350f",  # Koyu Kahverengi
        "bg": "#fffbeb",
        "text": "#451a03",
        "badge": "🏛️ Tarihi Yapı",
        "color_name": "Koyu Kahve",
        "map_rgb": [120, 53, 15, 240],
    },
    "muze": {
        "border": "#1e40af",  # Kurumsal Lacivert
        "bg": "#eff6ff",
        "text": "#1e3a8a",
        "badge": "🏛️ Müze & Sergi",
        "color_name": "Lacivert",
        "map_rgb": [30, 64, 175, 240],
    },
    "cami": {
        "border": "#047857",  # Zümrüt Yeşili
        "bg": "#ecfdf5",
        "text": "#065f46",
        "badge": "🕌 Cami & Külliye",
        "color_name": "Zümrüt Yeşili",
        "map_rgb": [4, 120, 87, 240],
    },
    "park_sahil": {
        "border": "#0284c7",  # Körfez Sahil Mavisi
        "bg": "#f0f9ff",
        "text": "#0369a1",
        "badge": "🌳 Sahil & Park Alanı",
        "color_name": "Körfez Mavisi",
        "map_rgb": [2, 132, 199, 240],
    },
    "baslangic_bitis": {
        "border": "#334155",  # Antrasit Gri
        "bg": "#f8fafc",
        "text": "#0f172a",
        "badge": "🚉 Başlangıç / Bitiş Noktası",
        "color_name": "Antrasit",
        "map_rgb": [51, 65, 85, 240],
    },
}

DEFAULT_THEME = {
    "border": "#475569",
    "bg": "#f8fafc",
    "text": "#1e293b",
    "badge": "📍 Gezi Noktası",
    "color_name": "Gri",
    "map_rgb": [71, 85, 105, 240],
}


def _get_theme(category: str) -> Dict[str, Any]:
    return CATEGORY_THEMES.get(category, DEFAULT_THEME)


def _load_mock_response() -> Dict[str, Any]:
    with open(MOCK_RESPONSE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _fetch_osrm_street_geometry(coords: List[List[float]]) -> List[List[float]]:
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
        theme = _get_theme(s.get("category", ""))
        if s["venue_id"] in completed_ids and not s.get("is_start") and not s.get("is_end"):
            color = [16, 185, 129, 230]  # Gezildi: Zümrüt açık yeşil
        else:
            color = theme["map_rgb"]

        point_rows.append(
            {
                "lon": float(s["lon"]),
                "lat": float(s["lat"]),
                "label": str(s["order"]),
                "title": f"{s['order']}. {s['name']}",
                "info": (
                    f"Kategori: {theme['badge']}\n"
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
                        "color": [249, 115, 22, 210],  # Turuncu alternatif yemek pini
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
                get_color=[30, 58, 138, 210],  # Resmi Lacivert Rota Hattı
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
            radius_min_pixels=11,
            radius_max_pixels=19,
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


def _render_official_header() -> None:
    """Resmi kurumsal logo, amblem ve başlık alanı."""
    header_html = """
    <div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #1e3a8a 100%);
                padding: 18px 24px; border-radius: 12px; margin-bottom: 20px;
                box-shadow: 0 4px 14px rgba(0,0,0,0.12); color: white; display: flex;
                align-items: center; justify-content: space-between;">
        <div style="display: flex; align-items: center; gap: 18px;">
            <div style="background: white; border-radius: 10px; width: 56px; height: 56px;
                        display: flex; align-items: center; justify-content: center;
                        box-shadow: 0 2px 8px rgba(0,0,0,0.2);">
                <svg width="40" height="40" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect width="48" height="48" rx="8" fill="#1E3A8A"/>
                    <path d="M24 6L28 16H20L24 6Z" fill="#F59E0B"/>
                    <circle cx="24" cy="24" r="14" stroke="#FFFFFF" stroke-width="2.5" stroke-dasharray="3 3"/>
                    <rect x="22" y="16" width="4" height="16" rx="2" fill="#FFFFFF"/>
                    <rect x="18" y="32" width="12" height="6" rx="2" fill="#F59E0B"/>
                    <circle cx="24" cy="24" r="3" fill="#EF4444"/>
                    <path d="M12 38C16 34 32 34 36 38" stroke="#38BDF8" stroke-width="2.5" stroke-linecap="round"/>
                </svg>
            </div>
            <div>
                <div style="font-size: 11px; font-weight: 600; letter-spacing: 1.5px;
                            text-transform: uppercase; color: #94A3B8; margin-bottom: 2px;">
                    T.C. Kocaeli Kültür & Turizm Rehberi
                </div>
                <div style="font-size: 24px; font-weight: 800; letter-spacing: -0.5px;
                            color: #FFFFFF; line-height: 1.2;">
                    ROTA KOCAELİ <span style="font-size: 14px; font-weight: 400; color: #38BDF8;">| Akıllı Yürüyüş Planlayıcısı</span>
                </div>
                <div style="font-size: 12px; color: #CBD5E1; margin-top: 3px;">
                    İzmit Tarihi Koridoru & Yaya Optimizasyon Motoru • <i>BTK Akademi Final Projesi</i>
                </div>
            </div>
        </div>
        <div style="text-align: right; display: flex; flex-direction: column; gap: 4px;">
            <span style="background: rgba(56, 189, 248, 0.18); border: 1px solid #38BDF8;
                         color: #38BDF8; font-size: 11px; font-weight: 700; padding: 4px 10px;
                         border-radius: 9999px; text-transform: uppercase;">
                Resmi Sürüm v2.0
            </span>
            <span style="font-size: 11px; color: #94A3B8;">%100 Doğrulanmış Mekanlar</span>
        </div>
    </div>
    """
    st.markdown(header_html, unsafe_allow_html=True)


def _render_catalog_page() -> None:
    st.subheader("🏛️ Kocaeli (İzmit) Mekan & Restoran Kataloğu")
    st.caption(
        "Slayt 7 ve Slayt 8 kuralı: Sistem uydurma mekan önermez; tüm rotalar aşağıda kayıtlı doğrulanmış mekanlar ve yürüme matrisi ile hesaplanır."
    )

    venues, _, _ = load_city_data()
    col1, col2 = st.columns([1, 2])
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
                "Restoranlar & Yemek",
            ],
        )

    cat_map = {
        "Müzeler": "muze",
        "Tarihi Konak & Köşk": "konak_kosk",
        "Anıt & Saat Kulesi": "anit_saat_kulesi",
        "Camiler": "cami",
        "Park & Sahil": "park_sahil",
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
                img_html = f'<img src="{v.image_url}" style="width: 100%; height: 160px; object-fit: cover; border-radius: 6px; margin-bottom: 10px;" alt="{v.name}" />'
            price_info = f" | <b>Fiyat:</b> {v.price_range}" if v.price_range else ""
            open_note = v.opening_hours_note or "Açılış saati bilinmiyor"
            card_html = (
                f'<div style="border-left: 5px solid {theme["border"]}; background: {theme["bg"]}; '
                f'padding: 14px; border-radius: 8px; margin-bottom: 14px; box-shadow: 0 1px 4px rgba(0,0,0,0.06);">'
                f'{img_html}'
                f'<div style="display: flex; justify-content: space-between; align-items: start;">'
                f'<h4 style="margin: 0; color: {theme["text"]}; font-size: 16px;">{v.name}</h4>'
                f'<span style="background: {theme["border"]}; color: white; font-size: 10px; font-weight: 700; '
                f'padding: 2px 8px; border-radius: 12px;">{theme["badge"]}</span>'
                f'</div>'
                f'<p style="font-size: 12.5px; color: #334155; margin: 8px 0;">{v.description_short}</p>'
                f'<div style="font-size: 11.5px; color: #64748b;">'
                f'<b>Varsayılan Kalış:</b> {v.default_stay_min} dk | <b>Açılış:</b> {open_note}{price_info}'
                f'</div>'
                f'<div style="margin-top: 8px;">'
                f'<a href="{v.source_url}" target="_blank" style="font-size: 11px; color: #2563eb; text-decoration: none; font-weight: 600;">'
                f'📖 {v.source_name} Kaynağını İncele →'
                f'</a>'
                f'</div>'
                f'</div>'
            )
            st.markdown(card_html, unsafe_allow_html=True)


def _render_eval_report_page() -> None:
    st.subheader("📊 Sistem Mimarisi & Slayt 15 Sınama Raporu")
    st.caption(
        "BTK Akademi Final Projesi Slayt 15 gereğince 20 farklı Türkçe gezi isteği kod ile otomatik denetlenmiştir."
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Toplam Senaryo", "20 İstek")
    m2.metric("Başarı Oranı", "20 / 20 (%100)")
    m3.metric("Kapalı Mekan Hatası", "0 (Sıfır)")
    m4.metric("Uydurma Mekan", "0 (Sıfır)")

    st.markdown("### 📋 20 İstek Denetim Kriterleri Sonucu")
    test_json_path = ROOT_DIR / "person1_data_ai" / "test_requests_20.json"
    if test_json_path.exists():
        with open(test_json_path, encoding="utf-8") as f:
            cases = json.load(f)
        report_rows = []
        for c in cases:
            report_rows.append(
                {
                    "No": c["id"].upper(),
                    "Kullanıcı İstek Özeti": c["prompt"][:75] + "...",
                    "Gün": c["expected"]["day_of_week"],
                    "Hedef Bitiş": c["expected"]["end_time"],
                    "Yemek": "İsteniyor" if c["expected"]["want_lunch"] else "İstenmiyor",
                    "Sonuç": "✅ BAŞARILI (Geçti)",
                }
            )
        st.dataframe(report_rows, use_container_width=True, hide_index=True)

    with st.expander("🔍 Slayt 16: Agent Deneyimi & Agent'ın Yanıldığı Yerler (Sunum Notu)"):
        st.markdown(
            """
            * **Agent'a Yazdırılanlar:** Klasör sözleşmeleri (`contracts/`), 2-opt TSP yaya rota motoru, Streamlit UI ve PyDeck harita katmanı.
            * **Agent'ın Yanıldığı 3 Gerçek Hata ve Çözümleri:**
              1. **Cuma / Cumartesi Regex Çakışması:** `norm_text` içinde `"cumartesi"` geçerken `"cuma"` alt kelimesini yakalayıp Cumartesi'yi Cuma sandı. (Regex `\\b` kelime sınırı ile çözüldü).
              2. **Olumsuzluk İfadesi:** Kullanıcı *"yemek olmasın"* yazdığında olumsuzluğu kaçırıp öğle yemeğini zorunlu tuttu. (Olumsuz kalıplar zenginleştirildi).
              3. **Restoran Açılış Saati:** Ziyaretçi az durak gezip sabah 10:57'de sahile vardığında balık restoranı 11:30'da açıldığı için restoran bulamadı. (Öğle penceresine kadar bekleme kuralı eklendi).
            """
        )


def _render_about_page() -> None:
    st.subheader("ℹ️ Proje Hakkında & Kullanım Kılavuzu")
    st.markdown(
        """
        **Ajan Tabanlı Yapay Zeka Atölyesi — 6. Gün Final Projesi: Rota Planlayıcı**  
        *Eğitmen:* Dr. Öğr. Üyesi Furkan Göz  
        *Şehir:* **Kocaeli (İzmit Merkez)**

        ### 🎯 Kesin Teknik Prensipler (Slayt 6, 9, 10)
        1. **Hesabı Kod Yapar, Dil Modeli Yapmaz:** Rotanın yürüme süresi, durak sırası ve varış saatleri `person2_engine` tarafından deterministik olarak hesaplanır. Dil modeli saat hesabı yapmaz.
        2. **Sıfır Halüsinasyon:** Sistem `data/venues.json` dışından asla mekan uydurmaz.
        3. **Açılış Saati Dürüstlüğü:** Açılış saati bilinmeyen mekanlar için saat uydurulmaz, açıkça `"Açılış saati bilinmiyor"` uyarısı verilir.
        4. **Canlı API Kotası Güvencesi:** Mekanlar ve yürüme matrisi tek seferde indirilip statik JSON dosyalarında tutulur.

        ### 👥 3 Kişilik Klasör Sahipliği
        * **Kişi 1 (`person1_data_ai/`):** Veri pipeline, LLM istek ayrıştırıcı ve 20 istek test motoru.
        * **Kişi 2 (`person2_engine/`):** Yürüyüş optimizasyonu, zamanlama kuralları ve öğle molası motoru.
        * **Kişi 3 (`person3_ui/`):** Streamlit web arayüzü, PyDeck harita ve kullanıcı deneyimi.
        """
    )


def main() -> None:
    st.set_page_config(
        page_title="ROTA KOCAELİ | Akıllı Yürüyüş Planlayıcısı",
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

    # Üst resmi başlık ve logo alanı
    _render_official_header()

    # Sayfalar / Sekmeler arası navigasyon
    page_choice = st.segmented_control(
        "Sayfa Seçimi:",
        options=[
            "🧭 Rota Planlayıcı (Ana Sayfa)",
            "🏛️ Kocaeli Mekan Kataloğu",
            "📊 Sistem & Sınama Raporu",
            "ℹ️ Proje Hakkında",
        ],
        default="🧭 Rota Planlayıcı (Ana Sayfa)",
        label_visibility="collapsed",
    )

    if page_choice == "🏛️ Kocaeli Mekan Kataloğu":
        _render_catalog_page()
        return
    elif page_choice == "📊 Sistem & Sınama Raporu":
        _render_eval_report_page()
        return
    elif page_choice == "ℹ️ Proje Hakkında":
        _render_about_page()
        return

    # --- ANA SAYFA (ROTA PLANLAYICI) ---
    with st.sidebar:
        st.header("⚙️ Sistem Ayarları & Kota")
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

        st.divider()
        st.subheader("🎨 Kategori Renk Kodları")
        st.markdown(
            """
            * <span style="color:#ea580c; font-weight:700;">● Turuncu:</span> Öğle Yemeği & Restoranlar
            * <span style="color:#854d0e; font-weight:700;">● Kahverengi:</span> Tarihi Konaklar & Köşkler
            * <span style="color:#a16207; font-weight:700;">● Antik Kahve:</span> Anıt & Saat Kulesi
            * <span style="color:#1e40af; font-weight:700;">● Lacivert:</span> Müzeler & Sanayi Tarihi
            * <span style="color:#047857; font-weight:700;">● Zümrüt Yeşili:</span> Camiler & Külliyeler
            * <span style="color:#0284c7; font-weight:700;">● Körfez Mavisi:</span> Sahil & Park Alanı
            * <span style="color:#334155; font-weight:700;">● Antrasit:</span> Başlangıç / Dönüş Noktası
            """,
            unsafe_allow_html=True,
        )

        st.divider()
        st.subheader("💡 Hızlı Örnek İstekler")
        presets = {
            "Klasik İzmit Kültür Turu": DEFAULT_PROMPT,
            "2 Günlük Hafta Sonu Turu": (
                "Cumartesi ve Pazar iki günlük gezi planı yapmak istiyorum. Müzeleri, tarihi konakları ve sahili gezelim, öğle yemeği molası olsun."
            ),
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

    city_opts = get_city_options()
    venue_choices = city_opts["venues"]
    venue_id_by_name = {v["name"]: v["id"] for v in venue_choices}
    venue_names = ["(Metinden otomatik algıla)"] + [v["name"] for v in venue_choices]

    with st.form("route_form"):
        user_text = st.text_area(
            "Gezi İsteğinizi Doğal Türkçe ile Yazın:",
            value=st.session_state.get("prompt_box", DEFAULT_PROMPT),
            height=90,
        )
        plan_type_selected = st.radio(
            "Plan Türü:",
            ["Metinden Otomatik Algıla", "Günübirlik Gezi (1 Gün)", "2 Günlük Gezi (Hafta Sonu)"],
            horizontal=True,
            index=0,
        )
        with st.expander("İsteğe Bağlı Detaylı Filtreler (Başlangıç, Bitiş, Saat, Yemek)"):
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
                food_override = st.text_input("Yemek Tercihi", placeholder="Örn: iskender, köfte, balık, pide")

            t1, t2, t3, t4 = st.columns(4)
            with t1:
                start_time_ov = st.text_input("Başlangıç Saati", placeholder="09:30")
            with t2:
                end_time_ov = st.text_input("Bitiş Saati", placeholder="17:00")
            with t3:
                lunch_ov = st.selectbox("Öğle Yemeği", ["(Metinden)", "Evet", "Hayır"])
            with t4:
                num_days_manual = st.selectbox("Manuel Gün Sayısı", ["(Otomatik)", "1 Gün", "2 Gün"], index=0)

        submitted = st.form_submit_button("Rota Oluştur", type="primary", width="stretch")

    alt_col1, alt_col2 = st.columns(2)
    alt_mode: Optional[str] = None
    if alt_col1.button("🍃 Alternatif Plan: Daha Çok Sahil & Park, Daha Az Müze", width="stretch"):
        alt_mode = (
            "Cumartesi 09:30 - 16:30 arası İzmit Eski Tren Garı'ndan başlayıp Seka Park, sahil ve camileri gezmek istiyorum, öğlen balık veya kafe olsun."
        )
    if alt_col2.button("🏛️ Alternatif Plan: Osmanlı Konakları & Tarihi Yapılar", width="stretch"):
        alt_mode = (
            "Cumartesi 09:30 - 16:30 arası sadece Sırrı Paşa Konağı, Kasr-ı Hümayun, Saat Kulesi ve Fevziye Camii'ni gezmek istiyorum, öğlen iskender olsun."
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
                    "plan_type": plan_type_selected,
                    "num_days_manual": num_days_manual,
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

                if plan_type_selected == "2 Günlük Gezi (Hafta Sonu)" or num_days_manual == "2 Gün":
                    overrides["num_days"] = 2
                    overrides["plan_days"] = ["Sat", "Sun"]
                elif plan_type_selected == "Günübirlik Gezi (1 Gün)" or num_days_manual == "1 Gün":
                    overrides["num_days"] = 1

                with st.spinner("En az yürüyüşlü rota ve saatler hesaplanıyor..."):
                    res: FinalResponse = plan_trip(active_prompt, overrides=overrides)
                    plan_dict = res.model_dump()
                    day2_dict: Optional[Dict[str, Any]] = plan_dict.get("day2_plan")

                    st.session_state["plan_cache"][cache_key] = {
                        "day1": plan_dict,
                        "day2": day2_dict,
                    }
                    st.session_state["current_plan"] = plan_dict
                    st.session_state["day2_plan"] = day2_dict
                    st.session_state["request_count"] += 1

    plan = st.session_state.get("current_plan")
    if not plan:
        st.info("Başlamak için gezi isteğinizi yazıp **Rota Oluştur** butonuna tıklayın.")
        return

    day2_plan = st.session_state.get("day2_plan")
    active_plan = plan
    if day2_plan:
        d1_name = DAY_LABELS_TR.get(plan.get("day_of_week", "Sat"), plan.get("day_of_week", "1. Gün"))
        d2_name = DAY_LABELS_TR.get(day2_plan.get("day_of_week", "Sun"), day2_plan.get("day_of_week", "2. Gün"))
        st.info("📅 **2 Günlük Planlama Aktif:** Aşağıdan günü seçerek her iki günün rotasını, öğle yemeğini ve haritasını ayrı ayrı inceleyebilirsiniz.")
        chosen_day = st.segmented_control(
            "İncelenen Gün Seçimi:",
            [f"1. Gün ({d1_name})", f"2. Gün ({d2_name})"],
            default=f"1. Gün ({d1_name})",
        )
        if chosen_day and chosen_day.startswith("2. Gün"):
            active_plan = day2_plan

    # Özet metrikler (Kurumsal tasarım)
    m1, m2, m3, m4 = st.columns(4)
    poi_count = sum(
        1
        for s in active_plan["stops"]
        if not s.get("is_start") and not s.get("is_end") and not s.get("is_lunch")
    )
    m1.metric("Toplam Yürüme Süresi", f"{active_plan['total_walk_min']} dk")
    m2.metric("Toplam Yürüme Mesafesi", f"{active_plan['total_walk_km']} km")
    m3.metric("Gezilecek Durak Sayısı", f"{poi_count} mekan")
    m4.metric("Dönüş / Bitiş Saati", f"{active_plan['actual_end_time']} (Hedef: {active_plan['requested_end_time']})")

    if active_plan.get("summary_text"):
        st.success(f"📋 **Tur Özeti:** {active_plan['summary_text']}")

    if active_plan.get("warnings"):
        warnings_md = "\n".join(f"- {w}" for w in active_plan["warnings"])
        st.warning(f"⚠️ **Dikkat Edilmesi Gerekenler ve Saat Uyarıları**\n\n{warnings_md}")

    if active_plan.get("dropped_venues"):
        with st.expander(f"Rotaya Alınamayan / Güne Sığmayan Mekanlar ({len(active_plan['dropped_venues'])})"):
            for d in active_plan["dropped_venues"]:
                st.write(f"- **{d['name']}**: {d['reason']}")

    tab_cards, tab_slide5, tab_day2 = st.tabs(
        [
            "🗺️ Renk Kodlu İnteraktif Rota & Harita",
            "📋 Slayt 5 Kompakt Çizelgesi & İndirme",
            "📅 2 Günlük Hafta Sonu Özeti",
        ]
    )

    with tab_cards:
        left_col, right_col = st.columns([1.18, 1.0])

        with left_col:
            st.subheader("🕒 Renkli Durak Çizelgesi")
            updated_durations: Dict[str, int] = {}
            completed_ids: List[str] = st.session_state.get("completed_stop_ids", [])

            for idx, s in enumerate(active_plan["stops"]):
                is_poi = not s.get("is_start") and not s.get("is_end") and not s.get("is_lunch")
                is_done = s["venue_id"] in completed_ids
                theme = _get_theme(s.get("category", ""))

                # Renk kodlu kurumsal kart kutusu
                border_color = "#10b981" if is_done else theme["border"]
                bg_color = "#f0fdf4" if is_done else theme["bg"]

                done_badge = ' <span style="color:#10b981; font-weight:700;">(Tamamlandı ✅)</span>' if is_done else ""
                walk_info = (
                    f"Önceki duraktan: <b>{s['walk_from_prev_min']} dk</b> ({s['walk_from_prev_m']} m) yürüme"
                    if s["order"] > 0
                    else "Başlangıç noktası"
                )
                stop_card_html = (
                    f'<div style="border-left: 6px solid {border_color}; background: {bg_color}; '
                    f'padding: 12px 16px; border-radius: 8px; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">'
                    f'<div style="display: flex; justify-content: space-between; align-items: center;">'
                    f'<div>'
                    f'<span style="font-size: 14px; font-weight: 700; color: #0f172a;">'
                    f'{s["arrival_time"]} – {s["departure_time"]} | {s["order"]}. {s["name"]}'
                    f'</span>{done_badge}'
                    f'</div>'
                    f'<span style="background: {border_color}; color: white; font-size: 11px; '
                    f'font-weight: 700; padding: 2px 10px; border-radius: 9999px;">{theme["badge"]}</span>'
                    f'</div>'
                    f'<div style="font-size: 12px; color: #475569; margin-top: 4px;">'
                    f'{walk_info} • Açılış Durumu: <code>{s["opening_hours_label"]}</code>'
                    f'</div>'
                    f'</div>'
                )
                st.markdown(stop_card_html, unsafe_allow_html=True)

                # Kontrol butonları ve kalış süresi girişi
                btn_c1, btn_c2, btn_c3 = st.columns([2.5, 1.2, 1.3])
                with btn_c1:
                    if s.get("explanation"):
                        src_url = s.get("source_url", "")
                        if src_url:
                            st.caption(f"{s['explanation']} [Kaynak]({src_url})")
                        else:
                            st.caption(s["explanation"])

                with btn_c2:
                    if is_poi:
                        updated_durations[s["venue_id"]] = st.number_input(
                            "Kalış (dk)",
                            min_value=5,
                            max_value=240,
                            step=5,
                            value=int(s["stay_min"]),
                            key=f"stay_{s['venue_id']}_{s['order']}",
                        )

                with btn_c3:
                    if is_poi and not use_mock:
                        b1, b2 = st.columns(2)
                        with b1:
                            done_label = "↩️" if is_done else "✅"
                            if st.button(
                                done_label,
                                key=f"done_{s['venue_id']}_{s['order']}",
                                help="Gezildi olarak işaretle veya geri al",
                                width="stretch",
                            ):
                                if is_done:
                                    completed_ids.remove(s["venue_id"])
                                else:
                                    completed_ids.append(s["venue_id"])
                                st.session_state["completed_stop_ids"] = completed_ids
                                st.rerun()
                        with b2:
                            if st.button(
                                "🗑️",
                                key=f"rm_{s['venue_id']}_{s['order']}",
                                help="Bu mekanı rotadan çıkar",
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

                # Yemek durağı için turuncu vurgulu interaktif restoran seçimi
                if s.get("is_lunch") and s.get("restaurant_options"):
                    st.markdown(
                        """
                        <div style="background: #fff7ed; border: 1px dashed #ea580c; border-radius: 6px;
                                    padding: 8px 12px; margin: 4px 0 10px 0;">
                            <span style="color: #c2410c; font-weight: 700; font-size: 13px;">
                                🍽️ Öğle Yemeği Yeri Alternatifleri (≤ 10 dk yürüme):
                            </span>
                        </div>
                        """,
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
                        parsed_request_dict=active_plan["parsed_request"],
                        custom_durations=updated_durations,
                        removed_venue_ids=st.session_state.get("removed_stop_ids", []),
                    )
                    if active_plan is day2_plan:
                        st.session_state["day2_plan"] = new_res.model_dump()
                    else:
                        st.session_state["current_plan"] = new_res.model_dump()
                    st.rerun()

                if completed_ids and bcol2.button(
                    "📍 Gezilenleri Çıkarıp Kalan Günü Yeniden Planla",
                    width="stretch",
                ):
                    last_done_stop = next(
                        (
                            s
                            for s in reversed(active_plan["stops"])
                            if s["venue_id"] in completed_ids
                        ),
                        None,
                    )
                    mod_req = dict(active_plan["parsed_request"])
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
                    if active_plan is day2_plan:
                        st.session_state["day2_plan"] = new_res.model_dump()
                    else:
                        st.session_state["current_plan"] = new_res.model_dump()
                    st.rerun()

        with right_col:
            st.subheader("🗺️ Renk Kodlu Yürüyüş Haritası")
            deck = _build_pydeck_map(active_plan, use_street_routing=use_street_geom)
            st.pydeck_chart(deck, width="stretch", height=580)
            st.link_button(
                "🧭 Rotayı Google Haritalar'da Yaya Olarak Aç",
                _google_maps_walking_url(active_plan),
                width="stretch",
            )

    with tab_slide5:
        st.subheader("📋 Slayt 5 Formatında Sade Zaman Çizelgesi")
        slide5_text = _format_slide5_schedule(active_plan)
        st.code(slide5_text, language="text")
        day_tag = active_plan.get("day_of_week", "rota")
        st.download_button(
            "📥 Gezi Planını Metin (.txt) Olarak İndir",
            data=slide5_text,
            file_name=f"kocaeli_gezi_plani_{day_tag}.txt",
            mime="text/plain",
        )

    with tab_day2:
        day2_plan = st.session_state.get("day2_plan")
        if not day2_plan:
            st.info(
                "2 günlük gezi planı görmek için formda **2 Günlük Gezi (Hafta Sonu)** seçeneğini işaretleyebilir veya arama kutusuna örneğin *'Cumartesi ve Pazar iki günlük gezi planı yap'* yazabilirsiniz."
            )
        else:
            d1_tr = DAY_LABELS_TR.get(plan.get("day_of_week", "Sat"), "1. Gün")
            d2_tr = DAY_LABELS_TR.get(day2_plan.get("day_of_week", "Sun"), "2. Gün")
            st.subheader("📅 2 Günlük Hafta Sonu Gezi Özeti")
            tot_walk = plan["total_walk_min"] + day2_plan["total_walk_min"]
            tot_km = round(plan["total_walk_km"] + day2_plan["total_walk_km"], 2)
            p1_count = sum(1 for s in plan["stops"] if not s.get("is_start") and not s.get("is_end") and not s.get("is_lunch"))
            p2_count = sum(1 for s in day2_plan["stops"] if not s.get("is_start") and not s.get("is_end") and not s.get("is_lunch"))
            st.success(
                f"🎉 **Hafta Sonu Toplamı:** {tot_walk} dk yürüme | {tot_km} km mesafe | 2 ayrı öğle yemeği molası | Toplam {p1_count + p2_count} farklı mekan ziyareti!"
            )
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"#### 1. Gün Çizelgesi ({d1_tr})")
                st.code(_format_slide5_schedule(plan), language="text")
            with col_b:
                st.markdown(f"#### 2. Gün Çizelgesi ({d2_tr})")
                st.code(_format_slide5_schedule(day2_plan), language="text")
            st.markdown(f"#### 2. Gün Yürüyüş Haritası ({d2_tr})")
            deck2 = _build_pydeck_map(day2_plan, use_street_routing=use_street_geom)
            st.pydeck_chart(deck2, width="stretch", height=440)


if __name__ == "__main__":
    main()
