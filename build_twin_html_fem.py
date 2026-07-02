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
import sys, os, struct, base64, json, math, copy
import numpy as np
from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from config import load_config, Geometry
from em_solver import compute_losses, compute_lift_force
from rom import ThermalROM


# ─── WP-C (2026-07-02) lift-force anchors, staged for WP-D ────────────────────
# NOT wired into anything live yet -- the JS levitation-gap block (~line 1130,
# "Z_GAP_5A_MM"/"Z_DECAY_MM") still owns its own hardcoded constants (WP-A/WP-D
# territory, see docs/PLAN_SIM_FEEDBACK_2026-07-02.md "Bản đồ conflict"). This
# dict is WP-C's deliverable for WP-D to fold into params.yaml (`levitation:`
# block) + the PARAMS JSON export, one entry per plate_library radius.
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
# z=5mm: z0=(5-1)/ln(F(1mm)/F(5mm)) -- NOTE this differs from the z0=21.4mm
# quoted in the 2026-07-01 CLAUDE.md entry for R=80, which instead anchored the
# second point at the F=F_grav crossing itself (z0=(z_eq-1)/ln(F(1mm)/F_grav));
# the two methods disagree by ~1.5x (13.6mm vs 21.4mm) because F(z) isn't a
# clean single exponential over that range. This dict uses the F1/F5 method
# consistently for both radii (reproducible from compute_lift_force() alone,
# no F_grav/mass dependency baked into the shape fit). Treat z0 as order-of-
# magnitude regardless of method (mesh-sensitive -- see the WP-C report for a
# fine_step_mm convergence check that moved z_eq(R=80) by ~0.7mm and
# I_min_lev(R=101) by ~0.5A between fine_step=2.0mm and 1.0mm).
def _lev_anchor(radius_mm: float, plate_thickness_mm: float = 3.0) -> dict:
    """Recompute the lift-force anchors for one plate radius. Re-solves EM from
    scratch at the given radius (NOT scaled from another radius's result) --
    see the WP-C module docstring above for why that matters once the disc
    overlaps the outer_iron_ring / outer-coil field region."""
    cfg = load_config()
    R_m = radius_mm * 1e-3
    t_m = plate_thickness_mm * 1e-3
    cfg.raw["plate_material"]["radius_mm"] = float(radius_mm)
    cfg.raw["excitation"]["current_A"] = 5.0 * math.sqrt(2.0)   # I_peak convention
    m_kg = cfg.plate["rho_kg_per_m3"] * math.pi * R_m ** 2 * t_m
    F_grav = m_kg * 9.81

    def F_at(z_mm):
        cfg.raw["plate_material"]["z_bottom_mm"] = float(z_mm)
        cfg.geometry = Geometry(plate_radius_m=R_m, plate_thickness_m=t_m,
                                 plate_z_bottom_m=float(z_mm) * 1e-3)
        return compute_lift_force(cfg)

    F1, F38, F5 = F_at(1.0), F_at(3.8), F_at(5.0)
    z0_mm = (5.0 - 1.0) / math.log(F1 / F5)

    out = {"radius_mm": radius_mm, "mass_kg": round(m_kg, 5), "F_grav_N": round(F_grav, 4),
           "F_at_1mm_N": round(F1, 4), "F_at_3p8mm_N": round(F38, 4),
           "z0_decay_mm": round(z0_mm, 2)}
    if F38 >= F_grav:
        zs = np.array([1.0, 3.8, 5.0]); Fs = np.array([F1, F38, F5])
        order = np.argsort(Fs)
        out["z_eq_5A_mm"] = round(float(np.interp(F_grav, Fs[order], zs[order])), 2)
        out["levitates_at_5A_rms"] = True
    else:
        out["I_min_lev_A_rms"] = round(5.0 * math.sqrt(F_grav / F38), 2)
        out["levitates_at_5A_rms"] = False
    return out


# LEV_ANCHORS: computed once (see WP-C report / commit message for the printed
# derivation); NOT auto-recomputed at every build() call (EM solves are ~seconds
# each and this isn't on the hot path) -- call _lev_anchor(radius_mm) directly
# if a new plate_library radius needs staging.
LEV_ANCHORS = {
    80.0:  {"radius_mm": 80.0,  "mass_kg": 0.16286, "F_grav_N": 1.5977,
            "F_at_1mm_N": 1.8462, "F_at_3p8mm_N": 1.6877, "z0_decay_mm": 13.63,
            "z_eq_5A_mm": 4.15, "levitates_at_5A_rms": True},
    101.0: {"radius_mm": 101.0, "mass_kg": 0.25958, "F_grav_N": 2.5465,
            "F_at_1mm_N": 1.6591, "F_at_3p8mm_N": 1.5318, "z0_decay_mm": 14.02,
            "I_min_lev_A_rms": 6.45, "levitates_at_5A_rms": False},
}


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

    def coil_C_solid(c):
        r_mean = (c["r_inner_mm"] + c["r_outer_mm"]) / 2 * mm
        Vc = c["turns"] * (2 * math.pi * r_mean) * A_wire
        return 8960.0 * 385.0 * Vc  # rho_Cu * cp_Cu * V_Cu, full solid-copper mass

    p = cfg.plate
    V_plate = math.pi * (p["radius_mm"] * mm) ** 2 * (p["thickness_mm"] * mm)
    C_plate = p["rho_kg_per_m3"] * p["cp_J_per_kgK"] * V_plate

    P_inner = 0.5 * cfg.I ** 2 * coil_R(co["inner"])
    P_outer = 0.5 * cfg.I ** 2 * coil_R(co["outer"])
    P_iron = em["P_iron_W"]
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
        "nodes": {
            "inner": {
                "P_ref":  P_inner,
                "C":      coil_C_solid(co["inner"]) * coil_C_scale,       # surface (IR-visible) mass
                "C_deep": coil_C_solid(co["inner"]) * (1 - coil_C_scale),  # winding-core mass
                "G_wind": G_wind,   # surface<->winding-core conductance (fit 2026-07-02)
                "hA":     hA_inner,
                "dT_cal": dT_cal["inner"],
            },
            "outer": {
                "P_ref":  P_outer,
                "C":      coil_C_solid(co["outer"]) * coil_C_scale,
                "C_deep": coil_C_solid(co["outer"]) * (1 - coil_C_scale),
                "G_wind": G_wind,
                "hA":     hA_outer,
                "dT_cal": dT_cal["outer"],
            },
            "iron": {
                "P_ref":  P_iron,
                "C":      0.5 * C_plate,
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
    exact radii (a genuine geometric gap -- see 3D_MODEL_UPDATE_PLAN.md), so they can't
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


# ─── Main build function ──────────────────────────────────────────────────────

def build(stl_path: str | None, out_path: str, plate_radius_mm: float | None = None) -> None:
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
    em = compute_losses(cfg)
    print(f"P_plate={em['P_plate_W']*1e3:.1f} mW  "
          f"P_coil={em['P_coil_W']:.1f} W  P_iron={em['P_iron_W']*1e3:.0f} mW")

    # 1a. EM field visualization data (optional "B Field" / "Eddy J" layers) —
    #     baked once at cfg.I; runtime scales by (I_display/I_em_ref) since both
    #     |B| and |J_e| are linear in A_φ, hence linear in I (q~I² is |J_e|², not J_e).
    print("[EMVIZ] Field lines + eddy density map ...", end=" ", flush=True)
    je_field = compute_eddy_field(em)
    field_lines, B_max = compute_em_field_lines(em, cfg)
    print(f"{len(field_lines)} field lines, B_max={B_max:.3f} T")

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
    B_max_iron, _ = check_saturation(em["res"], cfg)
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
        "B_max_iron":  round(B_max_iron, 3),
        "B_sat":       B_sat,
        "saturated":   bool(B_max_iron > B_sat),
        "I_em_ref":    float(cfg.I),     # current at which the EM viz (B/J_e) was baked
        "B_max":       round(B_max, 4),  # peak nodal |B| [T] at I_em_ref
        "J_max":       round(J_max, 1),  # peak disc |J_e| [A/m²] at I_em_ref
    }
    lumped = lumped_physics(cfg, em)
    params = {"rom": rom_params, "lumped": lumped, "field_lines": field_lines}

    # 5. Encode binary data as base64
    pos_b64   = base64.b64encode(V.reshape(-1).astype("<f4").tobytes()).decode()
    reg_b64   = base64.b64encode(region.tobytes()).decode()
    dT_b64    = base64.b64encode(dTe_vtx.tobytes()).decode()
    dtair_b64 = base64.b64encode(dTa_vtx.tobytes()).decode()
    je_b64    = base64.b64encode(Jn_vtx.tobytes()).decode()

    html = (TEMPLATE
            .replace("__POS_B64__",   pos_b64)
            .replace("__REG_B64__",   reg_b64)
            .replace("__DT_B64__",    dT_b64)
            .replace("__DTAIR_B64__", dtair_b64)
            .replace("__JE_B64__",    je_b64)
            .replace("__PARAMS__",    json.dumps(params)))

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    sz_kb = len(html) / 1024
    print(f"\nWrote {out_path}  ({sz_kb:.0f} KB) — double-click to run.")


# ─── HTML / JS template ───────────────────────────────────────────────────────

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Digital Twin — TEMF Thermal Levitator</title>
<style>
:root{
  --bg:#0f0f1e; --panel-bg:rgba(10,10,22,.72); --panel-border:#2a3050;
  --text:#ccc; --accent:#7ab4ff; --muted:#9ab;
  --hdr-bg:linear-gradient(135deg,rgba(14,16,30,.94),rgba(20,26,48,.88));
}
body.light{
  --bg:#eef1f8; --panel-bg:rgba(255,255,255,.78); --panel-border:#c4cce4;
  --text:#1c2333; --accent:#1d5fd6; --muted:#5a6478;
  --hdr-bg:linear-gradient(135deg,rgba(255,255,255,.94),rgba(238,242,250,.9));
}
*{box-sizing:border-box}
body{margin:0;overflow:hidden;background:var(--bg);color:var(--text);
     font-family:'Segoe UI',Tahoma,sans-serif;font-size:13px;transition:background .25s}

/* ── Header bar ──────────────────────────────────────────────────────────── */
#headerBar{position:fixed;top:0;left:0;right:0;height:54px;z-index:30;
  display:flex;align-items:center;justify-content:space-between;gap:14px;
  padding:0 18px;background:var(--hdr-bg);border-bottom:1px solid var(--panel-border);
  backdrop-filter:blur(12px);color:var(--text)}
