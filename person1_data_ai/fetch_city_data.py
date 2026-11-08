"""
Kişi 1 — Tek Seferlik Şehir Verisi İndirici (Kocaeli / İzmit)
Kullanım:
    python -m person1_data_ai.fetch_city_data --output-dir data
Not:
    Ücretsiz Overpass, Wikipedia ve OSRM API limitlerine takılmamak için veriyi bir kez
    indirip data/venues.json ve data/walking_matrix.json dosyalarına kaydeder.
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


def build_osrm_walking_matrix(
    venues: List[Dict[str, Any]], strict_osrm: bool = False
) -> Dict[str, Dict[str, Dict[str, int]]]:
    coords_str = ";".join(f"{v['lon']},{v['lat']}" for v in venues)
    # Gerçek yaya profili (kaldırım, park içi yürüyüş yolu, üst geçit vb.) için OpenStreetMap routed-foot
    urls = [
        f"https://routing.openstreetmap.de/routed-foot/table/v1/foot/{coords_str}?annotations=duration,distance",
        f"https://router.project-osrm.org/table/v1/foot/{coords_str}?annotations=duration,distance",
    ]
    headers = {"User-Agent": "RotaKocaeliPlanner/2.0 (Educational Project)"}
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
                        d_sec = float(durations[i][j] or (d_m / 1.25))
                        # Bazı OSRM demo sunucuları araç hızı döndürürse yaya hızıyla (75 m/dk) tutarlı kıl
                        if "routed-foot" not in url:
                            d_sec = max(d_sec, d_m / 1.25)
                        matrix[v1["id"]][v2["id"]] = {
                            "duration_min": max(1, int(round(d_sec / 60.0))),
                            "distance_m": int(round(d_m)),
                        }
            print(f"Yaya matrisi kaynağı: {url.split('/table')[0]}", flush=True)
            return matrix
        except Exception as e:
            print(f"Yaya matrisi uyarısı ({url[:45]}...): {e}", flush=True)
            continue

    if strict_osrm:
        raise RuntimeError("Canlı OSRM/routed-foot erişilemedi (--strict-osrm).")

    print("UYARI: Canlı OSRM erişilemedi, Haversine yedek matrisi kullanılıyor.", flush=True)
    # OSRM erişilemezse Haversine yedek hesaplama
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
                "duration_min": max(1, int(round(dist / 75.0))),
                "distance_m": dist,
            }
    return matrix


def build_osrm_walking_paths(venues: List[Dict[str, Any]], strict_osrm: bool = False) -> Dict[str, List[List[float]]]:
    """Her mekan çifti arasında kaldırımları ve yaya yollarını takip eden geometrileri indirir."""
    v_by_id = {v["id"]: v for v in venues}
    v_ids = list(v_by_id.keys())
    paths: Dict[str, List[List[float]]] = {}
    session = requests.Session()
    session.headers.update({"User-Agent": "RotaKocaeliPlanner/2.0 (Educational Project)"})

    unique_total = len(v_ids) * (len(v_ids) - 1) // 2
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
            if rev_key in paths:
                paths[pair_key] = list(reversed(paths[rev_key]))
                continue

            geom = None
            for base in (
                "https://routing.openstreetmap.de/routed-foot/route/v1/foot",
                "https://router.project-osrm.org/route/v1/foot",
            ):
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
                raise RuntimeError(f"Güzergah çizgisi alınamadı: {pair_key}")
            paths[pair_key] = geom or [[u_lon, u_lat], [v_lon, v_lat]]
            fetched_count += 1
            if fetched_count % 25 == 0 or fetched_count == unique_total:
                print(f"Yaya güzergahı indirildi: {fetched_count}/{unique_total}", flush=True)
            time.sleep(0.04)
    return paths


def main() -> None:
    urllib3_cn.allowed_gai_family = lambda: socket.AF_INET
    parser = argparse.ArgumentParser(description="Kocaeli/İzmit verisini indir ve JSON'a kaydet.")
    parser.add_argument("--output-dir", default="data", help="Çıktı klasörü (varsayılan: data)")
    parser.add_argument("--refresh-matrix-only", action="store_true", help="Mevcut venues.json için sadece OSRM matrisini ve yollarını yenile")
    parser.add_argument("--strict-osrm", action="store_true", help="OSRM erişilemezse yedek veriye düşmeden hata ver")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    venues_file = out_dir / "venues.json"
    matrix_file = out_dir / "walking_matrix.json"
    paths_file = out_dir / "walking_paths.json"

    if args.refresh_matrix_only and venues_file.exists():
        with open(venues_file, encoding="utf-8") as f:
            venues = json.load(f)
        matrix = build_osrm_walking_matrix(venues, strict_osrm=args.strict_osrm)
        with open(matrix_file, "w", encoding="utf-8") as f:
            json.dump(matrix, f, ensure_ascii=False, indent=2)
        print(f"OSRM yaya matrisi güncellendi: {matrix_file} ({len(venues)} mekan)")

        paths = build_osrm_walking_paths(venues, strict_osrm=args.strict_osrm)
        with open(paths_file, "w", encoding="utf-8") as f:
            json.dump(paths, f)
        print(f"OSRM yaya yolları güncellendi: {paths_file} ({len(paths)} güzergah)")
        return

    elements = fetch_overpass_pois()
    print(f"Overpass üzerinden {len(elements)} ham kayıt çekildi.")
    print("İpucu: Çekilen ham mekanları temizleyip data/venues.json içine ekledikten sonra --refresh-matrix-only ile OSRM matrisini üretin.")


if __name__ == "__main__":
    main()

