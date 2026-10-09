"""build_twin_html_fem.py — Bake FEM-accurate thermal digital twin into HTML.

Physics engine (identical to digital_twin.py):
  • Full axisymmetric FEM field dT_ref(r,z) from rom.py — interpolated to every
    STL plate vertex at build time and embedded as Float32 array.
  • ROM β(t) Euler integration in JS:  τ·dβ/dt = (I/I_ref)²·σ(T) − β
  • T(r,z,t) = T_amb + β(t)·dT_ref_vtx[vertex]   ← spatial FEM field, per vertex
  • σ(T) correction (same formula as rom.py)
  • Lumped RC ODE for inner coil / outer coil / iron (same as build_twin_html.py)
  • I(t) scenarios: step / ramp / sine / pulse
  • Rolling time-trace canvas chart of T_max(t)

vs existing build_twin_html.py (lumped only):
  • Plate: FEM field (N_nodes=697, mapped to 28 044 STL vertices)
  • Transient: ROM τ (not ad-hoc RC)
  • σ(T) feedback included

Run:
    python build_twin_html_fem.py [3D_model.stl]
Output:
    digital_twin_fem.html   (standalone, double-click to run)
"""
from __future__ import annotations
import sys, os, struct, base64, json, math, copy, datetime, time
import numpy as np
from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


# Single key loader (local/.env.local -> env -> placeholder) lives in weather_api.py.
from weather_api import load_key as _load_google_weather_key

from config import load_config, Geometry
from em_solver import compute_losses, compute_lift_force
from rom import ThermalROM
from scipy.optimize import brentq


# ─── WP-C (2026-07-02) lift-force anchors, wired live by WP-D ─────────────────
# WP-D (2026-07-02) folded this into params.yaml (`levitation:` block) + the
# PARAMS JSON export via lev_params() below -- the JS levitation-gap block
# (search "Levitation gap physics") now reads PARAMS.lev instead of hardcoding
# Z_GAP_5A_MM/Z_DECAY_MM.
# WP-LEV (2026-07-28, docs/archive/2026-07-28_BUG_REGISTER.md L1/L2): EVERY plate
# radius -- including the default R=80mm -- now goes through `_lev_anchor()`'s
# root-find below; R=80mm no longer special-cases straight to params.yaml's
# `levitation.z_gap_5A_mm`/`z_decay_mm` scalars (those are kept only as a
# reference/reproducibility anchor, see the comment on that params.yaml block).
# This also fixes the R=101mm "wrong nonzero gap at 5A" bug flagged below, AND
# the R=65/70/75mm "clamped to exactly 5.000mm" bug that motivated this rewrite
# in the first place (the OLD `_lev_anchor()` used a 3-point np.interp that
# silently clamped z_eq whenever the true crossing lay past its z=5mm table
# ceiling -- true for every radius except R=80).
#
# All F_z values computed with em_solver.compute_lift_force() at the physical
# PEAK current I_peak = 5A_rms*sqrt(2) = 7.0711A (CLAUDE.md "CURRENT CONVENTION"),
# default EM mesh (em_domain.fine_step_mm=2.0mm, unchanged -- matches the
# existing R=80 pipeline so the two rows are apples-to-apples). z=3.8mm is the
# PHYSICAL resting floor (plate_material.z_bottom_mm default = winding-form
# spacer height): the disc cannot get closer to the coil than this, so it is
# the correct z to test "does F clear gravity" at (not z=1mm, which isn't
# physically reachable at rest).
#
# R=80mm row reproduces the already-locked CLAUDE.md result exactly (z_eq=4.15
# vs the documented 4.1mm) -- confirms this derivation matches the existing
# validated pipeline. R=101mm is the new WP-C result: F(3.8mm) < F_grav at
# 5A_rms, i.e. the Ø202mm disc does NOT levitate at the standard operating
# point -- I_min_lev_A is the key new number, not a z_eq.
#
# z0 (decay length) is fit from two REAL points on the F(z) curve at z=1mm and
# z=5mm: z0=(5-1)/ln(F(1mm)/F(5mm)). WP-Z0 (2026-07-10, docs/AUDIT_FIX_PLAN_
# 2026-07-04.md OQ-4) resolved a prior disagreement: an EARLIER z0=21.4mm for
# R=80 (2026-07-01 CLAUDE.md entry, since removed) instead anchored the second
# point at the F=F_grav crossing itself (z0=(z_eq-1)/ln(F(1mm)/F_grav)) -- the
# two methods disagreed ~1.5x (13.6mm vs 21.4mm) because F(z) isn't a clean
# single exponential over that range. User confirmed the real rig's gap only
# "nudges up a little" at 7.75A, matching 13.6mm (21.4mm predicted
# z_eq(7.75A)≈22.9mm, clearly too large) -- params.yaml's `levitation.
# z_decay_mm` was switched to 13.6mm so R=80 now uses the SAME F1/F5 method as
# this dict uses for every other radius (reproducible from
# compute_lift_force() alone, no F_grav/mass dependency baked into the shape
# fit). Treat z0 as order-of-magnitude regardless of method (mesh-sensitive --
# see the WP-C report for a fine_step_mm convergence check that moved
# z_eq(R=80) by ~0.7mm and I_min_lev(R=101) by ~0.5A between fine_step=2.0mm
# and 1.0mm; no real multi-current gap measurement exists yet either).
def _find_z_eq(F_at, F_grav: float, z_max_mm: float = 40.0,
                z_step_mm: float = 2.0) -> float:
    """Bracket + converge the crossing F(z)=F_grav (WP-LEV, bug register L1):
    coarse-scan z=1..z_max_mm mm in z_step_mm steps looking for the sign change
    of F(z)-F_grav, then refine with scipy.optimize.brentq. Unlike the old
    3-point np.interp, this never silently clamps to the table's endpoint when
    the true crossing lies further out (R=65/70/75's crossings are all past the
    old table's 5mm ceiling, at 13.6-15.7mm).

    compute_lift_force() has a real (small) mesh-quantization artifact: at
    R=70mm, F(z) briefly dips a few hundredths of a Newton below F_grav in a
    ~0.2mm-wide notch near z=14.0mm before recovering and continuing its smooth
    decline to the true crossing further out -- a naive "stop at the first
    sign change" bracket locks onto that transient notch instead of the real
    equilibrium. Guard against it: once a candidate bracket is found, require
    the sign to STICK for one more coarse step before accepting it as the
    crossing to refine with brentq."""
    z = 1.0
    while z < z_max_mm:
        z_next = min(z + z_step_mm, z_max_mm)
        F_next = F_at(z_next)
        if F_next <= F_grav:
            z_confirm = min(z_next + z_step_mm, z_max_mm)
            F_confirm = F_at(z_confirm) if z_confirm > z_next else F_next
            if F_confirm <= F_grav or z_confirm <= z_next:
                return float(brentq(lambda zz: F_at(zz) - F_grav, z, z_next, xtol=1e-3))
            # Transient notch (F dipped below F_grav then recovered) -- keep
            # scanning forward from the recovered point instead of the notch.
            z = z_confirm
            continue
        z = z_next
    # No sign change found up to z_max_mm -- shouldn't happen for any radius in
    # plate_library (true crossings are 11.9-15.7mm), but fall back to the edge
    # rather than raising, matching the old code's "clamp" failure mode at least
    # in shape (though this should never actually be hit).
    return z_max_mm


def _lev_anchor(radius_mm: float, plate_thickness_mm: float = 3.0) -> dict:
    """Recompute the lift-force anchors for one plate radius. Re-solves EM from
    scratch at the given radius (NOT scaled from another radius's result) --
    see the WP-C module docstring above for why that matters once the disc
    overlaps the outer_iron_ring / outer-coil field region."""
    cfg = load_config()
    R_m = radius_mm * 1e-3
    t_m = plate_thickness_mm * 1e-3
    cfg.raw["plate_material"]["radius_mm"] = float(radius_mm)
    m_kg = cfg.plate["rho_kg_per_m3"] * math.pi * R_m ** 2 * t_m
    F_grav = m_kg * 9.81

    def F_at(z_mm):
        cfg.raw["plate_material"]["z_bottom_mm"] = float(z_mm)
        cfg.geometry = Geometry(plate_radius_m=R_m, plate_thickness_m=t_m,
                                 plate_z_bottom_m=float(z_mm) * 1e-3)
        # WP-PEAK (docs/archive/2026-07-04_AUDIT_FIX_PLAN.md): force needs the TRUE
        # phasor amplitude cfg.I_peak, not a manual current_A=5*sqrt(2) mutation
        # (the old pattern here, now handled cleanly via compute_lift_force's
        # own I_amplitude parameter). cfg.I stays at its natural params.yaml
        # value (5.0A_rms) so cfg.I_peak = 5*sqrt(2) = 7.071A, numerically
        # identical to the old hack.
        return compute_lift_force(cfg, I_amplitude=cfg.I_peak)

    F1, F38, F5 = F_at(1.0), F_at(3.8), F_at(5.0)
    z0_mm = (5.0 - 1.0) / math.log(F1 / F5)

    out = {"radius_mm": radius_mm, "mass_kg": round(m_kg, 5), "F_grav_N": round(F_grav, 4),
           "F_at_1mm_N": round(F1, 4), "F_at_3p8mm_N": round(F38, 4),
           "z0_decay_mm": round(z0_mm, 2)}
    if F38 >= F_grav:
        out["z_eq_5A_mm"] = round(_find_z_eq(F_at, F_grav), 2)
        out["levitates_at_5A_rms"] = True
    else:
        out["I_min_lev_A_rms"] = round(5.0 * math.sqrt(F_grav / F38), 2)
        out["levitates_at_5A_rms"] = False
    return out


def lev_params(cfg) -> dict:
    """WP-D (2026-07-02): bake the levitation spring-mass-damper constants into
    PARAMS.lev instead of JS hardcoding them (params.yaml.levitation).

    WP-LEV (2026-07-28, bug register L1/L2): EVERY plate radius, including the
    default R=80mm, now goes through the SAME `_lev_anchor()` root-find. R=80
    used to special-case straight to params.yaml's z_gap_5A_mm/z_decay_mm (a
    real 10-point F(z) sweep from run_rig_validation()) while every other
    radius used the OLD 3-point-np.interp `_lev_anchor()`, which silently
    CLAMPED z_eq to 5.000mm for any disc whose true crossing lay past 5mm (i.e.
    every radius except R=80) -- the exact opposite of the physics (R=65/70/75
    all "floated" at the same clamped 5.000mm, hiding that the smallest disc
    should float highest). Now that `_lev_anchor()` does a real bracketing
    root-find (z=1..40mm), it reproduces R=80's own params.yaml anchor to
    within ~0.15mm (11.86 vs 11.7mm -- different sweep resolution, not a
    method difference), so a single code path is correct for all radii.
    """
    lv = cfg.raw.get("levitation", {})
    radius_mm = float(cfg.plate["radius_mm"])

    anchor = _lev_anchor(radius_mm, cfg.plate["thickness_mm"])
    z_decay = float(anchor["z0_decay_mm"])
    if anchor.get("levitates_at_5A_rms"):
        z_gap_5A = float(anchor["z_eq_5A_mm"])
    else:
        I_min = float(anchor["I_min_lev_A_rms"])
        z_gap_5A = 2.0 * z_decay * math.log(5.0 / I_min)

    return {
        "z_gap_5A_mm":        round(z_gap_5A, 4),
        "z_decay_mm":         round(z_decay, 4),
        "zeta0":              float(lv.get("zeta0", 0.0)),
        "zeta1":              float(lv.get("zeta1", 0.02)),
        "jit_mm":             float(lv.get("jit_mm", 0.3)),
        "jit_freq1":          float(lv.get("jit_freq1_rad_s", 27.0)),
        "jit_freq2":          float(lv.get("jit_freq2_rad_s", 71.0)),
        "z_gap_exaggeration": float(lv.get("z_gap_exaggeration", 2.0)),
        # WP-HTML (2026-07-10): jitter fade-out threshold, was a JS literal `0.5`
        # (fadeIn = 1 - lev.z/0.5) in levStep(). A sibling agent may add this key
        # to params.yaml's `levitation:` block concurrently -- default matches
        # the old hardcoded behaviour exactly if the key isn't there yet.
        "jit_fade_mm":        float(lv.get("jit_fade_mm", 0.5)),
        # WP-SHIMMER V2 (2026-07-28): sustained levitating shimmer, DISPLAY ONLY
        # (see params.yaml's comment on lev_ripple_display_gain). mains_omega_rad_s
        # is DERIVED from excitation.frequency_Hz (not a separate hand-entered
        # constant) so LevCoeffs.x_ripple_mm/JS xRippleMm stay correct if the
        # mains frequency ever changes.
        "lev_ripple_display_gain": float(lv.get("lev_ripple_display_gain", 0.0)),
        "mains_omega_rad_s": 2.0 * math.pi * float(cfg.freq),
    }


def ambient_presets(cfg) -> list:
    """Fixed-ambient choices for the HTML's T_amb selector (the third choice,
    Live, is the Google Weather reading). Both values come from params.yaml:
    thermal_bc.T_ambient_degC = the reference the FEM/ROM is solved at, and
    validation_data.ambient_C = the lab during the IR sessions the coil hA
    values are bounded against."""
    T_ref = float(cfg.raw["thermal_bc"]["T_ambient_degC"])
    presets = [{"key": "ref", "value": T_ref,
                "note": "model reference (thermal_bc.T_ambient_degC)"}]
    lab = cfg.raw.get("validation_data", {}).get("ambient_C")
    if lab is not None and float(lab) != T_ref:
        presets.append({"key": "lab", "value": float(lab),
                        "note": "lab during the IR calibration session (validation_data)"})
    return presets


def live_sensor_params(cfg) -> dict:
    """params.yaml live_sensor block for the HTML's Sensor excitation mode —
    the same knobs digital_twin_live.py reads, so both live paths condition
    the measured current identically."""
    from twin_model import live_i_max_for   # lazy: twin_model imports this module too
    ls = cfg.raw.get("live_sensor") or {}
    return {
        "baudrate": int(ls.get("baudrate", 9600)),
        "deadband_A": float(ls.get("deadband_A", 0.2)),
        "stale_after_s": float(ls.get("stale_after_s", 3.0)),
        "max_gap_s": float(ls.get("max_gap_s", 10.0)),
        "invalid_above_A": float(ls.get("invalid_above_A", 20.0)),
        "zero_cal_s": float(ls.get("zero_cal_s", 0.0)),
        "zero_cal_max_A": float(ls.get("zero_cal_max_A", 1.0)),
        "zero_offset_mode": str(ls.get("zero_offset_mode", "linear")),
        "zero_offset_default_A": float(ls.get("zero_offset_default_A", 0.0)),
        "board_offsets": [{"name": str(b["name"]), "usb_id": str(b["usb_id"]).lower(),
                           "I0_A": float(b["I0_A"])} for b in ls.get("board_offsets") or []],
        "i_max_A": float(live_i_max_for(cfg)),
    }


def power_supply_params(cfg) -> dict:
    """Carroll & Meynell CMV 10 E-1 variac dial->current table (params.yaml
    power_supply, identified 2026-07-02 from docs/rig_photo.jpg). Lets the HTML
    twin's "Variac dial" input mode reproduce the real rig's knob instead of a
    bare amps slider -- JS does the same piecewise-linear interpolation as
    config.py's dial_to_current_A()."""
    ps = cfg.power_supply
    if not ps:
        return {}
    anchors = ps["dial_to_current_A"]
    return {
        "name":     ps["name"],
        "dial_min": float(ps["dial_min"]),
        "dial_max": float(ps["dial_max"]),
        "anchors":  [[float(a["dial"]), float(a["I"])] for a in anchors],
        "degree_to_volt_ratio": float(ps["degree_to_volt_ratio"]),
    }


def model_info(cfg, lev: dict) -> list:
    """Model-information tables behind the HTML's "i" button: components grouped
    by material, material properties, distances between components, excitation
    -- each row tagged with WHERE the numbers come from.
    Values are read from params.yaml (+ this build's levitation solve), never
    retyped here -- only the provenance tags/notes are authored in this function.

    src tags: meas = measured on the rig by the team, given = professor /
    TEAM 28 problem / teacher email, ref = handbook/literature value,
    calc = computed by this model, assumed = placeholder / estimate, not verified.
    """
    raw = cfg.raw
    pl, co, ci = cfg.plate, cfg.coils, cfg.iron
    ring = raw.get("outer_iron_ring", {})
    fr = raw.get("device_frame", {})
    bc = cfg.bc
    mp = raw.get("material_props", {})
    vd = raw.get("validation_data", {})
    ps = cfg.power_supply or {}

    def f(x, d=1):
        return f"{float(x):.{d}f}"

    def span(a, b, d=1):
        return f"{f(a, d)} – {f(b, d)} mm"

    r_core = float(ci.get("r_outer_mm", 0.0))
    ri0, ri1 = float(co["inner"]["r_inner_mm"]), float(co["inner"]["r_outer_mm"])
    rr0, rr1 = float(ring.get("r_inner_mm", 0.0)), float(ring.get("r_outer_mm", 0.0))
    ro0, ro1 = float(co["outer"]["r_inner_mm"]), float(co["outer"]["r_outer_mm"])
    fr_in = ro1 + float(fr.get("air_gap_mm", 0.0))
    fr_out = fr_in + float(fr.get("wall_thickness_mm", 0.0))
    h_coil = float(co["height_mm"])
    R_disc, t_disc = float(pl["radius_mm"]), float(pl["thickness_mm"])
    gap_rest = float(pl["z_bottom_mm"]) - float(co["z_top_mm"])
    vis_gap = vd.get("levitation_visible_gap_mm")

    disc_mass = next((p.get("mass_g") for p in raw.get("plate_library", [])
                      if abs(float(p["radius_mm"]) - R_disc) < 0.5), None)
    ASM = "assumed"   # cell flag: placeholder value, shown highlighted in the table

    # Row = {"cells": [...], "src": tag, "note": hover text}; a cell is a string,
    # or [string, "assumed"] to flag that one value as an unverified placeholder.
    components = [
        {"cells": ["Aluminium", "Levitating disc", f"0 – {f(R_disc)}  (Ø{f(2*R_disc, 0)})", f(t_disc),
                   f"{disc_mass} g" if disc_mass else "—"],
         "src": "meas", "note": "Ø16 cm per teacher's email; thickness + mass measured 2026-07-01"},
        {"cells": ["Copper", "Inner coil", f"{f(ri0)} – {f(ri1)}", f(h_coil),
                   f"{co['inner']['turns']} turns"],
         "src": "meas", "note": "ruler measurement 2026-07-10; turns confirmed by IR data"},
        {"cells": ["Copper", "Outer coil", f"{f(ro0)} – {f(ro1)}", f(h_coil),
                   f"{co['outer']['turns']} turns, opposite winding sense"],
         "src": "meas", "note": "ruler measurement 2026-07-10"},
        {"cells": ["Copper", "Coil wire", "—", "—", [f"Ø{f(co['wire_diameter_mm'])} mm wire", ASM]],
         "src": "assumed", "note": "wire gauge not measured on the rig"},
        {"cells": ["Iron", "Center core", f"0 – {f(r_core)}  (Ø{f(2*r_core)})", f(h_coil), "solid"],
         "src": "meas", "note": "ruler measurement 2026-07-10; magnet test: ferromagnetic"},
        {"cells": ["Iron", "Iron ring", f"{f(rr0)} – {f(rr1)}", f(h_coil), "solid"],
         "src": "meas", "note": "ruler measurement 2026-07-10; magnet test: ferromagnetic"},
        {"cells": ["Plywood", "Frame wall", f"{f(fr_in)} – {f(fr_out)}", "—", "octagonal, display only"],
         "src": "meas", "note": "outer coil → frame: 25–30 mm air, 50 mm to the outer edge"},
    ]

    al, cu, fe = mp.get("aluminium", {}), mp.get("copper", {}), mp.get("iron", {})
    alpha = f"α = {float(pl['sigma_tempco_per_K']):.2g} 1/K"
    properties = [
        {"cells": ["Aluminium", f"{float(pl['sigma_S_per_m']):.3g}", f(pl.get("mu_r", 1), 0),
                   f(pl["k_W_per_mK"], 0), f(pl["rho_kg_per_m3"], 0), f(pl["cp_J_per_kgK"], 0), alpha],
         "src": "ref", "note": "handbook values; α: σ(T) = σ₀/(1+α(T−T₀))"},
        {"cells": ["Copper", f"{float(co['sigma_Cu_S_per_m']):.3g}", f(cu.get("mu_r", 1), 0),
                   f(cu.get("k_W_per_mK", 0), 0), f(cu.get("rho_kg_per_m3", 0), 0),
                   f(cu.get("cp_J_per_kgK", 0), 0), alpha],
         "src": "ref", "note": "handbook values"},
        {"cells": ["Iron", [f"{float(ci.get('sigma_S_per_m', 0)):.2g}", ASM], [f(ci.get("mu_r", 0), 0), ASM],
                   "—", f(fe.get("rho_kg_per_m3", 0), 0), f(fe.get("cp_J_per_kgK", 0), 0),
                   f"B_sat = {f(ci.get('B_sat_T', 1.5))} T"],
         "src": "ref", "note": "ρ, c_p, B_sat: mild steel. σ, μᵣ: placeholders — alloy / B-H curve unknown"},
    ]

    gaps = [
        {"cells": ["Center core", "Inner coil", f"{f(ri0 - r_core)} mm", "radial"],
         "src": "meas", "note": "air gap"},
        {"cells": ["Inner coil", "Iron ring", f"{f(rr0 - ri1)} mm", "radial"],
         "src": "meas", "note": "air gap"},
        {"cells": ["Iron ring", "Outer coil", f"{f(ro0 - rr1)} mm", "radial"],
         "src": "meas", "note": "air gap"},
        {"cells": ["Outer coil", "Frame wall", f"{f(fr.get('air_gap_mm', 0))} mm", "radial"],
         "src": "meas", "note": "measured 25–30 mm, midpoint used"},
        {"cells": ["Disc (resting)", "Coil top", f"{f(gap_rest)} mm", "vertical"],
         "src": "given", "note": "TEAM 28 problem (winding-form thickness)"},
        {"cells": ["Disc (levitating, 5 A)", "Coil top", f"{f(lev['z_gap_5A_mm'])} mm (model)", "vertical"],
         "src": "calc", "note": "F_lift(z) = m·g — does NOT match the rig yet (open question, μᵣ unknown)"},
    ]
    if vis_gap:
        gaps.append({"cells": ["Disc (levitating, 5 A)", "Coil top",
                               f"{f(vis_gap[0], 0)} – {f(vis_gap[1], 0)} mm (rig)", "vertical"],
                     "src": "meas", "note": "visible gap observed 2026-07-01"})
    gaps.append({"cells": ["Disc edge", "Iron ring", f"disc R {f(R_disc)} ≥ ring {f(rr1)} mm",
                           "overlap"],
                 "src": "calc", "note": "the disc covers the whole iron ring, not only the inner coil"})

    anchors = ", ".join(f"{a['dial']:.0f}° → {a['I']:.2f} A" for a in ps.get("dial_to_current_A", []))
    excitation = [
        {"cells": ["Operating current (RMS)",
                   f"{f(cfg.I, 2)} A at {f(raw['excitation'].get('voltage_V', 190), 0)} V"],
         "src": "meas", "note": "multimeter, main operating point"},
        {"cells": ["Current amplitude î = I·√2", f"{f(cfg.I_peak, 2)} A"],
         "src": "calc", "note": "used by the lift-force chain"},
        {"cells": ["Frequency", f"{f(cfg.freq, 0)} Hz"], "src": "given", "note": "mains"},
        {"cells": ["Power supply", ps.get("name", "—")], "src": "meas",
         "note": "identified from rig photo 2026-07-02"},
        {"cells": ["Variac dial → current", anchors or "—"], "src": "meas",
         "note": "dial scale is degrees, not volts"},
    ]
    for p in vd.get("op_points", []):
        if float(p["I"]) != cfg.I:
            excitation.append({"cells": ["Calibration point", f"{p['V']} V → {p['I']} A"],
                               "src": "meas", "note": "IR session 2026-06-23"})
    excitation.append({"cells": ["Ambient temperature (default)", f"{f(bc['T_ambient_degC'], 0)} °C"],
                       "src": "given", "note": "professor, June 2026"})

    # "group": first column is a material -> merged cells + colour swatch in JS.
    return [
        {"title": "Components by material", "group": True,
         "cols": ["Material", "Component", "Radius r [mm]", "Height [mm]", "Details"],
         "rows": components},
        {"title": "Material properties", "group": True,
         "cols": ["Material", "σ [S/m]", "μᵣ", "k [W/(m·K)]", "ρ [kg/m³]", "c_p [J/(kg·K)]", "Other"],
         "rows": properties},
        {"title": "Distances between components", "group": False,
         "cols": ["From", "To", "Distance", "Direction"], "rows": gaps},
        {"title": "Excitation & ambient", "group": False,
         "cols": ["Quantity", "Value"], "rows": excitation},
    ]


# ─── EM field visualization data (B field lines + eddy current density) ──────

def compute_eddy_field(em: dict):
    """Per-element eddy-current density magnitude |J_e| = ωσ|A_φ| in the PLATE
    (+ payload) region, derived from the already-computed q_e map (q=|J_e|²/2σ)
    instead of re-deriving A at centroids — q_e is zero outside the plate/payload,
    so the mask falls out for free. Returns (coords_rz (M,2) [m], Je (M,) [A/m²]).
    """
    res = em["res"]
    tris, coords, ridge = res["tris"], res["coords"], res["ridge"]
    q_e = em["q_e"]
    mask = q_e > 0
    if not mask.any():
        return np.zeros((0, 2)), np.zeros(0)
    sigma_e = ridge[mask, 2]
    Je = np.sqrt(2.0 * sigma_e * q_e[mask])
    rc = ridge[mask, 0]
    zc = coords[tris][mask][:, :, 1].mean(axis=1)
    return np.column_stack([rc, zc]), Je


