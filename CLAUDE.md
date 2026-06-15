# CLAUDE.md — Project context for Thermal Digital Twin (TEAM 28-like Levitator)

Auto-loaded by Claude Code each session. Keep under ~200 lines. Single source of
truth. See @README.md for setup/run and @physics.md for the full formulation.
NOTE: all source + assets live FLAT in the repo root (no src/ docs/ data/ folders).

## What we are building
A real-time **thermal digital twin** for the aluminium plate + coils of a TEAM 28-like
electrodynamic levitator (TEMF). Predict T(r,z,t), validate vs the rig, visualize in
3D, then ship an AR app + QR code. Operating current î ≈ 5 A, 50 Hz.

## Locked decisions
- NO FEMM (Windows-native; dev machine is macOS). Pure Python (numpy/scipy).
- Problem is AXISYMMETRIC → solve 2D (r,z), revolve to 3D for display.
- Real-time mechanism: linear system → losses ~ î² with fixed spatial pattern,
  modulated by σ(T). Solve FEM once at (î_ref, T_ref); runtime = scalar multiply.
- All tunable parameters live in params.yaml (repo root). Never hardcode constants.
- params.yaml current_A defaults to 5A (operating point). Raise it (e.g. 20A) only
  for an exaggerated heating demo; the ROM always builds at I_ref=5A regardless.
- payload_model (steel disc) is a PLACEHOLDER, disabled by default. When enabled,
  EM reports P_payload_W and thermal/rom now account it (P_plate_W + P_payload_W).
- params.yaml uses e-notation (3.4e7); config.py coerces these to float (PyYAML quirk).

## Device numbers — UPDATED per teacher's email (in params.yaml)
- Plate aluminium: **Ø16cm → R=80mm** (NOT 13cm/65mm). thickness=3mm is a
  placeholder — TEAM MUST MEASURE the real 16cm plate. sigma=3.4e7 S/m.
- Current: **î ≈ 5 A** (rig runs at 5A, not the benchmark's 20A), f=50Hz.
- Turns: **inner=1000, outer=500** (teacher: "1000 und 500"; matches Gemini demo).
- **IRON CORES present** (not in TEAM 28). Modeled linear μ_r=1000; geometry is a
  PLACEHOLDER central cylinder — CONFIRM real core geometry with the rig.
  Watch for saturation at 5A·1000turns; solid core => add eddy loss (sigma_iron>0).
- Coils: height 52mm, Cu wire 1.2mm. Radii from Fig.2/STL — refine from CAD.

## Key physics points (see physics.md)
- Heat source q = ½·σ·ω²·|A_φ|² [W/m³] (cycle-averaged). NOT |∇T|²/σ.
- Solve EM as a PHASOR once; do NOT time-step 50Hz inside the thermal loop.
- σ(T)=σ0/(1+α(T-T0)), α≈3.9e-3/K — include as a runtime amplitude multiplier
  (sigma_tempco_per_K in params), no FEM re-solve. Bodies oppose: plate eddy ∝ σ,
  coil ohmic ∝ 1/σ.
- Skin depth in Al @50Hz ≈ 12mm ≫ 3mm plate → no fine through-thickness mesh.

## First quantitative result (î=5A, payload OFF, placeholder geometry)
Plate eddy ≈ 2.6 W, iron eddy ≈ 0.6 W, **coil ohmic ≈ 73 W → coils dominate heating.**
Plate-only ΔT_max ≈ 3.8 K (T_max ≈ 28.8°C). I²-scaling verified exactly (4.000).
Absolute values need benchmark calibration. (Enabling payload raises plate eddy to ≈5.4 W.)

## Data (repo root)
- levitation_height_team28.csv — Table I from the problem PDF.
  Columns t_ms, z_mm. LEVITATION height (not temperature); settles ~11.3mm.
  Used to validate EM/mechanics, not the thermal field. Thermal sensor data: TBD.
- 3D_model.stl (~Ø340mm, meters, axisymmetric; for visualization/AR + build_twin_html.py).
- Source PDFs (TeamProblem28.pdf / Aufgabenstellung) are NOT committed — keep locally.

## Validation strategy
1. EM reproduces ORIGINAL benchmark (benchmark_team28_original block: 960/576, 20A,
   R=65mm, no iron) → lift force balances gravity at z≈11.3mm vs CSV. Then trust EM.
2. Switch to rig (1000/500, iron, 5A) → loss maps.
3. Losses → thermal solver (done) → T field. Validate vs sensors later.

## Code status
- [x] config.py, params.yaml — done, runs.
- [x] thermal_solver.py — axisymmetric heat FEM, energy balance 0.000% error.
      EM q_e interpolated in; h_bot fix done; normalization fix done.
- [x] em_solver.py — axisymmetric AC eddy-current solve (complex A_phi, iron region);
      compute_losses(cfg) → P_plate/P_iron/P_coil + q_e map. I²-check passes.
      compute_lift_force() + run_benchmark_validation(): z_eq=10.9mm vs 11.3mm (3.5% err).
- [x] rom.py — ThermalROM: build() FEM once at I_ref, T_steady(I) scalar multiply,
      simulate(I_arr, t_arr) ODE bậc nhất, calibrate_UA() từ sensor.
      τ=3.4 phút | σ(T) correction lặp | I²-scaling verified 4.000000.
- [x] digital_twin.py — DigitalTwin(rom): step() Euler, run_live() matplotlib animation.
      Kịch bản: step/ramp/sine/pulse/manual. Slider I, Slider tốc độ (1×–200×, log),
      RadioButtons chọn tấm (plate_library), Space=pause. ROM rebuild on-demand + cache.
      Sensor integration để sau (calibrate_UA() đã sẵn trong ROM).
- [x] visualize.py — make_plate_3d(): revolve FEM 2D→3D surface (top+bot cap+rim),
      matplotlib 3D render (z_scale exaggeration), GLB export via trimesh.
      Outputs: thermal_3d.png, thermal_2d_section.png, plate.glb (247 KB).
      Optional: --pyvista for interactive window.
- [x] sim_plates.py — compare thermal response across plate_library (EM + thermal,
      3D revolve + bar/profile charts). --no-em fast path via σ·R² scaling.
- [x] build_twin_html.py — Phase 5: bake STL geometry + EM losses + lumped thermal
      network into ONE standalone digital_twin.html (no server, double-click to run).
- [ ] NEXT: data_io.py — read sensor CSV → calibrate_UA() (waiting on real sensors).
- [ ] Optional: QR code generation pointing to a hosted digital_twin.html / plate.glb.

## Conventions
- SI units; geometry entered in mm in params.yaml (code converts to m).
- Every new physics term needs an energy-balance / sanity check before use.
