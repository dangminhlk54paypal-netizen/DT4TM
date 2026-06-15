"""sim_plates.py — Compare thermal simulations for different metal plates.

Process for each plate in plate_library (params.yaml):
  1. Swap config to that plate (radius, material)
  2. Run EM solver → P_plate (real eddy losses)
  3. Run thermal solver → T(r,z) with h_bottom (heat transfer through air)
  4. Plot 3D surface (revolve 2D→3D) + comparison charts

Run:
    python sim_plates.py           # full run (EM + thermal, ~30-60s)
    python sim_plates.py --no-em   # skip EM, use fast scaling (~2s)
"""
from __future__ import annotations
import sys, os, copy, math, argparse
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.tri as mtri
from matplotlib.colors import Normalize
from matplotlib import cm
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
from scipy.interpolate import LinearNDInterpolator

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config, Config, Geometry
from thermal_solver import solve_steady, energy_balance


# ---------------------------------------------------------------------------
# 1) BUILD CONFIG FOR EACH PLATE
# ---------------------------------------------------------------------------

def build_plate_cfg(cfg_base: Config, plate_spec: dict) -> Config:
    """Clone cfg_base and override metal plate parameters."""
    cfg = copy.deepcopy(cfg_base)
    mat_name = plate_spec["material"]
    mat = cfg_base.raw["material_props"][mat_name]

    # Override plate_material
    pm = cfg.raw["plate_material"]
    pm["name"]         = mat_name
    pm["radius_mm"]    = float(plate_spec["radius_mm"])
    pm["thickness_mm"] = float(plate_spec.get("thickness_mm", pm["thickness_mm"]))
    for key, val in mat.items():
        pm[key] = float(val)

    # Update Geometry
    cfg.geometry = Geometry(
        plate_radius_m    = pm["radius_mm"]    * 1e-3,
        plate_thickness_m = pm["thickness_mm"] * 1e-3,
        plate_z_bottom_m  = cfg_base.geometry.plate_z_bottom_m,
    )
    return cfg


# ---------------------------------------------------------------------------
# 2) RUN EM + THERMAL FOR ONE PLATE
# ---------------------------------------------------------------------------

def run_plate(cfg: Config, use_em: bool = True) -> dict:
    """Returns result dict: P_plate, res_thermal, T."""
    if use_em:
        from em_solver import compute_losses
        L = compute_losses(cfg)
        P_plate = L["P_plate_W"]
    else:
        # Quick estimation: P ∝ σ·R²  (thin-disc approximation, normalised at ref)
        cfg_ref = load_config()
        sigma_ref = float(cfg_ref.plate["sigma_S_per_m"])
        R_ref     = cfg_ref.geometry.plate_radius_m
        P_ref     = float(cfg_ref.raw["excitation"]["power_ref_W"])
        I_ref     = cfg_ref.I_ref
        sigma     = float(cfg.plate["sigma_S_per_m"])
        R         = cfg.geometry.plate_radius_m
        I         = cfg.I
        P_plate   = P_ref * (sigma / sigma_ref) * (R / R_ref) ** 2 * (I / I_ref) ** 2
        L = {"P_plate_W": P_plate, "P_iron_W": 0.0, "P_coil_W": 0.0,
             "P_total_W": P_plate}

    em_kw = {"em_losses": L} if use_em else {}
    res = solve_steady(cfg, P_total_override=P_plate, **em_kw)
    Qin, Qout = energy_balance(res)
    return {
        "P_plate": P_plate,
        "losses": L,
        "res": res,
        "T": res["T"],
        "T_max": res["T"].max(),
        "T_min": res["T"].min(),
        "dT": res["T"].max() - float(cfg.bc["T_ambient_degC"]),
        "Qin": Qin, "Qout": Qout,
    }


# ---------------------------------------------------------------------------
# 3) 3D REVOLVE PLOT
# ---------------------------------------------------------------------------

def _interp_plate_grid(res: dict, Nr: int = 60, Nz: int = 10):
    """Interpolate T(r,z) onto a uniform grid (Nr×Nz) using scipy LinearNDInterpolator."""
    coords, T = res["coords"], res["T"]
    R, t = res["R"], res["t"]
    interp = LinearNDInterpolator(coords, T, fill_value=T.mean())
    r_1d = np.linspace(0.0, R, Nr)
    z_1d = np.linspace(0.0, t, Nz)
    RR, ZZ = np.meshgrid(r_1d, z_1d, indexing="ij")   # (Nr, Nz)
    T_grid = interp(np.c_[RR.ravel(), ZZ.ravel()]).reshape(Nr, Nz)
    return r_1d, z_1d, T_grid


