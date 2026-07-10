"""digital_twin.py — Real-time twin loop with interactive GUI.

Features:
  • Real-time T(r,z) heatmap
  • Current slider I (0–I_MAX, sized to the rig's variac) + a Variac dial
    slider (Carroll & Meynell CMV 10 E-1, 0–270) that drives I via the
    measured dial->current table (params.yaml power_supply)
  • Time-speed slider (1×–200×)
  • Metal plate selector from plate_library (Al Ø130/140/150/160mm, Ø160mm
    is the standard test disc) → automatically rebuilds ROM when a new plate
    is selected
  • I(t) scenarios: step / ramp / sine / pulse / manual
  • Space = pause/resume
"""
from __future__ import annotations
import sys, os, copy, math, time
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.tri as mtri
from matplotlib.widgets import Slider, RadioButtons, Button
from matplotlib.colors import Normalize
from matplotlib.animation import FuncAnimation

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# I(t) scenarios
# ---------------------------------------------------------------------------
def scenario_step(I: float = 5.0):
    return (lambda t: I), f"Step I={I}A"

def scenario_ramp(I: float = 5.0, t_r: float = 60.0):
    return (lambda t: min(t / t_r, 1.0) * I), f"Ramp 0→{I}A/{t_r:.0f}s"

def scenario_sine(I: float = 5.0):
    Im, Ia = I * 0.6, I * 0.4
    return (lambda t: max(0.0, Im + Ia * math.sin(2*math.pi*t/120))), f"Sin {Im:.1f}±{Ia:.1f}A"

def scenario_pulse(I: float = 5.0):
    return (lambda t: I if (t % 120) < 60 else 0.0), f"Pulse {I}A ON60/OFF60s"

SCENARIOS = {"step": scenario_step, "ramp": scenario_ramp,
             "sine": scenario_sine,  "pulse": scenario_pulse}


# ---------------------------------------------------------------------------
# DigitalTwin — Euler integration state machine
# ---------------------------------------------------------------------------
class DigitalTwin:
    """Holds β(t); T(r,z,t) = T_amb + β(t)·ΔT_ref(r,z)."""

    def __init__(self, rom, sigma_correction: bool = True):
        self.rom = rom
        self.sigma_correction = sigma_correction
        self._beta = 0.0
        self.t = 0.0
        self.hist_t    = [0.0]
        self.hist_I    = [0.0]
        self.hist_Tmax = [rom.T_amb]
        self.hist_Tmean= [rom.T_amb]

    def step(self, I: float, dt: float) -> None:
        r = self.rom
        ratio2 = (I / r.I_ref) ** 2
        s = r._sigma_scale(self._beta * r.dT_mean_ref) if self.sigma_correction else 1.0
        self._beta = max(0.0, self._beta + (ratio2 * s - self._beta) / r.tau * dt)
        self.t += dt
        T = self.T_field
        self.hist_t.append(self.t)
        self.hist_I.append(I)
        self.hist_Tmax.append(float(T.max()))
        self.hist_Tmean.append(float(T.mean()))

    @property
    def T_field(self) -> np.ndarray:
        return self.rom.T_amb + self._beta * self.rom.dT_ref

    def reset(self) -> None:
        self._beta = 0.0
        self.t = 0.0
        self.hist_t     = [0.0]
        self.hist_I     = [0.0]
        self.hist_Tmax  = [self.rom.T_amb]
        self.hist_Tmean = [self.rom.T_amb]


# ---------------------------------------------------------------------------
# Build ROM for a plate spec from plate_library
# ---------------------------------------------------------------------------
def _build_rom_for_plate(cfg_base, spec: dict, em_base=None, verbose=True):
    """Clone config, override plate, run EM+thermal → ThermalROM."""
    from config import Geometry
    from thermal_solver import solve_steady
    from rom import ThermalROM

    cfg = copy.deepcopy(cfg_base)
    mat_name = spec["material"]
    mat = cfg_base.raw["material_props"][mat_name]
    pm = cfg.raw["plate_material"]
    pm["name"]         = mat_name
    pm["radius_mm"]    = float(spec["radius_mm"])
    pm["thickness_mm"] = float(spec.get("thickness_mm", pm["thickness_mm"]))
    for k, v in mat.items():
        pm[k] = float(v)
    cfg.geometry = Geometry(
        plate_radius_m    = pm["radius_mm"]    * 1e-3,
        plate_thickness_m = pm["thickness_mm"] * 1e-3,
        plate_z_bottom_m  = cfg_base.geometry.plate_z_bottom_m,
    )

    em = None
    if em_base is not None:
        from em_solver import compute_losses
        if verbose:
            print(f"  [EM] Solving for {spec['name']}... ", end="", flush=True)
        em = compute_losses(cfg)
        if verbose:
            print(f"P={em['P_plate_W']*1e3:.1f} mW")

    rom = ThermalROM().build(cfg, em_losses=em, verbose=verbose)
    return rom


