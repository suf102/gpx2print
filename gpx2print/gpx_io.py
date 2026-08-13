"""GPX loading and projection into a local millimetre plane."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

EARTH_R = 6371008.8


@dataclass
class Track:
    lat: np.ndarray
    lon: np.ndarray
    ele: np.ndarray | None
    name: str
    seg: np.ndarray | None = None
    """Segment id per point. Separate segments must not be joined by a line."""

    def __len__(self) -> int:
        return len(self.lat)

    def segments(self):
        """Yield (lat, lon) arrays for each contiguous segment of two or more points."""
        if self.seg is None:
            yield self.lat, self.lon
            return
        for s in np.unique(self.seg):
            m = self.seg == s
            if m.sum() >= 2:
                yield self.lat[m], self.lon[m]


def load_gpx(path: str) -> Track:
    """Read every track, route and (as a last resort) waypoint in the file."""
    import gpxpy

    with open(path, encoding="utf-8", errors="replace") as fh:
        gpx = gpxpy.parse(fh)

    lat: list[float] = []
    lon: list[float] = []
    ele: list[float | None] = []
    seg: list[int] = []
    name = ""
    sid = 0

    for track in gpx.tracks:
        name = name or (track.name or "")
        for segment in track.segments:
            if not segment.points:
                continue
            for p in segment.points:
                lat.append(p.latitude)
                lon.append(p.longitude)
                ele.append(p.elevation)
                seg.append(sid)
            sid += 1

    if not lat:
        for route in gpx.routes:
            name = name or (route.name or "")
            for p in route.points:
                lat.append(p.latitude)
                lon.append(p.longitude)
                ele.append(p.elevation)
                seg.append(sid)
            sid += 1

    if not lat:
        for p in gpx.waypoints:
            lat.append(p.latitude)
            lon.append(p.longitude)
            ele.append(p.elevation)
            seg.append(0)

    if len(lat) < 2:
        raise ValueError(f"{path} contains fewer than two usable points")

    name = name or gpx.name or ""
    ele_arr = None
    if all(e is not None for e in ele):
        ele_arr = np.asarray(ele, dtype=float)

    return Track(
        lat=np.asarray(lat, dtype=float),
        lon=np.asarray(lon, dtype=float),
        ele=ele_arr,
        name=name.strip(),
        seg=np.asarray(seg, dtype=int),
    )


def drop_duplicates(track: Track, min_step_m: float = 1.0) -> Track:
    """Remove consecutive points closer together than `min_step_m`.

    GPS traces routinely contain long runs of near-identical points recorded while
    stationary; they add nothing but make the offset polygon self-intersect.
    """
    lat0 = float(np.mean(track.lat))
    mx, my = meters_per_degree(lat0)
    x = track.lon * mx
    y = track.lat * my

    seg = track.seg if track.seg is not None else np.zeros(len(track), dtype=int)

    keep = [0]
    for i in range(1, len(track)):
        j = keep[-1]
        if seg[i] != seg[j]:
            keep.append(i)
            continue
        dx = x[i] - x[j]
        dy = y[i] - y[j]
        if dx * dx + dy * dy >= min_step_m * min_step_m:
            keep.append(i)
    if len(keep) < 2:
        keep = list(range(len(track)))
    k = np.asarray(keep)

    return Track(
        lat=track.lat[k],
        lon=track.lon[k],
        ele=None if track.ele is None else track.ele[k],
        name=track.name,
        seg=seg[k],
    )


def expand_frame(
    frame: Frame, w_mm: float, h_mm: float, size_mm: float | None
) -> Frame:
    """Widen the window to w_mm x h_mm of the current scale, then rescale.

    A shape that is not a rectangle needs terrain out to the corners of its own
    bounding box, not just the track's rectangle, or the plate would be cut off
    where the grid runs out.
    """
    w_m = w_mm / frame.mm_per_m
    h_m = h_mm / frame.mm_per_m
    # With size_mm given, rescale so the finished plate measures that across. With
    # it left out the scale is fixed, so the plate simply comes out bigger.
    mm_per_m = frame.mm_per_m if size_mm is None else size_mm / max(w_m, h_m)
    half_lon = (w_m / frame.m_per_deg_lon) / 2
    half_lat = (h_m / frame.m_per_deg_lat) / 2
    return Frame(
        lat0=frame.lat0,
        lon0=frame.lon0,
        m_per_deg_lon=frame.m_per_deg_lon,
        m_per_deg_lat=frame.m_per_deg_lat,
        mm_per_m=mm_per_m,
        lon_min=frame.lon0 - half_lon,
        lon_max=frame.lon0 + half_lon,
        lat_min=frame.lat0 - half_lat,
        lat_max=frame.lat0 + half_lat,
        width_mm=w_m * mm_per_m,
        height_mm=h_m * mm_per_m,
    )


def load_pieces(paths: list[str], min_step_m: float = 1.0):
    """Every contiguous run of points across every file, ready to be chained."""
    from pathlib import Path as _Path

    from .chain import Piece

    pieces = []
    names = []
    for p in paths:
        track = drop_duplicates(load_gpx(p), min_step_m=min_step_m)
        label = track.name or _Path(p).stem
        names.append(label)
        seg = track.seg if track.seg is not None else np.zeros(len(track), dtype=int)
        for s in np.unique(seg):
            m = seg == s
            if m.sum() < 2:
                continue
            pieces.append(
                Piece(
                    lat=track.lat[m],
                    lon=track.lon[m],
                    ele=None if track.ele is None else track.ele[m],
                    source=label,
                )
            )
    if not pieces:
        raise ValueError("none of the given files contained a usable track")
    return pieces, names


def meters_per_degree(lat_deg: float) -> tuple[float, float]:
    """Metres per degree of longitude and latitude at a given latitude."""
    lat = np.radians(lat_deg)
    m_per_deg_lat = 111132.92 - 559.82 * np.cos(2 * lat) + 1.175 * np.cos(4 * lat)
    m_per_deg_lon = 111412.84 * np.cos(lat) - 93.5 * np.cos(3 * lat)
    return float(m_per_deg_lon), float(m_per_deg_lat)


@dataclass
class Frame:
    """Maps between WGS84 degrees and model millimetres.

    A local equirectangular projection about the map centre. Over the few
    kilometres a walk covers, its distortion is far below the printer's
    resolution, and it keeps north pointing straight up the print.
    """

    lat0: float
    lon0: float
    m_per_deg_lon: float
    m_per_deg_lat: float
    mm_per_m: float
    lon_min: float
    lon_max: float
    lat_min: float
    lat_max: float
    width_mm: float
    height_mm: float

    def to_mm(self, lat, lon):
        x = (np.asarray(lon) - self.lon_min) * self.m_per_deg_lon * self.mm_per_m
        y = (np.asarray(lat) - self.lat_min) * self.m_per_deg_lat * self.mm_per_m
        return x, y

    def to_deg(self, x, y):
        lon = np.asarray(x) / (self.m_per_deg_lon * self.mm_per_m) + self.lon_min
        lat = np.asarray(y) / (self.m_per_deg_lat * self.mm_per_m) + self.lat_min
        return lat, lon


def build_frame(
    track: Track, size_mm: float, margin: float, square: bool
) -> Frame:
    """Choose the geographic window and the scale that maps it onto the plate."""
    lat0 = float((track.lat.min() + track.lat.max()) / 2)
    lon0 = float((track.lon.min() + track.lon.max()) / 2)
    mx, my = meters_per_degree(lat0)

    # Work out the track extent in metres, then pad it.
    w_m = float(track.lon.max() - track.lon.min()) * mx
    h_m = float(track.lat.max() - track.lat.min()) * my

    # A track that is nearly a straight line, or a single out-and-back, can have a
    # near-zero extent on one axis. Give it something sensible to sit in.
    span = max(w_m, h_m, 200.0)
    w_m = max(w_m, span * 0.12)
    h_m = max(h_m, span * 0.12)

    pad = margin * max(w_m, h_m)
    w_m += 2 * pad
    h_m += 2 * pad

    if square:
        w_m = h_m = max(w_m, h_m)

    mm_per_m = size_mm / max(w_m, h_m)

    half_lon = (w_m / mx) / 2
    half_lat = (h_m / my) / 2

    return Frame(
        lat0=lat0,
        lon0=lon0,
        m_per_deg_lon=mx,
        m_per_deg_lat=my,
        mm_per_m=mm_per_m,
        lon_min=lon0 - half_lon,
        lon_max=lon0 + half_lon,
        lat_min=lat0 - half_lat,
        lat_max=lat0 + half_lat,
        width_mm=w_m * mm_per_m,
        height_mm=h_m * mm_per_m,
    )


def track_length_m(track: Track) -> float:
    """Great-circle length of the track in metres."""
    lat = np.radians(track.lat)
    lon = np.radians(track.lon)
    dlat = np.diff(lat)
    dlon = np.diff(lon)
    a = (
        np.sin(dlat / 2) ** 2
        + np.cos(lat[:-1]) * np.cos(lat[1:]) * np.sin(dlon / 2) ** 2
    )
    return float(np.sum(2 * EARTH_R * np.arcsin(np.sqrt(np.clip(a, 0, 1)))))
