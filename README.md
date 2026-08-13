# gpx2print

Turns a GPX track into a 3D-printable topographic map in **two separate parts**, so
each can be printed in its own colour:

1. **Map** — the terrain around the route, with a channel cut along the path.
2. **Trail** — an insert that drops into that channel. Its top follows the terrain
   surface and stands slightly proud, so the finished route reads as a raised line.

Each part is written to **its own `.3mf`**, sitting on the bed at the origin, ready to
drop straight into the slicer:

```
walk_map.3mf     the terrain plate
walk_trail.3mf   the insert
```

Give it **several GPX files** and legs that end where the next begins are joined into one
continuous path; anything that doesn't connect becomes its own piece, so a multi-day walk
with a rest-day side trip prints as `walk_trail1.3mf`, `walk_trail2.3mf`, … each in its
own colour.

## No terminal? Start here

Double-click the launcher for your computer — **`Start Map Maker (Mac).command`**,
**`Start Map Maker (Windows).bat`** or **`Start Map Maker (Linux).sh`** — for a window
with file pickers and plain English settings. Each one finds Python, installs what it
needs on first run, and opens the window. See **`START HERE.md`** for a walkthrough.

On Linux, if the launcher opens in a text editor rather than running, it has lost its
executable flag — downloading a single file from the web, or unpacking the zip with some
archive managers, strips it. `bash "Start Map Maker (Linux).sh"` works regardless, and
the file's own header explains the permanent fix. The **.tar.gz** download preserves the
flag more reliably than the .zip.

Otherwise the launcher handles the two things that differ on Linux: `tkinter` ships as
a separate package on most distributions, and distributions that mark their Python
"externally managed" refuse a plain `pip install`, so it falls back to a private
`.venv` inside the project folder. Or launch it yourself:

```bash
python3 -m gpx2print.gui
```

## Install

Needs **Python 3.10 or newer**. The launchers check this: macOS ships Python 3.9, and
Debian 11 and RHEL 8 still do, so "a Python exists" is not enough.

```bash
pip install .
```

That gives you a `gpx2print` command. To work on the code instead, use
`pip install -e .`, or just install the dependencies and run it in place:

```bash
pip install -r requirements.txt
python -m gpx2print walk.gpx
```

## Use

```bash
python -m gpx2print walk.gpx -o walk.3mf --preview walk.png
```

`-o` is a base name — you get `walk_map.3mf` and `walk_trail.3mf`. Add `--combined` if
you also want a single file holding both parts side by side.

With everything turned on:

```bash
python -m gpx2print walk.gpx -o walk.3mf --size 180 --z-scale 2.5 --tolerance 0.25 --caption "Ben Nevis · 12 May 2026" --preview walk.png
```

Preview only, without building meshes:

```bash
python -m gpx2print walk.gpx --dry-run --preview walk.png
```

## The options that matter

| Option | Default | What it does |
| --- | --- | --- |
| `--size MM` | 150 | Longest edge of the map. Everything else scales with it. |
| `--join-distance M` | 200 | How close two ends must be to be joined into one path (ground metres). |
| `--merge-distance MM` | 2.0 | Sections that cross or come this close on the print become one piece. |
| `--trail-width MM` | 3.0 | **Width of the printed trail line.** |
| `--tolerance MM` | 0.3 | **Clearance per side** between channel and insert. Total slop is twice this. |
| `--z-scale N` | 1.75 | Vertical exaggeration. True-to-life (1.0) almost always looks flat. |
| `--max-relief MM` | — | Force the terrain to exactly this height, ignoring `--z-scale`. |
| `--caption TEXT` | — | Text on a plinth below the map. |
| `--caption-style` | deboss | `deboss` cuts the lettering in, `emboss` raises it. Also affects the scale bar and north arrow. |
| `--no-scale-bar` | on | Drop the chequered distance scale. |
| `--no-north-arrow` | on | Drop the north arrow. |
| `--route-only` | off | Drop the landscape: just the route on a flat base. |
| `--margin F` | 0.15 | How much terrain to show around the track, as a fraction of its extent. |
| `--trail-entry` | top | `top` drops the route into a groove; `bottom` pushes it up through a slot cut right through. |
| `--trail-base` | flat | `flat` prints without support; `follow` is compact but needs support. |
| `--combined` | off | Also write one `.3mf` containing both parts. |
| `--layout` | separate | `separate` puts each part at the origin; `assembled` keeps true positions so loading both shows the fit. |

Run `python -m gpx2print --help` for the rest.

### Trail line width

`--trail-width` is the width of the visible line, in millimetres:

```bash
python -m gpx2print walk.gpx --trail-width 5      # a bold 5 mm route
python -m gpx2print walk.gpx --trail-width 1.5    # a fine line
```

The channel in the map is widened from it by the tolerance, so the two settings are
independent — loosening the fit never makes the trail look thinner.

