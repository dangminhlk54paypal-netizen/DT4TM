# CLAUDE.md — Project context for Thermal Digital Twin (TEAM 28-like Levitator)

Auto-loaded by Claude Code each session. Keep under ~200 lines. Single source of
truth. See @README.md for setup/run and @docs/physics.md for the full formulation.
NOTE: source scripts (*.py), params.yaml and input data (STL/CSV) stay FLAT in the
repo root — scripts self-locate everything via __file__, so do NOT move them into
src/ or data/. Three subfolders exist: docs/ (all *.md except CLAUDE.md/README.md),
outputs/ (all generated PNG/GLB/OBJ/HTML — gitignored except digital_twin_fem.html),
and local/ (entirely gitignored — local-only secrets, e.g. `local/.env.local`
holding `GOOGLE_WEATHER_API_KEY`; never committed, see "Code status" below).

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
- **COIL RADII — RE-MEASURED 2026-07-10** by direct ruler measurement of the rig
  (supersedes the 2026-07-01 "physical layout description" pass):
  - Center core: r=**0–25.9mm** (was 0–25mm; diameter measured 51.8mm)
  - Air gap core→inner coil: 2mm (25.9–27.9mm)
  - Inner coil (1000T): r=**27.9–61.9mm** (34mm wide) — WAS WRONG (2026-07-01: 28–78mm, 50mm wide)
  - Air gap inner coil→iron ring: 3mm (61.9–64.9mm)
  - **Iron ring**: r=**64.9–79.9mm** (15mm wide) — WAS WRONG (2026-07-01: 81–101mm, 20mm wide);
    material now **CONFIRMED IRON** (see below, was PENDING)
  - Air gap iron ring→outer coil: 3mm (79.9–82.9mm)
  - Outer coil (500T): r=**82.9–102.9mm** (20mm wide, unchanged width) — WAS WRONG (2026-07-01: 104–124mm)
  - After outer coil: 25–30mm air to frame's near wall, 50mm total to frame's outer edge
  - Device cross-section: core(0-25.9) | gap | inner(27.9-61.9) | gap | iron-ring(64.9-79.9) | gap | outer(82.9-102.9)
  - Levitating plate R=80mm now overlaps the iron-ring region (64.9–79.9mm), NOT just
    the inner coil — a structurally different EM picture than the pre-2026-07-10 geometry
    (where the disc edge sat just inside the inner coil's own outer edge at 78mm)
- **CURRENT CONVENTION**: `current_A=5.0` in params.yaml is the **RMS-measured** value
  (multimeter). The phasor solver's LOSS chain (compute_losses→hA calibration)
  intentionally treats it AS the amplitude — thermal predictions are correct as-is
  (the ×2 error is absorbed into hA_inner/hA_outer). The FORCE chain needs the true
  amplitude = I_rms×√2 = 7.07A: use `cfg.I_peak` (config.py) / pass
  `I_amplitude=cfg.I_peak` to `compute_lift_force()`/`solve_em()` — do NOT manually
  multiply F_z by 2.0 anymore (that pattern was replaced 2026-07-10, WP-PEAK).
- **CENTER CORE + IRON RING (r=64.9–79.9mm) — BOTH ferromagnetic, CONFIRMED 2026-07-10**
  (magnet-attracted). Center core supersedes the 2026-07-01 "CONFIRMED NON-FERROMAGNETIC"
  entry (that test is now considered wrong; user re-tested and confirmed attraction).
  Iron ring was PENDING, now confirmed by the same test. Both: `mu_r=1000.0`,
  `sigma_S_per_m=1.0e6` (mild-steel-*like* placeholder, docs/physics.md's original
  "e.g. mu_r=1000" — exact alloy/B-H curve still unmeasured). P_iron now nonzero
  (self-heats) — consistent with the "center core 45°C" IR reading below being real
  self-heating, not just conduction as previously assumed. ⚠️ `solve_em_saturating()`
  only Picard-corrects `iron_core`'s μᵣ, not `outer_iron_ring`'s (known gap,
  docs/AUDIT_FIX_PLAN_2026-07-04.md M5) — now live since this ring is real iron
  (solver prints a WARNING every run); not urgent since B_max=0.66T ≪ B_sat=1.5T.
- ⚠️ **LIFT FORCE — MISMATCH since 2026-07-10 (OPEN QUESTION), was VALIDATED 2026-07-01.**
  F_z(5A_rms peak, z=3.8mm) ≈ 4.10N ≫ F_gravity(163g)=1.60N — levitates with a much
  bigger margin, but predicted z_eq moved to **11.7mm** (plate bottom)/**14.7mm** visible
  — the real observed visible gap is **7–8mm** (2026-07-01), a ~7mm mismatch (previously
  matched almost exactly: 4.1mm→7.1mm ≈ 2.4× disc thickness ✓). Suspect cause: the
  `mu_r=1000` placeholder above may be too high (open magnetic circuit, real alloy
  unknown). User asked to keep the new data as-is and record this as an open question
  rather than reverse-fit μᵣ to match the old gap — do NOT treat z_eq as validated.

## Key physics points (see docs/physics.md)
- Heat source q = ½·σ·ω²·|A_φ|² [W/m³] (cycle-averaged). NOT |∇T|²/σ.
- Solve EM as a PHASOR once; do NOT time-step 50Hz inside the thermal loop.
- σ(T)=σ0/(1+α(T-T0)), α≈3.9e-3/K — include as a runtime amplitude multiplier
  (sigma_tempco_per_K in params), no FEM re-solve. Bodies oppose: plate eddy ∝ σ,
  coil ohmic ∝ 1/σ.
- Skin depth in Al @50Hz ≈ 12mm ≫ 3mm plate → no fine through-thickness mesh.

## First quantitative result (î=5A RMS, T_amb=20°C, payload OFF, domain ±500mm)
**RE-MEASURED geometry + iron material CONFIRMED 2026-07-10** (see "Device numbers"):
Plate eddy ≈ **25.8 W** (was 9.67W — plate now overlaps the iron ring). Iron core+ring
eddy ≈ **5.76 W** (was 0 W — iron self-heats now). Coil ohmic ≈ **106.4 W** (inner
52.3/outer 54.1W; was 128W — coil mean radii shrank). Total ≈ **138.0 W** (barely
changed from 137.9W — coincidence, the loss REDISTRIBUTED, not just scaled). B_max in
iron = 0.66T, unsaturated. I²-check 3.998≈4.000.
⚠️ Lift force/z_eq mismatch (OPEN QUESTION) and thermal calibration STALE — see
"LIFT FORCE" and "Real-rig validation" notes above/below, don't treat either as validated.

## Real-rig validation (HIKMICRO IR, 2026-06-23) — reference data
Two measured AC 50Hz operating points (`validation_data` in params.yaml): **190V→5A**
(main op point) and **270V→7.8A** (calibration anchor). **Session 1** (steady state
@7.8A): inner coil **79°C** (hottest), outer coil 74°C, center core 45°C, separator
40°C, ambient 29°C. **Session 2** (ramp, not steady): inner/outer coil 60.75/56°C at
t=450s, plus a timestamped outer-coil trajectory used to fit the coil's time constant.
**Caveat:** disc + center-core IR readings are UNRELIABLE (shiny aluminium, wrong
emissivity) — only the dark-varnished **coil** readings are trustworthy for calibration.
(Note 2026-07-10: the center-core 45°C reading is now also physically plausible as real
self-heating, since the core is confirmed iron with nonzero P_iron — previously it was
assumed to be pure conduction from the coils since the core itself had P=0.)
Final calibrated lumped coil network (params.yaml `lumped_thermal`):
`hA_inner=3.5611`/`hA_outer=4.3446`/`coil_C_scale=0.2241` → T_inner_ss≈40.5°C/
T_outer_ss≈38.5°C at 5A/20°C. A two-node cooldown model (surface + winding-core
reservoir) was added later — RMS residual on the ramp test = 2.5°C. Full calibration
history (two rounds, why the numbers changed) → docs/CHANGELOG.md.
⚠️ **STALE since 2026-07-10**: fitted against pre-remeasurement P_coil values (was
150.3/161.6W at 7.8A, now 127.3/131.7W, ~15-18% lower, plus P_iron/P_plate are no
longer ~0) — needs refitting, see NEXT list below.

## Data (repo root)
- levitation_height_team28.csv — Table I from the problem PDF.
  Columns t_ms, z_mm. LEVITATION height (not temperature); settles ~11.3mm.
  Used to validate EM/mechanics, not the thermal field. Thermal sensor data: TBD.
- 3D_model.stl (~Ø340mm, meters, axisymmetric; for visualization/AR — historical
  input to the now-deleted build_twin_html.py; build_twin_html_fem.py is fully
  procedural and no longer reads this file).
- Source PDFs (TeamProblem28.pdf / Aufgabenstellung) are NOT committed — keep locally.

## Validation strategy
1. EM reproduces ORIGINAL benchmark (benchmark_team28_original block: 960/576, 20A,
   R=65mm, no iron) → lift force balances gravity at z≈11.3mm vs CSV. Then trust EM.
2. Switch to rig (1000/500, iron, 5A) → loss maps.
3. Losses → thermal solver (done) → T field. Validate vs sensors later.

## Code status
Full session-by-session history (every fix, render tweak, calibration round,
WP-A/B/C/D/PEAK narrative) → **docs/CHANGELOG.md**. This section is CURRENT
STATE ONLY — trimmed 2026-07-10 (WP-TRIM, docs/AUDIT_FIX_PLAN_2026-07-04.md).

- [x] `config.py`/`params.yaml` — load/normalize cleanly. `Config.I_peak`
      (=I×√2, for force calcs) and `Config.dial_to_current_A`/
      `dial_to_voltage_V` (variac dial, degrees) available.
- [x] `thermal_solver.py` — axisymmetric heat FEM, energy balance 0.000% error.
- [x] `em_solver.py` — AC eddy solve; `compute_losses`/`compute_lift_force`/
      `check_saturation`/`solve_em_saturating` all take an optional
      `I_amplitude`/`B_scale` param (force/B-report path uses `cfg.I_peak`,
      loss path stays on `cfg.I` — see "CURRENT CONVENTION" above). I²-check
      passes (3.998≈4.000). `run_rig_validation()` correctly brackets
      F_gravity, prints z_eq≈11.7mm (plate-bottom) / visible gap≈14.7mm —
      ⚠️ MISMATCH vs observed 7-8mm, see "LIFT FORCE" OPEN QUESTION above.
      [x] RESOLVED 2026-07-10: `validate_domain_size()` now PASSES again
      (all diffs <1%, e.g. P_plate 0.767%) — was FAILing at 2.71% as of
      2026-07-10 (pre-remeasurement); re-ran clean after the geometry+iron
      update above, root cause of the earlier regression still unknown but
      no longer blocking.
- [ ] PAUSED: `run_benchmark_validation()` (original TEAM28, 20A, no iron)
      gives z_eq≈6.8mm vs 11.3mm expected (40% error; was 7.1mm/37% until
      2026-07-10, when `outer_iron_ring`/`payload_model` were also disabled
      for this call — they were previously left enabled, harmless while
      `outer_iron_ring` was air-like but no longer once it became real iron)
      — unexplained, paused by user request 2026-06-23, not blocking. Its
      20A is the original problem's own convention, not a multimeter reading.
- [x] `rom.py` — ThermalROM, I²-scaling exact (4.000000), τ=5.53min@R=80mm.
- [x] `digital_twin.py` — interactive matplotlib twin (I/dial/speed sliders,
      plate RadioButtons matched by `radius_mm`+material — not a name string,
      scenario picker). `--dt`/`--window` CLI defaults read from
      `params.yaml transient:` block.
- [x] `visualize.py`, `sim_plates.py` — 2D→3D revolve/GLB export, cross-plate
      comparison. Both stable, no open issues.
- [x] `data_io.py` + `arduino/thermal_sensor.ino` — SensorReader (serial/mock)
      → `calibrate_from_file()` → `rom.calibrate_UA()`. Tested against
      `mock_sensor_data.csv`; real hardware still NEXT (see below).
- [x] `gen_qr.py` — QR → `outputs/qr_digital_twin.png`. Hosting URL for
      `digital_twin_fem.html` still undecided (GitHub Pages vs other).
- [x] `build_twin_html_fem.py` — the FEM-accurate standalone AR twin (only
      active HTML builder; `build_twin_html.py` deleted 2026-07-02). CURRENT
      STATE: 100% procedural geometry from params.yaml (no STL dependency),
      matched to real device photos; two-node coil thermal model (surface +
      winding-core reservoir, nonlinear convection) with iron contact
      conduction; exact closed-form spring-mass levitation dynamics with
      current-dependent damping + sub-lift-off jitter, constants sourced from
      `params.yaml levitation:` block (not hardcoded); disc-radius compare
      mode (4 live-swappable aluminium radii, SSOT-derived from
      `plate_library`, each with its own from-scratch EM+ROM+lev+field-line
      solve); dual input mode (Amps slider or Variac Dial in degrees, correct
      V conversion); live T_amb from Google Weather API (falls back to
      29°C); `--bake-key` flag gates the real API key (default: always
      placeholder). Verified 0 JS errors, Playwright-tested after every change.
- [ ] NEXT: sensor hardware build (Arduino + MAX31855×2, docs/SENSOR_PLAN.md),
      log a real run, re-calibrate from it. Also: coil cooldown IR data (fits
      `coil_G_wind_W_per_K`/`convection_exponent`, currently
      order-of-magnitude only), 7.75-8A levitation-oscillation amplitude data
      (fits WP-A's ζ damping law, currently has an internal spec conflict —
      see docs/CHANGELOG.md), denser variac dial→I calibration table (only 3
      anchor points), annulus/hollow-disc geometry support (3 real discs in
      `plate_library_annulus_TODO`, r_out=55/r_in=27.5mm — solvers only mesh
      solid discs from r=0, not wired in yet).
- [ ] OPEN QUESTION (2026-07-10): iron_core/outer_iron_ring `mu_r=1000` is a
      mild-steel-*like* placeholder (never measured — no B-H curve, no
      resistivity test), and it makes the predicted levitation gap ~2x the
      observed one (see "LIFT FORCE" bullet above). Needs either a real B-H/μᵣ
      measurement, or accepting the mismatch as a known model limitation.
      Also NEXT: refit `lumped_thermal` (hA_inner/hA_outer/coil_C_scale) — the
      current values are STALE against the new P_coil numbers (see "First
      quantitative result"); and generalize `solve_em_saturating()`'s Picard
      loop to cover `outer_iron_ring` too (docs/AUDIT_FIX_PLAN_2026-07-04.md
      M5 — not urgent right now since B_max=0.66T is unsaturated, but was a
      silent gap before this ring had a real μᵣ to correct).
- [x] RESOLVED 2026-07-10: `plate_library` replaced with the team's real
      measured solid discs — Al Ø130/140/150/160mm, Ø160mm is the standard
      test disc (matches `plate_material` default r=80mm); dropped the old
      Ø100/Ø200/Ø202mm/Cu Ø160mm placeholders (not real stocked discs).
- [x] RESOLVED 2026-07-10 (WP-Z0): R=80's `levitation.z_decay_mm` switched
      21.4mm→**13.6mm** — user confirmed the real rig's gap only "nudges up a
      little" at 7.75A, matching the smaller F1/F5-method value (now used for
      EVERY plate radius, not just R=80). z_eq(7.75A) prediction: 22.9mm→16.0mm.
      Still order-of-magnitude (no real multi-current gap measurement exists
      yet). See docs/AUDIT_FIX_PLAN_2026-07-04.md OQ-4 / docs/CHANGELOG.md "WP-D".
- [ ] PENDING data, not blocking: plate-vs-coil temperature ordering is only
      *tied* in the model (IR data implies coil should be clearly hotter) —
      needs a real disc-bottom thermocouple reading to resolve further.

## Conventions
- SI units; geometry entered in mm in params.yaml (code converts to m).
- Every new physics term needs an energy-balance / sanity check before use.
- **Secrets/API keys — NEVER commit, in this repo or any future one.** Real key
  values go ONLY in `local/` (repo root, entirely gitignored — see NOTE at top
  of this file). Tracked source (*.py, params.yaml, etc.) must only ever
  contain a placeholder token (e.g. `__GOOGLE_WEATHER_KEY__` /
  `"YOUR_KEY_HERE"`); a build-time loader substitutes the real value from
  `local/` at build/run time and is the only thing allowed to read it. If a
  build product that bakes a real key (e.g. `outputs/digital_twin_fem.html`,
  which IS git-tracked) is regenerated locally, do not `git add`/`commit` it
  while it contains a real key — rebuild with the placeholder first, or
  strip the key back out. `.claude/settings.json` also carries a `PreToolUse`
  hook on `git commit *` that greps both the staged AND unstaged diff for
  known key patterns (currently `AIzaSy[0-9A-Za-z_-]{20,}` for Google keys)
  and denies the commit if found — treat this as a backstop, not a substitute
  for the rule above; extend the hook's regex whenever a new provider's key
  format is introduced. See docs/CHANGELOG.md's "Auto-init T_amb from a live
  weather API" entry for the worked example (Google Weather API key).

## Token discipline (Claude Code)
- Broad multi-file searches → dispatch an Explore subagent; keep only its summary
  in the main context, never raw file dumps.
- Filter long shell output (`| tail -n 30`, `grep -E ...`) — never paste full
  test/build/Playwright logs into context.
- Read big files by line-range only. NEVER Read `outputs/digital_twin_fem*.html`
  whole (~600 KB baked JS) — grep for the marker/section instead.
- Debugging: root cause BEFORE any fix — 4 phases reproduce → isolate → identify →
  verify (systematic-debugging skill). Symptom patches are failure.
- Before claiming done/fixed: run the verification command and show its output
  (verification-before-completion skill). Evidence before assertions.
