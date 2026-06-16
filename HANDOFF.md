# HANDOFF — Digital Twin for Thermal Management

> **Primary source of truth is [CLAUDE.md](CLAUDE.md) + [README.md](README.md).**
> This file is a quick handoff status summary. Last updated: 2026-06-15.

## Goal
A digital twin that predicts the **real-time temperature field** of the aluminium plate
in the TEAM 28 electrodynamic levitation device (TEMF). Validate against the real rig
→ 3D visualization → AR app → QR code.

## Architecture decisions (finalized)
- **No FEMM** (dev machine is macOS). Pure Python: `numpy + scipy + pyyaml + matplotlib`
  (+ `trimesh` for GLB export). Problem is **axisymmetric** → solve in 2D (r, z), revolve to 3D.
- **Real-time:** losses scale as I², spatial pattern stays fixed → run FEM once at I_ref=5A,
  online inference is just a multiply by (I/I_ref)². I²-scaling verified: 4.000000.
- All parameters live in [params.yaml](params.yaml). All source files are **flat in the repo root**.

## Device numbers (in params.yaml)
- Aluminium plate: **R=80mm (Ø16cm)**, thickness 3mm (placeholder — needs to be MEASURED), σ=3.4e7 S/m.
- Current: **î = 5 A** operating point, f = 50 Hz (original benchmark used 20A).
- Turns: **inner=1000, outer=500**.
- **Iron cores present** (μ_r=1000, placeholder geometry — CONFIRM with the real rig).
- payload_model (steel disc): placeholder, **disabled by default**.

## Status (mostly done)
- [x] config.py, params.yaml, thermal_solver.py (energy balance 0.000%)
- [x] em_solver.py — AC eddy currents + lift force, benchmark **z_eq=10.9mm vs 11.3mm (3.5%)**
- [x] rom.py — real-time ROM (I² + transient τ≈3.4 min + σ(T) correction)
- [x] digital_twin.py — interactive twin (current slider, plate selector, scenarios)
- [x] visualize.py — revolve 2D→3D, export plate.glb
- [x] sim_plates.py — compare plates across plate_library
- [x] build_twin_html.py — Phase 5: standalone digital_twin.html (double-click to run)
- [ ] data_io.py — read sensor CSV → calibrate_UA() (**waiting on real thermal sensor data**)

## Validation
1. EM reproduces original benchmark (960/576, 20A, R=65mm, no iron) → lift force balances at z≈11.3mm. ✓
2. Switch to real rig (1000/500, iron, 5A) → loss maps.
3. Losses → thermal solver → T field. **Thermal validation against sensors: pending real data.**

## Run commands — see [README.md](README.md) (note: `python config.py`, NOT `src/`).
