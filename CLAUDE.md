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
- [x] build_twin_html_fem.py — GEOMETRY MATCHED TO REAL DEVICE (2026-07-01 session 4),
      user verified vs docs/real_model.png: (1) wood frame moved 130..165 → **174..194mm**
      (new `device_frame` block in params.yaml: air_gap_mm=50, wall_thickness_mm=20 —
      outer coil stands free in ~50mm air); (2) air gaps 25-28/78-81/101-104mm now REAL
      voids — V_coregap removed, separator mesh shrunk 78..104 → **81..101mm** (reads
      `outer_iron_ring` radii); (3) coils split into own mesh `coilM` (roughness 0.30,
      metalness 0.20 — glossy varnish, not bare metal), COPPER_COLD darkened to
      [0.30,0.14,0.08] chocolate-brown per photo, COPPER_HOT softened to [0.93,0.55,0.16].
      Body tris 4896→3936. Label "Center Core (ceramic)"→"Center Core" (material disputed).
      `window.twinDebug={camera,controls,size}` exposed for headless tests. Verified via
      Playwright: 0 JS errors, screenshots confirm gaps + free-standing frame.
- [x] μ_r SENSITIVITY TEST (2026-07-01): user visually claims center core AND separator
      ring are ferromagnetic (conflicts with negative magnet test on core; ring test
      pending). EM sensitivity at 5A: ring-only μ_r=1000 → P_plate +168%, F_z +178%;
      core-only → +32%/+28%; both → P_plate 9.7→32.9W, F_z 1.69→5.78N (×2 conv).
      NOT negligible IF ferro — but observed levitation (~1.69N vs 1.60N gravity,
      z_eq=4.1mm ≈ user's "2-3× disc thickness") matches μ_r=1, NOT μ_r=1000 (plate
      would fly much higher). DECISION (user, 2026-07-01): keep μ_r=1.0 for now,
      re-verify by magnet test later.
- [x] build_twin_html_fem.py — LEVITATION GAP PHYSICS + BODY HEAT COLORS (2026-07-02):
      (1) Gap: replaced wrong "z_eq ∝ I with hard 4.64A cutoff" (jumped 0→3.8mm) by an
      exponential force-decay model F(I,z)=(I/5)²·F1·e^(−(z−z1)/z0), z0=21.4mm from the
      two EM anchors (F(5A,1mm)=1.85N, F(5A,4.1mm)=mg=1.60N) → z_eq(I)=4.1+2·z0·ln(I/5),
      CONTINUOUS lift-off at I_min≈4.54A, 4.1mm@5A, ≈18.5mm@7A. Plus spring-mass disc
      dynamics (ω=√(g/z0)≈21 rad/s, ζ=0.02, wall-time integration): disc bobs ~9s after
      a current step then settles — matches the real rig behaviour user described.
      Telemetry gap now shows the live spring state.
      (2) Body heat: core/separator colour was frozen (absolute 29–125°C scale → tnorm
      ~0.15 at 45°C) — now normalised to the inner coil's steady rise + sqrt perceptual
      boost in writeRampMetal. ROOT CAUSE was also physical: iron node had P_ref=0 and
      only air coupling (hA=0.06) → +2.4K after 30min. Added CONTACT CONDUCTION inner
      coil → iron node (`G_iron_cond_W_per_K: 0.06`, `hA_iron: 0.244` in params.yaml,
      fit to IR session 1: core 45°C@7.8A steady, ratio 0.32, τ≈4min; low-confidence IR,
      refit with thermocouples later). Now T_iron_ss(5A)=35.6°C ✓. Verified headless:
      0 JS errors, gap curve continuous (0/4.5A, 4.1/5A, 19/7A), bob-and-settle observed,
      coils golden + separator warm after 30 sim-min.
