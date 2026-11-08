from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


CATEGORY_DEFAULT_STAY_MIN: dict[str, int] = {
    "muze": 75,
    "konak_kosk": 30,
    "cami": 20,
    "anit_saat_kulesi": 15,
    "park_sahil": 40,
    "tarihi_yapi": 30,
    "ogle_yemegi": 60,
    "restoran": 60,
    "kafe": 30,
    "baslangic_bitis": 0,
}

DAY_LABELS_TR: dict[str, str] = {
    "Mon": "Pazartesi",
    "Tue": "Salı",
    "Wed": "Çarşamba",
    "Thu": "Perşembe",
    "Fri": "Cuma",
    "Sat": "Cumartesi",
    "Sun": "Pazar",
}


class OpeningHours(BaseModel):
    open_time: str = Field(..., description="HH:MM format, e.g. '09:00'")
    close_time: str = Field(..., description="HH:MM format, e.g. '17:00'")
    closed_days: List[str] = Field(
        default_factory=list,
        description="Weekday codes when venue is closed: Mon, Tue, Wed, Thu, Fri, Sat, Sun",
    )


class Venue(BaseModel):
    id: str
    name: str
    city: str = "Kocaeli"
    district: str = "İzmit"
    category: str
    tags: List[str] = Field(default_factory=list)
    lat: float
    lon: float
    default_stay_min: int
    opening_hours: Optional[OpeningHours] = None
    opening_hours_note: Optional[str] = None
    description_short: str = ""
    source_name: str = "OpenStreetMap"
    source_url: str = ""
    price_range: Optional[str] = None
    is_restaurant: bool = False
    image_url: Optional[str] = None


class ParsedRequest(BaseModel):
    city: str = "Kocaeli"
    day_of_week: Literal["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] = "Sat"
    num_days: int = 1
    plan_days: List[str] = Field(default_factory=list)
    start_venue_id: str
    end_venue_id: str
    start_time: str = "09:30"
    end_time: str = "17:00"
    interests: List[str] = Field(default_factory=list)
    want_lunch: bool = True
    lunch_window_start: str = "12:00"
    lunch_window_end: str = "14:00"
    lunch_duration_min: int = 60
    food_preference: Optional[str] = None
    selected_venue_ids: List[str] = Field(default_factory=list)
    unmatched_notes: List[str] = Field(default_factory=list)


class RestaurantOption(BaseModel):
    venue_id: str
    name: str
    cuisine_tags: List[str] = Field(default_factory=list)
    walk_from_stop_min: int
    walk_from_stop_m: int
    opening_hours_status: Literal["open", "unknown", "closed"] = "unknown"
    opening_hours_label: str = "Açılış saati bilinmiyor"
    price_range: Optional[str] = None
    description_short: str = ""
    source_url: str = ""
    lat: float
    lon: float


class StopSchedule(BaseModel):
    order: int
    venue_id: str
    name: str
    category: str
    lat: float
    lon: float
    arrival_time: str
    departure_time: str
    stay_min: int
    walk_from_prev_min: int
    walk_from_prev_m: int
    opening_hours_status: Literal["open", "unknown", "start_end"]
    opening_hours_label: str
    is_start: bool = False
    is_end: bool = False
    is_lunch: bool = False
    restaurant_options: List[RestaurantOption] = Field(default_factory=list)
    explanation: str = ""
    source_name: str = ""
    source_url: str = ""


class DroppedVenue(BaseModel):
    venue_id: str
    name: str
    reason: str


class CalculatedPlan(BaseModel):
    city: str
    day_of_week: str
    requested_start_time: str
    requested_end_time: str
    actual_end_time: str
    stops: List[StopSchedule]
    total_walk_min: int
    total_walk_m: int
    total_walk_km: float
    warnings: List[str] = Field(default_factory=list)
    dropped_venues: List[DroppedVenue] = Field(default_factory=list)
    route_coords: List[List[float]] = Field(default_factory=list)
    parsed_request: ParsedRequest
    day2_plan: Optional[CalculatedPlan] = None


class FinalResponse(CalculatedPlan):
    summary_text: str = ""
    used_llm: bool = False

