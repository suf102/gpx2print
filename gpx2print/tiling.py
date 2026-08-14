"""Cut the plate into tessellating pieces.

A map bigger than the print bed has to come apart somewhere, and a straight cut
across the middle reads as damage. Squares, equilateral triangles and hexagons
tile the plane, so the seams can follow a pattern instead — and the tiles are the
same shape as the plate they came out of, which is what makes it look meant.

There are two ways to get there, and they answer different halves of the request.

`divide` cuts the chosen outline up. Squares and triangles divide themselves
exactly — a square into k x k squares, a triangle into k^2 triangles, nothing
left over at the edges. A hexagon cannot be filled with smaller hexagons at all,
so the honeycomb is centred on the plate and clipped to it. Centring matters: the
lattice of hexagon centres has the same six-fold symmetry as the plate, so the
pattern comes out even rather than drifting off to one side. What that leaves is
part-hexagons around the rim, and anything too small to print is folded into the
neighbour it shares the most edge with. The map keeps its shape; the count has to
give, because a hexagon only divides into 7, 13, 19 and up.

`assemble` goes the other way. Exactly the number of whole tiles asked for are
laid over the map, and the outline is whatever they add up to — six hexagons are
six hexagons, all identical, in a cluster. The count is exact; the shape is what
gives.
"""

from __future__ import annotations

import math

import numpy as np
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

TILEABLE = ("square", "triangle", "hexagon")
"""The shapes that tile the plane. The rest have no tessellation to offer."""

LAYOUTS = ("divide", "assemble")
"""Two ways to end up with a map made of tiles, and they are not the same job.

`divide` cuts the chosen outline into pieces. The map stays a hexagon; the count
bends to fit, because a hexagon can only be cut into a honeycomb of 7, 13, 19 and
so on.

`assemble` goes the other way: lay down exactly the number of whole tiles asked
for, arranged to cover the map, and let the outline be whatever they add up to.
The count is then exact and the tiles are all identical, at the price of an
outline that is a cluster of hexagons rather than a hexagon.
"""

MIN_SHARE = 0.15
"""Smallest a clipped tile may be, as a fraction of a whole one.

Below this it is a rim sliver rather than a piece: fragile to print, fiddly to
place, and it makes the seams look accidental. Such tiles are absorbed instead.
"""

SPECK_MM2 = 0.5
"""Anything smaller than this is rounding noise, not geometry."""

MAX_STEPS = 15
"""Largest k for a k x k division: 225 pieces is far past anything sensible."""


# --------------------------------------------------------------------- lattices
def _cells_square(plate, k: int) -> list[Polygon]:
    minx, miny, maxx, maxy = plate.bounds
    w, h = (maxx - minx) / k, (maxy - miny) / k
    return [
        box(minx + i * w, miny + j * h, minx + (i + 1) * w, miny + (j + 1) * h)
        for j in range(k)
        for i in range(k)
    ]


def _cells_triangle(plate, k: int) -> list[Polygon]:
    """Divide an equilateral triangle into k^2 equilateral triangles.

    Every edge is cut into k, giving a barycentric grid of points. The upward
    triangles sit between consecutive rows; the downward ones fill the gaps
    between them. Together they cover the parent exactly, with no rim left over.
    """
    ring = list(plate.exterior.coords)[:-1]
    top = sorted(ring, key=lambda p: -p[1])
    A = np.asarray(top[0], dtype=float)
    B, C = (np.asarray(p, dtype=float) for p in sorted(top[1:], key=lambda p: p[0]))

    def P(i: int, j: int):
        return A + (B - A) * (i / k) + (C - B) * (j / k)

    cells = []
    for i in range(k):
        for j in range(i + 1):
            cells.append(Polygon([P(i, j), P(i + 1, j), P(i + 1, j + 1)]))
    for i in range(1, k):
        for j in range(i):
            cells.append(Polygon([P(i, j), P(i, j + 1), P(i + 1, j + 1)]))
    return cells