def plot_3d_disc(ax, res: dict, name: str, norm: Normalize,
                 colormap, N_theta: int = 72, Nr: int = 60):
    """Revolve 2D plate cross-section around z-axis → 3D surface colored by temperature."""
    R, t = res["R"], res["t"]
    r_1d, z_1d, T_grid = _interp_plate_grid(res, Nr=Nr, Nz=10)

    theta = np.linspace(0.0, 2 * math.pi, N_theta)

    def _surface(r_arr, z_val, T_row):
        """Create a circular surface (horizontal plane) at z=z_val."""
        R2d, TH = np.meshgrid(r_arr * 1e3, theta)   # mm
        X = R2d * np.cos(TH)
        Y = R2d * np.sin(TH)
        Z = np.full_like(X, z_val * 1e3)
        T2d = np.tile(T_row, (N_theta, 1))           # (N_theta, Nr)
        fc = colormap(norm(T2d))
        ax.plot_surface(X, Y, Z, facecolors=fc, shade=False, rcount=N_theta, ccount=Nr)

    # Top surface (z = t)
    _surface(r_1d, t, T_grid[:, -1])
    # Bottom surface (z = 0)
    _surface(r_1d, 0.0, T_grid[:, 0])

    # Side edge (r = R) — thin cylinder
    TH2, Z2 = np.meshgrid(theta, z_1d * 1e3, indexing="ij")
    X_side = R * 1e3 * np.cos(TH2)
    Y_side = R * 1e3 * np.sin(TH2)
    T_side = np.tile(T_grid[-1, :], (N_theta, 1))   # (N_theta, Nz)
    fc_side = colormap(norm(T_side))
    ax.plot_surface(X_side, Y_side, Z2, facecolors=fc_side,
                    shade=False, rcount=N_theta, ccount=10)

    R_mm = R * 1e3
    t_mm = t * 1e3
    ax.set_xlim(-R_mm * 1.1, R_mm * 1.1)
    ax.set_ylim(-R_mm * 1.1, R_mm * 1.1)
    ax.set_zlim(-1, t_mm + 1)
    ax.set_xlabel("x (mm)", fontsize=7, labelpad=2)
    ax.set_ylabel("y (mm)", fontsize=7, labelpad=2)
    ax.set_zlabel("z (mm)", fontsize=7, labelpad=2)
    ax.tick_params(labelsize=6)
    ax.set_title(f"{name}\nT_max={res['T'].max():.1f}°C", fontsize=9)


