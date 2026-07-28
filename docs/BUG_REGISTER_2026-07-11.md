# BUG REGISTER — 2026-07-11 Audit (post 2026-07-10 iron/geometry update)

Follow-up audit after the 2026-07-10/11 changes (re-measured coil geometry,
iron_core + outer_iron_ring both confirmed ferromagnetic μr=1000, Phase B hA
refit, Phase C saturation-loop generalization, Phase D comments). Triggered
by user suspicion that these updates broke something. 3 parallel Explore
agents covered the EM chain, the thermal/ROM chain, and HTML/docs staleness;
findings below were then fixed by the main agent (commits listed per item).
Companion doc: `docs/AUDIT_FIX_PLAN_2026-07-04.md` (previous audit round —
still has open items, see its Part 4).

> Severity: **BUG** = wrong number/behavior in a real code path. **DOC** =
> stale comment/doc, no runtime effect. **OPEN** = genuine physics unknown,
> not agent-fixable.

## Fixed this session

| # | Sev | File:line | What was wrong | Fix | Commit |
|---|-----|-----------|-----------------|-----|--------|
| B1 | BUG | `params.yaml` `lumped_thermal.hA_inner/outer_W_per_K` | The FIRST 2026-07-11 hA refit pass solved the steady-state balance with `AIR_DT_SS = (P_coils+P_iron+P_plate)/hA_far = 8.40K`, but the code that actually runs (`build_twin_html_fem.py` `AIR_P_SUM_REF` = Σ over `LUMPED.nodes{inner,outer,iron}` only — plate is a separate ROM node, never joins this shared air node) computes `AIR_DT_SS=6.83K`. Deployed twin would have under-predicted both coil steady temps by ~1.6°C vs the 79/74°C validation anchor. | Re-solved hA using the code's own formula: `hA_inner=2.9493`, `hA_outer=3.4509` (was the wrong-formula 3.0605/3.5986). Verified by hand: `T_inner=79.00°C`, `T_outer=74.00°C` exactly. | `81da2ee` |
| B2 | BUG | `em_solver.py` `compute_losses()` (was line ~453) | Iron-region loss classification used an `elif fe.get("enabled")` catch-all (iron_CORE gate only) instead of testing `outer_iron_ring`'s own r/z box. Latent: if `iron_core.enabled=False` while `outer_iron_ring.enabled=True`, the ring's eddy loss (σ=1e6>0 conductor) matched no branch and was silently dropped from every `P_*_W` total. | Explicit r/z box membership test for both core and ring; unclassified conductor elements now print a WARNING instead of silently vanishing. | `a2dd805` |
| B3 | BUG | `em_solver.py` `check_saturation()` (was line 251-290) | Only scanned `iron_core`'s r/z box for `B_max_iron`, even though `solve_em_saturating()`'s Picard loop was generalized (Phase C, 2026-07-10) to correct BOTH `iron_core` and `outer_iron_ring`. A ring-only saturation event would never trip the `!!! SATURATED` warning at any of its 3 call sites. | Generalized to scan both regions; return signature unchanged (`B_max_iron, B_e` 2-tuple, all 3 callers still unpack correctly). | `a2dd805` |
| D1 | DOC | `em_solver.py` mesh comment | "outer coil now at r=124mm" — stale, now 102.9mm. | Fixed. | `a2dd805` |
| D2 | DOC | `em_solver.py` `material()` comments | iron_core said "CONFIRMED non-ferromagnetic, r=0..25mm"; outer_iron_ring said "r=81..101mm, magnet test PENDING". Both flipped by the 2026-07-10 measurement (confirmed ferromagnetic, new radii). | Both comments corrected. | `a2dd805` |
| D3 | DOC | `em_solver.py` `solve_em_saturating()` docstring | Said "Currently a no-op while μ_r=1.0" — false since 2026-07-10 (μr=1000 for both regions, loop is active). Also didn't note the loop's own B evaluation stays on the loss-chain's RMS-as-amplitude convention (√2 below true peak). | Docstring rewritten to state the loop is active and note the amplitude-convention caveat. | `a2dd805` |
| D4 | DOC | `params.yaml` `excitation.current_A` comment | Said "F_z predictions... multiply by 2.0 when comparing vs physics" — this pattern was replaced 2026-07-10 by WP-PEAK (`I_amplitude=cfg.I_peak` at every force call site); the comment was never updated and directly contradicts CLAUDE.md's "do NOT manually multiply F_z by 2.0 anymore". | Rewritten to match the current `I_amplitude=cfg.I_peak` convention. | `a2dd805` |
| — | — | `outputs/digital_twin_fem.html` | Was baking the NEW 2026-07-10 losses/geometry but the OLD (pre-B1-fix) hA values — internally inconsistent artifact. | Rebuilt after B1; see verification below. | (this session, see WP-5 verify) |

