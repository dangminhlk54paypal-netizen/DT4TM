"""Axisymmetric electromagnetic solver (AC, harmonic), pure numpy/scipy — Phase 1b.

Solves the magnetic vector potential equation (azimuthal component A_φ only, COMPLEX phasor):

    -∇·(ν ∇A_φ) + ν A_φ/r²  + jωσ A_φ = J_s        (ν = 1/μ = 1/(μ_r μ0))

- J_s: source current density (azimuthal) in 2 coils = ± N·î/S_coil.
- jωσ A_φ: eddy current reaction in conductors (aluminum, iron core if σ>0).
- Iron core: region with high μ_r -> low ν -> attracts/directs magnetic flux.
- Boundary: A_φ = 0 on axis r=0 (symmetry) and on outer boundary (field vanishes far away).

CYCLE-AVERAGED Joule losses (½ factor from sin²):
    q(r,z) = ½ · σ · ω² · |A_φ|²              [W/m³]   (trong vật dẫn)

Since system is LINEAR (constant μ_r): A_φ ∝ î  ->  q ∝ î²  ->  preserves I² rule for real-time.
Coil ohmic losses are computed separately via I²R (more physical for multi-turn thin wire coils).
"""
from __future__ import annotations
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
import math

MU0 = 4e-7 * math.pi


# --------------------------------------------------------------------------
# 1) Graded MESH (fine around device, coarse in far air)
# --------------------------------------------------------------------------
def _graded(segments):
    """segments: list (start, end, step) mm -> array of ascending coordinates, deduplicated."""
    pts = []
    for s, e, st in segments:
        n = max(1, int(round((e - s) / st)))
        pts.append(np.linspace(s, e, n + 1))
    return np.unique(np.concatenate(pts))


def make_mesh_em(cfg):
    em = cfg.em
    fs, cs = em["fine_step_mm"], em["coarse_step_mm"]
    rmax, zmin, zmax = em["r_max_mm"], em["z_min_mm"], em["z_max_mm"]
    rs = _graded([(0, 110, fs), (110, rmax, cs)]) * 1e-3
    # Fine mesh covers từ -60mm đến max(15, z_plate_top+10)mm để theo vị trí tấm
    p = cfg.plate
    z_fine_top = max(15.0, p["z_bottom_mm"] + p["thickness_mm"] + 10.0)
    zs = _graded([(zmin, -60, cs), (-60, z_fine_top, fs), (z_fine_top, zmax, cs)]) * 1e-3
    RR, ZZ = np.meshgrid(rs, zs, indexing="ij")
    coords = np.column_stack([RR.ravel(), ZZ.ravel()])
    nz = len(zs)
    nid = lambda i, j: i * nz + j
    tris = []
    for i in range(len(rs) - 1):
        for j in range(nz - 1):
            a, b, c, d = nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)
            tris.append([a, b, d]); tris.append([b, c, d])
    return coords, np.array(tris, int), rs, zs


# --------------------------------------------------------------------------
# 2) ASSIGN MATERIALS by element centroid (r_c, z_c) [m]
#    returns: nu (1/μ), sigma (S/m), Js (A/m², signed)
# --------------------------------------------------------------------------
def material(cfg, rc, zc):
    mm = 1e-3
    I = cfg.I
    # --- aluminum plate ---
    p = cfg.plate
    if (rc <= p["radius_mm"] * mm and
            p["z_bottom_mm"] * mm <= zc <= (p["z_bottom_mm"] + p["thickness_mm"]) * mm):
        return 1.0 / (p["mu_r"] * MU0), p["sigma_S_per_m"], 0.0
    # --- payload ---
    if "payload_model" in cfg.raw and cfg.raw["payload_model"].get("enabled", False):
        pl = cfg.raw["payload_model"]
        pz_bot = (p["z_bottom_mm"] + p["thickness_mm"]) * mm
        pz_top = pz_bot + pl["thickness_mm"] * mm
        if rc <= pl["radius_mm"] * mm and pz_bot <= zc <= pz_top:
            return 1.0 / (pl["mu_r"] * MU0), pl.get("sigma_S_per_m", 0.0), 0.0
    # --- iron core ---
    fe = cfg.iron
    if fe.get("enabled", False):
        if (fe["r_inner_mm"] * mm <= rc <= fe["r_outer_mm"] * mm and
                fe["z_bottom_mm"] * mm <= zc <= fe["z_top_mm"] * mm):
            return 1.0 / (fe["mu_r"] * MU0), fe.get("sigma_S_per_m", 0.0), 0.0
    # --- coils (source) ---
    co = cfg.coils
    zt, zb = co["z_top_mm"] * mm, co["z_bottom_mm"] * mm
    for key in ("inner", "outer"):
        c = co[key]
        if (c["r_inner_mm"] * mm <= rc <= c["r_outer_mm"] * mm and zb <= zc <= zt):
            S = (c["r_outer_mm"] - c["r_inner_mm"]) * mm * (zt - zb)  # coil cross-section
            Js = c["current_sign"] * c["turns"] * I / S               # source current density
            return 1.0 / MU0, 0.0, Js
    # --- air ---
    return 1.0 / MU0, 0.0, 0.0


