# PLAN — 3D simulation upgrades from real-rig feedback (2026-07-02)

> Translated to English 2026-07-28 (repo-wide EN pass). Content otherwise unchanged:
> this is a historical planning record, so its numbers are deliberately left as they
> stood on 2026-07-02, including ones that later measurements superseded (most
> notably the iron-ring position/material and every levitation-gap figure).

Split into **4 work packages (WP-A..D)** for 3–4 Sonnet agents to run in parallel.
Each WP is self-contained: root cause, physical design, code location, steps, and
acceptance criteria. Read CLAUDE.md before starting.

> **IMPORTANT — conflict avoidance:** all 4 WPs touch `build_twin_html_fem.py` but in
> DIFFERENT REGIONS (see the "Conflict map" at the end of this file). Each agent works
> in its **own git worktree**, merging in the order: **WP-C → WP-B → WP-A → WP-D**.
> WP-D is the integrator and final tester.

---

## Background — 3 pieces of feedback from observing the real rig

1. **Levitation oscillation is wrong**: (a) turning up the time-speed slider does NOT
   speed up the oscillation; (b) in reality the disc rattles from ~0.1A, vibrating
   more strongly through 1→3A before it finally lifts — the current simulation sits
   perfectly still below 4.54A; (c) after settling at 5A, going up to 7.75–8A only
   nudges the gap slightly and the oscillation is much SMALLER than at lift-off — the
   current simulation oscillates equally strongly at all times.
2. **The coil cools far too quickly**: a hot wire takes a VERY long time to cool in
   air; the current first-order RC model gives τ_cool = τ_heat (~350s) — unrealistic.
3. **Disc radius**: currently R=80mm (Ø160mm). We want a larger disc covering all the
   way to the outer edge of the separator ring (r=101mm) → an **R=101mm (Ø202mm)** disc.

---

## WP-A — Levitation oscillation physics (agent 1)

> **STATUS: DONE (2026-07-02).** See CLAUDE.md Code status → the "WP-A" entry for full
> results. Summary: `levStep` switched to a closed-form solution + sim-time (the speed
> slider now works correctly), sub-lift-off jitter added, ζ(I) now follows I².
> **2 open questions remain unanswered** (see "Questions for the user to answer" at the
> end of this file) — not blocking; the code has placeholders ready.

### Root cause (verified in the code)
- `build_twin_html_fem.py` lines ~1150–1170: the oscillation is a **spring-mass system
  linearised around z_eq**: `m·z̈ = mω²(z_eq−z) − 2ζω·m·ż` with
  `LEV_OMEGA = √(g/z0) ≈ 21.4 rad/s` and a constant `LEV_ZETA = 0.02`.
- Line ~1998: `levStep(I_display, wall_dt)` — integrated against **wall-time** (the
  comment says this is deliberate). This is why the speed slider has no effect.
- Line ~1163: when `I < I_LEV_MIN (4.54A)`, `lev.z=0, lev.v=0` is hard-set → no
  vibration below the lift-off threshold.

### New physical design
1. **Integrate in sim-time**: call `levStep(I_display, dt_sim)` instead of `wall_dt`.
   Because at 200× speed `dt_sim ≈ 3.3s/frame` while ω=21 rad/s, do NOT use Euler
   substepping (it would need ~700 substeps/frame) — use the **closed-form solution**
   of the under-damped oscillation each frame instead (exact, unconditionally stable):
   ```
   z(t+dt) = z_eq + e^(−ζωdt)·[ (z−z_eq)·cos(ω_d dt) + ((v+ζω(z−z_eq))/ω_d)·sin(ω_d dt) ]
   ω_d = ω√(1−ζ²)
   ```
   (update v correspondingly by differentiating the expression above). Keep the
   floor-contact clamp `z ≥ 0`.
