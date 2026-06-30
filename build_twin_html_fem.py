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

from config import load_config
from em_solver import compute_losses
from rom import ThermalROM


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

    def coil_C(c):
        r_mean = (c["r_inner_mm"] + c["r_outer_mm"]) / 2 * mm
        Vc = c["turns"] * (2 * math.pi * r_mean) * A_wire
        return 8960.0 * 385.0 * Vc * coil_C_scale  # rho_Cu * cp_Cu * V_Cu, scaled

    p = cfg.plate
    V_plate = math.pi * (p["radius_mm"] * mm) ** 2 * (p["thickness_mm"] * mm)
    C_plate = p["rho_kg_per_m3"] * p["cp_J_per_kgK"] * V_plate

    return {
        "nodes": {
            "inner": {
                "P_ref": 0.5 * cfg.I ** 2 * coil_R(co["inner"]),
                "C":     coil_C(co["inner"]),
                "hA":    float(lt["hA_inner_W_per_K"]),
            },
            "outer": {
                "P_ref": 0.5 * cfg.I ** 2 * coil_R(co["outer"]),
                "C":     coil_C(co["outer"]),
                "hA":    float(lt["hA_outer_W_per_K"]),
            },
            "iron": {
                "P_ref": em["P_iron_W"],
                "C":     0.5 * C_plate,
                "hA":    float(lt["hA_iron_W_per_K"]),
            },
        },
        "air_node": {
            "C":      float(lt["air_node_C_J_per_K"]),
            "hA_far": float(lt["air_node_hA_far_W_per_K"]),
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


def build_separator_rings(cfg, z_bot_mm: float, z_top_mm: float, n_theta: int) -> np.ndarray:
    """Procedurally generate the two separator-ring gaps (region 5) as thin
    vertical sleeves spanning [z_bot_mm, z_top_mm] -- the same height as the
    real coil/center-spacer walls either side of them, so they read as a ring
    standing among the windings rather than a sliver lost at the floor. The real
    STL has NO surface at these exact radii (a genuine geometric gap -- see
    3D_MODEL_UPDATE_PLAN.md), so they can't be produced by recolouring existing
    triangles like the other regions; they're synthesized the same way the
    levitating disc is. Radii come from the gaps already implied by iron_core /
    coils in params.yaml (no new hardcoded geometry)."""
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

def build(stl_path: str, out_path: str) -> None:
    cfg = load_config()

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

    # 2. Parse STL → keep only the BASE (coils + iron + structure). The thin flat
    #    STL "plate" is discarded and replaced by a procedural solid stepped disc.
    print("[STL] Parsing ...", end=" ", flush=True)
    V_all   = parse_stl(stl_path)          # (nTri, 3, 3) mm
    reg_all = classify(V_all)              # (nTri,)
    # NOTE: region boundaries (26/45/62mm) do NOT match params.yaml's coil radii
    # (28/43/46.5/61.5mm) -- the STL's real geometry is a 3-wall hollow drum
    # (walls at r~24/59/79mm) with no surface at the exact cfg gap radii. The
    # separator ring (region 5) is therefore PROCEDURALLY GENERATED below (like
    # the disc), not carved out of the STL by recolouring. See
    # 3D_MODEL_UPDATE_PLAN.md for the full geometry-mismatch writeup.
    names = {0: "plate", 1: "inner coil", 2: "outer coil", 3: "center spacer",
             4: "wood base", 5: "separator (procedural)"}
    print(f"{len(V_all)} triangles")
    for k in range(5):
        print(f"   {names[k]:12s}: {(reg_all == k).sum()} tris")

    stl_plate = reg_all == 0
    z_disc_bot = float(V_all[stl_plate][:, :, 2].min())   # place disc where plate was
    keep = ~stl_plate
    V_base   = V_all[keep]
    reg_base = reg_all[keep]

    # 2b. Procedurally synthesize the separator-ring sleeves (region 5), spanning
    # the same [bottom-cap, wall-top] z-range as the real center-spacer wall
    # either side of them -- robust to whatever the STL's actual geometry is.
    z_cap_mm  = float(V_all[reg_all == 3][:, :, 2].min())
    z_wall_mm = float(V_all[reg_all == 3][:, :, 2].max())
    V_sep = build_separator_rings(cfg, z_cap_mm, z_wall_mm,
                                   n_theta=int(cfg.raw["levitating_disc"].get("n_theta", 96)))
    nTri_sep = len(V_sep)
    print(f"   {names[5]:12s}: {nTri_sep} tris (synthesized z={z_cap_mm:.1f}..{z_wall_mm:.1f}mm)")
    if nTri_sep == 0:
        print("WARNING: separator ring has 0 triangles (cfg gap radii collapsed) -- stopping.")
        raise SystemExit(1)
    V_base   = np.concatenate([V_base, V_sep], axis=0)
    reg_base = np.concatenate([reg_base, np.full(nTri_sep, 5, dtype=np.uint8)])

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
    <span class="hdr-badge">T_amb = 20 °C</span>
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
      <label><span>Time speed</span><span id="vS" class="val">100×</span></label>
      <input type="range" id="sS" min="0" max="2.301" step="0.01" value="2">
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
    <div style="font-size:.78rem;color:var(--muted);margin-bottom:2px">T_max(t) — plate</div>
    <canvas id="chart" width="228" height="130"></canvas>
    <div class="chart-legend">
      <span><i style="border-color:#ff6644"></i>T_max</span>
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
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
// ── Baked data ────────────────────────────────────────────────────────────────
const PARAMS = __PARAMS__;
const ROM    = PARAMS.rom;    // T_amb tau I_ref dT_mean_ref dT_max_ref alpha P_ref UA + I_em_ref/B_max/J_max
const LUMPED = PARAMS.lumped; // {nodes:{inner,outer,iron:{P_ref,C,hA}}}
const FIELD_LINES = PARAMS.field_lines; // [{r:[mm],z:[mm],amp:[0..1]}, ...] meridian-plane ψ=const contours

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
  // inner/outer/iron = body nodes; air = shared LOCAL air node they all heat up.
  // The bodies convect into `air`, and `air` sheds heat to the far ambient ROM.T_amb.
  T: { inner: ROM.T_amb, outer: ROM.T_amb, iron: ROM.T_amb, air: ROM.T_amb },
  hist_t:    [0.0],
  hist_Tmax: [ROM.T_amb],
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
  const num = ai.P_ref * (sim.T.inner - ROM.T_amb) +
              ao.P_ref * (sim.T.outer - ROM.T_amb);
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
  let Qconv = 0.0;
  for (const k in LUMPED.nodes) {
    const nd = LUMPED.nodes[k];
    const q   = nd.P_ref * s2;
    const out = nd.hA * (sim.T[k] - sim.T.air);   // convect into local air
    sim.T[k] += (q - out) / nd.C * dt;
    Qconv += out;
  }
  // Local air node: gains all body convection, loses to the far ambient ROM.T_amb.
  sim.T.air += (Qconv - AIR.hA_far * (sim.T.air - ROM.T_amb)) / AIR.C_air * dt;

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
  for (const k in sim.T) sim.T[k] = ROM.T_amb;
  sim.hist_t    = [0.0];
  sim.hist_Tmax = [ROM.T_amb];
  sim.hist_I    = [0.0];
}

// ── Color mapping ─────────────────────────────────────────────────────────────
//  T_amb → blue (HSL 240°),  125 °C → red (HSL 0°). Floor tracks the baked
//  ambient (20 °C per params.yaml) instead of a stale hardcoded value.
const T_COLOR_LO = ROM.T_amb, T_COLOR_HI = 125;
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
const METAL_RGB  = [170/255, 175/255, 185/255];  // passive white-grey metal (center spacer)

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

// Bloom postprocessing — strength is driven by whether current is flowing
// (see loop(): bloomPass.strength set from I_display), giving the coils a
// gentle glow only while they are actually being driven.
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloomPass = new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), 0.0, 0.45, 0.85);
composer.addPass(bloomPass);

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
function makeMesh(sub) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(sub.pos, 3));
  g.computeVertexNormals();
  const col = new Float32Array(sub.pos.length);
  g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  // envMapIntensity tamed below the 1.0 default: on large flat low-poly faces
  // (this procedural disc + base) a full-strength env reflection turns the whole
  // face into one big specular blowout instead of a soft sheen.
  const m = new THREE.Mesh(g,
    new THREE.MeshStandardMaterial({vertexColors:true, roughness:0.5, metalness:0.45,
                                    envMapIntensity:0.5, side:THREE.DoubleSide}));
  return {mesh:m, geo:g, reg:sub.reg, dT:sub.dT, dTa:sub.dTa, je:sub.je, col};
}

