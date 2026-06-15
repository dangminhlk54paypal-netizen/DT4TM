"""Axisymmetric thermal solver, P1 triangles, pure numpy/scipy.

Solves:  -div(k grad T) = p(r,z)   in plate
Convection boundary (Robin):  -k dT/dn = h (T - T_inf)
Axis r=0: symmetry (natural condition, no need to impose).

Axisymmetric volume integration uses r weight (dV = 2*pi*r dr dz).
Heat source p(r,z): if em_losses is passed from em_solver.compute_losses(),
uses the real eddy current map (interpolated from EM mesh); otherwise uses a placeholder.
"""
from __future__ import annotations
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator


# --------------------------------------------------------------------------
# 1) MESH: rectangular cross-section r in [0,R], z in [0,t]  -> structured triangles
# --------------------------------------------------------------------------
def make_mesh_stacked(R_plate: float, t_plate: float, R_payload: float, t_payload: float, dr: float, dz: float):
    # Combine 2 domains: aluminum plate and payload
    r_pts = sorted(list(set([0.0, R_plate, R_payload])))
    rs = []
    for i in range(len(r_pts)-1):
        s, e = r_pts[i], r_pts[i+1]
        if e > s:
            n = max(1, int(round((e - s) / dr)))
            rs.append(np.linspace(s, e, n+1)[:-1])
    rs.append([r_pts[-1]])
    rs = np.concatenate(rs)

    z_pts = sorted(list(set([0.0, t_plate, t_plate + t_payload])))
    zs = []
    for i in range(len(z_pts)-1):
        s, e = z_pts[i], z_pts[i+1]
        if e > s:
            n = max(1, int(round((e - s) / dz)))
            zs.append(np.linspace(s, e, n+1)[:-1])
    zs.append([z_pts[-1]])
    zs = np.concatenate(zs)

    RR, ZZ = np.meshgrid(rs, zs, indexing="ij")
    full_coords = np.column_stack([RR.ravel(), ZZ.ravel()])

    nr_nodes, nz_nodes = len(rs), len(zs)
    def nid(i, j): return i * nz_nodes + j

    tris = []
    for i in range(nr_nodes - 1):
        for j in range(nz_nodes - 1):
            rc = (rs[i] + rs[i+1]) / 2.0
            zc = (zs[j] + zs[j+1]) / 2.0
            in_plate = (rc <= R_plate) and (zc <= t_plate)
            in_payload = (rc <= R_payload) and (zc >= t_plate) and (zc <= t_plate + t_payload)
            if in_plate or in_payload:
                a, b, c, d = nid(i, j), nid(i+1, j), nid(i+1, j+1), nid(i, j+1)
                tris.extend([[a, b, d], [b, c, d]])

    used_nodes = np.unique(tris)
    node_map = {old: new for new, old in enumerate(used_nodes)}
    coords = full_coords[used_nodes]
    mapped_tris = np.array([[node_map[n] for n in tri] for tri in tris], dtype=int)
    return coords, mapped_tris


# --------------------------------------------------------------------------
# 2) HEAT SOURCE
# --------------------------------------------------------------------------
def heat_source(rc, zc, R, t, P_total):
    """Placeholder: analytical form, strong at bottom & outer rim (simulating eddy currents)."""
    delta = 0.25 * t
    return np.exp(-zc / delta) * (0.3 + (rc / R) ** 2)