# --------------------------------------------------------------------------
# 3) ASSEMBLY & SOLVE (complex system)
# --------------------------------------------------------------------------
def solve_em(cfg):
    coords, tris, rs, zs = make_mesh_em(cfg)
    nN = coords.shape[0]
    r, z = coords[:, 0], coords[:, 1]
    omega = cfg.omega

    K = sp.lil_matrix((nN, nN), dtype=complex)
    F = np.zeros(nN, dtype=complex)
    ridge = np.zeros((len(tris), 4))  # store rc, area, sigma, |Js| for post-processing

    Mhat = np.array([[2, 1, 1], [1, 2, 1], [1, 1, 2]], float) / 12.0

    for e, (i, j, m) in enumerate(tris):
        ri, rj, rm = r[i], r[j], r[m]
        zi, zj, zm = z[i], z[j], z[m]
        area = 0.5 * abs((rj - ri) * (zm - zi) - (rm - ri) * (zj - zi))
        if area <= 0:
            continue
        rc = (ri + rj + rm) / 3.0
        zc = (zi + zj + zm) / 3.0
        nu, sigma, Js = material(cfg, rc, zc)
        ridge[e] = [rc, area, sigma, Js]

        b = np.array([zj - zm, zm - zi, zi - zj]) / (2 * area)  # dN/dr
        c = np.array([rm - rj, ri - rm, rj - ri]) / (2 * area)  # dN/dz
        # curl-curl (gradient) :  ν (b bᵀ + c cᵀ) · r_c·area
        Ke = nu * (np.outer(b, b) + np.outer(c, c)) * rc * area
        # số hạng A/r² (regularize) :  ν/r_c · area · Mhat
        Ke += nu / rc * area * Mhat
        # eddy currents :  jωσ · r_c·area · Mhat
        Ke = Ke.astype(complex)
        Ke += 1j * omega * sigma * rc * area * Mhat
        # source :  J_s · r_c · area/3 cho mỗi node
        fe = Js * rc * area / 3.0
        idx = [i, j, m]
        for a in range(3):
            F[idx[a]] += fe
            for bb in range(3):
                K[idx[a], idx[bb]] += Ke[a, bb]

    # --- Dirichlet A=0: axis r=0 + outer boundaries ---
    tol = 1e-9
    rmax = rs[-1]; zmin, zmax = zs[0], zs[-1]
    bnd = np.where((r < tol) | (np.abs(r - rmax) < tol) |
                   (np.abs(z - zmin) < tol) | (np.abs(z - zmax) < tol))[0]
    K = K.tocsr()
    for n in bnd:
        K.data[K.indptr[n]:K.indptr[n + 1]] = 0.0
        K[n, n] = 1.0
        F[n] = 0.0
    K.eliminate_zeros()

    A = spla.spsolve(K.tocsc(), F)
    return {"coords": coords, "tris": tris, "A": A, "ridge": ridge,
            "omega": omega, "rs": rs, "zs": zs}


