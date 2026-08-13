"""Digital elevation model sampling.

The default source is the AWS "terrarium" terrain tile set: open data, no API key,
and a whole 256x256 patch of elevation per request, which is what makes sampling a
few hundred thousand grid points practical.
"""

from __future__ import annotations

import io
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

TERRARIUM_URLS = (
    "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
    "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png",
)
TILE_PX = 256
MAX_TILES = 64
USER_AGENT = "gpx2print/1.0 (https://github.com/; 3d-printed-hiking-maps)"

# Using this data obliges us to credit it. The upstream list of per-country
# sources is long; this is the short form plus a pointer to the full one.
# https://github.com/tilezen/joerd/blob/master/docs/attribution.md
ATTRIBUTION = {
    "terrarium": (
        "Elevation: Mapzen Terrain Tiles (Tilezen/joerd, a Linux Foundation "
        "project) via AWS Open Data — derived from USGS, SRTM, Copernicus EU-DEM "
        "and national sources"
    ),
    "opentopodata": (
        "Elevation: Open Topo Data (opentopodata.org) — SRTM, courtesy of the "
        "U.S. Geological Survey"
    ),
    "gpx": "Elevation: interpolated from the GPX track's own recorded elevations",
    "flat": "No elevation data used",
}

ATTRIBUTION_URL = "https://github.com/tilezen/joerd/blob/master/docs/attribution.md"

# The long form is unreadable engraved at this size, so the physical print carries
# a condensed two-line version instead.
# Each entry is (preferred, fallback). The fallback is used when the map is too
# small to engrave the longer wording legibly.
ATTRIBUTION_ENGRAVED = {
    "terrarium": (
        "Terrain: Mapzen Terrain Tiles (Tilezen, Linux Foundation) · "
        "USGS · SRTM · Copernicus EU-DEM · made with gpx2print",
        "Terrain: Mapzen Tiles · USGS · SRTM",
    ),
    "opentopodata": (
        "Terrain: Open Topo Data · SRTM courtesy of the USGS · "
        "made with gpx2print",
        "Terrain: Open Topo Data · USGS",
    ),
    "gpx": (
        "Terrain interpolated from the GPS track · made with gpx2print",
        "Terrain from GPS track",
    ),
    "flat": ("made with gpx2print", "gpx2print"),
}


def attribution_for(source: str) -> str:
    """Credit line for a source label such as 'terrarium z12'."""
    return ATTRIBUTION.get(source.split()[0], "Elevation: unknown source")


def engraved_credit_for(source: str) -> tuple[str, str]:
    """Preferred and fallback wording to cut into the underside of the map."""
    return ATTRIBUTION_ENGRAVED.get(
        source.split()[0], ("made with gpx2print", "gpx2print")
    )


class DEMError(RuntimeError):
    pass