def _interp_em_losses(em_losses: dict, rc_e: np.ndarray,
                      zc_e_local: np.ndarray, cfg) -> np.ndarray:
    """Interpolate q_e [W/m³] from EM mesh (global z) to thermal mesh element centroids (local z).

    EM mesh: global z (z_bottom_m = cfg.geometry.plate_z_bottom_m).
    Thermal mesh: local z ∈ [0, t], z_local = z_global − z_bottom_m.
    Uses LinearNDInterpolator; NearestNDInterpolator as fallback outside hull.
    """
    em_res    = em_losses["res"]
    q_e_em    = em_losses["q_e"]        # [W/m³] per EM element
    em_tris   = em_res["tris"]
    em_coords = em_res["coords"]

    mask = q_e_em > 0
    if not mask.any():
        return np.zeros_like(rc_e)

    # Centroids of EM elements in the plate
    tri_coords = em_coords[em_tris[mask]]          # (N, 3, 2)
    em_rc  = tri_coords[:, :, 0].mean(axis=1)
    em_zglobal = tri_coords[:, :, 1].mean(axis=1)

    z_bottom_m = cfg.geometry.plate_z_bottom_m
    em_zlocal  = em_zglobal - z_bottom_m

    pts  = np.c_[em_rc, em_zlocal]
    vals = q_e_em[mask]

    q_lin = LinearNDInterpolator(pts, vals, fill_value=np.nan)(
        np.c_[rc_e, zc_e_local])
    nan_mask = np.isnan(q_lin)
    if nan_mask.any():
        q_lin[nan_mask] = NearestNDInterpolator(pts, vals)(
            np.c_[rc_e[nan_mask], zc_e_local[nan_mask]])

    return np.maximum(q_lin, 0.0)


