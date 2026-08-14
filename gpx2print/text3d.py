"""Turn a caption string into solid geometry.

Glyph outlines come from matplotlib's TextPath, which gives real vector contours,
so the lettering stays crisp at any size instead of being traced from a bitmap.
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union


def _rings_to_polygons(rings: list[np.ndarray]) -> MultiPolygon:
    """Nest glyph contours so counters ('o', 'e', 'A') become real holes.

    Nesting is decided from points taken *on* each contour rather than from an
    interior point: the interior point of a ring like "0" or "O" can fall inside
    its own counter, which would classify the whole glyph as a hole and silently
    drop the letter.
    """
    from shapely.geometry import Point
    from shapely.prepared import prep

    shapes: list[Polygon] = []
    for r in rings:
        if len(r) < 3:
            continue
        p = Polygon(r)
        if p.is_empty or abs(p.area) < 1e-9:
            continue
        shapes.append(p)

    if not shapes:
        return MultiPolygon()

    ready = [prep(p) for p in shapes]
    probes = []
    for p in shapes:
        c = np.asarray(p.exterior.coords)[:-1]
        k = len(c)
        probes.append([Point(c[0]), Point(c[k // 3]), Point(c[2 * k // 3])])

    n = len(shapes)
    inside = np.zeros((n, n), dtype=bool)  # inside[i, j]: ring i sits within ring j
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            votes = sum(1 for pt in probes[i] if ready[j].contains(pt))
            inside[i, j] = votes >= 2

    depth = inside.sum(axis=1)

    built = []
    for i in range(n):
        if depth[i] % 2 != 0:
            continue
        holes = [
            np.asarray(shapes[j].exterior.coords)
            for j in range(n)
            if depth[j] == depth[i] + 1 and inside[j, i]
        ]
        poly = Polygon(np.asarray(shapes[i].exterior.coords), holes)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if not poly.is_empty:
            built.append(poly)

    merged = unary_union(built) if built else MultiPolygon()
    if isinstance(merged, Polygon):
        merged = MultiPolygon([merged])
    return merged


def text_polygons(text: str, font_path: str | None = None, size: float = 100.0):
    """Vector outline of `text` as a shapely MultiPolygon, baseline at y=0."""
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath

    kwargs = {"size": size}
    if font_path:
        kwargs["fname"] = font_path
    else:
        kwargs["family"] = "DejaVu Sans"
        kwargs["weight"] = "bold"
    prop = FontProperties(**kwargs)

    path = TextPath((0, 0), text, prop=prop, size=size)
    rings = [np.asarray(p) for p in path.to_polygons(closed_only=True)]
    return _rings_to_polygons(rings)


def _fit(polys, box_w: float, box_h: float):
    """Scale to fill the box and centre on the origin."""
    from shapely import affinity

    minx, miny, maxx, maxy = polys.bounds
    w = max(maxx - minx, 1e-6)
    h = max(maxy - miny, 1e-6)

    scale = min(box_w / w, box_h / h)
    out = affinity.scale(polys, xfact=scale, yfact=scale, origin=(0, 0))
    minx, miny, maxx, maxy = out.bounds
    out = affinity.translate(out, -(minx + maxx) / 2, -(miny + maxy) / 2)
    return out, scale


def fit_text(
    text: str,
    box_w: float,
    box_h: float,
    font_path: str | None = None,
):
    """Scale and centre the caption inside a `box_w` x `box_h` rectangle.

    Returns the polygons centred on the origin, plus the scale factor applied.
    """
    polys = text_polygons(text, font_path=font_path, size=100.0)
    if polys.is_empty:
        raise ValueError(f"the caption {text!r} produced no printable glyphs")
    return _fit(polys, box_w, box_h)


def text_block(lines: list[str], font_path: str | None = None, line_gap: float = 0.45):
    """Stack several lines of text, centred on each other, at a nominal size."""
    from shapely import affinity

    step = 100.0 * (1.0 + line_gap)
    parts = []
    for i, line in enumerate(lines):
        p = text_polygons(line, font_path=font_path, size=100.0)
        if p.is_empty:
            continue
        minx, _, maxx, _ = p.bounds
        parts.append(affinity.translate(p, -(minx + maxx) / 2.0, -step * i))

    if not parts:
        raise ValueError("the credit text produced no printable glyphs")

    merged = unary_union(parts)
    if isinstance(merged, Polygon):
        merged = MultiPolygon([merged])
    return merged


_WRAP_CACHE: dict = {}
"""Layouts already worked out, keyed by text and box.