// Per-disc-vertex live temperature: eddy part (fast β_eddy, uniform) + hot-air part
// (slow β_air, bottom-weighted). The two time constants differ, so the top/bottom
// gradient GROWS over time as the coils' hot air builds up — not a frozen pattern.
function discVtxT(M, vi) {
  return ROM.T_amb + ROM.f_eddy * sim.beta_eddy * M.dT[vi]
                   + ROM.f_air  * sim.beta_air  * M.dTa[vi];
}
const baseM  = makeMesh(buildSub(r => r !== 0));  // coils + iron + structure
const plateM = makeMesh(buildSub(r => r === 0));  // aluminium disc (levitates)

// Live min/max of the disc temperature field (radial + top/bottom gradient).
// Recomputed each frame because the field SHAPE changes over time (β_eddy vs β_air).
// Used both for the disc's relative colour scale and for telemetry.
let discTlo = ROM.T_amb, discThi = ROM.T_amb;
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
const modelH = bb.max.y - bb.min.y;
const LIFT = Math.max(modelH * 0.40, size * 0.07);  // exaggerated levitation gap

baseM.mesh.position.set(-ctr.x, -ctr.y, -ctr.z);
plateM.mesh.position.set(-ctr.x, -ctr.y + LIFT, -ctr.z);
scene.add(baseM.mesh, plateM.mesh);

