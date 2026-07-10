# Thermal Digital Twin — (Electrodynamic Levitation Device)

A digital twin that predicts the **temperature field in real time** for the
aluminium plate of the TEAM 28 electrodynamic levitation device (at TEMF).
It is validated against the real physical setup, then visualized in 3D, and
finally delivered through an **AR app + QR code**. Operating current ≤ 5 A.

## Why real-time is possible
At a fixed frequency with linear materials, **Joule losses scale as I²** while
the *spatial loss pattern stays fixed*. So we run the high-fidelity FEM solve
**once** at a reference current `I_ref`, and at runtime any current `I` is just a
multiply by `(I/I_ref)²` → prediction in milliseconds. Verified: ΔT(5A)/ΔT(1A) = 25 = 5².

## Architecture decisions
- **No FEMM** (Windows-native; the dev machine is macOS). Pure **Python** instead.
- The problem is **axisymmetric** → we solve in 2D (r, z) and revolve to 3D for display.
- Core stack: `numpy + scipy + pyyaml + matplotlib` (Phase 1–2);
  `pyvista + meshio + qrcode` added later (Phase 4–5).

## Setup (macOS)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run
Source scripts stay flat in the repo root (no `src/` subfolder); docs are in
`docs/`, generated files land in `outputs/`.
```bash
python config.py            # print normalized parameters
python em_solver.py         # AC eddy losses + I² check + benchmark (z_eq≈7.1mm vs 11.3 expected — improved, not yet matching, see CLAUDE.md)
python thermal_solver.py    # solve heat + energy balance (expect "error=0.000%")
python rom.py               # real-time ROM demo (I² scaling + transient)
python digital_twin.py      # interactive live twin (slider I, plate selector)
python visualize.py --no-show   # revolve 2D→3D, export outputs/plate.glb
python sim_plates.py            # compare plates from plate_library
# build_twin_html.py deleted 2026-07-02 (commit ec64ec1) — superseded by build_twin_html_fem.py below
python build_twin_html_fem.py            # FEM-accurate bake → outputs/digital_twin_fem.html (R=80mm, default disc)
python build_twin_html_fem.py --plate-radius 101   # same, but Ø202mm disc → outputs/digital_twin_fem_R101.html
python data_io.py --mode calibrate --csv mock_sensor_data.csv   # calibrate UA from a sensor log (no hardware needed)
python gen_qr.py <hosted-url>            # QR code -> outputs/qr_digital_twin.png (URL TBD, see CLAUDE.md)
```

## Layout
Source scripts, `params.yaml` and input data stay flat in the repo root (scripts
self-locate via `__file__`). Docs live in `docs/`, generated files in `outputs/`.
```
params.yaml         # ALL knobs (units, current, materials, BCs, mesh)
config.py           # loads params, converts mm->m, derives P ~ I^2
thermal_solver.py   # axisymmetric heat FEM (pure numpy/scipy)
em_solver.py        # AC eddy currents -> real loss map + lift force + benchmark
rom.py              # real-time ROM: I^2 + first-order transient + σ(T)
digital_twin.py     # interactive live loop I(t) -> T(r,z,t)
visualize.py        # revolve 2D->3D, export GLB/OBJ (+ optional PyVista)
sim_plates.py       # compare thermal response across plate_library
# (build_twin_html.py deleted 2026-07-02, commit ec64ec1 — superseded by build_twin_html_fem.py below)
build_twin_html_fem.py  # FEM-based bake  -> outputs/digital_twin_fem.html
data_io.py          # Arduino sensor bridge (serial or mock) -> rom.calibrate_UA()
gen_qr.py           # QR code for the hosted digital_twin_fem.html (URL via CLI arg)
arduino/thermal_sensor/thermal_sensor.ino  # MAX31855x2 firmware, 1Hz CSV over serial
3D_model.stl                    # colleague's CAD (source, meters, axisymmetric)
levitation_height_team28.csv    # Table I from the PDF (levitation height, validation)
mock_sensor_data.csv            # synthetic sensor log for testing data_io.py
docs/               # physics.md, ARCHITECTURE.md, HANDOFF.md, SENSOR_PLAN.md, 3D_MODEL_UPDATE_PLAN.md
outputs/            # generated PNG/GLB/OBJ/HTML (gitignored except digital_twin_fem.html)
```

## Roadmap
- [x] **Phase 1a** — Axisymmetric heat solver, verified by energy balance.
- [x] **Phase 1b** — EM solver (AC eddy currents) — real losses computed; original-benchmark
      lift-force check improved (z_eq≈7.1mm vs 11.3mm expected, was 3.4mm) after fixing
      the benchmark's coil geometry — not yet fully matching, see CLAUDE.md.
- [x] **Phase 2** — Real-time ROM (I² + first-order transient + σ(T) correction).
- [x] **Phase 3** — Twin loop (interactive). Measured-data ingestion: pending real sensors.
- [x] **Phase 4** — Revolve 2D→3D, export GLB/OBJ.
- [x] **Phase 5** — Standalone interactive AR twin (`digital_twin.html`). QR: optional.
- [x] **Phase 6a** — Domain validation: Dirichlet vs Neumann BC comparison (1×1m box).
      See `validate_domain_size()` in `em_solver.py` — PASS, diffs <0.06% at ±500mm domain.
- [x] **Phase 6b** — Re-run pipeline with T_amb=20°C, regenerate `digital_twin_fem.html`.
      Done 2026-06-22: full pipeline (config → em_solver → thermal_solver → rom →
      visualize → build_twin_html_fem) re-ran with T_amb=20°C, ±500mm domain; all
      outputs regenerated.
- [x] **Phase 8** — `data_io.py` + `arduino/thermal_sensor.ino`: `SensorReader` (serial or
  mock) -> `calibrate_from_file()` -> `rom.calibrate_UA()`. Tested against `mock_sensor_data.csv`.
- [ ] **Phase 7** — Sensor hardware: build the real Arduino rig (Arduino + thermocouple +
  IR thermometer, see `docs/SENSOR_PLAN.md`), then re-run Phase 8 calibration on real data.

## Axisymmetric FEM math (reference)
Weak form with volume weight `2πr dr dz`:

    ∫ k ∇T·∇v · 2πr dA  +  ∫_Γ h T v · 2πr ds
        =  ∫ p v · 2πr dA  +  ∫_Γ h T∞ v · 2πr ds

- P1 elements: `∇T` is constant per triangle → `Ke = 2π·k·(b bᵀ + c cᵀ)·A·r_c`.
- Convection edge (linear r weight):
  `Kedge = 2π·h·(L/12)·[[3rₐ+r_b, rₐ+r_b],[rₐ+r_b, rₐ+3r_b]]`.
- The axis r=0 is a symmetry boundary (natural condition, not imposed).
- **Required check:** at steady state Q_in (∫p dV) must equal Q_out (∫h(T−T∞)dA).