def _hexagon(x: float, y: float, r: float, turn: float = 0.0) -> Polygon:
    a0 = math.radians(turn)
    return Polygon(
        [
            (x + r * math.cos(a0 + math.pi / 3 * i),
             y + r * math.sin(a0 + math.pi / 3 * i))
            for i in range(6)
        ]
    )


def _cells_hexagon(plate, r: float) -> list[Polygon]:
    """A honeycomb of circumradius `r`, centred on the plate.

    The centres form a triangular lattice spanned by (1.5r, sqrt(3)r/2) and
    (0, sqrt(3)r), which is the offset to the neighbours sharing the upper-right
    and the top edge of a hexagon drawn with a vertex pointing along +x.
    """
    minx, miny, maxx, maxy = plate.bounds
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    dx, dy = 1.5 * r, math.sqrt(3.0) * r

    cells = []
    m_max = int(math.ceil((maxx - cx + 2 * r) / dx)) + 1
    for m in range(-m_max, m_max + 1):
        x = cx + m * dx
        lo = (miny - 2 * r - cy) / dy - m / 2.0
        hi = (maxy + 2 * r - cy) / dy - m / 2.0
        for n in range(int(math.floor(lo)), int(math.ceil(hi)) + 1):
            cells.append(_hexagon(x, cy + dy * (m / 2.0 + n), r))
    return cells


# ------------------------------------------------- laying whole tiles out freely
_UNIT_AREA = {
    "square": 1.0,
    "hexagon": 1.5 * math.sqrt(3.0),
    "triangle": math.sqrt(3.0) / 4.0,
}
"""Area of one tile per unit of its size parameter — side, or circumradius."""

SIZE_STEPS = 40
OFFSET_STEPS = 4
SNAP = 9
"""Decimal places everything in here works to.

Outlines that ought to share a boundary are worked out by separate arithmetic and
agree only to the last few bits of a double. That is enough for a union to leave a
crack down a seam, and enough for a difference to return, instead of nothing, a
thread of no width running out along one edge and back along the next. A thread
like that leaves the outline touching itself, and a piece unioned with one comes
back read as a ring — with a hole in it the size of its neighbour, and too broken
to extrude.

So every outline that goes into a boolean here is first snapped to a nanometre
grid, which is a thousand times finer than the file format records and a million
times finer than a printer can place plastic. On that grid the shared boundaries
really are shared, and the differences really do come back empty.
"""


def _snap(geom):
    """The outline on the working grid, ready to be compared with another."""
    import shapely

    return shapely.set_precision(geom, 10.0**-SNAP)


def _patterns(shape: str, size: float) -> list[tuple[list, tuple, tuple]]:
    """Ways to tile the plane with this shape: prototypes and a lattice basis.

    Each entry is the corners of the tiles sitting at one lattice point, and the
    two steps that repeat them. Hexagons get both orientations, since which way
    round they lie changes how neatly a given number of them wraps a map that is
    wider than it is tall.
    """
    if shape == "square":
        a = size
        return [([[(0, 0), (a, 0), (a, a), (0, a)]], (a, 0.0), (0.0, a))]

    if shape == "hexagon":
        r = size
        root = math.sqrt(3.0)

        def ring(turn):
            a0 = math.radians(turn)
            return [
                (r * math.cos(a0 + math.pi / 3 * i), r * math.sin(a0 + math.pi / 3 * i))
                for i in range(6)
            ]

        return [
            ([ring(0.0)], (1.5 * r, root * r / 2), (0.0, root * r)),
            ([ring(30.0)], (root * r, 0.0), (root * r / 2, 1.5 * r)),
        ]

    # Up and down triangles at every lattice point. The two steps are a side
    # along the base and a side up the left edge, which staggers the rows by
    # half a tile on its own — without that the corners of one row land on the
    # middle of the edges below, and the pieces no longer meet edge to edge.
    a = size
    tall = a * math.sqrt(3.0) / 2.0
    return [
        (
            [[(0, 0), (a, 0), (a / 2, tall)], [(a, 0), (1.5 * a, tall), (a / 2, tall)]],
            (a, 0.0),
            (a / 2, tall),
        )
    ]


