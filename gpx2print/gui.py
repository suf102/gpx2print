"""A window for making printable maps without touching a terminal.

Built on tkinter so it runs on a stock Python with nothing extra to install.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import tempfile
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .config import Config

PAD = 10
HINT = "#6b7280"
ACCENT = "#B4472B"


class Row:
    """A labelled number box with a one-line explanation underneath."""

    def __init__(self, parent, label, value, hint, frm, to, step, fmt="%.2f", width=7):
        self.var = tk.DoubleVar(value=value)
        line = ttk.Frame(parent)
        line.pack(fill="x", pady=(6, 0))
        ttk.Label(line, text=label).pack(side="left")
        self.spin = ttk.Spinbox(
            line,
            from_=frm,
            to=to,
            increment=step,
            textvariable=self.var,
            width=width,
            format=fmt,
        )
        self.spin.pack(side="right")
        ttk.Label(parent, text=hint, foreground=HINT, font=("", 10)).pack(
            anchor="w", pady=(0, 2)
        )

    def get(self) -> float:
        return float(self.var.get())


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GPX → 3D printed map")
        self.geometry("1120x780")
        # The settings column scrolls, so the window can be shorter than its content.
        self.minsize(940, 520)

        self.queue: queue.Queue = queue.Queue()
        self.busy = False
        self.build_result = None
        self.preview_img = None
        self.written: list[str] = []

        style = ttk.Style(self)
        if "aqua" in style.theme_names():
            style.theme_use("aqua")
        style.configure("Go.TButton", font=("", 13, "bold"))

        self._build_ui()
        self.after(80, self._pump)

    # ------------------------------------------------------------------ layout
    def _build_ui(self):
        outer = ttk.Frame(self, padding=PAD)
        outer.pack(fill="both", expand=True)

        left = ttk.Frame(outer, width=446)
        left.pack(side="left", fill="y", padx=(0, PAD))
        left.pack_propagate(False)

        right = ttk.Frame(outer)
        right.pack(side="left", fill="both", expand=True)

        # The buttons are pinned to the bottom and packed first, so they keep their
        # room; only the settings above them scroll.
        self._section_actions(left)
        panel = self._scrollable(left)

        self._section_route(panel)
        self._section_look(panel)
        self._section_fit(panel)
        self._section_advanced(panel)
        self._section_preview(right)

    def _scrollable(self, parent):
        """A vertically scrolling column. Returns the frame to put content in."""
        wrap = ttk.Frame(parent)
        wrap.pack(side="top", fill="both", expand=True)

        canvas = tk.Canvas(
            wrap, highlightthickness=0, bd=0, background=self.cget("background")
        )
        bar = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_content(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas(event):
            # Keep the content the width of the canvas so rows still fill across.
            canvas.itemconfigure(window, width=event.width)

        inner.bind("<Configure>", on_content)
        canvas.bind("<Configure>", on_canvas)

        self._scroll_canvas = canvas
        self._scroll_inner = inner
        self._bind_wheel(canvas)
        return inner

    def _bind_wheel(self, canvas):
        """Wheel scrolling, but only while the pointer is over this column."""
        def scroll(event):
            if not self._can_scroll(canvas):
                return
            if getattr(event, "num", None) == 4:
                canvas.yview_scroll(-3, "units")
            elif getattr(event, "num", None) == 5:
                canvas.yview_scroll(3, "units")
            else:
                delta = event.delta
                # Windows reports multiples of 120; macOS reports small numbers.
                step = -int(delta / 120) if abs(delta) >= 120 else -int(delta)
                canvas.yview_scroll(step or (-1 if delta > 0 else 1), "units")

        def enter(_e):
            canvas.bind_all("<MouseWheel>", scroll)
            canvas.bind_all("<Button-4>", scroll)
            canvas.bind_all("<Button-5>", scroll)

        def leave(_e):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", enter)
        canvas.bind("<Leave>", leave)

    @staticmethod
    def _can_scroll(canvas) -> bool:
        region = canvas.bbox("all")
        return bool(region) and (region[3] - region[1]) > canvas.winfo_height()

    def _group(self, parent, title):
        f = ttk.LabelFrame(parent, text=title, padding=(PAD, 6, PAD, 8))
        f.pack(fill="x", pady=(0, 8))
        return f

    def _section_route(self, parent):
        g = self._group(parent, "1.  Your walk")

        self.gpx_files: list[str] = []
        line = ttk.Frame(g)
        line.pack(fill="x")
        ttk.Button(line, text="Choose GPX file(s)…", command=self._pick_gpx).pack(
            side="left"
        )
        ttk.Button(line, text="Clear", command=self._clear_gpx).pack(
            side="left", padx=(6, 0)
        )
        self.gpx_label = ttk.Label(line, text="no files chosen", foreground=HINT)
        self.gpx_label.pack(side="left", padx=(8, 0))

        self.file_list = tk.Listbox(
            g, height=3, font=("", 11), relief="flat", highlightthickness=1,
            highlightbackground="#d9d4cc", activestyle="none",
        )
        self.file_list.pack(fill="x", pady=(5, 0))
        ttk.Label(
            g,
            text="Pick several at once for a multi-day walk. Days that end where "
                 "the next begins are joined; the rest become separate pieces.",
            foreground=HINT, font=("", 10), wraplength=390, justify="left",
        ).pack(anchor="w", pady=(2, 0))

        ttk.Separator(g).pack(fill="x", pady=(9, 5))
        ttk.Label(g, text="…or no walk at all: just a place",
                  foreground=HINT, font=("", 10, "bold")).pack(anchor="w")
        line = ttk.Frame(g)
        line.pack(fill="x", pady=(3, 0))
        ttk.Label(line, text="Coordinate").pack(side="left")
        self.at_var = tk.StringVar(value="")
        ttk.Entry(line, textvariable=self.at_var, width=22).pack(side="right")
        line = ttk.Frame(g)
        line.pack(fill="x", pady=(4, 0))
        ttk.Label(line, text="Ground covered (km)").pack(side="left")
        self.across_var = tk.DoubleVar(value=5.0)
        ttk.Spinbox(line, from_=0.2, to=200, increment=1, width=7,
                    textvariable=self.across_var, format="%.1f").pack(side="right")
        ttk.Label(
            g,
            text="Type a latitude and longitude, like 56.7969,-5.0037, to print the "
                 "landscape around a place with no route on it. Leave it blank if "
                 "you chose files above.",
            foreground=HINT, font=("", 10), wraplength=390, justify="left",
        ).pack(anchor="w", pady=(2, 0))

        self.out_var = tk.StringVar(value=str(Path.home() / "Desktop"))
        line = ttk.Frame(g)
        line.pack(fill="x", pady=(8, 0))
        ttk.Button(line, text="Save into…", command=self._pick_out).pack(side="left")
        self.out_label = ttk.Label(line, text="Desktop", foreground=HINT)
        self.out_label.pack(side="left", padx=(8, 0))

        line = ttk.Frame(g)
        line.pack(fill="x", pady=(8, 0))
        ttk.Label(line, text="Name the files").pack(side="left")
        self.name_var = tk.StringVar(value="")
        ttk.Entry(line, textvariable=self.name_var, width=22).pack(side="right")

    def _section_look(self, parent):
        g = self._group(parent, "2.  How it looks")

        self.size = Row(g, "Map size (mm)", 150, "Longest edge of the finished map.",
                        40, 400, 5, "%.0f")
        self.width = Row(g, "Trail line width (mm)", 3.0,
                         "How thick the coloured route looks.", 0.6, 12, 0.2)
        self.zscale = Row(g, "Hill height boost", 1.75,
                          "1 is true to life, which looks flat. 2–3 is dramatic.",
                          0.5, 8, 0.25)

        self.shape_var = tk.StringVar(value="Rectangle")
        line = ttk.Frame(g)
        line.pack(fill="x", pady=(6, 0))
        ttk.Label(line, text="Shape of the map").pack(side="left")
        ttk.Combobox(
            line, textvariable=self.shape_var, state="readonly", width=16,
            values=["Rectangle", "Square", "Circle", "Triangle", "Pentagon",
                    "Hexagon", "Octagon"],
        ).pack(side="right")
        ttk.Label(g, text="Anything but a rectangle is grown until the whole walk "
                          "fits inside it, then scaled back to the size above.",
                  foreground=HINT, font=("", 10), wraplength=390,
                  justify="left").pack(anchor="w", pady=(0, 2))

        self.cap_on = tk.BooleanVar(value=True)
        ttk.Checkbutton(g, text="Add a caption along the bottom",
                        variable=self.cap_on, command=self._toggle_caption).pack(
            anchor="w", pady=(8, 2))
        self.cap_var = tk.StringVar(value="")
        self.cap_entry = ttk.Entry(g, textvariable=self.cap_var)
        self.cap_entry.pack(fill="x")
        ttk.Label(g, text="Name, date, distance — whatever you like.",
                  foreground=HINT, font=("", 10)).pack(anchor="w")

        self.cap_pos_var = tk.StringVar(value="Along the bottom")
        line = ttk.Frame(g)
        line.pack(fill="x", pady=(6, 0))
        ttk.Label(line, text="Caption strip").pack(side="left")
        ttk.Combobox(
            line, textvariable=self.cap_pos_var, state="readonly", width=16,
            values=["Along the bottom", "Along the top"],
        ).pack(side="right")

        self.cut_var = tk.StringVar(value="Engraved — cut into the surface")
        line = ttk.Frame(g)
        line.pack(fill="x", pady=(6, 0))
        ttk.Label(line, text="Lettering").pack(side="left")
        self.cut_box = ttk.Combobox(
            line, textvariable=self.cut_var, state="readonly", width=30,
            values=[
                "Engraved — cut into the surface",
                "Raised — stands out from the surface",
            ],
        )
        self.cut_box.pack(side="right")
        ttk.Label(
            g,
            text="Engraved usually prints more cleanly: the nozzle can smear small "
                 "raised letters. This also applies to the scale and north arrow.",
            foreground=HINT, font=("", 10), wraplength=390, justify="left",
        ).pack(anchor="w", pady=(0, 2))

    def _section_fit(self, parent):
        g = self._group(parent, "3.  How the two parts fit")

        self.fit_var = tk.StringVar(value="Normal — most FDM printers (0.30 mm)")
        ttk.Label(g, text="Fit between the trail and its slot").pack(anchor="w")
        self.fit_box = ttk.Combobox(
            g, textvariable=self.fit_var, state="readonly",
            values=[
                "Glued — no gap at all (0.00 mm)",
                "Very tight — resin or a dialled-in printer (0.10 mm)",
                "Tight — firm push fit (0.15 mm)",
                "Snug — needs a shove (0.20 mm)",
                "Normal — most FDM printers (0.30 mm)",
                "Relaxed — goes in easily (0.40 mm)",
                "Loose — drops in with room (0.55 mm)",
                "Very loose — a visible gap (0.70 mm)",
                "Sloppy — for a rough printer (0.90 mm)",
                "Very sloppy — glue it in (1.20 mm)",
            ],
        )
        self.fit_box.pack(fill="x", pady=(2, 0))
        ttk.Label(
            g,
            text="Too tight to push in? Pick the next one down the list. Rattles "
                 "about? Pick the one above. First layers bulge slightly on most "
                 "printers, so the slot is always a little tighter than the number.",
            foreground=HINT, font=("", 10), wraplength=390, justify="left",
        ).pack(anchor="w", pady=(0, 4))

        self.entry_var = tk.StringVar(value="From above — drops into a groove")
        ttk.Label(g, text="Which way the route goes in").pack(anchor="w", pady=(6, 0))
        ttk.Combobox(
            g, textvariable=self.entry_var, state="readonly",
            values=[
                "From above — drops into a groove",
                "From underneath — pushed up through the map",
            ],
        ).pack(fill="x", pady=(2, 0))
        ttk.Label(
            g,
            text="From underneath, the slot goes right through, so the route "
                 "finishes flush with the back. A walk that returns to where it "
                 "started then cuts the middle free and the map arrives in two "
                 "pieces — the route locks them together.",
            foreground=HINT, font=("", 10), wraplength=390, justify="left",
        ).pack(anchor="w", pady=(0, 4))

        self.style_var = tk.StringVar(value="Flat bottom — no supports needed")
        ttk.Label(g, text="Trail piece shape").pack(anchor="w", pady=(6, 0))
        ttk.Combobox(
            g, textvariable=self.style_var, state="readonly",
            values=[
                "Flat bottom — no supports needed",
                "Follows the ground — smaller, needs supports",
            ],
        ).pack(fill="x", pady=(2, 0))

    def _section_advanced(self, parent):
        self.adv_open = tk.BooleanVar(value=False)
        self.adv_btn = ttk.Checkbutton(
            parent, text="Advanced settings", variable=self.adv_open,
            command=self._toggle_adv, style="Toolbutton",
        )
        self.adv_btn.pack(anchor="w", pady=(0, 4))

        self.adv = ttk.Frame(parent)
        g = self.adv

        self.base = Row(g, "Base thickness (mm)", 5.0,
                        "Solid slab under the lowest ground.", 1, 30, 0.5, "%.1f")
        self.thick = Row(g, "Trail piece thickness (mm)", 3.0,
                         "How deep the insert sits in its slot.", 1, 20, 0.5, "%.1f")
        self.proud = Row(g, "Trail sticks up by (mm)", 0.8,
                         "How far the route stands above the ground.", 0, 5, 0.1,
                         "%.1f")
        self.margin = Row(g, "Land around the walk", 0.15,
                          "0.15 shows a bit of surrounding country.", 0, 1.5, 0.05,
                          "%.2f")
        self.detail = Row(g, "Terrain detail", 260,
                          "Higher is finer but slower. 150–400 is sensible.",
                          60, 700, 20, "%.0f")

        self.scale = Row(g, "Scale 1 : (0 = use size)", 0,
                         "Set the map scale instead of the size. 25000 gives "
                         "1:25,000 and the plate comes out as big as it needs to.",
                         0, 2000000, 5000, "%.0f", width=9)
        self.alt = Row(g, "Altitude offset (m)", 0,
                       "Moves the height the relief is measured from. Positive "
                       "flattens low ground; useful for matching neighbouring maps.",
                       -3000, 6000, 50, "%.0f", width=9)

        self.join = Row(g, "Join files closer than (m)", 200,
                        "Ends nearer than this become one continuous path.",
                        0, 5000, 25, "%.0f")
        self.merge = Row(g, "Merge lines closer than (mm)", 2.0,
                         "Routes that cross or nearly touch print as one piece.",
                         0, 20, 0.5, "%.1f")

        ttk.Separator(g).pack(fill="x", pady=(10, 6))

        self.scale_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(g, text="Distance scale on the bottom strip",
                        variable=self.scale_var).pack(anchor="w")
        self.north_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(g, text="North arrow on the bottom strip",
                        variable=self.north_var).pack(anchor="w")
        ttk.Label(g, text="Both sit on the flat strip below the map, beside the "
                          "caption.", foreground=HINT, font=("", 10),
                  wraplength=390, justify="left").pack(anchor="w", pady=(0, 2))

        ttk.Separator(g).pack(fill="x", pady=(10, 6))

        self.route_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(g, text="Route only \u2014 no surrounding landscape",
                        variable=self.route_only_var).pack(anchor="w")
        ttk.Label(g, text="The route stands on a flat base as an elevation profile. "
                          "The base still carries the caption, scale and arrow.",
                  foreground=HINT, font=("", 10), wraplength=390,
                  justify="left").pack(anchor="w", pady=(0, 6))

        self.stl_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(g, text="Also save STL files", variable=self.stl_var).pack(
            anchor="w")

    def _section_actions(self, parent):
        f = ttk.Frame(parent)
        f.pack(fill="x", side="bottom", pady=(8, 0))

        self.progress = ttk.Progressbar(f, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 6))

        self.go_btn = ttk.Button(f, text="Create print files",
                                 command=lambda: self._run(export=True),
                                 style="Go.TButton")
        self.go_btn.pack(fill="x", ipady=4)
        self.prev_btn = ttk.Button(f, text="Just show me a preview",
                                   command=lambda: self._run(export=False))
        self.prev_btn.pack(fill="x", pady=(6, 0))
        self.open_btn = ttk.Button(f, text="Open the folder",
                                   command=self._open_folder, state="disabled")
        self.open_btn.pack(fill="x", pady=(6, 0))

    def _section_preview(self, parent):
        self.canvas = tk.Canvas(parent, bg="#f3f1ec", highlightthickness=1,
                                highlightbackground="#d9d4cc")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._draw_preview())
        self._placeholder()

        ttk.Label(parent, text="Progress", foreground=HINT).pack(
            anchor="w", pady=(8, 2))
        self.log = tk.Text(parent, height=9, wrap="word", font=("Menlo", 11),
                           bg="#fbfaf8", relief="flat", highlightthickness=1,
                           highlightbackground="#d9d4cc")
        self.log.pack(fill="x")
        self.log.configure(state="disabled")

    # ----------------------------------------------------------------- helpers
    def _placeholder(self):
        self.canvas.delete("all")
        w = self.canvas.winfo_width() or 600
        h = self.canvas.winfo_height() or 400
        self.canvas.create_text(
            w // 2, h // 2 - 12, text="Choose a GPX file, then press Preview",
            fill="#9aa0a6", font=("", 15),
        )
        self.canvas.create_text(
            w // 2, h // 2 + 14,
            text="you'll see the map before anything is made",
            fill="#b6bbc0", font=("", 12),
        )

    def _toggle_caption(self):
        on = "normal" if self.cap_on.get() else "disabled"
        self.cap_entry.configure(state=on)
        # The lettering style still drives the scale bar and north arrow, so it
        # stays usable even with the caption switched off.
        self.cut_box.configure(state="readonly")

    def _toggle_adv(self):
        if self.adv_open.get():
            self.adv.pack(fill="x", pady=(0, 8))
        else:
            self.adv.pack_forget()

        canvas = getattr(self, "_scroll_canvas", None)
        if canvas is None:
            return
        self.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))
        if self.adv_open.get():
            # Scroll the newly revealed settings into view rather than leaving the
            # user staring at an unchanged screen with content hidden below.
            total = max(self._scroll_inner.winfo_height(), 1)
            canvas.yview_moveto(min(1.0, max(0.0, self.adv_btn.winfo_y() / total)))

    def _say(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _pick_gpx(self):
        chosen = filedialog.askopenfilenames(
            title="Choose one or more GPX files",
            filetypes=[("GPX tracks", "*.gpx"), ("All files", "*.*")],
        )
        if not chosen:
            return
        for p in chosen:
            if p not in self.gpx_files:
                self.gpx_files.append(p)
        self._refresh_files()

        first = Path(self.gpx_files[0])
        if not self.name_var.get():
            self.name_var.set(first.stem)
        if not self.cap_var.get():
            self.cap_var.set(first.stem.replace("_", " ").title())

    def _clear_gpx(self):
        self.gpx_files = []
        self._refresh_files()

    def _refresh_files(self):
        self.file_list.delete(0, "end")
        for p in self.gpx_files:
            self.file_list.insert("end", f"  {Path(p).name}")
        n = len(self.gpx_files)
        self.gpx_label.configure(
            text="no files chosen" if n == 0 else f"{n} file{'s' if n > 1 else ''}",
            foreground=HINT if n == 0 else "black",
        )

    def _pick_out(self):
        p = filedialog.askdirectory(title="Where should the files be saved?")
        if p:
            self.out_var.set(p)
            self.out_label.configure(text=Path(p).name or p, foreground="black")

    def _open_folder(self):
        folder = self.out_var.get()
        if sys.platform == "darwin":
            subprocess.run(["open", folder], check=False)
        elif os.name == "nt":
            os.startfile(folder)  # noqa: S606
        else:
            subprocess.run(["xdg-open", folder], check=False)

    # -------------------------------------------------------------- the config
    def _collect(self) -> Config:
        at = self.at_var.get().strip()
        if not self.gpx_files and not at:
            raise ValueError(
                "Choose a GPX file, or type a coordinate to make a map of a place "
                "with no route on it."
            )
        if at and not self.gpx_files:
            from .gpx_io import parse_coordinate
            try:
                parse_coordinate(at)
            except ValueError as exc:
                raise ValueError(str(exc)) from None
        missing = [p for p in self.gpx_files if not Path(p).is_file()]
        if missing:
            names = "\n".join(Path(p).name for p in missing)
            raise ValueError(f"These files have gone missing:\n{names}")

        tol = float(self.fit_var.get().split("(")[1].split(" mm")[0])
        base = "flat" if self.style_var.get().startswith("Flat") else "follow"
        caption = self.cap_var.get().strip() if self.cap_on.get() else None

        return Config(
            gpx_paths=list(self.gpx_files),
            centre=(at or None),
            across_km=float(self.across_var.get()),
            join_distance_m=self.join.get(),
            scale_denominator=(self.scale.get() or None),
            altitude_offset_m=self.alt.get(),
            merge_distance_mm=self.merge.get(),
            out_path=str(Path(self.out_var.get()) / f"{self._stem()}.3mf"),
            size_mm=self.size.get(),
            margin=self.margin.get(),
            z_scale=self.zscale.get(),
            base_mm=self.base.get(),
            grid=int(self.detail.get()),
            trail_width=self.width.get(),
            tolerance=tol,
            trail_thickness=self.thick.get(),
            trail_proud=self.proud.get(),
            trail_base=base,
            trail_entry=("bottom" if self.entry_var.get().startswith("From under")
                         else "top"),
            caption=caption or None,
            shape=self.shape_var.get().lower(),
            caption_position=("top" if "top" in self.cap_pos_var.get().lower()
                              else "bottom"),
            caption_style=(
                "deboss" if self.cut_var.get().startswith("Engraved")
                else "emboss"
            ),
            scale_bar=bool(self.scale_var.get()),
            north_arrow=bool(self.north_var.get()),
            route_only=bool(self.route_only_var.get()),
            verbose=False,
            log_fn=lambda m: self.queue.put(("log", m)),
        )

    def _stem(self) -> str:
        fallback = Path(self.gpx_files[0]).stem if self.gpx_files else "map"
        name = self.name_var.get().strip() or fallback
        return "".join(c for c in name if c not in '/\\:*?"<>|').strip() or "map"

    # ------------------------------------------------------------------ running
    def _run(self, export: bool):
        if self.busy:
            return
        try:
            cfg = self._collect()
        except Exception as exc:  # noqa: BLE001
            messagebox.showwarning("Not quite ready", str(exc))
            return

        self.busy = True
        self.go_btn.configure(state="disabled")
        self.prev_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.progress.start(12)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self._say("Working on it…")

        threading.Thread(target=self._worker, args=(cfg, export), daemon=True).start()

    def _worker(self, cfg: Config, export: bool):
        try:
            from .build import build
            from .preview import render

            b = build(cfg)

            png = str(Path(tempfile.gettempdir()) / f"gpx2print_{os.getpid()}.png")
            render(b, cfg, png)
            self.queue.put(("preview", png))

            if export:
                from .export import export_parts

                written = export_parts(
                    b, cfg, cfg.out_path, stl=bool(self.stl_var.get()),
                    log=lambda m: self.queue.put(("log", m)),
                    preview=str(Path(cfg.out_path).with_suffix(".png")),
                )
                try:
                    render(b, cfg, str(Path(cfg.out_path).with_suffix(".png")))
                except Exception:  # noqa: BLE001 - the preview is a nicety
                    pass
                self.queue.put(("done", (b, written)))
            else:
                self.queue.put(("done", (b, [])))
        except Exception as exc:  # noqa: BLE001
            self.queue.put(("error", (str(exc), traceback.format_exc())))

    def _pump(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._say(payload)
                elif kind == "preview":
                    self.preview_path = payload
                    self._load_preview(payload)
                elif kind == "done":
                    self._finish(*payload)
                elif kind == "error":
                    self._fail(*payload)
        except queue.Empty:
            pass
        self.after(80, self._pump)

    def _finish(self, b, written):
        self.busy = False
        self.progress.stop()
        self.go_btn.configure(state="normal")
        self.prev_btn.configure(state="normal")

        s = b.stats
        self._say("")
        self._say(f"{s['length_km']:.1f} km, {s['ascent_m']:.0f} m of climbing")
        self._say(
            f"{'one object  ' if s.get('route_only') else 'map piece   '}"
            f"{s['map_size_mm'][0]:.0f} x {s['map_size_mm'][1]:.0f} x "
            f"{s['map_size_mm'][2]:.1f} mm"
        )

        secs = [] if s.get("route_only") else (s.get("sections") or [])
        if len(secs) > 1:
            self._say(f"{len(secs)} separate trail pieces:")
            for sec in secs:
                joined = (
                    f", {len(sec['sources'])} files joined" if sec["joins"] else ""
                )
                self._say(
                    f"  piece {sec['index']}  {sec['size_mm'][0]:.0f} x "
                    f"{sec['size_mm'][1]:.0f} x {sec['size_mm'][2]:.1f} mm, "
                    f"{sec['length_km']:.1f} km{joined}"
                )
        elif not s.get("route_only"):
            self._say(
                f"trail piece {s['trail_size_mm'][0]:.0f} x "
                f"{s['trail_size_mm'][1]:.0f} x {s['trail_size_mm'][2]:.1f} mm"
            )
        for w in b.warnings:
            self._say(f"NOTE: {w}")
        self._say("")
        self._say(s.get("attribution", ""))

        if written:
            self.written = written
            self.open_btn.configure(state="normal")
            self._say("")
            for p in written:
                self._say(f"saved  {Path(p).name}")
            names = "\n".join(Path(p).name for p in written if p.endswith(".3mf"))
            if s.get("route_only"):
                advice = ("Open it in your slicer and print it. The route is "
                          "already joined to its base, so it prints as one piece "
                          "in a single colour.")
            else:
                advice = ("Open each one in your slicer as a separate print, "
                          "with a different colour for each.")
            messagebox.showinfo(
                "Your files are ready",
                f"Saved into {self.out_var.get()}\n\n{names}\n\n{advice}",
            )
        else:
            self._say("Preview only — nothing saved yet.")

    def _fail(self, msg, tb):
        self.busy = False
        self.progress.stop()
        self.go_btn.configure(state="normal")
        self.prev_btn.configure(state="normal")
        self._say("")
        self._say(f"It didn't work: {msg}")
        for line in tb.strip().splitlines()[-4:]:
            self._say(f"   {line}")
        messagebox.showerror("Something went wrong", msg)

    # ------------------------------------------------------------------ preview
    def _load_preview(self, path):
        try:
            from PIL import Image

            self._pil = Image.open(path)
            self._pil.load()
        except Exception:  # noqa: BLE001
            self._pil = None
        self._draw_preview()

    def _draw_preview(self):
        pil = getattr(self, "_pil", None)
        if pil is None:
            self._placeholder()
            return
        cw = max(self.canvas.winfo_width(), 50)
        ch = max(self.canvas.winfo_height(), 50)
        scale = min(cw / pil.width, ch / pil.height)
        w, h = max(int(pil.width * scale), 1), max(int(pil.height * scale), 1)

        try:
            from PIL import Image, ImageTk

            resized = pil.resize((w, h), Image.LANCZOS)
            self.preview_img = ImageTk.PhotoImage(resized)
        except Exception:  # noqa: BLE001
            return

        self.canvas.delete("all")
        self.canvas.create_image(cw // 2, ch // 2, image=self.preview_img)


def main():
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