def compute_em_field_lines(em: dict, cfg, n_lines: int = 20, view_margin: float = 2.5):
    """Magnetic field lines in the (r,z) meridian plane: contours of the flux
    function ψ=r·Re(A_φ). em_solver.make_mesh_em() builds a STRUCTURED (r,z)
    grid, so res['A'] reshapes directly to (nr,nz) — no unstructured-mesh
    contour walk needed, just matplotlib's contour algorithm on a regular grid.

    The EM SOLVE domain is ±500mm (far enough for accuracy — see
    validate_domain_size()), but almost all of that air is irrelevant for a B
    field VISUALIZATION: without cropping, most contour levels trace huge,
    near-invisible diffuse loops out near the domain edge instead of the
    meaningful near-device field. So the contour search itself is cropped to a
    window of ±view_margin × plate_radius around the device, and ψ_max /|B|_max
    are both taken from that cropped window too — i.e. "near-device peak", which
    is where they actually occur (close to the coils/iron).

    Levels are picked as fixed FRACTIONS of ψ_max so the resulting contour
    shapes are invariant to the current magnitude (A scales linearly with I in
    the linear regime, so ψ=const at a fixed fraction of ψ_max always traces
    the same curve) — the baked geometry stays valid for any I, only the
    displayed |B| amplitude needs runtime (I/I_em_ref) scaling.

    Returns (lines, B_max): lines is a list of dicts {r,z,amp} (lists of float,
    mm / mm / 0..1-normalized |B|); B_max [T] is the peak nodal |B| at cfg.I.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy.interpolate import RegularGridInterpolator

    res = em["res"]
    rs_full, zs_full = res["rs"], res["zs"]
    nr_full, nz_full = len(rs_full), len(zs_full)
    A_grid_full = res["A"].reshape(nr_full, nz_full)

    R_view = float(cfg.plate["radius_mm"]) * 1e-3 * view_margin
    ir = np.where(rs_full <= R_view)[0]
    iz = np.where(np.abs(zs_full) <= R_view)[0]
    rs, zs = rs_full[ir], zs_full[iz]
    nr, nz = len(rs), len(zs)
    A_grid = A_grid_full[np.ix_(ir, iz)]

    # Nodal |B| (RMS) via central differences on the structured grid. This is a
    # coarser proxy than the elementwise FEM |B| used for saturation checks —
    # fine here since it only drives the field-line colour, not a physics decision.
    dAdz = np.gradient(A_grid, zs, axis=1)
    dAdr = np.gradient(A_grid, rs, axis=0)
    B_r = -dAdz
    B_z = A_grid / np.maximum(rs[:, None], 1e-9) + dAdr
    B_mag = np.sqrt(np.abs(B_r) ** 2 + np.abs(B_z) ** 2) / math.sqrt(2.0)
    B_max = float(B_mag.max())
    B_interp = RegularGridInterpolator((rs, zs), B_mag, bounds_error=False, fill_value=0.0)

    psi = rs[:, None] * A_grid.real
    psi_max = float(np.abs(psi).max())

    lines = []
    if psi_max > 1e-30 and B_max > 1e-30:
        fracs = np.linspace(-1.0, 1.0, n_lines + 2)[1:-1]
        fracs = fracs[np.abs(fracs) > 0.02]      # skip near-zero (degenerate loop)
        levels = sorted(float(f) * psi_max for f in fracs)

        fig, ax = plt.subplots()
        cs = ax.contour(zs, rs, psi, levels=levels)
        for segs in cs.allsegs:
            for seg in segs:
                if len(seg) < 3:
                    continue
                z_arr, r_arr = seg[:, 0], seg[:, 1]
                amp = B_interp(np.column_stack([r_arr, z_arr])) / B_max
                lines.append({
                    "r": [round(float(v) * 1e3, 2) for v in r_arr],   # m -> mm
                    "z": [round(float(v) * 1e3, 2) for v in z_arr],
                    "amp": [round(float(v), 3) for v in amp],
                })
        plt.close(fig)

    return lines, B_max


# ─── STL helpers (same as build_twin_html.py) ────────────────────────────────

def parse_stl(path: str) -> np.ndarray:
    """Return (nTri, 3, 3) vertex array in millimetres (CAD Z-up coords)."""
    raw = open(path, "rb").read()
    n = struct.unpack("<I", raw[80:84])[0]
    off, tris = 84, []
    for _ in range(n):
        d = struct.unpack("<12fH", raw[off:off + 50]); off += 50
        tris.append(d[3:12])
    return np.array(tris, dtype=np.float32).reshape(-1, 3, 3) * 1000.0  # m → mm


def classify(V: np.ndarray) -> np.ndarray:
    """Classify each triangle into physics region by centroid (r, z) [mm]."""
    C = V.mean(axis=1)
    r = np.hypot(C[:, 0], C[:, 1])
    z = C[:, 2]
    z_top = z.max() - 0.18 * (z.max() - z.min())
    region = np.full(len(C), 4, dtype=np.uint8)  # default: structure
    region[(z > z_top) & (r <= 90)] = 0           # plate
    body = z <= z_top
    region[body & (r <= 26)] = 3                   # iron core
    region[body & (r > 26) & (r <= 45)] = 1        # inner coil
    region[body & (r > 45) & (r <= 62)] = 2        # outer coil
    return region


# ─── Lumped params for coils / iron (same as build_twin_html.py) ─────────────

def lumped_physics(cfg, em: dict) -> dict:
    mm = 1e-3
    co = cfg.coils
    A_wire = math.pi * (co["wire_diameter_mm"] * mm / 2) ** 2
    lt = cfg.raw["lumped_thermal"]

    def coil_R(c):
        r_mean = (c["r_inner_mm"] + c["r_outer_mm"]) / 2 * mm
        return c["turns"] * (2 * math.pi * r_mean) / (co["sigma_Cu_S_per_m"] * A_wire)

    coil_C_scale = float(lt.get("coil_C_scale", 1.0))
    G_wind = float(lt.get("coil_G_wind_W_per_K", 0.0))
    conv_exp = float(lt.get("convection_exponent", 0.25))
    coil_hot_display_C = float(lt.get("coil_hot_display_C", 80.0))

    def coil_C_solid(c):
        r_mean = (c["r_inner_mm"] + c["r_outer_mm"]) / 2 * mm
        Vc = c["turns"] * (2 * math.pi * r_mean) * A_wire
        return 8960.0 * 385.0 * Vc  # rho_Cu * cp_Cu * V_Cu, full solid-copper mass

    # WP-COOL T2 (2026-07-28, docs/archive/2026-07-28_BUG_REGISTER.md T2): the iron
    # lumped-network node's REAL heat capacity, from the iron_core:/
    # outer_iron_ring: geometry and material_props.iron (params.yaml) -- was
    # `0.5*C_plate` (half the ALUMINIUM DISC's capacity, unrelated to iron and
    # 23x too small: 73.3 J/K vs the physical 1676 J/K). Both regions honour
    # their own `enabled` flag, same as the EM solver.
    mat_fe = cfg.raw.get("material_props", {}).get("iron", {})
    rho_Fe = float(mat_fe.get("rho_kg_per_m3", 7870.0))
    cp_Fe = float(mat_fe.get("cp_J_per_kgK", 450.0))

    def iron_region_volume(region: dict) -> float:
        if not region.get("enabled", False):
            return 0.0
        r_i = float(region.get("r_inner_mm", 0.0)) * mm
        r_o = float(region["r_outer_mm"]) * mm
        h = abs(float(region["z_top_mm"]) - float(region["z_bottom_mm"])) * mm
        return math.pi * (r_o ** 2 - r_i ** 2) * h

    V_iron = (iron_region_volume(cfg.raw.get("iron_core", {})) +
              iron_region_volume(cfg.raw.get("outer_iron_ring", {})))
    C_iron = rho_Fe * cp_Fe * V_iron
    print(f"[LUMPED] C_iron={C_iron:.1f} J/K (V_iron={V_iron*1e6:.1f} cm^3, "
          f"rho={rho_Fe:.0f} cp={cp_Fe:.0f})")

    # WP-ANCHOR phase 3 (2026-10-06): power basis of the lumped coil/iron network.
    # "loss_chain" = the old behaviour, P = 1/2*I^2*R with the RMS current_A used AS
    # the amplitude (half the true power; harmless at steady state because hA was
    # calibrated with the same P, but WRONG for transients: the node capacities C are
    # physical, so dT/dt = P/C needs the physical P). "rms_true" = P = I_rms^2*R =
    # 1/2*I_peak^2*R, and the iron eddy loss scaled by the same (I_peak/I)^2.
    # Evidence: at 6.175 A the inner coil heated 0.0729 K/s while 25-50 K above
    # ambient, above the loss-chain ADIABATIC limit of 0.0725 K/s (docs/CHANGELOG.md
    # WP-ANCHOR). The em_solver loss chain and the disc ROM are NOT changed here.
    basis = str(lt.get("power_basis", "loss_chain"))
    if basis == "rms_true":
        k_P = (cfg.I_peak / cfg.I) ** 2 if cfg.I else 2.0
    elif basis == "loss_chain":
        k_P = 1.0
    else:
        raise ValueError(f"lumped_thermal.power_basis must be rms_true|loss_chain, got {basis!r}")
    P_inner = k_P * 0.5 * cfg.I ** 2 * coil_R(co["inner"])
    P_outer = k_P * 0.5 * cfg.I ** 2 * coil_R(co["outer"])
    P_iron = k_P * em["P_iron_W"]
    print(f"[LUMPED] power_basis={basis} (x{k_P:.3f}): P_inner={P_inner:.2f} "
          f"P_outer={P_outer:.2f} P_iron={P_iron:.2f} W at I_ref")
    hA_inner = float(lt["hA_inner_W_per_K"])
    hA_outer = float(lt["hA_outer_W_per_K"])
    hA_iron = float(lt["hA_iron_W_per_K"])
    G_cond = float(lt.get("G_iron_cond_W_per_K", 0.0))
    hA_far = float(lt["air_node_hA_far_W_per_K"])

    # dT_cal[node] = (T_node_surface - T_local_air) at the I_ref steady state of
    # the ORIGINAL linear model -- the anchor point where hA_eff(dT_cal)=hA_cal
    # by construction, so the nonlinear convection correction below is exact at
    # I_ref (steady state stays T_inner_ss=40.5C/T_outer_ss=38.5C, unchanged).
    # Solved once from the small inner<->iron conduction-coupled linear system
    # (outer decouples trivially: dT_cal_outer = P_outer/hA_outer).
    dT_air_cal = (P_inner + P_outer + P_iron) / hA_far
    A = np.array([[hA_inner + G_cond, -G_cond],
                  [-G_cond, hA_iron + G_cond]])
    b = np.array([P_inner + hA_inner * dT_air_cal,
                   P_iron + hA_iron * dT_air_cal])
    dT_inner_amb, dT_iron_amb = np.linalg.solve(A, b)
    dT_cal = {
        "inner": float(dT_inner_amb - dT_air_cal),
        "outer": P_outer / hA_outer,
        "iron":  float(dT_iron_amb - dT_air_cal),
    }

    return {
        "convection_exponent": conv_exp,  # Churchill-Chu-simplified natural convection h~dT^n
        "T_coil_hot_display_C": coil_hot_display_C,  # coil colour-ramp ceiling (was JS literal T_COIL_HOT)
        "nodes": {
            "inner": {
                "P_ref":  P_inner,
                # WP-COOL T1 (2026-07-28, docs/archive/2026-07-28_BUG_REGISTER.md T1):
                # split P_ref across the surface/deep nodes in the SAME ratio
                # as their heat capacity (coil_C_scale), instead of dumping
                # 100% of P_ref onto the surface node while the deep node (77.6%
                # of the copper mass) got none -- that made both heat-up AND
                # cooldown ~4.5x too fast. Steady state is unchanged (proof in
                # the bug register): P_surf+P_deep == P_ref still.
                "P_ref_surf": P_inner * coil_C_scale,
                "P_ref_deep": P_inner * (1 - coil_C_scale),
                "C":      coil_C_solid(co["inner"]) * coil_C_scale,       # surface (IR-visible) mass
                "C_deep": coil_C_solid(co["inner"]) * (1 - coil_C_scale),  # winding-core mass
                "G_wind": G_wind,   # surface<->winding-core conductance (fit 2026-07-02)
                "hA":     hA_inner,
                "dT_cal": dT_cal["inner"],
            },
            "outer": {
                "P_ref":  P_outer,
                "P_ref_surf": P_outer * coil_C_scale,   # WP-COOL T1, see "inner" above
                "P_ref_deep": P_outer * (1 - coil_C_scale),
                "C":      coil_C_solid(co["outer"]) * coil_C_scale,
                "C_deep": coil_C_solid(co["outer"]) * (1 - coil_C_scale),
                "G_wind": G_wind,
                "hA":     hA_outer,
                "dT_cal": dT_cal["outer"],
            },
            "iron": {
                "P_ref":  P_iron,
                "C":      C_iron,
                "hA":     hA_iron,
                "dT_cal": dT_cal["iron"],
                # contact conduction from the inner coil (fit 2026-07-02, params.yaml)
                "G_cond": G_cond,
            },
        },
        "air_node": {
            "C":      float(lt["air_node_C_J_per_K"]),
            "hA_far": hA_far,
        },
    }


# ─── Procedural solid stepped disc (the real levitating object) ───────────────

def revolve(meridian, n_theta: int) -> np.ndarray:
    """Revolve a meridian polyline [(r,z), ...] (mm) into a closed solid of
    revolution. Returns (nTri, 3, 3) triangles. Degenerate tris at the axis
    (r=0) collapse to zero area and render nothing — harmless."""
    th = np.linspace(0, 2 * np.pi, n_theta, endpoint=False)
    ct, st = np.cos(th), np.sin(th)
    tris = []
    for k in range(len(meridian) - 1):
        r0, z0 = meridian[k]
        r1, z1 = meridian[k + 1]
        for j in range(n_theta):
            jn = (j + 1) % n_theta
            A = (r0 * ct[j],  r0 * st[j],  z0)
            B = (r0 * ct[jn], r0 * st[jn], z0)
            C = (r1 * ct[j],  r1 * st[j],  z1)
            D = (r1 * ct[jn], r1 * st[jn], z1)
            tris.append([A, C, D])
            tris.append([A, D, B])
    return np.array(tris, dtype=np.float32)


def revolve_ring(r_in_mm: float, r_out_mm: float, z_bot_mm: float, z_top_mm: float,
                 n_theta: int) -> np.ndarray:
    """Solid annular ring (toroid cross-section = rectangle) via revolve()."""
    mer = [(r_in_mm, z_bot_mm), (r_out_mm, z_bot_mm),
           (r_out_mm, z_top_mm), (r_in_mm, z_top_mm), (r_in_mm, z_bot_mm)]
    return revolve(mer, n_theta)


def build_octagonal_base(r_outer_mm: float, z_bot_mm: float, z_top_mm: float,
                          n_sides: int = 8) -> np.ndarray:
    """Solid n-sided polygonal disc (flat floor plate from center to r_outer)."""
    angles = np.linspace(0, 2 * np.pi, n_sides, endpoint=False)
    ox = r_outer_mm * np.cos(angles)
    oy = r_outer_mm * np.sin(angles)
    tris = []
    for i in range(n_sides):
        j = (i + 1) % n_sides
        tris.append([(0.0, 0.0, z_top_mm), (ox[i], oy[i], z_top_mm), (ox[j], oy[j], z_top_mm)])
        tris.append([(0.0, 0.0, z_bot_mm), (ox[j], oy[j], z_bot_mm), (ox[i], oy[i], z_bot_mm)])
        tris.append([(ox[i], oy[i], z_bot_mm), (ox[j], oy[j], z_bot_mm), (ox[i], oy[i], z_top_mm)])
        tris.append([(ox[j], oy[j], z_bot_mm), (ox[j], oy[j], z_top_mm), (ox[i], oy[i], z_top_mm)])
    return np.array(tris, dtype=np.float32)


def build_octagonal_frame(r_inner_mm: float, r_outer_mm: float,
                           z_bot_mm: float, z_top_mm: float,
                           n_sides: int = 8) -> np.ndarray:
    """Hollow n-sided polygonal prism: outer walls + inner walls + top/bottom ring caps.
    Used for the plywood octagonal device housing that wraps around the coil assembly."""
    angles = np.linspace(0, 2 * np.pi, n_sides, endpoint=False)
    ox = r_outer_mm * np.cos(angles); oy = r_outer_mm * np.sin(angles)
    ix = r_inner_mm * np.cos(angles); iy = r_inner_mm * np.sin(angles)
    tris = []
    for i in range(n_sides):
        j = (i + 1) % n_sides
        # Outer side wall panel
        tris += [
            [(ox[i], oy[i], z_bot_mm), (ox[j], oy[j], z_bot_mm), (ox[i], oy[i], z_top_mm)],
            [(ox[j], oy[j], z_bot_mm), (ox[j], oy[j], z_top_mm), (ox[i], oy[i], z_top_mm)],
        ]
        # Inner side wall panel (normal flipped — facing inward)
        tris += [
            [(ix[i], iy[i], z_bot_mm), (ix[i], iy[i], z_top_mm), (ix[j], iy[j], z_bot_mm)],
            [(ix[j], iy[j], z_bot_mm), (ix[i], iy[i], z_top_mm), (ix[j], iy[j], z_top_mm)],
        ]
        # Top annular cap
        tris += [
            [(ix[i], iy[i], z_top_mm), (ox[i], oy[i], z_top_mm), (ix[j], iy[j], z_top_mm)],
            [(ox[i], oy[i], z_top_mm), (ox[j], oy[j], z_top_mm), (ix[j], iy[j], z_top_mm)],
        ]
        # Bottom annular cap (normal flipped)
        tris += [
            [(ix[i], iy[i], z_bot_mm), (ix[j], iy[j], z_bot_mm), (ox[i], oy[i], z_bot_mm)],
            [(ox[i], oy[i], z_bot_mm), (ix[j], iy[j], z_bot_mm), (ox[j], oy[j], z_bot_mm)],
        ]
    return np.array(tris, dtype=np.float32)


def build_separator_rings(cfg, z_bot_mm: float, z_top_mm: float, n_theta: int) -> np.ndarray:
    """Procedurally generate the two separator-ring gaps (region 5) as vertical sleeves
    spanning [z_bot_mm, z_top_mm] (full device height from params.yaml coil z-range).
    They render as solid rings standing among the windings, visually closing the gaps
    between core/inner coil and inner/outer coil. The real STL has NO surface at these
    exact radii (a genuine geometric gap -- see docs/archive/2026-06-23_3D_MODEL_UPDATE_PLAN.md), so they can't
    be produced by recolouring existing triangles like the other regions; they're
    synthesized the same way the levitating disc is. Radii come from params.yaml, not
    hardcoded. These rings receive thermal coloring (tnIron) at runtime, showing heat
    conduction from the active coils (~39-45°C passive heating)."""
    iron, inner, outer = cfg.iron, cfg.coils["inner"], cfg.coils["outer"]
    gaps = [
        (float(iron["r_outer_mm"]), float(inner["r_inner_mm"])),   # inner gap
        (float(inner["r_outer_mm"]), float(outer["r_inner_mm"])),  # outer gap
    ]
    tris = []
    for r_in, r_out in gaps:
        if r_out <= r_in:
            continue
        mer = [(r_in, z_bot_mm), (r_out, z_bot_mm), (r_out, z_top_mm),
               (r_in, z_top_mm), (r_in, z_bot_mm)]
        tris.append(revolve(mer, n_theta))
    return np.concatenate(tris, axis=0) if tris else np.zeros((0, 3, 3), dtype=np.float32)


def build_solid_core(r_core_mm: float, z_bot_mm: float, z_top_mm: float, n_theta: int) -> np.ndarray:
    """Procedurally generate a complete solid cylinder (r=0..r_core_mm, z=z_bot_mm..z_top_mm).
    The STL only contains the hollow outer surface of the device; a solid procedural fill
    makes the center core render as a closed metallic block with full height, eliminating
    the "hollow interior" appearance. The z-range spans the full device height from params.yaml
    (typically z=-52..0mm for the coil assembly), making the core read as a substantial
    conductor block. At runtime, it receives thermal coloring (tnIron) showing passive
    heat conduction from adjacent coils."""
    mer = [(0.0, z_bot_mm), (r_core_mm, z_bot_mm), (r_core_mm, z_top_mm),
           (0.0, z_top_mm), (0.0, z_bot_mm)]
    return revolve(mer, n_theta)


def build_disc_mesh(cfg, rom, z_bottom_mm: float, je_field=None):
    """Generate ONE flat solid disc matching the physical plate radius and map the
    FEM ΔT_ref field onto every vertex. Physics unchanged (FEM solved on Ø160×3mm);
    display thickness is exaggerated so the 3mm disc reads clearly in 3D.

    Returns (V, dT_eddy, dT_air, Je): two per-vertex ΔT fields sharing the FEM
    radial shape, plus the per-vertex eddy-current density magnitude (or None if
    je_field wasn't given). dT_eddy is uniform through the thickness (eddy
    currents heat the whole slab); dT_air is weighted toward the BOTTOM face
    (hot air rises off the coils), via g(f)=1+grad·(0.5−f). The thickness mean
    of g is 1, so the combined steady field equals the original FEM field —
    only its top/bottom split is new."""
    disc    = cfg.raw["levitating_disc"]
    n_theta = int(disc.get("n_theta", 96))
    zex     = float(disc.get("display_z_exaggeration", 1.0))
    grad    = float(disc.get("bottom_heating_gradient", 0.0))

    plate_r = float(cfg.plate["radius_mm"])   # e.g. 80mm — single disc, one radius
    t_phys  = float(cfg.plate["thickness_mm"])  # 3mm (physics)
    z_vis   = t_phys * zex                    # display height (mm)

    # Meridian for a plain solid cylinder: bottom-centre→bottom-rim→top-rim→top-centre
    mer = [
        (0.0,     0.0),
        (plate_r, 0.0),
        (plate_r, z_vis),
        (0.0,     z_vis),
    ]

    V = revolve(mer, n_theta)           # (nTri,3,3) local, z 0..z_vis
    V[:, :, 2] += z_bottom_mm          # translate to plate position

    # Map FEM ΔT_ref(r,z) → disc vertices.  FEM domain: r 0..R, z 0..t_phys(=3mm).
    coords = rom.res_ref["coords"]      # (N,2) metres [r, z]
    dT_fem = rom.dT_ref
    lin = LinearNDInterpolator(coords, dT_fem, fill_value=np.nan)
    nn  = NearestNDInterpolator(coords, dT_fem)

    verts    = V.reshape(-1, 3)
    r_mm     = np.hypot(verts[:, 0], verts[:, 1])
    f        = (verts[:, 2] - z_bottom_mm) / max(z_vis, 1e-9)  # 0(bot)→1(top)
    r_m      = np.clip(r_mm * 1e-3, 0.0, coords[:, 0].max())
    z_phys_m = np.clip(f * t_phys * 1e-3, coords[:, 1].min(), coords[:, 1].max())
    pts = np.column_stack([r_m, z_phys_m])
    dT  = lin(pts)
    m   = np.isnan(dT)
    if m.any():
        dT[m] = nn(pts[m])

    # Split into eddy (through-thickness uniform) and hot-air (bottom-weighted).
    # f = 0 at the bottom face → g = 1 + grad/2 (hottest); f = 1 at the top → 1 − grad/2.
    g       = 1.0 + grad * (0.5 - f)
    dT_eddy = dT
    dT_air  = dT * g

    # Eddy-current density |J_e|: interpolated from the EM mesh, which uses the
    # ABSOLUTE z frame (cfg.plate z_bottom_mm..+thickness_mm) — unlike the thermal
    # mesh above (LOCAL z 0..t_phys) — so reuse verts[:,2] (already absolute mm,
    # V was translated by +z_bottom_mm) directly instead of the f/z_phys_m pair.
    Je_disc = None
    if je_field is not None:
        je_coords, je_vals = je_field
        if len(je_vals) > 0:
            z_abs_m = np.clip(verts[:, 2] * 1e-3, je_coords[:, 1].min(), je_coords[:, 1].max())
            r_je_m  = np.clip(r_mm * 1e-3, je_coords[:, 0].min(), je_coords[:, 0].max())
            pts_je  = np.column_stack([r_je_m, z_abs_m])
            lin_j = LinearNDInterpolator(je_coords, je_vals, fill_value=np.nan)
            nn_j  = NearestNDInterpolator(je_coords, je_vals)
            Jd  = lin_j(pts_je)
            mj  = np.isnan(Jd)
            if mj.any():
                Jd[mj] = nn_j(pts_je[mj])
            Je_disc = Jd.astype(np.float32)

    return (V.astype(np.float32),
            dT_eddy.astype(np.float32),
            dT_air.astype(np.float32),
            Je_disc)


# ─── Disc cooldown-vs-heatup τ ratio (WP-COOL T3) ─────────────────────────────

def disc_tau_cool_natural_frac(cfg) -> float:
    """WP-COOL T3 (2026-07-28, docs/archive/2026-07-28_BUG_REGISTER.md T3): the disc's
    ROM τ was derived from a FEM whose bottom BC is h_bottom_W_per_m2K=25
    ("enhanced convection facing coils" -- the coil plume). That enhancement
    fades with the coils' own current, so cooldown is physically slower than
    heat-up. Returns f_nat = UA_natural-everywhere / UA_as-built(plume-on) =
    tau_heat/tau_cool -- i.e. the ratio TwinState._rom_step's tau_eff uses to
    stretch τ as coilAirDrive() (the plume proxy) falls to 0. Computed from
    the ACTUAL params.yaml BCs + disc geometry (not pasted as a constant) so
    it stays correct if either changes."""
    bc = cfg.bc
    h_top = float(bc["h_convection_W_per_m2K"])
    h_bot = float(bc["h_bottom_W_per_m2K"])
    R = cfg.geometry.plate_radius_m
    t = cfg.geometry.plate_thickness_m
    A_face = math.pi * R ** 2       # top == bottom face area
    A_edge = 2.0 * math.pi * R * t
    UA_heat = h_top * A_face + h_bot * A_face + h_top * A_edge   # as-built (plume on)
    UA_cool = h_top * A_face + h_top * A_face + h_top * A_edge   # natural everywhere
    return UA_cool / UA_heat


# ─── Disc heat-source decomposition (eddy vs hot-air fraction) ────────────────

def compute_eddy_fraction(cfg, em: dict, rom) -> float:
    """Fraction of the disc's steady ΔT_mean that comes from its OWN eddy currents
    (vs. convective heating by the hot coil air). Re-solve the SAME steady FEM at
    I_ref but with the coil→air coupling switched off (Tinf_bot = T_amb): that
    isolates the eddy-driven field. The heat equation is linear, so
    f_eddy = ΔT_mean(eddy only) / ΔT_mean(full)."""
    from thermal_solver import solve_steady

    # em scaled to I_ref (mirror ThermalROM.build's internal scaling): keep the
    # original dict (incl. the "res" q_e spatial map) and override the P_* scalars.
    I_ref, I_cur = float(cfg.I_ref), float(cfg.I)
    scale = (I_ref / I_cur) ** 2
    em_ref = dict(em)
    for k in ("P_plate_W", "P_payload_W", "P_iron_W", "P_coil_W", "P_total_W"):
        if k in em:
            em_ref[k] = em[k] * scale

    cfg_eddy = copy.deepcopy(cfg)
    cfg_eddy.raw["excitation"]["current_A"] = I_ref
    cfg_eddy.raw["thermal_bc"]["k_coil_coupling_K_per_W"] = 0.0   # no hot-air BC

    res_eddy = solve_steady(cfg_eddy, em_losses=em_ref)
    dT_eddy_mean = float((res_eddy["T"] - rom.T_amb).mean())
    f_eddy = dT_eddy_mean / rom.dT_mean_ref
    return float(min(max(f_eddy, 0.0), 1.0))


# ─── Disc-radius compare mode (2026-07-03) ────────────────────────────────────
# User-requested feature: let the live twin swap between several disc radii
# WHILE the simulation runs, instead of only via separate `--plate-radius`
# builds (WP-C/D). All candidate radii are aluminium, 3mm thick (same material/
# thickness as the default disc — no material switching), so no other cfg
# override is needed besides the radius + derived geometry.
def plate_variant_radii_mm(cfg) -> list[float]:
    """SSOT for the disc-radius compare-mode button list (WP-HTML fix, was a
    hardcoded tuple that silently drifted from params.yaml's plate_library).
    Derives the candidate radii directly from plate_library: any entry whose
    material is aluminium and thickness is 3mm is a valid live swap target
    (same material/thickness as every other variant -- no other cfg override
    needed). Deduped, sorted ascending."""
    radii = set()
    for entry in cfg.raw.get("plate_library", []):
        if entry.get("material") != "aluminium":
            continue
        if abs(float(entry.get("thickness_mm", 0.0)) - 3.0) > 1e-6:
            continue
        radii.add(float(entry["radius_mm"]))
    return sorted(radii)


def solve_plate_variant(base_cfg, radius_mm: float, z_disc_bot_mm: float) -> dict:
    """Solve EM + ROM + disc mesh FROM SCRATCH for one plate radius (mirrors the
    --plate-radius override in build(), factored out so it can run in a loop for
    the disc-radius compare mode). Returns everything a JS-side plate swap needs:
    the FEM-mapped mesh arrays + this radius's own ROM/lev constants."""
    cfg_v = copy.deepcopy(base_cfg)
    cfg_v.raw["plate_material"]["radius_mm"] = float(radius_mm)
    cfg_v.geometry = Geometry(
        plate_radius_m=float(radius_mm) * 1e-3,
        plate_thickness_m=cfg_v.geometry.plate_thickness_m,
        plate_z_bottom_m=cfg_v.geometry.plate_z_bottom_m,
    )
    em_v = compute_losses(cfg_v)
    je_field_v = compute_eddy_field(em_v)
    rom_v = ThermalROM().build(cfg_v, em_losses=em_v, verbose=False)
    f_eddy_v = compute_eddy_fraction(cfg_v, em_v, rom_v)
    V_v, dTe_v, dTa_v, Je_v = build_disc_mesh(cfg_v, rom_v, z_disc_bot_mm, je_field=je_field_v)

    # WP-HTML (2026-07-10): this variant's OWN saturation-check + field-viz peaks
    # -- these 6 keys were previously MISSING from rom_params_v, so switching disc
    # variants in the JS (Object.assign(ROM, v.rom)) left them frozen at whatever
    # the main/active build's disc showed (mixing physics from two different
    # discs). Mirrors the main build's computation at the bottom of build() below.
    from em_solver import check_saturation
    # WP-PEAK: B_max_iron is compared against B_sat_T (a real material
    # property) -- report the TRUE physical B (I_peak-scaled), not em_v["res"]'s
    # own loss-chain convention. See check_saturation()'s B_scale docstring.
    B_max_iron_v, _ = check_saturation(em_v["res"], cfg_v, B_scale=cfg_v.I_peak / cfg_v.I)
    B_sat_v = float(cfg_v.iron.get("B_sat_T", 1.5))
    # Keep (not discard) this variant's own field-line contours -- a wider/
    # narrower disc genuinely reshapes the eddy/flux distribution (that's the
    # whole point of solving from scratch instead of scaling), so the B-field
    # visualization must swap per-variant too, not just the ROM scalars.
    field_lines_v, B_max_v = compute_em_field_lines(em_v, cfg_v)
    J_max_v = float(Je_v.max()) if Je_v is not None else 0.0

    k_coil_v = float(cfg_v.bc.get("k_coil_coupling_K_per_W", 0.0))
    rom_params_v = {
        "T_amb":       float(rom_v.T_amb),
        "tau":         float(rom_v.tau),
        "I_ref":       float(rom_v.I_ref),
        "dT_mean_ref": float(rom_v.dT_mean_ref),
        "dT_max_ref":  float(rom_v.dT_ref.max()),
        "UA":          float(rom_v.UA),
        "alpha":       float(rom_v.alpha),
        "P_ref":       float(rom_v.P_ref),
        "k_coil":      k_coil_v,
        "Tinf_bot_ref": float(cfg_v.bc["T_ambient_degC"]) + k_coil_v * em_v["P_coil_W"],
        "f_eddy":      round(f_eddy_v, 4),
        "f_air":       round(1.0 - f_eddy_v, 4),
        "tau_cool_natural_frac": round(disc_tau_cool_natural_frac(cfg_v), 4),  # WP-COOL T3
        "B_max_iron":  round(B_max_iron_v, 3),
        "B_sat":       B_sat_v,
        "saturated":   bool(B_max_iron_v > B_sat_v),
        "I_em_ref":    float(cfg_v.I),
        "B_max":       round(B_max_v, 4),
        "J_max":       round(J_max_v, 1),
    }
    return {
        "V": V_v, "dTe": dTe_v, "dTa": dTa_v, "Je": Je_v,
        "rom": rom_params_v, "lev": lev_params(cfg_v),
        "P_plate_W": float(em_v["P_plate_W"]),
        "field_lines": field_lines_v,
    }


# ─── Main build function ──────────────────────────────────────────────────────

def build(stl_path: str | None, out_path: str, plate_radius_mm: float | None = None,
          bake_key: bool = False) -> None:
    # Stage timing, printed as a table at the end and saved next to the HTML
    # (build_timing.json) so RUN.py can show it even when it skips the build.
    t_start = t_lap = time.perf_counter()
    timing = []

    def lap(label):
        nonlocal t_lap
        now = time.perf_counter()
        timing.append([label, now - t_lap])
        t_lap = now

    cfg = load_config()

    # WP-C (2026-07-02): optional plate-radius override, e.g. the Ø202mm disc
    # that covers out to the separator ring's outer edge (r=101mm). Does NOT
    # touch the params.yaml default (80mm, the real validated disc) -- only
    # this in-memory cfg. EM/ROM below re-solve FROM SCRATCH at the new radius
    # (never scaled from the R=80 result): a wider plate overlaps the
    # outer_iron_ring / outer-coil field region, so the eddy distribution and
    # P_plate genuinely differ, not just by area ratio.
    if plate_radius_mm is not None:
        cfg.raw["plate_material"]["radius_mm"] = float(plate_radius_mm)
        cfg.geometry = Geometry(
            plate_radius_m=float(plate_radius_mm) * 1e-3,
            plate_thickness_m=cfg.geometry.plate_thickness_m,
            plate_z_bottom_m=cfg.geometry.plate_z_bottom_m,
        )

    # 1. EM + ROM (same pipeline as digital_twin.py __main__)
    print(f"[EM]  Solving at î={cfg.I}A ...", end=" ", flush=True)
    lap("load params.yaml")
    em = compute_losses(cfg)
    print(f"P_plate={em['P_plate_W']*1e3:.1f} mW  "
          f"P_coil={em['P_coil_W']:.1f} W  P_iron={em['P_iron_W']*1e3:.0f} mW")

    # 1a. EM field visualization data (optional "B Field" / "Eddy J" layers) —
    #     baked once at cfg.I; runtime scales by (I_display/I_em_ref) since both
    #     |B| and |J_e| are linear in A_φ, hence linear in I (q~I² is |J_e|², not J_e).
    print("[EMVIZ] Field lines + eddy density map ...", end=" ", flush=True)
    je_field = compute_eddy_field(em)
    lap("EM FEM solve (phasor, active disc)")
    field_lines, B_max = compute_em_field_lines(em, cfg)
    print(f"{len(field_lines)} field lines, B_max={B_max:.3f} T")
    lap("EM field lines + eddy map")

    print("[ROM] Building FEM model ...", end=" ", flush=True)
    rom = ThermalROM().build(cfg, em_losses=em, verbose=False)
    print(f"done.  τ={rom.tau/60:.2f} min  "
          f"ΔT_max={rom.dT_ref.max():.3f} K  ΔT_mean={rom.dT_mean_ref:.3f} K")

    # 1b. Split the disc's steady rise into its two physical sources so the twin
    #     can give each its own time response (see the JS romStep):
    #       (a) eddy Joule heating IN the disc  → instantaneous with I²
    #       (b) hot air from the coils below     → gated by the copper's thermal
    #           inertia (coils take ~25 min to warm the gap air).
    #     dT_ref(full) = dT_eddy + dT_air  (heat eqn is linear in the source AND in
    #     the bottom-air ambient), so one extra eddy-only solve gives the fraction.
    f_eddy = compute_eddy_fraction(cfg, em, rom)
    f_air  = 1.0 - f_eddy
    print(f"[SPLIT] disc heat sources: eddy {f_eddy*100:.0f}% (instant)  "
          f"hot-air {f_air*100:.0f}% (coil-inertia gated)")
    lap("thermal FEM + ROM + heat split")

    # 2. Build device body 100% procedurally from params.yaml — STL is NOT used for
    #    body geometry. The STL had two fundamental problems: (1) coil radii mismatched
    #    the classify() boundaries, leaving inner coil as just 260 tris at z=-2mm;
    #    (2) the hollow STL shell created visible empty interiors. All parts below are
    #    synthesized as closed solid toroids and polygonal frames directly from physics params.
    n_theta  = int(cfg.raw["levitating_disc"].get("n_theta", 96))
    coil_h   = float(cfg.coils.get("height_mm", 52.0))

    # Coordinate system (Z-up, mm), natural device orientation:
    #   z = 0         → bottom of wooden base plate (floor under device)
    #   z = z_base    → bottom of coil assembly (top of base plate)
    #   z = z_coil_top → top of coil assembly (flush with wood frame top)
    #   z = z_disc_bot → levitating disc bottom (gap above coil top)
    z_base      = 8.0                 # wooden base plate thickness [mm]
    z_coil_bot  = z_base              # coil assembly starts at 8 mm
    z_coil_top  = z_base + coil_h    # 8 + 52 = 60 mm

    # Disc: sits directly on the coil top in the baked geometry — the levitation
    # gap is added at RUNTIME (JS lev.z * Z_GAP_EXAG), not baked into the mesh.
    z_disc_bot = z_coil_top

    # Radii from params.yaml
    r_core  = float(cfg.iron.get("r_outer_mm", 25.0))          # center core outer = 25 mm
    r_i_in  = float(cfg.coils["inner"]["r_inner_mm"])           # 28 mm
    r_i_out = float(cfg.coils["inner"]["r_outer_mm"])           # 78 mm
    r_o_in  = float(cfg.coils["outer"]["r_inner_mm"])           # 104 mm
    r_o_out = float(cfg.coils["outer"]["r_outer_mm"])           # 124 mm

    # Outer plywood frame dimensions — the real outer coil stands FREE with ~50mm
    # of air before the octagonal frame walls (user-verified vs docs/real_model.png)
    frm = cfg.raw.get("device_frame", {})
    r_frame_in  = r_o_out + float(frm.get("air_gap_mm", 50.0))            # 124+50 = 174 mm
    r_frame_out = r_frame_in + float(frm.get("wall_thickness_mm", 20.0))  # 194 mm

    print("[BODY] Building procedural device geometry from params.yaml:")

    # Center core: solid cylinder r=0..25mm (material under review: magnet test 2026-07-01
    # said non-ferromagnetic, user visual says ferro — EM keeps mu_r=1 pending re-test)
    V_core = build_solid_core(r_core, z_coil_bot, z_coil_top, n_theta)
    print(f"   center core  : {len(V_core):5d} tris  r=0..{r_core:.0f}mm  z={z_coil_bot:.0f}..{z_coil_top:.0f}mm")

    # r=25..28mm is a REAL ~3mm air gap between core and inner coil — left empty
    # (user-verified vs docs/real_model.png; both walls are closed solids either side)

    # Inner coil: full solid toroid r=28..78mm, 1000 turns, dark varnished copper
    V_inner = revolve_ring(r_i_in, r_i_out, z_coil_bot, z_coil_top, n_theta)
    print(f"   inner coil   : {len(V_inner):5d} tris  r={r_i_in:.0f}..{r_i_out:.0f}mm (1000T solid toroid)")

    # Separator ring: ONLY the real ring r=81..101mm (outer_iron_ring in params.yaml).
    # The air gaps 78..81 and 101..104mm are REAL voids on the device — left empty.
    oir = cfg.raw["outer_iron_ring"]
    r_ring_in, r_ring_out = float(oir["r_inner_mm"]), float(oir["r_outer_mm"])
    V_sep = revolve_ring(r_ring_in, r_ring_out, z_coil_bot, z_coil_top, n_theta)
    print(f"   separator    : {len(V_sep):5d} tris  r={r_ring_in:.0f}..{r_ring_out:.0f}mm (iron ring; air gaps either side)")

    # Outer coil: full solid toroid r=104..124mm, 500 turns, dark varnished copper
    V_outer = revolve_ring(r_o_in, r_o_out, z_coil_bot, z_coil_top, n_theta)
    print(f"   outer coil   : {len(V_outer):5d} tris  r={r_o_in:.0f}..{r_o_out:.0f}mm (500T solid toroid)")

    # Wooden octagonal base (8-sided plywood housing):
    #   (a) floor plate: solid octagon r=0..r_frame_out, thickness z=0..z_base
    #   (b) outer walls: hollow octagonal ring r=r_frame_in..r_frame_out, full device height
    V_floor = build_octagonal_base(r_frame_out, 0.0, z_base, n_sides=8)
    V_walls = build_octagonal_frame(r_frame_in, r_frame_out, 0.0, z_coil_top, n_sides=8)
    V_wood  = np.concatenate([V_floor, V_walls], axis=0)
    print(f"   wood frame   : {len(V_wood):5d} tris  8-sided octagon r={r_frame_in:.0f}..{r_frame_out:.0f}mm")

    # Assemble all non-disc parts (air gaps 25-28 / 78-81 / 101-104 / 124-174mm stay empty)
    V_base   = np.concatenate([V_core, V_inner, V_sep, V_outer, V_wood], axis=0)
    reg_base = np.concatenate([
        np.full(len(V_core),    3, dtype=np.uint8),  # center core
        np.full(len(V_inner),   1, dtype=np.uint8),  # inner coil 1000T
        np.full(len(V_sep),     5, dtype=np.uint8),  # separator / iron ring
        np.full(len(V_outer),   2, dtype=np.uint8),  # outer coil 500T
        np.full(len(V_wood),    4, dtype=np.uint8),  # octagonal wood frame
    ])
    print(f"   TOTAL body   : {len(V_base):5d} tris  z=0..{z_coil_top:.0f}mm  disc at z={z_disc_bot:.1f}mm")

    lap("3D device geometry")
    # 3. Procedural solid stepped disc + FEM ΔT_ref mapped onto its vertices
    print("[DISC] Building solid stepped disc + FEM field ...", end=" ", flush=True)
    V_disc, dTe_disc, dTa_disc, Je_disc = build_disc_mesh(cfg, rom, z_disc_bot, je_field=je_field)
    nTri_disc = len(V_disc)
    J_max = float(Je_disc.max()) if Je_disc is not None else 0.0
    Jn_disc = (Je_disc / J_max if J_max > 0 else np.zeros_like(Je_disc)) if Je_disc is not None \
        else np.zeros(len(V_disc) * 3, dtype=np.float32)
    print(f"{nTri_disc} tris, z_bot={z_disc_bot:.1f}mm  "
          f"dT_eddy {dTe_disc.min():.3f}..{dTe_disc.max():.3f} K  "
          f"dT_air {dTa_disc.min():.3f}..{dTa_disc.max():.3f} K  "
          f"J_max={J_max*1e-6:.3f} A/mm²")

    # 4. Splice base + disc into single per-triangle / per-vertex arrays.
    #    Disc tris are region 0 (plate); base verts carry dT=0 (lumped in JS).
    #    Two fields: eddy (uniform, β_eddy) and hot-air (bottom-weighted, β_air).
    V        = np.concatenate([V_base, V_disc], axis=0)
    region   = np.concatenate([reg_base, np.zeros(nTri_disc, dtype=np.uint8)])
    zero_base = np.zeros(len(V_base) * 3, dtype=np.float32)
    dTe_vtx  = np.concatenate([zero_base, dTe_disc]).astype(np.float32)
    dTa_vtx  = np.concatenate([zero_base, dTa_disc]).astype(np.float32)
    Jn_vtx   = np.concatenate([zero_base, Jn_disc]).astype(np.float32)
    nTri = len(V)

    # 4. Collect all physics data for JS
    from em_solver import check_saturation
    # WP-PEAK: B_max_iron is compared against B_sat_T (a real material
    # property) -- report the TRUE physical B (I_peak-scaled), not em["res"]'s
    # own loss-chain convention. See check_saturation()'s B_scale docstring.
    B_max_iron, _ = check_saturation(em["res"], cfg, B_scale=cfg.I_peak / cfg.I)
    B_sat = float(cfg.iron.get("B_sat_T", 1.5))
    k_coil = float(cfg.bc.get("k_coil_coupling_K_per_W", 0.0))
    Tinf_bot = float(cfg.bc["T_ambient_degC"]) + k_coil * em["P_coil_W"]

    rom_params = {
        "T_amb":       float(rom.T_amb),
        "tau":         float(rom.tau),
        "I_ref":       float(rom.I_ref),
        "dT_mean_ref": float(rom.dT_mean_ref),
        "dT_max_ref":  float(rom.dT_ref.max()),
        "UA":          float(rom.UA),
        "alpha":       float(rom.alpha),
        "P_ref":       float(rom.P_ref),
        "k_coil":      k_coil,
        "Tinf_bot_ref": Tinf_bot,
        "f_eddy":      round(f_eddy, 4),   # disc heat from its own eddy currents
        "f_air":       round(f_air, 4),    # disc heat from the hot coil air (lagged)
        "tau_cool_natural_frac": round(disc_tau_cool_natural_frac(cfg), 4),  # WP-COOL T3
        "B_max_iron":  round(B_max_iron, 3),
        "B_sat":       B_sat,
        "saturated":   bool(B_max_iron > B_sat),
        "I_em_ref":    float(cfg.I),     # current at which the EM viz (B/J_e) was baked
        "B_max":       round(B_max, 4),  # peak nodal |B| [T] at I_em_ref
        "J_max":       round(J_max, 1),  # peak disc |J_e| [A/m²] at I_em_ref
    }
    lumped = lumped_physics(cfg, em)
    lap("disc mesh + saturation + lumped network")
    lev = lev_params(cfg)
    lap("levitation z_eq root-find (active disc)")
    psup = power_supply_params(cfg)
    params = {"rom": rom_params, "lumped": lumped, "field_lines": field_lines, "lev": lev,
              "power_supply": psup,
              # 2026-10-02: model-information table behind the header's "i" button
              # (display only -- nothing in the physics reads it).
              "model_info": model_info(cfg, lev),
              # 2026-09-29: front-end tag. build_ar_twin.py reads this PARAMS block
              # from the baked HTML and re-tags it "AR" for outputs/ar_twin.html.
              "display_channel": "HTML",
              # 2026-09-29 (display only): FIELD_LINES are in the EM solve's (r,z) frame
              # (coil top at coils.z_top_mm, disc bottom at plate_material.z_bottom_mm);
              # the display mesh puts the coil top at z_coil_top with the disc resting on
              # it. These four numbers let the JS map one frame onto the other and let the
              # gap part of each line stretch with the live levitation lift.
              "field_view": {
                  "coil_top_em_mm":   float(cfg.coils.get("z_top_mm", 0.0)),
                  "coil_top_disp_mm": float(z_coil_top),
                  "gap_em_mm": float(cfg.plate["z_bottom_mm"]) - float(cfg.coils.get("z_top_mm", 0.0)),
                  "t_em_mm":   float(cfg.plate["thickness_mm"]),
                  "t_disp_mm": float(cfg.plate["thickness_mm"])
                               * float(cfg.raw["levitating_disc"].get("display_z_exaggeration", 1.0)),
              },
              # 2026-09-27: T_amb selector presets + Sensor-mode conditioning.
              "ambient_presets": ambient_presets(cfg),
              "live_sensor": live_sensor_params(cfg),
              # WP-HTML (2026-07-10): bake turn counts + the disc heat-ramp ceiling
              # from params.yaml instead of hardcoding them as JS/HTML literals.
              "coils_inner_turns": int(cfg.coils["inner"]["turns"]),
              "coils_outer_turns": int(cfg.coils["outer"]["turns"]),
              "plate_hot_display_C": float(cfg.raw["levitating_disc"].get("plate_hot_display_C", 125.0)),
              # WP-SHIMMER V1 (2026-07-28): ramp time [s] for the `quickstart`
              # I(t) scenario, params.yaml transient.quickstart_ramp_s.
              "quickstart_ramp_s": float(cfg.raw.get("transient", {}).get("quickstart_ramp_s", 8.0))}

    # 4c. Disc-radius compare mode (2026-07-03, user request; SSOT-derived count
    # since WP-HTML 2026-07-10 -- see plate_variant_radii_mm()): bake EVERY
    # aluminium/3mm plate_library radius so the UI can swap the live disc
    # without a rebuild. As of 2026-07-10 (real-disc data swap) that's 4 radii
    # (65/70/75/80mm -- the team's real measured Ø130/140/150/160mm discs;
    # Ø160mm/r=80mm is the standard test disc). Each radius gets its own
    # from-scratch EM+ROM+lev solve (same reasoning as --plate-radius: a
    # wider/narrower disc genuinely changes the eddy distribution and lift
    # force, not just a scale factor).
    # The active build's own radius is reused as-is (already solved above) to
    # avoid solving it twice.
    print("[VARIANTS] Solving EM+ROM for disc-radius compare mode:")
    active_radius_mm = float(cfg.plate["radius_mm"])
    # Always include whatever radius this build was actually invoked with (e.g. a
    # future --plate-radius value outside the 4 defaults) so active_idx below can
    # never fail to find a match.
    variant_radii = sorted(set(plate_variant_radii_mm(cfg)) | {active_radius_mm})
    plate_variants = []
    for r in variant_radii:
        if abs(r - active_radius_mm) < 0.5:
            data = {"V": V_disc, "dTe": dTe_disc, "dTa": dTa_disc, "Je": Je_disc,
                    "rom": rom_params, "lev": lev, "P_plate_W": float(em["P_plate_W"]),
                    "field_lines": field_lines}
            print(f"   Ø{2*r:.0f}mm disc : reusing active build")
        else:
            data = solve_plate_variant(cfg, r, z_disc_bot)
            # lev_params() doesn't expose "levitates_at_5A_rms" directly -- re-derive
            # I_min_lev from the returned z_gap_5A/z_decay the SAME way the JS side
            # does (I_LEV_MIN = 5*exp(-z_gap_5A/(2*z_decay))) for an accurate log line.
            i_min = 5.0 * math.exp(-data["lev"]["z_gap_5A_mm"] / (2 * data["lev"]["z_decay_mm"]))
            print(f"   Ø{2*r:.0f}mm disc : P_plate={data['P_plate_W']*1e3:.1f} mW  "
                  f"dT_mean_ref={data['rom']['dT_mean_ref']:.2f} K  "
                  f"lift@5A={'YES' if i_min <= 5.0 else f'no (I_min={i_min:.2f}A)'}")
        Je_v = data["Je"]
        Jn_v = (Je_v / Je_v.max()) if (Je_v is not None and Je_v.max() > 0) \
            else np.zeros(len(data["V"]) * 3, dtype=np.float32)
        plate_variants.append({
            "radius_mm": r,
            "pos_b64":   base64.b64encode(data["V"].reshape(-1).astype("<f4").tobytes()).decode(),
            "dT_b64":    base64.b64encode(data["dTe"].astype(np.float32).tobytes()).decode(),
            "dtair_b64": base64.b64encode(data["dTa"].astype(np.float32).tobytes()).decode(),
            "je_b64":    base64.b64encode(Jn_v.astype(np.float32).tobytes()).decode(),
            "rom":       data["rom"],
            "lev":       data["lev"],
            "P_plate_W": data["P_plate_W"],
            "field_lines": data["field_lines"],
            # Disc weight m·g [N] (ρ·πR²·t·g, same formula as _lev_anchor) -- the
            # force panel shows F_mag against it. Display only.
            "F_grav_N":  round(float(cfg.plate["rho_kg_per_m3"]) * math.pi * (r * 1e-3) ** 2
                               * float(cfg.plate["thickness_mm"]) * 1e-3 * 9.81, 4),
        })
    active_idx = next(i for i, r in enumerate(variant_radii)
                       if abs(r - active_radius_mm) < 0.5)
    params["plate_variants"] = plate_variants
    params["active_plate_idx"] = active_idx

    lap(f"{len(plate_variants) - 1} other disc radii (EM + ROM + z_eq each)")
    # 5. Encode binary data as base64
    pos_b64   = base64.b64encode(V.reshape(-1).astype("<f4").tobytes()).decode()
    reg_b64   = base64.b64encode(region.tobytes()).decode()
    dT_b64    = base64.b64encode(dTe_vtx.tobytes()).decode()
    dtair_b64 = base64.b64encode(dTa_vtx.tobytes()).decode()
    je_b64    = base64.b64encode(Jn_vtx.tobytes()).decode()

    # Key gating (security fix): by default ALWAYS bake the literal placeholder,
    # regardless of whether local/.env.local or GOOGLE_WEATHER_API_KEY is present
    # -- the previous unconditional call baked a real live key into this tracked
    # output file. Only --bake-key opts into embedding a real key, with a loud
    # warning so it's obvious the resulting file must not be committed as-is.
    # Expiry (params.yaml weather_api.key_valid_until, inclusive): past that date
    # the real key is never baked, and the baked JS itself also stops calling the
    # API, so a copy made before the cutoff goes quiet once the date passes.
    key_valid_until = str(cfg.raw.get("weather_api", {}).get("key_valid_until", "1970-01-01"))
    key_expired = datetime.date.today() > datetime.date.fromisoformat(key_valid_until)
    if bake_key and key_expired:
        print(f"\n[weather] key expired (valid until {key_valid_until}) — "
              f"baking the placeholder instead")
        bake_key = False
    if bake_key:
        google_key = _load_google_weather_key()
        if google_key and google_key != "YOUR_KEY_HERE":
            print(f"\n⚠️  Baking a REAL API key into {out_path} (valid until "
                  f"{key_valid_until}) — do not commit this file while it contains a real key")
    else:
        google_key = "YOUR_KEY_HERE"

    html = (TEMPLATE
            .replace("__POS_B64__",   pos_b64)
            .replace("__REG_B64__",   reg_b64)
            .replace("__DT_B64__",    dT_b64)
            .replace("__DTAIR_B64__", dtair_b64)
            .replace("__JE_B64__",    je_b64)
            .replace("__PARAMS__",    json.dumps(params))
            .replace("__GOOGLE_WEATHER_KEY__", google_key)
            .replace("__GOOGLE_WEATHER_KEY_VALID_UNTIL__", key_valid_until)
            .replace("__WEATHER_LAT__", repr(float(cfg.raw.get("weather_api", {}).get("lat", 49.8728))))
            .replace("__WEATHER_LON__", repr(float(cfg.raw.get("weather_api", {}).get("lon", 8.6512)))))

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    sz_kb = len(html) / 1024
    print(f"\nWrote {out_path}  ({sz_kb:.0f} KB) — double-click to run.")
    lap("encode + write HTML")

    total = time.perf_counter() - t_start
    print("\n[TIME] offline computation (this build):")
    for label, sec in timing:
        print(f"[TIME]   {label:44s} {sec:7.2f} s  {100 * sec / total:5.1f} %")
    print(f"[TIME]   {'TOTAL':44s} {total:7.2f} s")
    with open(os.path.join(os.path.dirname(os.path.abspath(out_path)), "build_timing.json"),
              "w", encoding="utf-8") as f:
        json.dump({"built_at": datetime.datetime.now().isoformat(timespec="seconds"),
                   "html": os.path.basename(out_path), "total_s": round(total, 3),
                   "stages": [[label, round(sec, 3)] for label, sec in timing]}, f, indent=1)


# ─── HTML / JS template ───────────────────────────────────────────────────────

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Digital Twin for Thermal Management — TEMF Levitator</title>
<style>
/* Design tokens. Values are tuned for long viewing: low-saturation text,
   one accent, semantic colours only on numbers that carry meaning. */
:root{
  --bg:#0d0f1a; --panel-bg:rgba(14,17,30,.80); --panel-border:rgba(130,150,200,.16);
  --text:#dde3f0; --muted:#8e98b0; --faint:#626c86; --accent:#8fb6ff;
  --hover:rgba(143,182,255,.08); --chip:rgba(143,182,255,.07);
  --hdr-bg:rgba(13,15,26,.86);
  --c-hot:#ffc266; --c-ok:#7fd8a0; --c-air:#f0a868; --c-gap:#9fcdf5;
  --c-b:#8fb6ff; --c-j:#e6cf72; --c-coil:#f59a62; --c-warn:#ff7a7a;
  --font:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Inter,Roboto,sans-serif;
}
body.light{
  --bg:#eef1f7; --panel-bg:rgba(255,255,255,.86); --panel-border:rgba(40,60,110,.14);
  --text:#14213d; --muted:#24406e; --faint:#43608f; --accent:#2a62d4;   /* cool navy/steel, not grey (user 2026-10-06) */
  --hover:rgba(42,98,212,.07); --chip:rgba(42,98,212,.06);
  --hdr-bg:rgba(255,255,255,.88);
  --c-hot:#c27a00; --c-ok:#1f8a4c; --c-air:#b8621e; --c-gap:#2a7ab8;
  --c-b:#2a62d4; --c-j:#9a7a00; --c-coil:#c4561b; --c-warn:#d23b3b;
}
*{box-sizing:border-box}
body{margin:0;overflow:hidden;background:var(--bg);color:var(--text);
     font-family:var(--font);font-size:12.5px;line-height:1.4;
     -webkit-font-smoothing:antialiased;transition:background .25s}

/* ── Header bar ──────────────────────────────────────────────────────────── */
#headerBar{position:fixed;top:0;left:0;right:0;height:48px;z-index:30;
  display:flex;align-items:center;justify-content:space-between;gap:14px;
  padding:0 16px;background:var(--hdr-bg);border-bottom:1px solid var(--panel-border);
  backdrop-filter:blur(14px);color:var(--text)}
