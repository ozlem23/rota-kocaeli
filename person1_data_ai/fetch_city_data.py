"""
Kişi 1 — Tek Seferlik Şehir Verisi İndirici (Kocaeli / İzmit)
Kullanım:
    python -m person1_data_ai.fetch_city_data --output-dir data --refresh-matrix-only --strict-osrm
    python -m person1_data_ai.fetch_city_data --output-dir data --refresh-driving-only --strict-osrm
Not:
    Ücretsiz Overpass, Wikipedia ve OSRM/routed-foot API limitlerine takılmamak için veriyi
    önceden indirip data/venues.json, walking_matrix.json, walking_paths.json,
    driving_matrix.json ve driving_paths.json dosyalarına kaydeder.
"""
from __future__ import annotations

import argparse
import json
import math
import socket
import time
from pathlib import Path
from typing import Any, Dict, List

import requests
import urllib3.util.connection as urllib3_cn

# İzmit Merkez (Kocaeli) varsayılan sınırlayıcı kutusu: south, west, north, east
IZMIT_BBOX = (40.7520, 29.8950, 40.7780, 29.9480)


def fetch_overpass_pois(bbox=IZMIT_BBOX) -> List[Dict[str, Any]]:
    s, w, n, e = bbox
    query = f"""
    [out:json][timeout:25];
    (
      node["tourism"~"museum|attraction|monument|viewpoint"]({s},{w},{n},{e});
      way["tourism"~"museum|attraction|monument"]({s},{w},{n},{e});
      node["historic"]({s},{w},{n},{e});
      way["historic"]({s},{w},{n},{e});
      node["amenity"~"restaurant|cafe|place_of_worship"]({s},{w},{n},{e});
      way["amenity"="place_of_worship"]({s},{w},{n},{e});
      way["leisure"="park"]({s},{w},{n},{e});
    );
    out center 60;
    """
    resp = requests.post(
        "https://overpass-api.de/api/interpreter",
        data={"data": query},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("elements", [])


def fetch_wikipedia_summary(title_or_query: str) -> tuple[str, str]:
    try:
        search_resp = requests.get(
            "https://tr.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": f"İzmit {title_or_query}",
                "format": "json",
                "srlimit": 1,
            },
            timeout=10,
        )
        hits = search_resp.json().get("query", {}).get("search", [])
        if not hits:
            return "", ""
        page_title = hits[0]["title"]
        sum_resp = requests.get(
            f"https://tr.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(page_title)}",
            timeout=10,
        )
        if sum_resp.status_code != 200:
            return "", ""
        data = sum_resp.json()
        extract = data.get("extract", "")[:260]
        url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
        return extract, url
    except Exception:
        return "", ""


