# WP-COOL / WP-LEV / WP-SHIMMER — implementation work order (2026-07-28)

Debug + root-cause already done. Full evidence, all reproduction numbers and
the derivations are in **`docs/archive/2026-07-28_BUG_REGISTER.md` — read that first,
in full.** Do not re-derive; do not re-debug. This file is the work order.

---

## Ground rules

- **`twin_core.py` is the SSOT integrator, but the baked JS in
  `build_twin_html_fem.py` is a hand-maintained twin of it.** Every physics
  change must land in **both**, identically. `xval_twin.py` exists precisely to
  catch drift — it must pass at the end.
- `twin_core.py` is **numpy + stdlib only**. No config/em_solver/rom imports.
  Its own import-only self-test enforces this.
- **No hardcoded constants.** Every new number goes in `params.yaml`, is read
  by `lumped_physics()` / `lev_params()`, and is baked into `PARAMS`.
- Display-only quantities get a `# DISPLAY ONLY` comment in `params.yaml`.
  CLAUDE.md Conventions: *"Every new physics term needs an energy-balance /
  sanity check before use."*
- The repo's debugging rules apply: root cause before fix, and **run the
  verification command and show its output before claiming anything is done.**
- Do **not** `git add` `outputs/digital_twin_fem.html` if it was rebuilt with a
  real Google Weather API key. Rebuild with the placeholder first.

---

## WP-LEV — fix the levitation gap ordering (issue 2). Do this first; it is self-contained.

**Defect (L1/L2, bug register §L1/L2).** `_lev_anchor()` finds `z_eq` with
`np.interp` over a 3-point table `zs=[1.0, 3.8, 5.0] mm`. `np.interp` clamps
outside its range, so every disc whose true crossing is past 5 mm gets exactly
`z_eq = 5.000`. R=65/70/75 are all baked at 5.000 mm. R=80 escapes only because
`lev_params()` special-cases it to `params.yaml`. Result: the biggest disc
appears to float highest, the exact opposite of the physics.

**Ground truth** (full 10-point `compute_lift_force(cfg, I_amplitude=cfg.I_peak)`
sweep, default mesh — reproduce these, they are your acceptance test):

| R [mm] | F_grav [N] | true z_eq [mm] | z0 (F1/F5) [mm] | I_lev_min [A] |
|--------|-----------|----------------|-----------------|---------------|
| 65 | 1.0547 | **15.74** | 11.34 | 2.50 |
| 70 | 1.2232 | **14.95** | 11.26 | 2.58 |
| 75 | 1.4042 | **13.58** | 11.37 | 2.75 |
| 80 | 1.5977 | **11.86** | 11.79 | 3.02 |

### Tasks

1. In `build_twin_html_fem.py` `_lev_anchor()`, replace the 3-point
   `np.interp` with a real bracketing root-find on `F(z) − F_grav`:
   coarse scan z = 1 → 40 mm (2 mm steps) to find the sign change, then
   `scipy.optimize.brentq` (or bisection) to converge. Keep
   `z0_decay_mm = (5−1)/ln(F(1)/F(5))` unchanged — those values are already
   correct and consistent across all radii.
   - If no sign change is found in range, keep the existing
     `levitates_at_5A_rms: False` / `I_min_lev_A_rms` branch.
   - Keep `F_at(3.8)` — the "does it clear gravity at the physical resting
     floor" test still uses it.
2. In `lev_params()`, **delete** the `if abs(radius_mm - default_radius) < 0.5`
   branch so every radius, R=80 included, goes through the same code path.
   Verify R=80 now comes out at 11.8–11.9 mm (vs the `params.yaml` 11.7 from
   the independent `run_rig_validation()` sweep — agreement is the check that
   the new method is right).
3. Delete or regenerate the `LEV_ANCHORS` dict. Its R=80 row
   (`z_eq_5A_mm: 4.15`, `z0_decay_mm: 13.63`) is from the pre-2026-07-10
   geometry and is now dead-wrong. If you keep the cache, regenerate both rows
   from the fixed `_lev_anchor()` and say so in the comment.
4. Update the `params.yaml levitation:` comment block: `z_gap_5A_mm`/
   `z_decay_mm` are now the *default-plate* values, produced by the same method
   as every other radius. Do **not** change the values themselves.

### Acceptance

- Rebuild and dump `PARAMS.plate_variants[*].lev.z_gap_5A_mm` from the HTML.
  Expect ≈ 15.7 / 14.9 / 13.6 / 11.9 — **strictly decreasing** with radius, and
  no value equal to 5.000.
