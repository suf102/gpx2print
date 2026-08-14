"""Render a preview of the area that will be printed."""

from __future__ import annotations

import numpy as np

INK = "#1d2129"
PAPER = "#faf8f4"
GRID = "#c9c3b8"


def _hillshade(Z, dx, dy, azimuth=315.0, altitude=45.0, exaggeration=2.0):
    gy, gx = np.gradient(Z * exaggeration, dy, dx)
    slope = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az = np.radians(360.0 - azimuth + 90.0)
    alt = np.radians(altitude)
    shade = np.sin(alt) * np.sin(slope) + np.cos(alt) * np.cos(slope) * np.cos(
        az - aspect
    )
    return np.clip(shade, 0, 1)


def _poly_path(geom):
    """Matplotlib path for shapely polygons, holes included.

    Drawing only the outer ring turns a route that loops back on itself into a
    filled blob, because the hole in the middle of the loop is what makes it read
    as a loop at all.
    """
    from matplotlib.path import Path as MPath
    from shapely.geometry import Polygon
    from shapely.geometry.polygon import orient

    verts, codes = [], []
    for g in getattr(geom, "geoms", [geom]):
        if not isinstance(g, Polygon) or g.is_empty:
            continue
        # Outer ring anticlockwise, holes clockwise, so the fill rule cuts them out.
        g = orient(g, sign=1.0)
        for ring in [g.exterior, *g.interiors]:
            c = np.asarray(ring.coords)
            if len(c) < 3:
                continue
            verts.extend(c)
            codes.extend(
                [MPath.MOVETO] + [MPath.LINETO] * (len(c) - 2) + [MPath.CLOSEPOLY]
            )
    return MPath(verts, codes) if verts else None


def _terrain_colors(Z_m):
    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list(
        "topo",
        [
            "#3f6d4e",
            "#6f8f57",
            "#a8ab68",
            "#c9b083",
            "#b98f6c",
            "#9d7f76",
            "#cfc7c2",
            "#ffffff",
        ],
    )