# --------------------------------------------------------------------------
# 3) ASSEMBLY & SOLVE
# --------------------------------------------------------------------------
def solve_steady(cfg, P_total_override=None, em_losses=None):
    """Solve steady-state heat for the plate.

    P_total_override: if passed, uses this value instead of cfg.total_power_W.
    em_losses: dict from em_solver.compute_losses(). If present, uses real q_e map
               instead of analytical placeholder; P_total is taken from P_plate_W.
    """
    R = cfg.geometry.plate_radius_m
    t = cfg.geometry.plate_thickness_m
    k_plate = float(cfg.plate["k_W_per_mK"])
    h      = float(cfg.bc["h_convection_W_per_m2K"])
    h_bot  = float(cfg.bc.get("h_bottom_W_per_m2K", h))   # bottom surface facing coils
    Tinf = float(cfg.bc["T_ambient_degC"])

    pl_cfg = cfg.raw.get("payload_model", {})
    if pl_cfg.get("enabled", False):
        R_pl = pl_cfg.get("radius_mm", 0.0) * 1e-3
        t_pl = pl_cfg.get("thickness_mm", 0.0) * 1e-3
        k_payload = float(pl_cfg.get("k_W_per_mK", k_plate))
    else:
        R_pl, t_pl, k_payload = 0.0, 0.0, k_plate

    if P_total_override is not None:
        P_total = P_total_override
    elif em_losses is not None:
        # q_e map covers plate + payload elements, so the source budget must too,
        # otherwise payload heat gets squashed into the plate budget on normalization.
        P_total = em_losses["P_plate_W"] + em_losses.get("P_payload_W", 0.0)
    else:
        P_total = cfg.total_power_W

    dr, dz = R / int(cfg.mesh["nr"]), t / int(cfg.mesh["nz"])
    coords, tris = make_mesh_stacked(R, t, R_pl, t_pl, dr, dz)
    nN = coords.shape[0]
    r = coords[:, 0]
    z = coords[:, 1]

    K = sp.lil_matrix((nN, nN))
    F = np.zeros(nN)

    # relative heat source per element + energy normalization
    shape_e = np.zeros(len(tris))
    area_e  = np.zeros(len(tris))
    rc_e    = np.zeros(len(tris))
    zc_e    = np.zeros(len(tris))

    for e, (i, j, m) in enumerate(tris):
        ri, rj, rm = r[i], r[j], r[m]
        zi, zj, zm = z[i], z[j], z[m]
        area = 0.5 * abs((rj - ri) * (zm - zi) - (rm - ri) * (zj - zi))
        rc = (ri + rj + rm) / 3.0
        zc = (zi + zj + zm) / 3.0
        area_e[e]  = area
        rc_e[e]    = rc
        zc_e[e]    = zc
        shape_e[e] = heat_source(rc, zc, R, t, P_total)
        
        k_e = k_plate if zc <= t else k_payload

        b = np.array([zj - zm, zm - zi, zi - zj]) / (2 * area)
        c = np.array([rm - rj, ri - rm, rj - ri]) / (2 * area)
        Ke = 2 * np.pi * k_e * (np.outer(b, b) + np.outer(c, c)) * area * rc
        idx = [i, j, m]
        for a in range(3):
            for bb in range(3):
                K[idx[a], idx[bb]] += Ke[a, bb]

    # --- Heat source map: real EM or placeholder ---
    if em_losses is not None:
        p_e = _interp_em_losses(em_losses, rc_e, zc_e, cfg)
        source_label = "em"
    else:
        integ  = np.sum(shape_e * 2 * np.pi * rc_e * area_e)
        p_e    = shape_e * (P_total / integ)
        source_label = "placeholder"

    # Normalize total power = P_total (keeps spatial shape, conserves energy)
    integ_p = np.sum(p_e * 2 * np.pi * rc_e * area_e)
    if integ_p > 0:
        p_e = p_e * (P_total / integ_p)

    # source load vector:  ∫ p N_i 2pi r dA  ~ p_e * 2pi*rc * (area/3)
    for e, (i, j, m) in enumerate(tris):
        contrib = p_e[e] * 2 * np.pi * rc_e[e] * area_e[e] / 3.0
        F[i] += contrib; F[j] += contrib; F[m] += contrib

    # --- convection boundaries on outer edges (EXCLUDING axis r=0) ---
    # boundary edge = edge lying on r=R, z=0, or z=t
    def on_boundary(n):
        return (abs(r[n] - R) < 1e-12) or (abs(z[n]) < 1e-12) or (abs(z[n] - t) < 1e-12)

    edges = {}
    for (i, j, m) in tris:
        for (a, bb) in [(i, j), (j, m), (m, i)]:
            key = (min(a, bb), max(a, bb))
            edges[key] = edges.get(key, 0) + 1
    boundary_edges = [e for e, cnt in edges.items() if cnt == 1]

    tol_z = t * 0.02   # tolerance for identifying top/bottom edges
    for (a, bb) in boundary_edges:
        ra, za = r[a], z[a]
        rb, zb = r[bb], z[bb]
        if abs(ra) < 1e-12 and abs(rb) < 1e-12:
            continue  # edge on axis -> skip (symmetry)
        # Bottom surface (z ≈ 0) uses h_bot; remaining surfaces use h
        on_bottom = (za < tol_z) and (zb < tol_z)
        h_eff = h_bot if on_bottom else h
        L = np.hypot(rb - ra, zb - za)
        # edge mass matrix with 2*pi*r weighting (see derivation in README)
        Kedge = 2 * np.pi * h_eff * (L / 12.0) * np.array([[3 * ra + rb, ra + rb],
                                                             [ra + rb, ra + 3 * rb]])
        fa = 2 * np.pi * h_eff * Tinf * L * (2 * ra + rb) / 6.0
        fb = 2 * np.pi * h_eff * Tinf * L * (ra + 2 * rb) / 6.0
        K[a, a] += Kedge[0, 0]; K[a, bb] += Kedge[0, 1]
        K[bb, a] += Kedge[1, 0]; K[bb, bb] += Kedge[1, 1]
        F[a] += fa; F[bb] += fb

    T = spla.spsolve(K.tocsr(), F)

    return {
        "coords": coords, "tris": tris, "T": T,
        "p_e": p_e, "area_e": area_e, "rc_e": rc_e,
        "boundary_edges": boundary_edges, "R": R, "t": t,
        "h": h, "h_bot": h_bot, "Tinf": Tinf, "P_total": P_total,
        "source": source_label,
    }