- [x] build_twin_html_fem.py — 4 render fixes (2026-07-02, docs/HTML_TWIN_FIX_PLAN_2026-07-02.md):
      (1) Gap displayed too high (~87 display-mm, disc floating above the whole
      device): root cause was a 3.8mm gap BAKED into the disc geometry (Python
      `z_disc_bot`) stacked with a `LIFT_BASE` JS offset AND `Z_GAP_EXAG=8.0` — all
      three added on top of each other. Fixed: disc now bakes at `z_disc_bot=
      z_coil_top` (sits on coil top), `LIFT_BASE` removed entirely, `Z_GAP_EXAG`
      8.0→2.0 (same factor as the disc-thickness exaggeration) → gap = `lev.z×2.0`
      only, 4.1mm@5A → 8.2 display-mm. Verified: settled display gain matches
      lev.z×2.0 to 5 decimal places.
      (2) B-field lines were static geometry that never reacted to I (dashOffset
      ran on wall-clock only, opacity only followed the slider). Field SHAPE stays
      static (linear problem, correct), but flow speed + opacity now scale with
      `emScale=I_display/I_em_ref`: 0 at I=0 (invisible, frozen), faster/brighter
      as I rises (capped 2x). Verified: opacity=0 at I=0, dashOffset actively
      advancing at I=13A.
      (3) Coil colour didn't track real heating: `tnInner`/`tnOuter` were divided
      by the CURRENT-DEPENDENT `T_ss(I)`, so bumping I made the coil look
      "instantly cooler" and any steady state at any I painted full-hot — visible
      as flicker-with-I in sine scenarios. Fixed: absolute fixed scale `T_COIL_HOT
      =80°C` (anchored to IR session 1: inner coil 79°C@7.8A, the hottest reading
      ever measured), independent of I — colour only moves when the real
      temperature moves. `tnIron` uses the same absolute scale ×1.8 boost (core/
      ring only reach ~45°C @7.8A, tnorm≈0.31 unboosted). Verified: colour holds
      steady immediately after an I step (temp hasn't moved yet), only drifts as
      sim time passes.
      (4) Studio-bright glare: `UnrealBloomPass`+`EffectComposer` (strength 0.42,
      on whenever I>0.01 — i.e. almost always) plus `envMapIntensity=0.8` on every
      mesh made all metal read as glossy chrome sliding highlights on rotate.
      Fixed: composer/bloom pipeline removed entirely (`renderer.render()`
      direct); `makeMesh()` gained a per-mesh `envInt` param — coils envInt=0.15
      roughness=0.80 metalness=0.05 (matte varnish), core/separator envInt=0.25
      roughness=0.60 metalness=0.30 (dull oxidised metal), wood envInt=0.05, only
      the aluminium disc keeps real metalness (0.65, envInt=0.45). Verified:
      0 JS errors across 5 camera angles, no sliding white highlights, matches
      docs/real_model.png (dark matte coils, only the disc is shiny).
- [x] build_twin_html_fem.py — coil GLOW + label de-overlap + field density (2026-07-02 s2),
      per user review vs docs/thermal_test.png (HIKMICRO IR: coils are the BRIGHTEST part,
      yellow-white at ~60°C): (1) coils split into coilInnerM/coilOuterM meshes, each with
      per-material emissive (ember orange, intensity=0.9·tn^1.4 on the absolute 80°C scale)
      — hot windings now visibly LIGHT UP; COPPER_HOT brightened to [1.0,0.80,0.22] +
      pow(t,0.65) perceptual boost (old ramp read as "slightly lighter brown" at tn≈0.5).
      (2) Labels: regionCentroid collapsed to (≈0,y_mid,≈0) for EVERY revolved ring → all
      4 labels stacked on one screen point; now regionAnchor(reg,θ,yPad) anchors each on
      its ring's outer-top edge at its own azimuth + a 5Hz greedy screen-space de-overlap
      pass (stack top-to-bottom via margin-top). (3) B-field line DENSITY now follows I:
      lines amp-ranked, visible fraction = min(I/I_ref,1) (72/360 at 1A → 360/360 at 5A),
      dash gaps shrink above I_ref — on top of existing speed/opacity scaling. (4) Coil
      "→T_ss" arrows were baked once at 5A, never updated → at 5.5A live T sailed past a
      stale "→50°"; now live per-frame coilTss(I). Verified headless: 0 JS errors, no
      label overlap at default+rotated cam, glow 0.43@59°C / 0.87@79°C / ≈0@29°C.
- [ ] OPEN physics question (2026-07-02): twin shows plate T_ss(5.5A)=61.7°C ABOVE the
      inner coil ≈59°C, but IR data says coils run far hotter than the disc. Plate ROM
      (ΔT_max=27K@5A) is the UNCALIBRATED FEM (guessed h; disc IR unreliable so it was
      never fitted) while the coil network is IR-calibrated. Needs a real disc
      thermocouple measurement to calibrate plate h — don't trust plate/coil ordering.
- [x] WP-C (2026-07-02, docs/PLAN_SIM_FEEDBACK_2026-07-02.md): **Al Ø202mm disc option**
      (R=101mm, covers out to the separator ring's outer edge). Added as a NEW
      `plate_library` entry — default `plate_material.radius_mm` stays 80mm (the real,
      validated disc). Build with `python build_twin_html_fem.py --plate-radius 101`
      → `outputs/digital_twin_fem_R101.html` (default file unaffected, verified via
      headless Playwright: 0 JS errors both files, disc bbox radius = 80mm / 101mm
      exactly, screenshot confirms the disc now covers the separator ring and stops
      just short of the outer coil). EM/ROM re-solve FROM SCRATCH at R=101 (not
      scaled from R=80) — `thermal_solver.energy_balance` still 0.000% error.
      **Key result: the Ø202mm disc does NOT levitate at the 5A_rms operating point.**
      m=259.6g → F_grav=2.5465N (was 162.9g/1.5977N at R=80); F_z at the physical
      resting floor z=3.8mm = 1.5318N (I_peak=7.07A convention) — 40% short of
      F_grav. Estimated **I_min_lev ≈ 6.45 A_rms** (vs 5A op point) for it to lift off
      at all; P_plate(5A) rises 9.67W→11.66W (+20%, wider disc overlaps more of the
      field). CAVEAT: outer_iron_ring (r=81–101mm, right under this disc) is still
      modeled as air (μ_r=1, magnet test PENDING) — if it turns out ferromagnetic,
      both F_z and P_plate change substantially (see μ_r sensitivity note above), so
      this R=101 result is only valid under the current air assumption.
      SECONDARY FINDING (mesh-resolution check, not yet acted on): refining
      em_domain.fine_step_mm 2.0→1.0mm moves the R=80 baseline's own z_eq from
      4.15mm→~3.5mm-equivalent (F(3.8mm) drops below F_grav) and R=101's I_min_lev
      from 6.45A→6.9A — same qualitative conclusions, but the already-"VALIDATED"
      R=80 4.1mm figure is more mesh-sensitive than previously assumed. Left
      em_domain unchanged (out of WP-C's scope, adjacent to the already-PAUSED
      benchmark mesh investigation) — flagging for whoever revisits that.
      Staged (NOT wired live) for WP-D: `LEV_ANCHORS` dict + `_lev_anchor()` helper
      in build_twin_html_fem.py (F_z anchors, mass, F_grav, decay length z0 per
      plate radius) — the JS levitation-gap block still owns its own hardcoded
      Z_GAP_5A_MM/Z_DECAY_MM constants (WP-A/WP-D territory); the R101 HTML's
      Levitation Gap telemetry currently still shows a (wrong) nonzero gap because
      of this — expected, closes once WP-D wires PARAMS.lev per radius.
- [x] WP-B (2026-07-02, docs/PLAN_SIM_FEEDBACK_2026-07-02.md): **realistic coil
      cooling** (rig feedback: hot windings take much longer to cool than to heat;
      the old single-node RC model cooled with the SAME τ it heated with, ~350s).
      Two additions in `romStep`/`lumped_physics` (build_twin_html_fem.py) +
      `lumped_thermal` (params.yaml), both scratch-fit (script not committed)
      against `validation_data.thermal_ramp_test`:
      (1) Nonlinear natural convection `h(ΔT) = hA_cal·(ΔT/dT_cal)^0.25`
      (simplified Churchill-Chu; new `convection_exponent` param) — h stays
      exactly hA_cal at the I_ref calibration point (`dT_cal`, baked per node
      from a small linear steady-state solve incl. the inner↔iron contact
      conduction), but drops as ΔT→0 during cooldown, stretching the tail.
      (2) Two-node coil (surface + winding-core): ALL P_ref lands on the surface
      node (unchanged ramp-test transient shape), the winding-core mass
      ((1−coil_C_scale) of the solid-Cu mass) only exchanges heat via a NEW
      `coil_G_wind_W_per_K=1.0` conductance — invisible while heating, keeps
      feeding the surface long after the current is cut. `coil_C_scale` and all
      four `hA_*`/`G_iron_cond` values are UNCHANGED (steady state provably
      invariant to both additions — proven analytically and confirmed live:
      T_inner_ss≈49.0-49.4°C/T_outer_ss≈47.2-47.4°C at T_amb=29°C, i.e.
      40.5°C/38.5°C-equivalent at T_amb=20°C, matches pre-WP-B exactly).
      **Side finding**: re-deriving the ramp-test residual found the CURRENTLY
      DEPLOYED (pre-WP-B) single-node model actually scores RMS=6.6°C on
      `thermal_ramp_test`, not the ~3°C previously claimed here — that claim had
      gone stale (most likely after the iron contact-conduction node was added
      2026-07-02 without re-checking the coil transient). The new two-node model
      both fixes this and adds cooling realism: RMS=2.5°C on the same data.
      Cooldown time-to-`T_air+10%ΔT` is now ~6-8× longer than the old model
      (inner ~1700-2100s sim-time vs ~255s) — verified live via headless
      Playwright (both `digital_twin_fem.html` R=80 and the WP-C
      `digital_twin_fem_R101.html` variant: 0 JS errors, monotonic cooldown,
      deep-node temperature visibly exceeds surface during cooldown confirming
      the reservoir feeds back, no node dips below T_amb).
      **CAVEAT** (same as coil_C_scale): no real COOLDOWN IR/thermocouple data
      exists yet — `coil_G_wind_W_per_K` is fit only against the heating ramp
      (which barely constrains it) plus a qualitative "much slower" cooldown
      target, so treat both the value and the resulting τ as order-of-magnitude.
      **NEXT** (unchanged ask, now more urgent): next lab session, log a real
      cooldown trajectory (steady 5A → I=0, read coil IR every 60s for 20-30 min)
      to actually fit `coil_G_wind_W_per_K` and `convection_exponent`.
- [x] WP-A (2026-07-02, docs/PLAN_SIM_FEEDBACK_2026-07-02.md): **levitation
      oscillation physics**, JS-only (`build_twin_html_fem.py` "Levitation gap
      physics" block + render loop + `window.twinDebug`), no Python/geometry
      changes. Fixes rig feedback: (a) speed slider didn't speed up the bob;
      (b) no chatter below lift-off; (c) 5→7.75A step oscillated as hard as
      0→5A. Changes:
      (1) `levStep(I, dt)` now integrates the spring-mass gap with the EXACT
      closed-form solution of the underdamped oscillator (was: wall-time-only
      substepped Euler) — unconditionally stable for any `dt`, and the caller
      now passes `dt_sim` (sim time) instead of `wall_dt`, so the speed slider
      correctly scales the bob-and-settle. Verified headless: real wall-clock
      settle time ratio between 1x and 10x speed ≈10.4x (target ~10x) — first
      measurement attempt gave a misleadingly low ratio (~3-5x) because the
      test's own "settled" check used a fixed wall-clock poll count, which is
      NOT equivalent between speeds; redone against a fixed SIM-time-stable
      window instead, confirming the fix is correct.
      (2) Sub-lift-off jitter: amplitude ∝ (I/5)² aliased two-tone shimmer
      (`JIT_MM`/`JIT_FREQ1`/`JIT_FREQ2`), fades out once `lev.z>0.5mm`. Verified:
      visible at 0.5A/3A (grows with I), exactly zero at I=0.
      (3) Damping now current-dependent: `ζ(I)=ζ0+ζ1·(I/5)²`, `ζ0=0`/`ζ1=0.02`
      reproduces the old fixed ζ=0.02 exactly at the 5A anchor.
      (4) `lev.z` settle vs `levGapEqMm(I)` verified exact (diff=0.00000mm) at
      6 test currents spanning 0 to 7.75A.
      **OPEN QUESTIONS (need user input, not blocking)**:
      - `Z_OBS_7_75A_MM` (real gap at 7.75A, mm or "x× disc thickness") is still
        `null` in the code — fill it in to refit `Z_DECAY_MM` (currently 21.4mm,
        which predicts z_eq(7.75A)≈22.9mm; user reports the real gap only
        "nudges up a little", so 21.4mm is likely too large).
      - **Numeric inconsistency found, not silently patched**: the plan's own
        acceptance target ("5→7.75A step overshoot <40% of the 0→5A step
        overshoot, normalized") requires ζ(7.75A)≈0.3 — but the plan's own
        physical model (§3, ζ∝I², anchored at ζ(5A)=0.02) can only reach
        ζ(7.75A)≈0.048 without breaking the 5A anchor. Measured overshoot ratio
        is 91.5%, not <40% — this test FAILS as specified. The two numbers in
        the plan (the ζ∝I² law and the <40% target) are mutually incompatible;
        picking one over the other is a product decision, not a bug fix. Left
        ζ1=0.02 (physically motivated, preserves the validated 5A behaviour) and
        documented the conflict inline in the code. Needs a decision: relax the
        overshoot target, adopt a steeper (less physically-derived) damping law,
        or wait for real oscillation-amplitude data at 7.75-8A to fit ζ properly.
      **Still open (WP-D territory, unchanged by this entry)**: `Z_GAP_5A_MM`,
      `Z_DECAY_MM`, `ζ0`/`ζ1`, `JIT_MM`/`JIT_FREQ1`/`JIT_FREQ2` are still
      hardcoded JS literals, not yet routed through `params.yaml`/PARAMS JSON —
      and the R101 build still uses the R=80 lift-force anchors (see WP-C entry
      above), so its levitation telemetry is known-wrong until WP-D wires
      `LEV_ANCHORS` per plate radius.

## Conventions
- SI units; geometry entered in mm in params.yaml (code converts to m).
- Every new physics term needs an energy-balance / sanity check before use.