def _grid(protos, a1, a2, ox: float, oy: float, bounds) -> list[Polygon]:
    """Every tile of one pattern that could reach into `bounds`.

    Built from raw coordinates rather than by transforming a prototype: this runs
    a few hundred times over while the layout is being searched, and the shapely
    machinery for moving a polygon about costs more than the geometry does.
    """
    det = a1[0] * a2[1] - a1[1] * a2[0]
    if abs(det) < 1e-12:
        return []
    minx, miny, maxx, maxy = bounds

    ms, ns = [], []
    for cx, cy in ((minx, miny), (maxx, miny), (minx, maxy), (maxx, maxy)):
        dx, dy = cx - ox, cy - oy
        ms.append((dx * a2[1] - dy * a2[0]) / det)
        ns.append((a1[0] * dy - a1[1] * dx) / det)

    cells = []
    for m in range(int(math.floor(min(ms))) - 1, int(math.ceil(max(ms))) + 1):
        for n in range(int(math.floor(min(ns))) - 1, int(math.ceil(max(ns))) + 1):
            x = ox + m * a1[0] + n * a2[0]
            y = oy + m * a1[1] + n * a2[1]
            for proto in protos:
                cells.append(
                    Polygon([(round(x + px, SNAP), round(y + py, SNAP))
                             for px, py in proto])
                )
    return cells


def _covering(cells, rect) -> list[int]:
    """Which cells hold any part of the rectangle, by index."""
    out = []
    for i, c in enumerate(cells):
        if c.intersects(rect) and c.intersection(rect).area > 1e-7:
            out.append(i)
    return out


def _span(cells, idx) -> float:
    """Longest edge of the bounding box round these cells."""
    xs0 = min(cells[i].bounds[0] for i in idx)
    ys0 = min(cells[i].bounds[1] for i in idx)
    xs1 = max(cells[i].bounds[2] for i in idx)
    ys1 = max(cells[i].bounds[3] for i in idx)
    return max(xs1 - xs0, ys1 - ys0)


def assemble(shape: str, w: float, h: float, count: int):
    """`count` whole tiles laid out to cover a w x h rectangle.

    Returns the outline they add up to and the tiles themselves, in the same
    coordinates as the rectangle.

    The whole print is scaled to the size asked for whatever happens, so what
    matters is not the tiles' own size but how much of the finished thing the
    route ends up occupying. The search is scored on the footprint the tiles add
    up to, smallest first — a pattern that wraps the map tightly leaves the route
    filling the print, while one that sprawls leaves it small in a sea of
    surrounding country. Tile size, where the lattice sits and, for hexagons,
    which way round they lie are all varied: sliding the pattern half a tile is
    often the difference between the map needing five of them and needing six.
    """
    if shape not in TILEABLE:
        raise ValueError(
            f"a map cannot be assembled out of {shape}s: they do not tile the "
            f"plane. Use one of: {', '.join(TILEABLE)}"
        )
    count = int(count)
    rect = box(0.0, 0.0, w, h)

    # Nothing can beat covering the rectangle with no waste at all, so start from
    # the size that would do exactly that and work upwards from there.
    floor = math.sqrt(rect.area / count / _UNIT_AREA[shape])
    best = None
    for step in range(SIZE_STEPS):
        size = floor * (1.0 + 3.0 * step / (SIZE_STEPS - 1))
        pad = 2.2 * size
        bounds = (-pad, -pad, w + pad, h + pad)
        for protos, a1, a2 in _patterns(shape, size):
            for fx in range(OFFSET_STEPS):
                for fy in range(OFFSET_STEPS):
                    ox = (a1[0] * fx + a2[0] * fy) / OFFSET_STEPS
                    oy = (a1[1] * fx + a2[1] * fy) / OFFSET_STEPS
                    cells = _grid(protos, a1, a2, ox, oy, bounds)
                    need = _covering(cells, rect)
                    if not need or len(need) > count:
                        continue
                    key = (count - len(need), _span(cells, need))
                    if best is None or key < best[0]:
                        best = (key, cells, need)
        # Tiles only get bigger from here, and so does anything they cover. Once
        # the full number is in use there is nothing tighter left to find.
        if best is not None and best[0][0] == 0:
            break

    if best is None:
        raise ValueError(
            f"could not lay {count} {shape}s over the map; try a different count"
        )

    _, cells, need = best
    return _pad_out(cells, need, count, w, h)