Below about 1.2 mm the insert gets fragile and the tool says so. Wide lines are safe;
they just swallow more detail on tight switchbacks.

### Several files at once

```bash
python -m gpx2print day1.gpx day2.gpx day3.gpx -o trip.3mf --caption "Cape Wrath Trail"
```

Every contiguous run of points, across every file, is treated as a piece. Pieces whose
ends fall within `--join-distance` of each other are joined end to end; the rest stay
apart. What survives is a set of **sections**, longest first, and each section becomes
its own printable insert sharing one map.

The joining works on parsed coordinates rather than by splicing the XML together, which
means the files can be given in **any order**, a leg recorded in the **opposite
direction** still joins (it is reversed automatically), and nothing depends on the files
sharing a schema or namespace. Gaps that are bridged are reported, so you can see how
far apart the ends actually were.

Raise `--join-distance` to pull separate walks together; set it to `0` to keep every
piece separate.

**Sections that meet their ends are only half the problem.** Two routes can start and
finish miles apart and still cross in the middle, or run alongside each other. Since
every insert spans the same range of heights, two that cross occupy *the same volume* —
they could not both be fitted, and printing them as separate parts would be meaningless.
Two that merely pass very close leave a wall of map between them too thin to survive.

So after the ends are chained, the printed footprints are checked again: anything that
touches, crosses, or comes within `--merge-distance` (2 mm by default) is merged into a
single piece, with any sub-threshold gap bridged so the result is one connected line.
The merge is transitive — if B crosses A and C runs close to A, all three become one
piece. It's reported in the output whenever it happens.

Note the two settings work in different units, because they answer different questions:
`--join-distance` is **ground metres** (were these recorded as one walk?), while
`--merge-distance` is **millimetres on the print** (can these be separate objects?).

### Raised or engraved lettering

```bash
python -m gpx2print walk.gpx --caption "Ben Nevis" --caption-style emboss
```

`deboss` (the default) cuts the caption, scale bar and north arrow **into** the plinth;
`emboss` raises them above it. Engraved is the default because it prints more cleanly:
small raised letters sit on top of the surface where the nozzle can drag and smear them,
whereas a groove is formed by the perimeters printed around it. `--caption-depth` sets
how deep it is cut or how far it stands up.

### Route only

```bash
python -m gpx2print walk.gpx --route-only --caption "Ben Nevis"
```

Leaves out the surrounding landscape. You get a flat base carrying the caption, scale
bar and north arrow, and the route standing on it as a fin whose top edge is the real
elevation profile of the walk — the ground is gone, the height is not.

**This mode writes a single file.** The route is welded to its base and comes out as one
connected solid, so there is no channel, no insert and no clearance to get right: you
open one `.3mf` and print it in one colour. Separate sections of a multi-day walk are
all fused to the same base, so even a route in several disconnected pieces stays a
single object.

`--trail-base follow`, `--tolerance` and `--combined` have nothing to act on here and
are ignored.

### Fitting the route from underneath

```bash
python -m gpx2print loop.gpx --trail-entry bottom
```

By default the slot is cut from above and the route drops in. With `--trail-entry
bottom` the slot goes **right through** the map and the route is pushed up from
underneath, finishing flush with the back.

**A route that closes on itself then cuts the map into pieces.** A loop separates the
land inside it from the land outside, and once the slot passes right through there is
nothing joining them. That is geometry, not a fault: the tool detects it, writes each
piece as `_map1.3mf`, `_map2.3mf`, … and says so. Fit the route and it keys the pieces
back together like an inlay. The same happens if a route crosses the map from edge to
edge.

An open route that stays inside the map leaves it in one piece, exactly as before.

`--trail-base follow` is ignored here, since the route has to reach the bottom of the
map to be pushed through it.

### The plinth

The strip below the terrain is the map's margin. It carries, from left to right, a
chequered **scale bar** with its ground distance written above it, the **caption**, and
a **north arrow**. All three are on by default and each can be turned off; the plinth
itself appears if any of them is wanted.

They sit on the plinth rather than on the terrain deliberately — a scale bar draped over
a hillside is neither straight nor measurable, which defeats the point of having one.

The scale bar always represents a round distance (1 km, 500 m, 250 m…) chosen to fit the
space, so it stays honest at any `--size`. North is straight up the print: the projection
keeps meridians vertical.

### Getting the fit right

`--tolerance` is the gap on **each** side, so the total slack is twice it. The default
is **0.3 mm per side (0.6 mm total)**, which suits a typical hobby FDM printer.

