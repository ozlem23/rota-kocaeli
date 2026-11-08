from __future__ import annotations

from itertools import permutations
from typing import Dict, List, Tuple


def get_leg(
    matrix: Dict[str, Dict[str, Dict[str, int]]],
    from_id: str,
    to_id: str,
) -> Tuple[int, int]:
    """İki mekan arasındaki (yürüme_dk, mesafe_m) bilgisini döndürür."""
    if from_id == to_id:
        return 0, 0
    leg = matrix.get(from_id, {}).get(to_id)
    if leg:
        return int(leg.get("duration_min", 10)), int(leg.get("distance_m", 750))
    return 10, 750


def route_walk_totals(
    start_id: str,
    ordered_stops: List[str],
    end_id: str,
    matrix: Dict[str, Dict[str, Dict[str, int]]],
) -> Tuple[int, int]:
    """Verilen sıranın toplam yürüme süresi (dk) ve mesafesini (m) hesaplar."""
    full_path = [start_id, *ordered_stops, end_id]
    total_min = 0
    total_m = 0
    for a, b in zip(full_path, full_path[1:]):
        d_min, d_m = get_leg(matrix, a, b)
        total_min += d_min
        total_m += d_m
    return total_min, total_m


def _nearest_neighbor_with_2opt(
    start_id: str,
    stop_ids: List[str],
    end_id: str,
    matrix: Dict[str, Dict[str, Dict[str, int]]],
) -> List[str]:
    """8'den fazla durak için hızlı Nearest Neighbor + 2-opt sezgisel çözümü."""
    remaining = list(stop_ids)
    order: List[str] = []
    current = start_id
    while remaining:
        nxt = min(remaining, key=lambda vid: get_leg(matrix, current, vid)[0])
        order.append(nxt)
        remaining.remove(nxt)
        current = nxt

    improved = True
    while improved and len(order) >= 3:
        improved = False
        best_cost = route_walk_totals(start_id, order, end_id, matrix)[0]
        for i in range(len(order) - 1):
            for j in range(i + 1, len(order)):
                candidate = order[:i] + list(reversed(order[i : j + 1])) + order[j + 1 :]
                cost = route_walk_totals(start_id, candidate, end_id, matrix)[0]
                if cost < best_cost:
                    order = candidate
                    best_cost = cost
                    improved = True
                    break
            if improved:
                break
    return order


def rank_candidate_orders(
    start_id: str,
    stop_ids: List[str],
    end_id: str,
    matrix: Dict[str, Dict[str, Dict[str, int]]],
    top_k: int = 50,
) -> List[Tuple[int, int, List[str]]]:
    """
    Verilen duraklar için en az yürüme süresine sahip aday sıralamaları döndürür.
    <= 7 durakta tüm permütasyonları (Slayt 9 yaklaşımı) kesin olarak dener.
    """
    unique_stops = [s for s in dict.fromkeys(stop_ids) if s not in (start_id, end_id)]
    if not unique_stops:
        d_min, d_m = get_leg(matrix, start_id, end_id)
        return [(d_min, d_m, [])]

    if len(unique_stops) <= 7:
        scored: List[Tuple[int, int, List[str]]] = []
        for perm in permutations(unique_stops):
            seq = list(perm)
            total_min, total_m = route_walk_totals(start_id, seq, end_id, matrix)
            scored.append((total_min, total_m, seq))
        scored.sort(key=lambda item: (item[0], item[1]))
        return scored[:top_k]

    heuristic_seq = _nearest_neighbor_with_2opt(start_id, unique_stops, end_id, matrix)
    total_min, total_m = route_walk_totals(start_id, heuristic_seq, end_id, matrix)
    return [(total_min, total_m, heuristic_seq)]