def _pad_out(cells, need: list[int], count: int, w: float, h: float):
    """Top the cluster up to `count` tiles, keeping it tight and in one piece.

    Extra tiles go on the edge nearest the middle of the map, so the cluster
    grows evenly rather than sprouting an arm. One that would close a ring around
    an untaken tile is passed over: a hole in the middle of a map is not a look
    anybody asked for, and the map would need something printed to fill it.
    """
    from shapely.geometry import Point

    picked = list(need)
    middle = Point(w / 2.0, h / 2.0)

    def merged(idx):
        return unary_union([cells[i] for i in idx]).buffer(0)

    while len(picked) < count:
        edge = unary_union([cells[i] for i in picked]).buffer(0)
        outside = [i for i in range(len(cells)) if i not in picked]
        near = sorted(
            (i for i in outside if _shared_edge(cells[i], edge) > 1e-6),
            key=lambda i: cells[i].centroid.distance(middle),
        )
        if not near:
            break
        for i in near:
            trial = merged([*picked, i])
            if not list(getattr(trial, "interiors", [])) and len(
                getattr(trial, "geoms", [trial])
            ) == 1:
                picked.append(i)
                break
        else:
            picked.append(near[0])

    tiles = _sort([cells[i] for i in picked], unary_union([cells[i] for i in picked]))
    return unary_union(tiles).buffer(0), tiles


def attach_strip(tiles, plate, region) -> list:
    """Give the pieces along one edge of the plate their share of the strip."""
    tiles = [_snap(t) for t in tiles]
    plate, region = _snap(plate), _snap(region)
    leftover = _strip_only(region, plate)
    if leftover.is_empty or leftover.area <= SPECK_MM2:
        return _repair(tiles)
    return _repair(_attach(tiles, leftover, plate))


# ------------------------------------------------------------------- choosing k
def _survivors(cells, plate) -> int:
    """How many cells would end up as pieces, without doing the work of merging."""
    n = 0
    for c in cells:
        if c.intersection(plate).area >= MIN_SHARE * c.area:
            n += 1
    return n


def _rank(n: int, want: int):
    """Closest count wins; a tie goes to the one that overshoots.

    Overshooting means smaller pieces, and someone who asked for six is dividing
    a map to get it onto a bed. Seven small pieces still fit that bed; five
    larger ones might not.
    """
    return (abs(n - want), 0 if n >= want else 1)