# ---------------------------------------------------------------------------
# 4) MAIN
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-em", action="store_true",
                        help="Skip EM solver, use quick estimation (σ·R² scaling)")
    args = parser.parse_args()
    use_em = not args.no_em

    cfg_base = load_config()
    plate_lib = cfg_base.raw.get("plate_library", [])
    if not plate_lib:
        print("plate_library not found in params.yaml")
        sys.exit(1)

    print(f"î = {cfg_base.I:.0f} A  |  f = {cfg_base.freq:.0f} Hz  "
          f"|  {'Real EM' if use_em else 'Estimated EM (--no-em)'}")
    print(f"{'Plate':<14} {'R (mm)':>7} {'Material':<10} "
          f"{'P_eddy (W)':>11} {'T_min (°C)':>11} {'T_max (°C)':>11} {'ΔT (K)':>8}")
    print("-" * 70)

    all_results = []
    for spec in plate_lib:
        cfg = build_plate_cfg(cfg_base, spec)
        if use_em:
            print(f"  Solving EM: {spec['name']} ...", end="", flush=True)
        r = run_plate(cfg, use_em=use_em)
        r["name"] = spec["name"]
        r["cfg"]  = cfg
        all_results.append(r)
        print(f"\r{spec['name']:<14} {spec['radius_mm']:>7.0f} "
              f"{spec['material']:<10} "
              f"{r['P_plate']:>11.3f} "
              f"{r['T_min']:>11.2f} "
              f"{r['T_max']:>11.2f} "
              f"{r['dT']:>8.2f}")

    # --- Calculate T_global to use shared color norm ---
    T_all_min = min(r["T_min"] for r in all_results)
    T_all_max = max(r["T_max"] for r in all_results)
    norm_global = Normalize(vmin=T_all_min, vmax=T_all_max)
    cmap = plt.colormaps["hot"]

    # -----------------------------------------------------------------------
    # FIGURE 1 — 3D thermal surface (revolve) for each plate
    # -----------------------------------------------------------------------
    n = len(all_results)
    ncols = min(3, n)
    nrows = math.ceil(n / ncols)
    fig3d = plt.figure(figsize=(5.5 * ncols, 5.0 * nrows))
    fig3d.suptitle(
        f"3D Temperature Distribution — î = {cfg_base.I:.0f} A, f = {cfg_base.freq:.0f} Hz\n"
        f"(heat transfer through air: h_top={cfg_base.bc['h_convection_W_per_m2K']} W/m²K, "
        f"h_bottom={cfg_base.bc.get('h_bottom_W_per_m2K', '?')} W/m²K)",
        fontsize=11)

    for i, r in enumerate(all_results):
        ax3d = fig3d.add_subplot(nrows, ncols, i + 1, projection="3d")
        plot_3d_disc(ax3d, r["res"], r["name"], norm_global, cmap)

    # Shared colorbar
    sm = cm.ScalarMappable(cmap=cmap, norm=norm_global)
    sm.set_array([])
    cbar = fig3d.colorbar(sm, ax=fig3d.axes, shrink=0.6, pad=0.04,
                          label="Temperature (°C)")
    cbar.ax.tick_params(labelsize=9)

    fig3d.tight_layout(rect=[0, 0, 1, 0.93])
    path3d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plates_3d.png")
    fig3d.savefig(path3d, dpi=140, bbox_inches="tight")
    print(f"\nSaved: {path3d}")

    # -----------------------------------------------------------------------
    # FIGURE 2 — Comparison: T_max, P_eddy, T(r) profiles
    # -----------------------------------------------------------------------
    names    = [r["name"]    for r in all_results]
    T_maxes  = [r["T_max"]  for r in all_results]
    P_plates = [r["P_plate"] for r in all_results]
    dTs      = [r["dT"]      for r in all_results]

    colors = [cmap(norm_global(t)) for t in T_maxes]
    x = np.arange(n)
    w = 0.38

    fig2, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig2.suptitle(
        f"Metal Plates Comparison — î = {cfg_base.I:.0f} A, f = {cfg_base.freq:.0f} Hz",
        fontsize=12)

    # --- Bar: T_max ---
    ax = axes[0]
    bars = ax.bar(x, T_maxes, color=colors, edgecolor="k", linewidth=0.6)
    ax.axhline(float(cfg_base.bc["T_ambient_degC"]), ls="--", color="gray",
               lw=0.8, label=f"T_amb = {cfg_base.bc['T_ambient_degC']}°C")
    for bar, val in zip(bars, T_maxes):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 0.5,
                f"{val:.1f}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels(names, rotation=20, ha="right", fontsize=9)
    ax.set_ylabel("Max Temperature (°C)"); ax.set_title("T_max by Plate")
    ax.legend(fontsize=8); ax.grid(axis="y", alpha=0.3)

    # --- Bar: P_eddy ---
    ax = axes[1]
    bars2 = ax.bar(x, P_plates, color=colors, edgecolor="k", linewidth=0.6)
    for bar, val in zip(bars2, P_plates):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 0.05,
                f"{val:.2f} W", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels(names, rotation=20, ha="right", fontsize=9)
    ax.set_ylabel("Eddy loss in plate (W)"); ax.set_title("P_eddy by Plate")
    ax.grid(axis="y", alpha=0.3)

    # --- Line: T(r) profile top surface ---
    ax = axes[2]
    prop_cycle = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    for i, r in enumerate(all_results):
        coords_r = r["res"]["coords"]
        T        = r["T"]
        t_val    = r["res"]["t"]
        z_vals   = coords_r[:, 1]
        mask_top = np.abs(z_vals - t_val) < t_val * 0.05
        idx_sort = np.argsort(coords_r[mask_top, 0])
        r_mm = coords_r[mask_top, 0][idx_sort] * 1e3
        T_top = T[mask_top][idx_sort]
        ax.plot(r_mm, T_top, "-o", ms=3, lw=1.5,
                color=prop_cycle[i % len(prop_cycle)], label=r["name"])

    ax.axhline(float(cfg_base.bc["T_ambient_degC"]), ls="--",
               color="gray", lw=0.8, label="T_amb")
    ax.set_xlabel("r (mm)"); ax.set_ylabel("Temperature (°C)")
    ax.set_title("T(r) Profile — Top Surface")
    ax.legend(fontsize=8, ncol=2); ax.grid(alpha=0.3)

    fig2.tight_layout()
    path2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plates_compare.png")
    fig2.savefig(path2, dpi=140, bbox_inches="tight")
    print(f"Saved: {path2}")

    plt.show()


if __name__ == "__main__":
    main()
