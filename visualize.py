"""visualize.py — Phase 4: Revolve axisymmetric FEM T(r,z) → 3D, export GLB for AR.

Outputs:
  thermal_3d.png     — matplotlib 3D surface (always)
  plate.glb          — binary glTF for AR (if trimesh installed)
  plate.obj          — OBJ fallback (if trimesh not installed)

Usage:
  python visualize.py                     # I=5A, full EM solver
  python visualize.py --I 3.0             # at 3A
  python visualize.py --no-em             # skip EM (faster, placeholder source)
  python visualize.py --no-show           # headless (CI / batch)
  python visualize.py --pyvista           # open PyVista interactive window
  python visualize.py --out my_plate.glb  # custom export path
"""
from __future__ import annotations
import argparse
import math
import os
import sys

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from matplotlib.colors import Normalize
from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator

def _cmap(name: str):
    """Compat wrapper: matplotlib 3.7+ dropped cm.get_cmap."""
    try:
        return matplotlib.colormaps[name]
    except AttributeError:
        from matplotlib import cm as _cm
        return _cm.get_cmap(name)

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from config import load_config
from rom import ThermalROM


# ---------------------------------------------------------------------------
# 1.  T sampler from ROM
# ---------------------------------------------------------------------------

def _make_T_sampler(rom: ThermalROM, I: float):
    """Return T(r_arr, z_arr) → ndarray using the ROM interpolator."""
    T_field = rom.T_steady(I)
    coords  = rom.res_ref["coords"]   # (N, 2) = (r, z) in m
    lin = LinearNDInterpolator(coords, T_field, fill_value=np.nan)
    nn  = NearestNDInterpolator(coords, T_field)

    def sample(r_pts, z_pts):
        pts = np.c_[np.asarray(r_pts).ravel(), np.asarray(z_pts).ravel()]
        Tv  = lin(pts)
        bad = np.isnan(Tv)
        if bad.any():
            Tv[bad] = nn(pts[bad])
        return Tv

    return sample


# ---------------------------------------------------------------------------
# 2.  3D surface geometry (revolve 2D → 3D)
# ---------------------------------------------------------------------------

def _grid_faces(M: int, N: int, base: int = 0) -> np.ndarray:
    """Vectorised: triangle faces for a (M×N) structured vertex grid → (2*(M-1)*(N-1), 3)."""
    i = np.arange(M - 1)[:, None]
    j = np.arange(N - 1)[None, :]
    a = base + i * N + j
    b = base + i * N + (j + 1)
    c = base + (i + 1) * N + (j + 1)
    d = base + (i + 1) * N + j
    tri1 = np.stack([a, b, d], axis=2).reshape(-1, 3)
    tri2 = np.stack([b, c, d], axis=2).reshape(-1, 3)
    return np.vstack([tri1, tri2])