def _candidates(shape: str, plate, want: int) -> list[list[Polygon]]:
    """Lattices worth trying, most promising first.

    Squares and triangles can only be divided k x k, so the reachable counts are
    1, 4, 9, 16 and so on. Hexagons look continuous — the honeycomb pitch is a
    real number — but the six-fold symmetry quantises them just as firmly, into
    1, 7, 13, 19 and upwards. Either way the request usually cannot be met
    exactly, so several nearby lattices are offered and the caller picks by the
    count each one really produces.
    """
    if shape in ("square", "triangle"):
        maker = _cells_square if shape == "square" else _cells_triangle
        # A request to split the map is never answered by not splitting it.
        ks = sorted(range(2, MAX_STEPS + 1), key=lambda n: _rank(n * n, want))
        return [maker(plate, k) for k in ks[:3]]

    minx, _, maxx, _ = plate.bounds
    radius = (maxx - minx) / 2.0
    guess = math.sqrt(max(want, 1))

    # Sweep the pitch and collect the distinct counts it passes through, keeping
    # the middle of each plateau: a pitch sitting right on a threshold has cells
    # grazing the rim, which is exactly where the count is least predictable.
    runs: list[tuple[int, list[float]]] = []
    f = max(1.0, guess - 2.0)
    while f <= guess + 2.0 + 1e-9:
        n = _survivors(_cells_hexagon(plate, radius / f), plate)
        if runs and runs[-1][0] == n:
            runs[-1][1].append(f)
        else:
            runs.append((n, [f]))
        f += 0.1

    # Three pitches from each plateau rather than one. They give the same count,
    # but not the same tessellation: whether a cell lands centred on a corner of
    # the plate — which is what leaves a wedge with nowhere to go — moves with the
    # pitch inside a plateau, so a count that looks unreachable at one pitch is
    # often perfectly clean a hair either side of it.
    picks: list[tuple[tuple, float]] = []
    for n, fs in runs:
        if n <= 1:
            continue
        rank = _rank(n, want)
        for order, part in enumerate((0.5, 0.28, 0.72)):
            picks.append(((rank, order), fs[min(int(len(fs) * part), len(fs) - 1)]))
    picks.sort(key=lambda p: p[0])
    return [_cells_hexagon(plate, radius / f) for _, f in picks[:9]]


# ------------------------------------------------------------- tidying the rim
def _clip(cells, plate) -> list[dict]:
    out = []
    for c in cells:
        g = _snap(c.intersection(plate))
        if g.is_empty or g.area <= SPECK_MM2:
            continue
        out.append({"poly": g, "full": c.area})
    return out


def _shared_edge(a, b) -> float:
    try:
        return a.boundary.intersection(b.boundary).length
    except Exception:  # noqa: BLE001 - a failed measurement just means "not adjacent"
        return 0.0


def _best_neighbour(pieces: list[dict], i: int):
    """The piece sharing the most edge with this one, or None if none does.

    There is deliberately no fall-back to the merely nearest piece. At the corner
    of a hexagon plate a sliver can meet its neighbours at a single point, and
    two polygons touching at a point do not become one when unioned — shapely
    keeps them apart, and the "merge" would ship as two loose fragments in one
    file. A sliver left whole is a worse-looking piece; a sliver merged badly is
    a broken one.
    """
    me = pieces[i]["poly"]
    best, score = None, 0.0
    for j, p in enumerate(pieces):
        if j == i:
            continue
        s = _shared_edge(me, p["poly"])
        if s > score:
            best, score = j, s
    return best


def _absorb(pieces: list[dict]) -> tuple[list[dict], list[int]]:
    """Fold rim slivers into the neighbour they share the most edge with.

    Merging along the longest shared edge, rather than into the nearest piece,
    is what keeps the result in one lump: two shapes that share an edge always
    make a connected whole, while the nearest one might only be near.
    """
    stuck: set[int] = set()
    for _ in range(len(pieces)):
        if len(pieces) <= 1:
            break
        runts = [
            i
            for i, p in enumerate(pieces)
            if i not in stuck and p["poly"].area < MIN_SHARE * p["full"]
        ]
        if not runts:
            break
        i = min(runts, key=lambda k: pieces[k]["poly"].area)
        j = _best_neighbour(pieces, i)
        if j is None:
            # Nothing to join it to without breaking it. Leave it be, and do not
            # come back to it, or the loop never ends.
            stuck.add(i)
            continue
        pieces[j]["poly"] = unary_union([pieces[j]["poly"], pieces[i]["poly"]]).buffer(0)
        pieces[j]["full"] = max(pieces[j]["full"], pieces[i]["full"])
        pieces.pop(i)
        stuck = {k - 1 if k > i else k for k in stuck if k != i}
    return pieces, sorted(stuck)