.brand{display:flex;align-items:center;gap:10px;min-width:0}
.brand .logo{font-size:1.15rem;line-height:1;opacity:.9}
.brand .titles{display:flex;flex-direction:column;line-height:1.2;min-width:0}
.brand .title{font-weight:600;font-size:13.5px;color:var(--text);letter-spacing:.01em;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.brand .subtitle{font-size:11px;color:var(--faint);white-space:nowrap}
.hdr-mid{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.hdr-badge{font-size:11px;padding:2px 9px;border-radius:10px;background:var(--chip);
  color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums}
.hdr-right{display:flex;align-items:center;gap:8px}
.iconbtn{background:none;border:1px solid var(--panel-border);color:var(--muted);
  border-radius:6px;padding:5px 10px;cursor:pointer;font-size:11.5px;white-space:nowrap}
.iconbtn:hover{color:var(--text);border-color:var(--accent)}
.infobtn{width:26px;height:26px;border-radius:50%;border:1.5px solid var(--accent);
  background:var(--chip);color:var(--accent);cursor:pointer;padding:0;flex:none;
  font:italic 700 14px/1 Georgia,'Times New Roman',serif}
.infobtn:hover,.infobtn.on{background:var(--accent);color:#fff}

/* ── Model-information sheet ("i" button) ───────────────────────────────── */
#infoOverlay{position:fixed;inset:0;z-index:60;display:none;align-items:center;
  justify-content:center;padding:16px;background:rgba(0,0,0,.45);backdrop-filter:blur(3px)}
#infoOverlay.open{display:flex}
#infoCard{width:min(860px,100%);max-height:calc(100vh - 32px);display:flex;flex-direction:column;
  background:var(--hdr-bg);border:1px solid var(--panel-border);border-radius:12px;
  box-shadow:0 18px 50px rgba(0,0,0,.45);backdrop-filter:blur(18px);overflow:hidden}
.info-head{display:flex;justify-content:space-between;align-items:center;gap:10px;
  padding:11px 16px;border-bottom:1px solid var(--panel-border);font-weight:600;font-size:13.5px}
.info-body{overflow-y:auto;padding:2px 16px 14px;scrollbar-width:thin}
.info-body h3{margin:16px 0 6px;font-size:11px;font-weight:600;letter-spacing:.06em;
  text-transform:uppercase;color:var(--accent)}
.info-wrap{overflow-x:auto}
.info-tbl{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
.info-tbl th{padding:5px 8px;text-align:left;font-size:10.5px;font-weight:600;color:var(--muted);
  background:var(--chip);border-bottom:1px solid var(--panel-border);white-space:nowrap}
.info-tbl td{padding:5px 8px;border-top:1px solid var(--panel-border);vertical-align:middle;color:var(--text)}
.info-tbl td.mat{font-weight:600;white-space:nowrap;border-right:1px solid var(--panel-border)}
.info-tbl td.k{color:var(--muted)}
.info-tbl td.s{width:1%;text-align:right}
.info-tbl tbody tr:hover td:not(.mat){background:var(--hover)}
.info-tbl tr[title]:not([title=""]){cursor:help}
.sw{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:7px;vertical-align:-1px}
.asm{color:#ff7a7a;font-weight:600}
.info-foot{margin-top:12px;font-size:10.5px;color:var(--faint);line-height:1.9}
.src{display:inline-block;font-size:10px;font-weight:600;padding:1px 7px;border-radius:9px;
  white-space:nowrap;border:1px solid currentColor;opacity:.9}
.src.meas{color:#3fbf7f}.src.given{color:#5b9cff}.src.ref{color:#a98bff}
.src.calc{color:#36c2d6}.src.assumed{color:#ff7a7a}

/* ── Panels: controls on the LEFT, readouts on the RIGHT, model free in the middle */
.ui-col{position:absolute;top:58px;display:flex;flex-direction:column;gap:10px;
  max-height:calc(100vh - 68px);overflow-y:auto;overflow-x:hidden;
  pointer-events:none;z-index:10;scrollbar-width:thin;scrollbar-color:var(--panel-border) transparent}
.ui-col::-webkit-scrollbar{width:4px}
.ui-col::-webkit-scrollbar-thumb{background:var(--panel-border);border-radius:2px}
#uiLeft{left:12px;align-items:flex-start}
#uiRight{right:12px;align-items:flex-end}
.panel{background:var(--panel-bg);border-radius:10px;flex:none;
  border:1px solid var(--panel-border);pointer-events:auto;backdrop-filter:blur(14px);
  box-shadow:0 6px 20px rgba(0,0,0,.28);width:252px;overflow:hidden;
  transition:width .25s ease,background .25s,border-color .25s}
.panel-head{margin:0;padding:9px 12px;cursor:pointer;user-select:none;
  display:flex;justify-content:space-between;align-items:center;gap:10px;
  font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
  color:var(--muted);border-bottom:1px solid var(--panel-border)}
.panel-head:hover{color:var(--text);background:var(--hover)}
.panel-head span:first-child{white-space:nowrap}
.panel-head .chev{font-size:10px;color:var(--faint);transition:transform .2s}
.panel.collapsed .panel-head{border-bottom-color:transparent}
.panel.collapsed .chev{transform:rotate(-90deg)}
.panel.collapsed .panel-body{display:none}
.panel-body{padding:10px 12px 12px}
.sec{font-size:10.5px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;
  color:var(--faint);margin:12px 0 6px}
.sec:first-child{margin-top:0}
/* Collapsible picker (Ambient / Disc radius): the chip shows the current choice,
   a click pops the options out, they fold back after PICK_HIDE_MS idle. */
.sec-pick{display:flex;align-items:center;justify-content:space-between;gap:8px}
.pick-chip{text-transform:none;letter-spacing:0;font-family:inherit;font-weight:600;font-size:11.5px;line-height:1;
  color:var(--accent);background:rgba(143,182,255,.12);border:1px solid rgba(143,182,255,.35);
  border-radius:6px;padding:4px 9px;cursor:pointer}
.pick-chip:hover,.pick-chip[aria-expanded="true"]{background:rgba(143,182,255,.22)}
.pick-chip::after{content:" ▾";opacity:.7}
.pick-chip[aria-expanded="true"]::after{content:" ▴"}
.pick-chip:disabled{opacity:.4;cursor:not-allowed}
.pick-body{display:none}
.pick-body.open{display:block}
.cg{margin-bottom:8px}
.cg label{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:2px;
  font-size:12px;color:var(--muted)}
input[type=range]{width:100%;margin:2px 0;cursor:pointer;accent-color:var(--accent)}
.row{display:flex;justify-content:space-between;align-items:baseline;gap:8px;
  padding:2px 0;font-size:12px;color:var(--muted)}
.row .sub{font-size:10.5px;color:var(--faint);font-style:italic}
.box{width:9px;height:9px;border-radius:2px;margin-right:6px;display:inline-block}
.val{font-weight:600;font-size:12.5px;color:var(--text);font-variant-numeric:tabular-nums;
  white-space:nowrap}
.valbig{font-weight:600;font-size:20px;line-height:1.1;color:var(--c-hot);
  font-variant-numeric:tabular-nums;white-space:nowrap}
.hero{display:flex;justify-content:space-between;align-items:center;padding:2px 0 4px}
.hero .lbl{font-size:12px;color:var(--muted)}
.kv{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.kv > div{background:var(--chip);border-radius:6px;padding:5px 8px;min-width:0}
.kv .k{display:block;font-size:10.5px;color:var(--faint)}
.kv .val{display:block;overflow:hidden;text-overflow:ellipsis}
.note{font-size:11px;color:var(--faint);font-style:italic;line-height:1.45;margin:6px 0 0}
details.more{margin-top:8px}
details.more summary{cursor:pointer;font-size:11px;color:var(--faint);list-style:none}
details.more summary::-webkit-details-marker{display:none}
details.more summary::before{content:"ⓘ  "}
details.more summary:hover{color:var(--muted)}
details.more p{font-size:11px;color:var(--muted);line-height:1.5;margin:6px 0 0}
/* segmented buttons */
.sc-group{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px}
.sc-btn{flex:1;background:var(--chip);color:var(--muted);border:1px solid transparent;
  border-radius:6px;padding:4px 0;cursor:pointer;font-size:11.5px;font-family:inherit;
  transition:background .15s,color .15s,border-color .15s}
.sc-btn:hover{color:var(--text)}
.sc-btn.active{background:rgba(143,182,255,.16);color:var(--accent);border-color:rgba(143,182,255,.35)}
body.light .sc-btn.active{background:rgba(42,98,212,.12);border-color:rgba(42,98,212,.35)}
button#reset{width:100%;background:none;color:var(--c-warn);border:1px solid rgba(255,122,122,.35);
  border-radius:6px;padding:5px;cursor:pointer;font-size:11.5px;font-family:inherit}
button#reset:hover{background:rgba(255,122,122,.08)}
.sc-btn:disabled,input[type=range]:disabled{opacity:.4;cursor:not-allowed}
.sc-group.locked{opacity:.4;pointer-events:none}
.sensor-stat{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);margin:2px 0 6px}
.sensor-stat .val{margin-left:auto}
.dot{width:7px;height:7px;border-radius:50%;background:var(--faint);flex:none}
.dot.live{background:var(--c-ok);box-shadow:0 0 6px var(--c-ok)}
.dot.stale{background:var(--c-hot)}
.dot.error{background:var(--c-warn)}
.export-row{display:flex;gap:4px;margin-top:8px}
.export-row .sc-btn{padding:5px 0}
#chart,#chartI{background:rgba(0,0,0,.28);border-radius:6px;border:1px solid var(--panel-border);
  display:block;margin-top:4px;width:100%}
.chart-legend{display:flex;gap:4px 10px;font-size:10.5px;color:var(--muted);margin-top:5px;flex-wrap:wrap}
.chart-legend i{display:inline-block;width:10px;height:0;border-top:2px solid;margin-right:4px;vertical-align:middle}
.chart-tip{position:fixed;background:rgba(0,0,0,.85);color:#fff;padding:4px 8px;
  border-radius:4px;font-size:11px;pointer-events:none;z-index:60;display:none;
  border:1px solid #456;font-variant-numeric:tabular-nums}
#scaleBar{margin-top:4px;height:8px;border-radius:4px;position:relative;
  background:linear-gradient(to right,#0000ff,#00ffff,#00ff00,#ffff00,#ff0000)}
#scaleBar .marker,.matBar .marker{position:absolute;top:-3px;width:2px;height:14px;background:#fff;
  box-shadow:0 0 2px #000;transition:left .25s linear}
.matBar{margin-top:4px;height:8px;border-radius:4px;position:relative}
.matBar .marker.o{background:#ffe2b8}
/* Section header with its material's colour bar on the same line: "DISC ▬▬▬" */
.secbar{display:flex;align-items:flex-start;gap:10px}
.secbar .secname{flex:none;min-width:38px;line-height:14px}
.secbar .barwrap{flex:1;min-width:0;text-transform:none;letter-spacing:0;font-weight:400}
.secbar #scaleBar,.secbar .matBar{margin-top:3px}
.scale-foot.tight{margin-top:0;margin-bottom:4px}
.scaleLabel{display:flex;justify-content:space-between;font-size:10px;color:var(--faint);
  margin-top:3px;font-variant-numeric:tabular-nums}
.scale-foot{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-top:6px}
.scale-foot .sc-btn{flex:none;padding:3px 10px}
hr.div{border:0;border-top:1px solid var(--panel-border);margin:10px 0}

/* ── Part callouts: tag + leader line to a camera-facing anchor on the part ── */
#calloutSvg{position:absolute;top:0;left:0;width:100%;height:100%;z-index:1;pointer-events:none;overflow:visible}
#calloutSvg .ld{fill:none;stroke:rgba(160,196,255,.75);stroke-width:1.1}
#calloutSvg .ld.hid{stroke-dasharray:3 3;stroke:rgba(160,196,255,.45)}
#calloutSvg .dot{fill:#9cc3ff;stroke:rgba(10,14,28,.9);stroke-width:1}
#calloutSvg .iron .ld{stroke:rgba(255,190,120,.75)}
#calloutSvg .iron .ld.hid{stroke:rgba(255,190,120,.45)}
#calloutSvg .iron .dot{fill:#ffc58a}
#calloutLayer{position:absolute;top:0;left:0;width:100%;height:100%;z-index:1;pointer-events:none;overflow:hidden}
.callout{position:absolute;left:0;top:0;font-family:var(--font);color:#d6e4ff;
  background:rgba(10,14,28,.72);border:1px solid rgba(143,182,255,.30);border-radius:7px;
  padding:3px 8px 4px;white-space:nowrap;line-height:1.25;will-change:transform}
.callout .nm{font-size:10.5px;font-weight:600}
.callout .lv{font-size:10.5px;margin-left:8px;color:#fff;font-variant-numeric:tabular-nums}
.callout .rl{display:block;font-size:9.5px;color:rgba(214,228,255,.62)}
.callout.iron{color:#ffdcb0;border-color:rgba(255,170,80,.38)}
.callout.iron .rl{color:rgba(255,220,176,.62)}
.callout.hid{opacity:.72}
.callout.force{font-size:10px;padding:1px 6px;border-radius:5px}
.callout.force.up{color:#7fe7ff;border-color:rgba(127,231,255,.45)}
.callout.force.dn{color:#ffb070;border-color:rgba(255,176,112,.45)}
/* "Why does the disc float?" strip -- B-field / Both modes only */
#forceInfoBtn{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);z-index:6;
  display:none;align-items:center;justify-content:center;padding:0}
#forcePanel{position:fixed;left:50%;bottom:50px;transform:translateX(-50%);z-index:5;
  background:rgba(10,14,28,.80);border:1px solid rgba(127,231,255,.30);border-radius:9px;
  padding:6px 12px;font-size:11px;color:#d6e4ff;max-width:min(560px,calc(100vw - 32px));
  display:none;pointer-events:none;line-height:1.45}
#forcePanel b{color:#fff;font-weight:600}
#forcePanel .up{color:#7fe7ff}
#forcePanel .dn{color:#ffb070}
#forcePanel .st{display:inline-block;margin-left:6px;padding:0 6px;border-radius:5px;
  background:rgba(127,231,255,.12);color:#bff3ff}

/* Light theme: overlays on the light 3D scene get a light card + dark, cool text
   (the dark-theme pastel cyan/amber/orange is unreadable on a pale background). */
body.light #calloutSvg .ld{stroke:rgba(36,64,110,.70)}
body.light #calloutSvg .ld.hid{stroke:rgba(36,64,110,.40)}
body.light #calloutSvg .dot{fill:#2a62d4;stroke:#fff}
body.light #calloutSvg .iron .ld{stroke:rgba(67,96,143,.75)}
body.light #calloutSvg .iron .ld.hid{stroke:rgba(67,96,143,.45)}
body.light #calloutSvg .iron .dot{fill:#43608f}
body.light .callout{color:#14213d;background:rgba(255,255,255,.92);border-color:rgba(42,98,212,.35);
  box-shadow:0 1px 4px rgba(20,33,61,.12)}
body.light .callout .lv{color:#0b3a8f}
body.light .callout .rl{color:#43608f}
body.light .callout.iron{color:#24406e;border-color:rgba(67,96,143,.45)}
body.light .callout.iron .rl{color:#43608f}
body.light .callout.force.up{color:#00609a;border-color:rgba(0,96,154,.45)}
body.light .callout.force.dn{color:#5b3aa8;border-color:rgba(91,58,168,.45)}
body.light #forcePanel{background:rgba(255,255,255,.95);color:#14213d;border-color:rgba(42,98,212,.35);
  box-shadow:0 2px 8px rgba(20,33,61,.15)}
body.light #forcePanel b{color:#0b1f4d}
body.light #forcePanel .up{color:#00609a}
body.light #forcePanel .dn{color:#5b3aa8}
body.light #forcePanel .st{background:rgba(42,98,212,.10);color:#1d4fb8}

#pausedBadge{position:fixed;top:58px;left:50%;transform:translateX(-50%);
  background:rgba(255,122,122,.12);color:var(--c-warn);border:1px solid rgba(255,122,122,.45);
  border-radius:6px;padding:3px 12px;font-size:11.5px;letter-spacing:.04em;
  z-index:25;display:none}

@media (max-width:760px){
  body{overflow-y:auto;overflow-x:hidden}
  #headerBar{position:sticky;height:auto;flex-wrap:wrap;padding:8px 12px;gap:6px}
  .brand .title{white-space:normal}
  .hdr-mid{order:3;width:100%}
  .ui-col,#uiLeft,#uiRight{position:relative;top:auto;left:auto;right:auto;max-height:none;overflow:visible;
    margin:10px;align-items:stretch;pointer-events:auto}
  .panel{width:100%}
  /* the canvas sits behind the stacked panels here -> callouts would only peek out */
  #calloutSvg,#calloutLayer,#forcePanel,#forceInfoBtn{display:none!important}
}
</style></head><body>

<div id="headerBar">
  <div class="brand">
    <span class="logo">🧲</span>
    <div class="titles">
      <span class="title">Digital Twin for Thermal Management — TEMF Levitator</span>
      <span class="subtitle">Real-time thermal simulation · TEAM 28</span>
    </div>
  </div>
  <div class="hdr-mid">
    <span class="hdr-badge">FEM ROM (axisymmetric)</span>
    <span class="hdr-badge" id="tAmbBadge">T_amb = 20 °C</span>
    <span class="hdr-badge" id="hdrIBadge">I = 5.00 A</span>
  </div>
  <div class="hdr-right">
    <button class="infobtn" id="infoBtn" title="Model information (I)" aria-label="Model information">i</button>
    <button class="iconbtn" id="themeToggle">☀️ Light</button>
  </div>
</div>
<div id="infoOverlay" role="dialog" aria-modal="true" aria-labelledby="infoTitle">
  <div id="infoCard">
    <div class="info-head">
      <span id="infoTitle">Model information — TEMF levitator</span>
      <button class="iconbtn" id="infoClose" aria-label="Close">✕</button>
    </div>
    <div class="info-body" id="infoBody"></div>
  </div>
</div>
<div id="pausedBadge">⏸ PAUSED — press Space to resume</div>

<div id="uiLeft" class="ui-col">
  <!-- Panel 1: Controls -->
  <div class="panel" id="panelControls">
    <div class="panel-head"><span>Physics Controls</span><span class="chev">▾</span></div>
    <div class="panel-body">
    <div class="sec sec-pick"><span>Scenario</span>
      <button class="pick-chip" id="scChip" aria-expanded="false" title="Change scenario">Quick</button></div>
    <div class="pick-body" id="scBody">
    <div class="sc-group" id="scGroup">
      <button class="sc-btn active" data-sc="quickstart">Quick</button>
      <button class="sc-btn" data-sc="step">Step</button>
      <button class="sc-btn" data-sc="ramp">Ramp</button>
      <button class="sc-btn" data-sc="sine">Sine</button>
      <button class="sc-btn" data-sc="pulse">Pulse</button>
    </div>
    </div>
    <div class="sec sec-pick"><span>Excitation</span>
      <button class="pick-chip" id="excChip" aria-expanded="false" title="Change input mode">Amps</button></div>
    <div class="pick-body" id="excBody">
    <div class="sc-group" id="inputModeGroup">
      <button class="sc-btn active" data-mode="amps">Amps</button>
      <button class="sc-btn" data-mode="dial">Variac dial</button>
      <button class="sc-btn" data-mode="sensor">Sensor</button>
    </div>
    </div>
    <div class="cg" id="sensorGroup" style="display:none">
      <div class="sensor-stat"><span class="dot" id="sensorDot"></span>
        <span id="sensorState">Not connected</span><span class="val" id="sensorI">— A</span></div>
      <div class="sc-group" style="margin-bottom:4px">
        <button class="sc-btn" id="btnSerial">Connect Arduino</button>
        <button class="sc-btn" id="btnSensorDemo">Demo signal</button>
        <button class="sc-btn" id="btnSensorZero" title="Re-measure the zero-current offset (Variac at 0)">Re-zero</button>
      </div>
      <p class="note" id="sensorNote">Measured I<sub>rms</sub> (ACS712 → Arduino, 1 Hz) drives the
        model in real time. Temperatures stay model predictions.</p>
    </div>
    <div class="cg" id="ampsGroup">
      <label><span>Current I</span><span id="vI" class="val">5.0 A</span></label>
      <input type="range" id="sI" min="0" max="20" step="0.1" value="5">
    </div>
    <div class="cg" id="dialGroup" style="display:none">
      <label><span>Variac dial (CMV 10 E-1)</span><span id="vDial" class="val">220</span></label>
      <input type="range" id="sDial" min="0" max="270" step="1" value="220">
    </div>
    <div class="cg">
      <label><span>Time speed</span><span id="vS" class="val">1.0×</span></label>
      <input type="range" id="sS" min="0" max="2.301" step="0.01" value="0">
    </div>
    <button id="reset">↺ Reset temperatures</button>
    <div class="sec sec-pick"><span>Ambient T<sub>amb</sub></span>
      <button class="pick-chip" id="ambChip" aria-expanded="false" title="Change ambient temperature">— °C</button></div>
    <div class="pick-body" id="ambBody">
      <div class="sc-group" id="ambGroup" style="margin-bottom:2px"></div>
      <p class="note" id="ambNote" style="margin:0 0 4px"></p>
    </div>
    <div class="sec sec-pick"><span>Disc radius</span>
      <button class="pick-chip" id="plateChip" aria-expanded="false" title="Change disc radius">—</button></div>
    <div class="pick-body" id="plateBody">
      <div class="sc-group" id="plateGroup"></div>
    </div>
    <div class="sec">Heat sources</div>
    <div class="row"><span>Disc eddy currents</span>
      <span class="val" id="vPdisc" style="color:var(--c-b)">0.0 W</span></div>
    <div class="row"><span>Coils (ohmic)</span>
      <span class="val" id="vPcoil" style="color:var(--c-coil)">0.0 W</span></div>
    <details class="more"><summary>Why does the disc heat up?</summary>
      <p>Two sources with different speeds: <b>eddy currents</b> in the disc (~4 K, instant
      with I²) and <b>hot air from the coils</b> 3.8 mm below (~8 K, slow — the copper
      takes ~25 min to warm). Total ΔT<sub>ss</sub> ≈ 11 K; hot air dominates, but lags.</p>
    </details>
    <div class="sec">Visualization</div>
    <div class="sc-group" id="vizGroup">
      <button class="sc-btn active" data-viz="thermal">Thermal</button>
      <button class="sc-btn" data-viz="bfield">B field</button>
      <button class="sc-btn" data-viz="eddy">Eddy J</button>
      <button class="sc-btn" data-viz="combined">Both</button>
    </div>
    <div class="cg">
      <label><span>Field line opacity</span><span id="vFLO" class="val">70%</span></label>
      <input type="range" id="sFLO" min="0" max="100" step="1" value="70">
    </div>
    <div class="export-row"><button class="sc-btn" id="btnFitView">Fit view</button></div>
    <p class="note">Space pause · R reset · 1–5 scenario · +/− speed · F / double-click fit view · scroll zoom</p>
    </div>
  </div>
</div>

<div id="uiRight" class="ui-col">
  <!-- Panel 2: Telemetry -->
  <div class="panel" id="panelTelemetry">
    <div class="panel-head"><span>Thermal Telemetry</span><span class="chev">▾</span></div>
    <div class="panel-body">
    <div class="kv">
      <div><span class="k">Sim time</span><span class="val" id="vT">0 s</span></div>
      <div><span class="k">Heat in</span><span class="val" id="vP">0.0 W</span></div>
    </div>
    <div class="sec secbar" title="Disc colour ramp (aluminium). The window eases between absolute (T_amb to hot) and relative (within the disc); the bottom face runs hotter as the coils' hot air builds up.">
      <span class="secname">Disc</span>
      <div class="barwrap">
        <div id="scaleBar"><div class="marker" id="scaleMarkerLo"></div><div class="marker" id="scaleMarkerHi"></div></div>
        <div class="scaleLabel" id="scaleTicks"></div>
      </div></div>
    <div class="scale-foot tight">
      <span class="row" style="padding:0"><span>Range&nbsp;</span><span class="val" id="scaleCurRange">—</span></span>
      <button class="sc-btn" id="scaleModeBtn">Scale: Auto</button>
    </div>
    <div class="hero">
      <span class="lbl"><span class="box" id="bPl" style="background:#2255aa"></span>T<sub>max</sub></span>
      <span class="valbig" id="tPmax">25.0 °C</span></div>
    <div class="row"><span>Bottom air</span>
      <span class="val" id="tAirBot" style="color:var(--c-air)">—</span></div>
    <div class="sec secbar" title="Coil colour ramp (varnished copper): T_amb to the hottest IR reading. Markers: inner (white) / outer (cream).">
      <span class="secname">Coils</span>
      <div class="barwrap">
        <div class="matBar" id="scaleBarCopper"><div class="marker" id="mkInner" title="inner coil"></div><div class="marker o" id="mkOuter" title="outer coil"></div></div>
        <div class="scaleLabel" id="scaleTicksCopper"></div>
      </div></div>
    <div class="row">
      <span><span class="box" id="bIn"></span>Inner · <span id="lblInnerTurns">1000</span> t</span>
      <span class="val" id="tIn">25.0 °C</span></div>
    <div class="row">
      <span><span class="box" id="bOut"></span>Outer · <span id="lblOuterTurns">500</span> t</span>
      <span class="val" id="tOut">25.0 °C</span></div>
    <div class="sec secbar" title="Iron colour ramp (center core + separator ring share one thermal node).">
      <span class="secname">Iron</span>
      <div class="barwrap">
        <div class="matBar" id="scaleBarIron"><div class="marker" id="mkIron"></div></div>
        <div class="scaleLabel" id="scaleTicksIron"></div>
      </div></div>
    <div class="row">
      <span><span class="box" id="bFe"></span>Core + separator ring</span>
      <span class="val" id="tFe">25.0 °C</span></div>
    <div class="sec">Field</div>
    <div class="row" id="satRow"><span>Iron B<sub>max</sub> / B<sub>sat</sub></span>
      <span class="val" id="tBmax" style="color:var(--c-ok)">—</span></div>
    <div class="row"><span>Disc |B|<sub>max</sub></span>
      <span class="val" id="tBplate" style="color:var(--c-b)">—</span></div>
    <div class="row"><span>Disc |J<sub>e</sub>|<sub>max</sub></span>
      <span class="val" id="tJmax" style="color:var(--c-j)">—</span></div>
    <div class="row"><span>Levitation gap</span>
      <span class="val" id="tLevGap" style="color:var(--c-gap)">0.0 mm</span></div>
    </div>
  </div>

  <!-- Panel 3: charts -->
  <div class="panel" id="panelChart">
    <div class="panel-head"><span>Time History</span><span class="chev">▾</span></div>
    <div class="panel-body">
    <div class="sec">Temperature</div>
    <canvas id="chart" width="228" height="150"></canvas>
    <div class="chart-legend">
      <span><i style="border-color:#ff6644"></i>Disc T<sub>max</sub></span>
      <span><i style="border-color:#ff8844"></i>Inner</span>
      <span><i style="border-color:#ffcc44"></i>Outer</span>
      <span><i style="border-color:#5599ff;border-top-style:dashed"></i>T<sub>amb</sub></span>
    </div>
    <div class="note" id="tauLabel"></div>
    <div class="sec">Current I(t)</div>
    <canvas id="chartI" width="228" height="80"></canvas>
    <div class="export-row">
      <button class="sc-btn" id="btnScreenshot">Screenshot</button>
      <button class="sc-btn" id="btnExportCsv">Export CSV</button>
    </div>
    </div>
  </div>
</div>

<script type="importmap">
{ "imports": {
  "three": "https://unpkg.com/three@0.160.0/build/three.module.js",
  "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"
} }
</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
// Load timing [ms since navigation start] -- diagnostics only. RUN.py reads
// window.__twinTiming from a headless browser and prints it in the terminal.
const TWIN_T = {three_loaded: performance.now()};
// ── Baked data ────────────────────────────────────────────────────────────────
const PARAMS = __PARAMS__;
const ROM    = PARAMS.rom;    // T_amb tau I_ref dT_mean_ref dT_max_ref alpha P_ref UA + I_em_ref/B_max/J_max
const LUMPED = PARAMS.lumped; // {nodes:{inner,outer,iron:{P_ref,C,hA}}}
const FIELD_LINES = PARAMS.field_lines; // [{r:[mm],z:[mm],amp:[0..1]}, ...] meridian-plane ψ=const contours

// Turn counts baked from params.yaml (WP-HTML fix, were JS/HTML literals
// "1000t"/"500t"/"1000 turns"/"500 turns") -- fill the telemetry-panel labels.
document.getElementById('lblInnerTurns').textContent = PARAMS.coils_inner_turns;
document.getElementById('lblOuterTurns').textContent = PARAMS.coils_outer_turns;

// Ambient fallback = params.yaml thermal_bc.T_ambient_degC (20 °C, baked as
// ROM.T_amb) -- the same constant ambient the offline FEM/ROM was solved at
// (professor: "take everything as simple as possible"). Used whenever there is
// no live reading (placeholder key, key past weather_api.key_valid_until,
// offline). With a live reading the twin runs on the REAL lab ambient instead,
// and the reading (value, source, time) is recorded in the header badge, the
// telemetry panel and every row of the exported CSV.
const T_AMB_FALLBACK_C = ROM.T_amb;

// Optional live ambient lookup (Google Maps Platform Weather API,
// currentConditions:lookup, Darmstadt DE @ 49.8728,8.6512) — this HTML is a
// standalone client-side file with no server, so any key placed here IS
// visible to anyone who views source. TEMP/LOCAL-TEST KEY ONLY — this key is
// unrestricted (no HTTP-referrer/IP lock) and DID NOT SHIP with this repo:
// do not commit this file with the key baked in, it would leak a billable
// Google API key publicly. Get a properly-restricted key at
// https://console.cloud.google.com/apis/credentials (enable "Weather API";
// docs: https://developers.google.com/maps/documentation/weather).
const GOOGLE_WEATHER_API_KEY = "__GOOGLE_WEATHER_KEY__";
// Inclusive last day the key may be used (params.yaml weather_api.key_valid_until).
const GOOGLE_WEATHER_KEY_VALID_UNTIL = "__GOOGLE_WEATHER_KEY_VALID_UNTIL__";
const DARMSTADT_LAT = __WEATHER_LAT__;   // params.yaml weather_api.lat/lon
const DARMSTADT_LON = __WEATHER_LON__;

function weatherKeyExpired() {
  const d = new Date();
  const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  return today > GOOGLE_WEATHER_KEY_VALID_UNTIL;   // ISO dates compare as strings
}

async function fetchAmbientC(timeoutMs = 4000) {
  const at = new Date();
  const fallback = (why) => ({ value: T_AMB_FALLBACK_C, live: false, at, source: `fallback (${why})` });
  if (!GOOGLE_WEATHER_API_KEY || GOOGLE_WEATHER_API_KEY === "YOUR_KEY_HERE") {
    return fallback('no key');
  }
  if (weatherKeyExpired()) {
    console.warn(`[ambient] weather key expired (valid until ${GOOGLE_WEATHER_KEY_VALID_UNTIL}); using fallback`);
    return fallback('key expired');
  }
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    const url = `https://weather.googleapis.com/v1/currentConditions:lookup?key=${GOOGLE_WEATHER_API_KEY}&location.latitude=${DARMSTADT_LAT}&location.longitude=${DARMSTADT_LON}&unitsSystem=METRIC`;
    const res = await fetch(url, { signal: ctrl.signal });
    clearTimeout(timer);
    if (!res.ok) throw new Error(`Google Weather API HTTP ${res.status}`);
    const data = await res.json();
    const t = data && data.temperature && data.temperature.degrees;
    if (typeof t !== 'number' || !isFinite(t)) throw new Error('Malformed Google Weather API response');
    return { value: t, live: true, at, source: 'google_weather' };
  } catch (err) {
    console.warn(`[ambient] Google Weather API fetch failed, falling back to ${T_AMB_FALLBACK_C}°C:`, err);
    return fallback('fetch failed');
  }
}
// Top-level await (module script): blocks the rest of this module until we know
// the baseline, so every T_AMB_JS-derived const below picks up the right value —
// resolves immediately (no real fetch) unless a live, unexpired key was baked in.
// `let`, not `const` (2026-09-27): the T_amb selector (20 °C / 29 °C / Live) can
// change it at runtime -- setAmbient() below then resets the sim to equilibrium
// at the new ambient and repaints everything derived from it.
let ambient = await fetchAmbientC();
let T_AMB_JS = ambient.value;
let T_AMB_AT = ambient.at.toISOString();   // when the ambient was recorded
TWIN_T.ambient_ready = performance.now();
console.info(`[ambient] T_amb = ${T_AMB_JS} °C, source=${ambient.source}, at ${T_AMB_AT}`);
function paintAmbient() {
  const hhmm = ambient.at.toTimeString().slice(0, 5);
  const badge = document.getElementById('tAmbBadge');
  if (badge) {
    badge.textContent = `T_amb = ${T_AMB_JS.toFixed(1)} °C${ambient.live ? ` (live ${hhmm})` : ''}`;
    badge.title = `source: ${ambient.source}, recorded ${T_AMB_AT}`;
  }
  // The live value is written into the left panel's "Live" button itself
  // (paintAmbGroup) -- no separate telemetry row (user, 2026-10-06).
}
paintAmbient();

function b64Buf(b64){
  const s=atob(b64),a=new Uint8Array(s.length);
  for(let i=0;i<s.length;i++)a[i]=s.charCodeAt(i);return a.buffer;
}
const positions  = new Float32Array(b64Buf("__POS_B64__"));    // CAD mm Z-up
const regions    = new Uint8Array  (b64Buf("__REG_B64__"));    // per triangle
const dT_ref_vtx = new Float32Array(b64Buf("__DT_B64__"));     // eddy field [K], uniform thru-thickness
const dT_air_vtx = new Float32Array(b64Buf("__DTAIR_B64__"));  // hot-air field [K], bottom-weighted
const Je_vtx     = new Float32Array(b64Buf("__JE_B64__"));     // eddy-current density, normalized 0..1
TWIN_T.data_decoded = performance.now();

// Rotate CAD Z-up → Three.js Y-up: (x,y,z)→(x,z,−y)
for(let i=0;i<positions.length;i+=3){
  const y=positions[i+1],z=positions[i+2];
  positions[i+1]=z; positions[i+2]=-y;
}

// ==== TWIN_ENGINE_BEGIN ====
// SINGLE SOURCE OF TRUTH for the twin's physics in the browser. build_ar_twin.py
// extracts everything between these two markers VERBATIM into ar_twin.html, so
// the AR page runs exactly this integrator (xval_twin.py pins both pages against
// twin_core.py). Rules for this block:
//   * PURE: no DOM, no Three.js, no UI state (paused, targetI, meshes, ...).
//   * External dependencies are ONLY these four names, defined by the host page
//     before the block: PARAMS (baked json), ROM (= PARAMS.rom), LUMPED
//     (= PARAMS.lumped) and T_AMB_JS (ambient baseline [deg C]).
//   * Anything else (display exaggeration, colours, scenarios, telemetry) lives
//     OUTSIDE the markers.
// ── Simulation state (mirrors digital_twin.py DigitalTwin) ───────────────────
const sim = {
  beta:      0.0,                // total disc amplitude β = f_eddy·β_eddy + f_air·β_air
  beta_eddy: 0.0,               // eddy-driven part — responds to I² instantly
  beta_air:  0.0,               // hot-air part — gated by the coils' thermal inertia
  t:    0.0,                     // sim time [s]
  // inner/outer/iron = body (surface) nodes; air = shared LOCAL air node they all
  // heat up. The bodies convect into `air`, and `air` sheds heat to the far
  // ambient ROM.T_amb. inner_deep/outer_deep = hidden winding-core mass (WP-B,
  // 2026-07-02): conducts with its surface node via G_wind, no direct
  // convection to air -- this is what makes cooldown far slower than heat-up.
  T: { inner: T_AMB_JS, outer: T_AMB_JS, iron: T_AMB_JS, air: T_AMB_JS,
       inner_deep: T_AMB_JS, outer_deep: T_AMB_JS },
  hist_t:    [0.0],
  hist_Tmax: [T_AMB_JS],
  hist_T_inner: [T_AMB_JS],
  hist_T_outer: [T_AMB_JS],
  hist_I:    [0.0],
};

// Shared LOCAL air node — the bodies (coils/iron) convect into this small pocket
// of air, which in turn loses heat to the far ambient. Illustrative environment
// values, baked from params.yaml lumped_thermal.air_node_* (same intent as the
// lumped-only build_twin_html.py).
const AIR = { C_air: LUMPED.air_node.C, hA_far: LUMPED.air_node.hA_far };

// Steady over-temperature of the air node above the far ambient at I_ref: it
// receives ALL body convection (Σ P_ref) and sheds it through hA_far.
let AIR_P_SUM_REF = 0.0;
for (const k in LUMPED.nodes) AIR_P_SUM_REF += LUMPED.nodes[k].P_ref;
const AIR_DT_SS_REF = AIR_P_SUM_REF / AIR.hA_far;

// Power-weighted coil steady over-temperature (vs far ambient) at I_ref — the
// denominator for the hot-air drive. Each coil sits at its own rise above the air
// node (P_ref/hA) PLUS the air node's rise above ambient, so coilAirDrive() still
// → (I/I_ref)² at steady state and the plate's β_air_ss is unchanged.
const COIL_DT_SS_REF =
  LUMPED.nodes.inner.P_ref * (LUMPED.nodes.inner.P_ref / LUMPED.nodes.inner.hA + AIR_DT_SS_REF) +
  LUMPED.nodes.outer.P_ref * (LUMPED.nodes.outer.P_ref / LUMPED.nodes.outer.hA + AIR_DT_SS_REF);
function coilAirDrive() {
  const ai = LUMPED.nodes.inner, ao = LUMPED.nodes.outer;
  const num = ai.P_ref * (sim.T.inner - T_AMB_JS) +
              ao.P_ref * (sim.T.outer - T_AMB_JS);
  return Math.max(0.0, num / COIL_DT_SS_REF);
}

// Nonlinear natural convection (simplified Churchill-Chu): h grows slowly with
// ΔT (h ~ ΔT^n, n=LUMPED.convection_exponent≈0.25). hA_cal was calibrated
// against the I_ref steady-state ΔT (nd.dT_cal), so hAEff(dT_cal)=hA_cal exactly
// — the I_ref steady state is untouched. Below dT_cal (e.g. during cooldown, as
// ΔT→0) h drops well below hA_cal, which is what stretches the cooldown tail.
function hAEff(hA_cal, dT, dT_cal) {
  const dTuse = Math.max(Math.abs(dT), 0.1);
  return hA_cal * Math.pow(dTuse / dT_cal, LUMPED.convection_exponent);
}

// ── ROM step — two-source disc model + coil thermal inertia ──────────────────
// The disc is heated by (a) its OWN eddy currents (instantaneous with I²) and
// (b) the hot air rising from the coils. (b) cannot appear before the copper mass
// warms up, so it is driven by the coil node temperature (which carries the
// inertia) instead of the instantaneous I². β_ss is unchanged → same steady state.
function romStep(I, dt) {
  const s2 = (I / ROM.I_ref) ** 2;
  // σ(T) correction: P_actual = P_ref / (1 + α·ΔT_mean)   (disc aluminium)
  const dT_mean = sim.beta * ROM.dT_mean_ref;
  const s = 1.0 / (1.0 + ROM.alpha * Math.max(dT_mean, 0.0));

  // (1) Lumped ODE for coils / iron — integrate FIRST so the disc's hot-air
  //     drive below reads this step's coil temperature (the source of inertia).
  //     Each body convects into the SHARED LOCAL air node (sim.T.air), not the
  //     far field — they heat up a common pocket of air around themselves.
  // Contact conduction inner coil → iron/core-separator: the passive metal parts
  // physically touch the coil and heat mainly through that contact (real IR:
  // core reaches ~45°C after 350 s at 6.175A, still rising), not through the air pocket.
  const q_cond = (LUMPED.nodes.iron.G_cond || 0) * (sim.T.inner - sim.T.iron);
  let Qconv = 0.0;
  for (const k in LUMPED.nodes) {
    const nd = LUMPED.nodes[k];
    // WP-COOL T1 (2026-07-28, docs/archive/2026-07-28_BUG_REGISTER.md T1): split
    // P_ref across surface/deep in the coil's own C-ratio instead of dumping
    // 100% onto the surface node while the deep node (most of the copper
    // mass) got none -- that made heat-up AND cooldown ~4.5x too fast.
    // Undefined P_ref_surf/P_ref_deep (iron, or an older bake) means "no
    // split" -- all power on the surface, matching the old behaviour exactly.
    let q_surf = (nd.P_ref_surf !== undefined ? nd.P_ref_surf : nd.P_ref) * s2;
    let q_deep = (nd.P_ref_deep !== undefined ? nd.P_ref_deep : 0.0) * s2;
    if (k === 'iron')  q_surf += q_cond;      // gains from the coil contact
    if (k === 'inner') q_surf -= q_cond;      // energy conservation (≪ P_inner, ~0.6W)
    const dTsurf = sim.T[k] - sim.T.air;
    const hA_use = hAEff(nd.hA, dTsurf, nd.dT_cal);
    const out = hA_use * dTsurf;         // convect into local air
    if (nd.G_wind) {
      // Two-node coil (WP-B): generation now split surf/deep by mass (WP-COOL
      // T1, was ALL-on-surface); the deep winding-core mass exchanges heat
      // with the surface via conduction G_wind, so it is nearly invisible
      // while heating but keeps feeding the surface long after the current is
      // cut, giving a realistic slow cooldown tail.
      const deepKey = k + '_deep';
      const g = nd.G_wind * (sim.T[deepKey] - sim.T[k]);  // >0 when deep hotter
      sim.T[k]       += (q_surf + g - out) / nd.C * dt;
      sim.T[deepKey] += (q_deep - g) / nd.C_deep * dt;
    } else {
      sim.T[k] += (q_surf - out) / nd.C * dt;
    }
    Qconv += out;
  }
  // Local air node: gains all body convection, loses to the far ambient ROM.T_amb.
  sim.T.air += (Qconv - AIR.hA_far * (sim.T.air - T_AMB_JS)) / AIR.C_air * dt;

  // trap 1: coil temperatures are already updated above, so coilAirDrive()
  // below reads the FRESH sim.T.inner/sim.T.outer from this same step.
  const airDrive = coilAirDrive();
  // WP-COOL T3 (2026-07-28, docs/archive/2026-07-28_BUG_REGISTER.md T3): the disc's τ
  // was fit from a FEM with an "enhanced convection facing coils" bottom BC
  // (the coil plume) -- that enhancement fades with the coils' own drive, so
  // cooldown is physically slower than heat-up. ROM.tau_cool_natural_frac
  // undefined (older bake) or 1.0 reproduces the OLD single-tau behaviour
  // exactly. τ only sets the RATE here, never the β targets below, so steady
  // state is unaffected -- see the bug register's proof.
  const fNat = ROM.tau_cool_natural_frac !== undefined ? ROM.tau_cool_natural_frac : 1.0;
  const tauEff = ROM.tau / (fNat + (1.0 - fNat) * Math.min(1.0, airDrive));

  // (2a) eddy part — instantaneous source, fast disc time constant τ
  const tgt_eddy = s2 * s;
  sim.beta_eddy = Math.max(0.0,
    sim.beta_eddy + (tgt_eddy - sim.beta_eddy) / tauEff * dt);
  // (2b) hot-air part — target tracks the (inertia-laden) coil temperature.
  //      airDrive → s2 at steady state, so β_air_ss = s2·s as before.
  const tgt_air = airDrive * s;
  sim.beta_air = Math.max(0.0,
    sim.beta_air + (tgt_air - sim.beta_air) / tauEff * dt);

  sim.beta = ROM.f_eddy * sim.beta_eddy + ROM.f_air * sim.beta_air;
  sim.t += dt;
}

function resetSim() {
  sim.beta = 0.0; sim.beta_eddy = 0.0; sim.beta_air = 0.0; sim.t = 0.0;
  for (const k in sim.T) sim.T[k] = T_AMB_JS;
  sim.hist_t      = [0.0];
  sim.hist_Tmax   = [T_AMB_JS];
  sim.hist_T_inner = [T_AMB_JS];
  sim.hist_T_outer = [T_AMB_JS];
  sim.hist_I      = [0.0];
  sim.hist_dt     = 1.0;
}

// ── Levitation gap physics ────────────────────────────────────────────────────
// The EM lift force decays ~exponentially with gap height z:
//   F(I,z) = (I/5A)² · F1 · e^{−(z−z1)/z0}
//   z_eq(I) = Z_GAP_5A_MM + 2·z0·ln(I/5)   (clamped at 0)
// → CONTINUOUS lift-off at I_min = 5·e^{−z_eq(5A)/(2·z0)}: the gap grows
// smoothly from 0 (no jump) up to z_eq(5A) at 5A.
// WP-D (2026-07-02): baked from params.yaml `levitation` via PARAMS.lev instead
// of hardcoded here; for any --plate-radius build OTHER than R=80mm,
// lev_params() (Python) recomputes fresh per-radius anchors (fixes the R=101
// "wrong nonzero gap" bug).
// z0 (decay length) CALIBRATION (WP-Z0, 2026-07-10, docs/AUDIT_FIX_PLAN_
// 2026-07-04.md OQ-4): two fitting methods for z0 disagreed ~1.5x for the SAME
// R=80mm disc — the F=F_grav-crossing method gave z0≈21.4mm (predicting
// z_eq(7.75A)≈22.9mm), while the F(1mm)/F(5mm) shape-fit method (used for
// every OTHER plate radius via _lev_anchor()) gives z0≈13.6mm. User confirmed
// the real rig's gap only "nudges up a little" from 5A to 7.75-8A, matching
// the smaller value — params.yaml `levitation.z_decay_mm` switched to 13.6mm
// so R=80 now uses the SAME method as every other radius. Still
// order-of-magnitude (no real multi-current gap measurement exists yet); if
// one is taken, refit directly against it instead.
const Z_OBS_7_75A_MM = null;   // [mm] fill in a real measured gap at 7.75A here to refit directly, once available

// Disc-radius compare mode (2026-07-03): every LEV_* constant below used to be a
// one-time `const` derived from PARAMS.lev at load. They are now `let` + rebuilt
// by applyLevParams() whenever the user swaps the active disc radius, so the
// levitation model (equilibrium gap, lift-off current, oscillator ω/ζ) always
// matches the CURRENTLY SELECTED plate's own EM/mass anchors instead of freezing
// at whichever radius happened to be active when the page loaded.
let LEV, Z_GAP_5A_MM, Z_DECAY_MM, I_LEV_MIN, Z_GAP_EXAG,
    LEV_OMEGA, LEV_ZETA0, LEV_ZETA1, JIT_MM, JIT_FREQ1, JIT_FREQ2, JIT_FADE_MM,
    LEV_RIPPLE_GAIN, MAINS_OMEGA, X_RIPPLE_MM;
function applyLevParams(levObj, radiusMm) {
  LEV = levObj;
  Z_GAP_5A_MM = LEV.z_gap_5A_mm;   // [mm] equilibrium gap at I=5A
  Z_DECAY_MM  = LEV.z_decay_mm;    // [mm] EM force decay length z0
  if (Z_OBS_7_75A_MM !== null && Math.abs(radiusMm - 80.0) < 0.5) {
    Z_DECAY_MM = (Z_OBS_7_75A_MM - Z_GAP_5A_MM) / (2 * Math.log(7.75 / 5.0));
  }
  I_LEV_MIN  = 5.0 * Math.exp(-Z_GAP_5A_MM / (2 * Z_DECAY_MM));  // lift-off current
  Z_GAP_EXAG = LEV.z_gap_exaggeration;  // display exaggeration — SAME as
                             // display_z_exaggeration used for the disc thickness
                             // (params.yaml), so every z-axis dimension of the disc
                             // scales consistently (4.1mm@5A -> 8.2 display-mm).
  // Disc vertical dynamics: m·z̈ = F(I,z) − mg − damping. Linearised about the
  // equilibrium this is an underdamped oscillator with ω = √(g/z0).
  LEV_OMEGA = Math.sqrt(9.81 / (Z_DECAY_MM * 1e-3));
  // Eddy-current damping grows with B² ∝ I² (more current -> more braking on the
  // bobbing disc): ζ(I) = ζ0 + ζ1·(I/5)². See CLAUDE.md WP-A for the open
  // calibration note on why ζ1 stays physically-derived rather than fit to the
  // overshoot-ratio acceptance target.
  LEV_ZETA0 = LEV.zeta0;
  LEV_ZETA1 = LEV.zeta1;
  // Sub-liftoff jitter: below I_LEV_MIN the disc rests on the coil, but the AC
  // force still pulses at 100Hz (i(t)² term) — shown as an aliased two-tone
  // shimmer, amplitude ∝ I², fading out once the disc actually lifts.
  JIT_MM    = LEV.jit_mm;
  JIT_FREQ1 = LEV.jit_freq1;
  JIT_FREQ2 = LEV.jit_freq2;
  // Gap [mm] above which sub-liftoff jitter has fully faded (was a JS literal
  // `0.5` inlined in levStep()'s fadeIn calc) -- read from PARAMS.lev, falls
  // back to that same 0.5 if the key isn't present yet.
  JIT_FADE_MM = LEV.jit_fade_mm !== undefined ? LEV.jit_fade_mm : 0.5;
  // WP-SHIMMER V2 (2026-07-28, docs/archive/2026-07-28_BUG_REGISTER.md V2): sustained
  // shimmer while levitating, DISPLAY ONLY -- see the params.yaml comment on
  // lev_ripple_display_gain and docs/physics.md §11. X_RIPPLE_MM is the real
  // (but invisible, ~25um) 1-DOF forced-response amplitude to the 100Hz force
  // ripple, COMPUTED from Z_DECAY_MM + the mains frequency (never pasted) so
  // it stays correct across plate-radius swaps and if the mains freq changes.
  LEV_RIPPLE_GAIN = LEV.lev_ripple_display_gain !== undefined ? LEV.lev_ripple_display_gain : 0.0;
  MAINS_OMEGA = LEV.mains_omega_rad_s !== undefined ? LEV.mains_omega_rad_s : 2 * Math.PI * 50.0;
  {
    const Omega = 2 * MAINS_OMEGA;
    X_RIPPLE_MM = Z_DECAY_MM / Math.abs(1 - (Omega / LEV_OMEGA) ** 2);
  }
}
applyLevParams(PARAMS.lev, PARAMS.plate_variants[PARAMS.active_plate_idx].radius_mm);

function levGapEqMm(I) {
  if (I <= I_LEV_MIN) return 0.0;
  return Z_GAP_5A_MM + 2 * Z_DECAY_MM * Math.log(I / 5.0);
}
function levZeta(I) { return LEV_ZETA0 + LEV_ZETA1 * (I / 5.0) ** 2; }

const lev = {z: 0.0, v: 0.0, jit: 0.0, jitPhase1: 0.0, jitPhase2: 0.0,
             jitLevPhase1: 0.0, jitLevPhase2: 0.0};   // gap [mm], velocity [mm/s]
function levStep(I, dt) {
  const zt   = levGapEqMm(I);
  const zeta = levZeta(I);
  if (zt <= 0 && lev.z <= 0) {
    lev.z = 0; lev.v = 0;   // resting on coil, target also at rest
  } else {
    // Closed-form solution of ẍ + 2ζω ẋ + ω² x = 0 about the (possibly moving)
    // target zt, exact for ANY dt — no substepping needed for stability, unlike
    // Euler. Integrated in SIM time (caller passes dt_sim), so the speed slider
    // correctly speeds up/slows down the bob-and-settle instead of only the
    // thermal side of the sim.
    const x0 = lev.z - zt, v0 = lev.v;
    const wd    = LEV_OMEGA * Math.sqrt(Math.max(1e-6, 1 - zeta * zeta));
    const decay = Math.exp(-zeta * LEV_OMEGA * dt);
    const cwt = Math.cos(wd * dt), swt = Math.sin(wd * dt);
    const A = (v0 + zeta * LEV_OMEGA * x0) / wd;
    lev.z = zt + decay * (x0 * cwt + A * swt);
    lev.v =      decay * ((A * wd - zeta * LEV_OMEGA * x0) * cwt - (x0 * wd + zeta * LEV_OMEGA * A) * swt);
    if (lev.z < 0) { lev.z = 0; if (lev.v < 0) lev.v = 0; }   // floor contact
  }

  const fadeIn = Math.max(0, 1 - lev.z / JIT_FADE_MM);
  let jitContact;
  if (I > 0.05 && fadeIn > 0) {
    lev.jitPhase1 += JIT_FREQ1 * dt;
    lev.jitPhase2 += JIT_FREQ2 * dt;
    const amp = Math.min(1.0, JIT_MM * (I / 5.0) ** 2);
    jitContact = fadeIn * amp * (Math.sin(lev.jitPhase1) + 0.5 * Math.sin(lev.jitPhase2));
  } else {
    jitContact = 0.0;
  }

  // WP-SHIMMER V2 (2026-07-28, docs/archive/2026-07-28_BUG_REGISTER.md V2): sustained
  // shimmer while actually levitating (z>0) -- jitContact above is gated OFF
  // above JIT_FADE_MM=0.5mm, so every disc above ~3.2A was previously
  // perfectly rigid. Honest DISPLAY-ONLY rendering of the real (but
  // invisible, ~25um/100Hz) vertical ripple force -- see X_RIPPLE_MM above.
  // Own phase accumulators so it doesn't sync with jitContact's.
  let jitLev;
  if (I > 0.05 && lev.z > 0.0) {
    lev.jitLevPhase1 += JIT_FREQ1 * dt;
    lev.jitLevPhase2 += JIT_FREQ2 * dt;
    const ampLev = X_RIPPLE_MM * LEV_RIPPLE_GAIN * (I / 5.0) ** 2;
    jitLev = ampLev * (Math.sin(lev.jitLevPhase1) + 0.5 * Math.sin(lev.jitLevPhase2));
  } else {
    jitLev = 0.0;
  }

  lev.jit = jitContact + jitLev;
}

// ── Engine helpers shared by both pages (pure) ───────────────────────────────
// Per-disc-vertex live temperature: eddy part (fast β_eddy, uniform) + hot-air part
// (slow β_air, bottom-weighted). The two time constants differ, so the top/bottom
// gradient GROWS over time as the coils' hot air builds up — not a frozen pattern.
// M needs .dT (eddy ΔT per vertex) and .dTa (hot-air ΔT per vertex).
function discVtxT(M, vi) {
  return T_AMB_JS + ROM.f_eddy * sim.beta_eddy * M.dT[vi]
                  + ROM.f_air  * sim.beta_air  * M.dTa[vi];
}
// Live min/max of the disc temperature field (radial + top/bottom gradient).
function discTempRange(M) {
  let lo = Infinity, hi = -Infinity;
  for (let vi = 0; vi < M.dT.length; vi++) {
    const T = discVtxT(M, vi);
    if (T < lo) lo = T;
    if (T > hi) hi = T;
  }
  return [lo, hi];
}
function discMeanT(M) {
  let s = 0;
  for (let vi = 0; vi < M.dT.length; vi++) s += discVtxT(M, vi);
  return s / M.dT.length;
}
// Levitation-state reset (thermal reset is resetSim()).
function resetLev() {
  lev.z = 0; lev.v = 0; lev.jit = 0; lev.jitPhase1 = 0; lev.jitPhase2 = 0;
  lev.jitLevPhase1 = 0; lev.jitLevPhase2 = 0;
}
// Raw-integrator trace (used by xval_twin.py via window.twinDebug.traceRom).
// Drives romStep/levStep directly, never substeps.
function engineTrace({I, dt, n, every}) {
  resetSim();
  // resetSim() is thermal-only BY DESIGN (matches the "Reset temperatures"
  // button and the scenario-selector -- neither should yank a currently-
  // levitating disc back down); a trace needs the explicit lev reset too for
  // reproducible/deterministic pinning (found by WP-XVAL: two traceRom calls in
  // the same page gave two different "reset" trajectories otherwise).
  resetLev();
  // I: a single number (constant current for all n steps, the original
  // WP-DEBUG shape) OR an array of n numbers (one per step, added for
  // WP-XVAL so ramp/sine/pulse/step-transition schedules can be pinned
  // too) -- Python drives the identical per-step schedule on its side.
  const Iat = Array.isArray(I) ? (i => I[i - 1]) : (() => I);
  const out = {t:[], beta:[], beta_eddy:[], beta_air:[], T_inner:[], T_outer:[],
    T_iron:[], T_air:[], T_inner_deep:[], T_outer_deep:[], z:[], v:[], jit:[]};
  const sample = () => {
    out.t.push(sim.t); out.beta.push(sim.beta);
    out.beta_eddy.push(sim.beta_eddy); out.beta_air.push(sim.beta_air);
    out.T_inner.push(sim.T.inner); out.T_outer.push(sim.T.outer);
    out.T_iron.push(sim.T.iron); out.T_air.push(sim.T.air);
    out.T_inner_deep.push(sim.T.inner_deep); out.T_outer_deep.push(sim.T.outer_deep);
    out.z.push(lev.z); out.v.push(lev.v); out.jit.push(lev.jit);
  };
  sample();
  for (let i = 1; i <= n; i++) {
    const Ii = Iat(i);
    romStep(Math.max(0, Math.min(Ii, 20.0)), dt);   // matches loop()'s I_now clamp
    levStep(Ii, dt);                                // matches loop()'s unclamped I_display
    if (i % every === 0) sample();
  }
  return out;
}
// ==== TWIN_ENGINE_END ====

// ── I(t) scenarios (same as digital_twin.py / twin_core.py SCENARIOS) ────────
// WP-SHIMMER V1 (2026-07-28, docs/archive/2026-07-28_BUG_REGISTER.md V1): `quickstart`
// is a fast 0->I ramp (PARAMS.quickstart_ramp_s, default 8s) -- same form as
// `ramp` (60s) but short enough to watch the disc bob on page load instead of
// snapping straight to its gap the way `step` does. It is the DEFAULT scenario
// below (was `step`).
const QUICKSTART_RAMP_S = PARAMS.quickstart_ramp_s || 8.0;
const SCENARIOS = {
  quickstart: (I, t) => Math.min(t / QUICKSTART_RAMP_S, 1.0) * I,
  step:  (I, t) => I,
  ramp:  (I, t) => Math.min(t / 60.0, 1.0) * I,
  sine:  (I, t) => Math.max(0, I * 0.6 + I * 0.4 * Math.sin(2 * Math.PI * t / 120)),
  pulse: (I, t) => (t % 120) < 60 ? I : 0.0,
};
let curScenario = 'quickstart';
let targetI = 5.0;   // from slider
// Non-null while Sensor mode drives the model: the latest MEASURED I_rms after
// dead-band/clamp (zero-order hold until the next sample). Scenarios are
// bypassed -- the rig, not a script, decides the current.
let sensorDriveI = null;
function getI() {
  return sensorDriveI !== null ? sensorDriveI : SCENARIOS[curScenario](targetI, sim.t);
}

// ── Color mapping ─────────────────────────────────────────────────────────────
//  T_amb → blue (HSL 240°),  PARAMS.plate_hot_display_C → red (HSL 0°). Floor
//  tracks the baked ambient (20 °C per params.yaml) instead of a stale hardcoded
//  value; ceiling now reads levitating_disc.plate_hot_display_C (WP-HTML fix,
//  was a JS literal `125`) instead of a hardcoded literal.
const T_COLOR_LO = T_AMB_JS, T_COLOR_HI = PARAMS.plate_hot_display_C;
const STRUCT = new THREE.Color(0x5a5a68);   // neutral grey for housing
function tcol(T) {  // allocating version — for UI swatches / legend only
  let t = (T - T_COLOR_LO) / (T_COLOR_HI - T_COLOR_LO);
  t = Math.max(0, Math.min(1, t));
  const c = new THREE.Color();
  c.setHSL((1 - t) * 240 / 360, 1, 0.5);
  return c;
}
// Allocation-free HSL→RGB written straight into the color buffer (hot path).
// s=1, l=0.5 fixed for the thermal ramp → simplified piecewise form.
function writeRamp(col, idx, tnorm) {
  let t = tnorm < 0 ? 0 : (tnorm > 1 ? 1 : tnorm);
  const h = (1 - t) * 240 / 360;       // 0(red)..0.667(blue)
  const q = 1.0, p = 0.0;              // l=0.5,s=1 → q=1, p=0
  const tc0 = h + 1/3, tc1 = h, tc2 = h - 1/3;
  col[idx]   = ramp1(tc0 > 1 ? tc0 - 1 : tc0);
  col[idx+1] = ramp1(tc1);
  col[idx+2] = ramp1(tc2 < 0 ? tc2 + 1 : tc2);
}
function ramp1(t) {
  if (t < 1/6) return 6 * t;
  if (t < 1/2) return 1;
  if (t < 2/3) return (2/3 - t) * 6;
  return 0;
}
const STRUCT_RGB = [160/255, 100/255, 55/255];   // wood base (plywood housing)
const METAL_RGB  = [170/255, 175/255, 185/255];  // passive white-grey metal

// Copper/varnish ramp: dark chocolate-brown lacquer at cold → IR-bright yellow at hot.
// Cold end matched to docs/real_model.png (solid dark-brown varnished mass); hot end
// matched to docs/thermal_test.png — the HIKMICRO IR image shows the windings as the
// brightest part of the whole device (yellow-white at ~60°C), so the hot colour must
// read unambiguously as "glowing", not as a slightly lighter brown.
const COPPER_COLD = [0.30, 0.14, 0.08];   // dark varnish/rosin over copper wire (cold)
const COPPER_HOT  = [1.00, 0.80, 0.22];   // IR-bright yellow-orange (hot)
function writeRampCopper(col, idx, tnorm) {
  let t = tnorm < 0 ? 0 : (tnorm > 1 ? 1 : tnorm);
  t = Math.pow(t, 0.65);   // perceptual boost: typical operating tnorm ≈0.4-0.6 on the
                           // absolute 80°C scale — pow<1 lifts that mid-range into a
                           // clearly orange band while keeping 0→0 and 1→1 fixed.
  col[idx]   = COPPER_COLD[0] + (COPPER_HOT[0] - COPPER_COLD[0]) * t;
  col[idx+1] = COPPER_COLD[1] + (COPPER_HOT[1] - COPPER_COLD[1]) * t;
  col[idx+2] = COPPER_COLD[2] + (COPPER_HOT[2] - COPPER_COLD[2]) * t;
}

// Metal/ceramic ramp: brushed silver at cold → warm orange at hot.
// Used for center core and separator ring (passive parts, ~39-45°C).
const METAL_COLD = [0.70, 0.72, 0.75];   // brushed aluminum / gray ceramic
const METAL_HOT  = [0.95, 0.62, 0.18];   // warm orange glow (45°C looks subtle)
function writeRampMetal(col, idx, tnorm) {
  let t = tnorm < 0 ? 0 : (tnorm > 1 ? 1 : tnorm);
  t = Math.sqrt(t);   // perceptual boost: passive parts peak at ~1/3 of the coil
                       // scale (steady ratio ≈0.32) — sqrt lifts that to a clearly
                       // visible warm shift while keeping 0→0 and 1→1 fixed.
  col[idx]   = METAL_COLD[0] + (METAL_HOT[0] - METAL_COLD[0]) * t;
  col[idx+1] = METAL_COLD[1] + (METAL_HOT[1] - METAL_COLD[1]) * t;
  col[idx+2] = METAL_COLD[2] + (METAL_HOT[2] - METAL_COLD[2]) * t;
}

// Eddy-current density ramp: dark purple (low |J_e|) → bright yellow (high).
// Je_vtx is pre-normalized 0..1 at build time (spatial pattern is static — a
// single linear EM solve — so no live min/max search is needed, unlike the
// thermal field which reshapes over time as β_eddy/β_air evolve separately).
const EDDY_LO = [0.18, 0.00, 0.22], EDDY_HI = [1.00, 0.95, 0.15];
function writeEddyRamp(col, idx, tnorm) {
  const t = tnorm < 0 ? 0 : (tnorm > 1 ? 1 : tnorm);
  col[idx]   = EDDY_LO[0] + (EDDY_HI[0] - EDDY_LO[0]) * t;
  col[idx+1] = EDDY_LO[1] + (EDDY_HI[1] - EDDY_LO[1]) * t;
  col[idx+2] = EDDY_LO[2] + (EDDY_HI[2] - EDDY_LO[2]) * t;
}

// Visualization mode: 'thermal' (default) | 'bfield' | 'eddy' | 'combined'.
// 'bfield'/'combined' show the B-field-line overlay; 'eddy'/'combined' switch
// the disc's vertex colours from the thermal ramp to the eddy-density ramp.
let vizMode = 'thermal';
let fieldLineOpacityPct = 0.70;
const regionKey = {1:'inner', 2:'outer', 3:'iron'};

// ── Three.js scene ────────────────────────────────────────────────────────────
const scene    = new THREE.Scene();
scene.fog      = new THREE.FogExp2(0x0f0f1e, 0.0014);
const camera   = new THREE.PerspectiveCamera(45, innerWidth/innerHeight, 0.1, 4000);
const renderer = new THREE.WebGLRenderer({antialias:true, alpha:true, preserveDrawingBuffer:true});
renderer.setPixelRatio(devicePixelRatio);
renderer.setSize(innerWidth, innerHeight);
// Tone mapping is required once an environment map is in play — otherwise PBR
// specular highlights clip straight to flat white instead of rolling off softly.
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.9;
document.body.appendChild(renderer.domElement);
// Set ONLY the positioning props. Assigning style.cssText here wiped the
// width/height that setSize() just wrote, so on a HiDPI screen (Retina, DPR=2)
// the canvas showed at its BUFFER size (2× the window) — model huge and pushed to
// the bottom-right, while the screen-space callouts stayed correctly placed.
Object.assign(renderer.domElement.style, {position: 'absolute', top: '0', left: '0', zIndex: '0'});

// Studio HDR-like environment (PMREM of a simple lit room) — gives the metallic
// coil/iron materials soft reflections instead of flat shading. Cosmetic only.
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

// Part callouts: an SVG layer for leader lines + an HTML layer for the tags
// (both screen-space, redrawn every frame from projected 3D anchors -- see
// "Part callouts" below). Sit above the canvas, below the UI panels.
const calloutSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
calloutSvg.id = 'calloutSvg';
document.body.appendChild(calloutSvg);
const calloutLayer = document.createElement('div');
calloutLayer.id = 'calloutLayer';
document.body.appendChild(calloutLayer);
const forcePanel = document.createElement('div');
forcePanel.id = 'forcePanel';
document.body.appendChild(forcePanel);
// The explanation strip is collapsed behind a small (i) button (user, 2026-10-06):
// click to read it, it folds back by itself after FORCE_INFO_MS (or on a 2nd click).
const FORCE_INFO_MS = 8000;
const forceInfoBtn = document.createElement('button');
forceInfoBtn.id = 'forceInfoBtn'; forceInfoBtn.className = 'infobtn';
forceInfoBtn.textContent = 'i';
forceInfoBtn.title = 'Why does the disc float?';
forceInfoBtn.setAttribute('aria-label', 'Why does the disc float?');
document.body.appendChild(forceInfoBtn);
let forceInfoOpen = false, forceInfoTimer = null;
forceInfoBtn.addEventListener('click', () => {
  forceInfoOpen = !forceInfoOpen;
  clearTimeout(forceInfoTimer);
  if (forceInfoOpen) forceInfoTimer = setTimeout(() => { forceInfoOpen = false; }, FORCE_INFO_MS);
});

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.08;
// OrbitControls listens ONLY on renderer.domElement, and the panels/header are
// siblings of that canvas, not descendants -- so a click or drag on a panel can
// never reach the controls; no guard is needed. The previous guard toggled
// controls.enabled on pointerenter/pointerleave, which goes stale whenever a
// panel collapses/moves under a stationary cursor (no leave event fires until
// the pointer moves), leaving the orbit disabled or enabled in the wrong place.
// Only wheel is stopped, so scrolling a panel never also zooms the model.
document.querySelectorAll('.panel, #headerBar').forEach(p =>
  p.addEventListener('wheel', e => e.stopPropagation(), {passive:true}));

// Build sub-meshes (plate levitates, base is fixed)
function buildSub(keepFn) {
  const P = [], G = [], DT = [], DTA = [], JE = [];
  for (let tri = 0; tri < regions.length; tri++) {
    if (!keepFn(regions[tri])) continue;
    for (let v = 0; v < 3; v++) {
      const i = (tri * 3 + v) * 3;
      P.push(positions[i], positions[i+1], positions[i+2]);
      DT.push(dT_ref_vtx[tri * 3 + v]);    // eddy ΔT (uniform through thickness)
      DTA.push(dT_air_vtx[tri * 3 + v]);   // hot-air ΔT (bottom-weighted)
      JE.push(Je_vtx[tri * 3 + v]);        // |J_e| normalized 0..1 (disc only, 0 on base)
    }
    G.push(regions[tri]);
  }
  return {pos: new Float32Array(P), reg: new Uint8Array(G),
          dT: new Float32Array(DT), dTa: new Float32Array(DTA), je: new Float32Array(JE)};
}
function makeMesh(sub, roughness=0.45, metalness=0.65, envInt=0.8) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(sub.pos, 3));
  g.computeVertexNormals();
  const col = new Float32Array(sub.pos.length);
  g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  const m = new THREE.Mesh(g,
    new THREE.MeshStandardMaterial({vertexColors:true, roughness, metalness,
                                    envMapIntensity:envInt, side:THREE.DoubleSide}));
  return {mesh:m, geo:g, reg:sub.reg, dT:sub.dT, dTa:sub.dTa, je:sub.je, col};
}

// discVtxT() lives in the TWIN_ENGINE block above (shared with ar_twin.html).
// Split base into passive metal (core, separator), varnished coil windings,
// wood frame and aluminium disc — each with its own PBR material.
// Matte, non-reflective materials for the body — only the aluminium disc is a
// real polished metal. Low envMapIntensity + no bloom avoids the "everything is
// glossy chrome under studio lights" look reported against docs/real_model.png.
const baseM  = makeMesh(buildSub(r => r === 3 || r === 5), 0.60, 0.30, 0.25); // core + separator — dull metal/oxide
// Coils split into TWO meshes (inner/outer) so each can carry its own emissive
// glow driven by its own temperature — MeshStandardMaterial emissive is per-material,
// not per-vertex, and the two coils run a few K apart.
const coilInnerM = makeMesh(buildSub(r => r === 1), 0.80, 0.05, 0.15); // inner coil — matte varnish/insulation
const coilOuterM = makeMesh(buildSub(r => r === 2), 0.80, 0.05, 0.15); // outer coil — matte varnish/insulation
const woodM  = makeMesh(buildSub(r => r === 4), 0.90, 0.00, 0.05);           // plywood
const plateM = makeMesh(buildSub(r => r === 0), 0.45, 0.65, 0.45);           // aluminium disc — real metal, toned down
// IR-style glow: hot windings must visibly LIGHT UP (docs/thermal_test.png) — vertex
// colours alone are multiplied by scene light, so a matte material stays dull no
// matter how bright the ramp colour is. Emissive adds light-independent radiance.
const COIL_GLOW_RGB = new THREE.Color(1.0, 0.45, 0.10);   // ember orange
coilInnerM.mesh.material.emissive.copy(COIL_GLOW_RGB);
coilOuterM.mesh.material.emissive.copy(COIL_GLOW_RGB);
function updateCoilGlow() {
  const dTh = T_COIL_HOT - T_AMB_JS;
  const gi = Math.max(0, Math.min(1, (sim.T.inner - T_AMB_JS) / dTh));
  const go = Math.max(0, Math.min(1, (sim.T.outer - T_AMB_JS) / dTh));
  const mi = coilInnerM.mesh.material, mo = coilOuterM.mesh.material;
  mi.emissiveIntensity += (0.9 * Math.pow(gi, 1.4) - mi.emissiveIntensity) * colorEaseK;
  mo.emissiveIntensity += (0.9 * Math.pow(go, 1.4) - mo.emissiveIntensity) * colorEaseK;
}

// Live min/max of the disc temperature field (radial + top/bottom gradient).
// Recomputed each frame because the field SHAPE changes over time (β_eddy vs β_air).
// Used both for the disc's relative colour scale and for telemetry.
let discTlo = T_AMB_JS, discThi = T_AMB_JS;
function updateDiscRange() {
  [discTlo, discThi] = discTempRange(plateM);
}

// Bounding box from full model
const bb = new THREE.Box3();
{const t = new THREE.BufferGeometry();
 t.setAttribute('position', new THREE.BufferAttribute(positions, 3));
 t.computeBoundingBox(); bb.copy(t.boundingBox);}
const ctr  = new THREE.Vector3(); bb.getCenter(ctr);
const size = bb.getSize(new THREE.Vector3()).length();
const modelH  = bb.max.y - bb.min.y;

function levLiftY() {
  return (lev.z + lev.jit) * Z_GAP_EXAG;   // spring-mass state + sub-liftoff shimmer; disc sits on coil top at lev.z=0
}

baseM.mesh.position.set(-ctr.x, -ctr.y, -ctr.z);
coilInnerM.mesh.position.set(-ctr.x, -ctr.y, -ctr.z);
coilOuterM.mesh.position.set(-ctr.x, -ctr.y, -ctr.z);
woodM.mesh.position.set(-ctr.x, -ctr.y, -ctr.z);
plateM.mesh.position.set(-ctr.x, -ctr.y + levLiftY(), -ctr.z);
scene.add(baseM.mesh, coilInnerM.mesh, coilOuterM.mesh, woodM.mesh, plateM.mesh);

// Field-line hints (blue arcs bridging coil rim → plate)
const rRim = Math.min(size * 0.18, 90);
const gapBot = bb.max.y - ctr.y - modelH * 0.12;
const gapTop = bb.max.y - ctr.y;
const flPts = [];
for (let a = 0; a < 12; a++) {
  const th = a / 12 * Math.PI * 2, x = Math.cos(th)*rRim, z = Math.sin(th)*rRim;
  flPts.push(x, gapBot, z,  x, gapTop + modelH * 0.10, z);
}
const flGeo = new THREE.BufferGeometry();
flGeo.setAttribute('position', new THREE.Float32BufferAttribute(flPts, 3));
scene.add(new THREE.LineSegments(flGeo,
  new THREE.LineBasicMaterial({color:0x4facfe, transparent:true, opacity:0.25})));

// ── EM "B Field" overlay — real field lines, baked from contours of ψ=r·A_φ ──
// (FIELD_LINES, see build_twin_html_fem.py compute_em_field_lines). Each 2D
// meridian-plane line is revolved into N_THETA_FIELD copies around the
// symmetry axis (CAD Z-up r,z → same rotation as `positions`: X=r·cosθ,
// Y=z, Z=−r·sinθ). Geometry is STATIC per disc radius (linear problem — shape
// doesn't change with I), but a different disc radius genuinely reshapes the
// eddy/flux distribution, so buildFieldLines() is re-run (not just baked once)
// whenever selectPlateVariant() swaps discs -- see there.
const N_THETA_FIELD = 24;  // intentionally hardcoded (cosmetic render density, not physics)
const fieldLineGroup = new THREE.Group();
fieldLineGroup.position.set(-ctr.x, -ctr.y, -ctr.z);   // same (un-lifted) frame as baseM
fieldLineGroup.visible = false;
scene.add(fieldLineGroup);

let flLightTheme = false;   // set by the theme toggle; light bg needs dark lines
function flColor(t, out) {
  t = t < 0 ? 0 : (t > 1 ? 1 : t);
  if (flLightTheme) {        // light theme: mid blue(0) -> royal(0.5) -> deep navy(1)
    if (t < 0.5) { const k = t / 0.5; out.setRGB(0.42 - 0.26 * k, 0.58 - 0.26 * k, 0.90 - 0.08 * k); }
    else         { const k = (t - 0.5) / 0.5; out.setRGB(0.16 - 0.12 * k, 0.32 - 0.20 * k, 0.82 - 0.36 * k); }
    return;
  }
  // dark theme: blue(0) -> cyan(0.5) -> white(1)
  if (t < 0.5) { const k = t / 0.5; out.setRGB(0.10 * (1 - k), 0.30 + 0.70 * k, 1.0); }
  else         { const k = (t - 0.5) / 0.5; out.setRGB(k, 1.0, 1.0); }
}
const fieldLineMats = [];   // {mat, line, amp, rankFrac} — amp = this line's average |B|/B_max
const _flCol = new THREE.Color();
const FL_GAP_BASE = size * 0.012;   // dash gap at I ≤ I_em_ref (shrinks above → denser flow)
// 2026-09-29: EM frame -> display frame. FIELD_LINES z is measured in the EM solve's
// frame (coil top at coil_top_em_mm, disc bottom gap_em_mm above it); the display
// mesh has its coil top at coil_top_disp_mm with the disc resting on it and lifted
// at runtime by levLiftY(). Without this map every line sat ~61 mm too low (below
// the housing). Above the coil top the line is also STRETCHED with the live lift:
// the gap part scales with the gap, everything above the disc moves with the disc
// -- so a rising disc visibly pulls the flux "cushion" open. Display-only mapping;
// the line SHAPES are still the baked FEM contours.
const FV = PARAMS.field_view;
const flSources = [];   // per baked 2D line: {r, z, zd, copies:[THREE.Line x N_THETA_FIELD]}
let flLiftY = 0;
function flDisplayZ(z, liftY) {
  const zr = z - FV.coil_top_em_mm;
  let zd;
  if (zr <= 0) zd = zr;                                              // coils / iron: fixed
  else if (zr <= FV.gap_em_mm) zd = zr * (liftY / FV.gap_em_mm);     // gap: stretches
  else if (zr <= FV.gap_em_mm + FV.t_em_mm)                          // inside the disc
    zd = liftY + (zr - FV.gap_em_mm) * (FV.t_disp_mm / FV.t_em_mm);
  else zd = liftY + FV.t_disp_mm + (zr - FV.gap_em_mm - FV.t_em_mm); // above: rides along
  return zd + FV.coil_top_disp_mm;
}
function layoutFieldLines(liftY) {
  flLiftY = liftY;
  for (const src of flSources) {
    const n = src.r.length;
    for (let i = 0; i < n; i++) src.zd[i] = flDisplayZ(src.z[i], liftY);
    for (const line of src.copies) {
      const pa = line.geometry.attributes.position, arr = pa.array;
      for (let i = 0; i < n; i++) arr[i*3+1] = src.zd[i];
      pa.needsUpdate = true;
      line.geometry.computeBoundingSphere();
      line.computeLineDistances();
    }
  }
}
function applyFieldLineOpacity() {
  for (const o of fieldLineMats) o.mat.opacity = fieldLineOpacityPct * (0.15 + 0.85 * o.amp);
}
let flCurrentData = null;   // last baked line set (theme toggle recolours it)
function buildFieldLines(linesData) {
  flCurrentData = linesData;
  // Tear down the previous disc's field lines (dispose GPU buffers) before
  // rebuilding from linesData -- mutate fieldLineMats IN PLACE (length=0, not
  // reassignment) since the render loop and applyFieldLineOpacity() close
  // over this same array reference.
  for (const o of fieldLineMats) { o.line.geometry.dispose(); o.mat.dispose(); }
  fieldLineGroup.clear();
  fieldLineMats.length = 0;
  flSources.length = 0;
  for (const fl of linesData) {
    const n = fl.r.length;
    let ampSum = 0;
    for (let i = 0; i < n; i++) ampSum += fl.amp[i];
    const avgAmp = ampSum / n;
    const src = {r: Float32Array.from(fl.r), z: Float32Array.from(fl.z),
                 zd: new Float32Array(n), copies: []};
    flSources.push(src);
    for (let t = 0; t < N_THETA_FIELD; t++) {
      const theta = t / N_THETA_FIELD * Math.PI * 2;
      const ct = Math.cos(theta), st = Math.sin(theta);
      const pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
      for (let i = 0; i < n; i++) {
        const r = fl.r[i], z = flDisplayZ(fl.z[i], flLiftY);
        pos[i*3] = r * ct; pos[i*3+1] = z; pos[i*3+2] = -r * st;
        flColor(fl.amp[i], _flCol);
        col[i*3] = _flCol.r; col[i*3+1] = _flCol.g; col[i*3+2] = _flCol.b;
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
      // depthTest:false — flux loops physically thread through the solid iron
      // core / coil windings (that's the point of a field-line diagram), which
      // would otherwise occlude most of each loop. Render as an X-ray overlay
      // on top of the opaque base/plate meshes instead.
      const mat = new THREE.LineDashedMaterial({
        vertexColors: true, transparent: true, opacity: fieldLineOpacityPct,
        depthTest: false, dashSize: size * 0.018, gapSize: size * 0.012,
      });
      const line = new THREE.Line(geo, mat);
      line.renderOrder = 10;
      line.computeLineDistances();
      fieldLineGroup.add(line);
      fieldLineMats.push({mat, line, amp: avgAmp});
      src.copies.push(line);
    }
  }
  // Rank lines by field strength so line DENSITY responds to I, not just
  // brightness: at low I only the strongest flux tubes (hugging the coils)
  // remain visible, full baked set at I_em_ref. rankFrac ∈ [0,1): 0=strongest.
  const sorted = [...fieldLineMats].sort((a, b) => b.amp - a.amp);
  sorted.forEach((o, i) => { o.rankFrac = i / sorted.length; });
  applyFieldLineOpacity();
}
buildFieldLines(FIELD_LINES);
function updateVizVisibility() {
  fieldLineGroup.visible = (vizMode === 'bfield' || vizMode === 'combined');
}
updateVizVisibility();
const FIELD_LINE_FLOW_SPEED = size * 0.05;   // world units/s — dash "flow" pulse at I_em_ref
let flFlowPhase = 0;   // accumulated dash offset — advances with I so speed changes don't jump

// Frame the levitating disc + coils in the clear lower area (UI panels cover the
// top). Aim above the device centre so the whole assembly drops into the lower
// half of the viewport, and pull back enough to keep the disc fully visible.
// Frame the camera on where the disc will SETTLE at the initial current (the live
// spring state starts at z=0, so use the equilibrium gap, not levLiftY()).
// 2026-09-29: open with the WHOLE device small and centred in the free area
// between the two UI panels, then let the user zoom freely. Fit the device's
// bounding sphere (base + disc at its equilibrium lift for the initial current)
// into FIT_FILL of the free viewport, from the same 3/4 view direction as before.
const FIT_FILL = 0.50;                       // fraction of the free viewport the device spans
const FIT_DIR  = new THREE.Vector3(0.70, 0.42, 0.70).normalize();
const fitCenter = new THREE.Vector3();
let fitRadius = size * 0.5, fitDist = size;
function freeViewportWidth() {
  // Desktop layout: panels float over the canvas on both sides -> only the gap
  // between them is usable. Mobile (<=760px): panels stack below the canvas.
  if (innerWidth <= 760) return innerWidth;
  const l = document.getElementById('uiLeft'), r = document.getElementById('uiRight');
  const lw = l ? l.getBoundingClientRect().right : 0;
  const rw = r ? innerWidth - r.getBoundingClientRect().left : 0;
  return Math.max(260, innerWidth - 2 * Math.max(lw, rw));   // symmetric -> stays centred
}
function fitView() {
  const lift = levGapEqMm(targetI) * Z_GAP_EXAG;
  const yLo = bb.min.y - ctr.y, yHi = bb.max.y - ctr.y + lift;
  fitCenter.set(0, 0.5 * (yLo + yHi), 0);
  // Radius of the device's horizontal footprint (axisymmetric/octagonal -> use
  // max |x|,|z|, not the box corner) combined with the half-height.
  const rFoot = Math.max(bb.max.x - ctr.x, ctr.x - bb.min.x, bb.max.z - ctr.z, ctr.z - bb.min.z);
  fitRadius = Math.hypot(rFoot, 0.5 * (yHi - yLo));
  const tanV = Math.tan(camera.fov * Math.PI / 360);
  const tanH = tanV * freeViewportWidth() / innerHeight;
  fitDist = fitRadius / (FIT_FILL * Math.min(tanV, tanH));
  camera.position.copy(fitCenter).addScaledVector(FIT_DIR, fitDist);
  controls.target.copy(fitCenter);
  controls.minDistance = fitRadius * 0.35;   // close-up on a single part
  controls.maxDistance = fitDist * 3.0;
  controls.update();
}
controls.zoomToCursor = true;                // zoom toward the part under the cursor (three r153+)
controls.zoomSpeed = 0.9;
fitView();
renderer.domElement.addEventListener('dblclick', fitView);
document.getElementById('btnFitView').onclick = fitView;
// Fog density follows the camera distance, so zooming out never fogs the device away.
const FOG_BASE = scene.fog.density, FOG_REF_DIST = size * 1.08;
// Exposed for headless (Playwright) verification — lets tests reposition the view.
window.twinDebug = {camera, controls, size, plateM, coilInnerM, coilOuterM,
  coilM: coilInnerM,   // back-compat alias for existing headless tests
  ctr, scene, get lev() { return lev; }, get sim() { return sim; },
  levStep, levGapEqMm, levZeta, get I_LEV_MIN() { return I_LEV_MIN; },   // WP-A: direct physics hooks for headless tests
  get ROM() { return ROM; }, get activePlateIdx() { return activePlateIdx; },
  selectPlateVariant,   // disc-radius compare mode (2026-07-03): headless hooks
  fieldLineGroup, get fieldLineMats() { return fieldLineMats; },   // per-variant B-field verification
  get PARAMS() { return PARAMS; }, get T_AMB_JS() { return T_AMB_JS; },
  setAmbient: (...a) => setAmbient(...a), get sensor() { return sensorDebug; },
  steadyState: (I) => { ssCache.at = 0; return engineSteadyState(I); },   // engine fixed point behind T_ss / → (no throttle)
  // Headless Python<->JS numeric cross-check (WP-DEBUG/WP-XVAL): drives
  // romStep/levStep directly, bypassing the render loop (so this never
  // substeps -- loop()'s nSub chopping, :2718, is a separate concern from the
  // raw integrators pinned here). Reaches romStep/resetSim/paused by closure
  // only -- they stay module-scoped, not separately exposed on window.
  traceRom({I, dt, n, every}) {
    paused = true;
    return engineTrace({I, dt, n, every});   // pure engine loop, see TWIN_ENGINE block
  }};   // WP-HTML: module-scoped consts aren't on
                                       // window in a module script -- expose for tests
scene.add(new THREE.AmbientLight(0xffffff, 0.5));
const dl = new THREE.DirectionalLight(0xffffff, 0.7);
dl.position.set(1, 1.5, 0.8); scene.add(dl);
const gridHelper = new THREE.GridHelper(size*2, 40, 0x333344, 0x1a1a28);
scene.add(gridHelper);

// ── Part callouts (2026-09-29) ────────────────────────────────────────────────
// Replaces the floating CSS2D labels. Every part has a 3D anchor ON the part that
// is re-placed each frame on the side of the device FACING the camera (camera
// azimuth + a fixed per-part offset), so orbiting never hides it behind the model.
// Its tag (name · live value / role) sits in a column just left or right of the
// device's screen footprint, joined by a leader line; parts covered by the disc
// (core, inner coil, separator ring) get a dashed leader so the eye still finds
// them. Pure display -- reads sim/lev state, never writes it.
function regionStats(regIdx) {
  let rMin = Infinity, rMax = 0, yTop = -Infinity;
  for (let tri = 0; tri < regions.length; tri++) {
    if (regions[tri] !== regIdx) continue;
    for (let v = 0; v < 3; v++) {
      const i = (tri * 3 + v) * 3;
      const r = Math.hypot(positions[i] - ctr.x, positions[i+2] - ctr.z);
      if (r < rMin) rMin = r;
      if (r > rMax) rMax = r;
      if (positions[i+1] > yTop) yTop = positions[i+1];
    }
  }
  return {rMin, rMax, yTop: yTop - ctr.y};
}
const CALLOUTS = [
  {key: 'plate', reg: 0, name: 'Aluminium Plate', rFrac: 0.62, az: -34, side: -1},
  {key: 'sep',   reg: 5, name: 'Separator Ring',  rFrac: 0.50, az: -62, side: -1, cls: 'iron',
   role: 'iron · flux return path'},
  {key: 'core',  reg: 3, name: 'Center Core',     rFrac: 0.00, az:   0, side: -1, cls: 'iron',
   role: 'iron · guides flux up the axis'},
  {key: 'inner', reg: 1, name: `Inner Coil · ${PARAMS.coils_inner_turns} turns`, rFrac: 0.50, az: 22, side: 1},
  {key: 'outer', reg: 2, name: `Outer Coil · ${PARAMS.coils_outer_turns} turns`, rFrac: 0.50, az: 50, side: 1},
];
const SVG_NS = 'http://www.w3.org/2000/svg';
for (const c of CALLOUTS) {
  if (c.reg !== 0) c.st = regionStats(c.reg);
  c.el = document.createElement('div');
  c.el.className = 'callout' + (c.cls ? ' ' + c.cls : '');
  c.el.innerHTML = `<span class="nm">${c.name}</span><span class="lv"></span><span class="rl">${c.role || ''}</span>`;
  c.lvEl = c.el.querySelector('.lv'); c.rlEl = c.el.querySelector('.rl');
  calloutLayer.appendChild(c.el);
  c.g = document.createElementNS(SVG_NS, 'g');
  if (c.cls) c.g.setAttribute('class', c.cls);
  c.path = document.createElementNS(SVG_NS, 'polyline'); c.path.setAttribute('class', 'ld');
  c.dot = document.createElementNS(SVG_NS, 'circle');    c.dot.setAttribute('class', 'dot'); c.dot.setAttribute('r', '3');
  c.g.append(c.path, c.dot); calloutSvg.appendChild(c.g);
  c.anchor = new THREE.Vector3(); c.hidden = false; c.w = 0; c.h = 0;
}
function plateTopLocalY() { return FV.coil_top_disp_mm + FV.t_disp_mm - ctr.y; }
function placeAnchor(c, phi, liftY) {
  let r, y;
  if (c.reg === 0) {
    r = c.rFrac * PLATE_VARIANTS[activePlateIdx].radius_mm;
    y = plateTopLocalY() + liftY;
  } else {
    r = c.st.rMin + c.rFrac * (c.st.rMax - c.st.rMin);
    y = c.st.yTop;
  }
  const a = phi + c.az * Math.PI / 180;
  c.anchor.set(r * Math.sin(a), y, r * Math.cos(a));
}

// Free-body arrows on the disc (B field / Both modes): F_mag up, m·g down.
const forceGroup = new THREE.Group();
forceGroup.visible = false;
scene.add(forceGroup);
function makeForceArrow(color) {
  const a = new THREE.ArrowHelper(new THREE.Vector3(0, 1, 0), new THREE.Vector3(), 1, color);
  for (const m of [a.line.material, a.cone.material]) { m.depthTest = false; m.transparent = true; }
  a.line.renderOrder = a.cone.renderOrder = 20;
  forceGroup.add(a);
  return a;
}
const arrUp = makeForceArrow(0x7fe7ff), arrDn = makeForceArrow(0xffb070);
const FORCE_ARROW_COL = {dark: [0x7fe7ff, 0xffb070], light: [0x00609a, 0x5b3aa8]};
const F_ARROW_L0 = size * 0.09;   // on-screen length of m·g; F_mag scales against it
const forceTags = {up: null, dn: null};
for (const k of ['up', 'dn']) {
  const el = document.createElement('div');
  el.className = 'callout force ' + k;
  calloutLayer.appendChild(el);
  forceTags[k] = el;
}
// Lift force of the SAME levitation law the disc dynamics use: z_eq(I) =
// z5 + 2·z0·ln(I/5) is exactly where F(I,z) = m·g·(I/5)²·exp(−(z−z5)/z0)
// equals m·g. Display only (levStep() is untouched).
function liftForceN(I, zMm) {
  const mg = PLATE_VARIANTS[activePlateIdx].F_grav_N;
  if (!(I > 0)) return 0;
  return mg * (I / 5.0) ** 2 * Math.exp(-(zMm - Z_GAP_5A_MM) / Z_DECAY_MM);
}

const _raycaster = new THREE.Raycaster();
const _v = new THREE.Vector3(), _dir = new THREE.Vector3();
let calloutTextTimer = 0, calloutOccTimer = 0;
function toScreen(v3, out) {
  _v.copy(v3).project(camera);
  out.x = (_v.x + 1) * 0.5 * innerWidth;
  out.y = (1 - _v.y) * 0.5 * innerHeight;
  out.behind = _v.z > 1;
  return out;
}
function updateCallouts(dt) {
  const liftY = levLiftY();
  const I = getI();
  _dir.subVectors(camera.position, controls.target);
  const phi = Math.atan2(_dir.x, _dir.z);
  for (const c of CALLOUTS) placeAnchor(c, phi, liftY);

  // Live text, ~5 Hz (numbers flicker if rewritten every frame).
  calloutTextTimer -= dt;
  if (calloutTextTimer <= 0) {
    calloutTextTimer = 0.2;
    const s2 = (I / ROM.I_ref) ** 2;
    for (const c of CALLOUTS) {
      if (c.key === 'plate') {
        c.lvEl.textContent = plateTmax().toFixed(1) + ' °C';
        c.rlEl.textContent = lev.z > 0.05
          ? `levitating ${lev.z.toFixed(1)} mm · eddy-current heating`
          : 'resting on the coils · eddy-current heating';
      } else if (c.key === 'inner') {
        c.lvEl.textContent = sim.T.inner.toFixed(1) + ' °C';
        c.rlEl.textContent = `${(LUMPED.nodes.inner.P_ref * s2).toFixed(0)} W · main field source`;
      } else if (c.key === 'outer') {
        c.lvEl.textContent = sim.T.outer.toFixed(1) + ' °C';
        c.rlEl.textContent = `${(LUMPED.nodes.outer.P_ref * s2).toFixed(0)} W · counter-wound, shapes the field`;
      } else {
        c.lvEl.textContent = sim.T.iron.toFixed(1) + ' °C';
      }
      c.w = c.el.offsetWidth; c.h = c.el.offsetHeight;
    }
  }

  // Occlusion (~7 Hz): is something in front of the anchor? -> dashed leader.
  calloutOccTimer -= dt;
  if (calloutOccTimer <= 0) {
    calloutOccTimer = 0.15;
    const meshes = [plateM.mesh, baseM.mesh, coilInnerM.mesh, coilOuterM.mesh, woodM.mesh];
    for (const c of CALLOUTS) {
      _dir.subVectors(c.anchor, camera.position);
      const d = _dir.length();
      _raycaster.set(camera.position, _dir.normalize());
      _raycaster.far = d + 1;
      const hit = _raycaster.intersectObjects(meshes, false)[0];
      c.hidden = !!hit && hit.distance < d - 1.5;
      c.el.classList.toggle('hid', c.hidden);
      c.path.classList.toggle('hid', c.hidden);
    }
  }

  // Device footprint on screen -> tag columns just outside it (inside the free area).
  let minX = Infinity, maxX = -Infinity;
  const p = {};
  for (let k = 0; k < 8; k++) {
    _v.set(k & 1 ? bb.max.x : bb.min.x, (k & 2 ? bb.max.y + liftY : bb.min.y), k & 4 ? bb.max.z : bb.min.z).sub(ctr);
    toScreen(_v, p);
    minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
  }
  const l = document.getElementById('uiLeft'), r = document.getElementById('uiRight');
  const loX = innerWidth > 760 && l ? l.getBoundingClientRect().right + 8 : 8;
  const hiX = innerWidth > 760 && r ? r.getBoundingClientRect().left - 8 : innerWidth - 8;
  const cols = {'-1': [], '1': []};
  for (const c of CALLOUTS) {
    toScreen(c.anchor, p);
    c.ax = p.x; c.ay = p.y; c.off = p.behind;
    cols[c.side].push(c);
  }
  for (const side of [-1, 1]) {
    const list = cols[side].sort((a, b) => a.ay - b.ay);
    let yNext = 58;
    for (const c of list) {
      const x = side < 0 ? Math.max(loX, minX - 22 - c.w) : Math.min(hiX - c.w, maxX + 22);
      const y = Math.max(yNext, c.ay - c.h - 10);
      yNext = y + c.h + 6;
      c.el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
      const ex = side < 0 ? x + c.w : x, ey = y + c.h * 0.5;
      const kx = ex + (side < 0 ? 12 : -12);
      c.path.setAttribute('points', `${c.ax.toFixed(1)},${c.ay.toFixed(1)} ${kx.toFixed(1)},${ey.toFixed(1)} ${ex.toFixed(1)},${ey.toFixed(1)}`);
      c.dot.setAttribute('cx', c.ax.toFixed(1)); c.dot.setAttribute('cy', c.ay.toFixed(1));
      const vis = !c.off;
      c.el.style.visibility = vis ? 'visible' : 'hidden';
      c.g.style.visibility  = vis ? 'visible' : 'hidden';
    }
  }

  // Forces (B field / Both only).
  const showF = fieldLineGroup.visible;
  forceGroup.visible = showF;
  forceTags.up.style.display = forceTags.dn.style.display = showF ? 'block' : 'none';
  forceInfoBtn.style.display = showF ? 'flex' : 'none';
  forceInfoBtn.classList.toggle('on', showF && forceInfoOpen);
  forcePanel.style.display = (showF && forceInfoOpen) ? 'block' : 'none';
  if (!showF) return;
  const mg = PLATE_VARIANTS[activePlateIdx].F_grav_N;
  const F = liftForceN(I, lev.z);
  const yTop = plateTopLocalY() + liftY, yBot = yTop - FV.t_disp_mm;
  const Lup = Math.max(0.001, Math.min(3, F / mg) * F_ARROW_L0);
  arrUp.position.set(0, yTop, 0);
  arrUp.setLength(Lup, Math.min(Lup * 0.35, size * 0.022), size * 0.014);
  arrUp.visible = F > 0.005;
  arrDn.position.set(0, yBot, 0);
  arrDn.setDirection(new THREE.Vector3(0, -1, 0));
  arrDn.setLength(F_ARROW_L0, size * 0.022, size * 0.014);
  const place = (el, v3) => {
    toScreen(v3, p);
    el.style.transform = `translate(${(p.x + 10).toFixed(1)}px, ${(p.y - 9).toFixed(1)}px)`;
  };
  if (calloutTextTimer >= 0.19) {   // same ~5 Hz text cadence as the part tags
    forceTags.up.textContent = `F_mag ${F.toFixed(2)} N`;
    forceTags.dn.textContent = `m·g ${mg.toFixed(2)} N`;
    let st;
    if (I < 0.05) st = 'no current → no field → disc rests';
    else if (lev.z <= 0.01 && F < mg) st = `F_mag < m·g → rests on the coils (lift-off at ${I_LEV_MIN.toFixed(2)} A)`;
    else if (F > mg * 1.02) st = 'F_mag > m·g → disc rises';
    else if (F < mg * 0.98) st = 'F_mag < m·g → disc sinks';
    else st = `balanced → hovers at ${lev.z.toFixed(1)} mm`;
    const B = ROM.B_max * I / ROM.I_em_ref;
    forcePanel.innerHTML =
      `<b>Why does the disc float?</b> I = ${I.toFixed(2)} A drives B ∝ I (${B.toFixed(3)} T at the disc). ` +
      `The AC field induces eddy currents in the disc that oppose it, so coils and disc repel: ` +
      `<span class="up">F_mag ∝ I²·e<sup>−z/z₀</sup></span>. More current → stronger push → the disc climbs until ` +
      `the push has decayed to its weight.<br>` +
      `<span class="up">F_mag = ${F.toFixed(2)} N ↑</span> · <span class="dn">m·g = ${mg.toFixed(2)} N ↓</span>` +
      `<span class="st">${st}</span>`;
  }
  place(forceTags.up, _dir.set(0, yTop + Lup, 0).clone());
  place(forceTags.dn, _dir.set(0, yBot - F_ARROW_L0, 0).clone());
}

// ── Disc-radius compare mode (2026-07-03) ────────────────────────────────────
// User-requested feature: swap the live disc between every aluminium/3mm
// radius in plate_library (see plate_variant_radii_mm() in the Python
// builder -- SSOT, not a hardcoded count here) to visually compare how
// fast/how much each one heats up, without rebuilding the HTML. All variants share the SAME mesh
// topology (n_theta/meridian is fixed in params.yaml, only the radius scales),
// so swapping is just: replace plateM's position/dT/dTa/je buffers in place,
// swap in that radius's own ROM + levitation constants (a wider/narrower disc
// genuinely changes the eddy loss and lift force, not just a display scale —
// see CLAUDE.md WP-C), and reset the sim so the new disc's heat-up curve is
// easy to read from a clean T_amb baseline (matches the plate-selector
// convention already used in digital_twin.py).
const PLATE_VARIANTS = PARAMS.plate_variants;
let activePlateIdx = PARAMS.active_plate_idx;
function decodeVariantPositions(v) {
  const pos = new Float32Array(b64Buf(v.pos_b64));
  for (let i = 0; i < pos.length; i += 3) {   // CAD Z-up -> Three.js Y-up
    const y = pos[i+1], z = pos[i+2];
    pos[i+1] = z; pos[i+2] = -y;
  }
  return pos;
}
function selectPlateVariant(idx) {
  if (idx === activePlateIdx || !PLATE_VARIANTS[idx]) return;
  const v = PLATE_VARIANTS[idx];
  activePlateIdx = idx;

  const pos = decodeVariantPositions(v);
  // Same topology across radii (fixed n_theta/meridian) -> identical vertex
  // count, so the existing BufferAttribute can be updated in place.
  plateM.geo.attributes.position.array.set(pos);
  plateM.geo.attributes.position.needsUpdate = true;
  plateM.geo.computeBoundingSphere();
  plateM.geo.computeVertexNormals();
  plateM.dT  = new Float32Array(b64Buf(v.dT_b64));
  plateM.dTa = new Float32Array(b64Buf(v.dtair_b64));
  plateM.je  = new Float32Array(b64Buf(v.je_b64));

  // ROM is referenced by object identity everywhere (romStep, plateTss,
  // telemetry) -- mutate its fields in place rather than rebinding the const.
  Object.assign(ROM, v.rom);
  applyLevParams(v.lev, v.radius_mm);

  // Field-line SHAPE also changes per disc radius (different eddy/flux
  // distribution, not just a scale factor) -- rebuild the B-field overlay
  // geometry from this variant's own contours, not just its ROM scalars.
  buildFieldLines(v.field_lines);

  resetSim();
  resetLev();

  // (The plate callout anchor reads the active variant's radius every frame.)
  flLiftY = -1;   // force a field-line re-layout for the new disc on the next frame

  // B_max_iron/saturation badge must repaint too -- v.rom now carries this
  // variant's OWN EM peaks (WP-HTML fix), not the previously-active disc's.
  updateEmBadges();
}

// ── Heat particles — faint glowing motes rising from the coils, shown only
// once a body is noticeably above ambient (>2 K). Purely decorative; does not
// feed back into any physics quantity.
function makeGlowDot() {
  const c = document.createElement('canvas'); c.width = c.height = 32;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(16, 16, 0, 16, 16, 16);
  grad.addColorStop(0, 'rgba(255,200,120,1)');
  grad.addColorStop(1, 'rgba(255,120,40,0)');
  g.fillStyle = grad; g.fillRect(0, 0, 32, 32);
  return new THREE.CanvasTexture(c);
}
const N_HEAT_PARTICLES = 70;  // intentionally hardcoded (cosmetic particle count, not physics)
const particlePos  = new Float32Array(N_HEAT_PARTICLES * 3);
const particleSeed = new Float32Array(N_HEAT_PARTICLES);
function resetParticle(i) {
  const ang = Math.random() * Math.PI * 2, rad = rRim * (0.25 + Math.random()*0.95);
  particlePos[i*3]   = Math.cos(ang) * rad;
  particlePos[i*3+1] = gapBot + Math.random() * (gapTop - gapBot) * 0.4;
  particlePos[i*3+2] = Math.sin(ang) * rad;
}
for (let i = 0; i < N_HEAT_PARTICLES; i++) { resetParticle(i); particleSeed[i] = Math.random(); }
const particleGeo = new THREE.BufferGeometry();
particleGeo.setAttribute('position', new THREE.BufferAttribute(particlePos, 3));
const particles = new THREE.Points(particleGeo, new THREE.PointsMaterial({
  map: makeGlowDot(), color: 0xffaa55, size: size*0.012, transparent: true,
  opacity: 0.6, blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true,
}));
particles.position.set(-ctr.x, -ctr.y, -ctr.z);
particles.visible = false;
scene.add(particles);
const particleTopY = gapTop + modelH * 0.10;
function updateHeatParticles(dt) {
  // Compare against T_AMB_JS (the shared display baseline used by every other
  // "is this hot" decision in this file), not ROM.T_amb (the physics ambient,
  // 20°C per params.yaml, which can lag/mismatch T_AMB_JS) -- avoids a paradox
  // where particles render "hot" off cold coils right after page load.
  const hot = Math.max(sim.T.inner, sim.T.outer, sim.T.iron) - T_AMB_JS > 2.0;
  particles.visible = hot;
  if (!hot) return;
  const arr = particleGeo.attributes.position.array;
  for (let i = 0; i < N_HEAT_PARTICLES; i++) {
    arr[i*3+1] += dt * (size*0.015 + particleSeed[i]*size*0.02);
    if (arr[i*3+1] > particleTopY) resetParticle(i);
  }
  particleGeo.attributes.position.needsUpdate = true;
}

// ── Paint vertex colors (allocation-free hot path) ───────────────────────────
let TRANGE = T_COLOR_HI - T_COLOR_LO;
// Coil colour-ramp ceiling — ABSOLUTE scale: 0 = T_amb, 1 = T_COIL_HOT.
// Anchored to the real IR data (session 1, 2026-06-23): inner coil hit 79°C @6.175A (run B, not steady),
// the hottest reading ever measured. Colour only changes when the actual
// temperature changes — NOT when I changes (a prior *relative* scale divided by
// I-dependent T_ss(I), so bumping I made the coil "cool" instantly and steady
// state always painted full-hot regardless of I — both wrong).
// (Module scope: shared by paintMesh and updateCoilGlow.)
// WP-D (2026-07-02): baked from params.yaml lumped_thermal.coil_hot_display_C
// instead of hardcoded — was a JS literal `T_COIL_HOT = 80.0`.
const T_COIL_HOT = LUMPED.T_coil_hot_display_C;   // [°C]
// Disc colour-scale mode: 'auto' keeps the original behaviour (stretch only once
// the in-plate spread is physically meaningful), 'absolute'/'relative' force one
// or the other — wired to the "Scale: …" button in the telemetry panel.
let colorScaleMode = 'auto';
// Smooth colour transitions (2026-09-29, user request). Two things used to jump:
// Auto flipped the disc from the absolute to the relative scale the instant the
// in-disc spread crossed 0.3 K (a uniformly blue disc became a full rainbow in one
// frame), and the relative window was re-fit to min/max every frame. Now (1) the
// disc colour WINDOW eases toward a target that blends absolute↔relative
// continuously and never gets narrower than DISC_MIN_SPAN_K, and (2) every vertex
// colour and the coil glow ease toward their targets (τ = COLOR_TAU_S, wall time).
// Display only -- temperatures themselves are untouched.
const COLOR_TAU_S = 0.35, WINDOW_TAU_S = 1.2, DISC_MIN_SPAN_K = 4.0;
let dispLo = T_COLOR_LO, dispHi = T_COLOR_HI, colorEaseK = 1, colorFirst = true;
function smoothstep(a, b, x) { const t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); }
function discWindowTarget() {
  const span = discThi - discTlo;
  const mid = 0.5 * (discTlo + discThi), half = 0.5 * Math.max(DISC_MIN_SPAN_K, span);
  const w = colorScaleMode === 'relative' ? 1 : colorScaleMode === 'absolute' ? 0
          : smoothstep(0.3, 3.0, span);
  return [T_COLOR_LO + (mid - half - T_COLOR_LO) * w, T_COLOR_HI + (mid + half - T_COLOR_HI) * w];
}
function updateColorEasing(wall_dt) {
  const [tLo, tHi] = discWindowTarget();
  if (colorFirst) { dispLo = tLo; dispHi = tHi; colorEaseK = 1; colorFirst = false; return; }
  const kw = 1 - Math.exp(-wall_dt / WINDOW_TAU_S);
  dispLo += (tLo - dispLo) * kw; dispHi += (tHi - dispHi) * kw;
  colorEaseK = 1 - Math.exp(-wall_dt / COLOR_TAU_S);
}
function paintMesh(M) {
  const col = M.tgt || (M.tgt = new Float32Array(M.col.length));   // targets; eased into M.col below
  const dT_hot = T_COIL_HOT - T_AMB_JS;
  const tnInner = (sim.T.inner - T_AMB_JS) / dT_hot;
  const tnOuter = (sim.T.outer - T_AMB_JS) / dT_hot;
  // Core/separator: same absolute scale as the coils, then a visual boost — the
  // real core/ring only reach ~45°C @6.175A (tnorm ≈0.31 on this scale), which would
  // look nearly frozen silver. 1.8x lifts that to a clearly visible warm-metal
  // shift while keeping writeRampMetal's own clamp to [0,1]; matches the real IR
  // image (docs/thermal_test.png): coils bright, ring/core moderately warm.
  const tnIron  = (sim.T.iron - T_AMB_JS) / dT_hot * IRON_BOOST;
  const tnByReg = [0, tnInner, tnOuter, tnIron];
  // Disc relative scale: blue = coolest part of plate (top rim), red = hottest
  // (bottom centre). Only stretch once the in-plate spread is physically meaningful
  // (≥0.3 K) — below that the plate is ~isothermal, so use the absolute T_amb–125°C
  // scale and it reads as a uniformly-warming blue (no fake rainbow on noise).
  const invSpan = 1.0 / Math.max(1e-6, dispHi - dispLo);   // eased window (see above)
  for (let tri = 0; tri < M.reg.length; tri++) {
    const reg = M.reg[tri];
    for (let v = 0; v < 3; v++) {
      const vi  = tri * 3 + v;
      const idx = vi * 3;
      if (reg === 0) {
        if (vizMode === 'eddy' || vizMode === 'combined') {
          writeEddyRamp(col, idx, M.je[vi]);
        } else {
          const T  = discVtxT(M, vi);
          writeRamp(col, idx, (T - dispLo) * invSpan);
        }
      } else if (reg === 4) {
        col[idx] = STRUCT_RGB[0]; col[idx+1] = STRUCT_RGB[1]; col[idx+2] = STRUCT_RGB[2];
      } else if (reg === 3 || reg === 5) {
        // Center Core (3) and Separator Ring (5): passive metallic parts that heat
        // by conduction from coils (~39–45°C). Silver-gray at cold → warm orange at hot.
        writeRampMetal(col, idx, tnIron);
      } else {
        // reg 1,2: coils — dark varnished copper at cold → bright orange-yellow at hot.
        writeRampCopper(col, idx, tnByReg[reg]);
      }
    }
  }
  const out = M.col, k = colorEaseK;
  for (let i = 0; i < out.length; i++) out[i] += (col[i] - out[i]) * k;
  M.geo.attributes.color.needsUpdate = true;
}

// ── T_max / T_mean from plate sub-mesh (combined eddy + hot-air field) ────────
function plateTmax() {
  return discThi;   // hottest disc vertex — kept current by updateDiscRange()
}
function plateTmean() {
  return discMeanT(plateM);
}
// T_ss for current I (no sigma correction for speed, close enough for UI)
// ── Steady-state targets = the ENGINE's own fixed point (2026-09-29) ──────────
// The "T_ss target" and the "→NN°" arrows used to be linear closed forms,
//   disc T_amb + ΔT_max_ref·(I/I_ref)²,  coil T_amb + (P_ref/hA + ΔT_air)·(I/I_ref)²,
// exact only at I_ref (5 A). They ignored the two negative feedbacks romStep()
// itself integrates, so they over-shot at high current (7.9 A/20 °C: disc 128
// vs 100 °C, inner coil 80 vs 71 °C):
//  (1) σ_Al(T) = σ0/(1+α·ΔT): skin depth ≈12 mm ≫ 3 mm, so the disc's eddy loss
//      ∝ σ — a disc at 100 °C conducts 24 % less and heats itself 24 % less;
//  (2) natural convection h ∝ ΔT^n (n = convection_exponent, Churchill-Chu
//      laminar ¼): a hotter coil sheds heat more effectively.
// Now the targets come from driving THIS SAME romStep() at constant I until
// nothing moves any more (explicit-Euler fixed point = ODE fixed point, for any
// stable dt). The probe snapshots the live state, integrates on it, reads the
// result and restores the snapshot — the running simulation never sees it.
// The iron node is the slowest mode (C/hA ≈ 1.9 h), hence the long horizon.
const SS_TOL_K = 1e-5;          // per-step change below which the state counts as steady
const SS_MAX_STEPS = 20000;     // ≈ 7 simulated days at 30 s — never reached in practice
const SS_MIN_INTERVAL_MS = 250; // recompute at most 4×/s while I keeps changing (sine, sensor)
const ssCache = {key: null, res: null, at: 0, warm: null};
function discTmaxAtCurrentState() {
  let hi = -Infinity;
  for (let vi = 0; vi < plateM.dT.length; vi++) {
    const T = discVtxT(plateM, vi);
    if (T > hi) hi = T;
  }
  return hi;
}
function engineSteadyState(I) {
  const key = `${I.toFixed(2)}|${T_AMB_JS}|${activePlateIdx}`;
  if (ssCache.key === key) return ssCache.res;
  const now = performance.now();
  if (ssCache.res && ssCache.warm && ssCache.warm.amb === T_AMB_JS &&
      ssCache.warm.plate === activePlateIdx && now - ssCache.at < SS_MIN_INTERVAL_MS)
    return ssCache.res;   // throttled: keep the last target a few more frames
  const snap = {beta: sim.beta, be: sim.beta_eddy, ba: sim.beta_air, t: sim.t, T: {...sim.T}};
  const w = ssCache.warm;
  if (w && w.amb === T_AMB_JS && w.plate === activePlateIdx) {   // warm start: last fixed point
    sim.beta = w.beta; sim.beta_eddy = w.be; sim.beta_air = w.ba; Object.assign(sim.T, w.T);
  }
  const dt = Math.min(30.0, ROM.tau * 0.1);   // ≪ every node's C/(dQ/dT) (≥ ~60 s) → stable
  const keys = Object.keys(sim.T), prev = {};
  let steps = 0, converged = false;
  for (; steps < SS_MAX_STEPS; steps++) {
    for (const k of keys) prev[k] = sim.T[k];
    const pe = sim.beta_eddy, pa = sim.beta_air;
    romStep(I, dt);
    let d = Math.max(Math.abs(sim.beta_eddy - pe), Math.abs(sim.beta_air - pa)) * ROM.dT_max_ref;
    for (const k of keys) d = Math.max(d, Math.abs(sim.T[k] - prev[k]));
    if (d < SS_TOL_K) { converged = true; break; }
  }
  const res = {I, converged, steps, T: {...sim.T},
               beta_eddy: sim.beta_eddy, beta_air: sim.beta_air,
               disc_Tmax: discTmaxAtCurrentState()};
  ssCache.warm = {amb: T_AMB_JS, plate: activePlateIdx, T: {...sim.T},
                  beta: sim.beta, be: sim.beta_eddy, ba: sim.beta_air};
  sim.beta = snap.beta; sim.beta_eddy = snap.be; sim.beta_air = snap.ba; sim.t = snap.t;
  Object.assign(sim.T, snap.T);
  ssCache.key = key; ssCache.res = res; ssCache.at = now;
  return res;
}
function plateTss(I)      { return engineSteadyState(I).disc_Tmax; }
function coilTss_inner(I) { return engineSteadyState(I).T.inner; }
function coilTss_outer(I) { return engineSteadyState(I).T.outer; }
function ironTss(I)       { return engineSteadyState(I).T.iron; }
// Total heat power at current I
function totalPower(I) {
  const s2 = (I / ROM.I_ref) ** 2;
  let p = ROM.P_ref * s2;
  for (const k in LUMPED.nodes) p += LUMPED.nodes[k].P_ref * s2;
  return p;
}

// ── Rolling chart canvas ──────────────────────────────────────────────────────
const chartCanvas = document.getElementById('chart');
const ctx = chartCanvas.getContext('2d');
// Whole-run x-axis (user, 2026-10-06): the charts always span t=0 -> now instead
// of a rolling 10-min window. CHART_MIN_SPAN only keeps the first seconds from
// being stretched across the full width. Cosmetic, not physics.
const CHART_MIN_SPAN = 60;
function chartSpan() {
  const N = sim.hist_t.length;
  const t0 = N ? sim.hist_t[0] : 0, tNow = N ? sim.hist_t[N-1] : 0;
  return {t0, span: Math.max(CHART_MIN_SPAN, tNow - t0)};
}
function fmtSpan(sec) { return sec < 120 ? sec.toFixed(0) + ' s' : sec < 7200 ? (sec/60).toFixed(1) + ' min' : (sec/3600).toFixed(2) + ' h'; }

function drawGrid(W, H, nRows) {
  ctx.strokeStyle = 'rgba(120,140,180,.12)'; ctx.lineWidth = 1; ctx.setLineDash([]);
  ctx.beginPath();
  for (let i = 1; i < nRows; i++) {
    const y = H * i / nRows;
    ctx.moveTo(0, y); ctx.lineTo(W, y);
  }
  for (let i = 1; i < 6; i++) {
    const x = W * i / 6;
    ctx.moveTo(x, 0); ctx.lineTo(x, H);
  }
  ctx.stroke();
}

function drawChart() {
  const W = chartCanvas.width, H = chartCanvas.height;
  ctx.fillStyle = '#0a0a14'; ctx.fillRect(0, 0, W, H);
  const N = sim.hist_t.length;
  if (N < 2) return;
  const tNow = sim.hist_t[N-1];
  const {t0, span} = chartSpan();
  // Steady-state target line removed (user, 2026-10-06: no measured steady state
  // yet, WP-ANCHOR) -- the axis now scales to the history actually drawn.
  let Thi = T_AMB_JS + 2;
  for (let i = 0; i < N; i++) {
    if (sim.hist_t[i] < t0) continue;
    Thi = Math.max(Thi, sim.hist_Tmax[i] + 1, sim.hist_T_inner[i] + 1, sim.hist_T_outer[i] + 1);
  }
  const Tlo = T_AMB_JS - 0.5;
  const tx = t => (t - t0) / span * W;
  const ty = T => H - (T - Tlo) / (Thi - Tlo) * H;
  drawGrid(W, H, 4);
  // T_amb line (blue dashed)
  ctx.strokeStyle = '#5599ff'; ctx.lineWidth = 1; ctx.setLineDash([5,4]);
  ctx.beginPath();
  ctx.moveTo(0, ty(T_AMB_JS)); ctx.lineTo(W, ty(T_AMB_JS)); ctx.stroke();
  ctx.setLineDash([]);
  // Outer coil line (bright yellow, thicker for contrast)
  ctx.strokeStyle = '#ffdd22'; ctx.lineWidth = 2.2;
  ctx.beginPath(); let fo = true;
  for (let i = 0; i < N; i++) {
    if (sim.hist_t[i] < t0) continue;
    const x = tx(sim.hist_t[i]), y = ty(sim.hist_T_outer[i]);
    fo ? (ctx.moveTo(x,y), fo=false) : ctx.lineTo(x,y);
  }
  ctx.stroke();
  // Inner coil line (vivid orange, thicker for contrast)
  ctx.strokeStyle = '#ff6600'; ctx.lineWidth = 2.2;
  ctx.beginPath(); let fi = true;
  for (let i = 0; i < N; i++) {
    if (sim.hist_t[i] < t0) continue;
    const x = tx(sim.hist_t[i]), y = ty(sim.hist_T_inner[i]);
    fi ? (ctx.moveTo(x,y), fi=false) : ctx.lineTo(x,y);
  }
  ctx.stroke();
  // Plate T_max line (red, drawn on top)
  ctx.strokeStyle = '#ff6644'; ctx.lineWidth = 1.8;
  ctx.beginPath(); let fp = true;
  for (let i = 0; i < N; i++) {
    if (sim.hist_t[i] < t0) continue;
    const x = tx(sim.hist_t[i]), y = ty(sim.hist_Tmax[i]);
    fp ? (ctx.moveTo(x,y), fp=false) : ctx.lineTo(x,y);
  }
  ctx.stroke();
  // labels
  ctx.fillStyle = '#7ab'; ctx.font = '9px monospace';
  ctx.fillText(Thi.toFixed(1)+'°C', 2, 11);
  ctx.fillText(Tlo.toFixed(1)+'°C', 2, H-3);
  // x-axis span, bottom-right (bottom-left holds the T_lo label)
  const spanLbl = `${fmtSpan(t0)} → ${fmtSpan(t0 + span)}`;
  ctx.fillStyle = '#7ab';
  ctx.fillText(spanLbl, W - ctx.measureText(spanLbl).width - 3, H - 3);
}

// ── I(t) current-profile chart (second canvas) ────────────────────────────────
const chartCanvasI = document.getElementById('chartI');
const ctxI = chartCanvasI.getContext('2d');
function drawCurrentChart() {
  const W = chartCanvasI.width, H = chartCanvasI.height;
  ctxI.fillStyle = '#0a0a14'; ctxI.fillRect(0, 0, W, H);
  const N = sim.hist_I.length;
  if (N < 2) return;
  const {t0, span} = chartSpan();
  let Ihi = Math.max(targetI, 1);
  for (let i = 0; i < N; i++) Ihi = Math.max(Ihi, sim.hist_I[i]);
  Ihi *= 1.15;
  const tx = t => (t - t0) / span * W;
  const iy = I => H - (I / Ihi) * H;
  ctxI.strokeStyle = 'rgba(120,140,180,.12)'; ctxI.lineWidth = 1;
  ctxI.beginPath();
  for (let i = 1; i < 3; i++) { const y = H*i/3; ctxI.moveTo(0,y); ctxI.lineTo(W,y); }
  for (let i = 1; i < 6; i++) { const x = W*i/6; ctxI.moveTo(x,0); ctxI.lineTo(x,H); }
  ctxI.stroke();
  ctxI.strokeStyle = '#5599ff'; ctxI.lineWidth = 1.6; ctxI.beginPath();
  let first = true;
  for (let i = 0; i < N; i++) {
    if (sim.hist_t[i] < t0) continue;
    const x = tx(sim.hist_t[i]), y = iy(sim.hist_I[i]);
    first ? (ctxI.moveTo(x,y), first=false) : ctxI.lineTo(x,y);
  }
  ctxI.stroke();
  ctxI.fillStyle = '#7ab'; ctxI.font = '9px monospace';
  ctxI.fillText(Ihi.toFixed(1)+'A', 2, 11);
  ctxI.fillText('0A', 2, H-3);
}

// ── Hover tooltips for both charts ────────────────────────────────────────────
const chartTip = document.createElement('div');
chartTip.className = 'chart-tip';
document.body.appendChild(chartTip);
function attachChartTooltip(canvas, formatFn) {
  canvas.addEventListener('mousemove', (e) => {
    const N = sim.hist_t.length;
    if (N < 2) { chartTip.style.display = 'none'; return; }
    const rect = canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) * (canvas.width / rect.width);
    const {t0, span} = chartSpan();
    const tAtX = t0 + x / canvas.width * span;
    let idx = 0, best = Infinity;
    for (let i = 0; i < N; i++) {
      const d = Math.abs(sim.hist_t[i] - tAtX);
      if (d < best) { best = d; idx = i; }
    }
    chartTip.textContent = formatFn(idx);
    chartTip.style.left = (e.clientX + 12) + 'px';
    chartTip.style.top  = (e.clientY - 10) + 'px';
    chartTip.style.display = 'block';
  });
  canvas.addEventListener('mouseleave', () => { chartTip.style.display = 'none'; });
}
attachChartTooltip(chartCanvas,  i =>
  `t=${sim.hist_t[i].toFixed(0)}s  Plate=${sim.hist_Tmax[i].toFixed(2)}°C  Inner=${sim.hist_T_inner[i].toFixed(2)}°C  Outer=${sim.hist_T_outer[i].toFixed(2)}°C`);
attachChartTooltip(chartCanvasI, i => `t=${sim.hist_t[i].toFixed(0)}s   I=${sim.hist_I[i].toFixed(2)}A`);

// ── UI wiring ─────────────────────────────────────────────────────────────────
const sI = document.getElementById('sI');
const sS = document.getElementById('sS');
sS.oninput = () => {
  const sp = Math.pow(10, +sS.value);
  document.getElementById('vS').textContent = (sp<10?sp.toFixed(1):Math.round(sp))+'×';
};
sS.oninput();  // sync display with initial slider value on load
// Collapsible picker (user, 2026-10-06): chip = current choice; click opens the
// options, they close by themselves PICK_HIDE_MS after the last interaction
// (hovering the open options holds them open; a 2nd chip click closes at once).
const PICK_HIDE_MS = 3000;
function makePicker(chipId, bodyId) {
  const chip = document.getElementById(chipId), body = document.getElementById(bodyId);
  let timer = null;
  const close = () => { clearTimeout(timer); body.classList.remove('open'); chip.setAttribute('aria-expanded', 'false'); };
  const arm = () => { clearTimeout(timer); timer = setTimeout(close, PICK_HIDE_MS); };
  chip.addEventListener('click', () => {
    if (body.classList.contains('open')) return close();
    body.classList.add('open'); chip.setAttribute('aria-expanded', 'true'); arm();
  });
  body.addEventListener('mouseenter', () => clearTimeout(timer));
  body.addEventListener('mouseleave', () => { if (body.classList.contains('open')) arm(); });
  body.addEventListener('click', () => { if (body.classList.contains('open')) arm(); });
  return {setLabel: t => { chip.textContent = t; }};
}
const ambPicker = makePicker('ambChip', 'ambBody');
const platePicker = makePicker('plateChip', 'plateBody');
const scPicker = makePicker('scChip', 'scBody');
const excPicker = makePicker('excChip', 'excBody');

function selectScenario(name) {
  if (sensorDriveI !== null) return;   // Sensor mode: the rig sets I(t)
  const btn = document.querySelector(`.sc-btn[data-sc="${name}"]`);
  if (!btn) return;
  document.querySelectorAll('.sc-btn[data-sc]').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  scPicker.setLabel(btn.textContent);
  curScenario = name;
  resetSim();
}
document.querySelectorAll('.sc-btn[data-sc]').forEach(btn => {
  btn.onclick = () => selectScenario(btn.dataset.sc);
});
document.getElementById('reset').onclick = resetSim;


// ── Disc-radius compare mode: build the radio buttons from PARAMS.plate_variants
// (not hardcoded here) so the radius list always matches what Python baked.
{
  const grp = document.getElementById('plateGroup');
  PLATE_VARIANTS.forEach((v, i) => {
    const b = document.createElement('button');
    b.className = 'sc-btn' + (i === activePlateIdx ? ' active' : '');
    b.textContent = `Ø${(2 * v.radius_mm).toFixed(0)}mm`;
    b.title = `dT_mean_ref=${v.rom.dT_mean_ref.toFixed(1)}K @ I_ref=${v.rom.I_ref}A`;
    b.onclick = () => {
      grp.querySelectorAll('.sc-btn').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      selectPlateVariant(i);
      platePicker.setLabel(b.textContent);
    };
    grp.appendChild(b);
    if (i === activePlateIdx) platePicker.setLabel(b.textContent);
  });
}

// ── Visualization mode (Thermal / B Field / Eddy J / Combined) ───────────────
document.querySelectorAll('.sc-btn[data-viz]').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('.sc-btn[data-viz]').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    vizMode = btn.dataset.viz;
    updateVizVisibility();
  };
});
const sFLO = document.getElementById('sFLO');
sFLO.oninput = () => {
  fieldLineOpacityPct = +sFLO.value / 100;
  document.getElementById('vFLO').textContent = sFLO.value + '%';
  applyFieldLineOpacity();
};

const setV = (id, v, dec=1) => document.getElementById(id).textContent = v.toFixed(dec)+' °C';
// Row swatches use the SAME ramp + normalisation as that part on the model (and as
// the colour bar in its section header): disc -> eased disc window, coils -> copper,
// core/separator -> iron (with IRON_BOOST).
const _sw = [0, 0, 0];
function setSwatch(id, writeFn, tn) {
  writeFn(_sw, 0, tn);
  document.getElementById(id).style.background =
    `rgb(${(_sw[0]*255)|0},${(_sw[1]*255)|0},${(_sw[2]*255)|0})`;
}

// ── Panel collapse (click header to toggle) ──────────────────────────────────
// CSS can't animate a transition into `width:fit-content` (browsers treat it as
// a non-interpolable keyword and just snap), so measure the header's natural
// shrink-to-fit width in JS and transition between two explicit px values.
document.querySelectorAll('.panel-head').forEach(h => {
  const panel = h.parentElement;
  h.onclick = () => {
    const collapsing = !panel.classList.contains('collapsed');
    if (collapsing) {
      const title = h.children[0], chev = h.children[1];
      const headStyle = getComputedStyle(h);
      const collapsedWidth = title.scrollWidth + chev.scrollWidth
        + parseFloat(headStyle.gap || 10)
        + parseFloat(headStyle.paddingLeft) + parseFloat(headStyle.paddingRight);
      // pin the CURRENT width first so the transition has a start value
      panel.style.width = panel.offsetWidth + 'px';
      panel.offsetWidth;   // force reflow
      panel.style.width = collapsedWidth + 'px';
      panel.classList.add('collapsed');
    } else {
      // Clear the inline override a frame later (double rAF = wait for the
      // collapsed width to actually paint) so the transition animates from
      // that width back to the stylesheet's own width (252px desktop / 100%
      // under the mobile media query) instead of a stale fixed px forever.
      panel.classList.remove('collapsed');
      requestAnimationFrame(() => requestAnimationFrame(() => { panel.style.width = ''; }));
    }
  };
});

// ── Dark / light theme toggle ─────────────────────────────────────────────────
const themeBtn = document.getElementById('themeToggle');
let isLightTheme = false;
themeBtn.onclick = () => {
  isLightTheme = !isLightTheme;
  document.body.classList.toggle('light', isLightTheme);
  themeBtn.textContent = isLightTheme ? '🌙 Dark' : '☀️ Light';
  const fogColor = isLightTheme ? 0xdfe6f5 : 0x0f0f1e;
  scene.fog.color.set(fogColor);
  // 3D overlays follow the theme too: field lines + force arrows get dark,
  // cool colours on the light background.
  flLightTheme = isLightTheme;
  if (flCurrentData) buildFieldLines(flCurrentData);
  const [cUp, cDn] = FORCE_ARROW_COL[isLightTheme ? 'light' : 'dark'];
  arrUp.setColor(cUp); arrDn.setColor(cDn);
};

// ── Model-information table ("i" button / key I) ──────────────────────────────
// Tables are baked from params.yaml (model_info() in build_twin_html_fem.py); the
// JS only lays them out. Display only. Notes appear as a hover tooltip.
const MODEL_INFO = PARAMS.model_info;
const SRC_LABEL = {meas: 'Measured', given: 'Given', ref: 'Reference', calc: 'Computed',
                   assumed: 'Assumed'};
const SRC_HINT = {
  meas: 'measured on the real rig by the team',
  given: 'given by the professor / TEAM 28 problem / teacher',
  ref: 'handbook / literature value',
  calc: 'computed by this model',
  assumed: 'placeholder or estimate, not verified',
};
function escHtml(s) {
  return String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
}
function srcChip(s) {
  return `<span class="src ${s}" title="${SRC_HINT[s] || ''}">${SRC_LABEL[s] || s}</span>`;
}
const MAT_COLOR = {Aluminium: '#c0c8d4', Copper: '#c4561b', Iron: '#8a94a6', Plywood: '#a0773f'};
function infoCell(c) {   // a cell is "text" or ["text", "assumed"]
  return Array.isArray(c) ? `<span class="asm">${escHtml(c[0])} †</span>` : escHtml(c);
}
function renderModelInfo() {
  let h = '';
  for (const sec of MODEL_INFO) {
    h += `<h3>${escHtml(sec.title)}</h3><div class="info-wrap"><table class="info-tbl">` +
         '<thead><tr>' + sec.cols.map(c => `<th>${escHtml(c)}</th>`).join('') + '<th>Source</th></tr></thead><tbody>';
    sec.rows.forEach((row, i) => {
      h += `<tr title="${escHtml(row.note || '')}">`;
      row.cells.forEach((c, j) => {
        if (j === 0 && sec.group) {   // merge consecutive rows of the same material
          if (i > 0 && sec.rows[i - 1].cells[0] === c) return;
          let n = 1;
          while (i + n < sec.rows.length && sec.rows[i + n].cells[0] === c) n++;
          h += `<td class="mat" rowspan="${n}"><span class="sw" style="background:${MAT_COLOR[c] || 'var(--faint)'}"></span>${escHtml(c)}</td>`;
        } else {
          h += `<td${j === 0 ? ' class="k"' : ''}>${infoCell(c)}</td>`;
        }
      });
      h += `<td class="s">${srcChip(row.src)}</td></tr>`;
    });
    h += '</tbody></table></div>';
  }
  h += '<div class="info-foot"><span class="asm">†</span> assumed placeholder, not measured · ' +
    'hover a row for its note<br>Source: ' +
    Object.keys(SRC_LABEL).map(k => `${srcChip(k)} ${SRC_HINT[k]}`).join(' · ') + '</div>';
  document.getElementById('infoBody').innerHTML = h;
}
renderModelInfo();
const infoOverlay = document.getElementById('infoOverlay');
const infoBtn = document.getElementById('infoBtn');
function setInfoOpen(open) {
  infoOverlay.classList.toggle('open', open);
  infoBtn.classList.toggle('on', open);
}
infoBtn.onclick = () => setInfoOpen(!infoOverlay.classList.contains('open'));
document.getElementById('infoClose').onclick = () => setInfoOpen(false);
infoOverlay.addEventListener('click', e => { if (e.target === infoOverlay) setInfoOpen(false); });

// ── Colour-scale ticks + mode toggle ──────────────────────────────────────────
function ticksHtml(lo, hi, steps, dec) {
  let html = '';
  for (let i = 0; i <= steps; i++) html += `<span>${(lo + (hi - lo) * i / steps).toFixed(dec)}°</span>`;
  return html;
}
// Material bars are sampled from the SAME ramp functions paintMesh uses (incl.
// their perceptual pow/sqrt boosts), so bar colour == model colour at that T.
function rampGradient(writeFn) {
  const c = [0, 0, 0], stops = [];
  for (let i = 0; i <= 10; i++) {
    writeFn(c, 0, i / 10);
    stops.push(`rgb(${(c[0]*255)|0},${(c[1]*255)|0},${(c[2]*255)|0}) ${i*10}%`);
  }
  return `linear-gradient(to right,${stops.join(',')})`;
}
const IRON_BOOST = 1.8;   // must match tnIron in paintMesh
function ironHotC() { return T_AMB_JS + (T_COIL_HOT - T_AMB_JS) / IRON_BOOST; }
let tickLo = NaN, tickHi = NaN;
function buildScaleTicks() {
  tickLo = dispLo; tickHi = dispHi;
  const dec = (dispHi - dispLo) < 12 ? 1 : 0;
  document.getElementById('scaleTicks').innerHTML = ticksHtml(dispLo, dispHi, 4, dec);
  document.getElementById('scaleTicksCopper').innerHTML = ticksHtml(T_AMB_JS, T_COIL_HOT, 4, 0);
  document.getElementById('scaleTicksIron').innerHTML = ticksHtml(T_AMB_JS, ironHotC(), 4, 0);
}
document.getElementById('scaleBarCopper').style.background = rampGradient(writeRampCopper);
document.getElementById('scaleBarIron').style.background = rampGradient(writeRampMetal);
buildScaleTicks();
const scaleModeBtn = document.getElementById('scaleModeBtn');
const SCALE_MODES = ['auto', 'absolute', 'relative'];
scaleModeBtn.onclick = () => {
  const i = (SCALE_MODES.indexOf(colorScaleMode) + 1) % SCALE_MODES.length;
  colorScaleMode = SCALE_MODES[i];
  scaleModeBtn.textContent = 'Scale: ' + colorScaleMode[0].toUpperCase() + colorScaleMode.slice(1);
};
const scaleMarkerLo = document.getElementById('scaleMarkerLo');
const scaleMarkerHi = document.getElementById('scaleMarkerHi');
const scaleCurRangeEl = document.getElementById('scaleCurRange');
let scaleTextTimer = 0;
const pctIn = (T, lo, hi) => (Math.max(0, Math.min(1, (T - lo) / Math.max(1e-6, hi - lo))) * 100).toFixed(1) + '%';
function updateScaleBar(dt) {
  // Disc markers sit in the eased display window, so they glide with it.
  scaleMarkerLo.style.left = pctIn(discTlo, dispLo, dispHi);
  scaleMarkerHi.style.left = pctIn(discThi, dispLo, dispHi);
  scaleTextTimer -= dt || 0;
  if (scaleTextTimer > 0) return;
  scaleTextTimer = 0.25;   // text at 4 Hz, markers every frame (CSS-eased)
  scaleCurRangeEl.textContent = `${discTlo.toFixed(1)}–${discThi.toFixed(1)} °C`;
  if (Math.abs(dispLo - tickLo) > 0.05 || Math.abs(dispHi - tickHi) > 0.05) buildScaleTicks();
  document.getElementById('mkInner').style.left = pctIn(sim.T.inner, T_AMB_JS, T_COIL_HOT);
  document.getElementById('mkOuter').style.left = pctIn(sim.T.outer, T_AMB_JS, T_COIL_HOT);
  document.getElementById('mkIron').style.left  = pctIn(sim.T.iron, T_AMB_JS, ironHotC());
}

// ── Export: screenshot (PNG) + T_max(t) history (CSV) ─────────────────────────
document.getElementById('btnScreenshot').onclick = () => {
  renderer.domElement.toBlob((blob) => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `thermal_twin_${Date.now()}.png`;
    a.click();
  });
};
document.getElementById('btnExportCsv').onclick = () => {
  let csv = 't_s,T_plate_max_C,T_inner_coil_C,T_outer_coil_C,I_A,T_amb_C,T_amb_source,T_amb_recorded_at\n';
  const amb = `${T_AMB_JS.toFixed(2)},${ambient.source},${T_AMB_AT}`;
  for (let i = 0; i < sim.hist_t.length; i++)
    csv += `${sim.hist_t[i].toFixed(2)},${sim.hist_Tmax[i].toFixed(3)},` +
           `${sim.hist_T_inner[i].toFixed(3)},${sim.hist_T_outer[i].toFixed(3)},` +
           `${sim.hist_I[i].toFixed(3)},${amb}\n`;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], {type:'text/csv'}));
  a.download = `tmax_history_${Date.now()}.csv`;
  a.click();
};