# --------------------------------------------------------------------------
# 4) POST-PROCESSING: loss map + total loss by region
# --------------------------------------------------------------------------
def compute_losses(cfg, res=None):
    if res is None:
        res = solve_em(cfg)
    A, tris, ridge, omega = res["A"], res["tris"], res["ridge"], res["omega"]
    coords = res["coords"]
    mm = 1e-3
    p = cfg.plate
    fe = cfg.iron
    pz0, pz1 = p["z_bottom_mm"] * mm, (p["z_bottom_mm"] + p["thickness_mm"]) * mm
    
    pl = cfg.raw.get("payload_model", {})
    pl_enabled = pl.get("enabled", False)
    pl_z0, pl_z1 = pz1, pz1 + pl.get("thickness_mm", 0.0) * mm

    zc_e = coords[tris][:, :, 1].mean(axis=1)            # z of each element centroid
    Ac = A[tris].mean(axis=1)                            # A at centroid (complex)
    q_e = np.zeros(len(tris))
    P_plate = P_payload = P_iron = 0.0
    for e in range(len(tris)):
        rc, area, sigma, Js = ridge[e]
        if sigma <= 0 or Js != 0.0:
            continue
        q = 0.5 * sigma * omega ** 2 * abs(Ac[e]) ** 2  # W/m³
        dV = 2 * math.pi * rc * area
        if pz0 <= zc_e[e] <= pz1 and rc <= p["radius_mm"] * mm:   # aluminum PLATE
            q_e[e] = q; P_plate += q * dV
        elif pl_enabled and pl_z0 <= zc_e[e] <= pl_z1 and rc <= pl.get("radius_mm", 0.0) * mm:
            q_e[e] = q; P_payload += q * dV
        elif fe.get("enabled", False):                            # iron CORE
            P_iron += q * dV
    # coil ohmic losses: ½ î² R
    co = cfg.coils
    A_wire = math.pi * (co["wire_diameter_mm"] * mm / 2) ** 2
    P_coil = 0.0
    for key in ("inner", "outer"):
        c = co[key]
        r_mean = (c["r_inner_mm"] + c["r_outer_mm"]) / 2 * mm
        R = c["turns"] * (2 * math.pi * r_mean) / (co["sigma_Cu_S_per_m"] * A_wire)
        P_coil += 0.5 * cfg.I ** 2 * R
    return {"q_e": q_e, "P_plate_W": P_plate, "P_payload_W": P_payload, "P_iron_W": P_iron,
            "P_coil_W": P_coil, "P_total_W": P_plate + P_payload + P_iron + P_coil, "res": res}


# --------------------------------------------------------------------------
# 5) LIFT FORCE: cycle-averaged Lorentz force integration over z
#    F_z = -½ Re[ ∫ J_φ · B_r* · 2π r dA ]
#    J_φ = -jωσ A_φ  (dòng xoáy),  B_r = -∂A_φ/∂z  (từ trường hướng r)
# --------------------------------------------------------------------------
def compute_lift_force(cfg, res=None):
    """Cycle-averaged lift force [N] on all conductors (plate + core).
    Positive = upwards (+z). Uses Lorentz integral on current EM mesh.
    """
    if res is None:
        res = solve_em(cfg)
    A = res["A"]
    coords, tris, ridge = res["coords"], res["tris"], res["ridge"]
    r_all, z_all = coords[:, 0], coords[:, 1]
    omega = res["omega"]

    F_z = 0.0
    for e, (i, j, m) in enumerate(tris):
        rc, area, sigma, Js = ridge[e]
        if sigma <= 0 or Js != 0.0:
            continue   # skip air and source regions

        ri, rj, rm = r_all[i], r_all[j], r_all[m]
        zi, zj, zm = z_all[i], z_all[j], z_all[m]

        # Gradient dN/dz cho P1: [rm-rj, ri-rm, rj-ri] / (2·area)
        cz = np.array([rm - rj, ri - rm, rj - ri]) / (2.0 * area)
        dAdz = cz[0] * A[i] + cz[1] * A[j] + cz[2] * A[m]   # ∂A_φ/∂z phức

        A_c = (A[i] + A[j] + A[m]) / 3.0        # A tại tâm phần tử (phức)
        J_phi = -1j * omega * sigma * A_c         # J_φ = -jωσA_φ
        B_r   = -dAdz                             # B_r = -∂A_φ/∂z

        # f_z = (J×B)_z = J_φ·B_r·(-1) → cycle average: -½ Re[J_φ B_r*]
        f_z = -0.5 * (J_phi * B_r.conjugate()).real
        F_z += f_z * 2.0 * math.pi * rc * area

    return F_z   # [N]


