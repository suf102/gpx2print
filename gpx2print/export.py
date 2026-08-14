"""Writing finished parts to disk, shared by the CLI and the GUI."""

from __future__ import annotations

from pathlib import Path

from .threemf import write_3mf


def to_origin(mesh):
    """Offset that drops a part onto the bed with its corner at the origin."""
    lo = mesh.bounds[0]
    return (-float(lo[0]), -float(lo[1]), -float(lo[2]))


TRAIL_PALETTE = (
    "#D6482B",  # red
    "#2F6FA8",  # blue
    "#E0A32E",  # amber
    "#4F8C52",  # green
    "#8B5CA8",  # violet
    "#3FA6A0",  # teal
)


def trail_colors(base: str, count: int) -> list[str]:
    """One colour per section: the chosen colour first, then a distinct palette."""
    if count <= 1:
        return [base]
    out = [base]
    for c in TRAIL_PALETTE:
        if len(out) >= count:
            break
        if c.lower() != base.lower():
            out.append(c)
    while len(out) < count:
        out.append(TRAIL_PALETTE[len(out) % len(TRAIL_PALETTE)])
    return out[:count]


def part_paths(out_path: str, n_trails: int = 1, route_only: bool = False):
    """<name>.3mf becomes <name>_map.3mf plus one file per trail section.

    With no landscape on it the plate is a base, not a map, so it is named as one.
    """
    stem = Path(out_path).with_suffix("")
    plate = f"{stem}_base.3mf" if route_only else f"{stem}_map.3mf"
    if n_trails <= 1:
        return plate, [f"{stem}_trail.3mf"]
    return plate, [f"{stem}_trail{i}.3mf" for i in range(1, n_trails + 1)]


def ensure_dir(path: str) -> str:
    p = Path(path).expanduser()
    if str(p.parent):
        p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def layout_offsets(b, layout: str):
    """Where each part sits when both are written into one combined file."""
    if layout == "assembled":
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)

    mb = b.map_mesh.bounds
    tb = b.trail_mesh.bounds
    gap = 8.0

    map_off = to_origin(b.map_mesh)
    mw = float(mb[1][0] - mb[0][0])
    mh = float(mb[1][1] - mb[0][1])
    tw = float(tb[1][0] - tb[0][0])
    th = float(tb[1][1] - tb[0][1])

    # Put the insert wherever it keeps the overall footprint squarest, so the
    # pair is more likely to fit on one plate.
    beside = (max(mw + gap + tw, mh), max(mw, mh + gap + th))
    if beside[0] <= beside[1]:
        trail_off = (mw + gap - float(tb[0][0]), -float(tb[0][1]), -float(tb[0][2]))
    else:
        trail_off = (-float(tb[0][0]), mh + gap - float(tb[0][1]), -float(tb[0][2]))
    return map_off, trail_off


def verify(path: str) -> tuple[bool, str]:
    """Reload a written file and check it is still a printable solid.

    The file is the deliverable, not the mesh in memory, so it is worth paying a
    second to confirm the two agree.
    """
    try:
        import trimesh

        scene = trimesh.load(path)
        meshes = list(scene.geometry.values()) if hasattr(scene, "geometry") else [scene]
        if not meshes:
            return False, "no geometry found in the file"
        bad = [m for m in meshes if not m.is_watertight]
        if bad:
            holes = sum(len(trimesh.repair.broken_faces(m)) for m in bad)
            return False, f"reloaded mesh is not watertight ({holes} broken faces)"
        return True, "watertight"
    except Exception as exc:  # noqa: BLE001
        return False, f"could not be re-read: {exc}"