// ── Keyboard shortcuts ────────────────────────────────────────────────────────
let paused = false;
const pausedBadge = document.getElementById('pausedBadge');
function setPaused(v) {
  paused = v;
  pausedBadge.style.display = paused ? 'block' : 'none';
}
function adjustSpeed(dir) {
  if (sS.disabled) return;   // Sensor mode runs at 1x real time
  const v = Math.max(0, Math.min(2.301, +sS.value + dir * 0.1));
  sS.value = v;
  sS.oninput();
}
addEventListener('keydown', (e) => {
  if (e.key === 'i' || e.key === 'I') { setInfoOpen(!infoOverlay.classList.contains('open')); return; }
  if (infoOverlay.classList.contains('open')) {   // sheet open: Esc closes, sim keys stay inert
    if (e.key === 'Escape') setInfoOpen(false);
    return;
  }
  switch (e.key) {
    case ' ':  e.preventDefault(); setPaused(!paused); break;
    case 'r': case 'R': resetSim(); break;
    case 'f': case 'F': fitView(); break;
    case '1': selectScenario('quickstart'); break;
    case '2': selectScenario('step');  break;
    case '3': selectScenario('ramp');  break;
    case '4': selectScenario('sine');  break;
    case '5': selectScenario('pulse'); break;
    case '+': case '=': adjustSpeed(1);  break;
    case '-': case '_': adjustSpeed(-1); break;
  }
});

