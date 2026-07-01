# CLAUDE.md — Project context for Thermal Digital Twin (TEAM 28-like Levitator)

Auto-loaded by Claude Code each session. Keep under ~200 lines. Single source of
truth. See @README.md for setup/run and @docs/physics.md for the full formulation.
NOTE: source scripts (*.py), params.yaml and input data (STL/CSV) stay FLAT in the
repo root — scripts self-locate everything via __file__, so do NOT move them into
src/ or data/. Only two subfolders exist: docs/ (all *.md except CLAUDE.md/README.md)
and outputs/ (all generated PNG/GLB/OBJ/HTML — gitignored except digital_twin_fem.html).

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
  See docs/SENSOR_PLAN.md.
- **Scope (Prof 2)**: Can start with disc-only simulation first, then expand to full
  device. Current full-device approach is also OK.

## Device numbers — UPDATED per teacher's email (in params.yaml)
- Plate aluminium: **Ø16cm → R=80mm** (NOT 13cm/65mm). thickness=**3mm CONFIRMED**
  (physically measured 2026-07-01). sigma=3.4e7 S/m.
- Current: **î ≈ 5 A** MEASURED (rig: 190V → 5A, re-measured 2026-06-23), f=50Hz.
  voltage_V=190 in params.
- Turns: **inner=1000, outer=500** — CONFIRMED 2026-06-23 by thermal data (inner
  coil runs hotter: more turns → more R → more loss).
- **COIL RADII — CORRECTED 2026-07-01** from physical layout description:
  - Inner coil (1000T): r=**28–78mm** (50mm wide) — WAS WRONG (old: 28–43mm, 15mm wide)
  - Outer coil (500T): r=**104–124mm** (20mm wide) — WAS WRONG (old: 46.5–61.5mm)
  - Air gap between inner coil and iron ring: r≈78–81mm (~3mm)
  - **Iron/separator ring**: r=**81–101mm** (20mm wide) — magnet test PENDING on this ring
  - Air gap between iron ring and outer coil: r≈101–104mm (~2mm)
  - After outer coil: ~50mm air to structural device frame edge
  - Device cross-section: core(0-25) | gap | inner(28-78) | gap | iron-ring(81-101) | gap | outer(104-124)
  - Levitating plate R=80mm sits entirely above inner coil — plate edge at 80mm ≈ inner coil edge at 78mm
- **CURRENT CONVENTION**: `current_A=5.0` in params.yaml is the **RMS-measured** value
  (multimeter). The phasor solver needs **amplitude (peak)** = I_rms×√2 = 7.07A.
  Force ∝ I² → EM force predictions are 2× too low if using I_rms as peak.
  Thermal calibration (hA_inner, hA_outer) was calibrated with I_rms as amplitude, so
  thermal temperature predictions remain correct (the ×2 error is absorbed in hA).
  For force: multiply computed F_z by 2.0 when comparing against physical levitation.
- **LIFT FORCE VALIDATED 2026-07-01** (corrected geometry + I_rms×√2):
  F_z_max(5A_rms, z=1mm) ≈ 1.85N > F_gravity(163g)=1.60N → levitation possible ✓
  Predicted z_eq ≈ **4.1mm** gap (plate bottom above coil top); plate top at z≈7.1mm
  → visible ratio 7.1mm/3mm = **2.4× disc thickness** → matches user observation "2–3×" ✓
- **CENTER CORE — CONFIRMED NON-FERROMAGNETIC (2026-07-01).** Magnet-contact test
  (unpowered): no attraction. Also confirmed non-thermally-conductive (ceramic/Al₂O₃-
  like). Model: `iron_core.mu_r=1.0`, `iron_core.sigma_S_per_m=0.0` → P_iron = 0 W.
- **Outer iron ring (r=81–101mm): magnet test PENDING** — currently modeled as air
  (mu_r=1.0, sigma=0) in `outer_iron_ring` block in params.yaml. If confirmed
  ferromagnetic, set mu_r=100–1000, sigma=1e6 and re-run EM.