2. **Sub-lift-off vibration (0.1A → I_min)**: the instantaneous AC force
   `F(t) ∝ i(t)² = I²·(1−cos(2ωt))/2` → a **100 Hz** beat component. The disc sitting
   on the coil rattles. 100Hz cannot be rendered at 60fps → simulate it with a
   **physical jitter amplitude**: when `lev.z < 0.5mm` and `I > 0.05A`, add a display
   displacement `A_jit·sin(φ₁)+0.5·A_jit·sin(φ₂)` using 2 fast, non-synchronised
   phases (an aliased shimmer), with amplitude:
   ```
   A_jit(I) = JIT_MM · (I / I_ref)²     (JIT_MM ≈ 0.3 display-mm, clamped ≤ 1mm)
   ```
   → a tiny rattle at 0.1A, a clear one at 3A, fading away smoothly as the disc lifts
   (fade by `max(0, 1 − lev.z/0.5)`).
3. **Damping rising with current** (eddy-current damping ∝ B² ∝ I²):
   ```
   ζ(I) = ζ0 + ζ1·(I/5)²    with ζ(5A) ≈ 0.02 (keeping the ~9s settle at lift-off),
                             ζ(7.75A) ≈ 0.05–0.08
   ```
   → stepping the current 5→7.75A gives a smaller oscillation that damps out much
   faster than at lift-off, matching the observation.
4. **OPEN CALIBRATION — ask the user**: the current model `z_eq(I)=4.1+2·z0·ln(I/5)`
   with `z0=21.4mm` gives gap@7.75A ≈ 22.9mm (a VERY large lift), but the user observes
   the gap only "rises a little". `Z_DECAY_MM` is most likely too large. The agent's
   job: write the refit formula `z0 = (z_obs − 4.1)/(2·ln(7.75/5))` and LEAVE A
   PLACEHOLDER for `z_obs` (the real gap at 7.75A, which the user can estimate in mm
   or as "× the disc thickness"). Note: ω = √(g/(z0·1e-3)) changes with it → update
   them together.
5. **(Optional, do last)**: decorative spin — add `lev.spin` (rad/s) decaying slowly
   (τ~60s), triggered by a small "Poke disc" button in the panel; the disc rotates
   about the Y axis while spin ≠ 0. Only if there is time left.

### Code region
JS: the "Levitation gap physics" block (~lines 1129–1170), its call in the render loop
(~lines 1995–2000), the gap telemetry (~lines 2020–2022). Do NOT touch `romStep`, do
NOT touch the Python geometry.

### Acceptance (headless Playwright, the pattern already exists from earlier sessions)
- 0 JS console errors.
- Speed 1× vs 10×: the wall-clock settle time of the oscillation after a current step
  must be ~10× shorter at speed 10×.
- I=0.5A: visible disc jitter (measured via `twinDebug` / position sampling);
  I=0: perfectly still.
- Stepping 5→7.75A after settling: peak overshoot < 40% of the 0→5A step's overshoot
  (normalised by the step amplitude).
- The settled `lev.z` still matches `levGapEqMm(I)` to ±0.05mm.

---

## WP-B — More realistic coil cooling (agent 2)

> **STATUS: DONE (2026-07-02).** See CLAUDE.md Code status → the "WP-B" entry.
> Summary: nonlinear convection (h~ΔT^0.25) + a 2-node coil (surface/winding-core,
> `coil_G_wind_W_per_K=1.0`) implemented and refitted from scratch. Ramp-test RMS=2.5°C
> (better than even the old claim), cooldown ~6-8× slower than the old model.
> Steady state unchanged (verified). **Side finding**: the old model (pre-WP-B)
> actually had RMS=6.6°C on `thermal_ramp_test`, not the ~3°C the old documentation
> claimed — that claim was stale, probably having drifted after iron contact-conduction
> was added without a re-check. There is still no real COOLDOWN data to fit
> quantitatively — see the questions at the end of this file.