.brand{display:flex;align-items:center;gap:10px;min-width:0}
.brand .logo{font-size:1.35rem;line-height:1}
.brand .titles{display:flex;flex-direction:column;line-height:1.15;min-width:0}
.brand .title{font-weight:600;font-size:.92rem;color:var(--accent);white-space:nowrap}
.brand .subtitle{font-size:.68rem;color:var(--muted);white-space:nowrap}
.hdr-mid{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.hdr-badge{font-size:.68rem;padding:3px 9px;border-radius:12px;border:1px solid var(--panel-border);
  background:rgba(127,127,160,.08);color:var(--muted);white-space:nowrap}
.hdr-right{display:flex;align-items:center;gap:8px}
.iconbtn{background:none;border:1px solid var(--panel-border);color:var(--text);
  border-radius:6px;padding:6px 10px;cursor:pointer;font-size:.78rem;white-space:nowrap}
.iconbtn:hover{border-color:var(--accent)}

#ui{position:absolute;top:66px;left:12px;display:flex;gap:14px;
    pointer-events:none;z-index:10}
.panel{background:var(--panel-bg);padding:0;border-radius:12px;
       border:1px solid var(--panel-border);pointer-events:auto;backdrop-filter:blur(12px);
       box-shadow:0 8px 24px rgba(0,0,0,.35);width:260px;overflow:hidden;
       transition:background .25s,border-color .25s}
.panel-head{margin:0;font-size:.95rem;color:var(--accent);
   border-bottom:1px solid var(--panel-border);padding:12px 16px;cursor:pointer;
   display:flex;justify-content:space-between;align-items:center;user-select:none}
.panel-head .chev{font-size:.75rem;color:var(--muted);transition:transform .2s}
.panel.collapsed .chev{transform:rotate(-90deg)}
.panel.collapsed .panel-body{display:none}
.panel-body{padding:14px 16px}
.cg{margin-bottom:10px}
.cg label{display:flex;justify-content:space-between;margin-bottom:4px;
          font-size:.82rem;color:var(--muted)}
