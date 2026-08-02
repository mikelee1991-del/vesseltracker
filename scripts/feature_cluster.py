"""Cluster AIS stop positions into underwater features by proximity.

Stops within FEATURE_CLUSTER_RADIUS_M of a shared centroid are treated as the
same place — absorbing AIS/GPS revisit scatter without single-linkage chaining
along a reef or transit path.
"""

from __future__ import annotations

import math
from collections import defaultdict


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _centroid(lats: list[float], lons: list[float], members: list[int]) -> tuple[float, float]:
    return (
        sum(lats[i] for i in members) / len(members),
        sum(lons[i] for i in members) / len(members),
    )


def cluster_indices_by_distance(
    lats: list[float],
    lons: list[float],
    radius_m: float,
) -> list[int]:
    """Centroid-bounded clustering: every member stays within radius_m of centroid.

    Greedy seed order is sorted by (lat, lon) for stability, then a few
    reassignment passes pull points to the nearest in-radius centroid.
    """
    n = len(lats)
    if n == 0:
        return []
    if n != len(lons):
        raise ValueError("lats/lons length mismatch")

    order = sorted(range(n), key=lambda i: (round(lats[i], 6), round(lons[i], 6)))
    clusters: list[list[int]] = []
    centroids: list[tuple[float, float]] = []

    # Spatial hash for candidate centroids.
    def bin_key(lat: float, lon: float) -> tuple[int, int]:
        x = lon * 111320.0 * math.cos(math.radians(lat))
        y = lat * 111320.0
        return int(math.floor(x / radius_m)), int(math.floor(y / radius_m))

    def nearby_cluster_ids(lat: float, lon: float) -> list[int]:
        bx, by = bin_key(lat, lon)
        out: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                out.extend(centroid_bins.get((bx + dx, by + dy), []))
        return out

    centroid_bins: dict[tuple[int, int], list[int]] = defaultdict(list)

    def reindex_bins() -> None:
        centroid_bins.clear()
        for k, (clat, clon) in enumerate(centroids):
            centroid_bins[bin_key(clat, clon)].append(k)

    for i in order:
        best_k = None
        best_d = radius_m
        for k in nearby_cluster_ids(lats[i], lons[i]):
            clat, clon = centroids[k]
            d = haversine_m(lats[i], lons[i], clat, clon)
            if d <= best_d:
                best_d = d
                best_k = k
        if best_k is None:
            centroids.append((lats[i], lons[i]))
            clusters.append([i])
            centroid_bins[bin_key(lats[i], lons[i])].append(len(clusters) - 1)
        else:
            clusters[best_k].append(i)
            centroids[best_k] = _centroid(lats, lons, clusters[best_k])
            reindex_bins()

    # Reassignment passes: each point → nearest centroid within radius; orphans
    # seed new clusters. Guarantees centroid membership after convergence.
    for _ in range(4):
        new_assign = [-1] * n
        for i in range(n):
            best_k = None
            best_d = radius_m
            for k in nearby_cluster_ids(lats[i], lons[i]):
                clat, clon = centroids[k]
                d = haversine_m(lats[i], lons[i], clat, clon)
                if d <= best_d:
                    best_d = d
                    best_k = k
            new_assign[i] = best_k if best_k is not None else -1

        # Rebuild clusters from assignments; orphans become singleton seeds in order.
        rebuilt: list[list[int]] = [[] for _ in centroids]
        orphans: list[int] = []
        for i in order:
            k = new_assign[i]
            if k is None or k < 0:
                orphans.append(i)
            else:
                rebuilt[k].append(i)
        clusters = [m for m in rebuilt if m]
        for i in orphans:
            # try existing rebuilt centroids first
            placed = False
            cents = [_centroid(lats, lons, m) for m in clusters]
            for k, (clat, clon) in enumerate(cents):
                if haversine_m(lats[i], lons[i], clat, clon) <= radius_m:
                    clusters[k].append(i)
                    placed = True
                    break
            if not placed:
                clusters.append([i])
        centroids = [_centroid(lats, lons, m) for m in clusters]
        reindex_bins()

    # Stable ids by centroid location.
    order_c = sorted(range(len(clusters)), key=lambda k: centroids[k])
    labels = [0] * n
    for new_id, old_k in enumerate(order_c):
        for i in clusters[old_k]:
            labels[i] = new_id
    return labels


def assign_feature_ids(
    stops: list[dict],
    radius_m: float,
    id_prefix: str = "f",
) -> list[dict]:
    """Mutate/return stops with feature_id and feature_cluster_radius_m."""
    if not stops:
        return stops
    order = sorted(
        range(len(stops)),
        key=lambda i: (
            round(float(stops[i]["lat"]), 6),
            round(float(stops[i]["lon"]), 6),
            stops[i].get("start_utc") or "",
            int(stops[i].get("mmsi") or 0),
        ),
    )
    lats = [float(stops[i]["lat"]) for i in order]
    lons = [float(stops[i]["lon"]) for i in order]
    labels = cluster_indices_by_distance(lats, lons, radius_m)
    for pos, stop_i in enumerate(order):
        stops[stop_i]["feature_id"] = f"{id_prefix}_{labels[pos]:05d}"
        stops[stop_i]["feature_cluster_radius_m"] = radius_m
    return stops
