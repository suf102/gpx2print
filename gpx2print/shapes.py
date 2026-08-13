"""Outlines for the map plate.

The plate does not have to be a rectangle. Whatever shape is chosen has to
*contain* the terrain rectangle, not sit inside it: an inscribed circle would
crop the corners off the map and take part of the route with them. So each shape
is grown to the smallest version of itself that swallows the terrain rectangle,
and the map is then scaled back down so the finished piece still measures what
was asked for.
"""

from __future__ import annotations

import math

from shapely.geometry import Polygon, box

SHAPES = ("rectangle", "square", "circle", "triangle", "pentagon", "hexagon",
          "octagon")

# Corners per shape, and the rotation that puts a flat edge (or a point) where it
# looks deliberate: triangles and pentagons stand on a flat base with a point up,
# hexagons and octagons sit flat top and bottom.
_SIDES = {"triangle": 3, "square": 4, "pentagon": 5, "hexagon": 6, "octagon": 8}
_START = {"triangle": 90.0, "square": 45.0, "pentagon": 90.0,
          "hexagon": 0.0, "octagon": 22.5}

_CIRCLE_SEGMENTS = 192

MARGIN_MM = 0.05
"""Grown by a hair beyond the terrain rectangle.

Sized exactly, the rectangle's corners land on the outline to within rounding,
which leaves the clip boolean working on coincident faces and makes 'is it
inside?' a coin toss. A twentieth of a millimetre is invisible and removes both
problems.
"""


def _unit(shape: str) -> Polygon:
    """The shape at radius 1, centred on the origin."""
    if shape == "circle":
        n, start = _CIRCLE_SEGMENTS, 0.0
    else:
        n, start = _SIDES[shape], _START[shape]
    a0 = math.radians(start)
    pts = [
        (math.cos(a0 + 2 * math.pi * i / n), math.sin(a0 + 2 * math.pi * i / n))
        for i in range(n)
    ]
    return Polygon(pts)


def _containment_scale(unit: Polygon, w: float, h: float) -> float:
    """Smallest radius at which `unit` contains a w x h rectangle centred on it.

    For a convex polygon written as a set of half-planes n·x <= d, scaling by s
    gives n·x <= s·d, so a corner p needs s >= (n·p)/d. Taking the largest such
    value over every edge and corner gives the exact answer in one pass.
    """
    ring = list(unit.exterior.coords)[:-1]
    corners = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]

    worst = 0.0
    for i, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(i + 1) % len(ring)]
        # Outward normal of this edge, and its offset from the centre.
        nx, ny = (y2 - y1), -(x2 - x1)
        length = math.hypot(nx, ny)
        if length == 0:
            continue
        nx, ny = nx / length, ny / length
        d = nx * x1 + ny * y1
        if d <= 0:
            continue
        for px, py in corners:
            worst = max(worst, (nx * px + ny * py) / d)
    return worst


def scale_ratio(shape: str, w: float, h: float) -> float:
    """How much bigger the shape's bounding box is than the terrain rectangle."""
    if shape == "rectangle":
        return 1.0
    if shape == "square":
        return max(w, h) / max(w, h)  # handled by the frame; see outline()
    unit = _unit(shape)
    from shapely import affinity

    s = _containment_scale(unit, w + 2 * MARGIN_MM, h + 2 * MARGIN_MM)
    grown = affinity.scale(unit, xfact=s, yfact=s, origin=(0, 0))
    minx, miny, maxx, maxy = grown.bounds
    return max(maxx - minx, maxy - miny) / max(w, h)


def outline(shape: str, w: float, h: float) -> Polygon:
    """The plate outline around a terrain rectangle spanning (0,0)-(w,h)."""
    if shape not in SHAPES:
        raise ValueError(f"unknown shape {shape!r}")
    if shape == "rectangle":
        return box(0.0, 0.0, w, h)
    if shape == "square":
        side = max(w, h) + 2 * MARGIN_MM
        cx, cy = w / 2.0, h / 2.0
        return box(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)

    from shapely import affinity

    unit = _unit(shape)
    s = _containment_scale(unit, w + 2 * MARGIN_MM, h + 2 * MARGIN_MM)
    poly = affinity.scale(unit, xfact=s, yfact=s, origin=(0, 0))
    return affinity.translate(poly, w / 2.0, h / 2.0)


def fill(shape: str, w: float, h: float) -> Polygon:
    """The shape scaled to fill a w x h plate, centred, never distorted."""
    if shape == "rectangle":
        return box(0.0, 0.0, w, h)

    from shapely import affinity

    unit = _unit(shape)
    minx, miny, maxx, maxy = unit.bounds
    # One scale for both axes: a circle must stay a circle even if the plate is a
    # hair off square.
    s = min(w / (maxx - minx), h / (maxy - miny))
    poly = affinity.scale(unit, xfact=s, yfact=s, origin=(0, 0))
    minx, miny, maxx, maxy = poly.bounds
    return affinity.translate(
        poly, (w - (maxx - minx)) / 2 - minx, (h - (maxy - miny)) / 2 - miny
    )
