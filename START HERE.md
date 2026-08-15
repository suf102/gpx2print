# Making a 3D printed map of your walk

You don't need to know anything technical. Two files come out at the end — one for the
map, one for the coloured route that clips into it — and you print them separately in
two colours.

## 1. Open it

Double-click the one for your computer:

| Your computer | Double-click this |
| --- | --- |
| Mac | **Start Map Maker (Mac).command** |
| Windows | **Start Map Maker (Windows).bat** |
| Linux | **Start Map Maker (Linux).sh** |

A black text window appears first — that's normal, ignore it. The map maker window
opens a moment later.

> **The very first time**, it spends a minute or two installing what it needs. That only
> happens once.

**If it won't open:**

- *Mac — "cannot be opened because it is from an unidentified developer"*: right-click
  the file, choose *Open*, then click *Open* in the box that appears. Only needed once.
- *Windows — a blue "Windows protected your PC" box*: click *More info*, then
  *Run anyway*. Only needed once.
- *Linux — it opens in a text editor instead of running*: the file has lost its
  "may be run" flag, which happens when you download a single file from a website or
  unpack the zip with certain archive managers. **The quickest fix needs no settings
  changed at all**: right-click the folder, choose *Open in Terminal*, and type

      bash "Start Map Maker (Linux).sh"

  To make double-clicking work instead, right-click the file → *Properties* →
  *Permissions* → tick *Allow executing file as program* (KDE: *Is executable*). On
  GNOME that alone still isn't enough — also right-click and choose *Run as a Program*,
  or set Files → *Preferences* → *Executable Text Files* → *Run them*. Downloading the
  **.tar.gz** rather than the .zip usually keeps the flag intact.
- *It says the graphical toolkit is missing*: tkinter is a separate package on most
  Linux distributions, and the launcher prints the exact command for yours — usually
  `sudo apt install python3-tk`.

  **If you use Anaconda or conda** (your terminal prompt starts with `(base)`), that
  command will not help: it installs tkinter for the *system* Python, while conda's
  Python is a different program entirely, so the same message keeps coming back however
  many times you install it. Use `conda install -y tk` instead, or `conda deactivate`
  to step out of conda. The launcher now spots this and tells you which one you need.
- *Either — it says your Python is too old*: it needs 3.10 or newer, and Macs and some
  Linux distributions still ship an older one. Install a current version and run the
  launcher again — it will find the new one on its own.