### Root cause
`romStep()` (~lines 996–1035): each coil is a single linear RC node,
`dT/dt = (P − hA·(T−T_air))/C` → cooling is symmetric with heating, τ ≈ C/hA ≈ 350s.
In reality: (a) natural convection weakens as ΔT shrinks (h ∝ ΔT^0.25) → a very long
cooling tail; (b) the current fit `coil_C_scale=0.2241` means only 22% of the copper
mass is "visible" to IR — the winding core (78% of the mass) stores heat deep inside
and releases it slowly once the current is switched off.

### New physical design (do BOTH — they complement each other)
1. **Nonlinear convection** (for each coil + iron node):
   ```
   hA_eff(ΔT) = hA_cal · (max(ΔT, 0.1) / ΔT_cal)^0.25
   ```
   `ΔT_cal` = the temperature rise at the calibration point (T_ss(5A) − T_air ≈ 11.5K
   for the inner coil) → the steady state at 5A is UNCHANGED, but during cooling ΔT
   shrinks → hA falls → the cooling tail stretches out. (This is a simplified
   Churchill-Chu law.)
2. **2-node coil** (surface + winding-core):
   - `C_surf = coil_C_scale · C_solid` (= the current fitted value, what IR sees)
   - `C_deep = (1 − coil_C_scale) · C_solid` (the remaining, genuinely present copper)
   - A link `G_wind` (W/K) between the two nodes, with the source P split between them
     in proportion to C.
   - `G_wind` is a NEW fitting parameter: choose it so the HEATING transient (session 2's
     ramp test, `thermal_ramp_test` in params.yaml) still gives RMS ≤ 3.5°C (not much
     worse than the old 3°C fit) — i.e. G_wind small enough that the deep node is
     almost "invisible" during the first 450s, but releases heat back into the surface
     once the current is cut → slow cooling. Start around G_wind ≈ 1–3 W/K and fit.
3. **Refit**: write a small fitting script (scratch, not committed) that re-runs the
   ramp-test residual with the new model; record the results (whether hA stays or
   shifts slightly, G_wind, the new RMS) in a params.yaml comment.
4. **Keep two places in sync**: this model lives in JS (`romStep`) AND the new keys must
   be added to the `lumped_thermal` block in `params.yaml` + the Python `LUMPED` export
   (~lines 185–210 of the builder). If `rom.py`/`digital_twin.py` share the lumped coil
   network, sync those too (check with `grep hA_inner`).
5. **TODO for CLAUDE.md**: there is no real COOLDOWN data yet — next lab visit, log a
   cooldown trajectory with IR (cut the current from steady 5A, read the coil every 60s
   for 20–30 minutes) to fit it quantitatively. For now the acceptance is qualitative only.

### Code region
JS `romStep` + the LUMPED constants (~lines 950–1035), the Python export block
(~185–210), `params.yaml` (`lumped_thermal`), possibly `rom.py`. Do NOT touch the
levitation block, do NOT touch the geometry.

### Acceptance
- Steady state UNCHANGED: T_inner_ss(5A) ≈ 40.5°C, T_outer_ss ≈ 38.5°C (±0.3K).
- Heating ramp-test RMS ≤ 3.5°C.
- Cooldown test (in JS, at high speed): from steady 5A → I=0, the time for the inner
  coil to reach `T_air + 0.1·ΔT` must be at least **3×** that of the old model; the
  temperature should fall quickly at first and slow down later (check that dT/dt
  decreases monotonically and the tail is long).
- 0 JS errors, energy sanity: no node ever drops below T_amb.

---

## WP-C — The large Ø202mm disc + re-running the EM (agent 3)

> **STATUS: DONE (2026-07-02).** See CLAUDE.md Code status → the "WP-C" entry for the
> full numbers + caveats. Summary: the Ø202mm disc does NOT levitate at 5A_rms (40%
> short on force; it needs I_min_lev≈6.45A) — a scientific result, not a bug.
> `LEV_ANCHORS` has been precomputed in build_twin_html_fem.py for WP-D to use, but is
> not yet wired into the live JS.