- `I_lev_min` strictly increasing: ≈ 2.50 / 2.58 / 2.75 / 3.02 A.
- In the HTML, switching discs at a fixed 5 A must show the Ø130 disc highest
  and Ø160 lowest.

---

## WP-COOL — make the rig cool at a physical rate (issue 1). The big one.

**Defects T1–T5, bug register §T1–T5.** Read that section before touching code;
the trade-off in "⚠️ The trade-off, stated honestly" is a decision that has
already been made — implement it, and record the regression rather than
fitting around it.

Shipped behaviour to beat: heat to 5 A steady state at T_amb=20 °C, then I=0 →
inner coil loses **half its rise in 102 s**, disc in 194 s.

### T1 — split coil power in the same ratio as coil capacity

`lumped_physics()` gives the surface node `C = C_solid·coil_C_scale` but
100 % of `P_ref`; the deep node gets no source. Fix:

- `lumped_physics()`: emit `P_surf_frac` (= `coil_C_scale`) on each coil node,
  or emit `P_ref_surf` / `P_ref_deep` directly. Prefer the explicit two-key
  form — it is self-documenting in the baked `PARAMS` and easier to eyeball.
- `twin_core.py _rom_step()` **and** the JS `romStep()`: the surface node takes
  `P_surf·s2`, the deep node takes `P_deep·s2`:
  ```
  T[k]    += (q_surf + g - out) / C      * dt
  T[deep] += (q_deep - g)       / C_deep * dt
  ```
