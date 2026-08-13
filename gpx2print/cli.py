"""Command line interface."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .config import Config

DESCRIPTION = """\
Turn a GPX track into a 3D-printable topographic map in two parts:
a terrain plate with a channel cut along the route, and a separate insert that
drops into that channel so the trail can be printed in its own colour.
"""

EPILOG = """\
One file is written per print: <name>_map.3mf and <name>_trail.3mf. Give several GPX
files and legs that meet end to end are joined; the rest become <name>_trail1.3mf,
<name>_trail2.3mf, ... each printable in its own colour.

examples:
  gpx2print walk.gpx
  gpx2print day1.gpx day2.gpx day3.gpx -o trip.3mf --caption "Cape Wrath Trail"
  gpx2print walk.gpx -o walk.3mf --size 180 --z-scale 2.5 --tolerance 0.25
  gpx2print walk.gpx --caption "Ben Nevis · 12 May 2026" --preview walk.png
  gpx2print walk.gpx --dry-run --preview walk.png      # preview only, no meshes
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gpx2print",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    d = Config()

    p.add_argument("gpx", nargs="+", metavar="GPX",
                   help="one or more .gpx files. Pieces whose ends meet "
                        "are joined; the rest become separate trail parts")
    p.add_argument(
        "-o",
        "--out",
        default=None,
        metavar="NAME.3mf",
        help="base name for the output. Two files are written: NAME_map.3mf and "
             "NAME_trail.3mf (default: from the gpx filename)",
    )
    p.add_argument(
        "--preview",
        nargs="?",
        const="auto",
        default=None,
        metavar="PNG",
        help="write a preview image (defaults to <out>.png)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="stop after the preview; skip mesh building and export",
    )
    p.add_argument("--stl", action="store_true", help="also write two .stl files")

    g = p.add_argument_group("size and shape")
    g.add_argument("--size", type=float, default=d.size_mm,
                   help=f"longest edge of the map in mm (default: {d.size_mm:g})")
    g.add_argument("--scale", type=float, default=None, metavar="N",
                   help="set the map scale as the N in 1:N, e.g. 50000 for "
                        "1:50,000. The plate then comes out whatever size the "
                        "route needs and --size is ignored")
    g.add_argument("--altitude-offset", type=float, default=d.altitude_offset_m,
                   metavar="M",
                   help=f"move the altitude the relief is measured from, in "
                        f"metres. Positive flattens ground below it onto the "
                        f"base; negative lifts the whole landscape "
                        f"(default: {d.altitude_offset_m:g})")
    g.add_argument("--join-distance", type=float, default=d.join_distance_m,
                   metavar="M",
                   help=f"how close two ends must be to be joined into one path, "
                        f"in metres (default: {d.join_distance_m:g})")
    g.add_argument("--merge-distance", type=float, default=d.merge_distance_mm,
                   metavar="MM",
                   help=f"trail sections that cross, or come this close on the "
                        f"print, are merged into one piece (default: "
                        f"{d.merge_distance_mm:g})")
    g.add_argument("--margin", type=float, default=d.margin,
                   help=f"terrain padding around the track, as a fraction of its "
                        f"extent (default: {d.margin:g})")
    g.add_argument("--route-only", action="store_true",
                   help="leave out the surrounding landscape: the route stands on "
                        "a flat base carrying the caption, scale bar and north "
                        "arrow. The route still follows real terrain height")
    g.add_argument("--shape", choices=("rectangle","square","circle","triangle",
                                      "pentagon","hexagon","octagon"),
                   default=d.shape,
                   help=f"outline of the map plate. Anything other than a "
                        f"rectangle is grown to hold the whole route, then scaled "
                        f"so the longest edge is still --size "
                        f"(default: {d.shape})")
    g.add_argument("--caption-position", choices=("bottom","top"),
                   default=d.caption_position,
                   help=f"which side the caption strip sits on "
                        f"(default: {d.caption_position})")
    g.add_argument("--square", action="store_true",
                   help="force a square footprint")
    g.add_argument("--z-scale", type=float, default=d.z_scale,
                   help=f"vertical exaggeration (default: {d.z_scale:g})")
    g.add_argument("--max-relief", type=float, default=None, metavar="MM",
                   help="scale terrain to exactly this relief in mm, "
                        "overriding --z-scale")
    g.add_argument("--base", type=float, default=d.base_mm,
                   help=f"solid base under the lowest terrain, mm "
                        f"(default: {d.base_mm:g})")

    g = p.add_argument_group("the fit between the two parts")
    g.add_argument("--tolerance", type=float, default=d.tolerance,
                   help=f"clearance per side, mm; the total gap is twice this. "
                        f"0.1-0.15 for a finely tuned printer, 0.3 for a typical "
                        f"one, 0.5-0.9 if parts usually come out tight "
                        f"(default: {d.tolerance:g})")
    g.add_argument("--trail-width", type=float, default=d.trail_width,
                   metavar="MM",
                   help=f"width of the printed trail line, mm. The channel is "
                        f"widened from this by the tolerance "
                        f"(default: {d.trail_width:g})")
    g.add_argument("--trail-thickness", type=float, default=d.trail_thickness,
                   help=f"minimum thickness of the insert, mm "
                        f"(default: {d.trail_thickness:g})")
    g.add_argument("--trail-proud", type=float, default=d.trail_proud,
                   help=f"how far the trail stands above the terrain, mm "
                        f"(default: {d.trail_proud:g})")
    g.add_argument("--trail-entry", choices=("top", "bottom"), default=d.trail_entry,
                   help="top: the route drops into a slot cut from above. bottom: "
                        "the slot goes right through and the route is pushed up "
                        "from underneath. A looping route then splits the map into "
                        f"several pieces (default: {d.trail_entry})")
    g.add_argument("--trail-base", choices=("flat", "follow"), default=d.trail_base,
                   help="flat: insert has a flat bottom and needs no support. "
                        "follow: constant thickness, more compact, needs support "
                        f"(default: {d.trail_base})")

    g = p.add_argument_group("terrain data")
    g.add_argument("--grid", type=int, default=d.grid,
                   help=f"DEM samples along the longest edge (default: {d.grid})")
    g.add_argument("--smooth", type=float, default=d.smooth,
                   help=f"gaussian smoothing in grid cells (default: {d.smooth:g})")
    g.add_argument("--dem-source",
                   choices=("terrarium", "opentopodata", "gpx", "flat"),
                   default=d.dem_source,
                   help=f"elevation source (default: {d.dem_source})")
    g.add_argument("--dem-zoom", type=int, default=None,
                   help="force a terrain tile zoom level")
    g.add_argument("--cache-dir", default=None, help="where to cache terrain tiles")

    g = p.add_argument_group("caption")
    g.add_argument("--caption", default=None,
                   help="text embossed on a plinth below the map")
    g.add_argument("--caption-height", type=float, default=d.caption_height_mm,
                   metavar="MM",
                   help=f"height of the caption band, mm "
                        f"(default: {d.caption_height_mm:g})")
    g.add_argument("--caption-size", type=float, default=d.caption_size,
                   help=f"text height as a fraction of the band "
                        f"(default: {d.caption_size:g})")
    g.add_argument("--caption-depth", type=float, default=d.caption_depth,
                   metavar="MM",
                   help=f"emboss height or engrave depth, mm "
                        f"(default: {d.caption_depth:g})")
    g.add_argument("--caption-style", choices=("emboss", "deboss"),
                   default=d.caption_style,
                   help=f"deboss cuts the lettering into the plinth, emboss raises "
                        f"it. Engraved usually prints more cleanly and applies to "
                        f"the scale bar and north arrow too "
                        f"(default: {d.caption_style})")
    g.add_argument("--caption-font", default=None, help="path to a .ttf or .otf font")
    g.add_argument("--no-scale-bar", dest="scale_bar", action="store_false",
                   help="omit the distance scale from the plinth")
    g.add_argument("--no-north-arrow", dest="north_arrow", action="store_false",
                   help="omit the north arrow from the plinth")
    g.add_argument("--no-credit", dest="credit", action="store_false",
                   help="omit the terrain-data credit engraved under the map. The "
                        "data licence still requires attribution, so credit it "
                        "another way if you share the model")
    g.add_argument("--credit-height", type=float, default=d.credit_height_mm,
                   metavar="MM",
                   help=f"cap height of the underside credit "
                        f"(default: {d.credit_height_mm:g})")

    g = p.add_argument_group("output")
    g.add_argument("--no-settings-file", dest="settings_file", action="store_false",
                   help="skip the _settings.txt record of how the files were made")
    g.add_argument("--combined", action="store_true",
                   help="also write a single .3mf holding both parts side by side")
    g.add_argument("--layout", choices=("separate", "assembled"), default="separate",
                   help="separate: each part sits on the bed at the origin, ready to "
                        "print. assembled: parts keep their true positions, so "
                        "loading both together shows them interlocked "
                        "(default: separate)")
    g.add_argument("--map-color", default=d.map_color, help="map colour in the 3MF")
    g.add_argument("--trail-color", default=d.trail_color,
                   help="trail colour in the 3MF")
    g.add_argument("-q", "--quiet", action="store_true")

    return p