def _sort(tiles, plate) -> list:
    """Number the pieces in reading order, so they can be laid out as printed.

    Rows are judged on where a piece starts rather than where its middle is: a
    row of triangles alternates up and down, and their middles sit at different
    heights even though they plainly belong to the same row.
    """
    minx, miny, maxx, maxy = plate.bounds
    rows = max(1, int(round(math.sqrt(max(len(tiles), 1)))))
    band = max((maxy - miny) / rows / 1.6, 1e-6)
    return sorted(tiles, key=lambda t: (-round(t.bounds[1] / band), t.centroid.x))


def _despike(poly):
    """Drop ring vertices that lie on the line through their two neighbours.

    Subtracting the plate from plate-plus-strip leaves a wedge in each corner,
    and the wedge's ring runs out along the plate's edge to a far-off vertex and
    straight back — a spike of no width and no area. It costs nothing in area but
    it stretches the wedge's bounding box across the whole map and gives it a
    long shared edge with pieces nowhere near it, so the strip gets handed to the
    wrong one. Simplification will not remove it: the stray vertex is nowhere
    near the *segment* between its neighbours, only near the line through them.
    """
    from shapely.geometry import Polygon as _P

    def tidy(coords):
        pts = list(coords)[:-1]
        changed = True
        while changed and len(pts) > 3:
            changed = False
            for k in range(len(pts)):
                a, v, b = pts[k - 1], pts[k], pts[(k + 1) % len(pts)]
                cross = (v[0] - a[0]) * (b[1] - a[1]) - (v[1] - a[1]) * (b[0] - a[0])
                span = math.hypot(b[0] - a[0], b[1] - a[1])
                if span > 0 and abs(cross) / span < 1e-7:
                    pts.pop(k)
                    changed = True
                    break
        return pts

    out = []
    for g in getattr(poly, "geoms", [poly]):
        if not isinstance(g, Polygon) or g.is_empty:
            continue
        shell = tidy(g.exterior.coords)
        if len(shell) < 3:
            continue
        # Pinholes come from the same rounding as the spikes and are just as
        # unreal, but a triangulator takes a hole seriously however thin it is
        # and hands back a surface that will not close.
        holes = [
            h
            for h in (tidy(r.coords) for r in g.interiors)
            if len(h) >= 3 and _P(h).area > SPECK_MM2
        ]
        fixed = _P(shell, holes)
        out.append(fixed if fixed.is_valid else fixed.buffer(0))
    return unary_union(out) if out else poly


def _strip_only(region, plate):
    """What the caption strip adds to the plate, with the boolean's litter gone."""
    left = _despike(_snap(region.difference(plate)))
    keep = [g for g in getattr(left, "geoms", [left]) if g.area > SPECK_MM2]
    return unary_union(keep) if keep else left


CONTACT_MM = 0.5
"""How much of the plate's edge a piece must hold to be given part of the strip.

In a divided triangle the downward-pointing pieces of the bottom row reach the
base at a single point. Handing one of those a slab of caption strip joined at a
point would ship it as two loose fragments.
"""