def make_plate_3d(rom: ThermalROM, I: float = 5.0,
                  N_phi: int = 72, N_r: int = 40, N_z: int = 8):
    """Build 3D triangulated surface of the plate disc coloured by T(r,z).

    The plate is axisymmetric (r,z) → revolved around z-axis with N_phi segments.
    Surface = top cap + bottom cap + outer cylindrical rim.

    Parameters
    ----------
    rom   : built ThermalROM
    I     : current [A] to evaluate T_steady at
    N_phi : number of circumferential segments (higher = smoother)
    N_r   : radial resolution on each cap face
    N_z   : axial resolution on the rim

    Returns
    -------
    verts   : (V, 3) float32   — XYZ in meters
    faces   : (F, 3) int32     — triangle vertex indices
    T_verts : (V,)   float32   — temperature per vertex [°C]
    """
    cfg = rom.cfg
    R   = cfg.geometry.plate_radius_m
    t   = cfg.geometry.plate_thickness_m

    sample  = _make_T_sampler(rom, I)
    T_amb   = rom.T_amb

    # 1-D grids
    r_arr  = np.linspace(0.0, R, N_r)
    z_arr  = np.linspace(0.0, t, N_z + 1)
    # phi grid: N_phi+1 so last = first → close the loop without explicit stitching
    phi_arr = np.linspace(0.0, 2.0 * math.pi, N_phi + 1)

    # Precompute T on 1-D slices (cheap: N_r + N_r + N_z+1 FEM interpolations)
    T_top_r  = sample(r_arr, np.full_like(r_arr, t))    # (N_r,) — top face at z=t
    T_bot_r  = sample(r_arr, np.zeros_like(r_arr))      # (N_r,) — bottom face at z=0
    T_rim_z  = sample(np.full_like(z_arr, R), z_arr)    # (N_z+1,) — rim at r=R

    verts_parts = []
    faces_parts = []
    T_parts     = []
    base = 0

    def _add(X, Y, Z, T_grid):
        """Append one structured (M×N) surface to the mesh lists."""
        nonlocal base
        M, N = X.shape
        pts  = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1).astype(np.float32)
        Tv   = T_grid.ravel().astype(np.float32)
        fcs  = _grid_faces(M, N, base)
        verts_parts.append(pts)
        T_parts.append(Tv)
        faces_parts.append(fcs)
        base += M * N

    # --- top cap (z = t) ---  shape (N_phi+1, N_r)
    Phi, Rr = np.meshgrid(phi_arr, r_arr, indexing="ij")
    _add(Rr * np.cos(Phi),
         Rr * np.sin(Phi),
         np.full_like(Rr, t),
         np.tile(T_top_r, (N_phi + 1, 1)))

    # --- bottom cap (z = 0) ---
    _add(Rr * np.cos(Phi),
         Rr * np.sin(Phi),
         np.zeros_like(Rr),
         np.tile(T_bot_r, (N_phi + 1, 1)))

    # --- outer rim (r = R) ---  shape (N_phi+1, N_z+1)
    Phi_r, Zr = np.meshgrid(phi_arr, z_arr, indexing="ij")
    _add(R * np.cos(Phi_r),
         R * np.sin(Phi_r),
         Zr,
         np.tile(T_rim_z, (N_phi + 1, 1)))

    verts   = np.vstack(verts_parts)          # (V, 3) float32
    faces   = np.vstack(faces_parts)          # (F, 3) int32
    T_verts = np.concatenate(T_parts)         # (V,)   float32
    return verts, faces, T_verts


# ---------------------------------------------------------------------------
# 3.  matplotlib 3D render  (always available)
# ---------------------------------------------------------------------------

def plot_3d_matplotlib(verts: np.ndarray, faces: np.ndarray, T_v: np.ndarray,
                       cfg, I: float, z_scale: float = 20.0,
                       save_path: str | None = None, show: bool = True):
    """Render revolved plate as a 3D matplotlib figure.

    z_scale exaggerates z-axis (plate is Ø160mm × 3mm — nearly invisible at 1×).
    """
    R_mm   = cfg.geometry.plate_radius_m * 1e3
    t_mm   = cfg.geometry.plate_thickness_m * 1e3
    T_amb  = float(cfg.bc["T_ambient_degC"])
    T_name = cfg.plate.get("name", "plate")

    cmap = _cmap("hot")
    norm = Normalize(vmin=T_v.min(), vmax=T_v.max())

    # Face colour = mean of 3 vertex temperatures
    T_face = T_v[faces].mean(axis=1)       # (F,)
    fc     = cmap(norm(T_face))             # (F, 4) RGBA

    # mm units + z exaggeration for display
    v_mm = verts * 1e3                      # m → mm
    v_mm[:, 2] *= z_scale

    fig = plt.figure(figsize=(13, 7))
    ax  = fig.add_subplot(111, projection="3d")

    polys = v_mm[faces]                     # (F, 3, 3)
    coll  = Poly3DCollection(polys, facecolors=fc, edgecolor="none", alpha=0.92)
    ax.add_collection3d(coll)

    # Colorbar
    sm = plt.cm.ScalarMappable(cmap=_cmap("hot"), norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, shrink=0.55, pad=0.08)
    cbar.set_label("Temperature (°C)", fontsize=10)

    lim = R_mm * 1.1
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_zlim(0, t_mm * z_scale * 1.6)
    ax.set_xlabel("x (mm)", fontsize=9)
    ax.set_ylabel("y (mm)", fontsize=9)
    ax.set_zlabel(f"z (mm  ×{z_scale:.0f})", fontsize=9)
    ax.set_title(
        f"Thermal Digital Twin — 3D Plate Surface\n"
        f"Material: {T_name}  |  I = {I:.1f} A  |  "
        f"T_max = {T_v.max():.1f} °C  |  ΔT_max = {T_v.max()-T_amb:.2f} K",
        fontsize=11,
    )
    ax.view_init(elev=28, azim=40)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"[viz] PNG saved: {save_path}")
    if show:
        plt.show()
    plt.close()