def args_to_config(a) -> Config:
    out = a.out or str(Path(a.gpx[0]).with_suffix(".3mf"))
    preview = a.preview
    if preview == "auto":
        preview = str(Path(out).with_suffix(".png"))

    return Config(
        gpx_paths=list(a.gpx),
        out_path=out,
        preview_path=preview,
        join_distance_m=a.join_distance,
        merge_distance_mm=a.merge_distance,
        size_mm=a.size,
        scale_denominator=a.scale,
        altitude_offset_m=a.altitude_offset,
        margin=a.margin,
        shape=a.shape,
        caption_position=a.caption_position,
        square=a.square,
        route_only=a.route_only,
        z_scale=a.z_scale,
        max_relief_mm=a.max_relief,
        base_mm=a.base,
        grid=a.grid,
        smooth=a.smooth,
        dem_source=a.dem_source,
        dem_zoom=a.dem_zoom,
        trail_width=a.trail_width,
        tolerance=a.tolerance,
        trail_thickness=a.trail_thickness,
        trail_proud=a.trail_proud,
        trail_entry=a.trail_entry,
        trail_base=a.trail_base,
        caption=a.caption,
        caption_height_mm=a.caption_height,
        caption_size=a.caption_size,
        caption_depth=a.caption_depth,
        caption_style=a.caption_style,
        caption_font=a.caption_font,
        credit=a.credit,
        credit_height_mm=a.credit_height,
        scale_bar=a.scale_bar,
        north_arrow=a.north_arrow,
        map_color=a.map_color,
        trail_color=a.trail_color,
        cache_dir=a.cache_dir,
        verbose=not a.quiet,
    )


