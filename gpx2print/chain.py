"""Stitch GPX pieces into continuous sections.

A multi-day walk usually arrives as one file per day, and the end of one day sits a
few metres from the start of the next. Anything whose ends meet is joined into a
single path; anything left over becomes a section of its own, and prints as its own
piece.

The joining is done on parsed coordinates rather than by splicing the XML together.
That way the files can be given in any order, a leg recorded in the opposite
direction still joins, and no assumptions are made about namespaces or schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

EARTH_R = 6371008.8


@dataclass
class Piece:
    """One contiguous run of points, from one segment of one file."""

    lat: np.ndarray
    lon: np.ndarray
    ele: np.ndarray | None
    source: str

    def reversed(self) -> Piece:
        return Piece(
            lat=self.lat[::-1].copy(),
            lon=self.lon[::-1].copy(),
            ele=None if self.ele is None else self.ele[::-1].copy(),
            source=self.source,
        )

    @property
    def start(self):
        return float(self.lat[0]), float(self.lon[0])

    @property
    def end(self):
        return float(self.lat[-1]), float(self.lon[-1])


@dataclass
class Section:
    """One continuous path, made of one or more pieces joined end to end."""

    lat: np.ndarray
    lon: np.ndarray
    ele: np.ndarray | None
    sources: list[str] = field(default_factory=list)
    joins: list[float] = field(default_factory=list)
    """Gap in metres bridged at each join."""

    def __len__(self) -> int:
        return len(self.lat)

    @property
    def name(self) -> str:
        uniq = list(dict.fromkeys(self.sources))
        if len(uniq) == 1:
            return uniq[0]
        return f"{uniq[0]} + {len(uniq) - 1} more"


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance between two (lat, lon) pairs, in metres."""
    lat1, lon1 = np.radians(a)
    lat2, lon2 = np.radians(b)
    d = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return float(2 * EARTH_R * np.arcsin(np.sqrt(np.clip(d, 0, 1))))


def _concat(pieces: list[Piece], gaps: list[float]) -> Section:
    have_ele = all(p.ele is not None for p in pieces)
    return Section(
        lat=np.concatenate([p.lat for p in pieces]),
        lon=np.concatenate([p.lon for p in pieces]),
        ele=np.concatenate([p.ele for p in pieces]) if have_ele else None,
        sources=[p.source for p in pieces],
        joins=gaps,
    )


def _closest(anchor, pool: set[int], pieces: list[Piece], from_start: bool):
    """Nearest unused piece to `anchor`, and whether it must be reversed."""
    best = None
    for j in pool:
        p = pieces[j]
        # When growing backwards we want a piece whose END meets our START.
        d_fwd = distance_m(anchor, p.end if from_start else p.start)
        d_rev = distance_m(anchor, p.start if from_start else p.end)
        d, rev = (d_fwd, False) if d_fwd <= d_rev else (d_rev, True)
        if best is None or d < best[0]:
            best = (d, j, rev)
    return best


def chain(pieces: list[Piece], join_m: float) -> list[Section]:
    """Join pieces whose ends meet within `join_m`; return the sections found."""
    if not pieces:
        return []

    unused = set(range(len(pieces)))
    sections: list[Section] = []

    while unused:
        seed = min(unused)
        unused.remove(seed)
        run = [pieces[seed]]
        gaps: list[float] = []

        # Grow forwards off the end, then backwards off the start.
        growing = True
        while growing and unused:
            growing = False
            found = _closest(run[-1].end, unused, pieces, from_start=False)
            if found and found[0] <= join_m:
                d, j, rev = found
                unused.remove(j)
                run.append(pieces[j].reversed() if rev else pieces[j])
                gaps.append(d)
                growing = True

        growing = True
        while growing and unused:
            growing = False
            found = _closest(run[0].start, unused, pieces, from_start=True)
            if found and found[0] <= join_m:
                d, j, rev = found
                unused.remove(j)
                run.insert(0, pieces[j].reversed() if rev else pieces[j])
                gaps.insert(0, d)
                growing = True

        sections.append(_concat(run, gaps))

    # Longest first, so the main route is always section 1.
    sections.sort(key=lambda s: -_length_m(s))
    return sections


def _length_m(section: Section) -> float:
    lat = np.radians(section.lat)
    lon = np.radians(section.lon)
    d = (
        np.sin(np.diff(lat) / 2) ** 2
        + np.cos(lat[:-1]) * np.cos(lat[1:]) * np.sin(np.diff(lon) / 2) ** 2
    )
    return float(np.sum(2 * EARTH_R * np.arcsin(np.sqrt(np.clip(d, 0, 1)))))


def length_m(section: Section) -> float:
    return _length_m(section)