def _attach(tiles, leftover, plate) -> list:
    """Hand the caption strip out among the pieces sitting along the plate's edge.

    Each of those pieces holds a stretch of that edge, and takes the slab of
    strip directly below (or above) its own stretch, so the two always meet along
    a real edge rather than at a point. The two outermost slabs run out to the
    ends of the strip: under a hexagon the strip spans the full width of the
    bounding box while the hexagon's own bottom edge is only half that, and those
    overhanging ends have nothing above them to belong to.
    """
    pminx, pminy, pmaxx, pmaxy = plate.bounds
    lminx, lminy, lmaxx, lmaxy = leftover.bounds
    on_top = (lminy + lmaxy) / 2.0 > plate.centroid.y

    edge = 0.05
    probe = (
        box(pminx - 1, pmaxy - edge, pmaxx + 1, pmaxy)
        if on_top
        else box(pminx - 1, pminy, pmaxx + 1, pminy + edge)
    )
    spans = []
    for i, t in enumerate(tiles):
        touch = t.intersection(probe)
        if touch.is_empty:
            continue
        x0, _, x1, _ = touch.bounds
        if x1 - x0 > CONTACT_MM:
            spans.append((x0, x1, i))

    if not spans:
        # Nothing sits along that edge at all, so the strip goes to the nearest.
        spans = [(lminx, lmaxx,
                  min(range(len(tiles)), key=lambda k: tiles[k].distance(leftover)))]

    # The stretches of edge held by different pieces are not always laid out
    # neatly one after another: a hexagon meeting the edge at a point sits inside
    # the stretch its neighbour holds. So the strip is split at every stretch's
    # ends, and each sliver between two of them goes to the narrowest stretch
    # covering it, or to the nearest if none does. Cutting halfway between
    # stretches instead would hand a nested one's slab to its neighbour, leaving
    # a piece wrapped round a slab that is not its own.
    marks = sorted({lminx - 1.0, lmaxx + 1.0}
                   | {v for x0, x1, _ in spans for v in (x0, x1)})

    groups: list[list] = [[t] for t in tiles]
    for a, b in zip(marks[:-1], marks[1:]):
        slab = box(a, lminy - 1.0, b, lmaxy + 1.0).intersection(leftover)
        if slab.is_empty or slab.area <= 0:
            continue
        mid = (a + b) / 2.0
        holding = [(x1 - x0, i) for x0, x1, i in spans if x0 <= mid <= x1]
        if holding:
            owner = min(holding)[1]
        else:
            owner = min(
                (min(abs(mid - x0), abs(mid - x1)), i) for x0, x1, i in spans
            )[1]
        groups[owner].append(slab)
    return [_snap(unary_union(g).buffer(0)) for g in groups]


WELD_MM = 0.002
"""How wide a crack counts as no crack at all.

Two pieces that meet along a shared edge sometimes fail to weld, because one of
the shared vertices came out of a boolean and lands a hair off the line the other
was drawn on. Two microns is far below anything a printer can resolve and far
above the error, so closing the gap costs nothing real.
"""


def _repair(tiles) -> list:
    """Put right any piece that came out as two lumps rather than one.

    A file holding two loose fragments is worse than an odd-looking seam, so this
    checks. Most cases are a hairline crack and close up; anything genuinely
    detached is handed to a piece that does touch it.
    """
    out = list(tiles)
    for i, t in enumerate(out):
        if len(getattr(t, "geoms", [t])) <= 1:
            continue
        # Rounded joins, not mitred: where the two lumps meet at a point the
        # mitre runs out into a spike, and the result passes every validity check
        # while quietly giving the wrong answer to anything overlaid on it.
        closed = t.buffer(WELD_MM).buffer(-WELD_MM)
        if len(getattr(closed, "geoms", [closed])) == 1:
            out[i] = closed
            continue

        parts = sorted(getattr(closed, "geoms", [closed]), key=lambda g: -g.area)
        out[i] = parts[0]
        for stray in parts[1:]:
            if stray.area <= SPECK_MM2:
                continue
            j, score = None, 0.0
            for k, other in enumerate(out):
                if k == i:
                    continue
                s = _shared_edge(stray, other)
                if s > score:
                    j, score = k, s
            if j is None:
                out[i] = unary_union([out[i], stray])
            else:
                out[j] = unary_union([out[j], stray]).buffer(0)
    return out


