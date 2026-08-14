"""Minimal 3MF writer with one coloured object per printable part.

trimesh can export 3MF, but it drops material colour. Writing the container by
hand keeps each part as its own named object with a base colour, which is what
lets a slicer assign a different filament to the map and to the trail.
"""

from __future__ import annotations

import zipfile
from xml.sax.saxutils import escape

import numpy as np

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
MODEL_REL = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"

IDENTITY = "1 0 0 0 1 0 0 0 1 0 0 0"


def _hex_rgba(color: str) -> str:
    c = color.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) == 6:
        c += "FF"
    if len(c) != 8:
        raise ValueError(f"colour {color!r} is not a #RRGGBB or #RRGGBBAA value")
    return "#" + c.upper()


def _settle(mesh, decimals: int):
    """The mesh as it will actually exist once written at this precision.

    Rounding is not a formatting detail: it can land two vertices on the same
    point, and any triangle that had both of them becomes a line with no area.
    Left in the file those show up as holes in a mesh that was watertight in
    memory. Doing the rounding here, then merging what it made identical and
    dropping the triangles that collapsed, means the file holds a solid — and
    that re-reading it checks the same geometry the writer decided on.
    """
    v = np.round(np.asarray(mesh.vertices, dtype=float), decimals)
    # Negative zero prints differently and compares as a different set of bytes,
    # so two vertices on the same point would survive as two.
    v[v == 0] = 0.0
    f = np.asarray(mesh.faces, dtype=np.int64)

    v, inverse = np.unique(v, axis=0, return_inverse=True)
    f = inverse.reshape(-1)[f]
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 2] != f[:, 0])]

    used, f = np.unique(f, return_inverse=True)
    return v[used], f.reshape(-1, 3)


def _mesh_xml(mesh, decimals: int = 6) -> str:
    # 4 decimals looks like ample precision for millimetres, but boolean output
    # routinely puts vertices closer together than 0.1 micron. Rounding welds those
    # into degenerate triangles and punches holes in an otherwise watertight mesh.
    v, f = _settle(mesh, decimals)

    vfmt = f'<vertex x="%.{decimals}f" y="%.{decimals}f" z="%.{decimals}f"/>'
    verts = "".join([vfmt % (a, b, c) for a, b, c in v])
    tris = "".join(['<triangle v1="%d" v2="%d" v3="%d"/>' % (a, b, c) for a, b, c in f])
    return f"<mesh><vertices>{verts}</vertices><triangles>{tris}</triangles></mesh>"


def _transform(offset) -> str:
    if offset is None:
        return IDENTITY
    x, y, z = offset
    return f"1 0 0 0 1 0 0 0 1 {x:.4f} {y:.4f} {z:.4f}"


def write_3mf(path: str, parts: list[dict], metadata: dict | None = None) -> None:
    """Write `parts` to a 3MF file.

    Each part is a dict with keys: mesh, name, color, and an optional offset
    applied by the build item rather than baked into the vertices.
    """
    if not parts:
        raise ValueError("no parts to write")

    materials = "".join(
        f'<base name="{escape(p["name"])}" '
        f'displaycolor="{_hex_rgba(p["color"])}"/>'
        for p in parts
    )

    objects = []
    items = []
    for i, p in enumerate(parts):
        oid = i + 2  # id 1 is the base material group
        objects.append(
            f'<object id="{oid}" type="model" name="{escape(p["name"])}" '
            f'pid="1" pindex="{i}">{_mesh_xml(p["mesh"])}</object>'
        )
        items.append(
            f'<item objectid="{oid}" transform="{_transform(p.get("offset"))}" '
            f'printable="1"/>'
        )

    meta = {"Application": "gpx2print", "Title": "GPX topographic map"}
    meta.update(metadata or {})
    meta_xml = "".join(
        f'<metadata name="{escape(k)}">{escape(str(v))}</metadata>'
        for k, v in meta.items()
        if v is not None
    )

    model = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<model unit="millimeter" xml:lang="en-US" xmlns="{CORE_NS}">'
        f"{meta_xml}"
        "<resources>"
        f'<basematerials id="1">{materials}</basematerials>'
        f'{"".join(objects)}'
        "</resources>"
        f'<build>{"".join(items)}</build>'
        "</model>"
    )

    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{REL_NS}">'
        f'<Relationship Id="rel0" Type="{MODEL_REL}" Target="/3D/3dmodel.model"/>'
        "</Relationships>"
    )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Types xmlns="{CT_NS}">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" '
        'ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        "</Types>"
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
