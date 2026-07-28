# AUDIT & FIX PLAN — 2026-07-04

> Translated to English 2026-07-28 (repo-wide EN pass). Content otherwise unchanged:
> this is a historical audit record, so its numbers are deliberately left as they
> were on 2026-07-04/10/11, including ones that later measurements superseded.

Results of a whole-system audit (3 parallel tracks: the physics solver chain, the 3D
HTML twin, and the integration/params/docs layer) plus a fix plan split into Work
Packages (WPs) so Sonnet agents can run them **in parallel per phase** (each WP owns
its own files and never touches another WP's files within the same phase).

> Severity convention: **HIGH** = genuinely wrong numbers/behaviour or a real
> security risk; **MED** = a contradiction/ambiguity likely to cause errors later;
> **LOW** = cleanup/docs.

---

## PART 1 — OVERALL ASSESSMENT

The system is fundamentally **correct in its physics core**: the following were
independently re-verified — q = ½σω²|A_φ|² matches the cycle-averaged formula; the
2πr weight is consistently present in the stiffness/load/convection-boundary terms of
both the EM and thermal solvers; the A_φ/r² term; the opposite coil sign; the
direction of σ(T) (eddy ∝ σ, applied only to the plate); I²-scaling exact at
4.000000; energy balance 6.7e-9%; the mm→m conversion and e-notation coercion are
clean; the q_e interpolation renormalises to conserve energy; `dial_to_current_A` in
Python and JS are the same clamped interpolation, with the JS reading from PARAMS
baked out of params.yaml (correct SSOT); `levStep`'s closed form is unconditionally
stable; `romStep` has substepping to guard against large dt; `fetchAmbientC` has an
AbortController timeout (so it cannot hang); history arrays are capped at 3600
points; the mesh topology of all 4 disc variants is identical (2160 vertices), so
buffer swapping is safe; `resetSim` resets the deep nodes too
(inner_deep/outer_deep/iron/air).

**But there are 5 genuine HIGH bugs** (table below) plus a cluster of input
ambiguities that the user/lab must settle (Part 4).

### Main defect table

| # | Sev | Location | Defect |
|---|-----|----------|--------|
| H1 | HIGH | working tree `outputs/digital_twin_fem*.html` + `.claude/settings.json` | **A real Google key is sitting in the working tree of a git-tracked file**; the commit-blocking hook only inspects `git diff --cached` → **`git commit -a` slips through** (exactly the current scenario: the change is unstaged) |
| H2 | HIGH | `em_solver.py` (`material()` → `compute_lift_force()`, `run_rig_validation()`) | The RMS current (`cfg.I=5.0`) is used as the **phasor amplitude** without the √2 factor → F_z is 2× too low; `run_rig_validation()` then prints the wrong conclusion "F_z cannot bracket F_grav" (0.844N < 1.598N) even though the real disc does levitate. The ×2 consequence is currently patched by hand at the caller (LEV_ANCHORS in build_twin_html_fem) — an implicit convention that is easy to double-apply or forget |
| H3 | HIGH | `build_twin_html_fem.py:672-685` + JS `selectPlateVariant()` | Multi-radius compare mode: `rom_params_v` is **missing 6 keys** (`B_max_iron, B_sat, saturated, I_em_ref, B_max, J_max`) → `Object.assign(ROM, v.rom)` keeps the old disc's values; the J_max/B_plate telemetry permanently mixes the physics of two discs after a disc switch; the iron-saturation badge (`tBmax`) only runs once at load and never updates |
| H4 | HIGH | `digital_twin.py:142-152` | The default disc name is assembled as `"Al Ø160mm"` (diameter) which does not match `plate_library` (`"Al Ø80mm"` = radius) → the R=80 ROM gets cached under the label `"Al Ø50mm"`, the RadioButtons show the wrong active disc, and the first click on that very label is a no-op |
| H5 | HIGH | `README.md:33` + docs | `build_twin_html.py` **has been deleted** (commit 5c8598d) but README/ARCHITECTURE/HANDOFF/3D_MODEL_UPDATE_PLAN/CLAUDE.md still instruct running it → the command fails immediately |
| M1 | MED | `params.yaml:228-234` | 5 of 6 `plate_library` entries use "Ø" for the **radius** ("Al Ø80mm" is really a Ø160mm disc); only the newest entry "Al Ø202mm" uses the diameter correctly — the naming contradiction leaks into the matplotlib UI and sim_plates |
| M2 | MED | `build_twin_html_fem.py:650` | `PLATE_VARIANT_RADII_MM = (50,65,80,101)` is hardcoded rather than read from `plate_library` → violates SSOT; editing params does not propagate to the HTML |
| M3 | MED | `build_twin_html_fem.py:~2041` | The heat-particle effect compares `sim.T` (initialised to T_AMB_JS, 29°C by default) against `ROM.T_amb` (=20°C, the physical value) → **heat particles rise off a cold coil at I=0 the moment the page opens** (a display contradiction) |
| M4 | MED | `build_twin_html_fem.py` lev_params vs params.yaml | The two z_decay fitting methods **disagree by ~1.5×**: R=80 uses 21.4mm (params.yaml, the F1/F_grav-crossing method) while every other radius uses `_lev_anchor()`'s F1/F5 (~13.6mm) → compare mode compares apples to oranges in gap-vs-current sensitivity. The real observation ("the gap barely moves at 7.75A") favours 13.6mm — needs a decision (OQ-4) |
| M5 | MED | `em_solver.py:246-340` | The saturation loop (`solve_em_saturating`/`check_saturation`) only considers `iron_core` and **ignores `outer_iron_ring`** — currently harmless (μ_r=1) but would silently go wrong if the ring were confirmed ferromagnetic and someone only changed μ_r. **[x] RESOLVED**: `solve_em_saturating` was generalised 2026-07-10 (commit aa9537c, Phase C — the ring was confirmed ferromagnetic the same day, see OQ-6); `check_saturation` (a separate reporting function that Phase C missed) was generalised 2026-07-11 by a second audit, see `docs/archive/2026-07-11_BUG_REGISTER.md` B3. |
| M6 | MED | `em_solver.py:54` | `z_fine_top` does not add `payload_model.thickness_mm` — a payload thicker than ~10mm would fall partly into the coarse mesh region with no warning |
| M7 | MED | README/ARCHITECTURE | Roadmap Phases 6a/6b are still `[ ]` although done; the file-size table is stale |
| M8 | MED | `build_twin_html_fem.py` JS | Hardcoded values that should come from params: the labels "Inner coil (1000t)"/"Outer coil (500t)" (4 places, not reading `cfg.coils.*.turns`), the 0.5mm jitter fade threshold, `T_COLOR_HI=125`, `CHART_WIN=600` |
| L1 | LOW | `params.yaml` | Dead blocks that no code reads: `separator_ring` (duplicates `outer_iron_ring`), `transient`, `units`; `validation_data` is reference documentation only (calibration constants are hand-derived, not auto-derived); `fill_factor: 0.6` is declared but not yet wired into any formula (correctly self-documented) |
| L2 | LOW | `thermal_solver.py:212` | `on_boundary()` is dead code |
| L3 | LOW | `CLAUDE.md` | 653 lines versus its own self-imposed ~200 budget — costs context every session |

---

## PART 2 — WORK PACKAGES FOR SONNET AGENTS

**Partitioning principle**: every WP within a phase owns a DISTINCT set of files (no
merge conflicts → safe to run in parallel). Phase 2 runs only after Phase 1 is
complete (because they share `build_twin_html_fem.py`). NO WP may edit `CLAUDE.md`
except WPF-DOCS (to avoid conflicts); each WP records its result at the end of this
file (the "Execution log" section).

Common standard for EVERY WP:
- Follow `CLAUDE.md` (token discipline, no hardcoded constants, never commit secrets).
- Before claiming completion: run the WP's verify command and paste the output
  (verification-before-completion).
- Do not commit — leave the diff for the user to review.

### PHASE 1 (4 parallel WPs)

---

#### WP-SEC — Patch the secret-scanning hook and keep real keys out of tracked files
**Files owned**: `.claude/settings.json` (do NOT touch build_twin_html_fem.py —
WP-HTML handles the builder side).
**Origin severity**: H1 (half — the other half is in WP-HTML).
1. Fix the `git commit *` PreToolUse hook: change the check from `git diff --cached`
   to checking **both** `git diff --cached` **and** `git diff HEAD` (catching the
   `git commit -a` case, where auto-staging happens after the hook runs). Keep the
   `AIzaSy[0-9A-Za-z_-]{20,}` regex and the deny mechanism.
2. (Optional, if the hook engine supports it) add a similar hook for `git push *`:
   grep `git log -p @{push}..HEAD -- .` (or `origin/main..HEAD`) for the same
   pattern, blocking the push if a key already made it into a commit.
**Acceptance / verify** (in a throwaway sandbox repo in the scratchpad, NOT the real repo):
- Create a fake repo with a tracked file containing a fake key matching the regex,
  UNSTAGED → `git commit -a` must be denied.
- Staged → `git commit` denied (the original regression still holds).
- Clean diff → commit allowed.

---

#### WP-HTML — Fix build_twin_html_fem.py: compare-mode telemetry, key gating, display contradiction, SSOT
**Files owned**: `build_twin_html_fem.py`, `outputs/digital_twin_fem.html`,
`outputs/digital_twin_fem_R101.html`. (Do NOT touch params.yaml — if a new display
key is needed there, coordinate: WP-PARAMS adds the key and WP-HTML reads it with
`.get(key, default)` so it does not depend on merge order.)
**Origin severity**: H1 (builder half), H3, M2, M3, M8.
1. **Key gating (H1)**: add a `--bake-key` CLI flag. By default (no flag): ALWAYS
   write the placeholder `"YOUR_KEY_HERE"` into the HTML, even when
   `local/.env.local` exists. Only `--bake-key` embeds the real key (for local
   deploy/test). Print a clear warning when the real key is baked.
2. **Compare-mode stale telemetry (H3)**: `solve_plate_variant()` must return, in
   `rom_params_v`, every key the main build bakes into `rom_params`
   (`B_max_iron, B_sat, saturated, I_em_ref, B_max, J_max` — computed per-variant
   from that variant's OWN EM solve, NOT copied from the main build). In JS: collect
   the `tBmax`/saturation badge-setting block (currently run once at load, ~lines
   2472-2477) into an `updateEmBadges()` function called both at init AND inside
   `selectPlateVariant()`.
3. **Idle heat particles (M3)**: at line ~2041 change `ROM.T_amb` → `T_AMB_JS`
   (consistent with every other "hot" indicator in the file).
4. **Radius SSOT (M2)**: drop the hardcoded `PLATE_VARIANT_RADII_MM` tuple; derive
   it from `cfg.raw["plate_library"]` (filter material=aluminium, thickness 3mm,
   unique `radius_mm`, sorted). Note: the r=100.0 entry currently in plate_library
   will add an extra Ø200mm button — that is acceptable (it is the point of SSOT),
   but verify mesh/telemetry with 5 variants instead of 4.
5. **JS hardcoding (M8)**: coil labels "(1000t)"/"(500t)" (4 places) → format from
   `cfg.coils["inner"]["turns"]`/`["outer"]["turns"]` at bake time. `T_COLOR_HI=125`
   → read `cfg.raw["levitating_disc"].get("plate_hot_display_C", 125.0)` (key added
   by WP-PARAMS). The 0.5mm jitter fade threshold → `PARAMS.lev` (key `jit_fade_mm`,
   default 0.5). `CHART_WIN`, `N_HEAT_PARTICLES`, `N_THETA_FIELD` stay literal with a
   comment "cosmetic, deliberately hardcoded".
6. Rebuild BOTH HTML files (default, no `--bake-key`).
**Acceptance / verify**:
- `grep -c 'AIzaSy' outputs/digital_twin_fem*.html` → 0 in both files.
- Headless Playwright on both files: 0 JS errors; cycle through ALL disc-variant
  buttons and assert `ROM.J_max`/`ROM.B_max`/the tBmax badge CHANGE per variant
  (compare against the values baked into `PARAMS.plate_variants[i].rom`).
- At I=0 after load: no heat particles displayed (check the `hot` variable === false).
- Regression: `levGapEqMm(5)` = 4.1000 (R=80 build), `I_LEV_MIN` = 4.543A (R=80)
  / 6.450A (variant r=101) unchanged.

---

#### WP-PARAMS — Clean up params.yaml + fix digital_twin.py plate matching
**Files owned**: `params.yaml`, `digital_twin.py`, `sim_plates.py` (if needed).
**Origin severity**: H4, M1, L1.
1. **Rename plate_library by true DIAMETER (M1)**:
   `Al Ø100mm`(r=50), `Al Ø130mm`(r=65), `Al Ø160mm`(r=80), `Al Ø200mm`(r=100),
   `Al Ø202mm`(r=101, unchanged), `Cu Ø160mm`(r=80). Add a convention comment
   "Ø = diameter, radius_mm = radius". Note Ø200 and Ø202 are very close together —
   flag the distinction in the entry comment itself.
2. **digital_twin.py (H4)**: drop the `default_name` string concatenation; match the
   default entry by `radius_mm == cfg.geometry.plate_radius_m*1e3` (tolerance 1e-6)
   **and** material — cache the ROM and initialise the RadioButtons from the entry
   that actually matches. After the fix: opening the app must show "Al Ø160mm"
   pre-selected, and the first click on "Al Ø100mm" (r=50) MUST rebuild the ROM (no
   longer a no-op).
3. **Remove dead blocks (L1)**: delete `separator_ring:` (duplicates
   `outer_iron_ring`). Add a comment at the top of `validation_data:` —
   "REFERENCE-ONLY: no code reads this; the lumped_thermal calibration constants are
   hand-derived". The `transient:` block: wire it into `digital_twin.py`'s argparse
   (`--dt`/`--window` defaults read from here) rather than deleting it.
   `units:`/`fill_factor` stay (they are already correctly self-documented).
4. Add display keys for WP-HTML: `levitating_disc.plate_hot_display_C: 125.0` and
   `levitation.jit_fade_mm: 0.5` (comment: display-only).
**Acceptance / verify**:
- `python config.py` runs cleanly and prints the dial→I table as before.
- A `python -c` smoke test: load params, assert the new plate_library names, assert
  the `separator_ring` key is gone.
- `python digital_twin.py` smoke test on the Agg backend (as the old WP described in
  CLAUDE.md): no exception; assert `state["plate_name"] == "Al Ø160mm"`.
- `python sim_plates.py --no-em` runs cleanly with the new names.

---

#### WP-DOCS — Synchronise the documentation with the actual code
**Files owned**: `README.md`, `docs/ARCHITECTURE.md`, `docs/HANDOFF.md`,
`docs/archive/2026-06-23_3D_MODEL_UPDATE_PLAN.md`. (Do NOT touch CLAUDE.md in this phase — the
CLAUDE.md entry is updated last by the user/main agent to avoid conflicts.)
**Origin severity**: H5, M7, F9.
1. Remove/fix every reference to `build_twin_html.py` that reads as if it still runs
   (README run-list + layout, ARCHITECTURE tree + command table, HANDOFF,
   3D_MODEL_UPDATE_PLAN) — leave a one-line note: "deleted 2026-07-02, superseded by
   build_twin_html_fem.py".
2. README roadmap: Phases 6a/6b → `[x]` (citing `validate_domain_size()`).
3. ARCHITECTURE: drop the file-size column (or update it to 853KB and note "this
   will drift").
4. Quickly check that the remaining README commands match reality (cross-reference
   the smoke table in Part 3 below).
**Acceptance / verify**: `grep -rn 'build_twin_html\.py' README.md docs/ | grep -v fem`
should only return the deletion note; every command in the README must correspond to
a file that exists.

### PHASE 2 (after Phase 1 merges — 1 WP, because it shares em_solver + build_twin_html_fem)

---

#### WP-PEAK — Standardise the RMS/peak convention in the lift force (H2, M5, M6, L2)
**Files owned**: `config.py`, `em_solver.py`, `thermal_solver.py`,
`build_twin_html_fem.py` (the LEV_ANCHORS/_lev_anchor part), rebuild outputs.
**THIS IS THE MOST SENSITIVE WP — hard constraints:**
- Current convention: the THERMAL chain (compute_losses → hA calibration)
  deliberately uses RMS-as-amplitude, and the ×2 error has been absorbed into hA —
  **ABSOLUTELY DO NOT change P_plate/P_coil/q_e** (P_plate(5A) must stay 9.67W,
  P_coil 128.17W).
- The FORCE chain currently has to be multiplied by ×2 by hand at the caller
  (LEV_ANCHORS was computed with that factor).
1. `config.py`: add a property `I_peak = I * sqrt(2)` (+ a docstring stating the convention).
2. `em_solver.py`: `compute_lift_force()` and `run_rig_validation()` (and
   `_compute_B_per_element`/`check_saturation` for the true B) must use the peak
   amplitude — the cleanest approach: an `I_amplitude=None` parameter in the solve;
   the force path passes `cfg.I_peak`, the loss path keeps `cfg.I` unchanged. Delete
   the hand-patched `*2.0` factors at EVERY force caller (grep the whole repo for
   `2.0` near F_z, `_lev_anchor`, LEV_ANCHORS in build_twin_html_fem.py, docstrings)
   — and check for NO double-correction: the anchor values after the refactor must
   match the previously-correct numbers (F(5A,1mm)≈1.85N, z_eq≈4.1mm,
   I_min_lev(r101)=6.45A).
3. After the fix, `run_rig_validation()` must bracket F_grav and print z_eq≈4.1mm.
4. **M5**: add a guard to `solve_em_saturating`/`check_saturation`: if
   `outer_iron_ring.mu_r > 5` but the saturation loop does not consider that region,
   print a clear WARNING (or generalise the loop to both iron regions).
5. **M6**: `z_fine_top` must add `payload.thickness_mm` when the payload is enabled.
6. **L2**: delete the dead `on_boundary()` in thermal_solver.py.
7. Rebuild both HTML files (without `--bake-key`) and re-run the Playwright
   regression as in WP-HTML.
**Acceptance / verify**:
- `python em_solver.py` full run: I² check passes; P_plate(5A)=9.67W UNCHANGED;
  `run_rig_validation()` brackets correctly, z_eq≈4.1mm; benchmark z_eq≈7.1mm
  unchanged (the PAUSED item keeps its status).
- `python thermal_solver.py` energy balance 0.000%.
- `python rom.py` I²-scaling 4.000000.
- HTML: `levGapEqMm(5)`=4.1000, per-variant `I_LEV_MIN` unchanged, 0 JS errors.

### PHASE 3 (optional, requires user approval first)

- **WP-TRIM**: restructure CLAUDE.md (653 lines → <250): keep the current state and
  move the WP-A/B/C/D narrative + calibration history into `docs/CHANGELOG.md`. Only
  run this with the user's agreement (CLAUDE.md is the team's memory).
- **WP-Z0**: unify the z_decay method (M4 / OQ-4) — AWAITING the user's decision (see
  Part 4, question 4). If the F1/F5 method (13.6mm) is chosen: change
  `levitation.z_decay_mm` in params.yaml, verify that the predicted gap(7.75A) drops
  from ~22.9mm to a "barely moves" level matching the observation, and update the comment.

### Suggested ways to run this automatically

- **In parallel**: in Claude Code, spawn 4 Sonnet agents (general-purpose subagent,
  `isolation: worktree` if separate diffs are wanted) with the prompt = the contents
  of each Phase 1 WP above + "read docs/archive/2026-07-04_AUDIT_FIX_PLAN.md section WP-xxx,
  stay exactly in scope, record the result in the Execution log". Merge/review, then
  run WP-PEAK (Phase 2) on its own.
- **Loop**: `/loop` with the prompt "carry out the next not-yet-done WP in
  docs/archive/2026-07-04_AUDIT_FIX_PLAN.md in phase order, one WP per iteration, running the
  verify step before marking it done" — slower but needs no merging.

---

## PART 3 — ENTRYPOINT SMOKE MATRIX (current status)

| README command | Result |
|---|---|
| `python config.py` / `em_solver.py` / `thermal_solver.py` / `rom.py` | OK |
| `python digital_twin.py` | Runs, but hits H4 (wrong disc label + no-op click) |
| `python visualize.py --no-show` / `sim_plates.py` | OK |
| `python build_twin_html.py 3D_model.stl` | **FAIL — file deleted (H5)** |
| `python build_twin_html_fem.py [--plate-radius 101]` | OK (the STL argument is a deliberate no-op) |
| `python data_io.py --mode calibrate --csv mock_sensor_data.csv` | OK |
| `python gen_qr.py <url>` | OK (hosting URL still TBD) |

requirements.txt matches the actual imports (pyvista being optional is deliberate).
`3D_model.stl` and `mock_sensor_data.csv` exist and have the right schema.

---

## PART 4 — QUESTIONS FOR THE USER/LAB TO ANSWER (not delegated to agents)

Merged from `docs/archive/2026-07-02_PLAN_SIM_FEEDBACK.md` + new findings from this audit:

1. **The real gap at 7.75A** (in mm, or as "× the disc thickness")? — fill in
   `Z_OBS_7_75A_MM` to refit z_decay. The model currently predicts ~22.9mm; the
   observation says "it barely moves".
   ⚠️ **Partly superseded 2026-07-10**: the geometry re-measurement + iron
   confirmation that day changed the EM picture entirely (the disc now overlaps the
   iron ring), and the predicted z_eq(5A) jumped 4.1mm→11.7mm — the old z_decay
   figures (fitted on the previous geometry) need re-deriving on the new geometry
   before this answer can be used. See also the CLAUDE.md "LIFT FORCE" bullet and
   `docs/archive/2026-07-11_BUG_REGISTER.md` WP-7 (iron saturation has been ruled out as the
   cause; it does NOT explain the gap).
2. **The ζ (damping) conflict**: the ζ∝I² law (anchored at ζ(5A)=0.02, matching the
   ~9s settle) only gives ζ(7.75A)≈0.048, whereas WP-A's own <40% overshoot target
   demands ~0.3. Choose: relax the target / change the damping law / wait for real
   7.75-8A oscillation data.
3. **Real cooldown data**: hold 5A until steady → cut the current → log the coil IR
   every 60s for 20-30 minutes (to fit `coil_G_wind_W_per_K` +
   `convection_exponent` — currently only order-of-magnitude).
4. **Choose the z_decay method** (M4): 21.4mm (F1/F_grav-crossing, currently used for
   R=80) vs 13.6mm (F1/F5, currently used for EVERY other radius) — a 1.5×
   discrepancy for the SAME disc. The audit's recommendation: the observation in
   question 1 favours the smaller value (13.6mm) → if confirmed, run WP-Z0. Gap
   measurements at ≥3 current levels would settle it definitively.
   **[x] The user decided on 2026-07-10 (WP-Z0)**: 13.6mm chosen and applied in
   params.yaml. See the "supersede" note in question 1 — the geometry changed later
   the same day, so the decision stands but the absolute z_eq has shifted.
5. **The Ø202mm disc**: the simulation says it does NOT levitate at 5A (needs
   ≥6.45A) — is a real disc going to be made to test this, or do we stay with Ø160mm?
6. **Magnet test for the separator ring (r=81-101mm)** — still PENDING; if it is
   ferromagnetic then P_plate/F_z change substantially (a μ_r sensitivity test
   already exists) and all R=101 results must be recomputed. **[x] RESOLVED
   2026-07-10**: the user re-tested and confirmed that BOTH the centre core AND
   `outer_iron_ring` are ferromagnetic (attracted to a magnet); the ring's position
   was also re-measured (now r=64.9-79.9mm, no longer 81-101mm). P_plate and F_z have
   been recomputed on the new geometry — see CLAUDE.md "Device numbers" + "First
   quantitative result".
7. **Disc-vs-coil temperature ordering**: the model currently ties them, while the
   real IR clearly says the coil is hotter — needs a contact thermocouple on the disc
   underside (the disc's h_top/h_bottom have never been calibrated). (Black tape with
   ε≈0.95 stuck to the disc underside is the cheapest fix for IR.)
8. **EM mesh sensitivity**: changing fine_step 2.0→1.0mm shifts z_eq(R=80) from 4.15
   to ~3.5mm and I_min_lev(R=101) from 6.45 to 6.9A — the "validated" 4.1mm figure is
   more mesh-sensitive than assumed, which also bears on the PAUSED 37% benchmark.
   Decision needed: reopen that investigation or not?
9. **(New) Lock down the Google API key**: the current key has NO referrer/IP
   restriction — go into the Google Cloud Console and add one (or switch to a
   project-scoped key) before shipping/hosting the HTML file.

---

## EXECUTION LOG (agents record results here)

| WP | Agent/model | Status | Verify output (summary) | Date |
|----|-------------|--------|--------------------------|------|
| WP-SEC | Sonnet (parallel, shared tree) | DONE | The hook now checks both `git diff --cached` and `git diff HEAD`. Verified in a sandbox (`scratchpad/hook_test`): unstaged key → deny (the original bug reproduced then fixed); staged → deny (regression); clean → allow. Side-finding: independently confirmed once more that `outputs/digital_twin_fem.html` had a real key in the unstaged diff at the time of the run. Only `.claude/settings.json` was modified. | 2026-07-10 |
| WP-HTML | Sonnet (parallel, shared tree) | DONE | (1) `--bake-key` flag added, default writes `YOUR_KEY_HERE`; verified `grep -c AIzaSy` = 0 in both files. (2) `solve_plate_variant()` now computes all 6 missing keys (B_max_iron/B_sat/saturated/I_em_ref/B_max/J_max) per-variant; `updateEmBadges()` called both at load and inside `selectPlateVariant()`; verified that cycling 5 variants changes ROM.J_max to match the baked PARAMS. (3) The hot-particle check changed `ROM.T_amb`→`T_AMB_JS`; verified hot=false at I=0. (4) The hardcoded `PLATE_VARIANT_RADII_MM` was removed and derived from plate_library → 5 variants (50/65/80/100/101mm) instead of 4. (5) turns labels/T_COLOR_HI/jit_fade_mm now read from PARAMS/.get(default). (6) Rebuilt both HTML files (without --bake-key) — 0 JS errors under headless Playwright, regression levGapEqMm(5)=4.1000/I_LEV_MIN=4.543A(R80)/6.450A(R101) unchanged. Re-rebuilt one final time by the orchestrator AFTER WP-PARAMS finished, to ensure params.yaml's final state (the new plate names) was baked correctly — both files pass key-check=0 again. Only build_twin_html_fem.py + the 2 HTML outputs were modified. | 2026-07-10 |
| WP-PARAMS | Sonnet (parallel, shared tree) | DONE | plate_library renamed by true diameter (Ø100/130/160/200/202mm + Cu Ø160mm); added the Ø=diameter convention comment plus a Ø200-vs-Ø202 warning. digital_twin.py: the default plate is now matched by radius_mm+material (tolerance 1e-6) instead of the incorrectly-assembled string — verified the suptitle reads "Al Ø160mm". Deleted `separator_ring:` (grep confirmed no code reads it). Added the REFERENCE-ONLY comment to validation_data. Wired `transient:` (dt_s/t_end_s) into digital_twin.py's argparse --dt/--window (same values as the old hardcoded 1.0/600.0). Added `levitating_disc.plate_hot_display_C=125.0` + `levitation.jit_fade_mm=0.5`. Verify: config.py clean, smoke test of the new names, Agg-backend run_live() with 0 exceptions, sim_plates.py --no-em clean. Only params.yaml + digital_twin.py modified (sim_plates.py needed no change — already generic). | 2026-07-10 |
| WP-DOCS | Sonnet (parallel, shared tree) | DONE | Fixed 6/6 `build_twin_html.py` references into deletion notes (README:37,56; ARCHITECTURE:24,153; HANDOFF:78; 3D_MODEL_UPDATE_PLAN:102). README Phases 6a/6b → [x] (confirmed `validate_domain_size()` exists). ARCHITECTURE file-size table: dead row removed, added a "sizes drift" note. Verify: the remaining grep hits are 100% historical notes, none of which read as a runnable command. Only 4 docs files modified, CLAUDE.md untouched (confirmed). Additional flag (not fixed, out of scope): `docs/ARCHITECTURE.md`'s Generated-files tree (~line 47) still mentions the old `digital_twin.html`, which should probably be cleaned up later too. | 2026-07-10 |
| WP-PEAK | Sonnet (solo, after Phase 1) | DONE | New `config.I_peak`; `material/solve_em/solve_em_saturating/compute_lift_force` gained `I_amplitude` (default None = byte-identical old behaviour); `run_rig_validation()` now brackets F_grav and prints z_eq=4.1mm (plate bottom) + visible gap=7.1mm MATCH; `run_benchmark_validation()` UNCHANGED (z_eq=7.1mm identical, verified). `check_saturation` gained `B_scale` (default 1.0, no change to the internal Picard loop); the 3 reporting call sites (`em_solver.py __main__`, 2 places in `build_twin_html_fem.py`) use `B_scale=cfg.I_peak/cfg.I` → "MAX B in iron" 0.033T→0.047T (correctly ×√2). `_lev_anchor()` dropped the `current_A` mutation hack in favour of a clean `I_amplitude=cfg.I_peak` — every field re-verified as a 100% match against the old `LEV_ANCHORS` cache. M5: added a WARNING guard if `outer_iron_ring.mu_r>5` while the Picard loop ignores it (currently harmless since mu_r=1). M6: `z_fine_top` adds `payload.thickness_mm`. L2: deleted the dead `on_boundary()`. Verify: `P_plate(5A)=9.6727W`/`P_coil=128.169W` bit-identical; I²=4.000000; energy balance 0.000%; both HTML files rebuilt + Playwright: `levGapEqMm(5)=4.1`, `I_LEV_MIN` correct in both builds, 0 JS errors. **Out-of-scope side-finding**: `validate_domain_size()` currently FAILS (2.71% > the 1% tolerance) — reproduced on unmodified HEAD, confirming this PRE-DATES WP-PEAK (not caused by today's changes), but it makes CLAUDE.md's "PASS <0.06%" claim stale — the domain size needs re-verifying in a later session. | 2026-07-10 |
| WP-TRIM | Sonnet (solo, after user approval) | DONE | CLAUDE.md 780→224 lines (under the 250 threshold). The entire historical narrative (every render-fix session, both calibration rounds, WP-A/B/C/D/PEAK) moved intact into `docs/CHANGELOG.md` (651 lines, no information lost). "Code status" in CLAUDE.md is now compact current-state only (1 paragraph per component + a pointer to the CHANGELOG). Fixed along the way: the CURRENT CONVENTION bullet updated for the new `cfg.I_peak` API (WP-PEAK), dropping the obsolete "multiply by 2.0 manually" instruction; the Real-rig validation section condensed (final numbers kept, the two-round narrative dropped); fixed one leftover `build_twin_html.py` reference inside CLAUDE.md (WP-DOCS had only touched README/docs/, not CLAUDE.md). | 2026-07-10 |
| WP-Z0 | Sonnet (solo, after the user settled OQ-4) | DONE | The user chose the F1/F5 method (13.6mm) via AskUserQuestion — confirming that the real rig observation "the gap barely moves" at 7.75A matches the smaller value. Changed `levitation.z_decay_mm` 21.4→13.6 in params.yaml (with a comment explaining the decision), updated the fallback default in `lev_params()` in Python plus the related JS comment. Verify: the predicted z_eq(7.75A) drops exactly as hand-calculated: 22.86mm→16.02mm; `levGapEqMm(5)`=4.1 UNCHANGED (correct, since z_gap_5A_mm did not change); `I_LEV_MIN`(R80) changed 4.543→4.300A (AS EXPECTED — an unavoidable consequence of changing z_decay, not a regression); `I_LEV_MIN`(R101)=6.450A UNCHANGED (correct — it uses its own anchor via `_lev_anchor()` and does not depend on R=80's z_decay). Both HTML files rebuilt, 0 JS errors. | 2026-07-10 |
| AUDIT-0711 | Sonnet (solo, second-pass audit) | DONE | The user suspected the 2026-07-10/11 updates (geometry re-measurement, iron confirmation, Phases A-D) had introduced bugs. Three Explore agents ran in parallel (EM chain / thermal-ROM chain / HTML+docs) before any fix. Full results: `docs/archive/2026-07-11_BUG_REGISTER.md`. Summary: 1 genuine numerical bug (Phase B's hA refit used the wrong AIR_DT_SS formula; fixed hA_inner 3.0605→2.9493 / hA_outer 3.5986→3.4509, hand-verified against 79.00/74.00°C); 2 latent bugs in em_solver.py (`compute_losses` could drop the iron-ring loss if the core were disabled; `check_saturation` was not generalised to the ring the way Phase C had generalised the solver) — both fixed, with P_plate/P_iron/P_coil verified bit-identical before/after; plus a sweep of stale comments (M5 above, old radii, the old ×2.0 convention). WP-6 (testing coil_C_scale, held unchanged, RMS=2.56°C) and WP-7 (adding a `saturating=` kwarg to `compute_lift_force`; the experiment showed saturation does NOT explain the lift-force mismatch — F_z changes <0.1%, z_eq invariant at 11.75mm) are both report-only and change no defaults. Rebuilt `outputs/digital_twin_fem.html` after the hA fix. Marked OQ-6 resolved, noted the partial supersede of OQ-1/OQ-4 above. CLAUDE.md/CHANGELOG.md synchronised. Verify: I²=3.998, energy balance 0.000%, ROM I²=4.000000, domain validation PASS. | 2026-07-11 |