document.getElementById('tauLabel').textContent =
  `τ = ${(ROM.tau/60).toFixed(2)} min  |  UA = ${ROM.UA.toFixed(4)} W/K`;

// Precompute coil steady-state temperatures (at I_ref) — shown as target arrows.
// True steady rise = own rise above the local air node + the air node's rise above
// the far ambient (AIR_DT_SS_REF), since the coils now convect into shared air.
// Steady-state read-outs REMOVED from the panel (user, 2026-10-06): there is no
// measured steady state yet (WP-ANCHOR -- coil hA are only bounds). The engine
// functions (coilTss_*/ironTss/plateTss) stay; xval and the chart may use them.
function paintCoilSS() {}
paintCoilSS();

// Iron/plate EM badges (B_max_iron/saturation) — was a one-shot block that never
// re-ran after a disc-radius swap (selectPlateVariant Object.assign(ROM, v.rom)
// updates the underlying numbers but nothing repainted the badge). Now a named
// function called both at initial load and at the end of selectPlateVariant().
function updateEmBadges() {
  const bmax = ROM.B_max_iron, bsat = ROM.B_sat;
  const satEl = document.getElementById('tBmax');
  satEl.textContent = `${bmax.toFixed(3)} T / ${bsat} T`;
  satEl.style.color = ROM.saturated ? 'var(--c-warn)' : 'var(--c-ok)';
  document.getElementById('satRow').title = ROM.saturated
    ? 'WARNING: iron core is magnetically saturated — μ_r=1000 is invalid!'
    : '';
}
updateEmBadges();
// Bottom air temperature seen by the disc. It is set by the LIVE coil temperature
// (coilAirDrive), so it warms slowly with the copper mass rather than jumping with
// I² — this is the thermal-inertia effect. Updated every frame in the loop.
function liveAirBot() {
  const Tinf_bot = T_AMB_JS + (ROM.Tinf_bot_ref - ROM.T_amb) * coilAirDrive();
  document.getElementById('tAirBot').textContent = Tinf_bot.toFixed(1) + ' °C';
}
liveAirBot();
sI.oninput = () => {
  targetI = +sI.value;
  document.getElementById('vI').textContent = targetI.toFixed(1)+' A';
};