- `twin_core.NodeCoeffs` gains the new field(s); `from_source` must tolerate a
  missing key (default: all power to the surface = today's behaviour) so an
  older baked HTML still loads.

**Invariant to assert in a test: the steady state must not move.** The
analytic proof is in the bug register; numerically the shipped model and every
P-split variant both give `ss@7.8 A/29 °C = inner 72.148 / outer 67.780 °C`.

⚠️ **Stability trap.** The deep-node update is forward Euler:
`dt < 2·C_deep/G_wind`. `TwinState.step()` substeps at `tau*0.05 ≈ 12.2 s`.
With a large `coil_C_scale` the deep node gets small and `G_wind` above ~8 W/K
diverges at that substep. Either keep `coil_G_wind_W_per_K` bounded, or tighten
the substep rule — and if you tighten it, `xval_twin.py`'s substep assertion
and its dt=25 s schedule must be re-checked.

### T2 — give the iron node the iron's heat capacity

`"C": 0.5 * C_plate` (= 73.3 J/K) is half the *aluminium disc's* capacity.
Replace with a real computation from `params.yaml` geometry:

```
V_core = π·r_core²·h                       (iron_core: r ≤ 25.9 mm, z −53…0)
V_ring = π(r_out² − r_in²)·h               (outer_iron_ring: 64.9…79.9 mm)
C_iron = rho_Fe·cp_Fe·(V_core + V_ring)    = 1676 J/K
```

- Add `rho_kg_per_m3` / `cp_J_per_kgK` for iron to `params.yaml`
  (`material_props:` already holds `aluminium`; add an `iron:` entry, or put
  them on the `iron_core:`/`outer_iron_ring:` blocks). Do **not** hardcode
  7870/450 in Python.
- Honour the `enabled` flags: if a region is disabled, drop its volume.
- Sanity-print `C_iron` in the build log.

### T3 — the disc's cooldown τ must not be its heat-up τ

`rom.UA` comes from a FEM with `h_bottom_W_per_m2K = 25` (the coil plume). Make
τ plume-dependent, using the `coilAirDrive()` value the code already computes:

```
tau_eff = ROM.tau / (f_nat + (1 - f_nat) * min(1.0, airDrive))
```

- `f_nat` goes in `params.yaml` (suggest `rom.tau_cool_natural_frac: 0.58`),
  derived from the BC h-values as
  `(h_top·A_top + h_top·A_bot + h_top·A_edge)/(h_top·A_top + h_bottom·A_bot + h_top·A_edge)`.
  **Compute it in `rom.py`/`lumped_physics()` from the actual params** rather
  than pasting 0.58 — then it stays correct if the BCs change.
- Apply `tau_eff` in the `beta_eddy`/`beta_air` updates, in both `_rom_step()`
  and JS `romStep()`.
- τ only sets the rate; the β targets are untouched, so the steady state is
  exactly preserved. Assert that.
- Sanity: `tau_eff` must land in 244 s (plume on) → ~421 s (plume off), inside
  the 350–700 s natural-convection band for a 3 mm Ø160 disc.

### T4 — refit hA through the nonlinear model

`hA_inner/hA_outer` were solved from the linear balance
`T = T_amb + P/hA + ΔT_air`, but the code runs
`hA_eff = hA·(ΔT/ΔT_cal)^0.25`. The shipped model lands at 72.15/67.78 °C at
7.8 A/29 °C instead of the calibrated 79.00/74.00.

- Write the refit as a **committed script or a `--refit-hA` mode**, not a
  one-off — the last two hA refits both shipped wrong because the fitting
  formula and the running code diverged (2026-07-11 B1, and now T4). The script
  must call the **actual integrator** (`twin_core.TwinState`), run it to steady
  state at 7.8 A/29 °C, and root-find `hA_inner/hA_outer` on the residual
  `(T_inner−79, T_outer−74)`.
- Expected result with T1+T2 in place: `hA_inner ≈ 2.47`, `hA_outer ≈ 2.89`
  (from 2.9493 / 3.4509). Recompute — the exact values shift with T2's C_iron.
- Update `params.yaml` with the new values **and** rewrite the calibration
  comment block to state that the fit is now solved through the nonlinear
  model, with the script name.

### T5 — air node: document, do not tune

`air_node_C_J_per_K: 3000` / `air_node_hA_far_W_per_K: 40` are self-labelled
"illustrative" (τ_air = 75 s; `hA_far=40` over ~0.2 m² implies h ≈ 200 W/m²K).
Leave the values alone. Update their comments to say explicitly that they are
unidentified fudge factors that cap the rig's thermal memory, and that they are
blocked on real cooldown data.

### Acceptance

Run this and paste the table into `docs/CHANGELOG.md`:

- Heat to 5 A steady state at 20 °C, then I=0; report `t50`/`t90` for the inner
  coil and the disc, before vs after.
  - Before: coil t50=102 s / t90=2032 s; disc t50=194 s / t90=712 s.
  - After (target): coil t50 in the **400–900 s** band; disc t90 ≥ 1000 s.
- Steady state at 7.8 A / 29 °C must be **79.00 / 74.00 °C** (that is what T4
  buys). Show the numbers.
- `thermal_ramp_test` RMS **will get worse**, ~2.5 °C → ~9–13 °C. Report the
  actual number. **This is expected and accepted** — see the bug register's
  trade-off section: that ramp is 5 points narrated from a video, is internally
  inconsistent (its t=300 s point exceeds the model's own 5 A asymptote), and
  cannot be reconciled with Session 1's 74 °C under any constants for this
  network. Do **not** re-shrink `coil_C_scale` to recover it.

---

## WP-SHIMMER — start-up ramp + a disc that actually moves (issue 3)

### V1 — `quickstart` scenario

Existing scenarios are `step / ramp / sine / pulse`; `ramp` is 60 s and the
default is `step` (current jumps to 5 A in one frame).

- Add `quickstart`: `min(t/t_rampup, 1)·I`, `t_rampup` from `params.yaml`
  (`transient.quickstart_ramp_s`, default **8.0** — user asked for 5–10 s).
- Add it to **both** `SCENARIOS` dicts: `twin_core.py:46-47` (SSOT, imported by
  `digital_twin.py`) and the JS `SCENARIOS` in `build_twin_html_fem.py:1460-1464`.
- Make it the **default scenario on load and on reset** in the HTML, and add
  its button to the scenario row (`build_twin_html_fem.py:1171-1174`), keeping
  the `1-4=scenario` keyboard hint in sync (it becomes 1-5).
- `digital_twin.py` and `digital_twin_pyvista.py` pick up the new scenario for
  free via the shared `SCENARIOS` — confirm their pickers list it.

### V2 — sustained oscillation while levitating

`fadeIn = max(0, 1 − z/jit_fade_mm)` with `jit_fade_mm = 0.5 mm` kills all
motion once the gap exceeds 0.5 mm — i.e. above ≈3.2 A the disc is rigid.

**Read the physics in the bug register §V2 / `docs/physics.md` §11 before
coding.** Summary: `F ∝ i²` gives 100 % force modulation at 100 Hz, but the
1-DOF response at Ω/ω_n = 628/28.8 is only **0.0249 mm**. Invisible, and above
the frame rate. The wobble seen on the real rig is the **lateral/tilt** mode,
not the vertical one. So this is explicitly a display effect built on a
traceable physical number.

- Keep `jit_contact` (today's sub-lift-off buzz, gated by `jit_fade_mm`)
  exactly as-is.
- Add a **separate** `jit_lev` term, active whenever the disc is levitating:
  amplitude ∝ (I/5)² (it scales with the force), base amplitude computed from
  the ripple transfer function
  `X_ripple = z_decay_mm / |1 − (2ω/ω_n)²|` (≈ 0.0249 mm at the current
  constants — **compute it, don't paste it**), multiplied by a new
  `levitation.lev_ripple_display_gain` (suggest **40**, → ~1 mm on screen).
- Use two incommensurate low frequencies (as `jit_freq1/2` already do) so the
  motion reads as an organic wobble rather than a pure sine, at a visible few
  Hz — not 100 Hz, which aliases.
- Optional, and clearly better visually: a slow **tilt/wobble** about x/y
  (2–4 Hz, two phases) — this is the honest representation of the real lateral
  instability. If you add it, it is display-only too.
- Every new constant in `params.yaml levitation:` with `# DISPLAY ONLY` and a
  one-line pointer to `docs/physics.md` §11.
- Mirror all of it in `twin_core.LevCoeffs`/`_lev_step` **and** the JS
  `levStep()`, with `from_source` defaulting the new keys to a no-op so older
  bakes still load.

### Acceptance

- Load the HTML: current ramps 0 → 5 A over ~8 s without touching a slider, and
  the disc visibly rises and bobs during the ramp.
- At a **fixed** 2 A, 3.5 A, 5 A and 7.5 A the disc is visibly moving in all
  four cases (not just below lift-off, not just for 1.7 s after a slider move).
- The *mean* gap at each current is unchanged from WP-LEV's values — the
  shimmer must ride on top of `z_gap_eq(I)`, never bias it. Assert
  `mean(z) ≈ z_gap_eq(I)` over a few seconds.

---

## Verification — run all of these and show the output

```bash
python twin_core.py                 # 6/6 self-checks PASS
python config.py                    # params load clean
python em_solver.py                 # I²-check 3.998≈4.000; rig validation
python thermal_solver.py            # energy balance error=0.000%
python rom.py                       # I² scaling exact
python digital_twin_pyvista.py --self-check
python build_twin_html_fem.py       # rebuild the bake (PLACEHOLDER key!)
python xval_twin.py                 # MUST pass — pins twin_core vs the baked JS
```

`xval_twin.py` is the one that matters. Its **assertion B** compares the baked
`PARAMS.lumped` / `PARAMS.rom.tau` against a fresh
`lumped_physics(cfg, compute_losses(cfg))` — this is exactly the "coefficient
changed but the HTML was never rebaked" bug class that shipped in commit
`d4f73d6`. Assertion **A** (integrator match, tol 1e-9) is what catches
`twin_core.py` and the JS drifting apart. If A fails, you changed one copy and
not the other.

Playwright check on the rebuilt HTML: **0 JS errors**, plus the four
fixed-current shimmer checks and the disc-swap gap ordering above.

---

## Docs to update when done

1. **`docs/CHANGELOG.md`** — a WP-COOL / WP-LEV / WP-SHIMMER entry: what
   changed, the before/after cooldown table, the new hA values, the
   `thermal_ramp_test` RMS regression **stated plainly with its justification**,
   and the new `params.yaml` keys.
2. **`CLAUDE.md`** — replace the long `OPEN (2026-07-28, user-reported…)` block
   with a short `[x] RESOLVED 2026-07-28` summary in the established style
   (a few lines + a pointer to `docs/archive/2026-07-28_BUG_REGISTER.md`). **The file
   is 446 lines against a ~200-line budget — this is a trim, not an append.**
   Also update the "First quantitative result" and "Real-rig validation"
   sections if the hA refit moved their numbers.
3. **`docs/archive/2026-07-28_BUG_REGISTER.md`** — add a "Fixed this session" table
   with commit hashes, matching the `docs/archive/2026-07-11_BUG_REGISTER.md` format.
4. **`README.md`** — only if a CLI surface changed (new `--refit-hA` mode, new
   scenario names in the run list).
5. **`docs/physics.md` §11** — flip the "OPEN" framing to resolved for (a)–(d),
   keep the derivations.

## Suggested commit split

- `WP-LEV`: `_lev_anchor` root-find + `lev_params` unification + `LEV_ANCHORS`.
- `WP-COOL-1`: T1 P-split + T2 C_iron (both integrators + `lumped_physics`).
- `WP-COOL-2`: T3 plume-dependent τ.
- `WP-COOL-3`: T4 hA refit script + new `params.yaml` values.
- `WP-SHIMMER`: V1 quickstart + V2 sustained shimmer.
- `WP-BAKE`: rebuild `outputs/digital_twin_fem.html` (placeholder key) + docs.