def _cache_dir(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
    else:
        base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
        p = Path(base) / "gpx2print" / "terrarium"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _lonlat_to_pixel(lon, lat, z):
    """WGS84 degrees to global web-mercator pixel coordinates at zoom `z`."""
    n = TILE_PX * (2**z)
    lat = np.clip(np.asarray(lat, dtype=float), -85.05112878, 85.05112878)
    px = (np.asarray(lon, dtype=float) + 180.0) / 360.0 * n
    s = np.sin(np.radians(lat))
    py = (0.5 - np.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return px, py


def choose_zoom(frame, grid: int, requested: int | None) -> int:
    """Pick the coarsest zoom that still resolves one DEM pixel per grid cell."""
    if requested is not None:
        return int(np.clip(requested, 1, 15))

    span_m = max(
        (frame.lon_max - frame.lon_min) * frame.m_per_deg_lon,
        (frame.lat_max - frame.lat_min) * frame.m_per_deg_lat,
    )
    cell_m = span_m / max(grid, 1)
    ground_res_z0 = 156543.03392 * math.cos(math.radians(frame.lat0))

    z = math.ceil(math.log2(max(ground_res_z0 / max(cell_m, 1e-6), 1.0)))
    z = int(np.clip(z, 5, 14))

    # Back off if the window would need an unreasonable number of tiles.
    while z > 5 and _tile_count(frame, z) > MAX_TILES:
        z -= 1
    return z


def _tile_range(frame, z):
    px0, py0 = _lonlat_to_pixel(frame.lon_min, frame.lat_max, z)
    px1, py1 = _lonlat_to_pixel(frame.lon_max, frame.lat_min, z)
    tx0, ty0 = int(px0 // TILE_PX), int(py0 // TILE_PX)
    tx1, ty1 = int(px1 // TILE_PX), int(py1 // TILE_PX)
    return tx0, ty0, tx1, ty1


def _tile_count(frame, z):
    tx0, ty0, tx1, ty1 = _tile_range(frame, z)
    return (tx1 - tx0 + 1) * (ty1 - ty0 + 1)


def _fetch_tile(z: int, x: int, y: int, cache: Path, session) -> np.ndarray | None:
    n = 2**z
    if not (0 <= y < n):
        return None
    x %= n  # wrap across the antimeridian

    path = cache / f"{z}_{x}_{y}.png"
    data = None
    if path.exists():
        try:
            data = path.read_bytes()
        except OSError:
            data = None

    if data is None:
        last = None
        for url in TERRARIUM_URLS:
            for attempt in range(3):
                try:
                    r = session.get(
                        url.format(z=z, x=x, y=y),
                        timeout=25,
                        headers={"User-Agent": USER_AGENT},
                    )
                    if r.status_code == 404:
                        return None
                    r.raise_for_status()
                    data = r.content
                    break
                except Exception as exc:  # noqa: BLE001 - retried, then reported
                    last = exc
                    time.sleep(0.4 * (attempt + 1))
            if data is not None:
                break
        if data is None:
            raise DEMError(f"could not fetch terrain tile {z}/{x}/{y}: {last}")
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        arr = np.asarray(im.convert("RGB"), dtype=np.float32)

    # terrarium encoding, metres above sea level
    return (arr[:, :, 0] * 256.0 + arr[:, :, 1] + arr[:, :, 2] / 256.0) - 32768.0


def _mosaic(frame, z: int, cache: Path, log) -> tuple[np.ndarray, int, int]:
    import requests

    tx0, ty0, tx1, ty1 = _tile_range(frame, z)
    jobs = [(x, y) for y in range(ty0, ty1 + 1) for x in range(tx0, tx1 + 1)]
    log(f"  fetching {len(jobs)} terrain tile(s) at zoom {z}")

    out = np.full(
        ((ty1 - ty0 + 1) * TILE_PX, (tx1 - tx0 + 1) * TILE_PX),
        np.nan,
        dtype=np.float32,
    )

    with requests.Session() as session:
        def work(job):
            x, y = job
            return job, _fetch_tile(z, x, y, cache, session)

        with ThreadPoolExecutor(max_workers=8) as pool:
            for (x, y), tile in pool.map(work, jobs):
                if tile is None:
                    continue
                r = (y - ty0) * TILE_PX
                c = (x - tx0) * TILE_PX
                out[r : r + TILE_PX, c : c + TILE_PX] = tile

    if np.all(np.isnan(out)):
        raise DEMError("no terrain tiles covered this area")
    return out, tx0 * TILE_PX, ty0 * TILE_PX


def _sample(mosaic, ox, oy, lon_grid, lat_grid, z):
    from scipy.ndimage import map_coordinates

    px, py = _lonlat_to_pixel(lon_grid, lat_grid, z)
    # Tile pixel centres sit at +0.5; shift so integer indices line up with them.
    coords = np.stack([py - oy - 0.5, px - ox - 0.5])

    filled = mosaic
    if np.any(np.isnan(mosaic)):
        filled = _fill_nan(mosaic)
    return map_coordinates(filled, coords, order=1, mode="nearest").astype(float)


def _fill_nan(a: np.ndarray) -> np.ndarray:
    """Replace NaN holes (missing tiles) with the nearest valid value."""
    from scipy.ndimage import distance_transform_edt

    bad = np.isnan(a)
    if not bad.any():
        return a
    idx = distance_transform_edt(bad, return_distances=False, return_indices=True)
    return a[tuple(idx)]


def sample_terrarium(frame, lat_grid, lon_grid, grid, zoom, cache_dir, log):
    z = choose_zoom(frame, grid, zoom)
    mosaic, ox, oy = _mosaic(frame, z, _cache_dir(cache_dir), log)
    return _sample(mosaic, ox, oy, lon_grid, lat_grid, z), z


def sample_opentopodata(lat_grid, lon_grid, log, dataset="srtm30m", max_points=3600):
    """Fallback point API. Rate limited, so a coarse grid is sampled and upscaled."""
    import requests
    from scipy.ndimage import zoom as ndzoom

    ny, nx = lat_grid.shape
    step = max(1, int(math.ceil(math.sqrt(ny * nx / max_points))))
    sub_lat = lat_grid[::step, ::step]
    sub_lon = lon_grid[::step, ::step]
    pts = np.column_stack([sub_lat.ravel(), sub_lon.ravel()])
    log(f"  querying opentopodata for {len(pts)} points (1 request/sec)")

    vals = np.empty(len(pts))
    with requests.Session() as session:
        for i in range(0, len(pts), 100):
            chunk = pts[i : i + 100]
            loc = "|".join(f"{a:.6f},{b:.6f}" for a, b in chunk)
            for attempt in range(4):
                try:
                    r = session.post(
                        f"https://api.opentopodata.org/v1/{dataset}",
                        data={"locations": loc},
                        timeout=40,
                        headers={"User-Agent": USER_AGENT},
                    )
                    if r.status_code == 429:
                        time.sleep(2.0 * (attempt + 1))
                        continue
                    r.raise_for_status()
                    res = r.json()["results"]
                    vals[i : i + len(chunk)] = [
                        (x["elevation"] if x["elevation"] is not None else np.nan)
                        for x in res
                    ]
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == 3:
                        raise DEMError(f"opentopodata request failed: {exc}") from exc
                    time.sleep(1.5 * (attempt + 1))
            time.sleep(1.05)

    sub = vals.reshape(sub_lat.shape)
    sub = _fill_nan(sub.astype(np.float32))
    if sub.shape != lat_grid.shape:
        sub = ndzoom(
            sub, (ny / sub.shape[0], nx / sub.shape[1]), order=1, mode="nearest"
        )
        sub = sub[:ny, :nx]
    return sub.astype(float)


def sample_from_track(frame, lat_grid, lon_grid, track, log):
    """Build a surface from the track's own elevations. Works with no network.

    Inverse-distance weighting across the track points. This is an invention, not a
    survey: it is only meaningful within a short distance of the path itself.
    """
    if track.ele is None:
        raise DEMError("the GPX file has no elevation data to interpolate from")
    log("  interpolating terrain from track elevations (offline)")

    tx, ty = frame.to_mm(track.lat, track.lon)
    gx, gy = frame.to_mm(lat_grid, lon_grid)
    pts = np.column_stack([tx, ty])

    from scipy.spatial import cKDTree

    tree = cKDTree(pts)
    q = np.column_stack([gx.ravel(), gy.ravel()])
    k = min(12, len(pts))
    dist, idx = tree.query(q, k=k)
    if k == 1:
        dist = dist[:, None]
        idx = idx[:, None]

    w = 1.0 / np.maximum(dist, 1e-3) ** 2
    z = np.sum(w * track.ele[idx], axis=1) / np.sum(w, axis=1)
    return z.reshape(lat_grid.shape)


def elevation_grid(cfg, frame, track, lat_grid, lon_grid, log):
    """Dispatch to the configured source, falling back gracefully."""
    src = cfg.dem_source
    if src == "flat":
        return np.zeros(lat_grid.shape), "flat"

    if src == "gpx":
        return sample_from_track(frame, lat_grid, lon_grid, track, log), "gpx"

    if src == "terrarium":
        try:
            z, used = sample_terrarium(
                frame, lat_grid, lon_grid, cfg.grid, cfg.dem_zoom, cfg.cache_dir, log
            )
            return z, f"terrarium z{used}"
        except Exception as exc:  # noqa: BLE001
            log(f"  terrain tiles unavailable ({exc})")
            if track.ele is not None:
                log("  falling back to track elevations")
                return sample_from_track(frame, lat_grid, lon_grid, track, log), "gpx"
            raise

    return sample_opentopodata(lat_grid, lon_grid, log), "opentopodata"