### Answering the question
The current disc: **R = 80mm (Ø160mm)**, 3mm thick (`plate_material.radius_mm: 80.0` in
params.yaml). The separator ring sits at r = 81–101mm → covering the ring's outer edge
requires **R = 101mm (Ø202mm)**.

### Work to do
1. **Add the new plate** to `plate_library` in params.yaml:
   `{name: "Al Ø202mm", radius_mm: 101.0, thickness_mm: 3.0, material: aluminium}`.
   Do NOT change the default `plate_material.radius_mm` (80mm is the real, validated
   disc) — add a way to choose the disc at bake time, e.g. via CLI:
   `python build_twin_html_fem.py --plate-radius 101` (overriding the radius before
   building the ROM/EM, output `outputs/digital_twin_fem_R101.html`).
2. **Re-run the EM at R=101mm** (mandatory — do NOT scale from the R=80 result, because
   the new disc covers the iron-ring/outer-coil region and the eddy distribution is
   completely different):
   - a new `P_plate` and a new `q_e` map.
   - the force curve `F_z(z)` at I_rms=5A (remember the **×2 convention**: the solver
     uses I_peak = I_rms·√2, see CLAUDE.md "CURRENT CONVENTION").
   - the new mass: `m = 2700·π·0.101²·0.003 ≈ 0.2596 kg` → `mg ≈ 2.55N` (the old disc
     is 163g/1.60N).
   - solve `F_z(z_eq) = mg` → the new z_eq; if `F_z_max(5A) < 2.55N` then the disc does
     NOT levitate at 5A → compute a new `I_min_lev` and REPORT it clearly (this is an
     important scientific result, not a failure).
3. **Bake the new anchors into JS**: `Z_GAP_5A_MM`, `Z_DECAY_MM` (refitted from the 2
   new F_z(z) points), and the mass — coordinate with WP-D: these constants must travel
   through the PARAMS JSON rather than being hardcoded (see WP-D). If WP-D has not
   merged yet, temporarily write the values into a single Python dict `LEV_ANCHORS` for
   WP-D to consume.
4. **Thermal**: the ROM rebuilds automatically for R=101 (with the new P_plate) when
   overridden — check that `thermal_solver`'s energy balance is still 0.000%.
5. **Warning to include in the report**: the iron ring (r=81–101mm) is currently
   modelled as AIR (μ_r=1, magnet test PENDING). The Ø202 disc sits directly over the
   ring → if the ring turns out to be ferromagnetic, F_z and P_plate change
   substantially (see the μ_r sensitivity study in CLAUDE.md). The current R=101 results
   are only valid under the assumption that the ring is air.

### Code region
`params.yaml` (plate_library), the Python part of `build_twin_html_fem.py` (argparse +
bake, ~lines 340–600), calling `em_solver.py` through the `compute_losses`/lift-force
API (do not modify em_solver unless an F_z(z) function needs exposing — and if so, only
ADD a function).

### Acceptance
- `python config.py` runs cleanly with the new params.
- A numerical report: P_plate(R101), F_z_max(5A), z_eq or I_min_lev, tabulated against R=80.
- `outputs/digital_twin_fem_R101.html`: 0 JS errors, the Ø202 disc renders covering the
  separator ring's outer edge (confirmed by screenshot), and the default R=80 file's
  behaviour is UNCHANGED.

---

## WP-D — Constant refactor + integration + testing (agent 4, final merge)

