from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from contracts.models import ParsedRequest

load_dotenv()


class _LLMParseSchema(BaseModel):
    day_of_week: str = Field(
        default="Sat",
        description="Haftanın başlangıç günü: Mon, Tue, Wed, Thu, Fri, Sat veya Sun. Belirtilmemişse Sat.",
    )
    num_days: int = Field(
        default=1,
        description="Gezi gün sayısı: 1 (günübirlik) veya 2 (iki günlük / hafta sonu).",
    )
    plan_days: List[str] = Field(
        default_factory=list,
        description="Planlanan günler listesi, örn: ['Sat', 'Sun'] veya ['Sat'].",
    )
    start_venue_id: str = Field(description="Başlangıç noktası venue_id (yalnızca listeden).")
    end_venue_id: str = Field(description="Bitiş noktası venue_id (yalnızca listeden).")
    start_time: str = Field(default="09:30", description="HH:MM biçiminde başlangıç saati.")
    end_time: str = Field(default="17:00", description="HH:MM biçiminde bitiş saati.")
    interests: List[str] = Field(default_factory=list, description="İlgi alanları.")
    want_lunch: bool = Field(default=True, description="Öğle yemeği molası isteniyor mu?")
    lunch_window_start: str = Field(default="12:00", description="Öğle yemeği aralığı başlangıcı HH:MM.")
    lunch_window_end: str = Field(default="14:00", description="Öğle yemeği aralığı bitişi HH:MM.")
    lunch_duration_min: int = Field(default=60, description="Öğle yemeği süresi (dk).")
    food_preference: Optional[str] = Field(default=None, description="Varsa yemek/mutfak tercihi.")
    selected_venue_ids: List[str] = Field(
        default_factory=list,
        description="İlgi alanına uygun seçilen mekanların venue_id listesi (YALNIZCA verilen listeden).",
    )
    unmatched_notes: List[str] = Field(
        default_factory=list,
        description="Şehir listesinde bulunmayan veya toplu taşıma gibi kapsam dışı istek notları.",
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


def _fallback_parse(
    user_text: str,
    venues: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """API anahtarı yokken veya ağ hatasında çalışan deterministik Türkçe kural tabanlı ayrıştırıcı."""
    norm_text = _norm(user_text)
    pois = [v for v in venues if not v.get("is_restaurant", False)]
    poi_ids = {v["id"] for v in pois}

    # Gün ve Gün Sayısı tespiti (cumartesi içinde 'cuma' geçmesini önlemek için kelime sınırı kullan)
    day_map = [
        ("pazartesi", "Mon"),
        ("sali", "Tue"),
        ("carsamba", "Wed"),
        ("persembe", "Thu"),
        ("cumartesi", "Sat"),
        ("cuma", "Fri"),
        ("pazar", "Sun"),
    ]
    next_day_map = {
        "Mon": "Tue", "Tue": "Wed", "Wed": "Thu", "Thu": "Fri", "Fri": "Sat", "Sat": "Sun", "Sun": "Mon"
    }

    multi_day_cues = [
        r"\b2\s*gun\b", r"\biki\s*gun\b", r"\b2\s*gunluk\b", r"\biki\s*gunluk\b",
        r"\bhaftasonu\b", r"\bhafta\s*sonu\b", r"\bcumartesi\s+(?:ve\s+)?pazar\b"
    ]
    is_multi_day = any(re.search(cue, norm_text) for cue in multi_day_cues)
    num_days = 2 if is_multi_day else 1

    found_days: List[str] = []
    for tr_day, code in day_map:
        if re.search(rf"\b{tr_day}\b", norm_text):
            found_days.append(code)

    day_of_week = found_days[0] if found_days else "Sat"

    if num_days == 2:
        if len(found_days) >= 2:
            plan_days = [found_days[0], found_days[1]]
        elif "hafta sonu" in norm_text or "haftasonu" in norm_text:
            plan_days = ["Sat", "Sun"]
            day_of_week = "Sat"
        else:
            plan_days = [day_of_week, next_day_map.get(day_of_week, "Sun")]
    else:
        plan_days = [day_of_week]

    # Saat tespiti (örn: 09.30, 09:30, 17:00)
    times = re.findall(r"\b(\d{1,2})[:.](\d{2})\b", user_text)
    formatted_times = [f"{int(h):02d}:{int(m):02d}" for h, m in times if 0 <= int(h) <= 23 and 0 <= int(m) <= 59]
    start_time = formatted_times[0] if len(formatted_times) >= 1 else "09:30"
    end_time = formatted_times[1] if len(formatted_times) >= 2 else "17:00"

    # Başlangıç / bitiş noktası eşleştirme
    default_start = "eski_gar" if "eski_gar" in poi_ids else pois[0]["id"]
    mentioned_positions: List[Tuple[int, str]] = []
    for v in pois:
        v_norm = _norm(v["name"])
        idx = norm_text.find(v_norm)
        if idx == -1 and v["id"] == "eski_gar":
            idx = norm_text.find("eski gar")
        if idx == -1 and v["id"] == "kasri_humayun":
            idx = norm_text.find("kasr-i humayun")
        if idx == -1:
            tokens = [t for t in v_norm.split() if len(t) > 3]
            if len(tokens) >= 2 and all(t in norm_text for t in tokens[:2]):
                idx = norm_text.find(tokens[0])
        if idx != -1:
            mentioned_positions.append((idx, v["id"]))

    mentioned_positions.sort(key=lambda item: item[0])
    mentioned_pois = [vid for _, vid in mentioned_positions]

    has_start_cue = any(cue in norm_text for cue in ["basla", "dayim", "deyim", "cikis"])
    has_return_same = any(cue in norm_text for cue in ["oraya don", "ayni yer", "orada bitir", "geri don"])

    if has_start_cue and mentioned_pois:
        start_id = mentioned_pois[0]
        if has_return_same or len(mentioned_pois) < 2:
            end_id = start_id
        else:
            end_id = mentioned_pois[-1]
    else:
        start_id = default_start
        end_id = default_start

    # Öğle yemeği
    want_lunch = True
    if any(
        p in norm_text
        for p in [
            "yemek istemiyorum",
            "yemek olmasin",
            "yemek yok",
            "ogle yemegi olmasin",
            "ogle yemegi istemiyorum",
            "ogle yemegi yok",
            "mola olmasin",
            "yemeksiz",
        ]
    ):
        want_lunch = False

    food_pref = None
    food_keywords = [
        "iskender",
        "doner",
        "lahmacun",
        "kofte",
        "balik",
        "pide",
        "kebap",
        "ev yemek",
        "vejetaryen",
        "vegan",
        "kafe",
        "kahvalti",
        "manti",
        "corba",
        "tatli",
        "burger",
        "pizza",
        "salata",
    ]
    for kw in food_keywords:
        if kw in norm_text:
            food_pref = kw
            break
    if not food_pref and want_lunch:
        m_food = re.search(r"\b([a-z]{3,15})\s+yemek\s+istiyorum\b", norm_text)
        if m_food and m_food.group(1) not in {"ogle", "bir", "iyi", "guzel", "uzun", "kisa"}:
            food_pref = m_food.group(1)

    # İlgi alanı eşleştirme
    interest_keywords = {
        "muze": ["muze", "arkeoloji", "kagit", "gemi", "kultur"],
        "tarihi yapi": ["tarih", "tarihi", "konak", "kosk", "saat kulesi", "osmanli", "mimari", "anit", "kultur"],
        "cami": ["cami", "inanc", "sinan"],
        "park": ["park", "sahil", "doga", "deniz", "korfez"],
    }
    interests: List[str] = []
    for cat, kws in interest_keywords.items():
        if any(k in norm_text for k in kws):
            interests.append(cat)
    if not interests:
        interests = ["muze", "tarihi yapi"]

    explicit_visits = [vid for vid in mentioned_pois if vid not in (start_id, end_id)]
    if "sadece" in norm_text and explicit_visits:
        selected_ids = explicit_visits
    else:
        selected_ids = list(explicit_visits)
        for v in pois:
            if v["id"] in selected_ids or (
                v["id"] in (start_id, end_id) and v.get("category") == "baslangic_bitis"
            ):
                continue
            v_search = _norm(" ".join([v["name"], v["category"], *v.get("tags", [])]))
            if any(_norm(intr) in v_search or any(w in v_search for w in _norm(intr).split()) for intr in interests):
                selected_ids.append(v["id"])

    if not selected_ids:
        selected_ids = [v["id"] for v in pois if v.get("category") != "baslangic_bitis"][:5]

    if num_days == 2 and len(selected_ids) < 8:
        for v in pois:
            if v["id"] not in selected_ids and v.get("category") != "baslangic_bitis":
                selected_ids.append(v["id"])
                if len(selected_ids) >= 9:
                    break

    unmatched: List[str] = []
    if any(k in norm_text for k in ["metro", "otobus", "tramvay", "toplu tasima", "vapur"]):
        unmatched.append("Not: Bu planlayıcı yalnızca yürüyüş rotaları içindir (toplu taşıma kapsam dışıdır).")
    if any(k in norm_text for k in ["uzay", "disneyland", "eyfel", "ayasofya", "topkap"]):
        unmatched.append("Not: İstenen bazı mekanlar Kocaeli mekan listesinde bulunamadığı için yalnızca listedeki mekanlar seçildi.")

    return {
        "city": venues[0].get("city", "Kocaeli") if venues else "Kocaeli",
        "day_of_week": day_of_week,
        "num_days": num_days,
        "plan_days": plan_days,
        "start_venue_id": start_id,
        "end_venue_id": end_id,
        "start_time": start_time,
        "end_time": end_time,
        "interests": interests,
        "want_lunch": want_lunch,
        "lunch_window_start": "12:00",
        "lunch_window_end": "14:00",
        "lunch_duration_min": 60,
        "food_preference": food_pref,
        "selected_venue_ids": selected_ids,
        "unmatched_notes": unmatched,
    }


def parse_user_request(
    user_text: str,
    venues: List[Dict[str, Any]],
    overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], bool]:
    """
    Serbest Türkçe metni doğrulanmış ParsedRequest sözlüğüne çevirir.
    Dönüş: (parsed_request_dict, used_llm_bool)
    """
    valid_poi_ids = {v["id"] for v in venues if not v.get("is_restaurant", False)}
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    used_llm = False
    result_dict: Optional[Dict[str, Any]] = None

    if api_key and user_text.strip():
        try:
            from google import genai

            compact_catalog = [
                {
                    "id": v["id"],
                    "name": v["name"],
                    "category": v["category"],
                    "tags": v.get("tags", []),
                }
                for v in venues
                if not v.get("is_restaurant", False)
            ]
            prompt = (
                "Aşağıdaki Kocaeli/İzmit mekan kataloğundan yararlanarak kullanıcının "
                "yürüyüş gezisi isteğini JSON formatına ayrıştır.\n\n"
                "KESİN KURALLAR:\n"
                "1. start_venue_id, end_venue_id ve selected_venue_ids alanlarında "
                "YALNIZCA verilen katalogdaki 'id' değerlerini kullan. Asla yeni mekan uydurma.\n"
                "2. Kullanıcı 2 günlük veya hafta sonu gezisi istiyorsa num_days: 2 ve plan_days: ['Sat', 'Sun'] (veya belirtilen günler) yap. Tek gün ise num_days: 1 yap.\n"
                "3. Saat veya rota sırası hesaplama; sadece kullanıcının istediği saat aralığını ve uygun mekan ID'lerini seç.\n"
                "4. Kullanıcı listede olmayan bir şehir dışı mekan veya toplu taşıma isterse unmatched_notes içine kısa Türkçe not yaz.\n\n"
                f"MEKAN KATALOĞU:\n{json.dumps(compact_catalog, ensure_ascii=False)}\n\n"
                f"KULLANICI İSTEĞİ:\n{user_text}"
            )
            client = genai.Client(api_key=api_key)
            interaction = client.interactions.create(
                model="gemini-3.8-flash",
                input=prompt,
                system_instruction="Sen Kocaeli şehir rehberi istek ayrıştırıcısısın. Yalnızca şemaya uygun geçerli JSON üretirsin.",
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": _LLMParseSchema.model_json_schema(),
                },
                store=False,
            )
            parsed_llm = _LLMParseSchema.model_validate_json(interaction.output_text or "{}")
            result_dict = parsed_llm.model_dump()
            result_dict["city"] = venues[0].get("city", "Kocaeli") if venues else "Kocaeli"
            used_llm = True
        except Exception:
            result_dict = None
            used_llm = False

    if result_dict is None:
        result_dict = _fallback_parse(user_text, venues)

    # Kod tarafı katı beyaz liste doğrulaması (uydurma ID'leri sıfırlar)
    default_start = "eski_gar" if "eski_gar" in valid_poi_ids else next(iter(valid_poi_ids))
    if result_dict.get("start_venue_id") not in valid_poi_ids:
        result_dict["start_venue_id"] = default_start
    if result_dict.get("end_venue_id") not in valid_poi_ids:
        result_dict["end_venue_id"] = result_dict["start_venue_id"]

    result_dict["selected_venue_ids"] = [
        vid for vid in dict.fromkeys(result_dict.get("selected_venue_ids", []))
        if vid in valid_poi_ids
    ]

    if result_dict.get("day_of_week") not in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}:
        result_dict["day_of_week"] = "Sat"

    # Arayüzden gelen manuel form geçersiz kılmaları (overrides)
    if overrides:
        for field in (
            "day_of_week",
            "start_venue_id",
            "end_venue_id",
            "start_time",
            "end_time",
            "want_lunch",
            "food_preference",
            "num_days",
            "plan_days",
        ):
            val = overrides.get(field)
            if val is not None and val != "":
                if field in ("start_venue_id", "end_venue_id") and val not in valid_poi_ids:
                    continue
                result_dict[field] = val

    validated = ParsedRequest.model_validate(result_dict)
    return validated.model_dump(), used_llm

