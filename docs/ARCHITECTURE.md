# DT4TM — File Architecture & Data Flow

> Last updated: 2026-07-28 (repo tidy-up: docs/archive/ + extensions/, WP-TIDY).
> Single-source-of-truth for file relationships.
> Source scripts + input data live **flat in repo root** (no src/ subfolder);
> docs live in `docs/`, generated files in `outputs/`. The one exception is
> `extensions/` — optional add-ons with heavy deps that nothing in the root
> imports (see `extensions/README.md` and CLAUDE.md's layout rule).

---

## File Tree

```
DT4TM/
├── params.yaml                  ← ALL physics knobs (geometry, materials, BCs, mesh)
├── config.py                    ← Loads params.yaml, converts mm→m, derives scalars
│
├── em_solver.py                 ← AC eddy-current FEM (axisymmetric, complex A_φ)
├── thermal_solver.py            ← Steady-state heat FEM (axisymmetric, P1 triangles)
├── rom.py                       ← Real-time ROM: I²-scaling + first-order ODE + σ(T)
├── twin_core.py                 ← SSOT time integrator (dual-β disc + lumped coil/iron/
│                                  air RC + levitation spring-mass-damper). numpy+stdlib
│                                  ONLY — ports what used to live only inside
│                                  build_twin_html_fem.py's baked JS. `TwinState`.
├── twin_model.py                ← heavy bridge: resolve_active_plate/PlateCache/
│                                  i_max_for/coeffs_from_live/build_plate_variant —
│                                  turns a live (cfg, em, rom) into twin_core coefficients.
├── xval_twin.py                 ← pins twin_core.py against the baked JS engine in
│                                  outputs/digital_twin_fem.html (Playwright + traceRom()).
├── digital_twin.py              ← Interactive live twin (matplotlib, sliders) — uses
│                                  twin_core.TwinState + twin_model, no physics of its own.
├── visualize.py                 ← Revolve 2D→3D, export outputs/plate.glb + thermal_3d.png
├── sim_plates.py                ← Batch compare plate materials from plate_library
├── build_twin_html_fem.py       ← Bake FEM+STL+ROM → outputs/digital_twin_fem.html
│                                  (build_twin_html.py — older lumped-only bake script —
│                                   deleted 2026-07-02, commit ec64ec1, superseded by this file)
├── data_io.py                   ← SensorReader (serial/mock) → calibrate_from_file() → rom.calibrate_UA()
│                                  live_compare() uses twin_core.TwinState too.
│
├── 3D_model.stl                 ← CAD geometry (meters, axisymmetric, ~467 KB)
├── levitation_height_team28.csv ← Benchmark Table I: t_ms, z_mm (levitation height)
├── mock_sensor_data.csv         ← Synthetic sensor log for testing data_io.py without hardware
│
├── CLAUDE.md                    ← Claude Code project instructions (auto-loaded)
├── README.md                    ← Setup, run commands, FEM math reference
│
├── extensions/                  ← OPTIONAL add-ons. Heavy deps the core avoids; NOTHING
│   │                              in the root imports them, so the pipeline runs with
│   │                              this folder deleted. Contract: extensions/README.md.
│   ├── README.md                ← Why the folder exists + how to write a new extension
│   └── digital_twin_pyvista.py  ← Interactive live twin (PyVista/VTK 3D) — same
│                                  twin_core.TwinState, reuses build_twin_html_fem.py's
│                                  procedural geometry builders. Optional dependency
│                                  (~400MB VTK); --self-check runs without it.
│
├── arduino/thermal_sensor/
│   └── thermal_sensor.ino       ← MAX31855×2 firmware, 1Hz CSV (see docs/SENSOR_PLAN.md)
│
├── docs/                        ← LIVING documentation (current state)
│   ├── physics.md               ← Full physics derivations + formulas
│   ├── ARCHITECTURE.md          ← This file
│   ├── CHANGELOG.md             ← Session-by-session history (every fix/calibration round)
│   ├── HANDOFF.md               ← Quick status handoff for team members
│   ├── SENSOR_PLAN.md           ← Hardware shopping list + sensor architecture
│   ├── QUICK_START_FOR_AGENTS.md ← Onboarding brief for a fresh agent/teammate
│   ├── math_formulation.md      ← Standalone maths write-up (for report/thesis)
│   ├── REPORT_WHY_CUSTOM_CODE{,_DE}.md ← "why not FEMM/COMSOL" report (EN + DE)
│   └── archive/                 ← COMPLETED one-off plans + bug registers, date-prefixed.
│                                   Historical record only — never the source of truth for
│                                   current behaviour (that is params.yaml + CLAUDE.md).
│                                   See docs/archive/README.md for the index.
│
└── outputs/                     ← [GENERATED — gitignored except digital_twin_fem.html]
    ├── digital_twin_fem.html    ← Full AR twin — double-click to run (kept in git)
    ├── plate.glb / plate.obj    ← 3D exports for AR
    └── *.png                    ← render outputs (thermal_3d, rom_demo, plates_*, …)
```

---

## Physics Chain (Data Flow)

```
params.yaml
    │
    ▼
config.py ──────────────────────────────────────────────┐
    │ cfg object (all parameters, SI units)              │
    ▼                                                    │
em_solver.py                                            │
    │  solve_em_saturating(cfg)                          │
    │    └─ Picard iteration: A_φ → B_e → μ_r_eff(B)   │
    │  compute_losses(cfg) → {                           │
    │      P_plate_W,  q_e[r,z]   (eddy map)            │
    │      P_coil_W               (ohmic)                │
    │      P_iron_W               (eddy)                 │
    │      check_saturation → B_max_iron                 │
    │  }                                                 │
    │                                                    │
    ▼                                                    │
thermal_solver.py                                        │
    │  solve_thermal(cfg, em_losses) → {                 │
    │      T[r,z], coords, tris                          │
    │      Tinf_bot = T_amb + k_coil × P_coil_W         │
    │      energy_balance: Q_in = Q_out ✓               │
    │  }                                                 │
    │                                                    │
    ▼                                                    │
rom.py                                                   │
    │  ThermalROM.build(cfg, em_losses)                  │
    │    ├─ FEM solve once at I_ref                      │
    │    ├─ τ = ρ c_p V / (h A)                         │
    │    └─ simulate(I_arr, t_arr) → β(t) ODE           │
    │                                                    │
    ▼                                                    │
twin_model.py :: coeffs_from_live(cfg, em, rom)          │
    │  bridges (cfg, em, rom) into twin_core's frozen     │
    │  RomCoeffs/LumpedCoeffs/LevCoeffs (calls             │
    │  build_twin_html_fem.py's OWN lumped_physics()/       │
    │  lev_params() — not reimplemented here)               │
    ▼                                                    │
twin_core.py :: TwinState(rom, lumped, lev, T_amb)       │
    │  SSOT integrator (numpy+stdlib only): dual-β disc,  │
    │  lumped coil/iron/air RC, levitation spring-damper. │
    │  .step(I, dt) / .T_field — pinned bit-for-bit        │
    │  against the JS engine below by xval_twin.py.        │
    │                                                    │
    ├──────────────────────┐                             │
    ▼                      ▼                             │
digital_twin.py    extensions/digital_twin_pyvista.py     │
    │  matplotlib       │  PyVista/VTK 3D (optional dep)  │
    │  run_live()       │  TwinPyVista.run_live()          │
    │                                                    │
    ▼                                                    │
build_twin_html_fem.py ◄────────────────────────────────┘
    │  Reads: em_losses + rom_params (100% procedural
    │  geometry from params.yaml, no STL — see below)
    │  Bakes all into one self-contained HTML, including
    │  its OWN copy of the integrator as JS (romStep/
    │  levStep) — xval_twin.py is what keeps that copy and
    │  twin_core.py from silently drifting apart.
    └──► digital_twin_fem.html  (~1 MB, no server needed)
```

---

## Module Dependency Graph

```
                   params.yaml
                       │
                   config.py
                  /    │    \
                 /     │     \
         em_solver  thermal  rom.py
              │      solver     │
              │        │        │
              └────────┴────────┘
                       │
              build_twin_html_fem.py ── lumped_physics()/lev_params()
                       │                (coefficients — SSOT stays here)
                       ▼
                 twin_model.py :: coeffs_from_live()
                       │
                       ▼
                 twin_core.py :: TwinState
                  (integrator — SSOT, numpy+stdlib only)
                 /                        \
                /                          \
       digital_twin.py     extensions/digital_twin_pyvista.py
        (matplotlib)                (PyVista/VTK, optional)

    build_twin_html_fem.py also bakes digital_twin_fem.html
    (three.js), which carries its OWN JS copy of the same
    integrator — pinned against twin_core.py by xval_twin.py,
    NOT part of the Python import graph above.
```

---

## Key Parameter Connections

| params.yaml key | Used by | Effect |
|---|---|---|
| `excitation.current_A` | em_solver, rom | Source current î (A) |
| `excitation.current_ref_A` | rom | I_ref for I²-scaling ROM |
| `plate_material.radius_mm` | em_solver, thermal, rom | Plate size (80mm = Ø16cm) |
| `plate_material.sigma_S_per_m` | em_solver | Eddy loss magnitude |
| `plate_material.sigma_tempco_per_K` | rom | σ(T) runtime correction |
| `coils.inner.turns` / `outer.turns` | em_solver | Source J_s density |
| `iron_core.mu_r` | em_solver | Linear μ_r (Picard corrects it) |
| `iron_core.B_sat_T` | em_solver | Lorentzian saturation threshold |
| `thermal_bc.k_coil_coupling_K_per_W` | thermal_solver | Coil→disc air coupling (0.15 K/W) |
| `thermal_bc.h_bottom_W_per_m2K` | thermal_solver | Enhanced bottom convection (25 W/m²K) |
| `mesh.nr` / `mesh.nz` | thermal_solver | Plate mesh resolution |
| `em_domain.*` | em_solver | EM mesh extents and resolution |

---

## Generated / Derived Files

All generated files land in `outputs/` (gitignored, except `digital_twin_fem.html`).

<!-- file sizes are approximate and drift over time; treat as order-of-magnitude -->
| File | How to regenerate | Size |
|---|---|---|
| `outputs/digital_twin_fem.html` | `python build_twin_html_fem.py 3D_model.stl` | 568 KB |
| `outputs/plate.glb` | `python visualize.py` | ~247 KB |
| `outputs/thermal_3d.png` | `python visualize.py --no-show` | — |
| `outputs/thermal_2d_section.png` | `python visualize.py --no-show` | — |
| `outputs/twin_pv.png` | `python extensions/digital_twin_pyvista.py --screenshot outputs/twin_pv.png --no-show` (optional pyvista/vtk dep) | — |

---

## Validation Data

```
levitation_height_team28.csv
    │  Columns: t_ms, z_mm
    │  Source: Table I from TeamProblem28.pdf
    │  Settles at z ≈ 11.3 mm
    │
    └──► em_solver.py: run_benchmark_validation()
             Uses benchmark_team28_original block (960/576 turns, 20A, R=65mm, no iron,
             coil radii 15-28/41-46.5mm from TeamProblem28.pdf Fig.2)
             Result: z_eq ≈ 14.5 mm vs 11.3 mm CSV — 28% OVERSHOOT, still PAUSED
             (history: z_eq≈3.4mm → 7.1mm after the 2026-06-23 coil-radii fix, then
             → 14.5mm on 2026-07-11 when a missed WP-PEAK call site was fixed — this
             function called compute_lift_force(cfg) without I_amplitude=cfg.I_peak,
             so F_z was ~2x too small at every z. The error flipped sign: 40% UNDER
             → 28% OVER. The "10.9mm ✓" once logged here was never reproducible at
             all, bisected through git history. Residual 28% unexplained — mesh/
             domain/sign all ruled out. See CLAUDE.md.)
```

---

## Physics Modules — Internal Structure

### em_solver.py
```
solve_em(cfg, nu_e_override=None)       ← core FEM (complex sparse system)
    ↓
_compute_B_per_element(res)             ← B_r, B_z from ∇A_φ; RMS magnitude
    ↓
check_saturation(res, cfg)              ← returns (B_max_iron, B_e[])
    ↑ used by
solve_em_saturating(cfg)                ← Picard loop: update ν(B) until convergence
    ↑ used by
compute_losses(cfg)                     ← top-level: returns P_plate/P_coil/P_iron/q_e
compute_lift_force(res, cfg)            ← Maxwell stress tensor → F_z [N]
run_benchmark_validation(cfg)           ← find z_eq where F_z = mg
```

### thermal_solver.py
```
build_mesh(cfg)                         ← structured r-z grid → triangles
assemble_system(cfg, q_e, ...)          ← K matrix + f vector (axisymmetric FEM)
solve_thermal(cfg, em_losses)           ← full pipeline, returns result dict
energy_balance(res)                     ← Q_in vs Q_out:
                                           bottom edges use Tinf_bot,
                                           top/side edges use Tinf (25°C)
```

### rom.py
```
ThermalROM
  .build(cfg, em_losses)                ← FEM solve at I_ref → τ, ΔT_max
  .T_steady(I)                          ← scalar: ΔT_ss × (I/I_ref)² × σ(T) factor
  .simulate(I_arr, t_arr)               ← Euler ODE: τ dβ/dt = (I/I_ref)² − β
  .calibrate_UA(I_meas, dT_meas)        ← fit UA/τ from one steady-state sensor reading
                                           (called by data_io.py::calibrate_from_file())
```

---

## What's Next (Pending)

```
[ ] Domain validation (Session 2)
      Run Dirichlet vs Neumann BC comparison at 1×1m box
      Confirm boundary is far enough (professor's suggestion)

[ ] Re-run pipeline with T_amb=20°C (Session 3)
      em_solver → thermal_solver → rom → regenerate digital_twin_fem.html

[x] data_io.py + arduino/thermal_sensor/thermal_sensor.ino
      SensorReader (serial or mock) → calibrate_from_file() → rom.calibrate_UA()
      Tested end-to-end against mock_sensor_data.csv; no real hardware yet.

[ ] Sensor hardware (Session 5 — see SENSOR_PLAN.md)
      Build the real Arduino rig (MAX31855×2 + thermocouples + IR thermometer)
      Shopping list → professor purchases (Reichelt/Conrad)
      Log a real run → re-run calibrate_from_file() on actual data
      Calibrate k_coil_coupling_K_per_W from actual core+disc readings (needs
      multiple I levels — calibrate_UA() alone only fits UA/τ from one reading)

[ ] Confirm real device geometry
      Iron core shape (currently: central cylinder placeholder)
      Plate thickness (currently: 3mm — measure the actual Ø16cm disc)

[ ] QR code (optional)
      Point to hosted digital_twin_fem.html / plate.glb
```

---

## Sensor Data Pipeline (implemented 2026-06-22, real hardware pending)

```
Arduino + 2× MAX31855 (Thermocouple Typ K)          [arduino/thermal_sensor/thermal_sensor.ino]
    │  reads T at copper core + disc bottom, 1 Hz
    │  Serial: "millis,T_core_degC,T_disc_degC\n"  (fault → "nan" + "# FAULT ..." line)
    │
    ▼
data_io.py :: SensorReader(port)                    [port=None/"mock" → no hardware needed]
    │  read_stream() → (t_s, T_core, T_disc) generator
    │  save_csv() → log to CSV  |  load_csv() → numpy arrays
    │
    ▼
data_io.py :: calibrate_from_file(csv_path, target="disc"|"core")
    │  trailing-window mean → (I_meas=cfg.I, dT_meas) → rom.calibrate_UA(I_meas, dT_meas)
    │  fits UA (W/K) and τ = C/UA — does NOT fit k_coil_coupling_K_per_W
    │  (that needs separate core/disc readings across several I, still manual)
    │
    ▼
digital_twin.py / build_twin_html_fem.py
    │  use the calibrated ROM for live predictions
    └─► digital_twin_fem.html (regenerate after calibrating)
```
Tested against `mock_sensor_data.csv` (`python data_io.py --mode calibrate`); the real
Arduino rig still needs to be built (see SENSOR_PLAN.md, Session 5 above).