// ── Variac dial input mode (Carroll & Meynell CMV 10 E-1, docs/rig_photo.jpg) ─
// Dial scale reads 0-270; anchors measured on the real rig (params.yaml
// power_supply.dial_to_current_A). Piecewise-linear, same as config.py's
// dial_to_current_A() so the twin and the offline tooling agree.
const PS_ANCHORS = (PARAMS.power_supply && PARAMS.power_supply.anchors) ||
  [[0, 0], [220, 5.0], [270, 6.175]];
function dialToCurrentA(dial) {
  const xs = PS_ANCHORS;
  if (dial <= xs[0][0]) return xs[0][1];
  if (dial >= xs[xs.length-1][0]) return xs[xs.length-1][1];
  for (let i = 1; i < xs.length; i++) {
    if (dial <= xs[i][0]) {
      const [x0, y0] = xs[i-1], [x1, y1] = xs[i];
      return y0 + (dial - x0) / (x1 - x0) * (y1 - y0);
    }
  }
  return xs[xs.length-1][1];
}
// Inverse of dialToCurrentA — approximates the variac DIAL ANGLE (degrees) for
// a given current, so Dial-input mode's slider can sync from Amps-input mode.
function dialFromCurrentA(I) {
  const xs = PS_ANCHORS;
  if (I <= xs[0][1]) return xs[0][0];
  if (I >= xs[xs.length-1][1]) return xs[xs.length-1][0];
  for (let i = 1; i < xs.length; i++) {
    if (I <= xs[i][1]) {
      const [x0, y0] = xs[i-1], [x1, y1] = xs[i];
      return x0 + (I - y0) / (y1 - y0) * (x1 - x0);
    }
  }
  return xs[xs.length-1][0];
}
// dial scale is DEGREES of rotation, NOT Volts (corrected 2026-07-10) — the
// output voltage scales linearly with angle up to ~input voltage at full turn.
const DEG_TO_VOLT_RATIO = (PARAMS.power_supply && PARAMS.power_supply.degree_to_volt_ratio) || 0.88889;
function dialToVoltageV(dial) { return dial * DEG_TO_VOLT_RATIO; }
const sDial = document.getElementById('sDial');
sDial.oninput = () => {
  targetI = dialToCurrentA(+sDial.value);
  document.getElementById('vDial').textContent = sDial.value;
  document.getElementById('vI').textContent = targetI.toFixed(2)+' A';
};
document.querySelectorAll('.sc-btn[data-mode]').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('.sc-btn[data-mode]').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    excPicker.setLabel(btn.textContent);
    const mode = btn.dataset.mode;
    document.getElementById('ampsGroup').style.display = mode === 'amps' ? '' : 'none';
    document.getElementById('dialGroup').style.display  = mode === 'dial' ? '' : 'none';
    document.getElementById('sensorGroup').style.display = mode === 'sensor' ? '' : 'none';
    if (mode !== 'sensor') stopSensor();   // leaving Sensor mode hands I back to the sliders
    if (mode === 'dial') sDial.oninput(); else if (mode === 'amps') sI.oninput();
  };
});

