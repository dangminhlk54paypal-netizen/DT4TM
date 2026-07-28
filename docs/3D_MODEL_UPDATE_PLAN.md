# 3D Model Update Plan — Status (2026-06-23, second revision)

> ⚠️ **HISTORICAL DOCUMENT.** Translated to English on 2026-07-28, otherwise kept as
> written on 2026-06-23. Several of its "still open" items have since been closed —
> most importantly, the direct magnet test WAS carried out on 2026-07-10 and
> confirmed that **both** the centre core and the separator/iron ring are
> ferromagnetic, and the coil radii WERE re-measured with a ruler on the same date
> (superseding both the STL and the params.yaml values discussed below). For the
> current state see CLAUDE.md and `docs/QUICK_START_FOR_AGENTS.md`; for the full
> history see `docs/CHANGELOG.md`.

The original version of this file was a plan drafted by Gemini (see the git
history). What follows records EXACTLY what was done based on real data (the rig +
a HIKMICRO thermal camera, two measurement sessions on the same day), replacing that
older plan.

**Correcting a WRONG finding from the previous revision:** the first analysis claimed
the real walls in the STL were only ~23mm tall (z≈21-43mm). While digging deeper to
build the separator ring, that turned out to be WRONG — the "wall" triangles actually
have one vertex at z=-2mm and one at z=66mm (spanning the FULL height of the device);
the average centroid landing at ~20.7/43.3 was an artefact of very long, thin
triangles. The real walls at r≈25/59/79mm run the whole way from the bottom
(z=-2mm) up to near the top (z=66mm).

## DONE (✓)

### 1. Material colours — `build_twin_html_fem.py` (JS TEMPLATE)
- `STRUCT_RGB` changed from neutral grey → **wood brown** `[160,100,55]/255`
  (region 4 = wood base).
- Added `METAL_RGB = [170,175,185]/255` (passive white-grey metal).
- `paintMesh()`: region 4 (wood) uses `STRUCT_RGB`; region 3 (centre spacer) and
  region 5 (separator ring, see item 4) use `METAL_RGB` **STATICALLY** (no
  temperature-driven `writeRamp`); regions 1/2 (inner/outer coil) still use
  `writeRamp` (a live thermal scale, because these are the real heat sources).
  Rationale: both measurement sessions showed the centre core + separator ring at
  only 36-45°C versus 56-79°C for the coils → essentially passive, so colouring them
  on a thermal scale would be misleading.
- CSS2D label `'Iron Core'` → `'Center Spacer'`; added a `'Separator Ring'` label.
- Verified with Playwright (headless Chromium): no JS errors; the screenshot confirms
  brown wood and a static white-grey centre spacer + separator ring even while the
  outer coil is glowing red.

### 2. Documenting materials + real data — `params.yaml`
- `excitation.voltage_V`: 220 → **190** (real measurement: 190V→5A). `current_A`
  stays at 5.0.
- Added `coils.fill_factor: 0.6` (placeholder, noted as NOT yet used to change any
  formula).
- Added a `separator_ring` block (material suspected aluminium/oxide OR iron — see
  item B below, still open).
- Added a `validation_data` block with 2 datasets: `thermal_at_7p8A` (held at 7.8A
  for ~6 minutes, reaching steady state) and `thermal_ramp_test` (the second session,
  two stages 5A→7.75A, used to fit the thermal time constant — see item 3).
- `iron_core` + `separator_ring`: explicitly recorded that the magnet / lift-force
  test is **CIRCUMSTANTIAL, NOT conclusive** (see item B).
- `python config.py` parses cleanly after every edit.

### 3. Calibrating the coil thermal network (2 fitting rounds) — `params.yaml` (`lumped_thermal`)
- **Round 1** (steady state at 7.8A only: inner=79°C, outer=74°C): `hA_inner=2.2109`,
  `hA_outer=1.8889` W/K (up from the old hand-guessed 0.48/0.44). Matches the steady
  measurements EXACTLY.
- **Round 2** (adding the ramp-test data to fit τ as well — transient, not just
  steady state): round 1 predicted the transient ~10°C SLOWER than reality (e.g. 38°C
  predicted vs 48.5°C measured at t=300s). Added a `coil_C_scale=0.434` parameter
  (the coil's effective thermal mass is only ~43% of the pure-copper assumption —
  plausible, since the coil contains insulation and air gaps, and
  `wire_diameter_mm=1.2` may be the INSULATED diameter rather than the bare copper
  core) → refit jointly: `hA_inner=2.2479`, `hA_outer=1.8788`, residual error now
  ~2-5°C (versus ~10°C before). This is an EMPIRICAL fit from a single session whose
  timestamps were read back from a verbal account (estimated ±10s uncertainty) —
  treat τ as CORRECT TO WITHIN AN ORDER OF MAGNITUDE, not exact; a session with a
  real time log (not a recollection) is needed to refine it further.
