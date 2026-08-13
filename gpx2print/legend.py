"""Map furniture: the scale bar and the north arrow.

Both live on the flat plinth below the terrain rather than on the terrain itself.
Draping a scale bar over a hillside would make it neither straight nor readable,
and the whole point of a scale bar is that you can measure against it.
"""

from __future__ import annotations

from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from . import text3d

# Ground distances a scale bar is allowed to represent, longest first.
NICE_DISTANCES = (
    50_000, 20_000, 10_000, 5_000, 2_000, 1_000,
    500, 400, 250, 200, 100, 50, 25, 10,
)


def _as_multi(geom):
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    if isinstance(geom, MultiPolygon):
        return geom
    return MultiPolygon([g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)])


def _label(text, cx, cy, cap, max_w, font_path=None):
    """A line of text centred on (cx, cy) with the given cap height."""
    polys, _ = text3d.fit_text(text, box_w=max_w, box_h=cap, font_path=font_path)
    return affinity.translate(polys, cx, cy)


def choose_distance(mm_per_m: float, max_mm: float) -> tuple[float, float]:
    """Pick a round ground distance whose bar fits in `max_mm`."""
    for metres in NICE_DISTANCES:
        length = metres * mm_per_m
        if length <= max_mm:
            return metres, length
    metres = NICE_DISTANCES[-1]
    return metres, metres * mm_per_m


def format_distance(metres: float) -> str:
    if metres >= 1000:
        km = metres / 1000.0
        return f"{km:g} km"
    return f"{metres:g} m"


def scale_bar(
    mm_per_m: float,
    x_left: float,
    y_centre: float,
    max_w: float,
    band: float,
    font_path: str | None = None,
    segments: int = 4,
):
    """A classic chequered scale bar with its distance written above it.

    Returns (polygons, ground_metres, drawn_width_mm).
    """
    metres, length = choose_distance(mm_per_m, max_w)

    # Lay out downward from the top of the band so nothing spills over an edge.
    pad = band * 0.12
    top = y_centre + band / 2.0 - pad
    bottom = y_centre - band / 2.0 + pad
    avail = top - bottom

    cap = max(avail * 0.34, 1.8)
    bar_h = max(avail * 0.30, 1.0)
    rule = max(band * 0.035, 0.45)  # outline thickness
    y1 = bottom + bar_h
    y0 = bottom

    outer = Polygon(
        [(x_left, y0), (x_left + length, y0), (x_left + length, y1), (x_left, y1)]
    )
    inner = Polygon(
        [
            (x_left + rule, y0 + rule),
            (x_left + length - rule, y0 + rule),
            (x_left + length - rule, y1 - rule),
            (x_left + rule, y1 - rule),
        ]
    )
    parts = [outer.difference(inner)]

    # Alternate filled blocks so the divisions read at a glance.
    step = length / segments
    for i in range(0, segments, 2):
        parts.append(
            Polygon(
                [
                    (x_left + i * step, y0),
                    (x_left + (i + 1) * step, y0),
                    (x_left + (i + 1) * step, y1),
                    (x_left + i * step, y1),
                ]
            )
        )

    parts.append(
        _label(
            format_distance(metres),
            x_left + length / 2.0,
            top - cap / 2.0,
            cap,
            length,
            font_path,
        )
    )

    return _as_multi(unary_union(parts)), metres, length


def north_arrow(
    cx: float,
    y_centre: float,
    band: float,
    font_path: str | None = None,
):
    """An arrow pointing to the top of the map, with an N above it.

    North is straight up the print: the projection keeps meridians vertical.
    """
    # Laid out downward from the top of the band: N first, then the arrow beneath
    # it, so the letter cannot overflow the edge of the plinth and be clipped off.
    pad = band * 0.12
    top = y_centre + band / 2.0 - pad
    bottom = y_centre - band / 2.0 + pad
    avail = top - bottom

    cap = max(avail * 0.30, 1.8)
    gap = avail * 0.08
    arrow_h = avail - cap - gap
    head_h = arrow_h * 0.48
    head_w = band * 0.30
    tail_w = max(band * 0.075, 0.8)

    y_head_top = top - cap - gap
    y_head_base = y_head_top - head_h

    shaft = Polygon(
        [
            (cx - tail_w / 2, bottom),
            (cx + tail_w / 2, bottom),
            (cx + tail_w / 2, y_head_base + head_h * 0.30),
            (cx - tail_w / 2, y_head_base + head_h * 0.30),
        ]
    )
    head = Polygon(
        [
            (cx, y_head_top),
            (cx + head_w / 2, y_head_base),
            (cx, y_head_base + head_h * 0.28),
            (cx - head_w / 2, y_head_base),
        ]
    )
    letter = _label("N", cx, top - cap / 2.0, cap, band * 0.9, font_path)

    return _as_multi(unary_union([shaft, head, letter]))
