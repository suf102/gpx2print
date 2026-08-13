"""User-facing build parameters."""

from dataclasses import dataclass, field


@dataclass
class Config:
    # --- input / output ---
    gpx_paths: list[str] = field(default_factory=list)
    """One or more GPX files. Pieces whose ends meet are joined into one path."""

    gpx_path: str = ""
    """Convenience for the single-file case; folded into gpx_paths."""

    join_distance_m: float = 200.0
    """How close two ends must be to count as the same path, in metres."""

    merge_distance_mm: float = 2.0
    """Sections whose printed lines come this close, or cross, become one piece.

    Two paths that cross occupy the same space and could not both be fitted; two
    that merely pass very close leave a wall of map too thin to survive. Either way
    they have to be printed as a single part.
    """

    out_path: str = "map.3mf"
    preview_path: str | None = None

    # --- overall size ---
    size_mm: float = 150.0
    """Length of the longest horizontal edge of the map, in millimetres."""

    scale_denominator: float | None = None
    """Set the map scale directly, as the N in 1:N, instead of the size.

    1:50000 means a metre of ground becomes 1/50 mm on the model. The plate then
    comes out whatever size the route needs, and --size is ignored.
    """

    altitude_offset_m: float = 0.0
    """Move the height the relief is measured from, in metres of real altitude.

    By default the lowest ground in view sits on the base. A positive offset
    raises that reference, so anything below it flattens onto the base — useful
    for lifting a valley floor out of the way, or for giving several maps of
    neighbouring areas the same vertical datum so they stand at matching heights.
    A negative offset lowers it, lifting the whole landscape off the base.
    """

    margin: float = 0.15
    """Terrain padding around the track, as a fraction of the track's bounding box."""

    shape: str = "rectangle"
    """Outline of the plate: rectangle, square, circle, triangle, pentagon,
    hexagon or octagon.

    The shape is grown until it contains the whole terrain rectangle, then the
    map is scaled back down so its longest edge is still --size. An inscribed
    shape would crop the corners off the map and take part of the route with it.
    """

    caption_position: str = "bottom"
    """Which side of the plate the caption strip is attached to: bottom or top."""

    square: bool = False
    """Force a square map footprint instead of matching the track's aspect ratio."""

    # --- vertical shape ---
    z_scale: float = 1.75
    """Vertical exaggeration. 1.0 is true-to-life, which usually looks far too flat."""

    max_relief_mm: float | None = None
    """If set, terrain relief is rescaled to exactly this height, overriding z_scale."""

    base_mm: float = 5.0
    """Solid slab beneath the lowest terrain point."""

    # --- terrain sampling ---
    grid: int = 260
    """Samples along the longest edge of the DEM grid."""

    smooth: float = 0.6
    """Gaussian smoothing sigma in grid cells. Tames DEM noise and stair-stepping."""

    dem_source: str = "terrarium"
    """One of: terrarium (AWS tiles), opentopodata, gpx (track only), flat."""

    dem_zoom: int | None = None
    """Terrarium tile zoom. Chosen automatically from the map area when None."""

    # --- the trail channel and its insert ---
    trail_width: float = 3.0
    """Width of the printed trail line, in millimetres.

    This is the visible red line: the width of the insert itself. The channel cut
    into the map is widened from it by the tolerance, so changing the fit never
    changes how thick the trail looks.
    """

    tolerance: float = 0.3
    """Clearance per side between channel wall and insert. Total slop is twice this.

    0.3 mm suits a typical hobby FDM printer. It looks generous on screen, but the
    first layers of both parts bulge outwards slightly (elephant's foot), so the
    real gap at the bottom of the slot is always smaller than the nominal figure.
    """

    trail_thickness: float = 3.0
    """Minimum vertical thickness of the insert, at the lowest point of the track."""

    trail_proud: float = 0.8
    """How far the insert stands above the terrain surface."""

    trail_entry: str = "top"
    """top: the route drops into a slot cut from above.

    bottom: the slot is cut right through and the route is pushed up from
    underneath, finishing flush with the bottom of the map. A route that closes on
    itself then detaches the land inside the loop, so the map arrives in several
    pieces which the route holds together once fitted.
    """

    trail_base: str = "flat"
    """flat: insert has a flat bottom (prints without support).
    follow: insert follows the terrain at constant thickness (compact, needs support)."""

    trail_simplify: float = 0.25
    """Douglas-Peucker tolerance in millimetres, applied to the projected track."""

    # --- caption ---
    caption: str | None = None
    caption_height_mm: float = 12.0
    """Height of the flat plinth band added below the terrain to carry the caption."""

    caption_size: float = 0.5
    """Cap height of the text as a fraction of the caption band height."""

    caption_depth: float = 0.8
    """Emboss height or deboss depth of the lettering."""

    caption_style: str = "deboss"
    """deboss (cut into the surface) or emboss (raised above it).

    Engraved is the default because it prints more cleanly: small raised letters
    are easily smeared by the nozzle, while a groove is cut by the surrounding
    perimeters. Applies to the caption, the scale bar and the north arrow.
    """

    caption_font: str | None = None
    """Path to a .ttf/.otf font. Falls back to a bundled matplotlib font."""

    route_only: bool = False
    """Drop the surrounding landscape and stand the route on a flat base.

    The route still takes its height from the real terrain, so the printed line
    is the elevation profile of the walk; only the land around it is removed.
    The base keeps the caption, scale bar and north arrow.
    """

    # --- map furniture on the plinth ---
    scale_bar: bool = True
    """Show a chequered distance scale on the plinth."""

    north_arrow: bool = True
    """Show a north arrow on the plinth."""

    # --- credit engraved on the underside ---
    credit: bool = True
    """Engrave the terrain data credit into the bottom of the map.

    The licence for the elevation data requires attribution, and a physical object
    carries none of the file metadata, so this is how the credit survives printing.
    """

    credit_depth: float = 0.4
    """How deep the underside lettering is cut."""

    credit_height_mm: float = 3.2
    """Cap height of the underside lettering."""

    # --- output detail ---
    map_color: str = "#6E7B54"
    trail_color: str = "#D6482B"

    cache_dir: str | None = None
    verbose: bool = True

    log_fn: object | None = None
    """Optional callable receiving progress lines instead of stdout."""

    # populated during the build, not set by the user
    stats: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Accept either a single path or a list, and keep both views in step.
        if isinstance(self.gpx_paths, str):
            self.gpx_paths = [self.gpx_paths]
        if self.gpx_path and not self.gpx_paths:
            self.gpx_paths = [self.gpx_path]
        if self.gpx_paths and not self.gpx_path:
            self.gpx_path = self.gpx_paths[0]

    def validate(self) -> None:
        if not self.gpx_paths:
            raise ValueError("no GPX file given")
        if self.join_distance_m < 0:
            raise ValueError("--join-distance cannot be negative")
        if self.merge_distance_mm < 0:
            raise ValueError("--merge-distance cannot be negative")
        if self.scale_denominator is not None and self.scale_denominator <= 0:
            raise ValueError("--scale must be greater than zero")
        if self.size_mm <= 10:
            raise ValueError("--size must be greater than 10 mm")
        if self.trail_width < 0.4:
            raise ValueError(
                f"--trail-width ({self.trail_width}) is below 0.4 mm, which is "
                f"thinner than a single extrusion; the insert would not print"
            )
        if self.tolerance < 0:
            raise ValueError("--tolerance cannot be negative")
        if self.grid < 40:
            raise ValueError("--grid must be at least 40")
        if self.grid > 900:
            raise ValueError("--grid above 900 makes meshes too heavy to slice")
        from .shapes import SHAPES
        if self.shape not in SHAPES:
            raise ValueError(f"--shape must be one of: {', '.join(SHAPES)}")
        if self.caption_position not in ("bottom", "top"):
            raise ValueError("--caption-position must be 'bottom' or 'top'")
        if self.trail_entry not in ("top", "bottom"):
            raise ValueError("--trail-entry must be 'top' or 'bottom'")
        if self.trail_base not in ("flat", "follow"):
            raise ValueError("--trail-base must be 'flat' or 'follow'")
        if self.caption_style not in ("emboss", "deboss"):
            raise ValueError("--caption-style must be 'emboss' or 'deboss'")
        if self.dem_source not in ("terrarium", "opentopodata", "gpx", "flat"):
            raise ValueError(
                "--dem-source must be terrarium, opentopodata, gpx or flat"
            )
