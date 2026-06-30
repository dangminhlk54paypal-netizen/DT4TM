# HANDOFF — Digital Twin for Thermal Management

> **Primary source of truth is [CLAUDE.md](CLAUDE.md) + [README.md](README.md).**
> This file is a quick handoff status summary. Last updated: 2026-06-22.

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
- Current: **î = 5 A** MEASURED (rig: 220V → 5A), f = 50 Hz. voltage_V=220 in params.
- Turns: **inner=1000, outer=500**.
- **Iron cores present** (μ_r=1000, placeholder geometry — CONFIRM with the real rig).
- payload_model (steel disc): placeholder, **disabled by default**.
- **T_ambient = 20°C** (professor: keep it simple for Phase 1).
- **EM domain: 1×1m box** (±500mm; professor: validate via Dirichlet vs Neumann BC).

## Professor Feedback (Juni 2026)
- Domain: 1×1m box OK, validate with BC comparison
- T_amb: constant 20°C, no lab sensor needed yet
- Excitation: 220V/5A measured, no real-time Messgerät yet
- Sensors: Arduino + thermocouple + IR thermometer, team builds, professor buys parts
- Scope: disc-only simulation as starting point is also OK

## Status (mostly done)
- [x] config.py, params.yaml, thermal_solver.py (energy balance 0.000%)
- [x] em_solver.py — AC eddy currents + lift force computed; original-benchmark check
      **IMPROVED but not yet matching** (z_eq≈7.1mm vs 11.3mm expected, was 3.4mm before
      2026-06-23 — the "10.9mm/PASS" once logged here was never actually reproduced,
      bisected through git history. Fixed root cause: benchmark was reusing the rig's
      coil radii instead of the original 960/576-turn problem's own geometry from
      TeamProblem28.pdf — now uses the real radii, halving the error. Remaining 37% gap
      unexplained — see CLAUDE.md)
- [x] rom.py — real-time ROM (I² + transient τ≈3.4 min + σ(T) correction)
- [x] digital_twin.py — interactive twin (current slider, plate selector, scenarios)
- [x] visualize.py — revolve 2D→3D, export plate.glb
- [x] sim_plates.py — compare plates across plate_library
- [x] build_twin_html.py — Phase 5: standalone digital_twin.html (double-click to run)
- [x] data_io.py + arduino/thermal_sensor.ino — sensor bridge implemented (`SensorReader`,
      `calibrate_from_file()`, `live_compare()`); mock-data tested end-to-end via
      `mock_sensor_data.csv` / `--port mock`. **Waiting on the real Arduino rig** to log
      actual data.

## Validation
1. EM reproduces original benchmark (960/576, 20A, R=65mm, no iron) → lift force balances at z≈11.3mm. **NOT YET** (z_eq≈7.1mm after fixing the coil geometry, see CLAUDE.md) — 37% error remains, unexplained.
2. Switch to real rig (1000/500, iron, 5A) → loss maps.
3. Losses → thermal solver → T field. **Thermal validation: Arduino + thermocouple + IR thermometer (see SENSOR_PLAN.md).**
4. Domain validation: Dirichlet vs Neumann BC comparison (Session 2).

## Next Sessions
- **Session 2**: Domain & BC validation (Dirichlet vs Neumann comparison)
- **Session 3**: Re-run pipeline with T_amb=20°C, regenerate HTML twin
- **Session 5**: Build the real Arduino rig, log a real run, calibrate `data_io.py`
  against actual sensor data instead of `mock_sensor_data.csv`

## Run commands — see [README.md](README.md) (note: `python config.py`, NOT `src/`).