> **STATUS: DONE (2026-07-02).** The `levitation:` block was added to params.yaml and
> `coil_hot_display_C` to `lumped_thermal:`. Python's `lev_params(cfg)` reads params +
> `LEV_ANCHORS`/`_lev_anchor()` (WP-C's deliverable) → JS reads `PARAMS.lev.*` instead of
> hardcoded `Z_GAP_5A_MM`/`Z_DECAY_MM`/`ζ0`/`ζ1`/`JIT_*`; `LUMPED.T_coil_hot_display_C`
> replaces `T_COIL_HOT`. **The bug WP-C flagged has been fixed**: the R=101 file now
> computes its own anchors instead of reusing R=80's — verified: R=80 gap@5A=4.1000mm
> (regression held absolutely, not one bit changed), R=101 gap@5A=0.0000mm +
> I_LEV_MIN=6.450A (exactly the numbers WP-C computed; the wrong R101 gap is gone). Both
> files: 0 JS console errors (headless Playwright).

### Rationale
The repo's locked decision: "All tunable parameters live in params.yaml. Never hardcode
constants" — yet the JS hardcodes `Z_GAP_5A_MM=4.1`, `Z_DECAY_MM=21.4`, the disc mass
(hidden inside 163g/1.60N), `T_COIL_HOT=80`, WP-A's new `JIT_MM`/`ζ0`/`ζ1`, and WP-B's
new cooling keys.

### Work to do
1. Create a `levitation:` block and extend `lumped_thermal:` in params.yaml to hold all
   the constants above (with a comment giving the provenance of each number).
2. The Python builder reads them → injects them into the existing PARAMS JSON (the
   `ROM`/`LUMPED` pattern, ~lines 580–600) → JS reads `PARAMS.lev.*` instead of literals.
3. **Merge coordinator**: merge in the order C → B → A, resolving conflicts in
   `build_twin_html_fem.py` (the regions are separate but can still meet at the PARAMS
   export + render loop).
4. **Full testing** (headless Playwright, both the default R=80 file and R101): the
   complete acceptance checklists of A, B and C plus regressions: gap 4.1mm@5A (the R=80
   file), coil glow, non-overlapping labels, B-field density tracking I (the earlier
   2026-07-02 fixes must not break).
5. Update CLAUDE.md (Code status + the TODO to log cooldown data + the z_obs@7.75A
   calibration question for the user) and the README if needed.

---

## Conflict map inside build_twin_html_fem.py

> Historical (for reference) — all 4 WPs are DONE and no merges are pending. In
> practice all 4 WPs ran sequentially in the same working tree (not in separate git
> worktrees as originally planned), so no real conflict ever occurred.

| WP | Python | JS |
|----|--------|-----|
| A  | — | ~1129–1170 (lev physics), ~1995–2022 (loop/telemetry) |
| B  | ~185–210 (LUMPED export), params.yaml | ~950–1035 (romStep) |
| C  | ~340–600 (geometry/bake/argparse), params.yaml, em_solver API | lev anchor constants |
| D  | ~580–600 (PARAMS export), params.yaml | replace literals → PARAMS.lev |

Hot spot: the **PARAMS export (~580–600)** — B, C and D all add keys there → each agent
only ADDS new keys (never edits existing ones), and D resolves at the end.
**params.yaml** — B adds to `lumped_thermal`, C adds to `plate_library`, D adds the
`levitation` block → different regions, easy to resolve.

## Questions for the user to answer (updated 2026-07-02, after all 4 WPs finished)

None of these block using the twin as it stands — they are all "accuracy" questions,
not runtime bugs. Ordered by priority.

1. **[WP-A] What is the real gap at 7.75A, in mm** (or as a multiple of the disc
   thickness)? The code already has a placeholder: the `Z_OBS_7_75A_MM` variable (JS,
   in the "Levitation gap physics" block) — currently `null`; fill in a number and
   `Z_DECAY_MM` refits itself. It currently uses `z_decay_mm=21.4mm` (params.yaml
   `levitation:`), predicting gap@7.75A≈22.9mm, but you observe the gap "only rises a
   little" — 21.4mm is most likely too large.

2. **[WP-A] A numerical contradiction inside this very plan, deliberately NOT resolved
   unilaterally**: WP-A's acceptance criterion demands that the 5→7.75A step's overshoot
   be <40% of the 0→5A step's — which would require ζ(7.75A)≈0.3. But the physical law
   ζ(I)=ζ0+ζ1·(I/5)², anchored at ζ(5A)=0.02 (matching the observed ~9s settle), only
   yields ζ(7.75A)≈0.048 — 0.3 is unreachable without breaking the 5A anchor. Measured:
   the real overshoot ratio is 91.5%, so the test FAILS against the original criterion.
   You need to decide: (a) relax the overshoot criterion, (b) switch to a steeper (less
   "physical") damping law, or (c) wait for real 7.75-8A oscillation data to fit ζ properly.

3. **[WP-B] There is no real COOLDOWN data.** `coil_G_wind_W_per_K=1.0` was only fitted
   from the HEATING curve (the ramp test) plus the qualitative target "much slower" —
   treat it as order-of-magnitude. Next lab visit: hold the current steady at 5A until
   steady state, cut the current, and read the coil temperature by IR every 60s for
   20-30 minutes → fit `coil_G_wind_W_per_K` and `convection_exponent` quantitatively.

4. **[WP-C/D] Two ways of computing z0 (the decay length) disagree by ~1.5×, found while
   wiring WP-C into WP-D; deliberately NOT picking a side**: the value currently USED in
   the default R=80 file is `z0=21.4mm` (fitting F(1mm) and the F=F_grav crossing — the
   original method, 2026-07-01). WP-C recomputed it a different way (fitting F(1mm) and
   F(5mm) directly, independent of the disc mass) and got `z0=13.6mm` for the SAME R=80mm
   disc. Both are "correct" by their own definition — they differ because F(z) is not a
   clean exponential over that interval. R=101 currently uses WP-C's method (the 13.6mm
   style). The question: is there measured gap data at several current levels to decide
   which one models reality better? (Question #1 above — gap@7.75A — would answer this too.)

5. **[WP-C] The Ø202mm disc does NOT levitate at the standard 5A_rms operating current**
   — it needs I_min_lev≈6.45A (about 40% short of the 2.55N weight). This is a simulation
   result, not yet verified with a real disc. If a Ø202mm disc is actually going to be
   made to test on the rig, is it worth trying, or do we stay with the current Ø160mm disc?

6. **[Background, not specific to any WP] The iron/separator ring (r=81-101mm) — the
   magnet test has NOT been done.** It is currently modelled as air (μ_r=1). If it really
   is ferromagnetic, P_plate and F_z could change enormously (see the "μ_r SENSITIVITY
   TEST" in CLAUDE.md) — affecting both the R=101 results (WP-C) and the current
   levitation numbers. A real magnet test on this ring is needed (like the one already
   done on the centre core).

7. **[Background] Is the disc hotter or is the coil hotter?** The twin currently predicts
   T_ss(plate, 5.5A)=61.7°C, HIGHER than the coil (~59°C), but the IR data says the coil
   is much hotter than the disc. The disc model (FEM, ΔT_max=27K@5A) has NEVER been fitted
   against real data (disc IR is untrustworthy — shiny aluminium, wrong ε). The disc
   temperature needs measuring with a real contact thermocouple (not IR) so the disc's h
   coefficient can be fitted.

8. **[Background, a side finding of WP-C] Mesh sensitivity**: refining the EM mesh
   (`em_domain.fine_step_mm` 2.0→1.0mm) changes z_eq(R=80) from 4.15mm to the equivalent
   of ~3.5mm (enough that the R=80 disc would then NOT levitate at 5A!), and
   I_min_lev(R=101) from 6.45A to 6.9A. So the "validated z_eq=4.1mm" figure is more
   mesh-sensitive than assumed — unresolved (out of WP-C's scope, and connected to the
   PAUSED 37% benchmark investigation). Someone should revisit this when there is time.