# ---------------------------------------------------------------------------
# 4.  Cross-section 2D plot (r-z heatmap of T field)
# ---------------------------------------------------------------------------

def plot_2d_crosssection(rom: ThermalROM, I: float,
                         save_path: str | None = None, show: bool = True):
    """2D heatmap T(r,z) from the FEM result — useful for publication / debugging."""
    import matplotlib.tri as mtri

    T_field = rom.T_steady(I)
    coords  = rom.res_ref["coords"]
    tris    = rom.res_ref["tris"]
    T_amb   = rom.T_amb

    r_mm = coords[:, 0] * 1e3
    z_mm = coords[:, 1] * 1e3
    triang = mtri.Triangulation(r_mm, z_mm, tris)

    fig, ax = plt.subplots(figsize=(8, 4))
    levels = np.linspace(T_field.min(), T_field.max(), 30)
    tcf = ax.tricontourf(triang, T_field, levels=levels, cmap="hot")
    ax.tricontour(triang, T_field, levels=levels, colors="k",
                  linewidths=0.3, alpha=0.4)
    fig.colorbar(tcf, ax=ax, label="T (°C)")
    ax.set_xlabel("r (mm)")
    ax.set_ylabel("z (mm)")
    ax.set_title(f"T(r, z) — 2D cross-section  I={I:.1f} A  |  "
                 f"ΔT_max={T_field.max()-T_amb:.2f} K")
    ax.set_aspect("auto")
    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"[viz] 2D cross-section saved: {save_path}")
    if show:
        plt.show()
    plt.close()


# ---------------------------------------------------------------------------
# 5.  GLB / OBJ export
# ---------------------------------------------------------------------------

def _T_to_rgba(T_v: np.ndarray, cmap_name: str = "hot") -> np.ndarray:
    """Temperature → uint8 RGBA per vertex."""
    norm = Normalize(vmin=T_v.min(), vmax=T_v.max())
    rgba = (_cmap(cmap_name)(norm(T_v)) * 255).astype(np.uint8)
    return rgba


def export_3d(verts: np.ndarray, faces: np.ndarray, T_v: np.ndarray,
              out_path: str) -> str:
    """Export 3D mesh to GLB (trimesh) or OBJ fallback.

    Returns the path actually written.
    """
    rgba = _T_to_rgba(T_v)

    # --- trimesh: GLB with vertex colours ---
    try:
        import trimesh
        mesh = trimesh.Trimesh(
            vertices=verts.astype(np.float64),
            faces=faces.astype(np.int64),
            process=False,
        )
        mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh, vertex_colors=rgba)
        ext = os.path.splitext(out_path)[1].lower()
        if ext not in (".glb", ".gltf"):
            out_path = os.path.splitext(out_path)[0] + ".glb"
        mesh.export(out_path)
        size_kb = os.path.getsize(out_path) // 1024
        print(f"[viz] GLB exported: {out_path}  ({size_kb} KB)")
        return out_path
    except ImportError:
        pass

    # --- OBJ fallback (always works) ---
    obj_path = os.path.splitext(out_path)[0] + ".obj"
    with open(obj_path, "w") as f:
        f.write("# Thermal Digital Twin — plate surface\n")
        f.write("# Vertex format: v x y z  (mm)\n")
        v_mm = verts * 1e3   # m → mm for OBJ (human-readable scale)
        for v in v_mm:
            f.write(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}\n")
        for tri in faces + 1:   # OBJ is 1-indexed
            f.write(f"f {tri[0]} {tri[1]} {tri[2]}\n")
    print(f"[viz] OBJ fallback: {obj_path}")
    print("      Install trimesh for GLB:  pip install trimesh")
    return obj_path


# ---------------------------------------------------------------------------
# 6.  PyVista interactive  (optional)
# ---------------------------------------------------------------------------