| Per side | Feel | Suits |
| --- | --- | --- |
| 0.00 | no gap at all | glue it in |
| 0.10–0.15 | firm push fit | resin, or a well-tuned FDM printer |
| 0.20 | needs a shove | a good FDM printer |
| **0.30** | **normal** | **most FDM printers** |
| 0.40 | goes in easily | slightly over-extruding printers |
| 0.55–0.70 | drops in with room | a printer you don't trust |
| 0.90–1.20 | visible gap | rough prints, or when you plan to glue |

**Why the number always feels tighter than it reads.** The first few layers of both
parts spread outwards under the weight of the nozzle — elephant's foot — so the insert
is fattest exactly where the slot is narrowest. A nominal 0.2 mm can end up as nothing
at all at the bottom of the channel. That is why the default is more generous than the
geometry alone would suggest.

Print the pair once and adjust one step at a time. The value you used is written into
the settings file next to the models, so you don't have to remember it.

The channel and insert are generated from the same path, so the clearance is exact and
constant along the whole route — measured across the range at 30 points per build, every
setting from 0.00 to 1.20 mm lands on its target. Changing `--tolerance` never changes
how thick the trail looks.

### flat vs follow

`--trail-base flat` gives the insert a **flat bottom** at one height, so it prints
straight onto the bed with no support. On a route that climbs a lot, that makes the
insert a tall thin ribbon; the tool warns when it gets extreme.

`--trail-base follow` keeps the insert a constant thickness that follows the ground, so
it stays small — but its underside is curved and needs support.

If the flat insert comes out too tall, lower `--z-scale` or set `--max-relief 20`.

## Elevation data

By default the terrain comes from **Mapzen Terrain Tiles** (the `terrarium` format) —
an open dataset from the [Tilezen/joerd](https://github.com/tilezen/joerd) project, now
under the Linux Foundation, published through the
[AWS Registry of Open Data](https://registry.opendata.aws/terrain-tiles/). It is built
from USGS 3DEP, SRTM, Copernicus EU-DEM and a range of national elevation models. No API
key; tiles are cached under `~/.cache/gpx2print`.

**Attribution is required** when you use this data, and a printed object carries none of
a file's metadata — so the credit is **engraved into the underside of the map** by
default, mirrored to read correctly when you turn the print over. It also goes into the
`Copyright` and `LicenseTerms` fields of both `.3mf` files, along the bottom of the
preview image, and to the terminal on every build.

The engraving wraps onto as many lines as it needs to stay above roughly 2.4 mm cap
height, and drops to shorter wording on small maps rather than shrinking into something
a 0.4 mm nozzle cannot cut. `--credit-height` nudges the size; `--no-credit` removes it,
in which case the licence still applies and you must credit the data another way. The
full per-country attribution list is
[here](https://github.com/tilezen/joerd/blob/master/docs/attribution.md).

**One caveat worth knowing.** We read the S3 bucket directly, but joerd's own docs say
the S3 endpoint is "meant for efficient networking with EC2 resources only" — the
intended public entry point was `tile.mapzen.com`, which shut down with Mapzen in 2018.
Direct bucket access is now the only route and is widely used, but it is undocumented
for this purpose and carries no availability guarantee. If it ever disappears, switch to
`--dem-source opentopodata`, which is a public API designed to be called this way.

Alternatives via `--dem-source`:

- `opentopodata` — the public point API. Rate limited to 1 request/sec, so it samples
  coarsely and interpolates.
- `gpx` — builds the surface from the track's own elevations. Works offline, but is only
  meaningful near the path itself.
- `flat` — no terrain at all.

If tile fetching fails, it falls back to the track's elevations automatically.

## Printing

Open `<name>_map.3mf` and `<name>_trail.3mf` as two separate jobs and load a different
filament for each. The map has no overhangs. The insert (in `flat` mode) sits on its own
flat bottom and needs no support.

The caption plinth is a good first-layer anchor — keep it flat on the bed.

Cura ignores the 3MF material colour, so each file just loads as one model — which is
exactly what you want here. `--stl` writes the same two parts as STL instead.

## Layout

```
gpx2print/
  cli.py        argument parsing and orchestration
  config.py     every build parameter, with defaults
  gpx_io.py     GPX parsing, local projection, framing
  dem.py        elevation sources and caching
  build.py      the geometry pipeline
  meshlib.py    heightfield solids, extrusion, booleans
  text3d.py     caption outlines to solid lettering
  threemf.py    3MF container with per-object colour
  preview.py    the preview image
examples/
  ben_nevis.gpx sample route
```

## Licence

MIT — see [LICENSE](LICENSE). Use it, change it, sell it; just keep the copyright
notice.

Two things the licence does **not** cover:

- **The elevation data.** Mapzen Terrain Tiles carry their own attribution
  requirement, which is why the credit is engraved into every print. See
  [Elevation data](#elevation-data) above.
- **Your GPX files.** Nothing is uploaded anywhere. The only network traffic is
  fetching public terrain tiles for the area you are mapping, cached locally
  afterwards.