def build_osrm_matrix(
    venues: List[Dict[str, Any]],
    profile: str = "foot",
    strict_osrm: bool = False,
) -> Dict[str, Dict[str, Dict[str, int]]]:
    """
    profile='foot' -> OpenStreetMap routed-foot (yaya kaldırım/park ağı)
    profile='driving' -> OSRM driving / routed-car (araç/tek yön yol ağı)
    """
    coords_str = ";".join(f"{v['lon']},{v['lat']}" for v in venues)
    if profile == "driving":
        urls = [
            f"https://router.project-osrm.org/table/v1/driving/{coords_str}?annotations=duration,distance",
            f"https://routing.openstreetmap.de/routed-car/table/v1/driving/{coords_str}?annotations=duration,distance",
        ]
        fallback_speed_mps = 6.94  # ~25 km/h şehir içi araç ortalaması
    else:
        urls = [
            f"https://routing.openstreetmap.de/routed-foot/table/v1/foot/{coords_str}?annotations=duration,distance",
            f"https://router.project-osrm.org/table/v1/foot/{coords_str}?annotations=duration,distance",
        ]
        fallback_speed_mps = 1.25  # ~4.5 km/h yaya yürüyüşü

    headers = {"User-Agent": "RotaKocaeliPlanner/3.0 (Educational Project)"}
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            durations = data["durations"]
            distances = data["distances"]
            matrix: Dict[str, Dict[str, Dict[str, int]]] = {}
            for i, v1 in enumerate(venues):
                matrix[v1["id"]] = {}
                for j, v2 in enumerate(venues):
                    if i == j:
                        matrix[v1["id"]][v2["id"]] = {"duration_min": 0, "distance_m": 0}
                    else:
                        d_m = float(distances[i][j] or 750)
                        d_sec = float(durations[i][j] or (d_m / fallback_speed_mps))
                        if profile == "foot" and "routed-foot" not in url:
                            d_sec = max(d_sec, d_m / 1.25)
                        matrix[v1["id"]][v2["id"]] = {
                            "duration_min": max(1, int(round(d_sec / 60.0))),
                            "distance_m": int(round(d_m)),
                        }
            print(f"[{profile}] Matris kaynağı: {url.split('/table')[0]}", flush=True)
            return matrix
        except Exception as e:
            print(f"[{profile}] Matris uyarısı ({url[:48]}...): {e}", flush=True)
            continue

    if strict_osrm:
        raise RuntimeError(f"Canlı {profile} yönlendirme sunucusuna erişilemedi (--strict-osrm).")

    print(f"UYARI [{profile}]: Canlı sunucu erişilemedi, Haversine yedek matrisi kullanılıyor.", flush=True)
    matrix = {}
    for v1 in venues:
        matrix[v1["id"]] = {}
        for v2 in venues:
            if v1["id"] == v2["id"]:
                matrix[v1["id"]][v2["id"]] = {"duration_min": 0, "distance_m": 0}
                continue
            r = 6371000
            p1, p2 = math.radians(v1["lat"]), math.radians(v2["lat"])
            dp = math.radians(v2["lat"] - v1["lat"])
            dl = math.radians(v2["lon"] - v1["lon"])
            a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
            dist = int(round(2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a)) * 1.28))
            matrix[v1["id"]][v2["id"]] = {
                "duration_min": max(1, int(round(dist / (fallback_speed_mps * 60.0)))),
                "distance_m": dist,
            }
    return matrix


def build_osrm_paths(
    venues: List[Dict[str, Any]],
    profile: str = "foot",
    strict_osrm: bool = False,
) -> Dict[str, List[List[float]]]:
    """
    Her mekan çifti arasında seçilen ulaşım profiline uygun (kaldırım veya araç yolu)
    gerçek yol geometrilerini indirir.
    Not: Tek yönlü araç yolları gidiş-dönüşte farklı olabileceği için 'driving' profilinde
    her yön ayrı çekilir; yaya ('foot') profilinde simetri korunarak yarı sürede indirilir.
    """
    v_by_id = {v["id"]: v for v in venues}
    v_ids = list(v_by_id.keys())
    paths: Dict[str, List[List[float]]] = {}
    session = requests.Session()
    session.headers.update({"User-Agent": "RotaKocaeliPlanner/3.0 (Educational Project)"})

    if profile == "driving":
        bases = (
            "https://router.project-osrm.org/route/v1/driving",
            "https://routing.openstreetmap.de/routed-car/route/v1/driving",
        )
        total_req = len(v_ids) * (len(v_ids) - 1)
    else:
        bases = (
            "https://routing.openstreetmap.de/routed-foot/route/v1/foot",
            "https://router.project-osrm.org/route/v1/foot",
        )
        total_req = len(v_ids) * (len(v_ids) - 1) // 2

    fetched_count = 0
    for uid in v_ids:
        u = v_by_id[uid]
        u_lon, u_lat = float(u["lon"]), float(u["lat"])
        for vid in v_ids:
            if uid == vid:
                continue
            v = v_by_id[vid]
            v_lon, v_lat = float(v["lon"]), float(v["lat"])
            pair_key = f"{uid}::{vid}"
            rev_key = f"{vid}::{uid}"
            if profile == "foot" and rev_key in paths:
                paths[pair_key] = list(reversed(paths[rev_key]))
                continue

            geom = None
            for base in bases:
                for _attempt in range(2):
                    try:
                        url = f"{base}/{u_lon},{u_lat};{v_lon},{v_lat}?overview=full&geometries=geojson"
                        r = session.get(url, timeout=(4.0, 6.0))
                        if r.status_code == 200:
                            routes = r.json().get("routes", [])
                            if routes and routes[0].get("geometry", {}).get("coordinates"):
                                geom = routes[0]["geometry"]["coordinates"]
                                break
                    except Exception:
                        time.sleep(0.2)
                if geom:
                    break
            if strict_osrm and not geom:
                raise RuntimeError(f"[{profile}] Güzergah çizgisi alınamadı: {pair_key}")
            paths[pair_key] = geom or [[u_lon, u_lat], [v_lon, v_lat]]
            fetched_count += 1
            if fetched_count % 30 == 0 or fetched_count == total_req:
                print(f"[{profile}] Güzergah indirildi: {fetched_count}/{total_req}", flush=True)
            time.sleep(0.03)
    return paths


