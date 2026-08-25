"""Small, dependency-free geometry helpers for the Jeonbuk datasets.

Coordinates are GeoJSON order (longitude, latitude).  The helpers deliberately
avoid a simple bounding-box test: Jeonbuk includes offshore islands, and several
valid outlets fall outside the mainland-shaped bbox used by the first prototype.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator


Point = tuple[float, float]
Ring = list[list[float]]
Polygon = list[Ring]


def iter_polygons(geom: dict) -> Iterator[Polygon]:
    """Yield polygons (outer ring followed by holes) from a GeoJSON geometry."""
    kind = geom.get("type")
    coords = geom.get("coordinates") or []
    if kind == "Polygon":
        yield coords
    elif kind == "MultiPolygon":
        yield from coords


def iter_vertices(geom: dict) -> Iterator[Point]:
    for polygon in iter_polygons(geom):
        for ring in polygon:
            for coord in ring:
                yield float(coord[0]), float(coord[1])


def geometry_bbox(geom: dict) -> tuple[float, float, float, float]:
    vertices = list(iter_vertices(geom))
    if not vertices:
        raise ValueError("empty geometry")
    xs, ys = zip(*vertices)
    return min(xs), min(ys), max(xs), max(ys)


def _point_on_segment(x: float, y: float, a: Point, b: Point, eps: float = 1e-11) -> bool:
    ax, ay = a
    bx, by = b
    cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
    if abs(cross) > eps:
        return False
    return (min(ax, bx) - eps <= x <= max(ax, bx) + eps
            and min(ay, by) - eps <= y <= max(ay, by) + eps)


def point_in_ring(x: float, y: float, ring: Ring) -> bool:
    """Boundary-inclusive ray casting test."""
    inside = False
    if len(ring) < 3:
        return False
    prev = (float(ring[-1][0]), float(ring[-1][1]))
    for coord in ring:
        cur = (float(coord[0]), float(coord[1]))
        if _point_on_segment(x, y, prev, cur):
            return True
        x1, y1 = prev
        x2, y2 = cur
        if (y1 > y) != (y2 > y):
            x_at_y = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < x_at_y:
                inside = not inside
        prev = cur
    return inside


def point_in_polygon(x: float, y: float, polygon: Polygon) -> bool:
    if not polygon or not point_in_ring(x, y, polygon[0]):
        return False
    return not any(point_in_ring(x, y, hole) for hole in polygon[1:])


def point_in_geometry(x: float, y: float, geom: dict) -> bool:
    return any(point_in_polygon(x, y, polygon) for polygon in iter_polygons(geom))


def _ring_area_centroid(ring: Ring) -> tuple[float, float, float] | None:
    twice_area = cx = cy = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = float(ring[i][0]), float(ring[i][1])
        x1, y1 = float(ring[i + 1][0]), float(ring[i + 1][1])
        cross = x0 * y1 - x1 * y0
        twice_area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(twice_area) < 1e-15:
        return None
    return abs(twice_area) / 2.0, cx / (3.0 * twice_area), cy / (3.0 * twice_area)


def largest_polygon(geom: dict) -> Polygon | None:
    ranked = []
    for polygon in iter_polygons(geom):
        if not polygon:
            continue
        ac = _ring_area_centroid(polygon[0])
        if ac:
            ranked.append((ac[0], polygon))
    return max(ranked, key=lambda item: item[0])[1] if ranked else None


def _scanline_intersections(ring: Ring, y: float) -> list[float]:
    xs: list[float] = []
    for i in range(len(ring) - 1):
        x1, y1 = float(ring[i][0]), float(ring[i][1])
        x2, y2 = float(ring[i + 1][0]), float(ring[i + 1][1])
        # Half-open test avoids counting a vertex twice.
        if (y1 <= y < y2) or (y2 <= y < y1):
            xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    return sorted(xs)


def representative_point(geom: dict) -> tuple[float, float, str] | None:
    """Return a deterministic point inside the largest polygon component.

    The geometric centroid is used only when it is actually inside.  Concave
    polygons and islands otherwise use the midpoint of a wide interior
    scanline.  This prevents centroids in water or outside a crescent-shaped
    administrative area.
    """
    polygon = largest_polygon(geom)
    if not polygon:
        return None
    ac = _ring_area_centroid(polygon[0])
    if not ac:
        return None
    _area, cx, cy = ac
    if point_in_polygon(cx, cy, polygon):
        return cx, cy, "largest_component_centroid_inside"

    xs = [float(c[0]) for c in polygon[0]]
    ys = [float(c[1]) for c in polygon[0]]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    y_candidates = [cy, (min_y + max_y) / 2]
    y_candidates.extend(min_y + (max_y - min_y) * (i + 0.5) / 160 for i in range(160))

    best: tuple[float, float, float] | None = None
    for y in y_candidates:
        cuts = _scanline_intersections(polygon[0], y)
        for left, right in zip(cuts[0::2], cuts[1::2]):
            for frac in (0.5, 0.25, 0.75):
                x = left + (right - left) * frac
                if not point_in_polygon(x, y, polygon):
                    continue
                # Prefer a point far from the scanline boundary, then near the centroid.
                clearance = min(x - left, right - x)
                score = clearance - math.hypot(x - cx, y - cy) * 1e-3
                if best is None or score > best[0]:
                    best = (score, x, y)
    if best:
        return best[1], best[2], "largest_component_scanline_inside"

    # Extremely narrow polygons: move from a boundary vertex toward the ring
    # centroid until an interior point is found.
    for coord in polygon[0][:-1]:
        vx, vy = float(coord[0]), float(coord[1])
        for frac in (0.001, 0.01, 0.05, 0.1, 0.25, 0.5):
            x, y = vx + (cx - vx) * frac, vy + (cy - vy) * frac
            if point_in_polygon(x, y, polygon):
                return x, y, "largest_component_vertex_inset"
    return None


def combined_bbox(geometries: Iterable[dict], margin_degrees: float = 0.08) -> tuple[float, float, float, float]:
    boxes = [geometry_bbox(g) for g in geometries]
    if not boxes:
        raise ValueError("no geometries")
    return (
        min(b[1] for b in boxes) - margin_degrees,
        max(b[3] for b in boxes) + margin_degrees,
        min(b[0] for b in boxes) - margin_degrees,
        max(b[2] for b in boxes) + margin_degrees,
    )