def render(build, cfg, path: str, dpi: int = 170) -> str:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    b = build
    st = b.stats
    frame = b.frame

    # Take the band from the build itself: the plinth exists if any of the caption,
    # the scale bar or the north arrow asked for it.
    band = float(getattr(b, "band_mm", 0.0) or 0.0)
    W, H = frame.width_mm, frame.height_mm

    # Terrain rows only; the strip is drawn separately, and it may be on either
    # side, so trim whichever end it was added to.
    on_top = st.get("caption_position", "bottom") == "top"
    if band > 0:
        Z_mm = b.Z_mm[:-2, :] if on_top else b.Z_mm[2:, :]
    else:
        Z_mm = b.Z_mm
    Z_m = b.Z_m

    aspect = (H + band) / W
    fig_w = 9.5
    fig_h = fig_w * aspect * 0.78 + 3.6
    fig = plt.figure(figsize=(fig_w, min(fig_h, 16)), dpi=dpi, facecolor=PAPER)

    gs = fig.add_gridspec(
        4, 1, height_ratios=[0.5, 6.2 * max(aspect, 0.45), 1.55, 0.34], hspace=0.30,
        left=0.06, right=0.94, top=0.965, bottom=0.04,
    )

    # ------------------------------------------------------------ title block
    ax0 = fig.add_subplot(gs[0])
    ax0.axis("off")
    map_only = bool(st.get("map_only"))
    title = st["track_name"] or ("Map" if map_only else "Hiking route")
    ax0.text(0, 0.62, title, fontsize=16, weight="bold", color=INK, va="center")
    ax0.text(
        0,
        0.02,
        (
            f"{st['across_km']:g} km across   ·   "
            f"{st['elev_min_m']:.0f}–{st['elev_max_m']:.0f} m"
            if map_only else
            f"{st['length_km']:.1f} km   ·   {st['ascent_m']:.0f} m ascent   ·   "
            f"{st['elev_min_m']:.0f}–{st['elev_max_m']:.0f} m"
        ),
        fontsize=9.5,
        color="#5a6068",
        va="center",
    )
    ax0.text(
        1,
        0.62,
        f"1 : {st['scale_denominator']:,.0f}",
        fontsize=11,
        color=INK,
        ha="right",
        va="center",
        weight="bold",
    )
    ax0.text(
        1,
        0.02,
        f"vertical ×{st['z_exaggeration']:.1f}   ·   {st['dem_source']}",
        fontsize=9.5,
        color="#5a6068",
        ha="right",
        va="center",
    )
    ax0.set_xlim(0, 1)
    ax0.set_ylim(0, 1)

    # ------------------------------------------------------------------- map
    ax = fig.add_subplot(gs[1])
    ax.set_facecolor(PAPER)

    dx = W / max(Z_mm.shape[1] - 1, 1)
    dy = H / max(Z_mm.shape[0] - 1, 1)
    extent = (0, W, 0, H)

    cmap = _terrain_colors(Z_m)
    norm = plt.Normalize(np.min(Z_m), max(np.max(Z_m), np.min(Z_m) + 1e-6))
    rgb = cmap(norm(Z_m))[:, :, :3]

    # The plate may not be a rectangle; everything terrain-ish is clipped to it.
    plate = getattr(b, "plate_poly", None)
    plate_path = _poly_path(plate) if plate is not None else None

    def clip_to_plate(artist):
        if plate_path is None:
            return artist
        from matplotlib.patches import PathPatch as _PP

        patch = _PP(plate_path, transform=ax.transData, facecolor="none",
                    edgecolor="none")
        ax.add_patch(patch)
        try:
            artist.set_clip_path(patch)
        except AttributeError:
            for c in getattr(artist, "collections", []):
                c.set_clip_path(patch)
        return artist

    if cfg.route_only:
        # Nothing is printed here but a flat plate, so don't draw a landscape that
        # will not exist on the model.
        from matplotlib.patches import PathPatch as _PP0

        if plate_path is not None:
            ax.add_patch(_PP0(plate_path, facecolor="#e4dfd4", edgecolor="none",
                              zorder=1))
        else:
            ax.add_patch(Rectangle((0, 0), W, H, facecolor="#e4dfd4",
                                   edgecolor="none", zorder=1))
    else:
        shade = _hillshade(Z_mm, dx, dy, exaggeration=1.6)[:, :, None]
        blended = np.clip(rgb * (0.35 + 0.75 * shade), 0, 1)
        clip_to_plate(ax.imshow(
            blended, extent=extent, origin="lower", interpolation="bilinear", zorder=1
        ))

    # contour lines at a round interval
    rng = st["relief_m"]
    step = next(
        (s for s in (5, 10, 20, 25, 50, 100, 200, 250, 500) if rng / s <= 14), 1000
    )
    levels = np.arange(
        np.floor(np.min(Z_m) / step) * step, np.max(Z_m) + step, step
    )
    xs = np.linspace(0, W, Z_m.shape[1])
    ys = np.linspace(0, H, Z_m.shape[0])
    cs = None if cfg.route_only else ax.contour(
        xs, ys, Z_m, levels=levels, colors="#000000", linewidths=0.35, alpha=0.28,
        zorder=2,
    )
    if cs is not None:
        clip_to_plate(cs)
        labels = ax.clabel(cs, cs.levels[::2], inline=True, fontsize=5.5, fmt="%d",
                           colors="#3a3a3a")
        # Clipping the contour lines leaves their labels floating outside the
        # plate, so drop any that do not sit on it.
        if plate is not None:
            from shapely.geometry import Point as _Pt

            for t in labels or []:
                x, y = t.get_position()
                if not plate.contains(_Pt(x, y)):
                    t.set_visible(False)

    # each section at its true channel width, in the colour it will print
    from matplotlib.patches import PathPatch

    from .export import trail_colors

    # One colour per printable piece, drawn from the merged footprint so the
    # preview shows exactly what the part will be, bridges and holes included.
    parts = b.parts or []
    colors = trail_colors(cfg.trail_color, max(len(parts), 1))

    for part, col in zip(parts, colors):
        outline = _poly_path(part.polygon)
        if outline is not None:
            ax.add_patch(
                PathPatch(outline, facecolor=col, edgecolor="#00000055",
                          lw=0.4, zorder=4)
            )

    # start and finish of every section
    for sec in (b.sections or []):
        sx, sy = frame.to_mm(sec.lat[[0, -1]], sec.lon[[0, -1]])
        ax.plot(sx[0], sy[0], "o", ms=6, mfc="#ffffff", mec=INK, mew=1.4, zorder=6)
        ax.plot(sx[1], sy[1], "s", ms=6, mfc=INK, mec="#ffffff", mew=1.2, zorder=6)

    # plate outline and caption strip
    from matplotlib.patches import PathPatch as _PP2

    # Above the seams: a piece's boundary is part seam and part the edge of the
    # map, and the outline drawn last is what keeps the outside reading as solid
    # while the cuts inside it read as dashed.
    if plate_path is not None:
        ax.add_patch(_PP2(plate_path, fill=False, ec=INK, lw=1.4, zorder=12))
        pminx, pminy, pmaxx, pmaxy = plate.bounds
    else:
        ax.add_patch(Rectangle((0, 0), W, H, fill=False, ec=INK, lw=1.4, zorder=12))
        pminx, pminy, pmaxx, pmaxy = 0.0, 0.0, W, H
    # The seams between tessellating pieces, and which piece is which. Drawn over
    # everything else, because where the map comes apart is the thing you most
    # want to check before spending a day of printer time on it.
    tiles = getattr(b, "tile_polys", None) or []
    if len(tiles) > 1:
        for i, tile in enumerate(tiles, 1):
            seam = _poly_path(tile)
            if seam is not None:
                ax.add_patch(
                    PathPatch(seam, fill=False, ec="#ffffff", lw=2.6, zorder=9,
                              joinstyle="round")
                )
                ax.add_patch(
                    PathPatch(seam, fill=False, ec=INK, lw=1.0, zorder=10,
                              linestyle=(0, (5, 3)))
                )
            c = tile.representative_point()
            ax.text(
                c.x, c.y, str(i), fontsize=8, weight="bold", color=INK,
                ha="center", va="center", zorder=11,
                bbox={"boxstyle": "circle,pad=0.24", "facecolor": "#ffffffcc",
                      "edgecolor": INK, "linewidth": 0.7},
            )

    if band > 0:
        sy = pmaxy if on_top else pminy - band
        # When the strip is a part of its own it is drawn as the shape it really
        # is, tongues and all, so it is plain where it parts from the map.
        loose = getattr(b, "strip_poly", None)
        if loose is not None:
            from shapely.ops import unary_union as _union

            edge = _poly_path(_union([loose, *getattr(b, "strip_tabs", [])]))
        else:
            edge = None
        if edge is not None:
            ax.add_patch(PathPatch(edge, facecolor="#e8e3d9", ec="none", zorder=7))
            ax.add_patch(PathPatch(edge, fill=False, ec=INK, lw=1.4, zorder=12))
        else:
            ax.add_patch(
                Rectangle((pminx, sy), pmaxx - pminx, band,
                          facecolor="#e8e3d9", ec="none", zorder=7)
            )
            ax.add_patch(
                Rectangle((pminx, sy), pmaxx - pminx, band,
                          fill=False, ec=INK, lw=1.4, zorder=12)
            )
        # Draw the very polygons the model is built from, so the preview cannot
        # drift out of step with what actually prints.
        if b.plinth_polys is not None:
            for g in getattr(b.plinth_polys, "geoms", [b.plinth_polys]):
                outline = _poly_path(g)
                if outline is not None:
                    # Engraved lettering is drawn as a recess, raised as solid ink,
                    # so the preview reads the same way the print will.
                    cut = cfg.caption_style == "deboss"
                    ax.add_patch(
                        PathPatch(
                            outline,
                            facecolor="#cfc8ba" if cut else INK,
                            edgecolor="#8d8676" if cut else "none",
                            lw=0.5 if cut else 0,
                            zorder=8,
                        )
                    )

    pad = max(W, H) * 0.02
    lo_y = (pminy if not on_top else pminy) - (0 if on_top else band) - pad
    hi_y = (pmaxy + band if on_top else pmaxy) + pad
    ax.set_xlim(pminx - pad, pmaxx + pad)
    ax.set_ylim(lo_y, hi_y)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    seams = "   ·   strip prints separately" if st.get("separate_strip") else ""
    if len(tiles) > 1:
        tw, th = st["tile_size_mm"]
        seams += (f"   ·   in {len(tiles)} {st['shape']}s, "
                 f"largest {tw:.0f} × {th:.0f} mm")
    ax.set_title(
        f"printed footprint  {pmaxx - pminx:.0f} × {pmaxy - pminy + band:.0f} mm"
        + seams,
        fontsize=8.5,
        color="#5a6068",
        pad=6,
    )

    # ------------------------------------------------------- elevation profile
    axp = fig.add_subplot(gs[2])
    axp.set_facecolor(PAPER)

    # Profiles are grouped by printable piece: every section that ended up in the
    # same part shares that part's colour and one legend entry.
    with_ele = [
        (part, col, [s for s in part.sections if s.ele is not None])
        for part, col in zip(parts, colors)
    ]
    with_ele = [(p, c, s) for p, c, s in with_ele if s]

    if map_only:
        # No route to plot a profile for, so show how the ground is distributed
        # by height instead, which says something about the terrain being printed.
        z = np.asarray(b.Z_m).ravel()
        axp.hist(z, bins=60, color="#6f8f57", edgecolor="none")
        axp.set_xlabel("elevation (m)", fontsize=8, color="#5a6068")
        axp.set_ylabel("how much ground", fontsize=8, color="#5a6068")
        axp.set_yticks([])
        axp.set_title("how the ground is spread by height", fontsize=8,
                      color="#5a6068", pad=4)
    elif with_ele:
        from .gpx_io import meters_per_degree

        floor = min(float(np.min(s.ele)) for _, _, ss in with_ele for s in ss)
        longest = 0.0
        for part, col, secs in with_ele:
            for k, sec in enumerate(secs):
                mx, my = meters_per_degree(float(np.mean(sec.lat)))
                d = np.concatenate(
                    [[0],
                     np.cumsum(np.hypot(np.diff(sec.lon) * mx, np.diff(sec.lat) * my))]
                )
                km = d / 1000.0
                longest = max(longest, float(km[-1]))
                axp.fill_between(km, sec.ele, floor, color=col, alpha=0.18)
                axp.plot(
                    km, sec.ele, color=col, lw=1.6,
                    label=(
                        None
                        if k or len(parts) == 1
                        else f"piece {part.index} · {sec.name}"
                    ),
                )
        axp.set_xlabel("distance (km)", fontsize=8, color="#5a6068")
        axp.set_ylabel("elevation (m)", fontsize=8, color="#5a6068")
        axp.set_xlim(0, longest)
        if len(parts) > 1:
            axp.legend(fontsize=7, frameon=False, loc="upper left", ncol=2)
    else:
        axp.text(0.5, 0.5, "no elevation data in the GPX file",
                 ha="center", va="center", fontsize=9, color="#8a9098")
        axp.set_xticks([])
        axp.set_yticks([])

    axp.tick_params(labelsize=7.5, colors="#5a6068")
    axp.grid(True, color=GRID, lw=0.5, alpha=0.6)
    for s in ("top", "right"):
        axp.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        axp.spines[s].set_color(GRID)

    axf = fig.add_subplot(gs[3])
    axf.axis("off")
    tw, td = st["trail_size_mm"], st["insert_thickness_mm"]
    ms = st["map_size_mm"]
    if len(tiles) > 1:
        tw, th = st["tile_size_mm"]
        footer = (
            f"{st['n_map_parts']} objects to print        "
            f"largest piece {tw:.0f} × {th:.0f} × {ms[2]:.1f} mm        "
            + (f"{st['across_km']:g} km across        " if map_only else "")
            + f"1:{st['scale_denominator']:,.0f}"
        )
    elif map_only:
        footer = (
            f"one object  {ms[0]:.0f} × {ms[1]:.0f} × {ms[2]:.1f} mm        "
            f"{st['across_km']:g} km across        1:{st['scale_denominator']:,.0f}"
        )
    elif cfg.route_only:
        footer = (
            f"one object  {ms[0]:.0f} × {ms[1]:.0f} × {ms[2]:.1f} mm        "
            f"route stands {ms[2] - cfg.base_mm:.1f} mm above a "
            f"{cfg.base_mm:.1f} mm base        line {cfg.trail_width:.1f} mm wide"
        )
    else:
        footer = (
            f"map  {ms[0]:.0f} × {ms[1]:.0f} × {ms[2]:.1f} mm        "
            f"insert  {tw[0]:.0f} × {tw[1]:.0f} × {tw[2]:.1f} mm, "
            f"{td[0]:.1f}–{td[1]:.1f} mm thick        "
            f"channel {st['channel_width_mm']:.2f} mm into insert "
            f"{st['insert_width_mm']:.2f} mm  "
            f"({st['total_clearance_mm']:.2f} mm clearance)"
        )
    axf.text(0, 0.55, footer, fontsize=7.5, color="#5a6068", va="center")
    axf.text(
        0,
        0.02,
        st.get("attribution", ""),
        fontsize=6.5,
        color="#8a9098",
        va="center",
    )
    axf.set_xlim(0, 1)
    axf.set_ylim(0, 1)

    fig.savefig(path, dpi=dpi, facecolor=PAPER)
    plt.close(fig)
    return path