def build_osrm_walking_matrix(
    venues: List[Dict[str, Any]], strict_osrm: bool = False
) -> Dict[str, Dict[str, Dict[str, int]]]:
    return build_osrm_matrix(venues, profile="foot", strict_osrm=strict_osrm)


def build_osrm_walking_paths(
    venues: List[Dict[str, Any]], strict_osrm: bool = False
) -> Dict[str, List[List[float]]]:
    return build_osrm_paths(venues, profile="foot", strict_osrm=strict_osrm)


def main() -> None:
    urllib3_cn.allowed_gai_family = lambda: socket.AF_INET
    parser = argparse.ArgumentParser(description="Kocaeli/İzmit verisini indir ve JSON'a kaydet.")
    parser.add_argument("--output-dir", default="data", help="Çıktı klasörü (varsayılan: data)")
    parser.add_argument("--refresh-matrix-only", action="store_true", help="Mevcut venues.json için yaya + araç matris/yollarını yenile")
    parser.add_argument("--refresh-driving-only", action="store_true", help="Yalnızca araç (driving) matris ve yollarını yenile")
    parser.add_argument("--strict-osrm", action="store_true", help="OSRM erişilemezse yedek veriye düşmeden hata ver")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    venues_file = out_dir / "venues.json"

    if (args.refresh_matrix_only or args.refresh_driving_only) and venues_file.exists():
        with open(venues_file, encoding="utf-8") as f:
            venues = json.load(f)

        if not args.refresh_driving_only:
            w_matrix = build_osrm_matrix(venues, profile="foot", strict_osrm=args.strict_osrm)
            with open(out_dir / "walking_matrix.json", "w", encoding="utf-8") as f:
                json.dump(w_matrix, f, ensure_ascii=False, indent=2)
            print(f"Yaya matrisi güncellendi ({len(venues)} mekan)")

            w_paths = build_osrm_paths(venues, profile="foot", strict_osrm=args.strict_osrm)
            with open(out_dir / "walking_paths.json", "w", encoding="utf-8") as f:
                json.dump(w_paths, f)
            print(f"Yaya yolları güncellendi ({len(w_paths)} güzergah)")

        d_matrix = build_osrm_matrix(venues, profile="driving", strict_osrm=args.strict_osrm)
        with open(out_dir / "driving_matrix.json", "w", encoding="utf-8") as f:
            json.dump(d_matrix, f, ensure_ascii=False, indent=2)
        print(f"Araç (araba) matrisi güncellendi ({len(venues)} mekan)")

        d_paths = build_osrm_paths(venues, profile="driving", strict_osrm=args.strict_osrm)
        with open(out_dir / "driving_paths.json", "w", encoding="utf-8") as f:
            json.dump(d_paths, f)
        print(f"Araç (araba) yolları güncellendi ({len(d_paths)} güzergah)")
        return

    elements = fetch_overpass_pois()
    print(f"Overpass üzerinden {len(elements)} ham kayıt çekildi.")
    print("İpucu: Çekilen ham mekanları temizleyip data/venues.json içine ekledikten sonra --refresh-matrix-only ile matrisleri üretin.")


if __name__ == "__main__":
    main()