## Key physics points (see docs/physics.md)
- Heat source q = ½·σ·ω²·|A_φ|² [W/m³] (cycle-averaged). NOT |∇T|²/σ.
- Solve EM as a PHASOR once; do NOT time-step 50Hz inside the thermal loop.
- σ(T)=σ0/(1+α(T-T0)), α≈3.9e-3/K — include as a runtime amplitude multiplier
  (sigma_tempco_per_K in params), no FEM re-solve. Bodies oppose: plate eddy ∝ σ,
  coil ohmic ∝ 1/σ.
- Skin depth in Al @50Hz ≈ 12mm ≫ 3mm plate → no fine through-thickness mesh.

## First quantitative result (î=5A RMS, T_amb=20°C, payload OFF, domain ±500mm)
**CORRECTED + RE-CALIBRATED 2026-07-01 — coil radii fixed (inner 28–78mm, outer 104–124mm):**
Plate eddy ≈ **9.67 W** (was 1.84W). Iron core = 0 W. Coil ohmic ≈ **128 W** (was 72.8W).
Total ≈ **138 W**.
**Lift force validated**: F_z_max(I_peak=7.07A) ≈ 1.85N > F_grav(163g)=1.60N ✓
z_eq ≈ **4.1mm** gap; plate top visible at 7.1mm = 2.4× disc thickness (matches obs) ✓
**Thermal re-calibrated 2026-07-01**: hA_inner=3.5611/hA_outer=4.3446/coil_C_scale=0.2241.
Steady-state coil temps at 5A/20°C: T_inner≈40.5°C, T_outer≈38.5°C (unchanged from before
— T_ss invariant when P and hA scale together). Transient RMS ≈3°C.
**Iron ring r=81–101mm**: material PENDING colleague confirmation. Currently air (mu_r=1.0).

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
Calibrated the lumped coil network in two rounds (2026-06-23) then RE-CALIBRATED
2026-07-01 with corrected coil geometry (P_coil: 72.8→128.2W at 5A). Final values:
`hA_inner=3.5611`/`hA_outer=4.3446`/`coil_C_scale=0.2241`. Steady-state predictions
unchanged at T_inner≈40.5°C/T_outer≈38.5°C at 5A/20°C (T scales proportionally with
P and hA). Transient RMS residual ≈3°C (same quality). Effective C_coil = 0.2241×5556
= 1245 J/K (solid-copper C_solid=5556 J/K with correct radii, 3.67× larger than old
1513 J/K; the 22.4% fill factor reflects insulation/voids in real winding). τ_inner≈
188s/τ_outer≈133s (effective, ignoring air node coupling). Treat as order-of-magnitude.

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
      Outputs (→ outputs/): thermal_3d.png, thermal_2d_section.png, plate.glb (247 KB).
      Optional: --pyvista for interactive window.
- [x] sim_plates.py — compare thermal response across plate_library (EM + thermal,
      3D revolve + bar/profile charts). --no-em fast path via σ·R² scaling.
- [x] build_twin_html.py — Phase 5: bake STL geometry + EM losses + lumped thermal
      network into ONE standalone digital_twin.html (no server, double-click to run).
- [x] data_io.py + arduino/thermal_sensor/thermal_sensor.ino — SensorReader (serial or
      port="mock" synthetic source) → calibrate_from_file() → rom.calibrate_UA(I_meas,
      dT_meas); live_compare() animation. Tested end-to-end against mock_sensor_data.csv
      (no real hardware yet) — see docs/SENSOR_PLAN.md.
- [ ] NEXT: Sensor hardware — build the real Arduino rig (MAX31855×2 + thermocouples,
      shopping list in docs/SENSOR_PLAN.md), log a real run, re-run calibrate_from_file() on it.
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
- [x] Coil thermal network calibrated (2026-06-23) then RE-CALIBRATED (2026-07-01)
      after coil geometry correction. Final: hA_inner=3.5611, hA_outer=4.3446,
      coil_C_scale=0.2241. See "Real-rig validation" + `lumped_thermal` in params.yaml.
- [ ] NEXT: build_twin_html.py (lumped-only, secondary file) not yet synced with the
      separator-ring procedural geometry — only needed if that file is still used.