# --------------------------------------------------------------------------
# 4) ENERGY BALANCE CHECK: Q_in (source) ≈ Q_out (convection)
# --------------------------------------------------------------------------
def energy_balance(res):
    Q_in = np.sum(res["p_e"] * 2 * np.pi * res["rc_e"] * res["area_e"])
    coords, T = res["coords"], res["T"]
    r, z = coords[:, 0], coords[:, 1]
    h, h_bot, Tinf = res["h"], res["h_bot"], res["Tinf"]
    tol_z = res["t"] * 0.02
    Q_out = 0.0
    for (a, b) in res["boundary_edges"]:
        ra, rb = r[a], r[b]
        za, zb = z[a], z[b]
        if abs(ra) < 1e-12 and abs(rb) < 1e-12:
            continue
        L = np.hypot(rb - ra, zb - za)
        Ta, Tb = T[a] - Tinf, T[b] - Tinf
        h_eff = h_bot if (za < tol_z and zb < tol_z) else h
        Q_out += 2 * np.pi * h_eff * L / 6.0 * (
            Ta * (2 * ra + rb) + Tb * (ra + 2 * rb))
    return Q_in, Q_out


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from config import load_config
    from em_solver import compute_losses

    cfg = load_config()
    print(f"Solving EM (î={cfg.I}A, f={cfg.freq}Hz)... ", end="", flush=True)
    em_losses = compute_losses(cfg)
    print(f"P_plate={em_losses['P_plate_W']*1e3:.1f}mW, "
          f"P_coil={em_losses['P_coil_W']:.1f}W, P_total={em_losses['P_total_W']:.1f}W")

    res = solve_steady(cfg, em_losses=em_losses)
    T = res["T"]
    Qin, Qout = energy_balance(res)
    Tinf = cfg.bc["T_ambient_degC"]
    print(f"\nHeat source: [{res['source']}]  P_plate = {res['P_total']:.4f} W")
    print(f"Temperature: min={T.min():.2f} °C  max={T.max():.2f} °C  "
          f"(ΔT_max = {T.max()-Tinf:.2f} K)")
    print(f"Energy balance: Q_in={Qin:.4f} W, Q_out={Qout:.4f} W, "
          f"error={abs(Qin-Qout)/Qin*100:.3f}%")

    # --- 2D Temperature Chart (r-z) ---
    import matplotlib.pyplot as plt
    import matplotlib.tri as mtri

    coords = res["coords"]
    r_mm = coords[:, 0] * 1e3
    z_mm = coords[:, 1] * 1e3
    tris  = res["tris"]

    triang = mtri.Triangulation(r_mm, z_mm, tris)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle(f"Aluminum Plate Temperature Field — î = {cfg.I:.0f} A, f = {cfg.freq:.0f} Hz  "
                 f"[source: {res['source']}]\n"
                 f"P_plate = {res['P_total']:.1f} W  |  "
                 f"T_max = {T.max():.1f} °C  |  ΔT_max = {T.max()-Tinf:.1f} K",
                 fontsize=12)

    # --- left subplot: T(r,z) map ---
    ax = axes[0]
    levels = 30
    tcf = ax.tricontourf(triang, T, levels=levels, cmap="hot")
    ax.tricontour(triang, T, levels=levels, colors="k", linewidths=0.3, alpha=0.4)
    cb = fig.colorbar(tcf, ax=ax, label="Temperature (°C)")
    ax.set_xlabel("r (mm)")
    ax.set_ylabel("z (mm)")
    ax.set_title("T(r, z)  — aluminum plate cross-section")
    ax.set_aspect("equal")

    # --- right subplot: T profile along r at z=z_top and z=z_bottom ---
    ax2 = axes[1]
    z_vals = coords[:, 1]
    z_top_model = z_vals.max()
    z_bottom = z_vals.min()
    tol_z = res["t"] * 0.05

    mask_top = np.abs(z_vals - z_top_model)    < tol_z
    mask_bot = np.abs(z_vals - z_bottom) < tol_z
    idx_top  = np.argsort(coords[mask_top, 0])
    idx_bot  = np.argsort(coords[mask_bot, 0])

    r_top = coords[mask_top, 0][idx_top] * 1e3
    T_top = T[mask_top][idx_top]
    r_bot = coords[mask_bot, 0][idx_bot] * 1e3
    T_bot = T[mask_bot][idx_bot]

    ax2.plot(r_top, T_top, "r-o", ms=3, label=f"Top surface (z={z_top_model*1e3:.1f} mm)")
    ax2.plot(r_bot, T_bot, "b-s", ms=3, label=f"Bottom surface (z={z_bottom*1e3:.1f} mm)")
    ax2.axhline(Tinf, ls="--", color="gray", lw=0.8, label=f"T_amb = {Tinf}°C")
    ax2.set_xlabel("r (mm)")
    ax2.set_ylabel("Temperature (°C)")
    ax2.set_title("T(r) Profile at top and bottom surfaces")
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = os.path.join(os.path.dirname(__file__), "thermal_map.png")
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"\nChart saved: {out_path}")
    plt.show()
