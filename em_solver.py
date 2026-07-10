"""Axisymmetric electromagnetic solver (AC, harmonic), pure numpy/scipy — Phase 1b.

Solves the magnetic vector potential equation (azimuthal component A_φ only, COMPLEX phasor):

    -∇·(ν ∇A_φ) + ν A_φ/r²  + jωσ A_φ = J_s        (ν = 1/μ = 1/(μ_r μ0))

- J_s: source current density (azimuthal) in 2 coils = ± N·î/S_coil.
- jωσ A_φ: eddy current reaction in conductors (aluminum, iron core if σ>0).
- Iron core: region with high μ_r -> low ν -> attracts/directs magnetic flux.
- Boundary: A_φ = 0 on axis r=0 (symmetry) and on outer boundary (field vanishes far away).

CYCLE-AVERAGED Joule losses (½ factor from sin²):
    q(r,z) = ½ · σ · ω² · |A_φ|²              [W/m³]   (in conductor)

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
    p = cfg.plate
    # Fine mesh must cover the full device (outer coil now at r=124mm).
    co = cfg.coils
    r_device_mm = max(
        co["outer"]["r_outer_mm"],
        co["inner"]["r_outer_mm"],
        p["radius_mm"],
    ) + 20.0   # 20mm margin beyond outermost component
    r_fine_mm = max(110.0, r_device_mm)
    rs = _graded([(0, r_fine_mm, fs), (r_fine_mm, rmax, cs)]) * 1e-3
    # Fine mesh covers from -60mm to max(15, z_plate_top+10)mm to track plate
    # position -- and the payload's top too, when enabled (M6,
    # docs/AUDIT_FIX_PLAN_2026-07-04.md): a thick payload stacked on the plate
    # would otherwise fall partly into the coarse mesh region with no warning.
    z_top_mm = p["z_bottom_mm"] + p["thickness_mm"]
    pl = cfg.raw.get("payload_model", {})
    if pl.get("enabled", False):
        z_top_mm += float(pl.get("thickness_mm", 0.0))
    z_fine_top = max(15.0, z_top_mm + 10.0)
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
def material(cfg, rc, zc, I_amplitude: float | None = None):
    """I_amplitude: override the phasor current amplitude used for the coil
    source term (Js). None (default) uses cfg.I -- the RMS-measured value,
    treated as amplitude, per the LOSS chain's calibrated convention (see
    config.Config.I_peak docstring). Pass cfg.I_peak here for FORCE
    computations, which need the true physical amplitude."""
    mm = 1e-3
    I = cfg.I if I_amplitude is None else I_amplitude
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
    # --- iron core (center, r=0..25mm, CONFIRMED non-ferromagnetic) ---
    fe = cfg.iron
    if fe.get("enabled", False):
        if (fe["r_inner_mm"] * mm <= rc <= fe["r_outer_mm"] * mm and
                fe["z_bottom_mm"] * mm <= zc <= fe["z_top_mm"] * mm):
            return 1.0 / (fe["mu_r"] * MU0), fe.get("sigma_S_per_m", 0.0), 0.0
    # --- outer iron ring (r=81..101mm, between inner and outer coil; magnet test PENDING) ---
    oir = cfg.raw.get("outer_iron_ring", {})
    if oir.get("enabled", False):
        if (oir["r_inner_mm"] * mm <= rc <= oir["r_outer_mm"] * mm and
                oir["z_bottom_mm"] * mm <= zc <= oir["z_top_mm"] * mm):
            return 1.0 / (oir["mu_r"] * MU0), oir.get("sigma_S_per_m", 0.0), 0.0
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
def solve_em(cfg, nu_e_override=None, outer_bc: str = "dirichlet",
             I_amplitude: float | None = None):
    """Solve EM phasor system.

    nu_e_override: optional list/array of length len(tris).  Each entry is
    either None (use material()) or a float ν value that overrides material()
    for that element — used by solve_em_saturating for nonlinear iron ν.

    I_amplitude: forwarded to material() for the coil source term. None
    (default) = cfg.I, the loss-chain convention (see material() docstring).

    outer_bc: boundary condition on the FAR outer domain edge (r=r_max, z=z_min,
    z=z_max). The axis r=0 is ALWAYS A_φ=0 (physical symmetry condition, not a
    domain-size choice).
        "dirichlet" (default) — A_φ=0 on the outer edge (field vanishes far away).
        "neumann"              — ∂A_φ/∂n=0 on the outer edge. Achieved by leaving
                                  those DOFs unconstrained: in the FEM weak form,
                                  not imposing a Dirichlet condition is exactly the
                                  natural (zero-flux) boundary condition.
    Used by validate_domain_size() to check the 1x1m em_domain is large enough
    (professor, Juni 2026): if Dirichlet and Neumann agree near the device, the
    domain does not influence the result and is big enough.
    """
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
        nu, sigma, Js = material(cfg, rc, zc, I_amplitude=I_amplitude)
        # Per-element ν override (for nonlinear iron saturation)
        if nu_e_override is not None and nu_e_override[e] is not None:
            nu = float(nu_e_override[e])
        ridge[e] = [rc, area, sigma, Js]

        b = np.array([zj - zm, zm - zi, zi - zj]) / (2 * area)  # dN/dr
        c = np.array([rm - rj, ri - rm, rj - ri]) / (2 * area)  # dN/dz
        # curl-curl (gradient) :  ν (b bᵀ + c cᵀ) · r_c·area
        Ke = nu * (np.outer(b, b) + np.outer(c, c)) * rc * area
        # A/r² term (regularize): ν/r_c · area · Mhat
        Ke += nu / rc * area * Mhat
        # eddy currents :  jωσ · r_c·area · Mhat
        Ke = Ke.astype(complex)
        Ke += 1j * omega * sigma * rc * area * Mhat
        # source: J_s · r_c · area/3 per node
        fe = Js * rc * area / 3.0
        idx = [i, j, m]
        for a in range(3):
            F[idx[a]] += fe
            for bb in range(3):
                K[idx[a], idx[bb]] += Ke[a, bb]

    # --- axis r=0: ALWAYS Dirichlet A=0 (physical symmetry, not a domain choice) ---
    tol = 1e-9
    rmax = rs[-1]; zmin, zmax = zs[0], zs[-1]
    bnd = np.where(r < tol)[0]
    # --- far outer edge (r=r_max, z=z_min, z=z_max): Dirichlet or Neumann ---
    if outer_bc == "dirichlet":
        outer = np.where((np.abs(r - rmax) < tol) |
                          (np.abs(z - zmin) < tol) | (np.abs(z - zmax) < tol))[0]
        bnd = np.union1d(bnd, outer)
    elif outer_bc == "neumann":
        pass  # leave outer DOFs free -> natural (zero-flux) BC
    else:
        raise ValueError(f"outer_bc must be 'dirichlet' or 'neumann', got {outer_bc!r}")
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
# 3b) B-FIELD PER ELEMENT  (used by saturation check and Picard solver)
# --------------------------------------------------------------------------
def _compute_B_per_element(res):
    """Return RMS |B| [T] at each element centroid from the A_φ solution.

    Axisymmetric relations:
        B_r = -∂A_φ/∂z          B_z = A_φ/r + ∂A_φ/∂r
    RMS from peak phasor: |B|_rms = sqrt(|B_r|² + |B_z|²) / sqrt(2).
    """
    A_sol = res["A"]
    coords, tris = res["coords"], res["tris"]
    r_all, z_all = coords[:, 0], coords[:, 1]
    B_e = np.zeros(len(tris))
    for e, (i, j, m) in enumerate(tris):
        ri, rj, rm = r_all[i], r_all[j], r_all[m]
        zi, zj, zm = z_all[i], z_all[j], z_all[m]
        area = 0.5 * abs((rj - ri) * (zm - zi) - (rm - ri) * (zj - zi))
        if area <= 0:
            continue
        rc = (ri + rj + rm) / 3.0
        # Shape-function gradients: b=dN/dr, c=dN/dz  (same as assembly)
        b = np.array([zj - zm, zm - zi, zi - zj]) / (2 * area)
        c = np.array([rm - rj, ri - rm, rj - ri]) / (2 * area)
        Ai, Aj, Am = A_sol[i], A_sol[j], A_sol[m]
        dAdr = b[0] * Ai + b[1] * Aj + b[2] * Am
        dAdz = c[0] * Ai + c[1] * Aj + c[2] * Am
        A_c  = (Ai + Aj + Am) / 3.0
        B_r  = -dAdz                                    # complex phasor
        B_z  = (A_c / max(rc, 1e-12)) + dAdr           # complex phasor
        B_e[e] = math.sqrt(abs(B_r) ** 2 + abs(B_z) ** 2) / math.sqrt(2)
    return B_e


def check_saturation(res, cfg=None, B_scale: float = 1.0):
    """Compute max RMS |B| in the iron core region.

    B_scale: multiply the computed B by this factor. `res` was solved at
    whatever current amplitude its own solve_em()/solve_em_saturating() call
    used -- by default that's cfg.I (the loss-chain's RMS-as-amplitude
    convention). Since the EM problem is linear, B scales exactly linearly
    with that amplitude, so passing B_scale=cfg.I_peak/cfg.I converts the
    result to the TRUE physical B [T] (needed to meaningfully compare against
    B_sat_T, a real material property) without re-solving. Leave at the
    default 1.0 for internal callers (solve_em_saturating's own Picard loop
    calls _compute_B_per_element directly, not through here, and must stay on
    the loss chain's convention -- see WP-PEAK in
    docs/AUDIT_FIX_PLAN_2026-07-04.md).

    Returns (B_max_iron, B_e) where:
        B_max_iron  [T]  — peak RMS B inside iron region (0 if iron disabled)
        B_e         [T]  — per-element RMS B array over all elements
    """
    if cfg is None:
        from config import load_config
        cfg = load_config()

    B_e = _compute_B_per_element(res) * B_scale

    fe = cfg.iron
    B_max_iron = 0.0
    if fe.get("enabled", False):
        coords, tris, ridge = res["coords"], res["tris"], res["ridge"]
        z_all = coords[:, 1]
        mm = 1e-3
        r0, r1 = fe["r_inner_mm"] * mm, fe["r_outer_mm"] * mm
        z0, z1 = fe["z_bottom_mm"] * mm, fe["z_top_mm"] * mm
        for e in range(len(tris)):
            rc = ridge[e, 0]
            zc = (z_all[tris[e, 0]] + z_all[tris[e, 1]] + z_all[tris[e, 2]]) / 3.0
            if r0 <= rc <= r1 and z0 <= zc <= z1:
                if B_e[e] > B_max_iron:
                    B_max_iron = B_e[e]
    return B_max_iron, B_e


# --------------------------------------------------------------------------
# 3c) NONLINEAR SOLVE — Picard iteration for iron saturation
# --------------------------------------------------------------------------
def solve_em_saturating(cfg, max_iter: int = 20, tol: float = 0.02,
                        relax: float = 0.5, outer_bc: str = "dirichlet",
                        I_amplitude: float | None = None):
    """EM solve with iron saturation via Picard (fixed-point) iteration.

    Saturation model (Lorentzian):
        μ_r_eff(B) = 1 + (μ_r_lin − 1) / (1 + (B / B_sat)²)

    Gives μ_r_eff → μ_r_lin for B → 0 and μ_r_eff → 1 for B >> B_sat.
    Under-relaxation (relax=0.5) stabilises convergence.

    Handles saturation correction for BOTH iron_core and outer_iron_ring regions
    (generalized 2026-07-11, previously iron_core only). Each region maintains
    its own μ_r and saturation threshold.

    I_amplitude: forwarded to solve_em() for the coil source term. None
    (default) = cfg.I -- this loop's own nonlinear μ_r update (below) must
    stay on whatever convention the CALLER needs (compute_losses() relies on
    the default to keep P_plate/P_coil unchanged; force-oriented callers may
    pass cfg.I_peak). Currently a no-op while μ_r=1.0 (Lorentzian reduces to
    μ_r_eff≡1 regardless of B) -- see docstring in check_saturation().

    Falls back to linear solve() if all iron regions are disabled.
    Returns the same dict as solve_em().
    """
    fe = cfg.iron
    oir = cfg.raw.get("outer_iron_ring", {})
    mm = 1e-3

    # Check if either ferromagnetic region is enabled
    core_enabled = fe.get("enabled", False) and float(fe.get("mu_r", 1.0)) > 1.1
    ring_enabled = oir.get("enabled", False) and float(oir.get("mu_r", 1.0)) > 1.1

    if not (core_enabled or ring_enabled):
        return solve_em(cfg, outer_bc=outer_bc, I_amplitude=I_amplitude)

    # Initial linear solve
    res = solve_em(cfg, outer_bc=outer_bc, I_amplitude=I_amplitude)
    coords, tris, ridge = res["coords"], res["tris"], res["ridge"]
    z_all = coords[:, 1]

    # Identify element indices for both ferromagnetic regions (once)
    iron_idx, oir_idx = [], []
    if core_enabled:
        r0_fe, r1_fe = fe["r_inner_mm"] * mm, fe["r_outer_mm"] * mm
        z0_fe, z1_fe = fe["z_bottom_mm"] * mm, fe["z_top_mm"] * mm
        iron_idx = [
            e for e in range(len(tris))
            if (r0_fe <= ridge[e, 0] <= r1_fe and
                z0_fe <= (z_all[tris[e, 0]] + z_all[tris[e, 1]] + z_all[tris[e, 2]]) / 3.0 <= z1_fe)
        ]

    if ring_enabled:
        r0_oir, r1_oir = oir["r_inner_mm"] * mm, oir["r_outer_mm"] * mm
        z0_oir, z1_oir = oir["z_bottom_mm"] * mm, oir["z_top_mm"] * mm
        oir_idx = [
            e for e in range(len(tris))
            if (r0_oir <= ridge[e, 0] <= r1_oir and
                z0_oir <= (z_all[tris[e, 0]] + z_all[tris[e, 1]] + z_all[tris[e, 2]]) / 3.0 <= z1_oir)
        ]

    if not (iron_idx or oir_idx):
        return res

    # Prepare override array and initialize ν for both regions
    nu_e_override = [None] * len(tris)
    nu_iron = np.full(len(iron_idx), 1.0 / (float(fe.get("mu_r", 1000.0)) * MU0)) if iron_idx else np.array([])
    nu_oir = np.full(len(oir_idx), 1.0 / (float(oir.get("mu_r", 1000.0)) * MU0)) if oir_idx else np.array([])

    B_sat_core = float(fe.get("B_sat_T", 1.5))
    B_sat_ring = float(oir.get("B_sat_T", 1.5))
    mu_r_lin_core = float(fe.get("mu_r", 1000.0))
    mu_r_lin_ring = float(oir.get("mu_r", 1000.0))

    for it in range(max_iter):
        B_e = _compute_B_per_element(res)

        # Extract B in each ferromagnetic region
        B_iron = np.array([B_e[e] for e in iron_idx]) if iron_idx else np.array([])
        B_oir = np.array([B_e[e] for e in oir_idx]) if oir_idx else np.array([])
        B_max = float(np.concatenate([B_iron, B_oir]).max()) if (len(B_iron) > 0 or len(B_oir) > 0) else 0.0

        # Update μ_r for iron_core
        if iron_idx:
            mu_r_eff_core = 1.0 + (mu_r_lin_core - 1.0) / (1.0 + (B_iron / B_sat_core) ** 2)
            nu_iron_new = 1.0 / (mu_r_eff_core * MU0)
            nu_iron = (1.0 - relax) * nu_iron + relax * nu_iron_new
            for ii, e in enumerate(iron_idx):
                nu_e_override[e] = nu_iron[ii]

        # Update μ_r for outer_iron_ring
        if oir_idx:
            mu_r_eff_ring = 1.0 + (mu_r_lin_ring - 1.0) / (1.0 + (B_oir / B_sat_ring) ** 2)
            nu_oir_new = 1.0 / (mu_r_eff_ring * MU0)
            nu_oir = (1.0 - relax) * nu_oir + relax * nu_oir_new
            for ii, e in enumerate(oir_idx):
                nu_e_override[e] = nu_oir[ii]

        res_new = solve_em(cfg, nu_e_override=nu_e_override, outer_bc=outer_bc,
                           I_amplitude=I_amplitude)

        # Convergence check on vector potential
        dA_rel = float(np.abs(res_new["A"] - res["A"]).max() /
                       (np.abs(res_new["A"]).max() + 1e-30))

        # Report both regions' μ_r if both present
        mu_r_str = f"B_max={B_max:.3f}T"
        if iron_idx and oir_idx:
            mu_r_str += f"  μ_r_core={float(mu_r_eff_core.mean()):.0f}  μ_r_ring={float(mu_r_eff_ring.mean()):.0f}"
        elif iron_idx:
            mu_r_str += f"  μ_r_core={float(mu_r_eff_core.mean()):.0f}"
        elif oir_idx:
            mu_r_str += f"  μ_r_ring={float(mu_r_eff_ring.mean()):.0f}"

        print(f"    [SAT {it+1:2d}] {mu_r_str}  ΔA_rel={dA_rel:.4f}", flush=True)
        res = res_new

        if dA_rel < tol and it >= 1:
            print(f"    Saturation converged after {it + 1} iterations.")
            break
    else:
        print(f"    Warning: saturation did not converge in {max_iter} iterations.")

    return res


# --------------------------------------------------------------------------
# 4) POST-PROCESSING: loss map + total loss by region
# --------------------------------------------------------------------------
def compute_losses(cfg, res=None, outer_bc: str = "dirichlet"):
    if res is None:
        res = solve_em_saturating(cfg, outer_bc=outer_bc)  # handles saturation when iron enabled
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
#    J_φ = -jωσ A_φ  (eddy current),  B_r = -∂A_φ/∂z  (radial magnetic field)
# --------------------------------------------------------------------------
def compute_lift_force(cfg, res=None, I_amplitude: float | None = None):
    """Cycle-averaged lift force [N] on all conductors (plate + core).
    Positive = upwards (+z). Uses Lorentz integral on current EM mesh.

    I_amplitude: forwarded to solve_em() when res is None (ignored if a
    pre-solved res is passed in -- its amplitude is already baked in). None
    (default) = cfg.I, UNCHANGED from before this parameter existed, so
    existing callers that don't pass anything are unaffected. Force
    computations that want the true physical amplitude should pass
    cfg.I_peak explicitly (see config.Config.I_peak docstring / CLAUDE.md
    "CURRENT CONVENTION") -- this replaces the old pattern of manually
    multiplying the returned F_z by 2.0.
    """
    if res is None:
        res = solve_em(cfg, I_amplitude=I_amplitude)
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
        dAdz = cz[0] * A[i] + cz[1] * A[j] + cz[2] * A[m]   # ∂A_φ/∂z (complex)

        A_c = (A[i] + A[j] + A[m]) / 3.0        # A at element centroid (complex)
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
    if "outer_iron_ring" in cfg.raw:
        cfg.raw["outer_iron_ring"]["enabled"] = False             # ditto -- no separator ring either
    if "payload_model" in cfg.raw:
        cfg.raw["payload_model"]["enabled"] = False                # ditto -- no payload in the original problem
    cfg.raw["plate_material"]["radius_mm"] = float(bm["plate_radius_mm"])
    cfg.raw["coils"]["inner"]["turns"]  = int(bm["inner_turns"])
    cfg.raw["coils"]["outer"]["turns"]  = int(bm["outer_turns"])
    # Original problem's OWN coil geometry (TeamProblem28.pdf Fig.2) -- much
    # narrower than this rig's coils, so it needs its own radii (NOT the rig's).
    cfg.raw["coils"]["inner"]["r_inner_mm"] = float(bm["inner_r_inner_mm"])
    cfg.raw["coils"]["inner"]["r_outer_mm"] = float(bm["inner_r_outer_mm"])
    cfg.raw["coils"]["outer"]["r_inner_mm"] = float(bm["outer_r_inner_mm"])
    cfg.raw["coils"]["outer"]["r_outer_mm"] = float(bm["outer_r_outer_mm"])
    # The benchmark's coils are much narrower (13mm / 5.5mm wide) than the rig's --
    # the rig's default fine_step_mm=2.0 under-resolves them badly (mesh-convergence
    # tested 2026-06-23: F at z=11.3mm jumps 0.50N->0.73N going from 2.0mm->1.0mm,
    # then settles ~0.70N by 0.2mm). Override just for this benchmark; the rig's own
    # EM solves don't need this finer (slower) mesh.
    cfg.raw["em_domain"]["fine_step_mm"] = 0.2

    R  = float(bm["plate_radius_mm"]) * 1e-3
    t  = float(cfg.raw["plate_material"]["thickness_mm"]) * 1e-3
    rho = float(cfg.raw["plate_material"]["rho_kg_per_m3"])
    m_plate = rho * math.pi * R**2 * t
    F_grav  = m_plate * 9.81

    print(f"\n{'='*60}")
    print(f"Original TEAM 28 Benchmark: I={bm['current_A']}A  "
          f"R={bm['plate_radius_mm']}mm  "
          f"coils {bm['inner_turns']}/{bm['outer_turns']}  NO iron core")
    print(f"Coil geometry from TeamProblem28.pdf Fig.2: inner r={bm['inner_r_inner_mm']}-"
          f"{bm['inner_r_outer_mm']}mm, outer r={bm['outer_r_inner_mm']}-{bm['outer_r_outer_mm']}mm")
    print(f"m_plate = {m_plate*1e3:.2f} g   →   F_gravity = {F_grav:.4f} N")
    print(f"Expected equilibrium height ≈ {bm['expected_levitation_height_mm']} mm")
    print(f"{'='*60}")
    print(f"  {'z_bottom (mm)':>14}  {'F_z (N)':>10}  {'F_z/mg':>8}  {'note'}")
    print(f"  {'-'*50}")

    # WP-PEAK (docs/AUDIT_FIX_PLAN_2026-07-04.md): force needs the TRUE phasor
    # amplitude (I_peak = I_rms*sqrt(2)), not I_rms used as-if-amplitude (the
    # loss chain's calibrated convention -- see config.Config.I_peak docstring).
    # Mirrors the fix already applied to run_rig_validation() below (commit
    # c37e8b8, 2026-07-10) -- this call site was missed by that commit.
    z_sweep = np.array([3, 4, 5, 6, 7, 8, 9, 10, 11, 11.3, 13, 15, 18])   # mm
    F_vals  = []
    for z_mm in z_sweep:
        cfg.raw["plate_material"]["z_bottom_mm"] = float(z_mm)
        cfg.geometry = Geometry(plate_radius_m=R, plate_thickness_m=t,
                                plate_z_bottom_m=float(z_mm) * 1e-3)
        F_z = compute_lift_force(cfg, I_amplitude=cfg.I_peak)
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


# --------------------------------------------------------------------------
# 6b) REAL-RIG LIFT-FORCE VALIDATION
#     Sweep plate height for the actual rig (1000/500 turns, 5A, R=80mm).
#     User observation (2026-07-01): Al disc ~150-200g levitates at ~7-8mm
#     gap above the coil top at 5A/190V.  Validates the EM solver on the
#     real device (independently of the TEAM28 benchmark, which uses
#     different coil geometry and 20A — see run_benchmark_validation()).
# --------------------------------------------------------------------------
def run_rig_validation():
    """Compute F_z vs plate height for the actual rig and find z_eq."""
    import copy, sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from config import load_config, Geometry

    cfg = load_config()
    p   = cfg.plate
    R   = p["radius_mm"]    * 1e-3
    t   = p["thickness_mm"] * 1e-3
    rho = p["rho_kg_per_m3"]
    m_plate = rho * math.pi * R ** 2 * t
    F_grav  = m_plate * 9.81
    co = cfg.coils

    print(f"\n{'='*60}")
    print(f"RIG LIFT-FORCE SWEEP: I={cfg.I}A_rms (I_peak={cfg.I_peak:.3f}A)  "
          f"R={p['radius_mm']}mm  coils {co['inner']['turns']}/{co['outer']['turns']}")
    print(f"Plate: m={m_plate*1e3:.1f}g  F_gravity={F_grav:.4f}N")
    print(f"Coil top z={co['z_top_mm']}mm  (z_bottom = gap above coil top)")
    print(f"Observed: disc levitates at ~7-8 mm VISIBLE gap (plate top above "
          f"coil top) at 5A/190V (2026-07-01)")
    print(f"{'='*60}")
    print(f"  {'z_bottom (mm)':>14}  {'F_z (N)':>10}  {'F_z/mg':>8}  note")
    print(f"  {'-'*50}")

    # WP-PEAK (docs/AUDIT_FIX_PLAN_2026-07-04.md): force needs the TRUE phasor
    # amplitude (I_peak = I_rms*sqrt(2)), not I_rms used as-if-amplitude (the
    # loss chain's calibrated convention -- see config.Config.I_peak docstring).
    # This was previously a manual "×2.0 the returned F_z" patch at the caller;
    # now handled cleanly via compute_lift_force's I_amplitude parameter.
    z_sweep = np.array([1, 2, 3, 3.8, 5, 6, 7, 8, 9, 10, 12, 15, 18])
    F_vals  = []
    for z_mm in z_sweep:
        cfg.raw["plate_material"]["z_bottom_mm"] = float(z_mm)
        cfg.geometry = Geometry(plate_radius_m=R, plate_thickness_m=t,
                                plate_z_bottom_m=float(z_mm) * 1e-3)
        F_z = compute_lift_force(cfg, I_amplitude=cfg.I_peak)
        F_vals.append(F_z)
        ratio = F_z / F_grav
        note = "<-- balanced" if abs(ratio - 1.0) < 0.12 else ""
        print(f"  {z_mm:>14.1f}  {F_z:>10.4f}  {ratio:>8.3f}  {note}")

    F_arr = np.array(F_vals)
    mask  = np.isfinite(F_arr) & (F_arr > 0)
    if mask.sum() >= 2:
        z_ok = z_sweep[mask];  F_ok = F_arr[mask]
        if F_ok.max() >= F_grav >= F_ok.min():
            z_eq = float(np.interp(F_grav, F_ok[::-1], z_ok[::-1].astype(float)))
            # z_eq above is the PLATE-BOTTOM equilibrium height; the "~7-8mm"
            # user observation is the VISIBLE gap (plate TOP above coil top),
            # i.e. z_eq + plate thickness (see CLAUDE.md "LIFT FORCE VALIDATED
            # 2026-07-01": z_eq(bottom)=4.1mm + 3mm thickness = 7.1mm visible).
            # Comparing z_eq directly against 7.5mm (as this code did before
            # WP-PEAK) was an apples-to-oranges bug -- fixed by comparing the
            # VISIBLE top instead, keeping z_eq itself labeled as plate-bottom.
            visible_top_mm = z_eq + t * 1e3
            err = abs(visible_top_mm - 7.5)     # target midpoint of the observed 7-8mm VISIBLE range
            print(f"\n  → Predicted z_eq (plate bottom) ≈ {z_eq:.1f} mm  "
                  f"(visible plate-top gap ≈ {visible_top_mm:.1f} mm)")
            print(f"  → Observed visible gap ~7-8 mm:  "
                  f"{'MATCH ✓' if err < 2.0 else f'MISMATCH (Δ={err:.1f} mm)'}")
        else:
            lo, hi = F_ok.min(), F_ok.max()
            print(f"\n  → F_z = [{lo:.3f}, {hi:.3f}] N does not bracket "
                  f"F_gravity={F_grav:.3f} N — sweep range too small.")
    print(f"{'='*60}\n")


# --------------------------------------------------------------------------
# 7) DOMAIN SIZE VALIDATION: Dirichlet vs Neumann outer BC
#    Professor (Juni 2026): run the same EM problem with (a) A_φ=0 on the far
#    outer edge and (b) ∂A_φ/∂n=0 there. If results near the device agree, the
#    1x1m em_domain is large enough; if they diverge, enlarge em_domain (params.yaml).
# --------------------------------------------------------------------------
def validate_domain_size(cfg, tol_percent: float = 1.0, verbose: bool = True):
    """Compare Dirichlet vs Neumann outer BC to check the EM domain is large enough.

    Runs compute_losses() twice (outer_bc="dirichlet" and "neumann") and compares
    P_plate_W / P_iron_W / P_coil_W / P_total_W, plus |A_φ| sampled near the plate.
    Small differences mean the far-field boundary doesn't influence the
    near-device solution -> domain is big enough. Large differences mean the
    boundary is too close and em_domain should be enlarged.

    Returns True (pass, diffs < tol_percent) / False (fail -> enlarge domain).
    """
    L_dir = compute_losses(cfg, outer_bc="dirichlet")
    L_neu = compute_losses(cfg, outer_bc="neumann")

    def pct(a, b):
        denom = max(abs(a), abs(b), 1e-30)
        return abs(a - b) / denom * 100.0

    diffs = {
        "P_plate_W": pct(L_dir["P_plate_W"], L_neu["P_plate_W"]),
        "P_iron_W":  pct(L_dir["P_iron_W"],  L_neu["P_iron_W"]),
        "P_coil_W":  pct(L_dir["P_coil_W"],  L_neu["P_coil_W"]),
        "P_total_W": pct(L_dir["P_total_W"], L_neu["P_total_W"]),
    }

    # Near-field comparison: |A_φ| at the mesh node closest to the plate centroid.
    coords = L_dir["res"]["coords"]
    mm = 1e-3
    p = cfg.plate
    r_probe = 0.5 * p["radius_mm"] * mm
    z_probe = (p["z_bottom_mm"] + 0.5 * p["thickness_mm"]) * mm
    node = int(np.argmin(np.hypot(coords[:, 0] - r_probe, coords[:, 1] - z_probe)))
    A_dir = abs(L_dir["res"]["A"][node])
    A_neu = abs(L_neu["res"]["A"][node])
    diffs["|A_phi|_near_plate"] = pct(A_dir, A_neu)

    passed = all(d < tol_percent for d in diffs.values())

    if verbose:
        em = cfg.em
        print(f"\n{'='*60}")
        print("DOMAIN SIZE VALIDATION: Dirichlet vs Neumann outer BC")
        print(f"  em_domain: r_max={em['r_max_mm']:.0f}mm  "
              f"z=[{em['z_min_mm']:.0f}, {em['z_max_mm']:.0f}]mm")
        print(f"{'='*60}")
        print(f"  {'quantity':>20}  {'Dirichlet':>12}  {'Neumann':>12}  {'diff %':>8}")
        print(f"  {'-'*58}")
        print(f"  {'P_plate_W':>20}  {L_dir['P_plate_W']:12.6f}  {L_neu['P_plate_W']:12.6f}  {diffs['P_plate_W']:8.3f}")
        print(f"  {'P_iron_W':>20}  {L_dir['P_iron_W']:12.6f}  {L_neu['P_iron_W']:12.6f}  {diffs['P_iron_W']:8.3f}")
        print(f"  {'P_coil_W':>20}  {L_dir['P_coil_W']:12.6f}  {L_neu['P_coil_W']:12.6f}  {diffs['P_coil_W']:8.3f}")
        print(f"  {'P_total_W':>20}  {L_dir['P_total_W']:12.6f}  {L_neu['P_total_W']:12.6f}  {diffs['P_total_W']:8.3f}")
        print(f"  {'|A_phi|_near_plate':>20}  {A_dir:12.3e}  {A_neu:12.3e}  {diffs['|A_phi|_near_plate']:8.3f}")
        print(f"  {'-'*58}")
        verdict = "PASS" if passed else "FAIL"
        print(f"  -> {verdict} (tolerance {tol_percent:.1f}%): "
              f"{'domain is large enough' if passed else 'ENLARGE em_domain in params.yaml'}")
        print(f"{'='*60}\n")

    return passed


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
    
    # B is a real material property comparison (B_sat_T) -- report the TRUE
    # physical B (I_peak-scaled), not L["res"]'s own loss-chain convention
    # (cfg.I used as amplitude). See check_saturation()'s B_scale docstring.
    B_max_iron, _ = check_saturation(L["res"], cfg, B_scale=cfg.I_peak / cfg.I)
    B_sat = float(cfg.iron.get("B_sat_T", 1.5))
    print(f"  MAX B in iron (RMS)         : {B_max_iron:.3f} T  (B_sat={B_sat} T)")
    if B_max_iron > B_sat:
        print(f"  !!! SATURATED: B_max={B_max_iron:.2f}T > B_sat={B_sat}T. "
              "Nonlinear μ_r correction applied by solve_em_saturating().")

    # I² rule check
    cfg.raw["excitation"]["current_A"] = 2 * cfg.I
    L2 = compute_losses(cfg)
    print(f"  I² Check: P(2î)/P(î) = {L2['P_plate_W']/L['P_plate_W']:.3f} (expected 4.000)")

    run_benchmark_validation()
    run_rig_validation()

    # Domain size validation (professor, Juni 2026): Dirichlet vs Neumann outer BC.
    # Fresh load: the I² check above mutated cfg.raw's current_A to 2*î.
    cfg_domain = load_config()
    validate_domain_size(cfg_domain)