# ---------------------------------------------------------------------------
# run_live — main animation loop
# ---------------------------------------------------------------------------
def run_live(
    rom_default,
    cfg,
    em_base=None,
    scenario_name: str = "step",
    I_init: float = 5.0,
    dt_sim: float = 1.0,
    t_window: float = 600.0,
    speed_init: float = 1.0,
    interval_ms: int = 100,
) -> FuncAnimation:

    plate_lib  = cfg.raw.get("plate_library", [])
    plate_names = [s["name"] for s in plate_lib]

    # Find the plate_library entry that matches the ACTIVE (default) plate by
    # value — radius_mm + material — not by reconstructing a name string and
    # string-matching it (that broke silently when plate_library's naming
    # convention didn't match: see CLAUDE.md H4 / docs/AUDIT_FIX_PLAN_2026-07-04.md).
    default_radius_mm = cfg.geometry.plate_radius_m * 1e3
    default_material  = cfg.plate.get("name", "aluminium")
    default_spec = next(
        (s for s in plate_lib
         if abs(s["radius_mm"] - default_radius_mm) < 1e-6
         and s.get("material", "aluminium") == default_material),
        None,
    )
    if default_spec is not None:
        default_name = default_spec["name"]
    else:
        # No plate_library entry matches the active plate_material config
        # (radius+material) -- do NOT silently borrow an unrelated entry's
        # name for it. That was the original H4 bug: the RadioButtons would
        # show e.g. "Al Ø100mm" as pre-selected/active while the ROM actually
        # running was for a different radius, and because state["plate_name"]
        # already equalled that borrowed name, clicking it was a permanent
        # no-op (see CLAUDE.md H4 / docs/AUDIT_FIX_PLAN_2026-07-04.md).
        # Synthesize an honest, distinct label instead and add it as its own
        # selectable entry so the UI can never lie about which plate is active.
        default_name = (f"Active (Ø{2*default_radius_mm:.0f}mm "
                         f"{default_material}, not in plate_library)")
        plate_names = [default_name] + plate_names
        print(f"[digital_twin] WARNING: active plate (radius_mm={default_radius_mm:.1f}, "
              f"material={default_material}) has no matching plate_library entry -- "
              f"showing it as '{default_name}' instead of mislabeling an unrelated entry.")

    # Cache ROM by plate name; pre-populate with default plate
    _rom_cache: dict[str, object] = {default_name: rom_default}

    # Shared mutable state
    state = {
        "rom":       rom_default,
        "twin":      DigitalTwin(rom_default),
        "I_func":    SCENARIOS[scenario_name](I_init)[0],
        "sc_label":  SCENARIOS[scenario_name](I_init)[1],
        "I_manual":  I_init,
        "sc_name":   scenario_name,
        "speed":     speed_init,
        "paused":    False,
        "building":  False,
        "plate_name": list(_rom_cache.keys())[0],
    }

    # -----------------------------------------------------------------------
    # Layout figure
    # -----------------------------------------------------------------------
    DARK_BG  = "#0f0f1e"
    DARK_AX  = "#12121e"
    TEXT_CLR = "#aaaacc"
    TITLE_CLR= "#ddddf5"

    fig = plt.figure(figsize=(15, 8))
    fig.patch.set_facecolor(DARK_BG)

    # --- Axes ---
    ax_T    = fig.add_axes([0.03, 0.26, 0.27, 0.64])   # heatmap
    ax_t    = fig.add_axes([0.36, 0.52, 0.61, 0.40])   # T(t)
    ax_I    = fig.add_axes([0.36, 0.30, 0.61, 0.17])   # I(t)
    ax_slI    = fig.add_axes([0.36, 0.17, 0.16, 0.05])   # slider I
    ax_slDial = fig.add_axes([0.56, 0.17, 0.16, 0.05])   # slider Variac dial
    ax_slSp   = fig.add_axes([0.76, 0.17, 0.21, 0.05])   # slider speed
    ax_plate= fig.add_axes([0.03, 0.04, 0.14, 0.18])   # plate radio
    ax_sc   = fig.add_axes([0.19, 0.04, 0.10, 0.18])   # scenario radio
    ax_info = fig.add_axes([0.36, 0.04, 0.61, 0.10])   # info text box

    def _style_ax(ax, title=""):
        ax.set_facecolor(DARK_AX)
        for sp in ax.spines.values(): sp.set_edgecolor("#334455")
        ax.tick_params(colors=TEXT_CLR, labelsize=8)
        for lbl in [ax.xaxis.label, ax.yaxis.label, ax.title]:
            lbl.set_color(TEXT_CLR)
        if title: ax.set_title(title, fontsize=9, color=TITLE_CLR)

    for ax, t_ in [(ax_T, "T(r,z) — plate cross-section"), (ax_t, "Temperature vs. time"),
                   (ax_I, "Current I(t)"), (ax_info, "")]:
        _style_ax(ax, t_)

    ax_info.axis("off")
    txt_info = ax_info.text(0.01, 0.85, "", transform=ax_info.transAxes,
                             fontsize=9, color=TEXT_CLR, va="top", family="monospace")

    # -----------------------------------------------------------------------
    # Slider I
    # -----------------------------------------------------------------------
    # I_MAX covers the rig's real max current (variac dial 270 -> 7.78A measured
    # 2026-07-02, docs/rig_photo.jpg), with a little headroom over the old 5.0A cap.
    ps = cfg.power_supply
    I_MAX = max(5.0, cfg.dial_to_current_A(ps["dial_max"])) if ps else 5.0
    sl_I = Slider(ax_slI, "I (A)", 0.0, round(I_MAX + 0.5, 1), valinit=I_init,
                  color="#335588", track_color="#223355")
    sl_I.label.set_color(TEXT_CLR); sl_I.valtext.set_color("#ffcc44")
    ax_slI.set_facecolor(DARK_AX)

    @sl_I.on_changed
    def _on_I(val):
        state["I_manual"] = val
        if state["sc_name"] == "manual":
            state["I_func"] = lambda t: state["I_manual"]

    # -----------------------------------------------------------------------
    # Variac dial slider (Carroll & Meynell CMV 10 E-1, docs/rig_photo.jpg) —
    # a convenience control that drives sl_I via the measured dial->I table
    # (params.yaml power_supply), so the twin can be operated the same way as
    # the physical rig's knob instead of typing amps directly.
    # -----------------------------------------------------------------------
    if ps:
        sl_dial = Slider(ax_slDial, "Dial", ps["dial_min"], ps["dial_max"],
                          valinit=220.0, color="#553388", track_color="#332255")
        sl_dial.label.set_color(TEXT_CLR); sl_dial.valtext.set_color("#cc99ff")
        ax_slDial.set_facecolor(DARK_AX)

        @sl_dial.on_changed
        def _on_dial(val):
            sl_I.set_val(cfg.dial_to_current_A(val))

    # -----------------------------------------------------------------------
    # Speed slider (1× – 200×, log scale)
    # -----------------------------------------------------------------------
    _log_min, _log_max = 0.0, math.log10(200)
    sl_spd = Slider(ax_slSp, "Speed", _log_min, _log_max,
                    valinit=math.log10(max(speed_init, 1.0)),
                    color="#335533", track_color="#223322")
    sl_spd.label.set_color(TEXT_CLR)
    sl_spd.valtext.set_color("#88ffaa")
    ax_slSp.set_facecolor(DARK_AX)

    def _fmt_speed(log_val):
        v = 10 ** log_val
        return f"{v:.0f}×" if v >= 10 else f"{v:.1f}×"
    sl_spd.valtext.set_text(_fmt_speed(sl_spd.val))

    @sl_spd.on_changed
    def _on_speed(val):
        state["speed"] = 10 ** val
        sl_spd.valtext.set_text(_fmt_speed(val))

    # -----------------------------------------------------------------------
    # Plate selector
    # -----------------------------------------------------------------------
    ax_plate.set_facecolor(DARK_AX)
    ax_plate.set_title("Metal plate", fontsize=8, color=TITLE_CLR, pad=2)
    disp_names = plate_names if plate_names else ["(none)"]
    init_idx = disp_names.index(state["plate_name"]) if state["plate_name"] in disp_names else 0
    radio_plate = RadioButtons(ax_plate, disp_names, active=init_idx)
    for lbl in radio_plate.labels:
        lbl.set_color(TEXT_CLR); lbl.set_fontsize(7.5)

    def _on_plate(name):
        if name == state["plate_name"] or state["building"]:
            return
        state["building"] = True
        state["paused"]   = True
        fig.suptitle("Building ROM...", color="#ffaa44", fontsize=11)
        fig.canvas.draw()
        fig.canvas.flush_events()

        if name not in _rom_cache:
            spec = next((s for s in plate_lib if s["name"] == name), None)
            if spec is None:
                state["building"] = False; state["paused"] = False; return
            new_rom = _build_rom_for_plate(cfg, spec, em_base=em_base, verbose=True)
            _rom_cache[name] = new_rom

        state["rom"]  = _rom_cache[name]
        state["plate_name"] = name
        state["twin"] = DigitalTwin(state["rom"])

        # Reset mesh and colormap for new plate
        _reinit_heatmap()

        state["building"] = False
        state["paused"]   = False
        _update_title()

    radio_plate.on_clicked(_on_plate)

    # -----------------------------------------------------------------------
    # Scenario selector
    # -----------------------------------------------------------------------
    ax_sc.set_facecolor(DARK_AX)
    ax_sc.set_title("Scenario", fontsize=8, color=TITLE_CLR, pad=2)
    sc_list = list(SCENARIOS.keys()) + ["manual"]
    init_sc = sc_list.index(scenario_name) if scenario_name in sc_list else 0
    radio_sc = RadioButtons(ax_sc, sc_list, active=init_sc)
    for lbl in radio_sc.labels:
        lbl.set_color(TEXT_CLR); lbl.set_fontsize(7.5)

    def _on_sc(name):
        state["sc_name"] = name
        I_now = sl_I.val
        if name in SCENARIOS:
            fn, lbl = SCENARIOS[name](I_now)
            state["I_func"]   = fn
            state["sc_label"] = lbl
        else:
            state["I_func"]   = lambda t: state["I_manual"]
            state["sc_label"] = f"Manual I={I_now:.1f}A"
        state["twin"].reset()
        _update_title()

    radio_sc.on_clicked(_on_sc)

    # -----------------------------------------------------------------------
    # Heatmap — init & reinit on plate change
    # -----------------------------------------------------------------------
    _hmap = {}   # holds heatmap state

    def _reinit_heatmap():
        rom  = state["rom"]
        coords = rom.res_ref["coords"]
        tris   = rom.res_ref["tris"]
        R_mm = rom.cfg.geometry.plate_radius_m * 1e3
        t_mm = rom.cfg.geometry.plate_thickness_m * 1e3
        r_mm = coords[:, 0] * 1e3
        z_mm = coords[:, 1] * 1e3

        T_ss = rom.T_steady(sl_I.val if sl_I.val > 0.1 else 5.0).max()
        _hmap["triang"]  = mtri.Triangulation(r_mm, z_mm, tris)
        _hmap["levels"]  = np.linspace(rom.T_amb - 0.5, T_ss + 1.0, 50)
        _hmap["norm"]    = Normalize(vmin=rom.T_amb - 0.5, vmax=T_ss + 1.0)
        _hmap["R_mm"]    = R_mm
        _hmap["t_mm"]    = t_mm

    _reinit_heatmap()
    cmap_hot = plt.colormaps["hot"]

    # Colorbar — created once, norm updated on plate change
    T0 = state["twin"].T_field
    ax_T.tricontourf(_hmap["triang"], T0, levels=_hmap["levels"],
                     cmap=cmap_hot, norm=_hmap["norm"])
    _cbar = [fig.colorbar(
        plt.cm.ScalarMappable(norm=_hmap["norm"], cmap=cmap_hot),
        ax=ax_T, pad=0.02, fraction=0.07)]
    _cbar[0].set_label("°C", color=TEXT_CLR, fontsize=8)
    _cbar[0].ax.tick_params(colors=TEXT_CLR, labelsize=7)

    # -----------------------------------------------------------------------
    # Time-trace lines
    # -----------------------------------------------------------------------
    ax_t.set_facecolor(DARK_AX); ax_t.grid(alpha=0.12, color="#334466")
    ax_I.set_facecolor(DARK_AX); ax_I.grid(alpha=0.12, color="#334466")
    for ax_ in [ax_t, ax_I]:
        for sp in ax_.spines.values(): sp.set_edgecolor("#334455")
        ax_.tick_params(colors=TEXT_CLR, labelsize=8)

    line_Tmax,  = ax_t.plot([], [], "-",  color="#ff6644", lw=1.8, label="T_max")
    line_Tmean, = ax_t.plot([], [], "--", color="#ffaa44", lw=1.2, label="T_mean")
    line_Tss,   = ax_t.plot([], [], ":",  color="#44ff88", lw=1.0, label="T_ss(I)")
    hline_Tamb  = ax_t.axhline(state["rom"].T_amb, color="#445566", lw=0.7, ls=":")
    ax_t.set_ylabel("Temperature (°C)", color=TEXT_CLR)
    ax_t.set_xlabel("Time (min)", color=TEXT_CLR)
    ax_t.set_title("Temperature vs. time", fontsize=9, color=TITLE_CLR)
    ax_t.legend(fontsize=7, loc="upper left",
                facecolor=DARK_BG, edgecolor="#445566", labelcolor=TEXT_CLR)

    line_I, = ax_I.plot([], [], "-", color="#44aaff", lw=1.5)
    ax_I.set_ylabel("I (A)", color=TEXT_CLR)
    ax_I.set_xlabel("Time (min)", color=TEXT_CLR)
    ax_I.set_title("Current I(t)", fontsize=9, color=TITLE_CLR)

    # -----------------------------------------------------------------------
    # Title & helpers
    # -----------------------------------------------------------------------
    def _update_title():
        rom = state["rom"]
        fig.suptitle(
            f"Thermal Digital Twin — {state['plate_name']}  |  "
            f"τ={rom.tau/60:.1f} min  |  {state['sc_label']}",
            color=TITLE_CLR, fontsize=11, y=0.99)

    _update_title()

    # Space = pause
    def _on_key(ev):
        if ev.key == " ":
            state["paused"] = not state["paused"]
    fig.canvas.mpl_connect("key_press_event", _on_key)

    # -----------------------------------------------------------------------
    # Animation update
    # -----------------------------------------------------------------------
    def update(_frame):
        if state["paused"] or state["building"]:
            return

        twin = state["twin"]
        rom  = state["rom"]
        I_fn = state["I_func"]
        spd  = state["speed"]

        # Integrate several steps
        n_steps = max(1, int(round(spd)))
        dt_eff  = dt_sim * spd / n_steps
        for _ in range(n_steps):
            I_now = max(0.0, min(float(I_fn(twin.t)), I_MAX))
            twin.step(I_now, dt_eff)

        T_cur   = twin.T_field
        t_min   = np.array(twin.hist_t)  / 60.0
        I_hist  = np.array(twin.hist_I)
        Tmax_h  = np.array(twin.hist_Tmax)
        Tmean_h = np.array(twin.hist_Tmean)

        # --- Heatmap ---
        ax_T.cla()
        _style_ax(ax_T, "T(r,z) — plate cross-section")
        ax_T.tricontourf(_hmap["triang"], T_cur,
                         levels=_hmap["levels"], cmap=cmap_hot, norm=_hmap["norm"])
        ax_T.set_xlabel("r (mm)", color=TEXT_CLR)
        ax_T.set_ylabel("z (mm)", color=TEXT_CLR)
        ax_T.set_xlim(-1, _hmap["R_mm"] + 2)
        ax_T.set_ylim(-0.2, _hmap["t_mm"] + 0.2)
        ax_T.set_aspect("auto")
        ax_T.text(0.04, 0.94, f"T_max = {T_cur.max():.2f} °C",
                  transform=ax_T.transAxes, fontsize=11,
                  color="#ffcc44", fontweight="bold", va="top")
        ax_T.text(0.04, 0.82, f"t = {twin.t/60:.2f} min\nI = {twin.hist_I[-1]:.2f} A",
                  transform=ax_T.transAxes, fontsize=9, color="#88aaff", va="top")

        # --- Time axis (sliding window) ---
        t_now  = twin.t / 60.0
        x_lo   = max(0.0, t_now - t_window / 60.0)
        x_hi   = max(t_window / 60.0, t_now)

        line_Tmax.set_data(t_min, Tmax_h)
        line_Tmean.set_data(t_min, Tmean_h)

        I_cur = twin.hist_I[-1]
        T_ss_now = rom.T_steady(I_cur).max()
        line_Tss.set_data([x_lo, x_hi], [T_ss_now, T_ss_now])
        hline_Tamb.set_ydata([rom.T_amb, rom.T_amb])

        ax_t.set_xlim(x_lo, x_hi)
        y_lo = rom.T_amb - 0.5
        y_hi = max(_hmap["levels"][-1], Tmax_h.max() + 0.5)
        ax_t.set_ylim(y_lo, y_hi)

        line_I.set_data(t_min, I_hist)
        ax_I.set_xlim(x_lo, x_hi)
        ax_I.set_ylim(0, max(I_hist.max() * 1.15, 0.5))

        # --- Info text ---
        dT_cur = T_cur.max() - rom.T_amb
        dT_ss  = T_ss_now - rom.T_amb
        ratio  = dT_cur / dT_ss * 100 if dT_ss > 0.01 else 0.0
        txt_info.set_text(
            f"Plate: {state['plate_name']}   R={rom.cfg.geometry.plate_radius_m*1e3:.0f}mm  "
            f"t={rom.cfg.geometry.plate_thickness_m*1e3:.1f}mm  "
            f"mat={rom.cfg.plate['name']}\n"
            f"τ={rom.tau/60:.1f} min   UA={rom.UA:.4f} W/K   "
            f"ΔT_max={dT_cur:.2f}K  →  {ratio:.0f}% of T_ss   "
            f"[Space]=pause  Speed={state['speed']:.0f}×"
        )

    ani = FuncAnimation(fig, update, interval=interval_ms, cache_frame_data=False)
    plt.show()
    return ani


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse(transient: dict | None = None):
    """CLI args. --dt/--window default from params.yaml's `transient` block
    (dt_s/t_end_s) instead of duplicating those numbers as hardcoded literals."""
    import argparse
    tr = transient or {}
    p = argparse.ArgumentParser(description="Thermal Digital Twin — TEAM 28-like")
    p.add_argument("--scenario", default="step",
                   choices=list(SCENARIOS.keys()) + ["manual"])
    p.add_argument("--I",      type=float, default=5.0, help="Current [A]")
    p.add_argument("--speed",  type=float, default=1.0, help="Initial speed (1–200)")
    p.add_argument("--window", type=float, default=tr.get("t_end_s", 600.0),
                   help="Time window [s] (default: params.yaml transient.t_end_s)")
    p.add_argument("--dt",     type=float, default=tr.get("dt_s", 1.0),
                   help="Integration step [s] (default: params.yaml transient.dt_s)")
    p.add_argument("--no-em",  action="store_true",
                   help="Skip EM solve, use placeholder (fast startup)")
    p.add_argument("--interval", type=int, default=100, help="Frame interval [ms]")
    return p.parse_args()


if __name__ == "__main__":
    from config import load_config
    from rom import ThermalROM

    cfg = load_config()
    args = _parse(cfg.raw.get("transient", {}))

    em = None
    if not args.no_em:
        from em_solver import compute_losses
        print(f"[EM] Solving at î={cfg.I}A... ", end="", flush=True)
        em = compute_losses(cfg)
        print(f"P_plate={em['P_plate_W']*1e3:.1f} mW  P_coil={em['P_coil_W']:.1f}W")

    rom = ThermalROM().build(cfg, em_losses=em, verbose=True)

    print(f"\nStarting Digital Twin:")
    print(f"  Scenario : {args.scenario}  (I={args.I}A)")
    print(f"  Speed    : {args.speed}×  (use slider to change)")
    print(f"  [Space]  : pause / resume")
    print(f"  Plate    : click radio → auto-rebuild ROM (~5-10s with EM)")

    run_live(
        rom,
        cfg,
        em_base=em,
        scenario_name=args.scenario,
        I_init=args.I,
        dt_sim=args.dt,
        t_window=args.window,
        speed_init=args.speed,
        interval_ms=args.interval,
    )