- Cross-check at I_ref=5A (T_amb=20°C, the twin's baked ambient): predicts
  **T_inner≈40.5°C, T_outer≈38.5°C** (steady state; the 5A transient was not computed).
- `AIR.C_air` / `AIR.hA_far` are no longer hardcoded in the JS — they are read from
  `LUMPED.air_node`.

### 4. "Separator ring" — RENDERED using procedural geometry
The real STL has no surface at the gaps that `params.yaml` implies (25-28mm: 0
triangles; 43-46.5mm: 1 triangle — not enough to colour). Option **(a) generate new
geometry** was chosen: a `build_separator_rings()` function in
`build_twin_html_fem.py` creates 2 thin cylindrical shells (region 5) at exactly
those 2 gaps (taken from `iron_core`/`coils.inner`/`coils.outer` in cfg, not
hardcoded), spanning the FULL height from z=-2mm to z=66mm — matching the real wall
height of the adjacent centre spacer (read dynamically from the STL data, not
hardcoded), so it sits visually "level" with the centre core and outer coil.
Verified: the build prints "separator (procedural): 1920 tris" (2 rings × 960
triangles, neither ring empty); Playwright confirms no JS errors; a close-up
screenshot clearly shows the grey ring standing between the core and the coil, with
the "Separator Ring" label correctly placed.
**Note:** this is NEW geometry (not present in the original STL) and exists purely
for display — it does not affect the EM/thermal solver (which still uses
`plate_material`/`coils`/`iron_core` as before).

## STILL OPEN

### B. Iron vs aluminium for the centre core AND the separator ring — still NOT firmly confirmed
User observation: when current flows, the aluminium disc is pushed up (magnetic
force) → inferring that the centre core is iron. **This inference is NOT reliable**:
the force pushing the aluminium disc comes from eddy currents induced in the disc
itself reacting to the coil's time-varying magnetic field — this happens REGARDLESS
of whether the centre core is iron or aluminium (the core only shapes/amplifies the
field, it is not the object being pushed). A more direct and conclusive test: hold a
PERMANENT MAGNET against the core/separator ring WITH THE POWER OFF and see whether
it is attracted. Until that test exists:
- `iron_core.mu_r` STAYS at 1000 (do not disable iron).
- `separator_ring.mu_r` STAYS at 1.0 (the ramp-test notes call the separator ring the
  "outer iron core", but there was NO separate test for it — only the same inference
  made for the centre core).
- The thermal data (both sessions) cannot distinguish the two — the core + separator
  ring always run much cooler than the coils whether they are iron or aluminium
  (P_iron is only ~0.6-1.5W).

## NEXT PHASE (waiting on the direct magnet test + more measurements)

1. **DIRECT magnet test** (touch a permanent magnet to the centre core AND the
   separator ring with the POWER OFF) — far more conclusive than inferring from the
   disc's lift force. If both are attracted: keep `iron_core.mu_r=1000` and change
   `separator_ring.mu_r` → 1000 (consistent); if not: set both to `mu_r=1.0`. This
   requires editing em_solver.py (the EM core), which was deliberately NOT done in
   the last round, per the agreed scope limit.
2. **Apply a matte paint dot** to the aluminium disc + centre core + separator ring
   and re-measure with IR/thermocouple — IR readings on shiny metal are currently NOT
   trustworthy (true ε ~0.1 vs the camera's ε=0.91 → readings come out low); this
   applies to BOTH sessions, not just the first.
3. Re-measure at **190V/5A**, held long enough to reach steady state, and compare
   against the predicted T_inner≈40.5°C / T_outer≈38.5°C.
4. If a more accurate τ is wanted than the current `coil_C_scale=0.434`: repeat the
   ramp test with a REAL TIME LOG (Arduino / stopwatch writing numbers down, not
   recalled from memory) — the current timestamp-reading error (±10s) is the main
   remaining source of uncertainty.
5. Physically measure the coil radii on the rig (versus the current `coils.inner/outer`
   in params.yaml) — the STL and params.yaml do not fully agree on several radii, so
   CONFIRM with a real ruler rather than trusting either the STL or params.yaml.
6. ~~`build_twin_html.py` (the lumped-only version, not the main one) has NOT been
   synced with the procedural separator ring — only worth doing if the user still
   uses that file.~~ **Now moot: that file was deleted on 2026-07-02, commit
   ec64ec1 — this item no longer applies.**
