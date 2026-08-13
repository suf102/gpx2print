"""Build the two printable parts from a GPX file."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh
from shapely.geometry import LineString, MultiLineString, box
from shapely.ops import unary_union

from . import chain, dem, gpx_io, legend, meshlib, text3d

MIN_FLOOR_MM = 1.2
"""Material left under the deepest point of the channel."""


@dataclass
class Build:
    map_mesh: trimesh.Trimesh
    trail_mesh: trimesh.Trimesh
    map_meshes: list = field(default_factory=list)
    trail_meshes: list = field(default_factory=list)
    sections: list = field(default_factory=list)
    section_lines: list = field(default_factory=list)
    parts: list = field(default_factory=list)
    frame: gpx_io.Frame = None
    track: gpx_io.Track = None
    X: np.ndarray = None
    Y: np.ndarray = None
    Z_mm: np.ndarray = None
    Z_m: np.ndarray = None
    path_mm: MultiLineString = None
    plinth_polys: object = None
    band_mm: float = 0.0
    stats: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _log(cfg):
    def log(msg):
        if getattr(cfg, "log_fn", None) is not None:
            cfg.log_fn(str(msg))
        elif cfg.verbose:
            print(msg, flush=True)

    return log


def _grid_shape(frame, n: int) -> tuple[int, int]:
    if frame.width_mm >= frame.height_mm:
        nx = n
        ny = max(16, int(round(n * frame.height_mm / frame.width_mm)))
    else:
        ny = n
        nx = max(16, int(round(n * frame.width_mm / frame.height_mm)))
    return ny, nx


def _project_path(track, frame, simplify_mm: float) -> MultiLineString:
    lines = []
    for lat, lon in track.segments():
        x, y = frame.to_mm(lat, lon)
        ls = LineString(np.column_stack([x, y]))
        if simplify_mm > 0:
            ls = ls.simplify(simplify_mm, preserve_topology=False)
        if ls.length > 0:
            lines.append(ls)
    if not lines:
        raise ValueError("the track has no length once projected")
    return MultiLineString(lines)


def _merged_track(sections) -> gpx_io.Track:
    """All sections as one Track, for framing, terrain and headline statistics."""
    have_ele = all(s.ele is not None for s in sections)
    seg = np.concatenate(
        [np.full(len(s), i, dtype=int) for i, s in enumerate(sections)]
    )
    return gpx_io.Track(
        lat=np.concatenate([s.lat for s in sections]),
        lon=np.concatenate([s.lon for s in sections]),
        ele=np.concatenate([s.ele for s in sections]) if have_ele else None,
        name=sections[0].name if sections else "",
        seg=seg,
    )


def _section_line(section, frame, simplify_mm: float) -> LineString:
    x, y = frame.to_mm(section.lat, section.lon)
    ls = LineString(np.column_stack([x, y]))
    if simplify_mm > 0:
        ls = ls.simplify(simplify_mm, preserve_topology=False)
    return ls


@dataclass
class _Part:
    """One printable trail piece: one or more sections that must stay together."""

    index: int
    sections: list
    lines: list
    polygon: object
    mesh: object = None


def _group_by_proximity(polys: list, gap_mm: float) -> list[list[int]]:
    """Group footprints that touch, overlap, or sit within `gap_mm` of each other.

    Horizontal distance is a safe stand-in for the distance between the finished
    solids: the inserts all span the same range of heights, so two that overlap in
    plan overlap in space, and two that are `d` apart in plan are at least `d` apart.
    """
    n = len(polys)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i in range(n):
        for j in range(i + 1, n):
            # distance() is 0 when the shapes intersect or merely touch.
            if polys[i].distance(polys[j]) <= gap_mm:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [groups[k] for k in sorted(groups)]


def _connect(poly, width: float, clip):
    """Join the loose parts of a merged footprint with the shortest possible bars.

    A morphological closing is not enough here. It bridges shapes that run
    alongside each other, but where two ribbon *ends* face each other across open
    ground the dilated caps meet in a thin lens that the erosion step then removes,
    leaving the "merged" piece as two separate solids. Adding an explicit bar
    between the nearest points is exact and always connects.
    """
    from shapely.ops import nearest_points

    bridges: list[float] = []
    geoms = list(getattr(poly, "geoms", [poly]))

    # Every pass welds at least one pair, so this many is already generous. The
    # bound exists so a shape nobody anticipated cannot hang the program.
    for _ in range(len(geoms) + 8):
        merged = unary_union(geoms)
        geoms = list(getattr(merged, "geoms", [merged]))
        if len(geoms) <= 1:
            return merged, bridges

        best = None
        for i in range(len(geoms)):
            for j in range(i + 1, len(geoms)):
                d = geoms[i].distance(geoms[j])
                if best is None or d < best[0]:
                    best = (d, i, j)
        d, i, j = best

        a, b = nearest_points(geoms[i], geoms[j])
        if d <= 0:
            # Touching at a single point. A union will not weld these — shapely
            # keeps them as separate polygons — so waiting for the next pass to
            # fix it loops forever. Drop a small disc over the contact instead.
            patch = a.buffer(max(width / 2.0, 1e-3), resolution=8)
        else:
            patch = LineString([a, b]).buffer(
                width / 2.0, cap_style=1, join_style=1, resolution=8
            )
            bridges.append(d)
        geoms.append(patch.intersection(clip))

    return unary_union(geoms), bridges


def _ribbon(path, width: float, clip):
    """Offset the path into a closed band of the given total width."""
    poly = path.buffer(
        width / 2.0, cap_style=2, join_style=1, resolution=8, mitre_limit=2.0
    )
    poly = unary_union(poly)
    poly = poly.intersection(clip)
    if poly.is_empty:
        raise ValueError("the trail does not overlap the map area")
    return poly


def build(cfg) -> Build:
    log = _log(cfg)
    cfg.validate()
    warnings: list[str] = []

    # ------------------------------------------------------------ input files
    pieces, file_names = gpx_io.load_pieces(cfg.gpx_paths)
    sections = chain.chain(pieces, cfg.join_distance_m)

    if len(cfg.gpx_paths) > 1 or len(sections) > 1:
        log(
            f"  {len(cfg.gpx_paths)} file(s), {len(pieces)} piece(s) -> "
            f"{len(sections)} section(s)"
        )
        for i, s in enumerate(sections, 1):
            joined = (
                f", joined at {len(s.joins)} point(s) "
                f"(largest gap {max(s.joins):.0f} m)"
                if s.joins
                else ""
            )
            log(
                f"    section {i}: {chain.length_m(s) / 1000:.1f} km "
                f"from {s.name}{joined}"
            )

    # One Track covering everything, used for framing and terrain.
    track = _merged_track(sections)
    frame = gpx_io.build_frame(track, cfg.size_mm, cfg.margin, cfg.square)
    ny, nx = _grid_shape(frame, cfg.grid)
    log(
        f"  map area: {frame.width_mm:.1f} x {frame.height_mm:.1f} mm, "
        f"DEM grid {nx} x {ny}"
    )

    # ------------------------------------------------------------- elevation
    lon_1d = np.linspace(frame.lon_min, frame.lon_max, nx)
    lat_1d = np.linspace(frame.lat_min, frame.lat_max, ny)
    lon_grid, lat_grid = np.meshgrid(lon_1d, lat_1d)

    Z_m, source = dem.elevation_grid(cfg, frame, track, lat_grid, lon_grid, log)
    Z_m = np.asarray(Z_m, dtype=float)

    if cfg.smooth > 0:
        from scipy.ndimage import gaussian_filter

        Z_m = gaussian_filter(Z_m, sigma=cfg.smooth, mode="nearest")

    z_min_m = float(np.min(Z_m))
    z_max_m = float(np.max(Z_m))
    relief_m = max(z_max_m - z_min_m, 1e-6)
    log(
        f"  elevation ({source}): {z_min_m:.0f} m to {z_max_m:.0f} m, "
        f"relief {relief_m:.0f} m"
    )

    # ------------------------------------------------- elevation to model mm
    if cfg.max_relief_mm is not None:
        relief_mm = float(cfg.max_relief_mm)
        z_gain = relief_mm / relief_m
    else:
        z_gain = frame.mm_per_m * cfg.z_scale
        relief_mm = relief_m * z_gain

    Z_mm = (Z_m - z_min_m) * z_gain + cfg.base_mm

    # X/Y of the terrain block, with the caption plinth added below it.
    x_1d = np.linspace(0.0, frame.width_mm, nx)
    y_1d = np.linspace(0.0, frame.height_mm, ny)

    # The plinth carries the caption, the scale bar and the north arrow. Any one of
    # them brings it into existence.
    wants_plinth = bool(cfg.caption) or cfg.scale_bar or cfg.north_arrow
    band = cfg.caption_height_mm if wants_plinth else 0.0
    if band > 0:
        # Two extra rows: one at the plinth's outer edge, one right beneath the
        # terrain, so the flat band cannot be tilted by the first terrain row.
        y_1d = np.concatenate([[-band, -1e-3], y_1d])
        Z_mm = np.vstack([np.full((2, nx), cfg.base_mm), Z_mm])
        ny += 2

    X, Y = np.meshgrid(x_1d, y_1d)

    log(
        f"  vertical: relief {relief_mm:.1f} mm on a {cfg.base_mm:.1f} mm base "
        f"(x{z_gain / frame.mm_per_m:.2f} exaggeration)"
    )

    # In route-only mode the surrounding landscape is dropped and the route stands
    # on a flat plate instead. Z_mm still holds the real terrain, because that is
    # what gives the route its height; only the solid underneath it changes.
    if cfg.route_only:
        Z_plate = np.full_like(Z_mm, cfg.base_mm)
        log(f"  route only: flat {cfg.base_mm:.1f} mm base, no surrounding terrain")
    else:
        Z_plate = Z_mm

    terrain = meshlib.heightfield_solid(X, Y, Z_plate, 0.0)

    # ------------------------------------------------------------ trail paths
    plate = box(0.0, 0.0, frame.width_mm, frame.height_mm)
    lines = [_section_line(s, frame, cfg.trail_simplify) for s in sections]

    keep, keep_lines, ins_polys = [], [], []
    for s, ls in zip(sections, lines):
        if ls.length <= 0:
            continue
        try:
            ins_polys.append(_ribbon(ls, cfg.trail_width, plate))
            keep.append(s)
            keep_lines.append(ls)
        except ValueError:
            warnings.append(f"section from {s.name} falls outside the map; skipped")
    if not keep:
        raise ValueError("no part of the route overlaps the map area")
    sections, lines = keep, keep_lines

    # Sections far apart at their ends can still cross, or run close enough that
    # they could not be printed or fitted as separate pieces. Anything touching or
    # within the merge distance becomes one part, bridged into a single line.
    groups = _group_by_proximity(ins_polys, cfg.merge_distance_mm)
    parts = []
    for idxs in groups:
        merged = unary_union([ins_polys[i] for i in idxs])
        if len(idxs) > 1:
            names = ", ".join(
                dict.fromkeys(n for i in idxs for n in sections[i].sources)
            )
            log(
                f"  merging {len(idxs)} sections into one line: they touch or come "
                f"within {cfg.merge_distance_mm:g} mm ({names})"
            )
            warnings.append(
                f"{len(idxs)} sections were merged into trail piece "
                f"{len(parts) + 1} because their paths cross or pass within "
                f"{cfg.merge_distance_mm:g} mm of each other"
            )
            # Bridge the sub-threshold gaps so the result really is one connected
            # line, not separate slivers sharing a file.
            merged, bridges = _connect(merged, cfg.trail_width, plate)
            if bridges:
                log(
                    f"    bridged {len(bridges)} gap(s), widest "
                    f"{max(bridges):.2f} mm"
                )
        parts.append(
            _Part(
                index=len(parts) + 1,
                sections=[sections[i] for i in idxs],
                lines=[lines[i] for i in idxs],
                polygon=merged,
            )
        )

    # Deriving the channel from the insert guarantees exactly `tolerance` of
    # clearance everywhere, including across any bridged gap.
    cut_poly = unary_union([p.polygon.buffer(cfg.tolerance, resolution=8) for p in parts])
    cut_poly = cut_poly.intersection(plate)
    path = MultiLineString(lines)

    # Terrain height along the path, used to place the channel floor.
    from scipy.interpolate import RegularGridInterpolator

    interp = RegularGridInterpolator(
        (y_1d, x_1d), Z_mm, bounds_error=False, fill_value=None
    )
    px, py = frame.to_mm(track.lat, track.lon)
    inside = (px >= 0) & (px <= frame.width_mm) & (py >= 0) & (py <= frame.height_mm)
    samp = np.column_stack([py[inside], px[inside]])
    trail_z = interp(samp)
    trail_z_min = float(np.min(trail_z))
    trail_z_max = float(np.max(trail_z))

    z_top = float(np.max(Z_mm)) + cfg.trail_proud + 10.0

    # ------------------------------------------------- channel and insert
    trail_base = cfg.trail_base
    if cfg.route_only and trail_base == "follow":
        # "follow" gives the insert a curved underside that hugged the terrain.
        # With the terrain gone there is nothing for it to hug.
        trail_base = "flat"
        warnings.append(
            "route-only mode fuses the route to its base, so --trail-base follow "
            "was ignored"
        )

    if cfg.trail_entry == "bottom" and not cfg.route_only:
        # A slot cut right through the map, so the route is pushed up from
        # underneath until its top stands proud. Its bottom finishes flush with
        # the bottom of the map.
        if trail_base == "follow":
            trail_base = "flat"
            warnings.append(
                "a route fitted from underneath has to reach the bottom of the "
                "map, so --trail-base follow was ignored"
            )
        z_floor = 0.0
        cutter = meshlib.extrude(cut_poly, height=z_top + 2.0, z0=-1.0)
        insert_blanks = [
            meshlib.extrude(pt.polygon, height=z_top + 2.0, z0=0.0) for pt in parts
        ]
        below = None
        insert_h = (trail_z_min, trail_z_max + cfg.trail_proud)
    elif cfg.route_only:
        # The route is welded to its base and printed as one object, so there is
        # no channel, no insert and no clearance to get right. Each fin simply
        # runs from the bottom of the plate up to the terrain surface, and the
        # union with the plate makes them a single solid.
        raised = meshlib.heightfield_solid(X, Y, Z_mm + cfg.trail_proud, -1.0)
        fins = []
        for i, pt in enumerate(parts, 1):
            log(f"  building route {i} of {len(parts)}")
            column = meshlib.extrude(pt.polygon, height=z_top, z0=0.0)
            fin = meshlib.boolean("intersection", [raised, column])
            fin, dropped = meshlib.drop_small_components(fin, min_volume=2.0)
            if dropped:
                warnings.append(
                    f"discarded {dropped} tiny detached fragment(s) from route {i}"
                )
            pt.mesh = fin
            fins.append(fin)

        log(f"  fusing {len(fins)} route(s) onto the base")
        map_mesh = meshlib.boolean("union", [terrain, *fins])
        trail_meshes = fins
        trail_mesh = fins[0]
        z_floor = 0.0
        insert_h = (
            trail_z_min - cfg.base_mm + cfg.trail_proud,
            trail_z_max - cfg.base_mm + cfg.trail_proud,
        )
    elif trail_base == "flat":
        z_floor = trail_z_min - cfg.trail_thickness
        if z_floor < MIN_FLOOR_MM:
            z_floor = MIN_FLOOR_MM
            warnings.append(
                f"channel floor raised to {MIN_FLOOR_MM} mm to keep material under "
                f"the slot; the insert is {trail_z_min - z_floor:.1f} mm thick at its "
                f"thinnest instead of {cfg.trail_thickness:.1f} mm. Increase --base "
                f"or reduce --trail-thickness to restore it."
            )
        cutter = meshlib.extrude(cut_poly, height=z_top - z_floor, z0=z_floor)
        insert_blanks = [
            meshlib.extrude(pt.polygon, height=z_top - z_floor, z0=z_floor)
            for pt in parts
        ]
        below = None
        insert_h = (trail_z_min - z_floor, trail_z_max - z_floor + cfg.trail_proud)
    else:
        below = meshlib.heightfield_solid(X, Y, Z_mm - cfg.trail_thickness, -5.0)
        tall_cut = meshlib.extrude(cut_poly, height=z_top + 10.0, z0=-6.0)
        cutter = meshlib.boolean("difference", [tall_cut, below])
        insert_blanks = [
            meshlib.boolean(
                "difference",
                [meshlib.extrude(pt.polygon, height=z_top + 10.0, z0=-6.0), below],
            )
            for pt in parts
        ]
        z_floor = float(trail_z_min - cfg.trail_thickness)
        insert_h = (
            cfg.trail_thickness + cfg.trail_proud,
            cfg.trail_thickness + cfg.trail_proud,
        )

    if not cfg.route_only:
        log(f"  cutting {len(parts)} trail channel(s)")
        map_mesh = meshlib.boolean("difference", [terrain, cutter])

        raised = meshlib.heightfield_solid(X, Y, Z_mm + cfg.trail_proud, -1.0)
        trail_meshes = []
        for i, blank in enumerate(insert_blanks, 1):
            log(f"  building trail insert {i} of {len(insert_blanks)}")
            m = meshlib.boolean("intersection", [raised, blank])
            # A path that wanders off the plate and back can leave detached crumbs.
            m, dropped = meshlib.drop_small_components(m, min_volume=2.0)
            if dropped:
                warnings.append(
                    f"discarded {dropped} tiny detached fragment(s) from trail {i}"
                )
            parts[i - 1].mesh = m
            trail_meshes.append(m)

        trail_mesh = trail_meshes[0]

    # ------------------------------------------- plinth: caption, scale, north
    scale_info = None
    plinth_polys = None
    if band > 0:
        W = frame.width_mm
        y_mid = -band / 2.0
        edge = band * 0.28
        features = []

        # Right end: north arrow. Left end: scale bar. Caption takes what is left.
        north_w = band * 0.60 if cfg.north_arrow else 0.0
        scale_max = min(W * 0.32, W - 2 * edge - north_w - band) if cfg.scale_bar else 0.0

        if cfg.scale_bar and scale_max > 5:
            bar, metres, drawn = legend.scale_bar(
                frame.mm_per_m, edge, y_mid, scale_max, band, cfg.caption_font
            )
            features.append(bar)
            scale_info = (metres, drawn)
            log(f"  scale bar: {legend.format_distance(metres)} = {drawn:.1f} mm")

        if cfg.north_arrow:
            features.append(
                legend.north_arrow(W - edge - north_w / 2.0, y_mid, band,
                                   cfg.caption_font)
            )
            log("  north arrow on the plinth")

        if cfg.caption:
            left = edge + (scale_info[1] if scale_info else 0.0)
            right = W - edge - north_w
            gap = band * 0.55
            avail = max(right - left - 2 * gap, W * 0.18)
            log(f"  {cfg.caption_style}ing caption {cfg.caption!r}")
            letters, _ = text3d.fit_text(
                cfg.caption,
                box_w=avail,
                box_h=band * cfg.caption_size,
                font_path=cfg.caption_font,
            )
            from shapely import affinity

            features.append(affinity.translate(letters, (left + right) / 2.0, y_mid))

        if features:
            merged = unary_union(features)
            plinth_polys = merged
            overlap = max(cfg.caption_depth * 0.5, 0.4)
            if cfg.caption_style == "emboss":
                solid = meshlib.extrude(
                    merged, height=cfg.caption_depth + overlap,
                    z0=cfg.base_mm - overlap,
                )
                map_mesh = meshlib.boolean("union", [map_mesh, solid])
            else:
                solid = meshlib.extrude(
                    merged, height=cfg.caption_depth + overlap,
                    z0=cfg.base_mm - cfg.caption_depth,
                )
                map_mesh = meshlib.boolean("difference", [map_mesh, solid])

    # ------------------------------------------- credit on the underside
    credit_text, credit_short = dem.engraved_credit_for(source)
    credit_lines: list[str] = []
    if cfg.credit:
        box_w = frame.width_mm * 0.86
        if band > 0:
            box_h = band * 0.72
            cy = -band / 2.0
        else:
            box_h = min(frame.height_mm * 0.24, 16.0)
            cy = frame.height_mm * 0.18
        try:
            letters, credit_lines, cap = text3d.underside_text(
                credit_text,
                centre_xy=(frame.width_mm / 2.0, cy),
                box_w=box_w,
                box_h=box_h,
                depth=cfg.credit_depth,
                font_path=cfg.caption_font,
                fallback=credit_short,
            )
            log(
                f"  engraving the data credit underneath "
                f"({len(credit_lines)} lines, {cap:.1f} mm tall)"
            )
            map_mesh = meshlib.boolean("difference", [map_mesh, letters])
            if cap < 2.4:
                warnings.append(
                    f"the underside credit is only {cap:.1f} mm tall, which a 0.4 mm "
                    f"nozzle may not cut legibly. The map is small; consider a bigger "
                    f"--size, or --no-credit and credit the terrain data another way."
                )
        except Exception as exc:  # noqa: BLE001 - never lose the model over a label
            warnings.append(f"could not engrave the underside credit: {exc}")

    if cfg.trail_entry == "bottom" and not cfg.route_only:
        # The through-slot may have divided the map. Every surviving piece is
        # wanted: a route that closes on itself leaves an island of land inside
        # the loop, and that island is part of the finished thing.
        map_meshes, crumbs = meshlib.split_components(map_mesh, min_volume=2.0)
        if crumbs:
            warnings.append(f"discarded {crumbs} tiny detached fragment(s) of the map")
        if len(map_meshes) > 1:
            log(f"  the slot divides the map into {len(map_meshes)} piece(s)")
            warnings.append(
                f"the route closes on itself or crosses the map, so the map comes "
                f"in {len(map_meshes)} pieces. The trail holds them together once "
                f"fitted; print them all."
            )
        map_mesh = map_meshes[0]
    else:
        map_mesh = meshlib.largest_component(map_mesh)
        map_meshes = [map_mesh]

    # ------------------------------------------------------------------ stats
    length_m = gpx_io.track_length_m(track)
    gain = 0.0
    if track.ele is not None and len(track.ele) > 1:
        d = np.diff(track.ele)
        gain = float(np.sum(d[d > 0]))

    tb = trail_mesh.bounds
    mb = map_mesh.bounds
    section_stats = []
    for pt in parts:
        sb = pt.mesh.bounds
        srcs = list(dict.fromkeys(n for sec in pt.sections for n in sec.sources))
        section_stats.append({
            "index": pt.index,
            "name": pt.sections[0].name,
            "sources": srcs,
            "merged_sections": len(pt.sections),
            "length_km": sum(chain.length_m(sec) for sec in pt.sections) / 1000.0,
            "joins": sum(len(sec.joins) for sec in pt.sections),
            "size_mm": (
                float(sb[1][0] - sb[0][0]),
                float(sb[1][1] - sb[0][1]),
                float(sb[1][2] - sb[0][2]),
            ),
            "faces": int(len(pt.mesh.faces)),
            "watertight": bool(pt.mesh.is_watertight),
        })
    stats = {
        "track_name": track.name,
        "points": len(track),
        "length_km": length_m / 1000.0,
        "ascent_m": gain,
        "elev_min_m": z_min_m,
        "elev_max_m": z_max_m,
        "relief_m": relief_m,
        "relief_mm": relief_mm,
        "z_exaggeration": z_gain / frame.mm_per_m,
        "scale_denominator": 1000.0 / frame.mm_per_m,
        "files": file_names,
        "sections": section_stats,
        "n_sections": len(parts),
        "n_raw_sections": len(sections),
        "merge_distance_mm": cfg.merge_distance_mm,
        "join_distance_m": cfg.join_distance_m,
        "route_only": cfg.route_only,
        "trail_entry": cfg.trail_entry,
        "n_map_parts": len(map_meshes),
        "dem_source": source,
        "attribution": dem.attribution_for(source),
        "engraved_credit": credit_lines if cfg.credit else [],
        "map_size_mm": (
            float(mb[1][0] - mb[0][0]),
            float(mb[1][1] - mb[0][1]),
            float(mb[1][2] - mb[0][2]),
        ),
        "trail_size_mm": (
            float(tb[1][0] - tb[0][0]),
            float(tb[1][1] - tb[0][1]),
            float(tb[1][2] - tb[0][2]),
        ),
        "insert_thickness_mm": insert_h,
        "scale_bar": scale_info,
        "channel_width_mm": cfg.trail_width + 2.0 * cfg.tolerance,
        "insert_width_mm": cfg.trail_width,
        "total_clearance_mm": 2.0 * cfg.tolerance,
        "channel_floor_z": z_floor,
        "map_health": meshlib.health(map_mesh),
        "trail_health": meshlib.health(trail_mesh),
    }

    if not map_mesh.is_watertight:
        warnings.append("the map mesh is not watertight; check it before printing")
    for st_ in section_stats:
        if not st_["watertight"]:
            warnings.append(
                f"trail piece {st_['index']} is not watertight; check before printing"
            )
    if cfg.trail_width < 1.2:
        warnings.append(
            f"the trail line is only {cfg.trail_width:.1f} mm wide, which is fragile "
            f"to print and easy to snap; raise --trail-width"
        )

    tall = float(tb[1][2] - tb[0][2])
    if trail_base == "flat" and not cfg.route_only and tall > 15 * cfg.trail_width:
        warnings.append(
            f"the insert stands {tall:.0f} mm tall but is only "
            f"{cfg.trail_width:.1f} mm wide, "
            f"because the route climbs the full relief of the map. Lower "
            f"--z-scale or --max-relief, or use --trail-base follow for a thin "
            f"ribbon that needs support instead."
        )
    if cfg.trail_base == "follow":
        warnings.append(
            "--trail-base follow gives the insert a curved underside; print it "
            "with supports"
        )

    return Build(
        map_mesh=map_mesh,
        trail_mesh=trail_mesh,
        map_meshes=map_meshes,
        trail_meshes=trail_meshes,
        sections=sections,
        section_lines=lines,
        parts=parts,
        frame=frame,
        track=track,
        X=X,
        Y=Y,
        Z_mm=Z_mm,
        Z_m=Z_m,
        path_mm=path,
        plinth_polys=plinth_polys,
        band_mm=band,
        stats=stats,
        warnings=warnings,
    )
