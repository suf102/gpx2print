"""Mesh construction helpers built on trimesh."""

from __future__ import annotations

import numpy as np
import trimesh


def _quads(i0, i1, i2, i3):
    return np.vstack([np.column_stack([i0, i1, i2]), np.column_stack([i0, i2, i3])])


def heightfield_solid(X, Y, Ztop, z_bottom: float) -> trimesh.Trimesh:
    """Close a regular-grid height surface into a watertight solid.

    X, Y and Ztop are (ny, nx) arrays from meshgrid. The result has the height
    surface on top, a flat floor at `z_bottom`, and vertical skirts joining them.
    """
    ny, nx = Ztop.shape
    if X.shape != Ztop.shape or Y.shape != Ztop.shape:
        raise ValueError("X, Y and Ztop must share a shape")

    Ztop = np.maximum(Ztop, z_bottom + 1e-4)

    idx = np.arange(nx * ny).reshape(ny, nx)
    top = np.column_stack([X.ravel(), Y.ravel(), Ztop.ravel()])
    bot = np.column_stack([X.ravel(), Y.ravel(), np.full(nx * ny, float(z_bottom))])
    verts = np.vstack([top, bot])
    off = nx * ny

    a = idx[:-1, :-1].ravel()
    b = idx[:-1, 1:].ravel()
    c = idx[1:, 1:].ravel()
    d = idx[1:, :-1].ravel()

    faces = [
        _quads(a, b, c, d),
        _quads(a + off, d + off, c + off, b + off),
    ]
    r = idx[0, :]
    faces.append(_quads(r[1:], r[:-1], r[:-1] + off, r[1:] + off))
    r = idx[-1, :]
    faces.append(_quads(r[:-1], r[1:], r[1:] + off, r[:-1] + off))
    c0 = idx[:, 0]
    faces.append(_quads(c0[:-1], c0[1:], c0[1:] + off, c0[:-1] + off))
    c1 = idx[:, -1]
    faces.append(_quads(c1[1:], c1[:-1], c1[:-1] + off, c1[1:] + off))

    mesh = trimesh.Trimesh(verts, np.vstack(faces), process=False)
    mesh.fix_normals()
    return mesh


def extrude(polygon, height: float, z0: float = 0.0) -> trimesh.Trimesh:
    """Extrude a shapely Polygon/MultiPolygon upward, honouring interior holes."""
    from shapely.geometry import MultiPolygon, Polygon

    if isinstance(polygon, Polygon):
        polys = [polygon]
    elif isinstance(polygon, MultiPolygon):
        polys = list(polygon.geoms)
    else:
        polys = [g for g in getattr(polygon, "geoms", []) if isinstance(g, Polygon)]

    parts = []
    for p in polys:
        if p.is_empty or p.area <= 0:
            continue
        m = trimesh.creation.extrude_polygon(p, height=height)
        parts.append(m)

    if not parts:
        raise ValueError("nothing to extrude: the polygon is empty")

    mesh = parts[0] if len(parts) == 1 else trimesh.util.concatenate(parts)
    if z0:
        mesh.apply_translation([0, 0, z0])
    return mesh


def boolean(op: str, meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    meshes = [m for m in meshes if m is not None and len(m.faces) > 0]
    if len(meshes) == 1:
        return meshes[0]
    fn = {
        "difference": trimesh.boolean.difference,
        "union": trimesh.boolean.union,
        "intersection": trimesh.boolean.intersection,
    }[op]
    result = fn(meshes, engine="manifold")
    if isinstance(result, list):
        result = trimesh.util.concatenate(result)
    return result


def largest_component(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Keep only the biggest connected body.

    A track that leaves and re-enters the map window, or a boolean that shaves off a
    sliver, can leave loose crumbs behind that the slicer would happily print.
    """
    parts = mesh.split(only_watertight=False)
    if len(parts) <= 1:
        return mesh
    return max(parts, key=lambda m: abs(m.volume) if m.is_volume else m.area)


def split_components(
    mesh: trimesh.Trimesh, min_volume: float = 2.0
) -> tuple[list[trimesh.Trimesh], int]:
    """Every separate body in the mesh, biggest first, crumbs discarded.

    Cutting a slot right through the map along a closed route detaches the island
    of land inside the loop. Those pieces are wanted, so this keeps them all rather
    than picking a winner.
    """
    parts = list(mesh.split(only_watertight=False))
    if len(parts) <= 1:
        return [mesh], 0
    keep = [p for p in parts if abs(p.volume) >= min_volume]
    if not keep:
        return [max(parts, key=lambda m: abs(m.volume))], len(parts) - 1
    keep.sort(key=lambda m: -abs(m.volume))
    return keep, len(parts) - len(keep)


def drop_small_components(
    mesh: trimesh.Trimesh, min_volume: float
) -> tuple[trimesh.Trimesh, int]:
    parts = mesh.split(only_watertight=False)
    if len(parts) <= 1:
        return mesh, 0
    keep = [p for p in parts if abs(p.volume) >= min_volume]
    if not keep:
        return max(parts, key=lambda m: abs(m.volume)), len(parts) - 1
    if len(keep) == len(parts):
        return mesh, 0
    return trimesh.util.concatenate(keep), len(parts) - len(keep)


def health(mesh: trimesh.Trimesh) -> dict:
    return {
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "volume_mm3": float(mesh.volume) if mesh.is_volume else float("nan"),
        "faces": int(len(mesh.faces)),
        "bodies": int(mesh.body_count),
    }
