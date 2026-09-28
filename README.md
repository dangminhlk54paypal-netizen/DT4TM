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
python em_solver.py         # AC eddy losses + I² check + benchmark (z_eq≈14.5mm vs 11.3 expected — PAUSED, see CLAUDE.md)
python thermal_solver.py    # solve heat + energy balance (expect "error=0.000%")
python rom.py               # real-time ROM demo (I² scaling + transient)
python twin_core.py         # SSOT time-integrator self-check (6/6 PASS, no config/matplotlib needed)
python digital_twin.py      # interactive live twin (slider I, plate selector)
python visualize.py --no-show   # revolve 2D→3D, export outputs/plate.glb
python sim_plates.py            # compare plates from plate_library
# build_twin_html.py deleted 2026-07-02 (commit ec64ec1) — superseded by build_twin_html_fem.py below
python build_twin_html_fem.py            # FEM-accurate bake → outputs/digital_twin_fem.html (R=80mm, default disc)
python build_twin_html_fem.py --plate-radius 75   # same, but Ø150mm disc → outputs/digital_twin_fem_R75.html
python xval_twin.py                      # pin twin_core.py against the baked JS engine (Playwright)
python refit_hA.py                       # WP-COOL T4: refit lumped_thermal.hA_inner/outer through the
                                          # actual nonlinear TwinState integrator (params.yaml stays SSOT)
python gen_qr.py <hosted-url>            # QR code -> outputs/qr_digital_twin.png (URL TBD, see CLAUDE.md)
python gen_ar_marker.py                  # Printable AprilTag (tag36h11) 2x2 board -> outputs/ar_marker.pdf (+ .png preview); print at 100 %
python build_apriltag_wasm.py            # OPTIONAL, needs Docker: rebuild apriltag_wasm.js from the pinned AprilTag C sources (committed artifact, bit-reproducible)
python build_ar_twin.py                  # Generate mobile WebAR twin -> outputs/ar_twin.html

# Optional extension: PyVista desktop 3D twin (~400MB VTK dep, see extensions/README.md)
python extensions/digital_twin_pyvista.py --self-check          # sanity check, no VTK needed
pip install "pyvista>=0.45" "vtk>=9.3,<9.7"                     # needed for the two below
python extensions/digital_twin_pyvista.py --screenshot outputs/twin_pv.png --no-show
python extensions/digital_twin_pyvista.py --speed 50            # live interactive window
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
twin_core.py        # SSOT time integrator (dual-β disc + lumped coil/iron/air + levitation);
                     # numpy+stdlib ONLY. TwinState — shared by every twin below.
twin_model.py        # heavy bridge: resolve_active_plate/PlateCache/coeffs_from_live/
                     # build_plate_variant (config/em_solver/rom/build_twin_html_fem-dependent)
digital_twin.py     # interactive live loop I(t) -> T(r,z,t) (matplotlib)
xval_twin.py        # pins twin_core.py against outputs/digital_twin_fem.html's baked JS (Playwright)
visualize.py        # revolve 2D->3D, export GLB/OBJ (+ optional PyVista)
sim_plates.py       # compare thermal response across plate_library
# (build_twin_html.py deleted 2026-07-02, commit ec64ec1 — superseded by build_twin_html_fem.py below)
build_twin_html_fem.py  # FEM-based bake  -> outputs/digital_twin_fem.html
refit_hA.py          # WP-COOL T4: solve lumped_thermal.hA_inner/outer through the actual
                     # TwinState integrator instead of a hand-derived linear formula
data_io.py          # Arduino sensor bridge (serial or mock) -> rom.calibrate_UA()
gen_qr.py           # QR code for the hosted digital_twin_fem.html (URL via CLI arg)
gen_ar_marker.py    # Printable AprilTag board PDF (vector, A4) + board-geometry constants shared with the AR page
build_apriltag_wasm.py + apriltag_glue.c  # Docker build -> apriltag_wasm.js + tag36h11_codes.json (committed; inline in ar_twin.html)
build_ar_twin.py    # Mobile WebAR app builder -> outputs/ar_twin.html
extensions/         # OPTIONAL add-ons — heavy deps the core avoids; nothing in the root
                    #   imports them, so the pipeline runs with this folder deleted.
                    #   digital_twin_pyvista.py (PyVista/VTK 3D twin). See its README.md.
arduino/thermal_sensor/thermal_sensor.ino  # MAX31855x2 firmware, 1Hz CSV over serial
3D_model.stl                    # colleague's CAD (source, meters, axisymmetric)
levitation_height_team28.csv    # Table I from the PDF (levitation height, validation)
mock_sensor_data.csv            # synthetic sensor log for testing data_io.py
docs/               # LIVING docs: physics.md, ARCHITECTURE.md, CHANGELOG.md, HANDOFF.md,
                    #   SENSOR_PLAN.md, QUICK_START_FOR_AGENTS.md, math_formulation.md,
                    #   REPORT_WHY_CUSTOM_CODE{,_DE}.md
docs/archive/       # COMPLETED plans + bug registers, named YYYY-MM-DD_TOPIC.md.
                    #   Historical record only — see docs/archive/README.md for the index.
outputs/            # generated PNG/GLB/OBJ/HTML (gitignored except digital_twin_fem.html)
```

## Roadmap
- [x] **Phase 1a** — Axisymmetric heat solver, verified by energy balance.
- [x] **Phase 1b** — EM solver (AC eddy currents) — real losses computed; original-benchmark
      lift-force check currently PAUSED at z_eq≈14.5mm vs 11.3mm expected (28% overshoot,
      2026-07-11 after an RMS/peak bugfix) — not yet fully matching, see CLAUDE.md.
- [x] **Phase 2** — Real-time ROM (I² + first-order transient + σ(T) correction).
- [x] **Phase 3** — Twin loop (interactive). Measured-data ingestion: pending real sensors.
- [x] **Phase 4** — Revolve 2D→3D, export GLB/OBJ.
- [x] **Phase 5** — Standalone interactive AR twin (`digital_twin.html`). QR: optional.
- [x] **Phase 6a** — Domain validation: Dirichlet vs Neumann BC comparison (1×1m box).
      See `validate_domain_size()` in `em_solver.py` — PASS, all diffs <1% at the ±500mm
      domain (largest: P_plate 0.767%), re-checked after the 2026-07-10 geometry
      re-measurement. The "<0.06%" once quoted here was the pre-remeasurement figure.
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