def plot_pyvista(verts: np.ndarray, faces: np.ndarray, T_v: np.ndarray,
                 show: bool = True, save_path: str | None = None) -> None:
    """Interactive PyVista window — only called when --pyvista flag is set."""
    try:
        import pyvista as pv
    except ImportError:
        print("[viz] PyVista not installed — skipping interactive view.")
        print("      pip install pyvista")
        return

    n   = len(faces)
    pv_faces = np.hstack([np.full((n, 1), 3, dtype=np.int_), faces])
    mesh = pv.PolyData(verts.astype(np.float64), pv_faces.ravel())
    mesh["Temperature (°C)"] = T_v

    pl = pv.Plotter(window_size=[1400, 800])
    pl.add_mesh(mesh, scalars="Temperature (°C)", cmap=_cmap("hot"),
                show_scalar_bar=True,
                scalar_bar_args={"title": "T (°C)", "n_labels": 5})
    pl.show_axes()
    pl.add_title("Thermal Digital Twin — Plate 3D", font_size=14)
    pl.view_isometric()
    if save_path:
        pl.screenshot(save_path)
        print(f"[viz] PyVista screenshot: {save_path}")
    if show:
        pl.show()


# ---------------------------------------------------------------------------
# 7.  main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Phase 4 — 3D thermal visualisation + GLB export")
    ap.add_argument("--I",       type=float, default=5.0,
                    help="Operating current [A] (default 5)")
    ap.add_argument("--phi",     type=int,   default=72,
                    help="Circumferential segments for revolution (default 72)")
    ap.add_argument("--nr",      type=int,   default=40,
                    help="Radial divisions on cap faces (default 40)")
    ap.add_argument("--nz",      type=int,   default=8,
                    help="Axial divisions on rim (default 8)")
    ap.add_argument("--z-scale", type=float, default=20.0,
                    help="Z exaggeration factor in matplotlib plot (default 20)")
    ap.add_argument("--no-em",   action="store_true",
                    help="Skip EM solver — use placeholder heat source (faster)")
    ap.add_argument("--no-show", action="store_true",
                    help="Headless mode — save files but do not open windows")
    ap.add_argument("--pyvista", action="store_true",
                    help="Open PyVista interactive window (requires pyvista)")
    ap.add_argument("--out",     default=None,
                    help="Output GLB/OBJ path (default: plate.glb in project root)")
    args = ap.parse_args()

    show = not args.no_show
    cfg  = load_config()

    # --- EM solver ---
    em = None
    if not args.no_em:
        from em_solver import compute_losses
        print(f"[EM] Solving at I={cfg.I} A, f={cfg.freq} Hz... ", end="", flush=True)
        em = compute_losses(cfg)
        print(f"P_plate={em['P_plate_W']*1e3:.0f} mW  "
              f"P_iron={em['P_iron_W']*1e3:.0f} mW  "
              f"P_coil={em['P_coil_W']:.1f} W")

    # --- ROM (one FEM solve) ---
    rom = ThermalROM().build(cfg, em_losses=em, verbose=True)
    print(f"  Visualising at I={args.I} A  →  "
          f"T_max={rom.T_steady(args.I).max():.2f} °C")

    # --- Build 3D surface ---
    print(f"[viz] Revolving mesh (N_phi={args.phi}, N_r={args.nr}, N_z={args.nz})...",
          end=" ", flush=True)
    verts, faces, T_v = make_plate_3d(
        rom, I=args.I, N_phi=args.phi, N_r=args.nr, N_z=args.nz)
    print(f"done  →  {len(verts):,} vertices, {len(faces):,} faces  |  "
          f"T: {T_v.min():.1f} – {T_v.max():.1f} °C")

    out_dir = os.path.join(ROOT, "outputs")
    os.makedirs(out_dir, exist_ok=True)

    # --- matplotlib 3D ---
    png_3d = os.path.join(out_dir, "thermal_3d.png")
    plot_3d_matplotlib(verts, faces, T_v, cfg, I=args.I,
                       z_scale=args.z_scale,
                       save_path=png_3d, show=show)

    # --- matplotlib 2D cross-section ---
    png_2d = os.path.join(out_dir, "thermal_2d_section.png")
    plot_2d_crosssection(rom, I=args.I, save_path=png_2d, show=show)

    # --- PyVista (optional) ---
    if args.pyvista:
        plot_pyvista(verts, faces, T_v, show=show,
                     save_path=os.path.join(out_dir, "thermal_pyvista.png") if not show else None)

    # --- Export GLB / OBJ ---
    out = args.out or os.path.join(out_dir, "plate.glb")
    export_3d(verts, faces, T_v, out)


if __name__ == "__main__":
    main()
