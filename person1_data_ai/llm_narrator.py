from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class _LLMExplanationItem(BaseModel):
    venue_id: str
    explanation: str = Field(description="Mekanın neden seçildiğini anlatan 1-2 cümlelik kaynaklı açıklama.")


class _LLMNarrationSchema(BaseModel):
    summary_text: str = Field(
        description="Hesaplanan toplam yürüme süresi, mesafe ve bitiş saatini birebir içeren kısa özet."
    )
    items: List[_LLMExplanationItem] = Field(default_factory=list)


def _deterministic_narration(
    calculated_plan: Dict[str, Any],
    venues_by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Hesaplanan planın sayılarını birebir koruyan şablon anlatıcı."""
    stops = calculated_plan.get("stops", [])
    total_min = calculated_plan.get("total_walk_min", 0)
    total_km = calculated_plan.get("total_walk_km", 0.0)
    actual_end = calculated_plan.get("actual_end_time", "")
    city = calculated_plan.get("city", "Kocaeli")

    poi_count = sum(1 for s in stops if not s.get("is_start") and not s.get("is_end") and not s.get("is_lunch"))
    summary_text = (
        f"{city} yürüyüş planınız hazırlandı: toplam {poi_count} gezi durağı, "
        f"{total_min} dk ({total_km} km) yürüme ve {actual_end} bitiş saati."
    )

    stop_explanations: Dict[str, str] = {}
    for s in stops:
        vid = s["venue_id"]
        v = venues_by_id.get(vid, {})
        if s.get("is_lunch"):
            opts = s.get("restaurant_options", [])
            names = ", ".join(o["name"] for o in opts[:3])
            stop_explanations[vid] = (
                f"Öğle saatine denk gelen duraktan en fazla 10 dk yürüme mesafesindeki seçenekler: {names}."
            )
        elif v:
            desc = v.get("description_short", "")
            src = v.get("source_name", "Wikipedia")
            stop_explanations[vid] = f"{desc} (Kaynak: {src})" if desc else f"İlgi alanınıza göre seçildi (Kaynak: {src})."

    return {
        "summary_text": summary_text,
        "stop_explanations": stop_explanations,
    }


def narrate_plan(
    calculated_plan: Dict[str, Any],
    venues: List[Dict[str, Any]],
    allow_llm: bool = True,
) -> Tuple[Dict[str, Any], bool]:
    """
    Hesaplanmış planı Wikipedia/Wikivoyage açıklamalarıyla anlatır.
    KESİN KURAL: Hiçbir yürüme süresi, mesafe veya varış saati değiştirilmez.
    """
    venues_by_id = {v["id"]: v for v in venues}
    fallback = _deterministic_narration(calculated_plan, venues_by_id)
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not allow_llm or not api_key:
        return fallback, False

    try:
        from google import genai

        plan_brief = {
            "city": calculated_plan.get("city"),
            "total_walk_min": calculated_plan.get("total_walk_min"),
            "total_walk_km": calculated_plan.get("total_walk_km"),
            "actual_end_time": calculated_plan.get("actual_end_time"),
            "stops": [
                {
                    "venue_id": s["venue_id"],
                    "name": s["name"],
                    "arrival_time": s["arrival_time"],
                    "stay_min": s["stay_min"],
                    "walk_from_prev_min": s["walk_from_prev_min"],
                    "is_lunch": s.get("is_lunch", False),
                    "source_desc": venues_by_id.get(s["venue_id"], {}).get("description_short", ""),
                    "source_name": venues_by_id.get(s["venue_id"], {}).get("source_name", ""),
                }
                for s in calculated_plan.get("stops", [])
            ],
        }

        prompt = (
            "Aşağıdaki HESAPLANMIŞ yürüyüş planını kullanıcıya akıcı Türkçe ile özetle ve her durak için "
            "verilen kaynak açıklamasına dayanarak neden seçildiğini 1-2 cümleyle anlat.\n\n"
            "KESİN KURALLAR:\n"
            f"1. summary_text içinde şu sayıları BİREBİR geçir: {plan_brief['total_walk_min']} dk, "
            f"{plan_brief['total_walk_km']} km, bitiş {plan_brief['actual_end_time']}.\n"
            "2. Asla yeni mekan uydurma, saatleri ve süreleri değiştirme.\n"
            "3. Kaynak bilgisini (Wikipedia / OpenStreetMap) parantez içinde belirt.\n\n"
            f"PLAN:\n{json.dumps(plan_brief, ensure_ascii=False)}"
        )

        client = genai.Client(api_key=api_key)
        interaction = client.interactions.create(
            model="gemini-3.8-flash",
            input=prompt,
            system_instruction="Sen Kocaeli gezi planı anlatıcısısın. Hesaplanmış sayısal verilere sadık kalırsın.",
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": _LLMNarrationSchema.model_json_schema(),
            },
            store=False,
        )
        narr = _LLMNarrationSchema.model_validate_json(interaction.output_text or "{}")

        # Sayısal tutarlılık koruması (Slayt 15: Anlatılan sayılar hesaplananla aynı mı?)
        expected_min_str = str(plan_brief["total_walk_min"])
        expected_end_str = str(plan_brief["actual_end_time"])
        summary_text = narr.summary_text
        if expected_min_str not in summary_text or expected_end_str not in summary_text:
            summary_text = fallback["summary_text"]

        explanations = dict(fallback["stop_explanations"])
        for item in narr.items:
            if item.venue_id in explanations and item.explanation.strip():
                explanations[item.venue_id] = item.explanation.strip()

        return {
            "summary_text": summary_text,
            "stop_explanations": explanations,
        }, True
    except Exception:
        return fallback, False