input[type=range]{width:100%;cursor:pointer;accent-color:#4facfe}
.row{display:flex;justify-content:space-between;margin-bottom:6px;
     font-size:.82rem;align-items:center;color:var(--text)}
.box{width:13px;height:13px;border-radius:3px;margin-right:7px;
     display:inline-block;vertical-align:middle}
.val{font-family:monospace;font-weight:bold;font-size:.95rem;color:var(--text)}
.valbig{font-family:monospace;font-weight:bold;font-size:1.2rem;color:#ffcc44}
.note{font-size:.72rem;color:var(--muted);line-height:1.4;margin-top:8px}
.badge{display:inline-block;background:#1a3a1a;color:#66ff88;
       border:1px solid #44aa44;border-radius:4px;padding:2px 7px;
       font-size:.75rem;margin-top:4px}
/* scenario buttons */
.sc-group{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:10px}
.sc-btn{flex:1;background:rgba(127,127,160,.08);color:var(--muted);border:1px solid var(--panel-border);
        border-radius:5px;padding:4px 0;cursor:pointer;font-size:.78rem;
        transition:all .15s}
.sc-btn.active{background:#1e3a5f;color:#7ab4ff;border-color:#4facfe}
button#reset{width:100%;background:#2a1a1a;color:#f88;border:1px solid #633;
             border-radius:5px;padding:5px;cursor:pointer;font-size:.8rem}
.export-row{display:flex;gap:6px;margin-top:8px}
.export-row .sc-btn{padding:6px 0}
#chart,#chartI{background:#0a0a14;border-radius:6px;border:1px solid var(--panel-border);
       display:block;margin-top:8px;width:100%}
.chart-legend{display:flex;gap:10px;font-size:.68rem;color:var(--muted);margin-top:4px;flex-wrap:wrap}
.chart-legend i{display:inline-block;width:11px;height:0;border-top:2px solid;margin-right:4px;vertical-align:middle}
.chart-tip{position:fixed;background:rgba(0,0,0,.85);color:#fff;padding:4px 8px;
  border-radius:4px;font-size:.72rem;pointer-events:none;z-index:60;display:none;
  border:1px solid #456;font-family:monospace}
#scaleBar{margin-top:10px;height:14px;border-radius:4px;position:relative;
          background:linear-gradient(to right,#0000ff,#00ffff,#00ff00,#ffff00,#ff0000)}
#scaleBar .marker{position:absolute;top:-3px;width:2px;height:20px;background:#fff;
  box-shadow:0 0 3px #000}
.scaleLabel{display:flex;justify-content:space-between;
            font-size:.68rem;color:var(--muted);margin-top:3px}
hr.div{border:0;border-top:1px solid var(--panel-border);margin:8px 0}

/* ── 3D labels (CSS2DRenderer) ───────────────────────────────────────────── */
.label3d{font-family:'Segoe UI',Tahoma,sans-serif;font-size:11px;color:#cfe3ff;
  background:rgba(10,15,30,.6);padding:3px 9px;border-radius:10px;
  border:1px solid rgba(122,180,255,.35);white-space:nowrap;
  transform:translate(-50%,-100%);pointer-events:none}
.label3d.iron{color:#ffd9a8;border-color:rgba(255,170,80,.4)}

#pausedBadge{position:fixed;top:64px;left:50%;transform:translateX(-50%);
  background:rgba(255,80,80,.15);color:#ff8888;border:1px solid #ff8888;
  border-radius:6px;padding:4px 14px;font-size:.78rem;letter-spacing:.05em;
  z-index:25;display:none}

@media (max-width:760px){
  #headerBar{height:auto;flex-wrap:wrap;padding:8px 12px;gap:6px}
  .hdr-mid{order:3;width:100%}
  #ui{flex-direction:column;top:auto;position:relative;left:0;margin:90px 10px 10px;
      pointer-events:auto}
  .panel{width:100%}
}
</style></head><body>

<div id="headerBar">
  <div class="brand">
    <span class="logo">🧲</span>
    <div class="titles">
      <span class="title">Digital Twin — TEMF Thermal Levitator</span>
      <span class="subtitle">Real-time thermal simulation · TEAM 28</span>
    </div>
  </div>
  <div class="hdr-mid">
    <span class="hdr-badge">FEM ROM (axisymmetric)</span>
    <span class="hdr-badge">T_amb = 29 °C</span>
    <span class="hdr-badge">I = 5 A, 220 V</span>
  </div>
  <div class="hdr-right">
    <button class="iconbtn" id="themeToggle">☀️ Light</button>
  </div>
</div>
<div id="pausedBadge">⏸ PAUSED — press Space to resume</div>

<div id="ui">
  <!-- Panel 1: Controls -->
  <div class="panel" id="panelControls">
    <div class="panel-head"><span>Physics Controls</span><span class="chev">▾</span></div>
    <div class="panel-body">
    <div class="sc-group" id="scGroup">
      <button class="sc-btn active" data-sc="step">Step</button>
      <button class="sc-btn" data-sc="ramp">Ramp</button>
      <button class="sc-btn" data-sc="sine">Sine</button>
      <button class="sc-btn" data-sc="pulse">Pulse</button>
    </div>
    <div class="cg">
      <label><span>Current I</span><span id="vI" class="val">5.0 A</span></label>
      <input type="range" id="sI" min="0" max="20" step="0.5" value="5">
    </div>
    <div class="cg">
      <label><span>Time speed</span><span id="vS" class="val">1.0×</span></label>
      <input type="range" id="sS" min="0" max="2.301" step="0.01" value="0">
    </div>
    <button id="reset">↺ Reset temperatures</button>
    <div class="badge">FEM ROM (axisymmetric)</div>
    <hr class="div">
    <div style="font-size:.78rem;color:var(--muted);margin-bottom:4px">Heat sources</div>
    <div class="row" style="font-size:.79rem">
      <span>⚡ Disc eddy currents</span>
      <span class="val" id="vPdisc" style="color:#7ab4ff">0.0 W</span></div>
    <div class="row" style="font-size:.79rem">
      <span>🔥 Coils (Ohmic)</span>
      <span class="val" id="vPcoil" style="color:#ff8844">0.0 W</span></div>
    <p class="note">
      The disc heats up from <b>2 sources</b>, each with its OWN speed:<br>
      ① <b>Foucault eddy currents</b> (~4K) induced in the disc — appear <i>instantly</i> with I².<br>
      ② <b>Hot air from the coils</b> (~8K) — coils sit only 3.8mm below the disc. This part is
      <i>slow</i>: the copper mass takes ~25min to warm, so the bottom air lags behind I².<br>
      Total ΔT_ss ≈ 11K — hot air is the <i>dominant</i> (but delayed) heat source for the disc.
    </p>
    <hr class="div">
    <div style="font-size:.78rem;color:var(--muted);margin-bottom:4px">Visualization</div>
    <div class="sc-group" id="vizGroup">
      <button class="sc-btn active" data-viz="thermal">Thermal</button>
      <button class="sc-btn" data-viz="bfield">🧲 B Field</button>
      <button class="sc-btn" data-viz="eddy">⚡ Eddy J</button>
      <button class="sc-btn" data-viz="combined">Combined</button>
    </div>
    <div class="cg">
      <label><span>Field line opacity</span><span id="vFLO" class="val">70%</span></label>
      <input type="range" id="sFLO" min="0" max="100" step="1" value="70">
    </div>
    <p class="note">⌨ Space=pause · R=reset · 1-4=scenario · +/−=speed</p>
    </div>
  </div>

  <!-- Panel 2: Telemetry -->
  <div class="panel" id="panelTelemetry">
    <div class="panel-head"><span>Thermal Telemetry</span><span class="chev">▾</span></div>
    <div class="panel-body">
    <div class="row"><span>Sim time</span>
      <span class="val" id="vT">0 s</span></div>
    <div class="row"><span>Current I(t)</span>
      <span class="val" id="vIC">0.0 A</span></div>
    <div class="row"><span>Total heat in</span>
      <span class="val" id="vP">0.0 W</span></div>
    <hr class="div">
    <div class="row">
      <div><span class="box" id="bPl" style="background:#2255aa"></span>
        <b>Plate T_max</b></div>
      <span class="valbig" id="tPmax">25.0 °C</span></div>
    <div class="row">
      <div><span>Plate T_mean</span></div>
      <span class="val" id="tPmean">25.0 °C</span></div>
    <div class="row">
      <div><span>Plate T_ss (target)</span></div>
      <span class="val" id="tPss" style="color:#44ff88">25.0 °C</span></div>
    <div class="row" style="font-size:.68rem;color:var(--muted);line-height:1.3">
      <span>Disc colours = <i>relative</i> scale (cool→hot within plate).
      Bottom face runs hotter than the top as the coils' hot air builds up.</span></div>
    <hr class="div">
    <div class="row">
      <div><span class="box" id="bIn"></span>Inner coil (1000t)</div>
      <span class="val" id="tIn">25.0 °C</span>
      <span style="font-size:.7rem;color:#ff8844" id="tInSS"></span></div>
    <div class="row">
      <div><span class="box" id="bOut"></span>Outer coil (500t)</div>
      <span class="val" id="tOut">25.0 °C</span>
      <span style="font-size:.7rem;color:#ff8844" id="tOutSS"></span></div>
    <div class="row">
      <div><span class="box" id="bFe"></span>Iron core</div>
      <span class="val" id="tFe">25.0 °C</span></div>
    <hr class="div">
    <div class="row" style="font-size:.78rem">
      <span>Bottom air T (disc)</span>
      <span class="val" id="tAirBot" style="color:#ffaa44">—</span></div>
    <div class="row">
      <div>Levitation Gap</div>
      <span class="val" id="tLevGap" style="color:#aaddff">0.0 mm</span></div>
    <div class="row" style="font-size:.78rem" id="satRow">
      <span>Iron core B_max</span>
      <span class="val" id="tBmax" style="color:#88ff88">—</span></div>
    <div class="row" style="font-size:.78rem">
      <span>🧲 Plate |B| max</span>
      <span class="val" id="tBplate" style="color:#7ab4ff">—</span></div>
    <div class="row" style="font-size:.78rem">
      <span>⚡ Disc |J_e| max</span>
      <span class="val" id="tJmax" style="color:#ffe066">—</span></div>
    <div id="scaleBar"><div class="marker" id="scaleMarkerLo"></div><div class="marker" id="scaleMarkerHi"></div></div>
    <div class="scaleLabel" id="scaleTicks"></div>
    <div class="row" style="font-size:.7rem;margin-top:4px">
      <span>Current range</span><span class="val" id="scaleCurRange" style="font-size:.72rem">—</span></div>
    <button class="sc-btn" id="scaleModeBtn" style="width:100%;margin-top:4px">Scale: Auto</button>
    </div>
  </div>

  <!-- Panel 3: charts -->
  <div class="panel" id="panelChart">
    <div class="panel-head"><span>Time History</span><span class="chev">▾</span></div>
    <div class="panel-body">
    <div style="font-size:.78rem;color:var(--muted);margin-bottom:2px">Temperatures vs time</div>
    <canvas id="chart" width="228" height="150"></canvas>
    <div class="chart-legend">
      <span><i style="border-color:#ff6644"></i>Plate T_max</span>
      <span><i style="border-color:#ff8844"></i>Inner coil</span>
      <span><i style="border-color:#ffcc44"></i>Outer coil</span>
      <span><i style="border-color:#44ff88;border-top-style:dashed"></i>T_ss</span>
      <span><i style="border-color:#5599ff;border-top-style:dashed"></i>T_amb</span>
    </div>
    <div class="note" id="tauLabel"></div>
    <div style="font-size:.78rem;color:var(--muted);margin:8px 0 2px">I(t) — current profile</div>
    <canvas id="chartI" width="228" height="80"></canvas>
    <div class="export-row">
      <button class="sc-btn" id="btnScreenshot">📸 Screenshot</button>
      <button class="sc-btn" id="btnExportCsv">📊 Export CSV</button>
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
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
// ── Baked data ────────────────────────────────────────────────────────────────
const PARAMS = __PARAMS__;
const ROM    = PARAMS.rom;    // T_amb tau I_ref dT_mean_ref dT_max_ref alpha P_ref UA + I_em_ref/B_max/J_max
const LUMPED = PARAMS.lumped; // {nodes:{inner,outer,iron:{P_ref,C,hA}}}
const FIELD_LINES = PARAMS.field_lines; // [{r:[mm],z:[mm],amp:[0..1]}, ...] meridian-plane ψ=const contours

// Display ambient temperature: real lab condition (measured 29°C during IR validation session).
// Physics ΔT is still baked at FEM T_ref=20°C; only the absolute baseline shifts for display.
// TODO (future): fetch real-time ambient from OpenWeatherMap API for Darmstadt, Germany
//   (Zipcode: 64289) and initialise T_AMB_JS dynamically on page load.
const T_AMB_JS = 29.0;

function b64Buf(b64){
  const s=atob(b64),a=new Uint8Array(s.length);
  for(let i=0;i<s.length;i++)a[i]=s.charCodeAt(i);return a.buffer;
}
const positions  = new Float32Array(b64Buf("__POS_B64__"));    // CAD mm Z-up
const regions    = new Uint8Array  (b64Buf("__REG_B64__"));    // per triangle
const dT_ref_vtx = new Float32Array(b64Buf("__DT_B64__"));     // eddy field [K], uniform thru-thickness
const dT_air_vtx = new Float32Array(b64Buf("__DTAIR_B64__"));  // hot-air field [K], bottom-weighted
const Je_vtx     = new Float32Array(b64Buf("__JE_B64__"));     // eddy-current density, normalized 0..1

// Rotate CAD Z-up → Three.js Y-up: (x,y,z)→(x,z,−y)
for(let i=0;i<positions.length;i+=3){
  const y=positions[i+1],z=positions[i+2];
  positions[i+1]=z; positions[i+2]=-y;
}

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

// ── I(t) scenarios (same as digital_twin.py) ─────────────────────────────────
const SCENARIOS = {
  step:  (I, t) => I,
  ramp:  (I, t) => Math.min(t / 60.0, 1.0) * I,
  sine:  (I, t) => Math.max(0, I * 0.6 + I * 0.4 * Math.sin(2 * Math.PI * t / 120)),
  pulse: (I, t) => (t % 120) < 60 ? I : 0.0,
};
let curScenario = 'step';
let targetI = 5.0;   // from slider
function getI() { return SCENARIOS[curScenario](targetI, sim.t); }

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
  // core reaches ~45°C at 7.8A steady), not through the air pocket.
  const q_cond = (LUMPED.nodes.iron.G_cond || 0) * (sim.T.inner - sim.T.iron);
  let Qconv = 0.0;
  for (const k in LUMPED.nodes) {
    const nd = LUMPED.nodes[k];
    let q = nd.P_ref * s2;
    if (k === 'iron')  q += q_cond;      // gains from the coil contact
    if (k === 'inner') q -= q_cond;      // energy conservation (≪ P_inner, ~0.6W)
    const dTsurf = sim.T[k] - sim.T.air;
    const hA_use = hAEff(nd.hA, dTsurf, nd.dT_cal);
    const out = hA_use * dTsurf;         // convect into local air
    if (nd.G_wind) {
      // Two-node coil (WP-B): ALL generation lands on the surface node (same as
      // before — matches the IR-calibrated ramp-test transient); the deep
      // winding-core mass only exchanges heat via conduction G_wind, so it is
      // nearly invisible while heating but keeps feeding the surface long after
      // the current is cut, giving a realistic slow cooldown tail.
      const deepKey = k + '_deep';
      const g = nd.G_wind * (sim.T[deepKey] - sim.T[k]);  // >0 when deep hotter
      sim.T[k]       += (q + g - out) / nd.C * dt;
      sim.T[deepKey] += (-g) / nd.C_deep * dt;
    } else {
      sim.T[k] += (q - out) / nd.C * dt;
    }
    Qconv += out;
  }
  // Local air node: gains all body convection, loses to the far ambient ROM.T_amb.
  sim.T.air += (Qconv - AIR.hA_far * (sim.T.air - T_AMB_JS)) / AIR.C_air * dt;

  // (2a) eddy part — instantaneous source, fast disc time constant τ
  const tgt_eddy = s2 * s;
  sim.beta_eddy = Math.max(0.0,
    sim.beta_eddy + (tgt_eddy - sim.beta_eddy) / ROM.tau * dt);
  // (2b) hot-air part — target tracks the (inertia-laden) coil temperature.
  //      coilAirDrive() → s2 at steady state, so β_air_ss = s2·s as before.
  const tgt_air = coilAirDrive() * s;
  sim.beta_air = Math.max(0.0,
    sim.beta_air + (tgt_air - sim.beta_air) / ROM.tau * dt);

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
}

// ── Color mapping ─────────────────────────────────────────────────────────────
//  T_amb → blue (HSL 240°),  125 °C → red (HSL 0°). Floor tracks the baked
//  ambient (20 °C per params.yaml) instead of a stale hardcoded value.
const T_COLOR_LO = T_AMB_JS, T_COLOR_HI = 125;
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

// ── Levitation gap physics ────────────────────────────────────────────────────
// The EM lift force decays ~exponentially with gap height z:
//   F(I,z) = (I/5A)² · F1 · e^{−(z−z1)/z0}
// Anchored on the EM solve (CLAUDE.md 2026-07-01): F(5A, z=1mm)=1.85N and the
// observed equilibrium F(5A, z_eq=4.1mm) = F_grav = 1.60N (163g disc), giving a
// decay length z0 = (4.1−1)/ln(1.85/1.60) ≈ 21.4mm. Solving F = F_grav for z:
//   z_eq(I) = Z_GAP_5A_MM + 2·z0·ln(I/5)   (clamped at 0)
// → CONTINUOUS lift-off at I_min = 5·e^{−4.1/(2·z0)} ≈ 4.54A: the gap grows
// smoothly from 0 (no jump), passes 4.1mm at 5A, reaches ≈18.5mm at 7A.
const Z_GAP_5A_MM = 4.1;    // [mm] equilibrium gap at I=5A

// CALIBRATION OPEN (user question, docs/PLAN_SIM_FEEDBACK_2026-07-02.md WP-A #4):
// at Z_DECAY_MM=21.4mm, z_eq(7.75A)≈22.9mm — user reports the real rig's gap only
// "nudges up a little" from 5A to 7.75-8A, so 21.4mm is likely too large. Once the
// real gap at 7.75A is measured (mm, or "x times disc thickness"), fill it in below
// and Z_DECAY_MM refits itself; leave null to keep the 21.4mm placeholder.
const Z_OBS_7_75A_MM = null;
let Z_DECAY_MM = 21.4;      // [mm] EM force decay length z0 (from the two EM anchors)
if (Z_OBS_7_75A_MM !== null) {
  Z_DECAY_MM = (Z_OBS_7_75A_MM - Z_GAP_5A_MM) / (2 * Math.log(7.75 / 5.0));
}
const I_LEV_MIN   = 5.0 * Math.exp(-Z_GAP_5A_MM / (2 * Z_DECAY_MM));  // ≈4.54A lift-off
const Z_GAP_EXAG  = 2.0;    // display exaggeration factor — SAME as display_z_exaggeration
                             // used for the disc thickness (params.yaml), so every z-axis
                             // dimension of the disc scales consistently (4.1mm@5A -> 8.2 display-mm).

function levGapEqMm(I) {
  if (I <= I_LEV_MIN) return 0.0;
  return Z_GAP_5A_MM + 2 * Z_DECAY_MM * Math.log(I / 5.0);
}

// Disc vertical dynamics: m·z̈ = F(I,z) − mg − damping. Linearised about the
// equilibrium this is an underdamped oscillator with ω = √(g/z0) ≈ 21 rad/s.
const LEV_OMEGA = Math.sqrt(9.81 / (Z_DECAY_MM * 1e-3));  // ≈21.4 rad/s

// Eddy-current damping grows with B² ∝ I² (more current -> more braking on the
// bobbing disc): ζ(I) = ζ0 + ζ1·(I/5)². ζ1=0.02 reproduces the original fixed
// ζ=0.02 exactly at the 5A anchor (settle ≈4/(ζω)≈9s, matches the 2026-07-01
// observation), giving ζ(7.75A)≈0.048.
// NOTE (open calibration, same spirit as Z_DECAY_MM above): a pure I² law only
// reaches ζ(7.75A)≈0.048 — the WP-A overshoot acceptance target ("<40% of the
// 0->5A step overshoot, normalized") works out to needing ζ≈0.3 at 7.75A, which
// a quadratic law can't reach without breaking the ζ(5A)=0.02 anchor. Flagging
// this rather than silently forcing a steeper/unphysical law — revisit once
// real oscillation-amplitude data at 7.75-8A exists.
const LEV_ZETA0 = 0.0;
const LEV_ZETA1 = 0.02;
function levZeta(I) { return LEV_ZETA0 + LEV_ZETA1 * (I / 5.0) ** 2; }

// Sub-liftoff jitter: below I_LEV_MIN the disc rests on the coil, but the AC
// force still pulses at 100Hz (i(t)² term) — real rig "rung lạch cạch" chatter
// starting around 0.1A, growing through 1-3A. 100Hz can't be resolved at 60fps,
// so it's shown as an aliased two-tone shimmer, amplitude ∝ I², fading out once
// the disc actually lifts (lev.z > 0.5mm).
const JIT_MM    = 0.3;   // [display-mm] max shimmer amplitude before liftoff
const JIT_FREQ1 = 27.0;  // [rad/s] visual-only shimmer rates (incommensurate, not physical 100Hz)
const JIT_FREQ2 = 71.0;

const lev = {z: 0.0, v: 0.0, jit: 0.0, jitPhase1: 0.0, jitPhase2: 0.0};   // gap [mm], velocity [mm/s]
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

  const fadeIn = Math.max(0, 1 - lev.z / 0.5);
  if (I > 0.05 && fadeIn > 0) {
    lev.jitPhase1 += JIT_FREQ1 * dt;
    lev.jitPhase2 += JIT_FREQ2 * dt;
    const amp = Math.min(1.0, JIT_MM * (I / 5.0) ** 2);
    lev.jit = fadeIn * amp * (Math.sin(lev.jitPhase1) + 0.5 * Math.sin(lev.jitPhase2));
  } else {
    lev.jit = 0.0;
  }
}

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
renderer.domElement.style.cssText = 'position:absolute;top:0;left:0;z-index:0;';