// Field-line hints (blue arcs bridging coil rim → plate)
const rRim = Math.min(size * 0.18, 90);
const gapBot = bb.max.y - ctr.y - modelH * 0.12;
const gapTop = bb.max.y - ctr.y;
const flPts = [];
for (let a = 0; a < 12; a++) {
  const th = a / 12 * Math.PI * 2, x = Math.cos(th)*rRim, z = Math.sin(th)*rRim;
  flPts.push(x, gapBot, z,  x, gapTop + LIFT * 0.9, z);
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
    fieldLineMats.push({mat, amp: avgAmp});
  }
}
function applyFieldLineOpacity() {
  for (const o of fieldLineMats) o.mat.opacity = fieldLineOpacityPct * (0.15 + 0.85 * o.amp);
}
applyFieldLineOpacity();
function updateVizVisibility() {
  fieldLineGroup.visible = (vizMode === 'bfield' || vizMode === 'combined');
}
updateVizVisibility();
const FIELD_LINE_FLOW_SPEED = size * 0.05;   // world units/s — dash "flow" pulse, runs on wall clock

// Frame the levitating disc + coils in the clear lower area (UI panels cover the
// top). Aim above the device centre so the whole assembly drops into the lower
// half of the viewport, and pull back enough to keep the disc fully visible.
const plateTopY = (bb.max.y - ctr.y) + LIFT;   // top of the lifted disc
camera.position.set(size*0.70, size*0.42, size*0.70);
controls.target.set(0, plateTopY*0.62, 0); controls.update();
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
function addLabel(text, pos, cls) {
  const div = document.createElement('div');
  div.className = 'label3d' + (cls ? ' ' + cls : '');
  div.textContent = text;
  const obj = new CSS2DObject(div);
  obj.position.copy(pos);
  scene.add(obj);
  return obj;
}
const plateCentroid = regionCentroid(0);
addLabel('Aluminium Plate', new THREE.Vector3(plateCentroid.x, plateCentroid.y + LIFT + size*0.05, plateCentroid.z));
addLabel('Inner Coil (1000 turns)', regionCentroid(1));
addLabel('Outer Coil (500 turns)',  regionCentroid(2));
addLabel('Center Spacer', regionCentroid(3), 'iron');
addLabel('Separator Ring', regionCentroid(5), 'iron');

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
const particleTopY = gapTop + LIFT * 0.9;
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
// Disc colour-scale mode: 'auto' keeps the original behaviour (stretch only once
// the in-plate spread is physically meaningful), 'absolute'/'relative' force one
// or the other — wired to the "Scale: …" button in the telemetry panel.
let colorScaleMode = 'auto';
function paintMesh(M) {
  const col = M.col;
  // Per-region uniform tnorm for coils/iron (one temperature each per frame).
  const tnInner = (sim.T.inner - T_COLOR_LO) / TRANGE;
  const tnOuter = (sim.T.outer - T_COLOR_LO) / TRANGE;
  const tnIron  = (sim.T.iron  - T_COLOR_LO) / TRANGE;
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
        // Center spacer (3) and separator ring (5) are PASSIVE (don't self-heat:
        // 39-45°C vs coils' 56-79°C across both validation runs, per params.yaml)
        // -- render as static metal, not the heat ramp.
        col[idx] = METAL_RGB[0]; col[idx+1] = METAL_RGB[1]; col[idx+2] = METAL_RGB[2];
      } else {
        writeRamp(col, idx, tnByReg[reg]);   // reg 1,2: coils -- dynamic heat ramp
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
  return ROM.T_amb + ROM.dT_max_ref * r2;
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
  const t0 = Math.max(0, tNow - CHART_WIN);
  // T range: from T_amb to current T_ss + buffer
  const Tlo = ROM.T_amb - 0.5;
  const curTss = plateTss(getI());
  const Thi = Math.max(curTss + 2, sim.hist_Tmax[N-1] + 1, ROM.T_amb + 2);
  const tx = t => (t - t0) / CHART_WIN * W;
  const ty = T => H - (T - Tlo) / (Thi - Tlo) * H;
  drawGrid(W, H, 4);
  // T_amb line (blue dashed)
  ctx.strokeStyle = '#5599ff'; ctx.lineWidth = 1; ctx.setLineDash([5,4]);
  ctx.beginPath();
  ctx.moveTo(0, ty(ROM.T_amb)); ctx.lineTo(W, ty(ROM.T_amb)); ctx.stroke();
  // T_ss line (green dashed)
  ctx.strokeStyle = '#44ff88'; ctx.lineWidth = 1; ctx.setLineDash([5,4]);
  ctx.beginPath(); ctx.moveTo(0, ty(curTss)); ctx.lineTo(W, ty(curTss)); ctx.stroke();
  ctx.setLineDash([]);
  // T_max line (orange-red)
  ctx.strokeStyle = '#ff6644'; ctx.lineWidth = 1.8;
  ctx.beginPath();
  let first = true;
  for (let i = 0; i < N; i++) {
    if (sim.hist_t[i] < t0) continue;
    const x = tx(sim.hist_t[i]), y = ty(sim.hist_Tmax[i]);
    first ? (ctx.moveTo(x,y), first=false) : ctx.lineTo(x,y);
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
attachChartTooltip(chartCanvas,  i => `t=${sim.hist_t[i].toFixed(0)}s   T_max=${sim.hist_Tmax[i].toFixed(2)}°C`);
attachChartTooltip(chartCanvasI, i => `t=${sim.hist_t[i].toFixed(0)}s   I=${sim.hist_I[i].toFixed(2)}A`);

// ── UI wiring ─────────────────────────────────────────────────────────────────
const sI = document.getElementById('sI');
const sS = document.getElementById('sS');
sS.oninput = () => {
  const sp = Math.pow(10, +sS.value);
  document.getElementById('vS').textContent = (sp<10?sp.toFixed(1):Math.round(sp))+'×';
};
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
  let csv = 't_s,T_max_C,I_A\n';
  for (let i = 0; i < sim.hist_t.length; i++)
    csv += `${sim.hist_t[i].toFixed(2)},${sim.hist_Tmax[i].toFixed(3)},${sim.hist_I[i].toFixed(3)}\n`;
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
const T_ss_inner = ROM.T_amb + LUMPED.nodes.inner.P_ref / LUMPED.nodes.inner.hA + AIR_DT_SS_REF;
const T_ss_outer = ROM.T_amb + LUMPED.nodes.outer.P_ref / LUMPED.nodes.outer.hA + AIR_DT_SS_REF;
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
  const Tinf_bot = ROM.T_amb + (ROM.Tinf_bot_ref - ROM.T_amb) * coilAirDrive();
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
      sim.hist_I.push(getI());
      // Keep max 3600 points
      if (sim.hist_t.length > 3600) {
        sim.hist_t.shift(); sim.hist_Tmax.shift(); sim.hist_I.shift();
      }
    }

    updateHeatParticles(dt_sim);
  }

  // Paint meshes
  paintMesh(baseM);
  paintMesh(plateM);
  updateScaleBar();

  // Update telemetry
  const I_display = getI();
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

  document.getElementById('tPmax').textContent  = Tmax.toFixed(2)+' °C';
  setV('tPmean', Tmean); setV('tPss', Tss);
  setV('tIn',  sim.T.inner); setV('tOut', sim.T.outer); setV('tFe',  sim.T.iron);

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

  // Field-line "flow" pulse — always animates on the wall clock, independent of
  // sim pause/speed (purely a visual flow cue, not tied to any physics quantity).
  if (fieldLineGroup.visible) {
    const dashOffset = -(now / 1000) * FIELD_LINE_FLOW_SPEED;
    for (const o of fieldLineMats) o.mat.dashOffset = dashOffset;
  }

  // Bloom glow tied to whether current is actually flowing — gentle "active coil"
  // cue rather than a constant stylistic effect.
  bloomPass.strength = I_display > 0.01 ? 0.42 : 0.0;

  drawChart();
  drawCurrentChart();
  controls.update();
  composer.render();
  labelRenderer.render(scene, camera);
}

addEventListener('resize', () => {
  renderer.setSize(innerWidth, innerHeight);
  labelRenderer.setSize(innerWidth, innerHeight);
  composer.setSize(innerWidth, innerHeight);
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
});

loop();
</script></body></html>"""


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    stl = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "3D_model.stl")
    out = os.path.join(HERE, "digital_twin_fem.html")
    build(stl, out)