# ------------------------------------------------------------------- public API
def divide(shape: str, plate, region, want: int) -> list:
    """Split `region` into tessellating pieces, as near `want` of them as it goes.

    `plate` is the map outline; `region` is that plus the caption strip, which is
    not part of the tessellation but has to end up attached to something.
    """
    if shape not in TILEABLE:
        raise ValueError(
            f"{shape} does not tessellate, so it cannot be split into pieces. "
            f"Use one of: {', '.join(TILEABLE)}"
        )
    want = int(want)
    plate, region = _snap(plate), _snap(region)
    if want <= 1:
        return [region]

    # Rim slivers get folded into their neighbours, and how many that removes is
    # not known until it is done — two slivers merging can add up to a piece that
    # stands on its own. So the candidates are actually cut, not just predicted.
    #
    # A lattice that leaves a sliver with nowhere to go is rejected outright, even
    # if its count is the closest. That happens when a cell lands centred on a
    # corner of the plate and the wedge it leaves meets its neighbours at a point;
    # shifting to the next pitch up or down avoids it, and a spare unprintable
    # speck of a piece is a worse answer than missing the requested count by one.
    best = None
    for cells in _candidates(shape, plate, want):
        pieces = _clip(cells, plate)
        if not pieces:
            continue
        pieces, stuck = _absorb(pieces)
        key = (bool(stuck), *_rank(len(pieces), want))
        if best is None or key < best[0]:
            best = (key, pieces)
        if key[:2] == (False, 0):
            break
    if best is None:
        raise ValueError("the tessellation covered none of the map")

    return attach_strip(_sort([p["poly"] for p in best[1]], plate), plate, region)


COLLAR_BITE_MM = 0.05
"""How far the collar reaches back inside the plate, past its outer wall.

Butted exactly against the tile it belongs to, the collar's inner edge and the
tile's outer edge are the same line to the last bit of a double, and the union
of the two solids comes out full of micro-slivers — which look watertight in
memory and fall apart when the file is read back. Overlapping them by a real
amount gives the boolean something solid to work with. The cost is that a collar
also bites the same skin off the two neighbours within a millimetre along the
rim, so those pieces meet the map's edge 0.05 mm proud of where they should:
a twentieth of a millimetre, well inside what any printer holds anyway.
"""


def prism_polygons(tile, region, out_mm: float = 1.2) -> list:
    """The shapes to extrude and join into the tool that cuts this piece out.

    Coincident faces are what a boolean engine handles worst, and the map's own
    outside wall sits exactly on the outer edge of the rim pieces. Adding a collar
    that reaches a millimetre past it removes the argument. The *inside* edges are
    left exactly where they are: those are the seams between two pieces that have
    to butt up against each other.

    The collar is returned beside the tile rather than merged into it. Merged, the
    two often meet at a single corner and nowhere else, and a ring that visits the
    same vertex twice makes the triangulator hand back a surface with holes in it.
    Nudging them into an overlap works, but leaves slivers a tenth of a micron
    wide in the finished mesh — which survive in memory and come apart on the way
    back off disk. Extruding each shape cleanly and letting the boolean engine
    join the solids avoids both.
    """
    tile, region = _snap(tile), _snap(region)
    collar = _snap(
        tile.buffer(out_mm, join_style=2, mitre_limit=3.0).difference(
            region.buffer(-COLLAR_BITE_MM, join_style=2, mitre_limit=3.0)
        )
    )
    out = [tile]
    for g in getattr(collar, "geoms", [collar]):
        if not g.is_empty and g.area > 0.05:
            out.append(g)
    return [p for p in (_despike(g) for g in out) if not p.is_empty]


def counts_near(shape: str) -> str:
    """What this shape can actually be divided into, in words, for the user.

    Both cases are quantised, for the same underlying reason: the tessellation
    has to keep the plate's own symmetry or it stops looking deliberate.
    """
    if shape in ("square", "triangle"):
        return ("only divides " + " x ".join(("k", "k"))
                + ", so 4, 9, 16, 25 and so on")
    return "only comes out in a honeycomb count, so 7, 13, 19, 21 and upwards"