from .export import ensure_dir as _ensure_dir  # noqa: E402


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    cfg = args_to_config(a)

    cfg.gpx_paths = [str(Path(p).expanduser()) for p in cfg.gpx_paths]
    cfg.gpx_path = cfg.gpx_paths[0]
    for p in cfg.gpx_paths:
        if not Path(p).is_file():
            print(f"gpx2print: no such file: {p}", file=sys.stderr)
            return 2

    cfg.out_path = _ensure_dir(cfg.out_path)
    if cfg.preview_path:
        cfg.preview_path = _ensure_dir(cfg.preview_path)

    log = print if cfg.verbose else (lambda *_a, **_k: None)
    t0 = time.time()

    try:
        from .build import build

        log(f"reading {cfg.gpx_path}")
        b = build(cfg)

        if cfg.preview_path:
            from .preview import render

            log(f"rendering preview -> {cfg.preview_path}")
            render(b, cfg, cfg.preview_path)

        if not a.dry_run:
            from .export import export_parts

            export_parts(
                b,
                cfg,
                cfg.out_path,
                layout=a.layout,
                combined=a.combined,
                stl=a.stl,
                log=log,
                settings_file=a.settings_file,
                preview=cfg.preview_path,
            )

    except Exception as exc:  # noqa: BLE001 - the CLI reports rather than traces
        print(f"gpx2print: {exc}", file=sys.stderr)
        if not cfg.verbose:
            return 1
        import traceback

        traceback.print_exc()
        return 1

    if cfg.verbose:
        _report(b, cfg, time.time() - t0)
    return 0


def _report(b, cfg, secs):
    s = b.stats
    print()
    print(f"  {'route':<20}{s['track_name'] or '(unnamed)'}")
    print(f"  {'length':<20}{s['length_km']:.2f} km, {s['ascent_m']:.0f} m ascent")
    print(f"  {'scale':<20}1:{s['scale_denominator']:,.0f}, "
          f"vertical x{s['z_exaggeration']:.2f}")
    label = "one object" if s.get("route_only") else "map part"
    print(f"  {label:<20}"
          f"{s['map_size_mm'][0]:.1f} x {s['map_size_mm'][1]:.1f} "
          f"x {s['map_size_mm'][2]:.1f} mm, {s['map_health']['faces']:,} faces"
          + (f", {s['map_health']['bodies']} connected piece(s)"
             if s.get("route_only") else ""))

    if s.get("n_map_parts", 1) > 1:
        print(f"  {'map pieces':<20}{s['n_map_parts']} — the route cuts the map "
              f"apart; print them all")
    pieces = [] if s.get("route_only") else (s.get("sections") or [])
    if len(pieces) > 1:
        print(f"  {'trail parts':<20}{len(pieces)} separate pieces "
              f"(joined within {s['join_distance_m']:.0f} m)")
        for sec in pieces:
            src = ", ".join(sec["sources"])
            joins = f", {sec['joins']} join(s)" if sec["joins"] else ""
            if sec.get("merged_sections", 1) > 1:
                joins += f", {sec['merged_sections']} routes merged"
            print(f"    {'part ' + str(sec['index']):<18}"
                  f"{sec['size_mm'][0]:.1f} x {sec['size_mm'][1]:.1f} x "
                  f"{sec['size_mm'][2]:.1f} mm, {sec['length_km']:.1f} km"
                  f"  [{src}{joins}]")
    elif not s.get("route_only"):
        print(f"  {'trail part':<20}{s['trail_size_mm'][0]:.1f} x "
              f"{s['trail_size_mm'][1]:.1f} x {s['trail_size_mm'][2]:.1f} mm, "
              f"{s['trail_health']['faces']:,} faces")
    if not s.get("route_only"):
        print(f"  {'fit':<20}channel {s['channel_width_mm']:.2f} mm, insert "
          f"{s['insert_width_mm']:.2f} mm, {s['total_clearance_mm']:.2f} mm total "
          f"clearance")
    if s.get("route_only"):
        print(f"  {'watertight':<20}{s['map_health']['watertight']}")
    else:
        print(f"  {'watertight':<20}map {s['map_health']['watertight']}, "
              f"trail {s['trail_health']['watertight']}")
    for w in b.warnings:
        print(f"  ! {w}")
    print(f"\n  {s['attribution']}")
    print(f"\n  done in {secs:.1f}s")


if __name__ == "__main__":
    raise SystemExit(main())