def export_parts(
    b,
    cfg,
    out_path: str,
    layout: str = "separate",
    combined: bool = False,
    stl: bool = False,
    log=print,
    check: bool = True,
    settings_file: bool = True,
    preview: str | None = None,
) -> list[str]:
    """Write one 3MF per printable part. Returns the paths written."""
    out_path = ensure_dir(out_path)
    title = b.stats["track_name"] or Path(cfg.gpx_path).stem
    desc = (
        f"{b.stats['length_km']:.1f} km, "
        f"{b.stats['ascent_m']:.0f} m ascent, "
        f"1:{b.stats['scale_denominator']:,.0f}"
    )

    # The credit travels with the model, so it survives being shared or re-uploaded.
    credit = b.stats.get("attribution", "")
    common = {"Description": desc, "Copyright": credit, "LicenseTerms": credit}

    keep = layout == "assembled"
    map_only = bool(b.stats.get("map_only"))
    trails = [] if map_only else (b.trail_meshes or [b.trail_mesh])
    route_only = bool(b.stats.get("route_only"))
    written: list[str] = []

    stem = Path(out_path).with_suffix("")
    maps = b.map_meshes or [b.map_mesh]
    tiled = int(b.stats.get("n_tiles") or 0) > 1

    if tiled:
        # A tessellated plate is a set of equal objects rather than one object
        # with afterthoughts, so they are numbered plainly and none is "the map".
        jobs = [
            (f"{stem}_tile{i}.3mf", m, f"Tile {i} of {len(maps)}", cfg.map_color)
            for i, m in enumerate(maps, 1)
        ]
    elif map_only or route_only:
        # Nothing to fit together and nothing to keep in register, so one object
        # in one file, named for what it actually is.
        jobs = [(out_path, b.map_mesh, "Map" if map_only else "Route",
                 cfg.map_color)]
    elif len(maps) == 1:
        jobs = [(part_paths(out_path, len(trails), route_only)[0], maps[0],
                 "Map", cfg.map_color)]
    else:
        # A slot cut right through can leave the map in several pieces.
        jobs = [
            (f"{stem}_map{i}.3mf", m,
             f"Map {i}" if i > 1 else "Map 1 (largest)", cfg.map_color)
            for i, m in enumerate(maps, 1)
        ]

    colors = trail_colors(cfg.trail_color, max(len(trails), 1))
    if not map_only and not route_only:
        _, trail_paths = part_paths(out_path, len(trails), route_only)
        for i, (path, mesh) in enumerate(zip(trail_paths, trails)):
            name = "Trail" if len(trails) == 1 else f"Trail {i + 1}"
            jobs.append((path, mesh, name, colors[i]))

    # The caption strip, when it is a part of its own. It carries the caption,
    # the scale bar and the arrow, which is the whole reason for separating it,
    # so it is listed last: it is the one you load the second colour for.
    if b.strip_mesh is not None:
        jobs.append(
            (f"{Path(out_path).with_suffix('')}_strip.3mf", b.strip_mesh,
             "Caption strip", cfg.map_color)
        )

    for path, mesh, name, color in jobs:
        write_3mf(
            path,
            [
                {
                    "mesh": mesh,
                    "name": name,
                    "color": color,
                    "offset": None if keep else to_origin(mesh),
                }
            ],
            metadata={"Title": f"{title} — {name}", **common},
        )
        written.append(path)
        note = ""
        if check:
            ok, why = verify(path)
            if not ok:
                note = f"  ** CHECK FAILED: {why} **"
                b.warnings.append(f"{Path(path).name}: {why}")
        log(f"wrote {path} ({Path(path).stat().st_size / 1024:,.0f} kB){note}")

    if combined and tiled:
        # There is no single map object left to pair the insert with.
        log("skipping --combined: the map is in tiles, so there is nothing to "
            "put side by side")
    elif combined and not route_only and not map_only:
        map_off, trail_off = layout_offsets(b, layout)
        parts = [
            {
                "mesh": b.map_mesh,
                "name": "Map",
                "color": cfg.map_color,
                "offset": map_off,
            }
        ]
        # Stack the sections beside the map, each clear of the last.
        cursor = 0.0
        for i, mesh in enumerate(trails):
            if keep:
                off = (0.0, 0.0, 0.0)
            else:
                bb = mesh.bounds
                off = (
                    trail_off[0] + cursor,
                    trail_off[1],
                    trail_off[2] + float(b.trail_mesh.bounds[0][2] - bb[0][2]),
                )
                cursor += float(bb[1][0] - bb[0][0]) + 8.0
            parts.append(
                {
                    "mesh": mesh,
                    "name": "Trail" if len(trails) == 1 else f"Trail {i + 1}",
                    "color": colors[i],
                    "offset": off,
                }
            )
        write_3mf(out_path, parts, metadata={"Title": title, **common})
        written.append(out_path)
        log(f"wrote {out_path} ({Path(out_path).stat().st_size / 1024:,.0f} kB, all)")

    if stl:
        stem = str(Path(out_path).with_suffix(""))
        if tiled:
            items = [(f"_tile{i}.stl", m) for i, m in enumerate(maps, 1)]
        elif route_only or map_only:
            items = [(".stl", b.map_mesh)]
        else:
            items = [("_map.stl", b.map_mesh)]
        if not route_only and not map_only:
            for i, mesh in enumerate(trails):
                suffix = "_trail.stl" if len(trails) == 1 else f"_trail{i + 1}.stl"
                items.append((suffix, mesh))
        if b.strip_mesh is not None:
            items.append(("_strip.stl", b.strip_mesh))
        for suffix, mesh in items:
            out = mesh if keep else mesh.copy()
            if not keep:
                out.apply_translation(to_origin(mesh))
            out.export(stem + suffix)
            written.append(stem + suffix)
            log(f"wrote {stem + suffix}")

    if settings_file:
        from . import manifest

        path = f"{Path(out_path).with_suffix('')}_settings.txt"
        manifest.write(
            path, b, cfg, list(written), out_path,
            combined=combined, stl=stl, layout=layout, preview=preview,
        )
        written.append(path)
        log(f"wrote {path}")

    return written