## Investigated, found NOT to be bugs (verified-clean — do not re-check next session)

- **RMS/peak convention**: every FORCE/B-report call site (`compute_lift_force`,
  `run_rig_validation`, `run_benchmark_validation`, `_lev_anchor`,
  `check_saturation` call sites) correctly passes `I_amplitude=cfg.I_peak` /
  `B_scale=cfg.I_peak/cfg.I`. Every LOSS call site stays on the default
  `cfg.I`. No double-correction, nothing missing.
- **solve_em_saturating() Picard loop internals**: variable scoping, index
  alignment between `iron_idx`/`oir_idx` and `nu_iron`/`nu_oir`,
  under-relaxation blending, convergence criterion, and both fallback paths
  (all-disabled → linear; no-elements-matched → return initial) are all
  correct post Phase-C generalization.
- **Geometry**: params.yaml matches the 2026-07-10 ruler measurements exactly;
  no hardcoded radii bypass params.yaml in any `*.py` (only stale comments,
  see D1/D2 above).
- **Benchmark isolation**: `run_benchmark_validation()` (TEAM28 original, no
  iron) correctly disables both `iron_core` and `outer_iron_ring` — the newly-
  ferromagnetic ring does not contaminate the benchmark.
- **Mesh region assignment**: z-aware, no double-assignment — the plate
  (R=80mm) and the iron ring (r=64.9-79.9mm) overlap in r but never in z, so
  `material()`'s early-return chain resolves them correctly.
- **rom.py / thermal_solver.py / digital_twin.py / sim_plates.py / data_io.py**:
  all pull losses live from `em_solver.compute_losses()`, none cache
  pre-2026-07-10 numbers. `excitation.power_ref_W=25.825` is internally
  consistent (`P_plate(7.8A)=62.82W / (7.8/5)² ≈ 25.83W`) and only feeds the
  `--no-em` fallback path (never the normal EM-backed run).