A map split into tessellating pieces engraves the same credit into every piece,
and the pieces are usually congruent, so the same wrap is otherwise computed a
couple of dozen times over — each one building glyph outlines for five candidate
line counts.
"""


def best_wrap(text: str, box_w: float, box_h: float, font_path=None, max_lines=5):
    """Choose the number of lines that makes the lettering as large as possible.

    One long line on a narrow map scales down until the strokes are finer than a
    nozzle can lay. Splitting it lets the letters grow instead.
    """
    import textwrap

    key = (text, round(box_w, 3), round(box_h, 3), font_path, max_lines)
    if key in _WRAP_CACHE:
        return _WRAP_CACHE[key]

    best = None
    for n in range(1, max_lines + 1):
        width = max(6, -(-len(text) // n))
        lines = textwrap.wrap(text, width=width) or [text]
        if len(lines) > n:
            continue
        block = text_block(lines, font_path=font_path)
        fitted, scale = _fit(block, box_w, box_h)
        cap = scale * 100.0
        if best is None or cap > best[2]:
            best = (fitted, lines, cap)
    # Shapely geometry is never mutated in place here, so sharing it is safe.
    _WRAP_CACHE[key] = best
    return best


def underside_text(
    text: str,
    centre_xy: tuple[float, float],
    box_w: float,
    box_h: float,
    depth: float,
    font_path: str | None = None,
    fallback: str | None = None,
    min_cap: float = 2.4,
):
    """Lettering to engrave into a face at z=0 that points downward.

    Mirrored in X, so it reads the right way round when the print is turned over.
    Falls back to shorter wording when the map is too small for the full credit.
    """
    from shapely import affinity

    from .meshlib import extrude

    best = best_wrap(text, box_w, box_h, font_path)
    if best is None:
        raise ValueError("the credit text produced no printable glyphs")

    if best[2] < min_cap and fallback:
        alt = best_wrap(fallback, box_w, box_h, font_path)
        if alt is not None and alt[2] > best[2]:
            best = alt

    polys, lines, cap = best
    polys = affinity.scale(polys, xfact=-1.0, yfact=1.0, origin=(0, 0))
    polys = affinity.translate(polys, centre_xy[0], centre_xy[1])

    overlap = 0.3
    mesh = extrude(polys, height=depth + overlap, z0=-overlap)
    return mesh, lines, cap


def caption_solid(
    text: str,
    centre_xy: tuple[float, float],
    box_w: float,
    box_h: float,
    z_surface: float,
    depth: float,
    style: str = "emboss",
    font_path: str | None = None,
):
    """Build the lettering geometry to union onto (or subtract from) a flat band.

    The prism deliberately overlaps the band it meets so the boolean has a clean
    volume to work with rather than two coincident faces.
    """
    from shapely import affinity

    polys, _ = fit_text(text, box_w, box_h, font_path=font_path)
    polys = affinity.translate(polys, centre_xy[0], centre_xy[1])

    from .meshlib import extrude

    overlap = max(depth * 0.5, 0.4)
    if style == "emboss":
        mesh = extrude(polys, height=depth + overlap, z0=z_surface - overlap)
    else:
        mesh = extrude(polys, height=depth + overlap, z0=z_surface - depth)
    return mesh, polys