// ── Ambient selector: fixed presets (params.yaml) + Live (Google Weather) ─────
// Changing T_amb restarts the sim at equilibrium with the NEW ambient: the disc
// field is stored relative to T_amb while the coil/iron/air nodes are absolute,
// so switching mid-run would give an inconsistent mixed state.

const AMB_PRESETS = PARAMS.ambient_presets || [{key: 'ref', value: ROM.T_amb, note: 'model reference'}];
const LIVE_KEY_OK = !!GOOGLE_WEATHER_API_KEY && GOOGLE_WEATHER_API_KEY !== "YOUR_KEY_HERE" && !weatherKeyExpired();
const ambGroup = document.getElementById('ambGroup'), ambNote = document.getElementById('ambNote');
let ambMode = ambient.live ? 'live'
  : (AMB_PRESETS.find(p => Math.abs(p.value - T_AMB_JS) < 1e-9) || AMB_PRESETS[0]).key;
function paintAmbGroup() {
  ambGroup.querySelectorAll('.sc-btn').forEach(b => b.classList.toggle('active', b.dataset.amb === ambMode));
  const liveBtn = ambGroup.querySelector('.sc-btn[data-amb="live"]');
  if (liveBtn) liveBtn.textContent = ambient.live ? `Live ${T_AMB_JS.toFixed(1)} °C` : 'Live';
  ambPicker.setLabel(ambMode === 'live' ? `Live ${T_AMB_JS.toFixed(1)} °C` : `${T_AMB_JS.toFixed(0)} °C`);
  const p = AMB_PRESETS.find(q => q.key === ambMode);
  ambNote.textContent = ambMode === 'live'
    ? `Google Weather, Darmstadt · ${ambient.at.toTimeString().slice(0, 5)}`
    : (p ? p.note : '');
}
function setAmbient(value, src) {
  ambient = src; T_AMB_JS = value; T_AMB_AT = src.at.toISOString();
  T_COLOR_LO = T_AMB_JS; TRANGE = T_COLOR_HI - T_COLOR_LO;
  resetSim();
  discTlo = discThi = T_AMB_JS;
  buildScaleTicks(); paintCoilSS(); paintAmbient(); liveAirBot();
  console.info(`[ambient] switched: T_amb = ${T_AMB_JS} °C, source=${ambient.source}`);
}
AMB_PRESETS.forEach(p => {
  const b = document.createElement('button');
  b.className = 'sc-btn'; b.dataset.amb = p.key; b.title = p.note;
  b.textContent = `${p.value.toFixed(0)} °C`;
  b.onclick = () => {
    ambMode = p.key;
    setAmbient(p.value, {value: p.value, live: false, at: new Date(), source: `preset ${p.key}`});
    paintAmbGroup();
  };
  ambGroup.appendChild(b);
});
{
  const b = document.createElement('button');
  b.className = 'sc-btn'; b.dataset.amb = 'live'; b.textContent = 'Live';
  b.disabled = !LIVE_KEY_OK;
  b.title = LIVE_KEY_OK ? 'Current outdoor temperature, Darmstadt (Google Weather API)'
    : 'Unavailable: this build has no (valid) weather API key -- see params.yaml weather_api';
  b.onclick = async () => {
    b.disabled = true; ambNote.textContent = 'Fetching live temperature…';
    const r = await fetchAmbientC();
    b.disabled = false;
    if (r.live) { ambMode = 'live'; setAmbient(r.value, r); paintAmbGroup(); }
    else { paintAmbGroup(); ambNote.textContent = `Live unavailable (${r.source}) — kept ${T_AMB_JS.toFixed(0)} °C`; }
  };
  ambGroup.appendChild(b);
}
paintAmbGroup();

