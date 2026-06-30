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

## Professor Feedback — Juni 2026 (locked)
- **Simulation domain**: 1×1×1 m bounding box is sufficient. Validate by comparing
  Dirichlet vs Neumann BC — if results match, domain is large enough. Enlarge if edge
  effects appear. (em_domain now ±500 mm in params.yaml.)
- **Ambient temperature**: Use constant T_amb = 20°C. Do NOT integrate real lab sensor
  data yet. Upgrade only if results are inaccurate. ("Nehmt erst mal alles so einfach
  wie möglich an.")
- **Excitation data**: Measured constant values: 220 V → 5 A (superseded 2026-06-23
  by a re-measurement: see "Real-rig validation" below — main op point is now 190V→5A).
  No real-time current measurement device yet (needs purchase). Use constant I=5A
  for Phase 1.
- **Sensors for validation**: Team designs own solution. Arduino + thermocouple/RTD
  sensors + IR thermometer. Create shopping list (Reichelt/Conrad) → professor buys.
  See SENSOR_PLAN.md.
- **Scope (Prof 2)**: Can start with disc-only simulation first, then expand to full
  device. Current full-device approach is also OK.

## Device numbers — UPDATED per teacher's email (in params.yaml)
- Plate aluminium: **Ø16cm → R=80mm** (NOT 13cm/65mm). thickness=3mm is a
  placeholder — TEAM MUST MEASURE the real 16cm plate. sigma=3.4e7 S/m.
- Current: **î ≈ 5 A** MEASURED (rig: 190V → 5A, re-measured 2026-06-23), f=50Hz.
  voltage_V=190 in params.
- Turns: **inner=1000, outer=500** — CONFIRMED 2026-06-23 by thermal data (inner
  coil runs hotter: more turns → more R → more loss).
- **IRON CORE — material STILL UNVERIFIED.** Modeled linear μ_r=1000 (params.yaml
  `iron_core`); geometry is a PLACEHOLDER central cylinder. User observed the disc
  gets pushed up by a magnetic force once current flows and infers the core is
  iron — this is CIRCUMSTANTIAL, not conclusive (eddy-current repulsion on the
  aluminium disc happens regardless of the core's permeability). Thermal data
  can't tell either (P_iron≈0.6-1.5W barely self-heats either way). A DIRECT test
  (touch a permanent magnet to the unpowered core) would be conclusive — still
  pending. Don't disable iron or change mu_r until that test is done. Watch for
  saturation at 5A·1000turns; solid core => add eddy loss (sigma_iron>0).
- **Separator ring** (white-grey metal ring between coil windings; user's 2nd
  session calls it "lõi sắt ngoài", same unconfirmed-magnet caveat as above) IS
  now rendered as distinct 3D geometry: `build_separator_rings()` in
  build_twin_html_fem.py PROCEDURALLY synthesizes it (region 5, static metal
  colour) since the real STL has no surface at the exact gap radii params.yaml
  implies — a 3-wall hollow-drum shape (walls at r≈24/59/79mm, full device height
  z≈-2..66mm). Visual-only; EM/thermal solve unchanged. See 3D_MODEL_UPDATE_PLAN.md.
- Coils: height 52mm, Cu wire 1.2mm. Radii from Fig.2/STL — **CONFIRM with a real
  ruler measurement on the rig**: the STL's actual coil-region geometry doesn't
  line up cleanly with these radii either (see 3D_MODEL_UPDATE_PLAN.md mismatch).

## Key physics points (see physics.md)
- Heat source q = ½·σ·ω²·|A_φ|² [W/m³] (cycle-averaged). NOT |∇T|²/σ.
- Solve EM as a PHASOR once; do NOT time-step 50Hz inside the thermal loop.
- σ(T)=σ0/(1+α(T-T0)), α≈3.9e-3/K — include as a runtime amplitude multiplier
  (sigma_tempco_per_K in params), no FEM re-solve. Bodies oppose: plate eddy ∝ σ,
  coil ohmic ∝ 1/σ.
- Skin depth in Al @50Hz ≈ 12mm ≫ 3mm plate → no fine through-thickness mesh.

## First quantitative result (î=5A, T_amb=20°C, payload OFF, domain ±500mm, re-run 2026-06-22)
Plate eddy ≈ 2.61 W, iron eddy ≈ 0.63 W, **coil ohmic ≈ 72.8 W → coils dominate heating.**
With coil→air coupling (k_coil_coupling_K_per_W=0.15, thermal_bc): **T_max ≈ 31.4°C, ΔT_max ≈
11.4 K** (disc bottom is warmed by coil heat, not just plate eddy — this dominates over the
T_amb shift alone). ROM: τ≈10.6 min, UA=0.231 W/K. I²-scaling verified (3.999–4.000000).
Energy balance error 0.000%. Absolute values need benchmark calibration. (Enabling payload
raises plate eddy to ≈5.4 W — not re-verified after this T_amb/domain update.)

## Real-rig validation (HIKMICRO IR, 2026-06-23, two sessions same day)
Two measured AC 50Hz operating points (`validation_data` in params.yaml): **190V→5A**
(main op point) and **270V→7.8A** (stronger-heating demo, calibration anchor).
**Session 1** (held at 7.8A ~6min, reached steady state): inner coil **79°C**
(hottest), outer coil **74°C**, center core 45°C, separator ring 40°C, disc
rim/center 40/37°C, ambient 29°C. **Session 2** (a 2-stage ramp: 5A for 5min then
7.75A for 2.5min more, NOT held long enough to reach steady state): at the end
(t=450s), inner coil 60.75°C, outer coil 56°C, center core 39.5°C, separator 36°C,
disc-bottom rim/center 44/35°C — plus a timestamped outer-coil trajectory at
t=140/200/300/360s (40/43/48.5/55.75°C) used to fit the coil's time constant.
**Caveat:** disc + center-core IR readings are UNRELIABLE in BOTH sessions (shiny
aluminium, true ε≈0.1 vs camera ε set to 0.91 → reads low) — only the
dark-varnished **coil** readings are trustworthy for calibration.
Calibrated the lumped coil network in two rounds: round 1 (steady-state only) gave
`hA_inner=2.2109`/`hA_outer=1.8889` (was hand-guessed 0.48/0.44), exact fit to
79°C/74°C — but predicted session 2's transient ~10°C too slow. Round 2 added
`coil_C_scale=0.434` (coil thermal mass empirically ~43% of the solid-copper
estimate — insulation/voids, and `wire_diameter_mm=1.2` may be the insulated OD not
bare copper) and refit jointly: `hA_inner=2.2479`/`hA_outer=1.8788`, residuals down
to ~2-5°C. Treat this τ as order-of-magnitude right, not exact (fit from one
narrated-timeline run, ±~10s timing uncertainty). Cross-check at I_ref=5A
(T_amb=20°C baked default, steady-state): predicts T_inner≈40.5°C, T_outer≈38.5°C.

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
      validate_domain_size(cfg): Dirichlet vs Neumann outer BC, PASS (diffs <0.06% at ±500mm).
- [ ] PAUSED (user choice, 2026-06-23): `run_benchmark_validation()` gives z_eq≈7.1mm vs
      11.3mm expected (37% error) — improved from z_eq≈3.4mm (70%) after fixing
      `benchmark_team28_original`'s coil radii (now from the real TeamProblem28.pdf:
      inner r=15-28mm/outer r=41-46.5mm, vs the rig's own 28-43/46.5-61.5mm it was
      wrongly reusing) + a finer mesh for the benchmark's narrow coils (`fine_step_mm
      =0.2` override, just for this call). The old "z_eq=10.9mm/PASS" claim in
      HANDOFF.md/README.md/ARCHITECTURE.md was never actually reproducible (bisected
      every git commit) — corrected those files. Ruled out as the remaining cause:
      mesh resolution, domain size, current_sign convention. 37% gap still unexplained
      — paused here by user request, not currently blocking other work.
- [x] rom.py — ThermalROM: build() FEM once at I_ref, T_steady(I) scalar multiply,
      simulate(I_arr, t_arr) first-order ODE, calibrate_UA() from sensor.
      τ=10.6 min | σ(T) correction iterative | I²-scaling verified 4.000000.
- [x] digital_twin.py — DigitalTwin(rom): step() Euler, run_live() matplotlib animation.
      Scenarios: step/ramp/sine/pulse/manual. Slider I, speed slider (1×–200×, log),
      RadioButtons plate selector (plate_library), Space=pause. ROM rebuild on-demand + cache.
      Sensor integration pending (calibrate_UA() already wired in ROM).
- [x] visualize.py — make_plate_3d(): revolve FEM 2D→3D surface (top+bot cap+rim),
      matplotlib 3D render (z_scale exaggeration), GLB export via trimesh.
      Outputs: thermal_3d.png, thermal_2d_section.png, plate.glb (247 KB).
      Optional: --pyvista for interactive window.
- [x] sim_plates.py — compare thermal response across plate_library (EM + thermal,
      3D revolve + bar/profile charts). --no-em fast path via σ·R² scaling.
- [x] build_twin_html.py — Phase 5: bake STL geometry + EM losses + lumped thermal
      network into ONE standalone digital_twin.html (no server, double-click to run).
- [x] data_io.py + arduino/thermal_sensor/thermal_sensor.ino — SensorReader (serial or
      port="mock" synthetic source) → calibrate_from_file() → rom.calibrate_UA(I_meas,
      dT_meas); live_compare() animation. Tested end-to-end against mock_sensor_data.csv
      (no real hardware yet) — see SENSOR_PLAN.md.
- [ ] NEXT: Sensor hardware — build the real Arduino rig (MAX31855×2 + thermocouples,
      shopping list in SENSOR_PLAN.md), log a real run, re-run calibrate_from_file() on it.
- [x] Domain validation — Dirichlet vs Neumann BC comparison: validate_domain_size() in
      em_solver.py; PASS, diffs <0.06% at ±500mm domain → domain is large enough.
- [x] Re-ran full pipeline with T_amb=20°C, ±500mm domain (2026-06-22): config → em_solver →
      thermal_solver → rom → visualize → build_twin_html_fem, all outputs regenerated.
- [ ] Optional: QR code generation pointing to a hosted digital_twin.html / plate.glb.
- [x] build_twin_html_fem.py render fix (2026-06-23): center spacer (region 3) and
      separator ring (region 5) render as static METAL_RGB instead of the heat ramp
      (both passive, ~36-45°C vs coils' 56-79°C); wood base recoloured brown; CSS2D
      labels "Iron Core"→"Center Spacer", added "Separator Ring". Verified via
      headless Playwright (no JS errors, screenshots confirmed).
- [x] Separator-ring 3D geometry (2026-06-23): `build_separator_rings()` procedurally
      synthesizes 2 thin cylindrical sleeves (region 5) at the iron/inner/outer coil
      gap radii, full device height (z≈-2..66mm, matching the real walls either
      side) — the real STL has no surface to recolour there. Visual only.
- [x] Coil thermal network calibrated in 2 rounds (2026-06-23) from real 7.8A
      steady-state IR data + a 2nd ramp-test session — see "Real-rig validation"
      above and `lumped_thermal` in params.yaml (`coil_C_scale` is new).
- [ ] NEXT: build_twin_html.py (lumped-only, secondary file) not yet synced with the
      separator-ring procedural geometry — only needed if that file is still used.
- [ ] NEXT: Direct magnet-contact test on rig (iron core + separator ring, UNPOWERED)
      to resolve the open ferromagnetic-vs-aluminium question — the lift-force
      observation so far is circumstantial, not conclusive; then re-confirm
      coil/iron radii by ruler.

## Conventions
- SI units; geometry entered in mm in params.yaml (code converts to m).
- Every new physics term needs an energy-balance / sanity check before use.