// Studio HDR-like environment (PMREM of a simple lit room) — gives the metallic
// coil/iron materials soft reflections instead of flat shading. Cosmetic only.
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

// CSS2DRenderer overlay for floating 3D part labels (HTML, not WebGL geometry).
const labelRenderer = new CSS2DRenderer();
labelRenderer.setSize(innerWidth, innerHeight);
labelRenderer.domElement.style.cssText = 'position:absolute;top:0;left:0;z-index:1;pointer-events:none;';
document.body.appendChild(labelRenderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.08;
document.querySelectorAll('.panel, #headerBar').forEach(p => {
  p.addEventListener('pointerenter', () => controls.enabled = false);
  p.addEventListener('pointerleave', () => controls.enabled = true);
  ['pointerdown','mousedown','wheel','touchstart'].forEach(ev =>
    p.addEventListener(ev, e => e.stopPropagation(), {passive:false}));
});

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

// Per-disc-vertex live temperature: eddy part (fast β_eddy, uniform) + hot-air part
// (slow β_air, bottom-weighted). The two time constants differ, so the top/bottom
// gradient GROWS over time as the coils' hot air builds up — not a frozen pattern.
function discVtxT(M, vi) {
  return T_AMB_JS + ROM.f_eddy * sim.beta_eddy * M.dT[vi]
                  + ROM.f_air  * sim.beta_air  * M.dTa[vi];
}
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
  coilInnerM.mesh.material.emissiveIntensity = 0.9 * Math.pow(gi, 1.4);
  coilOuterM.mesh.material.emissiveIntensity = 0.9 * Math.pow(go, 1.4);
}