// ── Sensor excitation mode: measured I_rms drives the model ──────────────────
// Source: the rig's Arduino (arduino/thermal_sensor/thermal_sensor.ino) over
// Web Serial -- "millis,I_rms_A" at 1 Hz ('#' lines = diagnostics), the same
// wire format data_io.py parses -- or a synthetic demo signal. Conditioning
// matches digital_twin_live.py's LiveDriver (params.yaml live_sensor): dead-band,
// clamp to the rig's I_max, zero-order hold between samples, STALE after
// stale_after_s without a sample, plus the same AUTO zero offset for a real serial
// source: the first zero_cal_s seconds (Variac at 0) give I0 = RMS of the readings,
// then I = I_raw - I0 (zero_offset_mode linear) or sqrt(I_raw^2 - I0^2) (quadrature);
// I0 > zero_cal_max_A (current was flowing) -> the board's default from
// live_sensor.board_offsets (matched by USB VID:PID via port.getInfo()) instead. Also accepts bare "I_rms" lines (firmware without millis).
// While a source runs: speed locked to 1x (real time), scenarios off.
// Temperatures remain model OUTPUT (no T sensor on the rig).
const LS = PARAMS.live_sensor || {};
const SENSOR_BAUD = LS.baudrate || 9600, SENSOR_DEADBAND_A = LS.deadband_A ?? 0.2;
const SENSOR_STALE_S = LS.stale_after_s || 3.0, SENSOR_I_MAX = LS.i_max_A || 20.0;
const ZERO_CAL_S = LS.zero_cal_s || 0, ZERO_CAL_MAX_A = LS.zero_cal_max_A ?? 1.0;
const SENSOR_INVALID_A = LS.invalid_above_A ?? 20.0;   // above = not a current (raw ADC?)
const ZERO_MODE = LS.zero_offset_mode || 'linear', ZERO_DEFAULT_A = LS.zero_offset_default_A || 0;
const BOARD_OFFSETS = LS.board_offsets || [];
function boardOffset(info) {   // same rule as digital_twin_live.board_offset()
  const hex = n => (n ?? -1).toString(16).padStart(4, '0');
  const id = info && info.usbVendorId != null ? `${hex(info.usbVendorId)}:${hex(info.usbProductId)}` : null;
  const b = BOARD_OFFSETS.find(x => id && x.usb_id === id);
  return b ? {name: b.name, id, I0: b.I0_A} : {name: 'unknown board', id, I0: ZERO_DEFAULT_A};
}
const HAS_SERIAL = 'serial' in navigator;
const sensor = {kind: null, state: 'off', msg: '', lastWall: 0, lastRaw: NaN, n: 0,
                port: null, reader: null, timer: null,
                zero: 'off', zeroT0: 0, zeroBuf: [], I0: 0,    // zero: off|measuring|done|rejected
                board: {name: '', id: null, I0: ZERO_DEFAULT_A}};
const sDot = document.getElementById('sensorDot'), sStateEl = document.getElementById('sensorState');
const sIEl = document.getElementById('sensorI'), sNote = document.getElementById('sensorNote');
const btnSerial = document.getElementById('btnSerial'), btnDemo = document.getElementById('btnSensorDemo');
const btnZero = document.getElementById('btnSensorZero');
const sNoteDefault = sNote.innerHTML;   // restored when no zero-offset message applies
if (!HAS_SERIAL) {
  btnSerial.disabled = true;
  btnSerial.title = 'Web Serial needs Chrome or Edge on a desktop (not Safari/Firefox/iOS)';
}
function parseSensorLine(line) {
  // "millis,I_rms_A" (rig), "millis,T_core,T_disc,I_rms" (legacy log) or a bare
  // "I_rms" (firmware without millis) -> I, else null
  line = line.trim();
  if (!line || line[0] === '#') return null;
  if (/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(line)) return parseFloat(line);
  const f = line.split(',').map(x => x.trim());
  if ((f.length !== 2 && f.length !== 4) || !/^-?\d+$/.test(f[0])) return null;
  const I = parseFloat(f[f.length - 1]);
  return Number.isFinite(I) ? I : null;
}
function conditionI(I) {   // same rule as LiveDriver.condition()
  I = ZERO_MODE === 'quadrature' ? Math.sqrt(Math.max(0, I * I - sensor.I0 * sensor.I0))
                                 : Math.max(0, I - sensor.I0);   // zero offset
  if (!(I >= SENSOR_DEADBAND_A)) return 0.0;
  return Math.min(I, SENSOR_I_MAX);
}
function lockControls(on) {
  document.getElementById('scGroup').classList.toggle('locked', on);
  const scChip = document.getElementById('scChip');   // collapsed picker: lock it too
  scChip.disabled = on;
  scChip.title = on ? 'Locked: the rig sets I(t) in Sensor mode' : 'Change scenario';
  if (on) { document.getElementById('scBody').classList.remove('open'); scChip.setAttribute('aria-expanded', 'false'); }
  if (on) { sS.value = 0; sS.oninput(); }
  sS.disabled = on;
}
function paintSensor() {
  const labels = {off: 'Not connected', connecting: 'Connecting…', waiting: 'Waiting for data…',
                  live: sensor.kind === 'demo' ? 'LIVE · demo signal' : 'LIVE · Arduino',
                  stale: 'STALE · no new sample', error: 'Disconnected'};
  sDot.className = 'dot ' + ({live: 'live', stale: 'stale', error: 'error'}[sensor.state] || '');
  sStateEl.textContent = labels[sensor.state] + (sensor.msg ? ` — ${sensor.msg}` : '');
  sIEl.textContent = Number.isFinite(sensor.lastRaw) ? `${sensor.lastRaw.toFixed(2)} A` : '— A';
  const zeroTxt = {measuring: `Zero offset: measuring — keep the Variac at 0 (${ZERO_CAL_S} s) · ${sensor.board.name || 'board ?'}`,
                   done: `Zero offset I₀ = ${sensor.I0.toFixed(3)} A removed (${ZERO_MODE === 'quadrature' ? '√(I² − I₀²)' : 'I − I₀'}), raw value shown above`,
                   rejected: `Auto offset REJECTED (current was flowing) — using the ${sensor.board.name} default I₀ = ${sensor.I0.toFixed(3)} A; set the Variac to 0 and press Re-zero`};
  sNote.innerHTML = zeroTxt[sensor.zero] || sNoteDefault;
  btnZero.disabled = sensor.kind !== 'serial' || !ZERO_CAL_S;
  btnSerial.textContent = sensor.kind === 'serial' ? 'Disconnect' : 'Connect Arduino';
  btnDemo.textContent = sensor.kind === 'demo' ? 'Stop demo' : 'Demo signal';
  btnDemo.disabled = sensor.kind === 'serial';
  if (HAS_SERIAL) btnSerial.disabled = sensor.kind === 'demo';
}
function startZeroCal() {
  sensor.zero = ZERO_CAL_S > 0 ? 'measuring' : 'off';
  sensor.zeroT0 = 0; sensor.zeroBuf = [];
}
function sensorPush(I_raw) {
  sensor.lastRaw = I_raw; sensor.lastWall = performance.now(); sensor.n++;
  if (I_raw > SENSOR_INVALID_A) {   // same rule as LiveDriver: ignore, hold the last valid I
    sensor.state = 'live';
    sensor.msg = `invalid reading ${I_raw.toFixed(0)} (raw ADC? check firmware) — ignored`;
    paintSensor(); return;
  }
  if (sensor.zero === 'measuring') {
    if (!sensor.zeroT0) sensor.zeroT0 = sensor.lastWall;
    if (Number.isFinite(I_raw)) sensor.zeroBuf.push(I_raw);
    sensorDriveI = 0.0;                    // Variac at 0 while the offset is measured
    if (sensor.lastWall - sensor.zeroT0 >= ZERO_CAL_S * 1000 && sensor.zeroBuf.length) {
      const I0 = Math.sqrt(sensor.zeroBuf.reduce((a, x) => a + x * x, 0) / sensor.zeroBuf.length);
      if (I0 > ZERO_CAL_MAX_A) { sensor.zero = 'rejected'; sensor.I0 = sensor.board.I0; }
      else { sensor.zero = 'done'; sensor.I0 = I0; }
    }
  } else {
    sensorDriveI = conditionI(I_raw);
  }
  sensor.state = 'live'; sensor.msg = '';
  paintSensor();
}
function startSource(kind) {
  sensor.kind = kind; sensor.state = kind === 'serial' ? 'connecting' : 'waiting';
  sensor.n = 0; sensor.lastRaw = NaN; sensor.msg = '';
  sensor.I0 = 0;
  if (kind === 'serial') startZeroCal(); else sensor.zero = 'off';   // demo is already clean
  sensorDriveI = null; lockControls(true); setPaused(false); paintSensor();
}
async function stopSensor(msg = '') {
  const {reader, port, timer} = sensor;
  sensor.kind = null; sensor.reader = sensor.port = sensor.timer = null;
  if (timer) clearInterval(timer);
  if (reader) { try { await reader.cancel(); } catch (e) {} }
  if (port) { try { await port.close(); } catch (e) {} }
  sensorDriveI = null; lockControls(false);
  sensor.state = msg ? 'error' : 'off'; sensor.msg = msg;
  paintSensor();
}
function startDemo() {
  // Stand-in for the rig: the Variac held at the 5 A operating point + ACS712-like
  // noise, 1 sample/s (same as data_io.py's mock source). Real time, like the rig.
  startSource('demo');
  const gauss = () => Math.sqrt(-2 * Math.log(1 - Math.random())) * Math.cos(2 * Math.PI * Math.random());
  sensor.timer = setInterval(() => sensorPush(5.0 + 0.03 * gauss()), 1000);
}
async function connectSerial(port = null) {
  if (!port) {   // a NEW port needs this click (user gesture); a granted one is passed in
    try { port = await navigator.serial.requestPort(); }
    catch (e) { sensor.msg = 'no port selected'; paintSensor(); return; }
  }
  startSource('serial');
  sensor.board = boardOffset(port.getInfo ? port.getInfo() : null);
  console.log(`[sensor] ${sensor.board.name} (USB ${sensor.board.id || '?'}) -> default I0 ${sensor.board.I0} A`);
  try { await port.open({baudRate: SENSOR_BAUD}); }
  catch (e) { await stopSensor(`cannot open port (${e.message})`); return; }
  sensor.port = port; sensor.state = 'waiting'; paintSensor();   // Arduino reboots ~2 s on open
  const decoder = new TextDecoderStream();
  const piped = port.readable.pipeTo(decoder.writable).catch(() => {});
  const reader = decoder.readable.getReader();
  sensor.reader = reader;
  let buf = '';
  try {
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      buf += value;
      let nl;
      while ((nl = buf.indexOf('\n')) >= 0) {
        const I = parseSensorLine(buf.slice(0, nl));
        buf = buf.slice(nl + 1);
        if (I !== null && sensor.port === port) sensorPush(I);
      }
    }
  } catch (e) { /* unplugged -> handled below */ }
  finally { try { reader.releaseLock(); } catch (e) {} await piped; }
  if (sensor.port === port) {   // stream ended without the user pressing Disconnect
    await stopSensor('serial link lost');
    setPaused(true);            // do not keep simulating on an unknown current
  }
}
btnSerial.onclick = () => sensor.kind === 'serial' ? stopSensor() : connectSerial();
// `?sensor` in the URL (RUN.py --sensor): open in Sensor mode and connect to an
// Arduino this browser was already allowed to use. Web Serial needs ONE click on
// "Connect Arduino" the very first time (browser security rule); after that the
// page reconnects by itself, also when the Arduino is unplugged and plugged back.
const sensorModeBtn = document.querySelector('.sc-btn[data-mode="sensor"]');
async function autoConnectSerial() {
  if (!HAS_SERIAL || sensor.kind) return;
  const ports = await navigator.serial.getPorts();
  if (ports.length) { connectSerial(ports[0]); return; }
  sensor.msg = 'first time: click Connect Arduino and pick the port'; paintSensor();
}
if (new URLSearchParams(location.search).has('sensor')) {
  sensorModeBtn.click();
  if (HAS_SERIAL) autoConnectSerial();
  else { sensor.msg = 'open this page in Chrome or Edge (Web Serial)'; paintSensor(); }
}
if (HAS_SERIAL) navigator.serial.addEventListener('connect', () => {
  if (sensorModeBtn.classList.contains('active')) autoConnectSerial();
});
btnDemo.onclick   = () => sensor.kind === 'demo' ? stopSensor() : startDemo();
btnZero.onclick   = () => { startZeroCal(); paintSensor(); };
setInterval(() => {   // watchdog: flag a silent source, keep holding the last I
  if (sensor.state === 'live' && performance.now() - sensor.lastWall > SENSOR_STALE_S * 1000) {
    sensor.state = 'stale'; paintSensor();
  }
}, 500);
paintSensor();
const sensorDebug = {parseSensorLine, conditionI, push: sensorPush, startDemo, stopSensor,
                     startSource, startZeroCal, boardOffset,
                     setBoard: info => { sensor.board = boardOffset(info); },
                     get state() { return sensor.state; }, get driveI() { return sensorDriveI; },
                     get zero() { return {state: sensor.zero, I0: sensor.I0}; },
                     get note() { return sNote.textContent; }};

// ── Main animation loop ───────────────────────────────────────────────────────
let lastWall = performance.now();
let recordTimer = 0;

function loop() {
  requestAnimationFrame(loop);
  const now = performance.now();
  let wall_dt = (now - lastWall) / 1000;
  lastWall = now;
  // cap at 100ms (tab-hidden guard) -- except while the sensor drives the model:
  // then sim time must track wall time, so a throttled background tab catches up
  // on return (substepping below keeps that stable), bridged with the held I.
  if (wall_dt > 0.1) wall_dt = sensorDriveI !== null ? Math.min(wall_dt, 3600) : 0.1;

  const speed = Math.pow(10, +sS.value);
  const dt_sim = wall_dt * speed;      // simulated seconds per frame

  if (!paused) {
    // Sub-step: integrate dt_sim in multiple smaller steps for stability
    const nSub = Math.max(1, Math.ceil(dt_sim / (ROM.tau * 0.05)));
    const dt   = dt_sim / nSub;
    for (let i = 0; i < nSub; i++) {
      const I_now = Math.max(0, Math.min(getI(), 20.0));
      romStep(I_now, dt);
    }

    // Refresh the live disc min/max (combined eddy + hot-air field) ONCE per frame.
    // Everything downstream (colour scale, T_max, history, telemetry) reads it.
    updateDiscRange();

    // Record history every sim.hist_dt sim-seconds (starts at 1 s)
    recordTimer += dt_sim;
    if (recordTimer >= (sim.hist_dt || 1.0)) {
      recordTimer = 0;
      const Tmax = plateTmax();
      sim.hist_t.push(sim.t);
      sim.hist_Tmax.push(Tmax);
      sim.hist_T_inner.push(sim.T.inner);
      sim.hist_T_outer.push(sim.T.outer);
      sim.hist_I.push(getI());
      // Max 3600 points, but the START of the run is never dropped (the chart
      // shows t=0 -> now): over the cap, keep every 2nd point and double the
      // sampling interval. CSV export then has the same (coarser) spacing.
      if (sim.hist_t.length > 3600) {
        for (const k of ['hist_t', 'hist_Tmax', 'hist_T_inner', 'hist_T_outer', 'hist_I'])
          sim[k] = sim[k].filter((_, i) => i % 2 === 0);
        sim.hist_dt = (sim.hist_dt || 1.0) * 2;
      }
    }

    updateHeatParticles(dt_sim);
  }

  // Paint meshes
  updateColorEasing(wall_dt);
  paintMesh(baseM);
  paintMesh(coilInnerM);
  paintMesh(coilOuterM);
  paintMesh(woodM);
  paintMesh(plateM);
  updateCoilGlow();   // emissive ∝ coil T — hot windings visibly light up (IR look)
  updateScaleBar(wall_dt);

  // Update disc Z position — spring-mass response toward z_eq(I): the disc bobs
  // for ~10s after a current step, then settles (matches the real rig behaviour).
  // Integrated in SIM time (dt_sim), so the speed slider speeds up/slows down
  // the bob-and-settle exactly like the thermal side of the sim.
  const I_display = getI();
  if (!paused) levStep(I_display, dt_sim);
  const liftY = levLiftY();
  plateM.mesh.position.y = -ctr.y + liftY;

  // Update telemetry
  const Tmax  = plateTmax();

  document.getElementById('vT').textContent  = sim.t < 120
    ? sim.t.toFixed(1)+' s' : (sim.t/60).toFixed(2)+' min';
  document.getElementById('vP').textContent  = totalPower(I_display).toFixed(1)+' W';
  document.getElementById('hdrIBadge').textContent =
    `I = ${I_display.toFixed(2)} A, ~${dialToVoltageV(dialFromCurrentA(I_display)).toFixed(0)} V`;

  // Power breakdown: disc eddy vs coil ohmic
  const s2disp = (I_display / ROM.I_ref) ** 2;
  const P_disc = ROM.P_ref * s2disp;
  const P_coil_now = (LUMPED.nodes.inner.P_ref + LUMPED.nodes.outer.P_ref) * s2disp;
  document.getElementById('vPdisc').textContent = P_disc.toFixed(2) + ' W';
  document.getElementById('vPcoil').textContent = P_coil_now.toFixed(1) + ' W';

  // Live gap = the spring-mass state, so telemetry shows the bob-and-settle too.
  document.getElementById('tLevGap').textContent =
    lev.z.toFixed(1) + ' mm';
  document.getElementById('tPmax').textContent  = Tmax.toFixed(2)+' °C';
  setV('tIn',  sim.T.inner); setV('tOut', sim.T.outer); setV('tFe',  sim.T.iron);

  {
    const dTh = T_COIL_HOT - T_AMB_JS;
    setSwatch('bPl',  writeRamp,       (Tmax - dispLo) / Math.max(1e-6, dispHi - dispLo));
    setSwatch('bIn',  writeRampCopper, (sim.T.inner - T_AMB_JS) / dTh);
    setSwatch('bOut', writeRampCopper, (sim.T.outer - T_AMB_JS) / dTh);
    setSwatch('bFe',  writeRampMetal,  (sim.T.iron  - T_AMB_JS) / dTh * IRON_BOOST);
  }
  liveAirBot();

  // EM field telemetry: |B| and |J_e| are linear in A_φ, hence linear in I (the
  // baked maps are at I_em_ref) — unlike thermal power, which goes as I².
  const emScale = I_display / ROM.I_em_ref;
  document.getElementById('tBplate').textContent = (ROM.B_max * emScale).toFixed(3) + ' T';
  document.getElementById('tJmax').textContent = (ROM.J_max * emScale * 1e-6).toFixed(3) + ' A/mm²';

  // Field-line "flow" pulse + opacity + DENSITY, tied to I_display: the FIELD SHAPE
  // is static (linear problem — each line's geometry doesn't change with I), but
  // |B| ∝ I, so the visual density must grow with I too: below I_em_ref the weakest
  // lines are culled (only the strong flux tubes near the coils survive), the full
  // baked set shows at I_em_ref, and above it the dash gaps shrink (denser flow) on
  // top of the existing speed/brightness scaling. B=0 reads as still+invisible.
  if (fieldLineGroup.visible) {
    if (Math.abs(liftY - flLiftY) > 0.05) layoutFieldLines(liftY);
    const iFrac = Math.min(2.0, Math.abs(emScale));   // 0->0A, 1->I_em_ref, capped at 2x
    flFlowPhase += wall_dt * FIELD_LINE_FLOW_SPEED * iFrac;
    const visFrac  = Math.min(1, iFrac);              // fraction of lines shown
    const gapScale = 1 / Math.max(1, iFrac);          // >I_ref: shorter gaps = denser dashes
    for (const o of fieldLineMats) {
      o.line.visible  = o.rankFrac < visFrac;
      o.mat.dashOffset = -flFlowPhase;
      o.mat.gapSize    = FL_GAP_BASE * gapScale;
      o.mat.opacity = fieldLineOpacityPct * (0.15 + 0.85 * o.amp) * Math.min(1, iFrac);
    }
  }

  drawChart();
  drawCurrentChart();
  controls.update();
  scene.fog.density = FOG_BASE * FOG_REF_DIST / Math.max(1, camera.position.distanceTo(controls.target));
  renderer.render(scene, camera);
  updateCallouts(wall_dt);
}

addEventListener('resize', () => {
  renderer.setSize(innerWidth, innerHeight);
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
});

TWIN_T.scene_built = performance.now();
loop();                                    // first simulation step + first render
TWIN_T.first_step = performance.now();
window.__twinTiming = TWIN_T;
console.log('[TIME] page load, ms since navigation start:', TWIN_T);
</script></body></html>"""


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("stl", nargs="?", default=os.path.join(HERE, "3D_model.stl"),
                     help="unused (body geometry is 100%% procedural) -- kept for CLI compatibility")
    ap.add_argument("--plate-radius", type=float, default=None,
                     help="Override plate_material.radius_mm (mm) for this build only "
                          "(params.yaml default is unchanged). E.g. --plate-radius 75 for "
                          "the Ø150mm disc. Output gets a _R<radius> filename suffix.")
    ap.add_argument("--bake-key", action="store_true",
                     help="Bake the REAL Google Weather API key (from local/.env.local or "
                          "GOOGLE_WEATHER_API_KEY) into the output HTML. DEFAULT (flag absent): "
                          "always writes the literal placeholder 'YOUR_KEY_HERE', even if a real "
                          "key is available locally -- do not pass this flag for a build you "
                          "intend to commit.")
    ap.add_argument("--out", default=None,
                     help="Output filename inside outputs/ (overrides the default name). "
                          "RUN.py uses digital_twin_fem_live.html (gitignored) for key builds.")
    args = ap.parse_args()

    out_dir = os.path.join(HERE, "outputs")
    os.makedirs(out_dir, exist_ok=True)
    if args.out is not None:
        out_name = os.path.basename(args.out)
    elif args.plate_radius is not None:
        out_name = f"digital_twin_fem_R{int(round(args.plate_radius))}.html"
    else:
        out_name = "digital_twin_fem.html"
    out = os.path.join(out_dir, out_name)
    build(args.stl, out, plate_radius_mm=args.plate_radius, bake_key=args.bake_key)