- **q_e spatial map**: iron/ring elements intentionally do NOT populate
  `q_e[e]` (stays 0) even after the B2 fix — `thermal_solver._interp_em_losses()`
  builds a Delaunay triangulation over every `q_e>0` point and interpolates
  onto the DISC's own local mesh; adding iron/ring points to that cloud would
  change the triangulation/convex-hull the disc mesh interpolates against.
  Iron heat is delivered through the lumped-network `P_iron` scalar
  (`build_twin_html_fem.py`'s `lumped_physics()`), not this spatial map, so
  q_e=0 there is correct, not an oversight.
- **config.py**: `I_peak = I*√2`, e-notation coercion, `dial_to_current_A`
  interpolation all correct.
- **CHANGELOG Phase B/C/D entries**: none overclaim vs git state (Phase B
  explicitly labeled its verification as a hand-calc, not a rebuild).

## WP-6 result: coil_C_scale / coil_G_wind — tested, held unchanged

Replicated `build_twin_html_fem.py`'s two-node `romStep()` coil model in
Python (scratch script, not committed — same precedent as prior fits, see
params.yaml `lumped_thermal` comments), fit against
`validation_data.thermal_ramp_test` using the NEW P distribution + corrected
hA (B1). Baseline (`coil_C_scale=0.2241`, `G_wind=1.0`, unchanged) scores
**RMS=2.56°C** — consistent with the ~2.5°C previously claimed, so the new
losses did not break the transient shape. A Nelder-Mead least-squares search
over both parameters only reached RMS=2.50°C at a degenerate optimum
(`coil_C_scale=0.145`, smaller effective mass than the physically-derived
0.2241, likely overfitting 7 residuals with 2 free parameters). **Held
unchanged** — not worth destabilizing the mass-based value for a 0.06°C gain.
Documented in `params.yaml` comments. Real fix needs actual cooldown IR data
(existing NEXT-list item, unchanged).

## WP-7 result: force + saturation experiment — REFUTES the saturation hypothesis

CLAUDE.md's open "LIFT FORCE MISMATCH" question speculated that the fixed
`μr=1000` linear assumption (vs the Lorentzian saturation model already used
for loss reporting) might explain part of the gap between predicted z_eq
(11.7mm plate-bottom / 14.7mm visible) and the observed 7-8mm visible gap.
Added `compute_lift_force(..., saturating=False)` (default off, backward
compatible) to optionally run the force solve through
`solve_em_saturating()` instead of the linear `solve_em()`. Ran the full
rig sweep both ways at `I_amplitude=cfg.I_peak` (physically correct peak
amplitude, so the Picard loop sees the true B, not the √2-low loss-chain
convention):

```
z_bottom(mm)   F_lin(N)   F_sat(N)   ratio
        3.8     4.1041     4.1046    1.0001
        5.0     3.2627     3.2633    1.0002
       18.0     0.7305     0.7313    1.0010

z_eq (plate-bottom): LINEAR = 11.75mm,  SATURATING = 11.75mm  (IDENTICAL)
```

**Result: saturation changes F_z by <0.1% everywhere in the sweep — z_eq is
unchanged to 2 decimal places.** At B≈0.66-0.68T (well below B_sat=1.5T) the
Lorentzian μr_eff only drops to ≈830 (from 1000), but this has essentially no
effect on the Lorentz-force integral. **This refutes the saturation
hypothesis as an explanation for the 7mm gap mismatch** — the discrepancy is
NOT a saturation artifact. Per user instruction, μr was NOT reverse-fit to
close the gap; this stays an **open question** (see CLAUDE.md). Candidate
directions for a future session: (a) the μr=1000 mild-steel-like placeholder
itself may be wrong at the *unsaturated* level (never measured — no B-H
curve), (b) the force model (`compute_lift_force`) only integrates J×B on
actual eddy-current-carrying conductors — it has no explicit ponderomotive
/Maxwell-stress term for the iron's own magnetization, which could be
under-counting the iron's contribution to lift independent of saturation.
Neither was investigated further this session (out of scope — report-only).
`saturating=True` is now available for future experiments but is NOT the
default anywhere.

## Verification run (this session)

```
python em_solver.py   | tail -30   → I²-check 3.998≈4.000, domain validation PASS (<1%),
                                      P_plate=25.81W/P_iron=5.856W/P_coil=106.4W unchanged
python thermal_solver.py | tail -5 → energy balance error=0.000%
python rom.py          | tail -10  → I² scaling 4.000000 exact
```
(HTML rebuild verification — grep counts for old/new hA, API-key check — see
commit message for the WP-5 rebuild commit.)

## Not investigated this session (carry forward)

- `docs/REPORT_WHY_CUSTOM_CODE_DE.md` (+ English counterpart) still cite
  pre-2026-07-10 coil/iron radii and "ring = air" — flagged by the audit,
  fix scope given to WP-8 docs sync (see CLAUDE.md/CHANGELOG for status by
  the time you read this).
- Gitignored `outputs/*.png`/`.glb` predate the 2026-07-10 geometry — cosmetic,
  regenerate on demand (`python visualize.py --no-show`, `sim_plates.py`, etc.).
- All Part 4 open questions in `docs/AUDIT_FIX_PLAN_2026-07-04.md` (OQ-1
  through OQ-9) are unaffected by this round except OQ-6, now resolved (ring
  confirmed ferromagnetic 2026-07-10) — mark it there.