// Live min/max of the disc temperature field (radial + top/bottom gradient).
// Recomputed each frame because the field SHAPE changes over time (β_eddy vs β_air).
// Used both for the disc's relative colour scale and for telemetry.
let discTlo = T_AMB_JS, discThi = T_AMB_JS;
function updateDiscRange() {
  let lo = Infinity, hi = -Infinity;
  for (let vi = 0; vi < plateM.dT.length; vi++) {
    const T = discVtxT(plateM, vi);
    if (T < lo) lo = T;
    if (T > hi) hi = T;
  }
  discTlo = lo; discThi = hi;
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
// Y=z, Z=−r·sinθ). Static geometry, built once; toggled via vizMode and an
// always-running dash-offset animation ("flow" cue), independent of pause.
const N_THETA_FIELD = 24;
const fieldLineGroup = new THREE.Group();
fieldLineGroup.position.set(-ctr.x, -ctr.y, -ctr.z);   // same (un-lifted) frame as baseM
fieldLineGroup.visible = false;
scene.add(fieldLineGroup);

function flColor(t, out) {   // blue(0) -> cyan(0.5) -> white(1)
  t = t < 0 ? 0 : (t > 1 ? 1 : t);
  if (t < 0.5) { const k = t / 0.5; out.setRGB(0.10 * (1 - k), 0.30 + 0.70 * k, 1.0); }
  else         { const k = (t - 0.5) / 0.5; out.setRGB(k, 1.0, 1.0); }
}
const fieldLineMats = [];   // {mat, amp} — amp = this line's average |B|/B_max, for opacity weighting
const _flCol = new THREE.Color();
for (const fl of FIELD_LINES) {
  const n = fl.r.length;
  let ampSum = 0;
  for (let i = 0; i < n; i++) ampSum += fl.amp[i];
  const avgAmp = ampSum / n;
  for (let t = 0; t < N_THETA_FIELD; t++) {
    const theta = t / N_THETA_FIELD * Math.PI * 2;
    const ct = Math.cos(theta), st = Math.sin(theta);
    const pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const r = fl.r[i], z = fl.z[i];
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
  }
}
// Rank lines by field strength so line DENSITY responds to I, not just brightness:
// at low I only the strongest flux tubes (hugging the coils) remain visible, and
// the full baked set appears at I_em_ref. rankFrac ∈ [0,1): 0 = strongest line.
{
  const sorted = [...fieldLineMats].sort((a, b) => b.amp - a.amp);
  sorted.forEach((o, i) => { o.rankFrac = i / sorted.length; });
}
const FL_GAP_BASE = size * 0.012;   // dash gap at I ≤ I_em_ref (shrinks above → denser flow)
function applyFieldLineOpacity() {
  for (const o of fieldLineMats) o.mat.opacity = fieldLineOpacityPct * (0.15 + 0.85 * o.amp);
}
applyFieldLineOpacity();
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
const plateTopY = (bb.max.y - ctr.y) + levGapEqMm(targetI) * Z_GAP_EXAG;
camera.position.set(size*0.70, size*0.42, size*0.70);
controls.target.set(0, plateTopY*0.55, 0); controls.update();
// Exposed for headless (Playwright) verification — lets tests reposition the view.
window.twinDebug = {camera, controls, size, plateM, coilInnerM, coilOuterM,
  coilM: coilInnerM,   // back-compat alias for existing headless tests
  ctr, scene, get lev() { return lev; }, get sim() { return sim; },
  levStep, levGapEqMm, levZeta, I_LEV_MIN};   // WP-A: direct physics hooks for headless tests
scene.add(new THREE.AmbientLight(0xffffff, 0.5));
const dl = new THREE.DirectionalLight(0xffffff, 0.7);
dl.position.set(1, 1.5, 0.8); scene.add(dl);
const gridHelper = new THREE.GridHelper(size*2, 40, 0x333344, 0x1a1a28);
scene.add(gridHelper);

// ── 3D annotation labels (CSS2DObject) ────────────────────────────────────────
// Centroid of all vertices belonging to a region, in the SAME local frame the
// meshes use (model-space minus ctr) — purely a label-placement helper, no
// physics involved.
function regionCentroid(regIdx) {
  let sx = 0, sy = 0, sz = 0, n = 0;
  for (let tri = 0; tri < regions.length; tri++) {
    if (regions[tri] !== regIdx) continue;
    for (let v = 0; v < 3; v++) {
      const i = (tri * 3 + v) * 3;
      sx += positions[i]; sy += positions[i+1]; sz += positions[i+2]; n++;
    }
  }
  return n ? new THREE.Vector3(sx/n - ctr.x, sy/n - ctr.y, sz/n - ctr.z) : new THREE.Vector3();
}
const labelDivs = [];   // for the screen-space de-overlap pass below
function addLabel(text, pos, cls) {
  const div = document.createElement('div');
  div.className = 'label3d' + (cls ? ' ' + cls : '');
  div.textContent = text;
  labelDivs.push(div);
  const obj = new CSS2DObject(div);
  obj.position.copy(pos);
  scene.add(obj);
  return obj;
}
// Screen-space label de-overlap: the 3D anchors are spread out, but an arbitrary
// camera angle can still project two labels onto the same spot. Every ~200ms,
// nudge the later label downward until it clears (margin-top applies before the
// CSS2D transform, so it stacks cleanly with the renderer's own positioning).
let labelDeOverlapTimer = 0;
function deOverlapLabels(dt) {
  labelDeOverlapTimer -= dt;
  if (labelDeOverlapTimer > 0) return;
  labelDeOverlapTimer = 0.2;
  // Greedy stacking, stable in one pass: measure the un-shifted rects, walk the
  // labels top-to-bottom, and push each one below every x-overlapping label
  // already placed above it. (A naive pairwise push oscillated between frames.)
  for (const d of labelDivs) d.style.marginTop = '0px';
  const rects = labelDivs.map(d => d.getBoundingClientRect());
  const order = labelDivs.map((_, k) => k).sort((p, q) => rects[p].top - rects[q].top);
  const shift = new Array(labelDivs.length).fill(0);
  for (let oi = 1; oi < order.length; oi++) {
    const k = order[oi];
    for (let oj = 0; oj < oi; oj++) {
      const m = order[oj];
      const ox = Math.min(rects[m].right, rects[k].right)
               - Math.max(rects[m].left,  rects[k].left);
      if (ox <= 0) continue;
      const mBot = rects[m].bottom + shift[m];
      const kTop = rects[k].top    + shift[k];
      const kBot = rects[k].bottom + shift[k];
      if (kTop < mBot + 2 && kBot > rects[m].top + shift[m] - 2)
        shift[k] = mBot + 4 - rects[k].top;
    }
  }
  labelDivs.forEach((d, k) => { if (shift[k]) d.style.marginTop = shift[k] + 'px'; });
}
const plateCentroid = regionCentroid(0);
const plateLabelObj = addLabel('Aluminium Plate',
  new THREE.Vector3(plateCentroid.x, plateCentroid.y + levLiftY() + size*0.05, plateCentroid.z));
// Ring labels anchor on each ring's OUTER TOP EDGE at its own azimuth θ — the naive
// full-revolve centroid collapses to (≈0, y_mid, ≈0) for EVERY ring (x,z average out
// over 2π and the coil assembly shares one z-band), which stacked all four labels
// onto the same screen point. Distinct radii + distinct azimuths keep them apart
// from any camera angle; small y-stagger breaks the remaining near-ties.
function regionAnchor(regIdx, thetaDeg, yPad) {
  let rMax = 0, yTop = -Infinity, n = 0;
  for (let tri = 0; tri < regions.length; tri++) {
    if (regions[tri] !== regIdx) continue;
    for (let v = 0; v < 3; v++) {
      const i = (tri * 3 + v) * 3;
      const r = Math.hypot(positions[i], positions[i+2]);
      if (r > rMax) rMax = r;
      if (positions[i+1] > yTop) yTop = positions[i+1];
      n++;
    }
  }
  if (!n) return new THREE.Vector3();
  const th = thetaDeg * Math.PI / 180;
  return new THREE.Vector3(rMax * Math.cos(th) - ctr.x,
                           yTop + (yPad || 0) - ctr.y,
                           -rMax * Math.sin(th) - ctr.z);
}
addLabel('Inner Coil (1000 turns)', regionAnchor(1,  25, size*0.030));
addLabel('Outer Coil (500 turns)',  regionAnchor(2, -40, size*0.015));
addLabel('Center Core',    regionAnchor(3,  90, size*0.008), 'iron');
// Separator: keep LOW (yPad 0) and well left (θ=190°) — a back-side ring label
// projects toward screen centre-height, where it collided with the plate label.
addLabel('Separator Ring', regionAnchor(5, 190, 0), 'iron');

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
const N_HEAT_PARTICLES = 70;
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
  const hot = Math.max(sim.T.inner, sim.T.outer, sim.T.iron) - ROM.T_amb > 2.0;
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
const TRANGE = T_COLOR_HI - T_COLOR_LO;
// Coil colour-ramp ceiling — ABSOLUTE scale: 0 = T_amb, 1 = T_COIL_HOT.
// Anchored to the real IR data (session 1, 2026-06-23): inner coil hit 79°C @7.8A,
// the hottest reading ever measured. Colour only changes when the actual
// temperature changes — NOT when I changes (a prior *relative* scale divided by
// I-dependent T_ss(I), so bumping I made the coil "cool" instantly and steady
// state always painted full-hot regardless of I — both wrong).
// (Module scope: shared by paintMesh and updateCoilGlow.)
const T_COIL_HOT = 80.0;   // [°C]
// Disc colour-scale mode: 'auto' keeps the original behaviour (stretch only once
// the in-plate spread is physically meaningful), 'absolute'/'relative' force one
// or the other — wired to the "Scale: …" button in the telemetry panel.
let colorScaleMode = 'auto';
function paintMesh(M) {
  const col = M.col;
  const dT_hot = T_COIL_HOT - T_AMB_JS;
  const tnInner = (sim.T.inner - T_AMB_JS) / dT_hot;
  const tnOuter = (sim.T.outer - T_AMB_JS) / dT_hot;
  // Core/separator: same absolute scale as the coils, then a visual boost — the
  // real core/ring only reach ~45°C @7.8A (tnorm ≈0.31 on this scale), which would
  // look nearly frozen silver. 1.8x lifts that to a clearly visible warm-metal
  // shift while keeping writeRampMetal's own clamp to [0,1]; matches the real IR
  // image (docs/thermal_test.png): coils bright, ring/core moderately warm.
  const tnIron  = (sim.T.iron - T_AMB_JS) / dT_hot * 1.8;
  const tnByReg = [0, tnInner, tnOuter, tnIron];
  // Disc relative scale: blue = coolest part of plate (top rim), red = hottest
  // (bottom centre). Only stretch once the in-plate spread is physically meaningful
  // (≥0.3 K) — below that the plate is ~isothermal, so use the absolute T_amb–125°C
  // scale and it reads as a uniformly-warming blue (no fake rainbow on noise).
  const span = discThi - discTlo;
  const wantAdaptive = colorScaleMode === 'relative' ? true
                     : colorScaleMode === 'absolute' ? false
                     : span > 0.3;
  const adaptive = wantAdaptive && span > 1e-6;   // guard against 1/0 at t=0
  const invSpan  = adaptive ? 1.0 / span : 0.0;
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
          const tn = adaptive ? (T - discTlo) * invSpan : (T - T_COLOR_LO) / TRANGE;
          writeRamp(col, idx, tn);
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
  M.geo.attributes.color.needsUpdate = true;
}

// ── T_max / T_mean from plate sub-mesh (combined eddy + hot-air field) ────────
function plateTmax() {
  return discThi;   // hottest disc vertex — kept current by updateDiscRange()
}
function plateTmean() {
  let s = 0;
  for (let vi = 0; vi < plateM.dT.length; vi++) s += discVtxT(plateM, vi);
  return s / plateM.dT.length;
}
// T_ss for current I (no sigma correction for speed, close enough for UI)
function plateTss(I) {
  const r2 = (I / ROM.I_ref) ** 2;
  return T_AMB_JS + ROM.dT_max_ref * r2;
}
// Coil steady-state temperatures at given I — used for relative colour scale
function coilTss_inner(I) {
  const s2 = (I / ROM.I_ref) ** 2;
  return T_AMB_JS + (LUMPED.nodes.inner.P_ref / LUMPED.nodes.inner.hA + AIR_DT_SS_REF) * s2;
}
function coilTss_outer(I) {
  const s2 = (I / ROM.I_ref) ** 2;
  return T_AMB_JS + (LUMPED.nodes.outer.P_ref / LUMPED.nodes.outer.hA + AIR_DT_SS_REF) * s2;
}
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
const CHART_WIN = 600; // 10 min window

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
  const t0   = Math.max(0, tNow - CHART_WIN);
  const curI = getI();
  const curTss       = plateTss(curI);
  const curInnerSS   = coilTss_inner(curI);
  const Tlo = T_AMB_JS - 0.5;
  const Thi = Math.max(curTss + 2, sim.hist_Tmax[N-1] + 1,
                        curInnerSS + 2, sim.hist_T_inner[N-1] + 1, T_AMB_JS + 2);
  const tx = t => (t - t0) / CHART_WIN * W;
  const ty = T => H - (T - Tlo) / (Thi - Tlo) * H;
  drawGrid(W, H, 4);
  // T_amb line (blue dashed)
  ctx.strokeStyle = '#5599ff'; ctx.lineWidth = 1; ctx.setLineDash([5,4]);
  ctx.beginPath();
  ctx.moveTo(0, ty(T_AMB_JS)); ctx.lineTo(W, ty(T_AMB_JS)); ctx.stroke();
  // T_ss plate line (green dashed)
  ctx.strokeStyle = '#44ff88'; ctx.lineWidth = 1; ctx.setLineDash([5,4]);
  ctx.beginPath(); ctx.moveTo(0, ty(curTss)); ctx.lineTo(W, ty(curTss)); ctx.stroke();
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
  ctx.fillStyle = '#44ff88'; ctx.fillText('T_ss', W-28, ty(curTss)-4);
  const winLabel = tNow < CHART_WIN ? (tNow/60).toFixed(1)+'min' : '-10min…now';
  ctx.fillStyle = '#556'; ctx.fillText(winLabel, 2, H/2);
}