- [x] Magnet-contact test DONE (2026-07-01): center core = non-ferromagnetic, non-
      thermally-conductive. mu_r=1.0, sigma=0.0 confirmed. Plate thickness=3mm confirmed.
- [ ] NEXT: Re-confirm coil/iron radii by ruler (geometry still unverified).
- [x] build_twin_html_fem.py UI improvements (2026-07-01 session 1):
      Time speed slider default reset to 1×; T_amb display = 29°C (lab ambient);
      Solid center core procedural geometry (`build_solid_core()`, r=0–25mm);
      Gap filler ring r=25–28mm (inner coil material, no air gap between core and coil);
      Levitation gap Z-axis animation bound to I (z_eq=4.1mm@5A, min I_lev=4.64A);
      Levitation gap shown in Telemetry panel; disc label follows disc Y-position;
      Inner/outer coil temps plotted realtime on Time History chart alongside plate T_max;
      Coil surface uses relative heat ramp (0=T_amb, 1=T_ss(I)) → visible colour change;
      Header badge voltage corrected to 220 V (was incorrectly set to 190V).
- [ ] TODO (future): auto-initialise T_amb from OpenWeatherMap API at page load —
      fetch current temperature for Darmstadt, Germany (Zipcode: 64289) and use it
      as the simulation's ambient baseline instead of the hardcoded 29°C.
- [x] build_twin_html_fem.py rendering fixes (2026-07-01 session 2):
      Center Core (reg 3) and Separator Ring (reg 5) now use writeRamp(tnIron) instead
      of static METAL_RGB — they show real heat-ramp colour (conduction from coils,
      ~39-45°C). Center Core label corrected to "Center Core (ferromagnetic)" per user.
      Inner Coil material upgraded (roughness 0.35, metalness 0.55, envMapIntensity 0.7)
      for a coated-wire / insulation-wrapped look. Telemetry row label cleaned to
      "Levitation Gap" (no emoji), value now reads "Levitation Gap: X.X mm".
      Z_GAP_EXAG raised 6.0→8.0 so the 4.1mm physical gap at 5A maps to ~33 display-mm
      (clearer visual lift). Chart coil line widths raised 1.4→2.2 px, colors brightened:
      outer=#ffdd22, inner=#ff6600 — clearly distinct from Plate T_max (#ff6644 1.8px).
- [x] build_twin_html_fem.py — FULL PROCEDURAL GEOMETRY REBUILD (2026-07-01 session 3):
      STL body geometry entirely REMOVED from body pipeline (STL was causing 5 visual bugs:
      hollow core, unrealistic gaps, plastic-looking material, hexagonal frame, surface-only heat).
      ALL device parts now built 100% from params.yaml numbers via revolve_ring()/build_solid_core()/
      build_octagonal_frame() — no classify() STL voxelization. New coordinate system (natural,
      z=0 floor, z=8..60 coil assembly, z=63.8 disc bottom). Region labels:
        reg 3 = center core (solid cylinder r=0..25mm, ceramic/Al₂O₃)
        reg 1 = inner coil + gap-filler (solid toroid r=25..78mm, 1000T varnished copper)
        reg 5 = separator / iron ring (solid fill r=78..104mm — entire gap, no visible voids)
        reg 2 = outer coil (solid toroid r=104..124mm, 500T varnished copper)
        reg 4 = plywood octagonal frame (8-sided prism r=130..165mm)
        reg 0 = levitating disc (Ø160mm × 3mm Al, z≈63.8mm above coil top)
      New thermal ramp functions: writeRampCopper() (dark red-brown→orange-yellow, for coils) and
      writeRampMetal() (silver-gray→warm orange, for core/separator). Separate Three.js meshes:
      baseM (roughness=0.42, metalness=0.68) / woodM (0.88, 0.02) / plateM (0.35, 0.75).
      Total body tris: ~4896. Disc: ~3072 tris. Output: outputs/digital_twin_fem.html (625 KB).

## Conventions
- SI units; geometry entered in mm in params.yaml (code converts to m).
- Every new physics term needs an energy-balance / sanity check before use.