# --------------------------------------------------------------------------
# 6) ORIGINAL TEAM 28 BENCHMARK VALIDATION
#    Sweep z_bottom height, find point F_z = mg ≈ 1.05 N → compare with CSV 11.3 mm
# --------------------------------------------------------------------------
def run_benchmark_validation():
    import copy, sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from config import load_config, Geometry

    cfg_base = load_config()
    bm = cfg_base.raw["benchmark_team28_original"]

    cfg = copy.deepcopy(cfg_base)
    cfg.raw["excitation"]["current_A"]  = float(bm["current_A"])
    cfg.raw["iron_core"]["enabled"]     = False                  # original benchmark has no core
    cfg.raw["plate_material"]["radius_mm"] = float(bm["plate_radius_mm"])
    cfg.raw["coils"]["inner"]["turns"]  = int(bm["inner_turns"])
    cfg.raw["coils"]["outer"]["turns"]  = int(bm["outer_turns"])

    R  = float(bm["plate_radius_mm"]) * 1e-3
    t  = float(cfg.raw["plate_material"]["thickness_mm"]) * 1e-3
    rho = float(cfg.raw["plate_material"]["rho_kg_per_m3"])
    m_plate = rho * math.pi * R**2 * t
    F_grav  = m_plate * 9.81

    print(f"\n{'='*60}")
    print(f"Original TEAM 28 Benchmark: I={bm['current_A']}A  "
          f"R={bm['plate_radius_mm']}mm  "
          f"coils {bm['inner_turns']}/{bm['outer_turns']}  NO iron core")
    print(f"m_plate = {m_plate*1e3:.2f} g   →   F_gravity = {F_grav:.4f} N")
    print(f"Expected equilibrium height ≈ {bm['expected_levitation_height_mm']} mm")
    print(f"{'='*60}")
    print(f"  {'z_bottom (mm)':>14}  {'F_z (N)':>10}  {'F_z/mg':>8}  {'note'}")
    print(f"  {'-'*50}")

    z_sweep = np.array([2, 5, 8, 9, 10, 11, 12, 13, 15, 18, 22])   # mm
    F_vals  = []
    for z_mm in z_sweep:
        cfg.raw["plate_material"]["z_bottom_mm"] = float(z_mm)
        cfg.geometry = Geometry(plate_radius_m=R, plate_thickness_m=t,
                                plate_z_bottom_m=float(z_mm) * 1e-3)
        F_z = compute_lift_force(cfg)
        F_vals.append(F_z)
        ratio = F_z / F_grav
        note = "<-- balanced" if abs(ratio - 1.0) < 0.15 else ""
        print(f"  {z_mm:>14.1f}  {F_z:>10.4f}  {ratio:>8.3f}  {note}")

    F_arr = np.array(F_vals)
    mask = np.isfinite(F_arr) & (F_arr > 0)
    if mask.sum() >= 2:
        z_ok = z_sweep[mask]
        F_ok = F_arr[mask]
        if F_ok.max() >= F_grav >= F_ok.min():
            z_eq = float(np.interp(F_grav, F_ok[::-1], z_ok[::-1].astype(float)))
            print(f"\n  → Interpolated equilibrium height: z ≈ {z_eq:.1f} mm  "
                  f"(expected {bm['expected_levitation_height_mm']} mm)")
        else:
            print(f"\n  → F_z is outside gravity range in this sweep.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from config import load_config

    cfg = load_config()
    print(f"Solving EM: î={cfg.I}A, f={cfg.freq}Hz, iron core μ_r={cfg.iron.get('mu_r')}")
    L = compute_losses(cfg)
    print(f"  ALUMINUM PLATE losses (eddy): {L['P_plate_W']*1e3:8.2f} mW")
    print(f"  IRON CORE losses (eddy)     : {L['P_iron_W']:8.3f} W")
    print(f"  COIL losses      (ohmic)    : {L['P_coil_W']:8.3f} W")
    print(f"  TOTAL heat source           : {L['P_total_W']:8.3f} W")

    # I² rule check
    cfg.raw["excitation"]["current_A"] = 2 * cfg.I
    L2 = compute_losses(cfg)
    print(f"  I² Check: P(2î)/P(î) = {L2['P_plate_W']/L['P_plate_W']:.3f} (expected 4.000)")

    run_benchmark_validation()