- *Either — it says Python isn't installed*: get it from
  [python.org/downloads](https://www.python.org/downloads/). **On Windows, tick "Add
  python.exe to PATH" on the first screen of the installer**, or the launcher won't
  find it.

## 2. Fill it in

**1. Your walk**
- *Choose GPX file(s)* — the track from your watch, phone or Strava. You can pick
  **several at once**, or press it again to add more. See below for what happens then.
- *Save into* — where the finished files should go. The Desktop is fine.
- *Name the files* — fills itself in from your first GPX file; change it if you like.

### Walks split across several files

A multi-day walk usually comes as one file per day. Choose them all. Any day that ends
where the next one begins is **joined into a single continuous route** — you don't have
to put them in order, and it doesn't matter if one was recorded walking the other way.

Anything that *doesn't* join up — a separate afternoon walk somewhere else, say —
becomes its **own trail piece**, printed separately in its own colour, on the same map.
So you might end up with:

```
trip_map.3mf      the landscape
trip_trail1.3mf   the main route
trip_trail2.3mf   the side walk
```

Two routes that **cross each other**, or run close enough to touch on the finished
print, are also combined into one piece — they'd otherwise occupy the same space and
neither would fit. You'll see a note when this happens.

The progress box tells you how many pieces you're getting and which files went into
each. If two days that should have joined didn't, raise *Join files closer than* under
*Advanced settings*.

### No walk — just a place

Leave the files alone and type a **coordinate** instead, like `56.7969,-5.0037`, with
how many kilometres of ground to cover. You get the landscape around that spot with no
route on it, as a single piece in one colour. Handy for a hill, a town, or somewhere you
have not walked yet.

**2. How it looks**
- *Map size* — how big the finished thing is, in millimetres, along its longest edge.
  150 mm is about the width of a postcard. Check it fits your printer.
- *Trail line width* — how thick the coloured route looks. 3 mm is a good start.
- *Hill height boost* — real hills are surprisingly flat at this scale, so this
  stretches them upwards. 1 is true to life and looks dull; 2–3 looks like a mountain.
- *Shape of the map* — rectangle, square, circle, triangle, pentagon, hexagon or
  octagon. Whatever you choose is made big enough to hold the whole walk, then scaled
  back to the size you asked for, so nothing is ever cut off.
- *Split into pieces* — leave it at **1** for one whole map. See below if you want a
  map bigger than your printer.
- *Pieces make* — only matters once you've split it. See below.
- *Caption* — text along the edge. A name and a date works nicely.
- *Caption strip* — put it along the bottom or the top.
- *Print the strip as a separate piece* — the strip carries the caption, the
  distance scale and the north arrow, so printing it on its own is how you get
  those in a **second colour**. It comes away along the map's own edge and pushes
  back on with a few tongues, at whatever fit you chose in section 3. You get an
  extra file, `yourname_strip.3mf`.

  On a circle, or the point of a triangle, the edge curves away and there is
  nowhere for a tongue to bite. It says so and the two just butt together, so
  you'll want a dab of glue.
- *Lettering* — **Engraved** cuts the text into the surface, **Raised** makes it stand
  out. Engraved usually prints more neatly, so it's the default. This also changes the
  distance scale and north arrow.

### A map bigger than your printer

Set *Map size* to whatever you actually want — 300 mm, say — and turn *Split into
pieces* up. The map comes out cut into that many smaller copies of its own shape, which
sit back together like tiles. The progress box tells you **how big the largest piece
is**, so you can check it against your printer before spending a day on it.

This only works for **Square, Triangle and Hexagon**, because those are the shapes that
fit together with no gaps. Pick one of those first, or it will tell you it can't.

**Then choose what *Pieces make* should do**, because you can't have both:

- ***Keep the map's shape*** — the map is still a hexagon, cut into a honeycomb. But a
  hexagon only cuts into 7, 13, 19 or 31 (and squares and triangles into 4, 9, 16 or
  25), so you get the nearest and it tells you which. Ask for 6 hexagons and you'll get
  7.
- ***Exactly this many pieces*** — you get the number you asked for, whatever it is, and
  the map's outline becomes whatever those tiles add up to. Six hexagons really are six
  hexagons, all the same size, in a cluster shape.

Six hexagons don't add up to a hexagon, and no amount of arranging will make them —
that's the whole choice. If you want a hexagonal map, keep the shape. If you want an
exact number of identical pieces, choose exactly.

One thing to know about *exactly*: the tiles have to cover the whole walk between them,
and sometimes a particular number wraps it loosely, leaving the route small in a lot of
surrounding countryside. It warns you when that happens and tells you roughly how much
of the print the walk takes up, so you can try a different number.

The route is **not** cut up — it stays one piece and crosses several tiles, which is
what holds them together once you push it in. Print all the tiles, push the route in
last.

**3. How the two parts fit**
- *Fit* — how tightly the route clips into the map. Leave it on **Normal** for now;
  that suits most printers. There are ten settings from *Glued* to *Very sloppy*, so
  if the first attempt is wrong just move one step along the list and reprint the
  trail piece.

  Printers lay their first few layers slightly wider than they should, which makes the
  slot tighter than the number suggests — so if in doubt, go looser rather than tighter.
- *Which way the route goes in* — **From above** drops it into a groove, which is the
  simple choice. **From underneath** cuts the slot right through so the route finishes
  flush with the back of the map.

  Careful with that second one if your walk is a **loop**: going right through cuts the
  middle of the loop free, so the map comes in two pieces. That's unavoidable — nothing
  is holding the middle on any more. Print both; the route slots in and locks them
  together. You'll get `yourname_map1.3mf` and `yourname_map2.3mf` instead of one map.
- *Trail piece shape* — leave on **Flat bottom** unless your route climbs a mountain
  and the trail piece comes out awkwardly tall.

### Settings that go grey

Boxes that cannot affect *this* print grey themselves out as you go. Type a
coordinate instead of choosing files and everything about the trail — its width,
its fit, which way it goes in — goes grey, because there is no trail on that
print. Set a scale and *Map size* goes grey, because the scale decides the size.
Turn off the caption, the distance scale and the north arrow and everything about
the strip goes grey, because there is no strip.

Nothing is hidden and nothing is lost: turn the setting back on and the boxes come
back exactly as you left them. It is only there so you can see at a glance which
numbers are actually doing something.

Everything else is under *Advanced settings* and you can ignore it — though two things
in there are worth knowing about:

- *Distance scale* — a small ruler on the bottom strip showing how far a centimetre of
  map is on the ground ("2 km", say). On by default.
- *North arrow* — an arrow on the bottom strip showing which way is north. On by
  default.
- *Scale 1:* — set the map scale rather than its size. Put 25000 for 1:25,000 and the
  map comes out as big as it needs to be. Leave it at 0 to use the size instead.
- *Altitude offset* — changes the height the hills are measured from. Handy if you are
  printing two neighbouring walks and want them to stand at matching heights.
- *Flatten the sea* — the height data includes the **sea floor**, so a map of
  anywhere coastal otherwise comes out with a trench beside the land, and the hills
  squashed flat to fit both into one model. Tick this and everything below 0 m is
  levelled, so the water reads as a surface. Off by default, because inland it does
  nothing, and somewhere genuinely below sea level and dry — the Netherlands, the
  Dead Sea — it would flatten real land.
- *Route only* — leaves out the landscape entirely. You get the route standing on a
  plain base as an elevation profile: the hills around it are gone, but the route still
  rises and falls with the real ground. The base keeps the caption, scale and arrow.
  This one comes out as **a single file printed in one colour** — the route is already
  joined to its base, so there is nothing to clip together.

Untick either if you'd rather have a cleaner strip with just your caption.

## 3. Look before you leap

Press **Just show me a preview**. You get a picture of the map, the route, the caption
and the hill profile, plus the exact size of both pieces — without making anything.

Change things and press it again until it looks right. It takes a few seconds.

## 4. Make the files

Press **Create print files**. When it finishes you'll have:

```
yourname_map.3mf     the landscape
yourname_trail.3mf   the route that clips into it
yourname_strip.3mf   the caption strip, if you asked for it separately
yourname.png         the preview picture, to keep
```

If your walk came out as more than one piece you'll get `yourname_trail1.3mf`,
`yourname_trail2.3mf` and so on — one per piece, each shown in its own colour on the
preview.

If you split the map into tiles you'll get `yourname_tile1.3mf`, `yourname_tile2.3mf`
and so on instead of one map file. They're numbered left to right, top to bottom, the
same as on the preview.

Press **Open the folder** to find them.

## 5. Print

Open **yourname_map.3mf** in your slicer, load your landscape colour, and print it.

If you asked for the strip separately, **yourname_strip.3mf** is the one to load your
third colour for — or your second, if there's no route. It's flat and thin, so it
prints quickly.

Then open **yourname_trail.3mf**, load your route colour, and print that.

Neither one needs supports. Both already sit flat on the bed, so you shouldn't need to
move or rotate anything.

When they're both done, press the route into the groove in the map. It should need a
firm push.

## If something goes wrong

**"Choose a GPX file first"** — you haven't picked your walk yet.

**It's slow the first time you use a new area** — it's downloading the landscape data.
The next map of the same area is quick.

**The trail piece is really tall and thin** — your route climbs a lot. Turn the *hill
height boost* down to about 1, or switch *Trail piece shape* to *Follows the ground*.
There's a note in the progress box when this happens.

**The route won't push into the map** — reprint just the trail piece with the fit set
one step looser down the list. **It rattles about** — one step tighter. You only need
to reprint the small piece, not the map, and the settings file next to your models
tells you which setting you used last time.

**No internet** — it still works. It uses the height readings recorded in your GPX file
instead, so the landscape around the path is a rough guess rather than real terrain.

## Where the landscape comes from

The hills are real. They're downloaded from **Mapzen Terrain Tiles**, a free open dataset
(a Linux Foundation project, hosted on AWS Open Data) built from government survey data —
US Geological Survey, NASA's shuttle radar, the EU's Copernicus programme, and national
mapping agencies.

Using it comes with one condition: **you have to credit it**. That's done for you — a
small line of text is engraved into the **underside of the map**, so the credit stays
with the object even if the files are long gone. If you split the map into tiles, every
tile gets the whole credit rather than a slice of it, since any one of them might end up
somewhere on its own. Turn the print over and you'll see it
the right way round. It's also written inside both `.3mf` files and printed along the
bottom of the preview picture.

You don't need to do anything about this. Just don't sand it off.

---

*If you'd rather use the terminal, see `README.md` — everything here is also available
as a command line tool with more options.*
