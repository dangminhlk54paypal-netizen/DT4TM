# DT4TM — File Architecture & Data Flow

> Last updated: 2026-06-16. Single-source-of-truth for file relationships.
> All files live **flat in repo root** (no src/ subfolder).

---

## File Tree

```
DT4TM/
├── params.yaml                  ← ALL physics knobs (geometry, materials, BCs, mesh)
│
├── config.py                    ← Loads params.yaml, converts mm→m, derives scalars
│
├── em_solver.py                 ← AC eddy-current FEM (axisymmetric, complex A_φ)
├── thermal_solver.py            ← Steady-state heat FEM (axisymmetric, P1 triangles)
├── rom.py                       ← Real-time ROM: I²-scaling + first-order ODE + σ(T)
├── digital_twin.py              ← Interactive live twin (matplotlib, sliders)
│
├── visualize.py                 ← Revolve 2D→3D, export plate.glb / thermal_3d.png
├── sim_plates.py                ← Batch compare plate materials from plate_library
│
├── build_twin_html_fem.py       ← Bake FEM+STL+ROM → standalone digital_twin_fem.html
├── build_twin_html.py           ← Older bake script (lumped ROM only, no FEM disc)
│
├── digital_twin_fem.html        ← [GENERATED] Full AR twin — double-click to run
├── digital_twin.html            ← [GENERATED] Older version (lumped only)
│
├── 3D_model.stl                 ← CAD geometry (meters, axisymmetric, ~467 KB)
├── levitation_height_team28.csv ← Benchmark Table I: t_ms, z_mm (levitation height)
│
├── params.yaml                  (already listed above)
├── physics.md                   ← Full physics derivations + formulas
├── CLAUDE.md                    ← Claude Code project instructions (auto-loaded)
├── README.md                    ← Setup, run commands, FEM math reference
├── HANDOFF.md                   ← Quick status handoff for team members
└── ARCHITECTURE.md              ← This file
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
digital_twin.py  ──────────────────────────────────────►│
    │  DigitalTwin(rom)                                  │
    │  run_live(): matplotlib animation                  │
    │  Signals: step / ramp / sine / pulse / manual      │
    │                                                    │
    ▼                                                    │
build_twin_html_fem.py ◄────────────────────────────────┘
    │  Reads: 3D_model.stl + em_losses + rom_params
    │  Bakes all into one self-contained HTML:
    └──► digital_twin_fem.html  (568 KB, no server needed)
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
              ┌────────┴──────────┐
              │                   │
        digital_twin.py   build_twin_html_fem.py
              │                   │
         (matplotlib)    digital_twin_fem.html
                                  │
                              3D_model.stl
                          (STL geometry baked in)
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

| File | How to regenerate | Size |
|---|---|---|
| `digital_twin_fem.html` | `python build_twin_html_fem.py 3D_model.stl` | 568 KB |
| `digital_twin.html` | `python build_twin_html.py 3D_model.stl` | 464 KB |
| `plate.glb` | `python visualize.py` | ~247 KB |
| `thermal_3d.png` | `python visualize.py --no-show` | — |
| `thermal_2d_section.png` | `python visualize.py --no-show` | — |

---

## Validation Data

```
levitation_height_team28.csv
    │  Columns: t_ms, z_mm
    │  Source: Table I from TeamProblem28.pdf
    │  Settles at z ≈ 11.3 mm
    │
    └──► em_solver.py: run_benchmark_validation()
             Uses benchmark_team28_original block (960/576 turns, 20A, R=65mm, no iron)
             Result: z_eq = 10.9 mm vs 11.3 mm CSV → 3.5% error ✓
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
  .calibrate_UA(T_meas, t_meas, I_meas) ← fit τ to real sensor data (pending)
```

---

## What's Next (Pending)

```
[ ] data_io.py
      Read thermocouple CSV → calibrate_UA() in rom.py
      Calibrate k_coil_coupling_K_per_W from actual bottom temperature measurement

[ ] Confirm real device geometry
      Iron core shape (currently: central cylinder placeholder)
      Plate thickness (currently: 3mm — measure the actual Ø16cm disc)

[ ] QR code (optional)
      Point to hosted digital_twin_fem.html / plate.glb
```