// ── I(t) current-profile chart (second canvas) ────────────────────────────────
const chartCanvasI = document.getElementById('chartI');
const ctxI = chartCanvasI.getContext('2d');
function drawCurrentChart() {
  const W = chartCanvasI.width, H = chartCanvasI.height;
  ctxI.fillStyle = '#0a0a14'; ctxI.fillRect(0, 0, W, H);
  const N = sim.hist_I.length;
  if (N < 2) return;
  const tNow = sim.hist_t[N-1];
  const t0 = Math.max(0, tNow - CHART_WIN);
  const Ihi = Math.max(targetI, 1) * 1.15;
  const tx = t => (t - t0) / CHART_WIN * W;
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
    const tNow = sim.hist_t[N-1], t0 = Math.max(0, tNow - CHART_WIN);
    const tAtX = t0 + x / canvas.width * CHART_WIN;
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
function selectScenario(name) {
  const btn = document.querySelector(`.sc-btn[data-sc="${name}"]`);
  if (!btn) return;
  document.querySelectorAll('.sc-btn[data-sc]').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  curScenario = name;
  resetSim();
}
document.querySelectorAll('.sc-btn[data-sc]').forEach(btn => {
  btn.onclick = () => selectScenario(btn.dataset.sc);
});
document.getElementById('reset').onclick = resetSim;

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
const setBox = (id, T) => document.getElementById(id).style.background =
  '#' + tcol(T).getHexString();

// ── Panel collapse (click header to toggle) ──────────────────────────────────
document.querySelectorAll('.panel-head').forEach(h => {
  h.onclick = () => h.parentElement.classList.toggle('collapsed');
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
};

// ── Colour-scale ticks + mode toggle ──────────────────────────────────────────
(function buildScaleTicks() {
  const ticksEl = document.getElementById('scaleTicks');
  const steps = 6;
  let html = '';
  for (let i = 0; i <= steps; i++) {
    const T = T_COLOR_LO + TRANGE * i / steps;
    html += `<span>${T.toFixed(0)}°</span>`;
  }
  ticksEl.innerHTML = html;
})();
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
function updateScaleBar() {
  const lo = Math.max(0, Math.min(1, (discTlo - T_COLOR_LO) / TRANGE));
  const hi = Math.max(0, Math.min(1, (discThi - T_COLOR_LO) / TRANGE));
  scaleMarkerLo.style.left = (lo * 100).toFixed(1) + '%';
  scaleMarkerHi.style.left = (hi * 100).toFixed(1) + '%';
  scaleCurRangeEl.textContent = `${discTlo.toFixed(1)}–${discThi.toFixed(1)} °C`;
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
  let csv = 't_s,T_plate_max_C,T_inner_coil_C,T_outer_coil_C,I_A\n';
  for (let i = 0; i < sim.hist_t.length; i++)
    csv += `${sim.hist_t[i].toFixed(2)},${sim.hist_Tmax[i].toFixed(3)},` +
           `${sim.hist_T_inner[i].toFixed(3)},${sim.hist_T_outer[i].toFixed(3)},` +
           `${sim.hist_I[i].toFixed(3)}\n`;
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
  const v = Math.max(0, Math.min(2.301, +sS.value + dir * 0.1));
  sS.value = v;
  sS.oninput();
}
addEventListener('keydown', (e) => {
  switch (e.key) {
    case ' ':  e.preventDefault(); setPaused(!paused); break;
    case 'r': case 'R': resetSim(); break;
    case '1': selectScenario('step');  break;
    case '2': selectScenario('ramp');  break;
    case '3': selectScenario('sine');  break;
    case '4': selectScenario('pulse'); break;
    case '+': case '=': adjustSpeed(1);  break;
    case '-': case '_': adjustSpeed(-1); break;
  }
});

document.getElementById('tauLabel').textContent =
  `τ = ${(ROM.tau/60).toFixed(2)} min  |  UA = ${ROM.UA.toFixed(4)} W/K`;

// Precompute coil steady-state temperatures (at I_ref) — shown as target arrows.
// True steady rise = own rise above the local air node + the air node's rise above
// the far ambient (AIR_DT_SS_REF), since the coils now convect into shared air.
const T_ss_inner = T_AMB_JS + LUMPED.nodes.inner.P_ref / LUMPED.nodes.inner.hA + AIR_DT_SS_REF;
const T_ss_outer = T_AMB_JS + LUMPED.nodes.outer.P_ref / LUMPED.nodes.outer.hA + AIR_DT_SS_REF;
document.getElementById('tInSS').textContent  = `→${T_ss_inner.toFixed(0)}°`;
document.getElementById('tOutSS').textContent = `→${T_ss_outer.toFixed(0)}°`;

// Iron saturation status (static, baked at build time)
{
  const bmax = ROM.B_max_iron, bsat = ROM.B_sat;
  const satEl = document.getElementById('tBmax');
  satEl.textContent = `${bmax.toFixed(3)} T / ${bsat} T`;
  satEl.style.color = ROM.saturated ? '#ff4444' : '#88ff88';
  if (ROM.saturated)
    document.getElementById('satRow').title = 'WARNING: iron core is magnetically saturated — μ_r=1000 is invalid!';
}
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

// ── Main animation loop ───────────────────────────────────────────────────────
let lastWall = performance.now();
let recordTimer = 0;

function loop() {
  requestAnimationFrame(loop);
  const now = performance.now();
  let wall_dt = (now - lastWall) / 1000;
  lastWall = now;
  if (wall_dt > 0.1) wall_dt = 0.1;   // cap at 100ms (tab-hidden guard)

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

    // Record history every ~1 sim-second
    recordTimer += dt_sim;
    if (recordTimer >= 1.0) {
      recordTimer = 0;
      const Tmax = plateTmax();
      sim.hist_t.push(sim.t);
      sim.hist_Tmax.push(Tmax);
      sim.hist_T_inner.push(sim.T.inner);
      sim.hist_T_outer.push(sim.T.outer);
      sim.hist_I.push(getI());
      // Keep max 3600 points
      if (sim.hist_t.length > 3600) {
        sim.hist_t.shift(); sim.hist_Tmax.shift();
        sim.hist_T_inner.shift(); sim.hist_T_outer.shift();
        sim.hist_I.shift();
      }
    }

    updateHeatParticles(dt_sim);
  }

  // Paint meshes
  paintMesh(baseM);
  paintMesh(coilInnerM);
  paintMesh(coilOuterM);
  paintMesh(woodM);
  paintMesh(plateM);
  updateCoilGlow();   // emissive ∝ coil T — hot windings visibly light up (IR look)
  updateScaleBar();

  // Update disc Z position — spring-mass response toward z_eq(I): the disc bobs
  // for ~10s after a current step, then settles (matches the real rig behaviour).
  // Integrated in SIM time (dt_sim), so the speed slider speeds up/slows down
  // the bob-and-settle exactly like the thermal side of the sim.
  const I_display = getI();
  if (!paused) levStep(I_display, dt_sim);
  const liftY = levLiftY();
  plateM.mesh.position.y = -ctr.y + liftY;
  plateLabelObj.position.y = plateCentroid.y + liftY + size * 0.05;

  // Update telemetry
  const Tmax  = plateTmax();
  const Tmean = plateTmean();
  const Tss   = plateTss(I_display);

  document.getElementById('vT').textContent  = sim.t < 120
    ? sim.t.toFixed(1)+' s' : (sim.t/60).toFixed(2)+' min';
  document.getElementById('vIC').textContent = I_display.toFixed(2)+' A';
  document.getElementById('vP').textContent  = totalPower(I_display).toFixed(1)+' W';

  // Power breakdown: disc eddy vs coil ohmic
  const s2disp = (I_display / ROM.I_ref) ** 2;
  const P_disc = ROM.P_ref * s2disp;
  const P_coil_now = (LUMPED.nodes.inner.P_ref + LUMPED.nodes.outer.P_ref) * s2disp;
  document.getElementById('vPdisc').textContent = P_disc.toFixed(2) + ' W';
  document.getElementById('vPcoil').textContent = P_coil_now.toFixed(1) + ' W';

  // Live gap = the spring-mass state, so telemetry shows the bob-and-settle too.
  document.getElementById('tLevGap').textContent =
    'Levitation Gap: ' + lev.z.toFixed(1) + ' mm';
  document.getElementById('tPmax').textContent  = Tmax.toFixed(2)+' °C';
  setV('tPmean', Tmean); setV('tPss', Tss);
  setV('tIn',  sim.T.inner); setV('tOut', sim.T.outer); setV('tFe',  sim.T.iron);
  // Steady-state target arrows must track the CURRENT I — they were previously baked
  // once at I_ref (5A), so at 5.5A the live temperature sailed past a stale "→50°".
  document.getElementById('tInSS').textContent  = `→${coilTss_inner(I_display).toFixed(0)}°`;
  document.getElementById('tOutSS').textContent = `→${coilTss_outer(I_display).toFixed(0)}°`;

  setBox('bPl',  Tmax);
  setBox('bIn',  sim.T.inner);
  setBox('bOut', sim.T.outer);
  setBox('bFe',  sim.T.iron);
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
  renderer.render(scene, camera);
  labelRenderer.render(scene, camera);
  deOverlapLabels(wall_dt);
}

addEventListener('resize', () => {
  renderer.setSize(innerWidth, innerHeight);
  labelRenderer.setSize(innerWidth, innerHeight);
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
});

loop();
</script></body></html>"""


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("stl", nargs="?", default=os.path.join(HERE, "3D_model.stl"),
                     help="unused (body geometry is 100% procedural) -- kept for CLI compatibility")
    ap.add_argument("--plate-radius", type=float, default=None,
                     help="Override plate_material.radius_mm (mm) for this build only "
                          "(params.yaml default is unchanged). E.g. --plate-radius 101 for "
                          "the Ø202mm disc. Output gets a _R<radius> filename suffix.")
    args = ap.parse_args()

    out_dir = os.path.join(HERE, "outputs")
    os.makedirs(out_dir, exist_ok=True)
    if args.plate_radius is not None:
        out_name = f"digital_twin_fem_R{int(round(args.plate_radius))}.html"
    else:
        out_name = "digital_twin_fem.html"
    out = os.path.join(out_dir, out_name)
    build(args.stl, out, plate_radius_mm=args.plate_radius)
