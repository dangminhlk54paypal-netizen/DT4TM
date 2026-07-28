"""digital_twin_pyvista.py — Real-time PyVista 3D digital twin (level C).

Exists ALONGSIDE (not instead of) the two other twins:
  digital_twin.py            matplotlib, 2D heatmap, disc only
  outputs/digital_twin_fem.html   three.js, full 3D, the reference "level C" build

Physics: twin_core.TwinState (SSOT integrator, pinned bit-for-bit against the
baked JS engine by xval_twin.py) via twin_model's coefficient/plate bridges.
Geometry: reuses build_twin_html_fem.py's procedural mesh builders VERBATIM
(build_octagonal_base/frame, build_solid_core, revolve_ring, build_disc_mesh,
compute_em_field_lines, compute_eddy_field) — geometry is NOT reimplemented
here. See docs/archive/2026-07-28_PYVISTA_TWIN_PLAN.md for the full architecture and
the reasoning behind every non-obvious choice below.

Coordinate system: Z-up, millimetres — the SAME frame build_twin_html_fem.py
builds its geometry in internally. Unlike its baked JS output, this script
does NOT rotate to Y-up (that rotation, build_twin_html_fem.py:1406-1410,
exists only because three.js is Y-up by convention; VTK has no such
convention) — instead sets `pl.camera.up = (0, 0, 1)`.

Run:
  python digital_twin_pyvista.py --self-check
      Import/build sanity check. Works WITHOUT pyvista/vtk installed.
  python digital_twin_pyvista.py --screenshot outputs/twin_pv.png --no-show
      Static off-screen render (needs pyvista/vtk).
  python digital_twin_pyvista.py --speed 50
      Live interactive window. Space=pause, r=reset, 1-4=viz mode, [ / ] = disc radius.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import sys
import threading
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import pyvista as pv
    HAVE_PYVISTA = True
except ImportError:
    HAVE_PYVISTA = False

# matplotlib.use("Agg") is forced, as a SIDE EFFECT, by build_twin_html_fem's
# compute_em_field_lines() (called from solve_plate_variant(), used by the
# worker-thread plate rebuild below) — matplotlib.use() is not thread-safe, so
# it must be called explicitly, once, HERE on the main thread before any
# worker thread can race it (docs/archive/2026-07-28_PYVISTA_TWIN_PLAN.md WP-PLATE
# note). Harmless: this script never opens an interactive matplotlib window.
import matplotlib
matplotlib.use("Agg")

from twin_core import LevCoeffs, RomCoeffs, TwinState
from twin_model import PlateCache, PlateVariant, coeffs_from_live, i_max_for, resolve_active_plate

# Region ids — MUST match build_twin_html_fem.py's reg_base/region convention.
REG_PLATE, REG_INNER, REG_OUTER, REG_IRON_CORE, REG_WOOD, REG_IRON_RING = range(6)

# Material colours (0..1 RGB) — matches build_twin_html_fem.py's JS material
# scheme (STRUCT_RGB/METAL_RGB/COPPER_COLD, :1556/:1582/:1589) so the two
# twins read as "the same device."
COLOR_WOOD   = (160 / 255, 100 / 255, 55 / 255)
COLOR_METAL  = (170 / 255, 175 / 255, 185 / 255)
COLOR_COPPER = (0.30, 0.14, 0.08)


# ---------------------------------------------------------------------------
# WP-GEO — geometry (reused verbatim from build_twin_html_fem.py)
# ---------------------------------------------------------------------------
def soup_to_polydata(V: np.ndarray) -> "pv.PolyData":
    """(nTri,3,3) triangle soup -> unwelded pv.PolyData. NEVER call .clean()
    on the disc's PolyData: dT_eddy/dT_air/Je are indexed by the SOUP's own
    vertex order (build_twin_html_fem.py build_disc_mesh, :589-598); welding
    would silently reorder points and desync every per-vertex scalar array
    while the mesh still looks fine."""
    verts = V.reshape(-1, 3).astype(np.float64)
    faces = np.arange(len(verts), dtype=np.int64).reshape(-1, 3)
    return pv.PolyData.from_regular_faces(verts, faces)


def build_body_geometry(cfg) -> dict:
    """Procedural device body, Z-up mm. Mirrors build_twin_html_fem.py's
    build()'s body-geometry section (:800-876) minus the Y-up rotation --
    calls the SAME functions with the SAME parameters, do not re-derive."""
    from build_twin_html_fem import (
        build_octagonal_base, build_octagonal_frame, build_solid_core, revolve_ring,
    )

    n_theta = int(cfg.raw["levitating_disc"].get("n_theta", 96))
    coil_h  = float(cfg.coils.get("height_mm", 52.0))
    z_base = z_coil_bot = 8.0
    z_coil_top = z_base + coil_h

    r_core  = float(cfg.iron.get("r_outer_mm", 25.0))
    r_i_in  = float(cfg.coils["inner"]["r_inner_mm"])
    r_i_out = float(cfg.coils["inner"]["r_outer_mm"])
    r_o_in  = float(cfg.coils["outer"]["r_inner_mm"])
    r_o_out = float(cfg.coils["outer"]["r_outer_mm"])
    oir = cfg.raw["outer_iron_ring"]
    r_ring_in, r_ring_out = float(oir["r_inner_mm"]), float(oir["r_outer_mm"])
    frm = cfg.raw.get("device_frame", {})
    r_frame_in  = r_o_out + float(frm.get("air_gap_mm", 50.0))
    r_frame_out = r_frame_in + float(frm.get("wall_thickness_mm", 20.0))

    V_core  = build_solid_core(r_core, z_coil_bot, z_coil_top, n_theta)
    V_inner = revolve_ring(r_i_in, r_i_out, z_coil_bot, z_coil_top, n_theta)
    V_ring  = revolve_ring(r_ring_in, r_ring_out, z_coil_bot, z_coil_top, n_theta)
    V_outer = revolve_ring(r_o_in, r_o_out, z_coil_bot, z_coil_top, n_theta)
    V_floor = build_octagonal_base(r_frame_out, 0.0, z_base, n_sides=8)
    V_walls = build_octagonal_frame(r_frame_in, r_frame_out, 0.0, z_coil_top, n_sides=8)
    V_wood  = np.concatenate([V_floor, V_walls], axis=0)

    return {
        "V_core": V_core, "V_inner": V_inner, "V_ring": V_ring,
        "V_outer": V_outer, "V_wood": V_wood,
        "z_disc_bot": z_coil_top, "n_theta": n_theta,
    }


def solve_active_disc(cfg, z_disc_bot: float) -> dict:
    """EM+ROM solve + disc mesh for the ACTIVE (params.yaml default) plate --
    mirrors build()'s disc section, reusing build_disc_mesh/compute_eddy_field
    verbatim. Returns everything needed for both the mesh and the physics."""
    from build_twin_html_fem import build_disc_mesh, compute_eddy_field
    from em_solver import compute_losses
    from rom import ThermalROM

    em = compute_losses(cfg)
    je_field = compute_eddy_field(em)
    rom = ThermalROM().build(cfg, em_losses=em, verbose=False)
    V_disc, dTe, dTa, Je = build_disc_mesh(cfg, rom, z_disc_bot, je_field=je_field)
    return {"V_disc": V_disc, "dTe": dTe, "dTa": dTa, "Je": Je, "em": em, "rom": rom}


def add_body_meshes(pl: "pv.Plotter", body: dict) -> None:
    pl.add_mesh(soup_to_polydata(body["V_core"]),  color=COLOR_METAL,  smooth_shading=False, name="core")
    pl.add_mesh(soup_to_polydata(body["V_ring"]),  color=COLOR_METAL,  smooth_shading=False, name="ring")
    pl.add_mesh(soup_to_polydata(body["V_wood"]),  color=COLOR_WOOD,   smooth_shading=False, name="wood")
    pl.add_mesh(soup_to_polydata(body["V_inner"]), color=COLOR_COPPER, smooth_shading=False, name="coil_inner")
    pl.add_mesh(soup_to_polydata(body["V_outer"]), color=COLOR_COPPER, smooth_shading=False, name="coil_outer")


def make_disc_mesh(disc: dict, T_amb: float, T_hot: float):
    """Builds the disc PolyData with BOTH 'Temperature' and 'Je' scalar
    arrays (WP-VIZ toggles between them via set_active_scalars — never
    rebuilds the mesh for a mode switch, only re-adds the same actor's
    active array)."""
    mesh = soup_to_polydata(disc["V_disc"])
    mesh["Temperature"] = np.full(mesh.n_points, T_amb, dtype=np.float64)
    Je = disc["Je"]
    mesh["Je"] = (Je if Je is not None else np.zeros(mesh.n_points)).astype(np.float64)
    mesh.set_active_scalars("Temperature")
    return mesh


# ---------------------------------------------------------------------------
# WP-VIZ — B-field lines (one PolyData, hand-built `lines` cell array)
# ---------------------------------------------------------------------------
def build_field_lines_polydata(field_lines: list[dict], n_azimuth: int = 4):
    """21 (r,z) meridian contours x 4 azimuthal angles (0/90/180/270°) = up to
    84 polylines in ONE PolyData. Built by hand (points + a flat `lines` cell
    array [n0,i0,i1,...,in0-1, n1,...]) — pv.MultipleLines/lines_from_points
    both draw ONE continuous broken line through every point they're given,
    which would wrongly stitch contour k's last point to contour k+1's
    first."""
    if not field_lines:
        return None
    angles = np.linspace(0, 2 * np.pi, n_azimuth, endpoint=False)
    pts, cells, amps = [], [], []
    idx = 0
    for line in field_lines:
        r = np.asarray(line["r"], dtype=np.float64)
        z = np.asarray(line["z"], dtype=np.float64)
        amp = np.asarray(line["amp"], dtype=np.float64)
        n = len(r)
        if n < 2:
            continue
        for th in angles:
            ct, st = np.cos(th), np.sin(th)
            pts.append(np.column_stack([r * ct, r * st, z]))
            cells.append(n)
            cells.extend(range(idx, idx + n))
            amps.append(amp)
            idx += n
    if not pts:
        return None
    poly = pv.PolyData()
    poly.points = np.concatenate(pts, axis=0)
    poly.lines = np.array(cells, dtype=np.int64)
    poly["amp"] = np.concatenate(amps, axis=0)
    return poly


# ---------------------------------------------------------------------------
# WP-PLATE — disc rebuild on a worker thread
# ---------------------------------------------------------------------------
class PlateRebuildWorker:
    """solve_plate_variant()/build_plate_variant() touch no VTK state, so
    they're safe on a background thread; the result is handed back through a
    lock-protected slot and swapped in on the MAIN thread at a frame
    boundary (poll(), called from the timer callback) -- every VTK call
    stays on the main thread. The live simulation keeps running on the OLD
    ROM/mesh while a rebuild is in flight (better than digital_twin.py's
    pause-and-block-the-GUI-thread approach, see its docstring)."""

    def __init__(self, cfg):
        self._cfg = cfg
        self._lock = threading.Lock()
        self._result: PlateVariant | None = None
        self._error: str | None = None
        self._busy = False

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def request(self, radius_mm: float, z_disc_bot_mm: float) -> None:
        if self.busy:
            return
        with self._lock:
            self._busy = True

        def _work():
            from twin_model import build_plate_variant
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):   # em_solver prints unconditionally
                    variant = build_plate_variant(self._cfg, radius_mm, z_disc_bot_mm)
                with self._lock:
                    self._result = variant
            except Exception as exc:   # noqa: BLE001 -- report, don't crash the render thread
                with self._lock:
                    self._error = f"{type(exc).__name__}: {exc}"
            finally:
                with self._lock:
                    self._busy = False

        threading.Thread(target=_work, daemon=True).start()

    def poll(self) -> "PlateVariant | None":
        """Call once per frame from the main thread. Returns a finished
        PlateVariant exactly once (then None until the next request)."""
        with self._lock:
            if self._error is not None:
                print(f"[PlateRebuildWorker] rebuild failed: {self._error}")
                self._error = None
            v, self._result = self._result, None
            return v


# ---------------------------------------------------------------------------
# TwinPyVista — owns the Plotter, the physics state, and every callback
# ---------------------------------------------------------------------------
class TwinPyVista:
    def __init__(self, cfg, args):
        self.cfg = cfg
        self.args = args

        self.active = resolve_active_plate(cfg)
        self.body = build_body_geometry(cfg)
        self.disc = solve_active_disc(cfg, self.body["z_disc_bot"])
        self.plate_cache = PlateCache(cfg, self.active.name, self.disc["rom"], em_base=self.disc["em"])

        rom_c, lumped_c, lev_c = coeffs_from_live(cfg, self.disc["em"], self.disc["rom"])
        self.T_amb = rom_c.T_amb
        self.twin = TwinState(rom=rom_c, lumped=lumped_c, lev=lev_c, T_amb=self.T_amb)
        self.I_MAX = i_max_for(cfg)
        self.I_target = float(args.I)

        self.T_hot = float(cfg.raw["levitating_disc"].get("plate_hot_display_C", 125.0))
        self.z_gap_exag = float(cfg.raw.get("levitation", {}).get("z_gap_exaggeration", 2.0))

        self.field_lines_data, _B_max = self._compute_field_lines()

        self.viz_mode = "thermal"   # thermal | eddy
        self.paused = False
        self.speed = float(args.speed)

        variant_radii = sorted({s["radius_mm"] for s in cfg.raw.get("plate_library", [])
                                 if s.get("material") == "aluminium"
                                 and abs(float(s.get("thickness_mm", 0.0)) - 3.0) < 1e-6}
                                | {float(cfg.plate["radius_mm"])})
        self.variant_radii = variant_radii
        self.variant_idx = variant_radii.index(float(cfg.plate["radius_mm"]))

        self.rebuild_worker = PlateRebuildWorker(cfg)

        self.pl: "pv.Plotter | None" = None
        self.disc_mesh = None
        self.disc_actor = None
        self._chart_T = None
        self._chart_I = None
        self._hist_t: list[float] = []
        self._hist_Tmax: list[float] = []
        self._hist_I: list[float] = []
        self._chart_accum = 0.0
        self._last_wall = None

    def _compute_field_lines(self):
        from build_twin_html_fem import compute_em_field_lines
        return compute_em_field_lines(self.disc["em"], self.cfg)

    # -- geometry / actors --------------------------------------------------
    def build_scene(self, off_screen: bool) -> "pv.Plotter":
        pl = pv.Plotter(window_size=[1400, 900], off_screen=off_screen)
        pl.set_background("#0f0f1e")
        pl.camera.up = (0.0, 0.0, 1.0)

        add_body_meshes(pl, self.body)

        self.disc_mesh = make_disc_mesh(self.disc, self.T_amb, self.T_hot)
        self.disc_actor = pl.add_mesh(
            self.disc_mesh, scalars="Temperature", cmap="coolwarm",
            clim=[self.T_amb - 0.5, self.T_hot], smooth_shading=False,
            name="disc", show_scalar_bar=True,
            scalar_bar_args={"title": "T (°C)", "color": "white"},
        )

        fl_poly = build_field_lines_polydata(self.field_lines_data)
        self.field_line_actor = None
        if fl_poly is not None:
            self.field_line_actor = pl.add_mesh(
                fl_poly, scalars="amp", cmap="plasma", line_width=1.5,
                name="field_lines", show_scalar_bar=False,
            )
            self.field_line_actor.visibility = False

        pl.add_text("Thermal Digital Twin — PyVista", position="upper_left",
                    font_size=12, color="white", name="title")
        pl.view_isometric()
        pl.reset_camera()
        self.pl = pl
        return pl

    def _apply_disc_transform(self) -> None:
        z_mm = (self.twin.lev_state.z + self.twin.lev_state.jit) * self.z_gap_exag
        self.disc_actor.position = (0.0, 0.0, z_mm)

    def _repaint_disc(self) -> None:
        # thermal mode: T_amb + β·ΔT_eddy (single combined field the same way
        # TwinState.T_field does it -- see twin_core.py's own docstring on
        # why the JS's separate dT_eddy/dT_air weighting collapses to one
        # array here); eddy mode shows the STATIC |J_e| pattern, not β-scaled.
        if self.viz_mode == "eddy":
            self.disc_mesh.set_active_scalars("Je")
            self.disc_actor.mapper.scalar_range = (0.0, float(self.disc["Je"].max()) or 1.0)
        else:
            beta = self.twin.rom_state.beta
            self.disc_mesh["Temperature"] = self.T_amb + beta * self.disc["dTe"]
            self.disc_mesh.set_active_scalars("Temperature")
            self.disc_actor.mapper.scalar_range = (self.T_amb - 0.5, self.T_hot)

    # -- physics step ---------------------------------------------------
    def step(self, dt_sim: float) -> None:
        I_now = max(0.0, min(self.I_target, self.I_MAX))
        self.twin.step(I_now, dt_sim)
        self._apply_disc_transform()
        self._repaint_disc()
        self._chart_accum += dt_sim
        if self._chart_accum >= 1.0:
            self._chart_accum = 0.0
            self._hist_t.append(self.twin.t)
            self._hist_Tmax.append(float(self.disc_mesh["Temperature"].max()))
            self._hist_I.append(I_now)
            if len(self._hist_t) > 3600:
                del self._hist_t[0]; del self._hist_Tmax[0]; del self._hist_I[0]
            self._update_charts()

    def reset(self) -> None:
        self.twin.reset()
        self._hist_t.clear(); self._hist_Tmax.clear(); self._hist_I.clear()
        self._chart_accum = 0.0
        self._apply_disc_transform()
        self._repaint_disc()

    # -- WP-CHART ---------------------------------------------------------
    def add_charts(self, pl: "pv.Plotter") -> None:
        chart_T = pv.Chart2D(size=(0.4, 0.25), loc=(0.58, 0.72))
        chart_T.background_color = (15, 15, 30, 180)
        chart_T.x_label = "t (min)"
        chart_T.y_label = "T_max (°C)"
        self._plot_T = chart_T.line([0.0], [self.T_amb], color="#ff6644", width=2.0)

        chart_I = pv.Chart2D(size=(0.4, 0.20), loc=(0.58, 0.50))
        chart_I.background_color = (15, 15, 30, 180)
        chart_I.x_label = "t (min)"
        chart_I.y_label = "I (A)"
        self._plot_I = chart_I.line([0.0], [0.0], color="#44aaff", width=2.0)

        pl.add_chart(chart_T)
        pl.add_chart(chart_I)
        self._chart_T, self._chart_I = chart_T, chart_I
        pl.set_chart_interaction(False)   # else clicks near the chart eat camera drag

    def _update_charts(self) -> None:
        if self._chart_T is None or not self._hist_t:
            return
        t_min = [t / 60.0 for t in self._hist_t]
        self._plot_T.update(t_min, self._hist_Tmax)
        self._plot_I.update(t_min, self._hist_I)

    # -- WP-PLATE -----------------------------------------------------------
    def request_variant(self, step: int) -> None:
        new_idx = (self.variant_idx + step) % len(self.variant_radii)
        radius_mm = self.variant_radii[new_idx]
        print(f"[pyvista] rebuilding disc variant r={radius_mm}mm on worker thread...")
        self.rebuild_worker.request(radius_mm, self.body["z_disc_bot"])
        self._pending_variant_idx = new_idx

    def _poll_variant(self) -> None:
        variant = self.rebuild_worker.poll()
        if variant is None:
            return
        self.variant_idx = self._pending_variant_idx
        # Swap mesh + coefficients at this frame boundary -- every VTK call
        # below runs on the MAIN thread (the worker only computed numpy
        # arrays / dataclasses, no VTK objects).
        self.disc = {"V_disc": variant.V, "dTe": variant.dTe, "dTa": variant.dTa,
                      "Je": variant.Je, "em": self.disc["em"], "rom": self.disc["rom"]}
        new_mesh = make_disc_mesh(self.disc, self.T_amb, self.T_hot)
        self.pl.remove_actor(self.disc_actor, render=False)
        self.disc_mesh = new_mesh
        self.disc_actor = self.pl.add_mesh(
            self.disc_mesh, scalars="Temperature", cmap="coolwarm",
            clim=[self.T_amb - 0.5, self.T_hot], smooth_shading=False,
            name="disc", show_scalar_bar=True,
            scalar_bar_args={"title": "T (°C)", "color": "white"},
        )
        rom_c = variant.rom
        # lumped/lev coeffs stay the coils'/frame's own (radius-independent);
        # only the disc's own ROM + lev anchors change per variant.
        self.twin = TwinState(rom=rom_c, lumped=self.twin.lumped, lev=variant.lev, T_amb=self.T_amb)
        self.reset()
        print(f"[pyvista] disc variant swapped: r={self.variant_radii[self.variant_idx]}mm  "
              f"tau={rom_c.tau:.1f}s  I_LEV_MIN={variant.lev.I_lev_min:.3f}A")

    # -- WP-LOOP: real-time timer + widgets ----------------------------------
    def _on_timer(self, *_args) -> None:
        import time
        now = time.perf_counter()
        wall_dt = 0.0 if self._last_wall is None else min(now - self._last_wall, 0.1)
        self._last_wall = now
        self._poll_variant()
        if not self.paused:
            self.step(wall_dt * self.speed)
        self.pl.render()

    def _on_key_space(self) -> None:
        self.paused = not self.paused

    def _on_key_reset(self) -> None:
        self.reset()

    def _on_key_mode(self, mode: str) -> None:
        self.viz_mode = mode
        if self.field_line_actor is not None:
            self.field_line_actor.visibility = mode in ("field", "combined")
        self._repaint_disc()

    def add_widgets(self, pl: "pv.Plotter") -> None:
        def _on_I(value):
            self.I_target = float(value)
        pl.add_slider_widget(_on_I, [0.0, round(self.I_MAX + 0.5, 1)], value=self.I_target,
                              title="I (A)", pointa=(0.03, 0.90), pointb=(0.23, 0.90),
                              interaction_event="always", color="white")

        def _on_speed(value):
            self.speed = float(value)
        pl.add_slider_widget(_on_speed, [1.0, 200.0], value=self.speed,
                              title="Speed", pointa=(0.03, 0.80), pointb=(0.23, 0.80),
                              interaction_event="always", color="white")

        pl.add_key_event("space", self._on_key_space)
        pl.add_key_event("r", self._on_key_reset)
        pl.add_key_event("1", lambda: self._on_key_mode("thermal"))
        pl.add_key_event("2", lambda: self._on_key_mode("eddy"))
        pl.add_key_event("3", lambda: self._on_key_mode("field"))
        pl.add_key_event("4", lambda: self._on_key_mode("combined"))
        pl.add_key_event("bracketright", lambda: self.request_variant(+1))
        pl.add_key_event("bracketleft", lambda: self.request_variant(-1))

    # -- entry points --------------------------------------------------
    def run_static(self, screenshot: str | None, show: bool) -> None:
        off_screen = not show
        pl = self.build_scene(off_screen=off_screen)
        self._apply_disc_transform()
        if screenshot:
            pl.screenshot(screenshot)
            print(f"[pyvista] screenshot -> {screenshot}")
        if show:
            pl.show()
        else:
            pl.close()

    def run_live(self) -> None:
        pl = self.build_scene(off_screen=False)
        self.add_charts(pl)
        self.add_widgets(pl)
        self._apply_disc_transform()
        # Registered BEFORE show(): add_timer_event owns the event loop from
        # here on. show(interactive_update=True)+update() is the WRONG
        # pattern (it fights VTK's own Cocoa run loop on macOS and starves
        # it) — see docs/archive/2026-07-28_PYVISTA_TWIN_PLAN.md WP-LOOP.
        pl.add_timer_event(max_steps=2**31 - 1, duration=33, callback=self._on_timer)
        pl.show()


# ---------------------------------------------------------------------------
# --self-check — must work WITHOUT pyvista/vtk installed
# ---------------------------------------------------------------------------
def self_check() -> bool:
    ok = True
    print(f"[self-check] pyvista/vtk installed: {HAVE_PYVISTA}")

    from config import load_config
    cfg = load_config()

    body = build_body_geometry(cfg)
    for k in ("V_core", "V_inner", "V_ring", "V_outer", "V_wood"):
        n = len(body[k])
        print(f"  {k}: {n} tris")
        if n == 0:
            ok = False
    print(f"  z_disc_bot = {body['z_disc_bot']} mm")

    disc = solve_active_disc(cfg, body["z_disc_bot"])
    print(f"  disc: {len(disc['V_disc'])} tris  "
          f"dT_eddy {disc['dTe'].min():.2f}..{disc['dTe'].max():.2f} K  "
          f"tau={disc['rom'].tau:.1f}s")

    rom_c, lumped_c, lev_c = coeffs_from_live(cfg, disc["em"], disc["rom"])
    twin = TwinState(rom=rom_c, lumped=lumped_c, lev=lev_c, T_amb=rom_c.T_amb)
    for _ in range(10):
        twin.step(5.0, 1.0)
    print(f"  TwinState smoke test: t={twin.t}s  beta={twin.rom_state.beta:.4f}  "
          f"T_field.max()={float(twin.T_field.max()):.2f}C")
    if not (twin.T_field.max() > rom_c.T_amb):
        ok = False

    field_lines, B_max = None, 0.0
    from build_twin_html_fem import compute_em_field_lines
    field_lines, B_max = compute_em_field_lines(disc["em"], cfg)
    print(f"  field lines: {len(field_lines)} contours  B_max={B_max:.3f} T")

    if HAVE_PYVISTA:
        poly = build_field_lines_polydata(field_lines)
        n_lines = poly.n_cells if poly is not None else 0
        print(f"  field-line PolyData: {n_lines} polylines, {0 if poly is None else poly.n_points} points")
        pd = soup_to_polydata(disc["V_disc"])
        if pd.n_points != len(disc["V_disc"]) * 3:
            print("  FAIL: soup_to_polydata point count does not match unwelded triangle soup")
            ok = False

    print("PASS" if ok else "FAIL")
    return ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="PyVista 3D digital twin — TEAM 28-like")
    ap.add_argument("--self-check", action="store_true", help="Headless sanity check, no VTK needed")
    ap.add_argument("--screenshot", default=None, help="Save a static screenshot to this path")
    ap.add_argument("--no-show", action="store_true", help="Don't open an interactive window")
    ap.add_argument("--speed", type=float, default=1.0, help="Initial speed multiplier (1-200x)")
    ap.add_argument("--I", type=float, default=5.0, help="Initial current [A]")
    args = ap.parse_args()

    if args.self_check:
        return 0 if self_check() else 1

    if not HAVE_PYVISTA:
        print('PyVista/VTK not installed. Install with:\n'
              '  pip install "pyvista>=0.45" "vtk>=9.3,<9.7"\n'
              "For a working twin right now without that ~400MB dependency, "
              "use digital_twin.py (matplotlib) instead.")
        return 2

    from config import load_config
    cfg = load_config()
    twin_pv = TwinPyVista(cfg, args)

    if args.screenshot or args.no_show:
        twin_pv.run_static(screenshot=args.screenshot, show=not args.no_show)
        return 0

    twin_pv.run_live()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
