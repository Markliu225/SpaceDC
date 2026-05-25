"""Visual GUI to assemble the satellite from independent components.

Tabs:
  * Bay Shell    — 6 faces (top/bottom/back/front/left/right); each has its
                    own visibility toggle + translate + rotate + size.
  * Solar Panels — LUMID-derived cross-arm panels (translate/rotate/scale).
  * DGX Rack     — grid + spacing + scale + position + rotation.
  * Camera       — eye, look-at target, focal length.

Slider changes are debounced 500 ms; then the GUI saves
tools/assembly_config.json, regenerates usd/components.usda and
usd/dgx_rack.usda, and tells the backend to reload the satellite stage.

Run:
    backend/.venv/Scripts/python.exe tools/gui_assemble.py
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_assembly as AA  # noqa: E402


DEBOUNCE_MS = 500


class Slider(ttk.Frame):
    def __init__(self, master, label, getter, setter, *, frm, to,
                 width_entry=8, integer=False, on_change=None):
        super().__init__(master)
        self.columnconfigure(1, weight=1)
        self.getter, self.setter = getter, setter
        self.on_change = on_change
        self.integer = integer
        self._syncing = False
        self.var = tk.DoubleVar(value=float(getter()))
        ttk.Label(self, text=label, width=10, anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.scale = ttk.Scale(self, from_=frm, to=to, variable=self.var, orient="horizontal",
                               command=self._on_scale)
        self.scale.grid(row=0, column=1, sticky="ew")
        self.entry = ttk.Entry(self, width=width_entry)
        self.entry.insert(0, self._fmt(getter()))
        self.entry.bind("<Return>", self._on_entry)
        self.entry.bind("<FocusOut>", self._on_entry)
        self.entry.grid(row=0, column=2, padx=(4, 0))

    def _fmt(self, v) -> str:
        return f"{int(round(float(v)))}" if self.integer else f"{float(v):.3f}"

    def _sync(self, v) -> None:
        self._syncing = True
        self.entry.delete(0, tk.END)
        self.entry.insert(0, self._fmt(v))
        self._syncing = False

    def _on_scale(self, _v: str) -> None:
        val = int(round(float(self.var.get()))) if self.integer else float(self.var.get())
        self.setter(val); self._sync(val)
        if self.on_change: self.on_change()

    def _on_entry(self, _e=None) -> None:
        if self._syncing: return
        try: val = float(self.entry.get())
        except ValueError: return
        val = int(round(val)) if self.integer else val
        self.var.set(val); self.setter(val)
        if self.on_change: self.on_change()


class AssemblyGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SpaceDC — Satellite Assembly")
        self.geometry("660x920")
        self.cfg = AA.load_config()
        self._pending = None
        self.live_var = tk.BooleanVar(value=True)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self._build_bay_tab(nb)
        self._build_solar_tab(nb)
        self._build_rack_tab(nb)
        self._build_camera_tab(nb)

        footer = ttk.Frame(self)
        footer.pack(fill="x", padx=8, pady=8)
        ttk.Checkbutton(footer, text="Apply live (500 ms debounce)",
                        variable=self.live_var).pack(side="left")
        ttk.Button(footer, text="Apply now", command=self._apply_now).pack(side="right")
        ttk.Button(footer, text="Reload config", command=self._reload_cfg).pack(side="right", padx=6)

        self.status = tk.StringVar(value="ready")
        ttk.Label(self, textvariable=self.status, anchor="w", relief="sunken")\
            .pack(fill="x", padx=8, pady=(0, 8))

    # ---- Bay tab -----------------------------------------------------------

    def _build_bay_tab(self, nb) -> None:
        tab = ttk.Frame(nb, padding=6); nb.add(tab, text="Bay Shell")
        canvas = tk.Canvas(tab, borderwidth=0, highlightthickness=0)
        sb = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        for name in AA.BAY_FACE_ORDER:
            box = ttk.LabelFrame(inner, text=f"{name.capitalize()} panel", padding=8)
            box.pack(fill="x", padx=6, pady=4)

            vis_var = tk.BooleanVar(value=bool(self.cfg["bay_shell"][name].get("visible", True)))
            def _mk_cb(n, v):
                def cb():
                    self.cfg["bay_shell"][n]["visible"] = bool(v.get())
                    self._schedule()
                return cb
            ttk.Checkbutton(box, text="visible", variable=vis_var,
                            command=_mk_cb(name, vis_var)).pack(anchor="w")

            ttk.Label(box, text="Translate (cm)", font=("TkDefaultFont", 9, "bold"))\
                .pack(anchor="w", pady=(4, 0))
            for i, ax in enumerate("XYZ"):
                Slider(box, f"T{ax}",
                       getter=lambda n=name, i=i: self.cfg["bay_shell"][n]["translate"][i],
                       setter=lambda v, n=name, i=i: self._set_vec3("bay_shell", n, "translate", i, v),
                       frm=-60, to=60, on_change=self._schedule).pack(fill="x", pady=1)

            ttk.Label(box, text="Rotate (deg)", font=("TkDefaultFont", 9, "bold"))\
                .pack(anchor="w", pady=(4, 0))
            for i, ax in enumerate("XYZ"):
                Slider(box, f"R{ax}",
                       getter=lambda n=name, i=i: self.cfg["bay_shell"][n]["rotate"][i],
                       setter=lambda v, n=name, i=i: self._set_vec3("bay_shell", n, "rotate", i, v),
                       frm=-180, to=180, on_change=self._schedule).pack(fill="x", pady=1)

            ttk.Label(box, text="Size W/D/H (cm)", font=("TkDefaultFont", 9, "bold"))\
                .pack(anchor="w", pady=(4, 0))
            for i, ax in enumerate(("W", "D", "H")):
                Slider(box, ax,
                       getter=lambda n=name, i=i: self.cfg["bay_shell"][n]["size"][i],
                       setter=lambda v, n=name, i=i: self._set_vec3("bay_shell", n, "size", i, v),
                       frm=0.2, to=60, on_change=self._schedule).pack(fill="x", pady=1)

    # ---- Solar tab (4 independent panels) ---------------------------------

    def _build_solar_tab(self, nb) -> None:
        tab = ttk.Frame(nb, padding=6); nb.add(tab, text="Solar Panels")
        canvas = tk.Canvas(tab, borderwidth=0, highlightthickness=0)
        sb = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")

        labels = {"px": "+X panel", "nx": "-X panel", "pz": "+Z panel", "nz": "-Z panel"}
        for name in AA.SOLAR_PANEL_ORDER:
            box = ttk.LabelFrame(inner, text=labels[name], padding=8)
            box.pack(fill="x", padx=6, pady=4)

            vis_var = tk.BooleanVar(value=bool(self.cfg["solar_panels"][name].get("visible", True)))
            def _mk_cb(n, v):
                def cb():
                    self.cfg["solar_panels"][n]["visible"] = bool(v.get())
                    self._schedule()
                return cb
            ttk.Checkbutton(box, text="visible", variable=vis_var,
                            command=_mk_cb(name, vis_var)).pack(anchor="w")

            ttk.Label(box, text="Translate (cm)", font=("TkDefaultFont", 9, "bold"))\
                .pack(anchor="w", pady=(4, 0))
            for i, ax in enumerate("XYZ"):
                Slider(box, f"T{ax}",
                       getter=lambda n=name, i=i: self.cfg["solar_panels"][n]["translate"][i],
                       setter=lambda v, n=name, i=i: self._set_vec3("solar_panels", n, "translate", i, v),
                       frm=-150, to=150, on_change=self._schedule).pack(fill="x", pady=1)

            ttk.Label(box, text="Rotate (deg)", font=("TkDefaultFont", 9, "bold"))\
                .pack(anchor="w", pady=(4, 0))
            for i, ax in enumerate("XYZ"):
                Slider(box, f"R{ax}",
                       getter=lambda n=name, i=i: self.cfg["solar_panels"][n]["rotate"][i],
                       setter=lambda v, n=name, i=i: self._set_vec3("solar_panels", n, "rotate", i, v),
                       frm=-180, to=180, on_change=self._schedule).pack(fill="x", pady=1)

            ttk.Label(box, text="Size W/D/H (cm)", font=("TkDefaultFont", 9, "bold"))\
                .pack(anchor="w", pady=(4, 0))
            for i, ax in enumerate(("W", "D", "H")):
                Slider(box, ax,
                       getter=lambda n=name, i=i: self.cfg["solar_panels"][n]["size"][i],
                       setter=lambda v, n=name, i=i: self._set_vec3("solar_panels", n, "size", i, v),
                       frm=0.2, to=150, on_change=self._schedule).pack(fill="x", pady=1)

    # ---- Rack tab ----------------------------------------------------------

    def _build_rack_tab(self, nb) -> None:
        tab = ttk.Frame(nb, padding=10); nb.add(tab, text="DGX Rack")
        k = "dgx_rack"
        ttk.Label(tab, text="Grid", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(0, 2))
        Slider(tab, "Cols (X)", getter=lambda: self.cfg[k]["cols"],
               setter=lambda v: self._set(k, "cols", int(v)),
               frm=1, to=6, integer=True, on_change=self._schedule).pack(fill="x", pady=2)
        Slider(tab, "Rows (Z)", getter=lambda: self.cfg[k]["rows"],
               setter=lambda v: self._set(k, "rows", int(v)),
               frm=1, to=6, integer=True, on_change=self._schedule).pack(fill="x", pady=2)
        Slider(tab, "Pitch X", getter=lambda: self.cfg[k]["pitch_x"],
               setter=lambda v: self._set(k, "pitch_x", v),
               frm=40, to=200, on_change=self._schedule).pack(fill="x", pady=2)
        Slider(tab, "Pitch Z", getter=lambda: self.cfg[k]["pitch_z"],
               setter=lambda v: self._set(k, "pitch_z", v),
               frm=28, to=120, on_change=self._schedule).pack(fill="x", pady=2)
        ttk.Label(tab, text="Scale", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(10, 2))
        Slider(tab, "DGX scale", getter=lambda: self.cfg[k]["dgx_scale"],
               setter=lambda v: self._set(k, "dgx_scale", v),
               frm=0.04, to=0.4, on_change=self._schedule).pack(fill="x", pady=2)
        Slider(tab, "Rack x", getter=lambda: self.cfg[k]["scale_factor"],
               setter=lambda v: self._set(k, "scale_factor", v),
               frm=0.3, to=3.0, on_change=self._schedule).pack(fill="x", pady=2)
        ttk.Label(tab, text="Position (cm)", font=("TkDefaultFont", 10, "bold"))\
            .pack(anchor="w", pady=(10, 2))
        for i, ax in enumerate("XYZ"):
            Slider(tab, f"T{ax}",
                   getter=lambda i=i: self.cfg[k]["translate"][i],
                   setter=lambda v, i=i: self._set_vec(k, "translate", i, v),
                   frm=-40, to=40, on_change=self._schedule).pack(fill="x", pady=2)
        ttk.Label(tab, text="Rotation (deg)", font=("TkDefaultFont", 10, "bold"))\
            .pack(anchor="w", pady=(10, 2))
        for i, ax in enumerate("XYZ"):
            Slider(tab, f"R{ax}",
                   getter=lambda i=i: self.cfg[k]["rotate"][i],
                   setter=lambda v, i=i: self._set_vec(k, "rotate", i, v),
                   frm=-180, to=180, on_change=self._schedule).pack(fill="x", pady=2)

    # ---- Camera tab --------------------------------------------------------

    def _build_camera_tab(self, nb) -> None:
        tab = ttk.Frame(nb, padding=10); nb.add(tab, text="Camera")
        ttk.Label(tab, text="Eye (cm)", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(0, 2))
        for i, ax in enumerate("XYZ"):
            Slider(tab, f"Eye {ax}",
                   getter=lambda i=i: self.cfg["camera"]["eye"][i],
                   setter=lambda v, i=i: self._set_vec("camera", "eye", i, v),
                   frm=-500, to=500, on_change=self._schedule).pack(fill="x", pady=2)
        ttk.Label(tab, text="Look-at target (cm)", font=("TkDefaultFont", 10, "bold"))\
            .pack(anchor="w", pady=(10, 2))
        for i, ax in enumerate("XYZ"):
            Slider(tab, f"Tgt {ax}",
                   getter=lambda i=i: self.cfg["camera"]["target"][i],
                   setter=lambda v, i=i: self._set_vec("camera", "target", i, v),
                   frm=-60, to=60, on_change=self._schedule).pack(fill="x", pady=2)
        ttk.Label(tab, text="Optics", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(10, 2))
        Slider(tab, "FL (mm)", getter=lambda: self.cfg["camera"]["focal_length"],
               setter=lambda v: self._set("camera", "focal_length", v),
               frm=14, to=100, on_change=self._schedule).pack(fill="x", pady=2)

    # ---- plumbing ----------------------------------------------------------

    def _set(self, s, k, v): self.cfg[s][k] = v
    def _set_vec(self, s, k, i, v): self.cfg[s][k][i] = float(v)
    def _set_vec3(self, s, sub, k, i, v): self.cfg[s][sub][k][i] = float(v)
    def _set_uniform_scale(self, s, v): self.cfg[s]["scale"] = [float(v)] * 3

    def _reload_cfg(self) -> None:
        self.cfg = AA.load_config()
        self.status.set("config reloaded — close & reopen GUI to see updated slider positions")

    def _schedule(self) -> None:
        if not self.live_var.get(): return
        if self._pending is not None: self.after_cancel(self._pending)
        self._pending = self.after(DEBOUNCE_MS, self._apply_now)

    def _apply_now(self) -> None:
        self._pending = None
        try:
            AA.save_config(self.cfg)
            AA.apply(self.cfg, reload=True)
            hidden = [n for n in AA.BAY_FACE_ORDER
                      if not bool(self.cfg["bay_shell"][n].get("visible", True))]
            note = f"  hidden: {', '.join(hidden)}" if hidden else ""
            r = self.cfg["dgx_rack"]
            self.status.set(f"applied — grid {r['cols']}x{r['rows']}, dgx_scale {r['dgx_scale']:.2f}{note}")
        except Exception as e:  # noqa: BLE001
            self.status.set(f"apply failed: {e}")


def main() -> None:
    AssemblyGUI().mainloop()


if __name__ == "__main__":
    main()
