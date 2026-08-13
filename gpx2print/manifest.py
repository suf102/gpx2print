"""A plain-text record of how a set of files was made.

Written next to the models so that months later, with no memory of what was typed,
the same prints can be made again. It holds a literal command line rather than a
prose description, and it spells out every setting rather than relying on defaults,
because defaults change between versions and a command that leans on them will
quietly produce something different.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import shlex
import sys
from pathlib import Path

WIDTH = 78


def _sha256(path: str, limit: int = 16) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return "unreadable"
    return h.hexdigest()[:limit]


def _rule(title: str = "") -> str:
    if not title:
        return "-" * WIDTH
    return f"{title}  " + "-" * max(WIDTH - len(title) - 2, 0)


def command_line(cfg, out_path: str, combined=False, stl=False,
                 layout="separate", preview: str | None = None) -> list[str]:
    """The full command that reproduces this build, as argv pieces.

    Every value option is written out even when it matches the current default, so
    the command keeps meaning if a later version changes those defaults.
    """
    argv: list[str] = ["gpx2print"]
    argv += [str(p) for p in cfg.gpx_paths]
    argv += ["-o", str(out_path)]

    if preview:
        argv += ["--preview", str(preview)]
    if stl:
        argv += ["--stl"]
    if combined:
        argv += ["--combined"]
    if layout != "separate":
        argv += ["--layout", layout]

    argv += [
        "--size", f"{cfg.size_mm:g}",
        "--margin", f"{cfg.margin:g}",
        "--base", f"{cfg.base_mm:g}",
        "--grid", f"{cfg.grid:d}",
        "--smooth", f"{cfg.smooth:g}",
        "--dem-source", cfg.dem_source,
        "--trail-width", f"{cfg.trail_width:g}",
        "--trail-thickness", f"{cfg.trail_thickness:g}",
        "--trail-proud", f"{cfg.trail_proud:g}",
        "--trail-base", cfg.trail_base,
        "--tolerance", f"{cfg.tolerance:g}",
        "--join-distance", f"{cfg.join_distance_m:g}",
        "--merge-distance", f"{cfg.merge_distance_mm:g}",
    ]

    # Vertical scale is either an exaggeration or a fixed relief, never both.
    if cfg.max_relief_mm is not None:
        argv += ["--max-relief", f"{cfg.max_relief_mm:g}"]
    else:
        argv += ["--z-scale", f"{cfg.z_scale:g}"]

    if cfg.square:
        argv += ["--square"]
    if cfg.route_only:
        argv += ["--route-only"]
    if cfg.dem_zoom is not None:
        argv += ["--dem-zoom", str(cfg.dem_zoom)]
    if cfg.cache_dir:
        argv += ["--cache-dir", str(cfg.cache_dir)]

    if cfg.caption:
        argv += [
            "--caption", cfg.caption,
            "--caption-height", f"{cfg.caption_height_mm:g}",
            "--caption-size", f"{cfg.caption_size:g}",
            "--caption-depth", f"{cfg.caption_depth:g}",
            "--caption-style", cfg.caption_style,
        ]
    else:
        argv += ["--caption-style", cfg.caption_style]
    if cfg.caption_font:
        argv += ["--caption-font", str(cfg.caption_font)]

    # These are on by default, so they only appear when switched off.
    if not cfg.scale_bar:
        argv += ["--no-scale-bar"]
    if not cfg.north_arrow:
        argv += ["--no-north-arrow"]
    if not cfg.credit:
        argv += ["--no-credit"]
    else:
        argv += ["--credit-height", f"{cfg.credit_height_mm:g}"]

    return argv


def _wrap_command(argv: list[str]) -> str:
    """One argument per continuation line once it stops fitting on one."""
    quoted = [shlex.quote(a) for a in argv]
    line = " ".join(quoted)
    if len(line) <= WIDTH - 4:
        return "  " + line

    out, current = [], "  " + quoted[0]
    for piece in quoted[1:]:
        # Keep a flag and its value together on the same line.
        if piece.startswith("--") or len(current) + len(piece) + 1 > WIDTH - 6:
            out.append(current + " \\")
            current = "    " + piece
        else:
            current += " " + piece
    out.append(current)
    return "\n".join(out)


def render(b, cfg, written: list[str], out_path: str, combined=False, stl=False,
           layout="separate", preview: str | None = None) -> str:
    from . import __version__

    s = b.stats
    now = dt.datetime.now().astimezone()
    argv = command_line(cfg, out_path, combined, stl, layout, preview)

    L: list[str] = []
    add = L.append

    add(f"gpx2print {__version__} - build settings")
    add("=" * WIDTH)
    add(f"Written {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    add(f"Python  {sys.version.split()[0]} on {sys.platform}")
    add("")
    add("This file records everything used to produce the models beside it.")
    add("")

    add(_rule("TO MAKE THESE FILES AGAIN"))
    add("")
    add(_wrap_command(argv))
    add("")
    add("Every setting is written out in full, including ones that happen to match")
    add("today's defaults, so this command keeps its meaning in later versions.")
    add("")
    add("Running from the source folder instead of an installed copy? Replace the")
    add("leading 'gpx2print' with 'python3 -m gpx2print'.")
    add("")

    add(_rule("INPUT"))
    add("")
    for p in cfg.gpx_paths:
        name = Path(p).name
        size = Path(p).stat().st_size if Path(p).exists() else 0
        add(f"  {name}")
        add(f"      {size:,} bytes    sha256 {_sha256(p)}")
    add("")
    add("  The checksums identify the exact track files. Different checksums mean")
    add("  different input, and the models will not match however the settings are set.")
    add("")

    add(_rule("SETTINGS"))
    add("")
    rows = [
        ("Overall size", f"{cfg.size_mm:g} mm along the longest edge"),
        ("Land around the route", f"{cfg.margin:g} of the track's extent"),
        ("Square footprint", "yes" if cfg.square else "no"),
        ("Route only, no landscape", "yes" if cfg.route_only else "no"),
        ("Vertical",
         f"relief forced to {cfg.max_relief_mm:g} mm"
         if cfg.max_relief_mm is not None else f"exaggeration x{cfg.z_scale:g}"),
        ("Base thickness", f"{cfg.base_mm:g} mm"),
        ("Terrain detail", f"{cfg.grid} samples, smoothing {cfg.smooth:g}"),
        ("Elevation source", cfg.dem_source),
        ("Trail line width", f"{cfg.trail_width:g} mm"),
        ("Trail thickness", f"{cfg.trail_thickness:g} mm"),
        ("Trail stands proud by", f"{cfg.trail_proud:g} mm"),
        ("Trail underside", cfg.trail_base),
        ("Fit clearance", f"{cfg.tolerance:g} mm per side"),
        ("Join files closer than", f"{cfg.join_distance_m:g} m on the ground"),
        ("Merge lines closer than", f"{cfg.merge_distance_mm:g} mm on the print"),
        ("Caption", f'"{cfg.caption}"' if cfg.caption else "none"),
        ("Caption band", f"{cfg.caption_height_mm:g} mm tall, "
                         f"text {cfg.caption_size:g} of the band"),
        ("Lettering",
         f"{cfg.caption_style} ({'cut into' if cfg.caption_style == 'deboss' else 'raised above'}"
         f" the surface), {cfg.caption_depth:g} mm"),
        ("Caption font", cfg.caption_font or "built-in"),
        ("Scale bar", "yes" if cfg.scale_bar else "no"),
        ("North arrow", "yes" if cfg.north_arrow else "no"),
        ("Underside credit",
         f"yes, {cfg.credit_height_mm:g} mm tall" if cfg.credit else "no"),
    ]
    for k, v in rows:
        add(f"  {k:<26}{v}")
    add("")

    add(_rule("WHAT CAME OUT"))
    add("")
    add(f"  Route            {s['track_name'] or '(unnamed)'}")
    add(f"  Length           {s['length_km']:.2f} km, {s['ascent_m']:.0f} m ascent")
    add(f"  Elevation        {s['elev_min_m']:.0f} to {s['elev_max_m']:.0f} m")
    add(f"  Scale            1:{s['scale_denominator']:,.0f}, "
        f"vertical x{s['z_exaggeration']:.2f}")
    if s.get("scale_bar"):
        add(f"  Scale bar shows  {s['scale_bar'][0]:g} m as "
            f"{s['scale_bar'][1]:.1f} mm")
    add(f"  Sections found   {s.get('n_raw_sections', 1)} "
        f"-> {s.get('n_sections', 1)} printable piece(s)")
    add("")
    for p in written:
        add(f"  {Path(p).name:<34}{Path(p).stat().st_size / 1024:,.0f} kB")
    add("")

    add(_rule("REPRODUCIBILITY"))
    add("")
    add(f"  Terrain came from: {s.get('dem_source', 'unknown')}")
    add("")
    if str(s.get("dem_source", "")).startswith("terrarium"):
        zoom = str(s["dem_source"]).split()[-1]
        add("  The tile zoom was chosen automatically from the map size. Re-running")
        add(f"  at a different --size may pick a different zoom; pin it with")
        add(f"  --dem-zoom {zoom.lstrip('z')} to rule that out.")
        add("")
    add("  Elevation tiles are fetched from a live public dataset and cached under")
    add("  ~/.cache/gpx2print. If that dataset is ever revised upstream, a rebuild")
    add("  could differ slightly. The cached tiles are what this build actually used.")
    add("")

    add(_rule("TERRAIN DATA CREDIT"))
    add("")
    for line in _fold(s.get("attribution", ""), WIDTH - 2):
        add(f"  {line}")
    add("")
    return "\n".join(L) + "\n"


def _fold(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def write(path: str, b, cfg, written: list[str], out_path: str, **kw) -> str:
    Path(path).write_text(render(b, cfg, written, out_path, **kw), encoding="utf-8")
    return path
