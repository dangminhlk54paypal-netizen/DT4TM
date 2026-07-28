# CLAUDE.md — Project context for Thermal Digital Twin (TEAM 28-like Levitator)

Auto-loaded each session. Keep under ~200 lines — **CURRENT STATE ONLY.** All history
(every fix, calibration round, superseded number) → **docs/CHANGELOG.md**; finished
one-off plans/audits → **docs/archive/** (indexed in `docs/archive/README.md`).
See @README.md for setup/run and @docs/physics.md for the full formulation.

**Layout rule:** source scripts (*.py), params.yaml and input data (STL/CSV) stay FLAT
in the repo root — scripts self-locate via `__file__`, so do NOT move them into src/ or
data/. Four subfolders, and only these:
- `docs/` — all *.md except CLAUDE.md/README.md, plus `docs/archive/` for completed plans.
- `outputs/` — generated PNG/GLB/OBJ/HTML, gitignored except digital_twin_fem.html.
- `local/` — entirely gitignored; local-only secrets, e.g. `local/.env.local` holding
  `GOOGLE_WEATHER_API_KEY` (see "Conventions").
- `extensions/` — the ONE exception to the flat rule (added 2026-07-28). A script may
  live here only if it needs a heavy/awkward dependency the core avoids AND nothing in
  the root imports it. Dependency arrow is one-way (`extensions/ → root`, never back), so
  the core pipeline still runs with the folder deleted. Such scripts must put the REPO
  ROOT on `sys.path` (not their own folder), import-guard the heavy dep, and ship a
  `--self-check` that runs without it. Contract + rationale: `extensions/README.md`.

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
  EM reports P_payload_W and thermal/rom account it (P_plate_W + P_payload_W).
- params.yaml uses e-notation (3.4e7); config.py coerces these to float (PyYAML quirk).

## Professor Feedback — Juni 2026 (locked)
- **Simulation domain**: 1×1×1 m bounding box is sufficient. Validate by comparing
  Dirichlet vs Neumann BC — if results match, domain is large enough. Enlarge if edge
  effects appear. (em_domain now ±500 mm in params.yaml.)
- **Ambient temperature**: constant T_amb = 20°C. Do NOT integrate real lab sensor data
  yet. Upgrade only if results are inaccurate. ("Nehmt erst mal alles so einfach wie
  möglich an.")
- **Excitation data**: measured constant values, main op point **190V→5A**. No real-time
  current measurement device yet (needs purchase). Use constant I=5A for Phase 1.
- **Sensors for validation**: team designs own solution. Arduino + thermocouple/RTD +
  IR thermometer. Shopping list (Reichelt/Conrad) → professor buys. See docs/SENSOR_PLAN.md.
- **Scope (Prof 2)**: can start disc-only, then expand. Current full-device approach is OK.

## Device numbers (params.yaml is the SSOT — values below mirror it)
Geometry was RE-MEASURED 2026-07-10 by direct ruler measurement of the rig; every
pre-2026-07-10 radius is superseded (history → docs/CHANGELOG.md).
- Plate aluminium: **Ø16cm → R=80mm**, thickness **3mm** (measured 2026-07-01),
  sigma=3.4e7 S/m, mass 159–163g.
- Current: **î ≈ 5 A** MEASURED (190V → 5A), f=50Hz. voltage_V=190 in params.
- Turns: **inner=1000, outer=500** — confirmed by thermal data (inner coil runs hotter).
- Cross-section (mm, radius): core **0–25.9** | gap | inner coil 1000T **27.9–61.9** |
  gap | **iron ring 64.9–79.9** | gap | outer coil 500T **82.9–102.9** | 25–30mm air to
  the frame's near wall. Coil/core height 53mm.
- ⚠️ The levitating plate (R=80mm) **overlaps the iron ring** (64.9–79.9mm), not just the
  inner coil — a structurally different EM picture from the pre-2026-07-10 geometry.
- **Center core AND iron ring are BOTH ferromagnetic** (magnet-attracted, confirmed
  2026-07-10). Both use `mu_r=1000.0`, `sigma_S_per_m=1.0e6` — a mild-steel-*like*
  PLACEHOLDER, exact alloy/B-H curve still unmeasured (see OPEN QUESTIONS). P_iron is
  nonzero, so the iron self-heats. `solve_em_saturating()`/`check_saturation()` both
  correct core AND ring; B_max=0.66T ≪ B_sat=1.5T, unsaturated either way.

### ⚠️ CURRENT CONVENTION (read before touching any force code)
`current_A=5.0` in params.yaml is the **RMS-measured** value (multimeter).
- **LOSS chain** (`compute_losses` → hA calibration) intentionally treats it AS the
  amplitude. Thermal predictions are correct as-is — the ×2 error is absorbed into
  hA_inner/hA_outer. Keep this path on `cfg.I`.
- **FORCE chain** needs the true amplitude = I_rms×√2 = 7.07A: use `cfg.I_peak`
  (config.py), i.e. pass `I_amplitude=cfg.I_peak` to `compute_lift_force()`/`solve_em()`.
  Do NOT manually multiply F_z by 2.0 (that pattern was removed 2026-07-10, WP-PEAK).
  This repo has already shipped this bug twice at overlooked call sites — grep for
  `compute_lift_force(` whenever touching it.

## Key physics points (see docs/physics.md)
- Heat source q = ½·σ·ω²·|A_φ|² [W/m³] (cycle-averaged). NOT |∇T|²/σ.
- Solve EM as a PHASOR once; do NOT time-step 50Hz inside the thermal loop.
- σ(T)=σ0/(1+α(T-T0)), α≈3.9e-3/K — runtime amplitude multiplier (sigma_tempco_per_K),
  no FEM re-solve. Bodies oppose: plate eddy ∝ σ, coil ohmic ∝ 1/σ.
- Skin depth in Al @50Hz ≈ 12mm ≫ 3mm plate → no fine through-thickness mesh.

## Current quantitative result (î=5A RMS, T_amb=20°C, payload OFF, domain ±500mm)
| Body | P [W] |
|---|---|
| Plate eddy (Al disc) | 25.81 |
| Iron core + ring eddy | 5.86 |
| Coil ohmic (inner 52.32 + outer 54.12) | 106.44 |
| **Total** | **138.11** |

B_max in iron = 0.66T (unsaturated). I²-check 3.998 ≈ 4.000. `validate_domain_size()`
PASSES, all diffs <1% (largest: P_plate 0.767%).

## Real-rig validation (HIKMICRO IR, 2026-06-23) — reference data
Two measured AC 50Hz operating points (`validation_data` in params.yaml): **190V→5A**
(main op point) and **270V→7.8A** (calibration anchor).
- **Session 1** (steady state @7.8A): inner coil **79°C** (hottest), outer coil 74°C,
  center core 45°C, separator 40°C, ambient 29°C.
- **Session 2** (ramp, NOT steady): inner/outer coil 60.75/56°C at t=450s, plus a
  timestamped outer-coil trajectory used to fit the coil's time constant.
- ⚠️ **Caveat:** disc + center-core IR readings are UNRELIABLE (shiny aluminium, wrong
  emissivity). Only the dark-varnished **coil** readings are trustworthy for calibration.

Calibrated lumped coil network (params.yaml `lumped_thermal`, current values):
`hA_inner=2.4744` / `hA_outer=2.8885` / `coil_C_scale=0.2241` → T_inner_ss≈79.00°C /
T_outer_ss≈74.00°C at 7.8A/29°C — exact match to Session 1, solved through the ACTUAL
nonlinear `TwinState` integrator by `refit_hA.py` (never a hand-derived linear formula;
that shortcut caused two separate refit bugs). Six calibration rounds so far, all
narrated in docs/CHANGELOG.md.

## Data (repo root)
- `levitation_height_team28.csv` — Table I from the problem PDF (t_ms, z_mm). LEVITATION
  height, not temperature; settles ~11.3mm. Validates EM/mechanics. Thermal data: TBD.
- `3D_model.stl` (~Ø340mm, meters, axisymmetric) — historical input to the deleted
  build_twin_html.py. `build_twin_html_fem.py` is fully procedural and no longer reads it.
- `mock_sensor_data.csv` — synthetic log so data_io.py is testable without hardware.
- Source PDFs (TeamProblem28.pdf / Aufgabenstellung) are NOT committed — keep locally.

## Validation strategy
1. EM reproduces ORIGINAL benchmark (`benchmark_team28_original`: 960/576, 20A, R=65mm,
   no iron) → lift force balances gravity at z≈11.3mm vs CSV. Then trust EM.
2. Switch to rig (1000/500, iron, 5A) → loss maps.
3. Losses → thermal solver (done) → T field. Validate vs sensors later.

## Code status — stable modules
All of these are done, verified, and have no open issues. Details → docs/CHANGELOG.md.

| File | What it is |
|---|---|
| `config.py` / `params.yaml` | Load/normalize. `Config.I_peak` (=I×√2), `dial_to_current_A`/`dial_to_voltage_V` (variac dial in degrees). |
| `thermal_solver.py` | Axisymmetric heat FEM. Energy balance 0.000% error. |
| `em_solver.py` | AC eddy solve. `compute_losses`/`compute_lift_force`/`check_saturation`/`solve_em_saturating` all take optional `I_amplitude`/`B_scale`. `run_rig_validation()` brackets F_gravity → z_eq≈11.7mm (⚠️ see OPEN QUESTIONS). |
| `rom.py` | ThermalROM. I²-scaling exact (4.000000), τ=4.07min @R=80mm. |
| `twin_core.py` | **SSOT time integrator** — dual-β disc, lumped coil/iron/air RC network, levitation spring-mass-damper + jitter. **numpy+stdlib only** (no config/em_solver/rom/matplotlib). `python twin_core.py` → 6/6 self-checks PASS. |
| `twin_model.py` | Heavy bridge: `resolve_active_plate`/`PlateCache`/`i_max_for`/`coeffs_from_live`/`build_plate_variant`. |
| `xval_twin.py` | Pins `twin_core.py` against the baked JS in `outputs/digital_twin_fem.html` (Playwright). **A** integrator match (abs 1e-9, 7 schedules); **B** bake freshness (rel 1e-6) — catches the "coefficient fixed but never rebaked" bug class that A structurally cannot. `python xval_twin.py` → PASS. |
| `digital_twin.py` | Interactive matplotlib twin. Imports `TwinState`/`SCENARIOS` from twin_core, the rest from twin_model — no second copy of the physics. |
| `extensions/digital_twin_pyvista.py` | Desktop 3D twin (PyVista/VTK, OPTIONAL ~400MB dep — hence `extensions/`, see layout rule). Same `TwinState`; geometry reuses `build_twin_html_fem.py`'s mesh builders verbatim. `--self-check` runs with no VTK installed. Run from repo root. |
| `build_twin_html_fem.py` | The FEM-accurate standalone AR twin (only active HTML builder). 100% procedural geometry, two-node coil thermal model, closed-form levitation, 4 live-swappable disc radii, Amps/dial dual input, live T_amb from Google Weather API. `--bake-key` gates the real key (default: placeholder). |
| `refit_hA.py` | Refits `lumped_thermal.hA_inner/outer` through the real `TwinState` integrator. params.yaml stays SSOT. |
| `visualize.py`, `sim_plates.py` | 2D→3D revolve/GLB export, cross-plate comparison. |
| `data_io.py` + `arduino/thermal_sensor.ino` | SensorReader (serial/mock) → `calibrate_from_file()` → `rom.calibrate_UA()`. Tested vs `mock_sensor_data.csv`. |
| `gen_qr.py` | QR → `outputs/qr_digital_twin.png`. Hosting URL still undecided. |

**Cross-cutting invariant:** `twin_core.py` and the HTML's baked JS implement the same
physics twice. Change one → change the other → `python xval_twin.py` must stay PASS.

## ⚠️ OPEN QUESTIONS
- **LIFT FORCE / z_eq mismatch** (since 2026-07-10, was VALIDATED before it).
  F_z(5A_rms peak, z=3.8mm) ≈ 4.10N ≫ F_gravity(163g)=1.60N — levitates with a big
  margin, but predicted z_eq = **11.7mm** (plate bottom) / **14.7mm** visible, whereas
  the real observed visible gap is **7–8mm** (2026-07-01) — a ~7mm mismatch. Prime
  suspect: the `mu_r=1000` placeholder is too high (open magnetic circuit, alloy
  unknown). Tested and RULED OUT: magnetic saturation — `compute_lift_force(...,
  saturating=True)` changes F_z by <0.1% and gives an identical z_eq (11.75mm both
  ways). **Do NOT treat z_eq as validated, and do NOT reverse-fit μᵣ to match the old
  gap** (explicit user decision — keep the measured data as-is).
- **`mu_r=1000` for iron_core/outer_iron_ring is unmeasured** (no B-H curve, no
  resistivity test). Needs a real measurement, or accept the gap mismatch above as a
  known model limitation.

## Open items / NEXT
- [ ] **NEXT, highest value: log a real coil+disc COOLDOWN curve and a properly
      timestamped heat-up ramp.** The whole `lumped_thermal` block (coil_C_scale,
      coil_G_wind, air_node_C/hA_far, G_iron_cond, hA_iron) is unidentifiable from the
      existing heat-up-only data, and the shared air node (T5) cannot be fitted without
      it. Also fits `coil_G_wind_W_per_K`/`convection_exponent` (order-of-magnitude
      only today). See docs/SENSOR_PLAN.md.
- [ ] **NEXT: sensor hardware build** (Arduino + MAX31855×2, docs/SENSOR_PLAN.md), log a
      real run, re-calibrate from it.
- [ ] PAUSED, not blocking: `run_benchmark_validation()` (original TEAM28, 20A, no iron)
      gives z_eq≈**14.5mm** vs 11.3mm expected (28% overshoot). Was 6.8mm/40% UNDERSHOOT
      until a missed WP-PEAK call site was fixed 2026-07-11 — that confirmed the RMS/peak
      bug was real and explains part of the old gap, but a 28% residual remains
      unexplained. Its 20A is the original problem's own convention, not a multimeter reading.
- [ ] PENDING data, not blocking: plate-vs-coil temperature ordering is only *tied* in
      the model (IR data implies the coil should be clearly hotter) — needs a real
      disc-bottom thermocouple reading.
- [ ] Other data gaps: 7.75–8A levitation-oscillation amplitude (fits WP-A's ζ damping
      law, which has an internal spec conflict — see docs/CHANGELOG.md); denser variac
      dial→I calibration table (only 3 anchor points today).
- [ ] Feature gap: annulus/hollow-disc geometry. 3 real discs sit in
      `plate_library_annulus_TODO` (r_out=55/r_in=27.5mm) but the solvers only mesh solid
      discs from r=0 — not wired in yet.
- [ ] Docs: `docs/REPORT_WHY_CUSTOM_CODE_DE.md` (German) is out of sync with
      `REPORT_WHY_CUSTOM_CODE.md` — commit 19e4161 added a "section 2.5" to the EN
      version only. Either port it or drop it.

## Conventions
- SI units; geometry entered in mm in params.yaml (code converts to m).
- Every new physics term needs an energy-balance / sanity check before use.
- **Secrets/API keys — NEVER commit, in this repo or any future one.** Real key values
  go ONLY in `local/` (entirely gitignored). Tracked source (*.py, params.yaml, …) must
  only ever contain a placeholder token (e.g. `__GOOGLE_WEATHER_KEY__`); a build-time
  loader substitutes the real value from `local/` and is the only thing allowed to read
  it. If a git-tracked build product that can bake a real key (i.e.
  `outputs/digital_twin_fem.html`) is regenerated locally, do NOT `git add`/`commit` it
  while it holds a real key — rebuild with the placeholder first. `.claude/settings.json`
  carries a `PreToolUse` hook on `git commit *` that greps the staged AND unstaged diff
  for known key patterns (currently `AIzaSy[0-9A-Za-z_-]{20,}`) and denies the commit;
  treat it as a backstop, not a substitute for the rule. Extend its regex whenever a new
  provider's key format is introduced.

## Token discipline (Claude Code)
- Broad multi-file searches → dispatch an Explore subagent; keep only its summary in the
  main context, never raw file dumps.
- Filter long shell output (`| tail -n 30`, `grep -E ...`) — never paste full
  test/build/Playwright logs into context.
- Read big files by line-range only. NEVER Read `outputs/digital_twin_fem*.html` whole
  (~1 MB baked JS) — grep for the marker/section instead.
- Debugging: root cause BEFORE any fix — reproduce → isolate → identify → verify
  (systematic-debugging skill). Symptom patches are failure.
- Before claiming done/fixed: run the verification command and show its output
  (verification-before-completion skill). Evidence before assertions.
