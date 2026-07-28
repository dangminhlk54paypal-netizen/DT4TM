# BUG REGISTER — 2026-07-28 (user-reported HTML-twin behaviour)

Triggered by three observations the user made while driving
`outputs/digital_twin_fem.html` on the real rig side-by-side:

1. Coil **and** disc temperatures fall far too fast when the current drops —
   on the real rig they fall very slowly (the team sometimes has to actively
   cool the disc / outer coil).
2. The Ø160 mm (R=80) disc floats **higher** than every smaller disc as soon as
   current flows — the opposite of what the physics predicts.
3. There is no fast start-up ramp to watch the disc bob, and the disc does not
   visibly oscillate at *any* current — only a brief ring-down after a slider
   move.

All findings below were reproduced numerically before any fix was proposed.
Reproduction scripts are throwaway (scratchpad); the numbers they produced are
inlined here so they don't need re-running.

> Severity: **BUG** = wrong number/behaviour in a real code path.
> **STRUCT** = the model form itself is wrong (not just a constant).
> **FEAT** = missing capability, not a defect.
> **OPEN** = genuine unknown, needs measurement.

---

## Summary table

| # | Sev | Where | One-line |
|---|-----|-------|----------|
| L1 | BUG | `build_twin_html_fem.py:116-126` `_lev_anchor()` | `np.interp` over a 3-point z-table clamps `z_eq` to **exactly 5.000 mm** for every disc that floats above 5 mm — R=65/70/75 all hit the clamp, R=80 escapes it only because `lev_params()` special-cases it to `params.yaml`. |
| L2 | BUG | `build_twin_html_fem.py:167-169` `lev_params()` | R=80 reads `params.yaml levitation:` (a real 10-point F(z) sweep) while every other radius goes through `_lev_anchor()`. Two different methods for the same quantity → the SSOT is split. |
| T1 | STRUCT | `build_twin_html_fem.py:400-415` `lumped_physics()` + `twin_core.py:351-367` `_rom_step` | Coil surface node gets **100 % of `P_ref`** but only `coil_C_scale`=22.4 % of the copper mass. `dT/dt = P/(0.2241·C_solid)` → both heat-up and cooldown run ~4.5× too fast. |
| T2 | STRUCT | `build_twin_html_fem.py:418` | `iron` node heat capacity is `0.5 * C_plate` = **73.3 J/K** — half the *aluminium disc's* capacity, unrelated to iron. Real core+ring from `params.yaml` geometry = **1676 J/K** (23× larger). |
| T3 | STRUCT | `twin_core.py:376` / `params.yaml lumped_thermal` | Disc ROM uses one `tau` for heat-up and cooldown, but `rom.UA` was derived from a FEM with `h_bottom_W_per_m2K=25` ("enhanced convection facing coils"). That enhancement only exists while the coils are hot. |
| T4 | BUG | `params.yaml lumped_thermal.hA_inner/outer` | Refit with the **linear** steady-state equation, but the deployed code applies the **nonlinear** `hAEff`. Shipped model settles at 72.15/67.78 °C at 7.8 A/29 °C, not the calibrated **79.00/74.00**. Same bug class as B1 (2026-07-11). |
| T5 | OPEN | `params.yaml air_node_C/hA_far` | Both self-labelled "illustrative"; τ_air = 75 s. This is the node every other node dumps into, so it caps how long the whole rig can stay warm. Never fit to anything. |
| V1 | FEAT | `build_twin_html_fem.py:1460-1464` JS `SCENARIOS` + `twin_core.py:46-47` | No fast start-up ramp. Existing `ramp` is 60 s; user wants 0→5 A in 5–10 s, auto-running on load. |
| V2 | BUG | `build_twin_html_fem.py:1725` / `twin_core.py:405` | `fadeIn = max(0, 1 − z/jit_fade_mm)` with `jit_fade_mm=0.5 mm` kills all disc motion once the gap exceeds 0.5 mm. Above ≈3.2 A the gap is already ≥3 mm → the disc is perfectly still at every operating current. |

---

## L1/L2 — the R=80 disc floats highest (issue 2)

### Reproduction

Full `compute_lift_force(cfg, I_amplitude=cfg.I_peak)` sweep, 10 z-points from
1 mm to 18 mm, per radius (default EM mesh, `fine_step_mm=2.0`):

| R [mm] | m [kg] | F_grav [N] | F(1) | F(3.8) | F(5) | F(9) | F(13) | **true z_eq [mm]** | z0 (F1/F5) | I_lev_min |
|--------|--------|------------|------|--------|------|------|-------|--------------------|------------|-----------|
| 65 | 0.10751 | 1.0547 | 4.785 | 4.275 | 3.363 | 2.194 | 1.433 | **15.74** | 11.34 | 2.50 A |
| 70 | 0.12469 | 1.2232 | 5.085 | 4.520 | 3.565 | 2.322 | 1.510 | **14.95** | 11.26 | 2.58 A |
| 75 | 0.14314 | 1.4042 | 4.969 | 4.420 | 3.495 | 2.285 | 1.489 | **13.58** | 11.37 | 2.75 A |
| 80 | 0.16286 | 1.5977 | 4.581 | 4.104 | 3.263 | 2.149 | 1.407 | **11.86** | 11.79 | 3.02 A |

The physics is **monotone and correct**: mass grows as R² while the lift
saturates, so the *smallest* disc should float *highest*, and R=80 should be
the **lowest** of the four. `z_eq(R=80)=11.86 mm` also reproduces the
`params.yaml` value 11.7 mm (different sweep resolution), so the R=80 path is fine.

### What the twin actually bakes

Extracted from `outputs/digital_twin_fem.html` `PARAMS.plate_variants[*].lev`:

| variant | z_gap_5A_mm baked | true | I_lev_min baked |
|---------|-------------------|------|-----------------|
| R=65 | **5.000** | 15.74 | 4.011 A |
| R=70 | **5.000** | 14.95 | 4.004 A |
| R=75 | **5.000** | 13.58 | 4.013 A |
| R=80 | 11.700 | 11.86 | 3.044 A |

All three small discs sit at *exactly* 5.000 — the signature of a clamp.

### Root cause

`_lev_anchor()` evaluates F at only three z values and interpolates:

```python
F1, F38, F5 = F_at(1.0), F_at(3.8), F_at(5.0)
...
zs = np.array([1.0, 3.8, 5.0]); Fs = np.array([F1, F38, F5])
order = np.argsort(Fs)
out["z_eq_5A_mm"] = round(float(np.interp(F_grav, Fs[order], zs[order])), 2)
```

`np.interp` **clamps to the endpoint** outside its x-range. For R=65,
`F_grav=1.0547 N` is below `F(5 mm)=3.363 N`, so the query lands off the left
end of the sorted table and returns `zs[order][0] = 5.0`. Verified directly:

```
_lev_anchor np.interp result for R=65mm: 5.0     (true crossing: 15.74)
```

The z-table simply does not reach far enough — the true crossings are at
13–16 mm, three times past its last point.

R=80 escapes because `lev_params()` branches:

```python
if abs(radius_mm - default_radius) < 0.5:
    z_gap_5A = float(lv.get("z_gap_5A_mm", 4.1))   # params.yaml, real 10-pt sweep
else:
    anchor = LEV_ANCHORS.get(radius_mm) or _lev_anchor(...)   # clamped 3-pt table
```

So the *only* reason R=80 looks different is that it uses a different,
better method — **L2**, a split single-source-of-truth. (`LEV_ANCHORS`'s
hardcoded R=80 row is also stale: `z_eq_5A_mm: 4.15`, `z0_decay_mm: 13.63`,
both from the pre-2026-07-10 geometry.)

### Fix

1. Replace the 3-point `np.interp` in `_lev_anchor()` with a real bracketing
   root-find on `F(z) − F_grav` over a wide range (e.g. z = 1 → 40 mm, coarse
   scan to bracket + bisection/`brentq` to converge). Keep the F(1)/F(5)
   `z0_decay_mm` fit as-is — those values (11.26–11.79 mm) are already
   consistent across all four radii and match `params.yaml`.
2. Delete the `abs(radius_mm - 80) < 0.5` special case in `lev_params()` so
   **every** radius, including R=80, comes from the same code path. Confirm the
   result reproduces 11.7–11.9 mm for R=80 (it does: 11.86 mm).
3. Purge the stale `LEV_ANCHORS` R=80/R=101 rows or regenerate them.

Expected after the fix: gaps ordered 65 > 70 > 75 > 80, lift-off currents
ordered 2.50 < 2.58 < 2.75 < 3.02 A — i.e. the small discs lift **earlier and
higher**, exactly opposite to what ships today.

---

## T1–T5 — everything cools far too fast (issue 1)

### Reproduction

Driving the SSOT integrator `twin_core.TwinState` with the shipped baked
`PARAMS` (heat to steady state at 5 A / T_amb=20 °C, then I=0):

```
STEADY @5A: inner=40.62 outer=38.47 iron=45.58 air=22.80 disc=57.54

COOLDOWN (I=0):   t[s]   inner   outer    disc     air   | % of rise lost: coil / disc
                    10   38.67   36.54   56.26   22.78   |   9.4% /  3.4%
                    60   32.75   30.87   50.38   22.29   |  38.1% / 19.1%
                   120   29.59   28.00   44.47   21.66   |  53.5% / 34.8%
                   300   26.61   25.42   32.91   20.82   |  68.0% / 65.6%
                   600   25.12   24.22   25.04   20.52   |  75.2% / 86.6%
```

The inner coil loses **half its temperature rise in 102 s**. On the real rig
this takes many minutes.

### T1 — coil node gets all the power but a fifth of the mass

`lumped_physics()` builds a two-node coil (IR-visible surface + winding-core
reservoir):

```python
"C":      coil_C_solid(c) * coil_C_scale,        # 246.7 J/K  (inner)
"C_deep": coil_C_solid(c) * (1 - coil_C_scale),  # 854.0 J/K
"G_wind": G_wind,                                # 1.0 W/K
```

but `_rom_step` puts the **entire** `P_ref` into the surface node and gives the
deep node **no source at all**:

```python
q = nd.P_ref * s2                      # 100% of the loss -> surface
...
g = nd.G_wind * (T[deep_key] - T[k])
T[k]        += (q + g - out) / nd.C * dt          # C = 22.4% of the copper
T[deep_key] += (-g) / nd.C_deep * dt              # no q term
```

So `dT/dt|₀ = P/(0.2241·C_solid)` — 4.46× the physical rate — and the deep
reservoir, holding 77.6 % of the copper, is coupled through only 1.0 W/K
(`coil_G_wind_W_per_K`, whose own params.yaml note says "order-of-magnitude").
Eigenvalues of the shipped 2-node coil: **τ_fast = 61 s**, τ_slow = 1166 s with
a small amplitude. The fast mode is what the user sees.

Physical bound: `C_solid_inner = 1101 J/K`, `hA_inner = 2.949 W/K` → τ ≥ **373 s**.

**Fix**: split `P_ref` in the same ratio as `C`, i.e.
`P_surf = P_ref·coil_C_scale`, `P_deep = P_ref·(1−coil_C_scale)`.

Steady state is **provably unchanged**: at steady state the deep node gives
`P_deep = G(T_s − T_d)`, so the surface balance becomes
`P_surf + P_deep = hA(T_s − T_air)` — identical to before. Verified
numerically: `ss@7.8A/29 °C = 72.148/67.780 °C` for the baseline **and** for
every P-split variant tested, to 3 decimals.

⚠️ **Integrator-stability trap**: the deep-node update is forward Euler, so
`dt < 2·C_deep/G_wind`. `TwinState.step()` substeps at `tau*0.05 ≈ 12.2 s`.
With `coil_C_scale=0.95` the deep node is only 55 J/K, so `G_wind` above ~8 W/K
goes unstable at that substep (observed: temperatures diverge). Any refit must
either keep `G_wind` bounded or tighten the substep rule.

### T2 — the iron node's heat capacity is the aluminium disc's

```python
"iron": { "C": 0.5 * C_plate, ... }     # 73.3 J/K
```

`C_plate` is the *levitating aluminium disc*. Half of it is not a model of the
iron core + ring by any argument. From `params.yaml` geometry
(core r ≤ 25.9 mm, ring r = 64.9–79.9 mm, both z = −53…0 mm, ρ·cp for iron
= 7870·450 = 3.5415e6 J/m³K):

```
V_core = π·0.0259²·0.053            = 1.117e-4 m³
V_ring = π(0.0799²−0.0649²)·0.053   = 3.616e-4 m³
C_iron = 3.5415e6 · 4.733e-4        = 1676 J/K       (model: 73.3 — 23× low)
```

The iron sits directly under both coils and the disc and is by far the rig's
largest slow reservoir. Under-sizing it by 23× removes the long tail from the
whole network.

### T3 — the disc has one τ for heating and cooling

`rom.py:90-103` derives `UA = P_ref/dT_mean` from a FEM steady state whose
boundary conditions are

```yaml
h_convection_W_per_m2K: 10.0    # top + side surfaces (natural convection)
h_bottom_W_per_m2K: 25.0        # bottom surface facing coils (enhanced convection)
```

The 25 W/m²K is explicitly the coil plume. When the current is off the plume
dies and the bottom relaxes to natural convection. With
A_top = A_bot = 0.0201 m², A_edge = 0.00151 m²:

```
UA_heat ∝ 10·A_top + 25·A_bot + 10·A_edge = 0.719
UA_cool ∝ 10·A_top + 10·A_bot + 10·A_edge = 0.417     ratio 0.58
τ_cool / τ_heat = 1/0.58 = 1.72  ->  τ_cool ≈ 421 s   (shipped: 244 s for both)
```

Independent sanity check: C_disc = 146.6 J/K, natural-convection hA ≈ 0.2–0.4 W/K
→ τ = 350–700 s. 421 s sits inside that band; 244 s does not.

**Fix**: scale the ROM τ by the already-computed `coilAirDrive()` (a 0…1
plume proxy that decays as the coils cool):

```
tau_eff = tau_ref / (f_nat + (1 - f_nat) * min(1, airDrive))     f_nat = 0.58
```

τ only sets the *rate*; `beta`'s target is untouched, so the steady state is
exactly preserved.

### T4 — the hA refit used a formula the code doesn't run

`params.yaml` documents the refit as

```
T_inner = T_amb + P_inner(7.8A)/hA_inner + AIR_DT_SS
```

which is **linear** in hA and gives exactly 79.00/74.00 °C. But the deployed
`romStep`/`_rom_step` applies

```python
hA_use = hA_cal * (max(|dT|,0.1) / dT_cal) ** 0.25
```

and `dT_cal` was anchored at `I_ref = 5 A`, so at 7.8 A the correction pushes
`hA_eff` above `hA_cal` and the coils settle **cooler**. Verified against the
SSOT `TwinState` (not a re-implementation):

```
TwinState ss@7.8A/29C: inner=72.148  outer=67.780  iron=82.514  air=35.832
Documented calibration target:  inner=79.00  outer=74.00
```

→ **−6.85 °C / −6.22 °C** at the one point the calibration claims to match
exactly. Solving the same constraint through the *nonlinear* model gives
`hA_inner = 2.4744`, `hA_outer = 2.8885` (from 2.9493/3.4509).

This also partly explains why the ramp fit needed such a small `coil_C_scale`:
with the asymptote sitting ~5 °C too low, the only way to reach the measured
ramp points in 450 s was to make the model fast.

### T5 — the shared air node was never fit

```yaml
air_node_C_J_per_K: 3000.0     # shared local-air thermal mass (illustrative)
air_node_hA_far_W_per_K: 40.0  # local air -> far ambient (illustrative, unchanged)
```

τ_air = 75 s. Every other node dumps into this one, so it caps the whole rig's
memory at ~2 min. `hA_far = 40 W/K` over a rig surface of ~0.2 m² implies
h ≈ 200 W/m²K, which is not natural convection — it is a fudge factor. Left as
**OPEN**: it cannot be pinned without a real cooldown log.

### Combined effect (verified)

Heat to 5 A steady state at 20 °C, then I = 0. `t50`/`t90` = time to lose
50 %/90 % of the temperature rise:

| variant | ramp RMS | coil t50 | coil t90 | disc t50 | disc t90 |
|---------|----------|----------|----------|----------|----------|
| **BASELINE (shipped)** | 2.53 °C | **102 s** | 2032 s | **194 s** | 712 s |
| T1+T2, `cs=0.5, gw=3` | 9.51 °C | 414 s | 1858 s | 210 s | 826 s |
| T1+T2+T3, `cs=0.5, gw=3` | 9.51 °C | 414 s | 1858 s | 228 s | 1000 s |
| T1+T2+T3, `cs=0.35, gw=2` | 10.99 °C | 528 s | 2346 s | 228 s | 1058 s |
| T1+T2+T3, `cs=0.2241, gw=1` | 13.47 °C | 888 s | 3752 s | 228 s | 1250 s |

Coil `t50` moves from 102 s to 414–888 s — a 4–9× slowdown, matching the
user's report.

### ⚠️ The trade-off, stated honestly

Fixing T1+T2 raises the `thermal_ramp_test` RMS from **2.53 °C to 9.5–13.5 °C**.
That is not a regression to hide — it means the ramp data and the physical
thermal mass are **mutually inconsistent**, and the 2026-07-02 fit bought its
2.53 °C by shrinking the copper mass 4.5× below physical.

Evidence that the ramp data is the weaker constraint:

- `params.yaml` itself labels it *"Treat tau as order-of-magnitude (fit from
  narrated `thermal_ramp_test`)"* — the 5 points were read off a video, not logged.
- It is **internally inconsistent**: the t=300 s point (48.5 °C, end of the 5 A
  stage) already **exceeds** the model's own 5 A asymptote (~43–44 °C
  nonlinear, 47.5 °C linear). No first-order model can fit that.
- Reaching 40 °C at t=140 s from an 18.5 K asymptote requires τ ≈ 155 s. Pinning
  τ=155 s with the physical C=1139 J/K forces hA_outer = 7.35 W/K, which
  predicts T_outer_ss = 46.7 °C at 7.8 A — flatly contradicting Session 1's
  measured 74 °C. **Session 1 and Session 2 cannot both be fit by the current
  network structure**, whatever the constants.
- The user's direct observation ("cooling is very slow; we sometimes need
  active cooling") is a *new, independent* constraint the model has never been
  fit against, and it agrees with the physical thermal mass.

**Recommendation**: ship the structural fixes (they cost nothing at steady
state and are provably correct in form), record the ramp-RMS regression in
`docs/CHANGELOG.md`, and promote **"log a real cooldown curve + a properly
timestamped heat-up ramp"** to the top of the NEXT list. Do **not** re-shrink
`coil_C_scale` to chase the 2.53 °C — that is fitting noise with a
non-physical parameter.

---

## V1/V2 — no fast ramp, no visible oscillation (issue 3)

### V1 — start-up ramp

`SCENARIOS` (JS `build_twin_html_fem.py:1460-1464`, Python
`twin_core.py:33-47`) offers `step / ramp / sine / pulse`. `ramp` is
`min(t/60, 1)·I` — a 60 s ramp, and the default scenario is `step`, so on load
the current jumps to 5 A in one frame and the disc snaps to its gap.

**Fix**: add a `quickstart` scenario, `min(t/t_rampup, 1)·I` with
`t_rampup` from `params.yaml` (default 8 s, user asked for 5–10 s), select it
as the default on load and on reset, and add it in **both** `SCENARIOS` dicts
(`twin_core.py` is the SSOT that `digital_twin.py` imports; the JS copy is
what the HTML runs).

### V2 — the disc is frozen at every operating current

```js
const fadeIn = Math.max(0, 1 - lev.z / JIT_FADE_MM);   // JIT_FADE_MM = 0.5 mm
if (I > 0.05 && fadeIn > 0) { ...jitter... } else { lev.jit = 0.0; }
```

Jitter is a **sub-lift-off** effect only: it is fully faded out once the gap
exceeds 0.5 mm. With `z_gap_eq(I) = 11.7 + 2·11.79·ln(I/5)`:

| I | gap | jitter |
|---|-----|--------|
| 3.04 A (I_lev_min) | 0.00 mm | on |
| 3.2 A | 1.21 mm | **off** |
| 3.5 A | 3.29 mm | **off** |
| 5.0 A | 11.70 mm | **off** |

So above ≈3.2 A the disc is perfectly rigid apart from the ring-down after a
slider move (ζ(5 A)=0.02, ω=28.8 rad/s → dead in ~1.7 s).

**The honest physics.** A 1-DOF vertical spring–mass–damper *cannot* sustain
oscillation — it needs an excitation. The real one is the 100 Hz force ripple:
with `i(t) = Î sin ωt` and `F ∝ i²`, `F(t) = F_dc(1 − cos 2ωt)`, i.e. **100 %
modulation** at Ω = 2ω = 628 rad/s. Response of the 1-DOF system:

```
|X/X_static| = 1/|1 − (Ω/ω_n)²| = 1/|1 − (628/28.8)²| = 0.00211
X_static     = g/ω_n² = z_decay = 11.79 mm
X_ripple     = 11.79 × 0.00211 = 0.0249 mm  ≈ 25 µm
```

25 µm at 100 Hz is both invisible and far above the render frame rate. So the
*visible* wobble on the real rig is not the vertical 100 Hz mode — it is the
lateral/tilt mode, which has a much lower natural frequency (a few Hz) and is
only marginally stable.

**Fix**: keep the two effects separate and explicitly labelled, following the
precedent already set by `z_gap_exaggeration`:

- `jit_contact` — the existing sub-lift-off buzz, still gated by `jit_fade_mm`.
  Unchanged.
- `jit_lev` — **new**, a sustained shimmer while levitating, amplitude ∝ I²
  (the ripple scales with the force), base amplitude the physically-derived
  0.0249 mm, multiplied by a separately-named, params-driven
  `lev_ripple_display_gain` (≈40 → ~1 mm on screen). The physical number stays
  traceable; the exaggeration is named and visual-only, exactly like
  `z_gap_exaggeration: 2.0`.
- Optionally a slow tilt/wobble (2–4 Hz, two incommensurate phases) — the
  visually honest representation of the real lateral instability. Must be
  flagged **display-only**.

Every new constant goes in `params.yaml levitation:` with a `# DISPLAY ONLY`
comment, so none of it can be mistaken for a validated physics term
(CLAUDE.md Conventions: *"Every new physics term needs an energy-balance /
sanity check before use"*).

---

## Verified clean — do not re-check next session

- `twin_core.py`'s port of `romStep`/`levStep` is bit-faithful to the baked JS.
  An independent re-implementation reproduced `TwinState` to 3 decimals
  (`inner=72.148 outer=67.780 iron=82.514 air=35.832` at 7.8 A/29 °C) — the
  traps 1–9 documented in `twin_core.py` are all correctly ported. Fix the
  physics in **both** copies; do not "fix" the port.
- `z0_decay_mm` from the F(1 mm)/F(5 mm) method is consistent across all four
  radii (11.26–11.79 mm) and agrees with `params.yaml`. Only `z_eq` is broken
  (L1), not the decay length.
- The 4-point `dial_to_current_A` interpolation, the `I_amplitude=cfg.I_peak`
  force convention, and the `AIR_P_SUM_REF` coil+iron-only air-node sum
  (2026-07-11 B1) are all still correct.

---

## Fixed this session (docs/PROMPT_WP_COOL_LEV_2026-07-28.md work order)

Verification: `python xval_twin.py` — **PASS** (assertion A: bit-exact across
all 7 integrator schedules + the dt=25s substep check; assertion B: 0 relative
diff, baked HTML matches a fresh `lumped_physics()`/`ThermalROM().build().tau`).
Full narrative + before/after numbers → `docs/CHANGELOG.md`'s
"WP-LEV / WP-COOL / WP-SHIMMER" entry.

| # | Sev | File | What was wrong | Fix | Commit |
|---|-----|------|-----------------|-----|--------|
| L1 | BUG | `build_twin_html_fem.py` `_lev_anchor()` | 3-point `np.interp` clamped `z_eq` to exactly 5.000mm for every disc whose true crossing lay past 5mm (R=65/70/75). | Real bracketing root-find (coarse scan z=1→40mm, `scipy.optimize.brentq` to converge), with a persistence check guarding against a real mesh-quantization notch found near z=14mm for R=70mm. | (this session) |
| L2 | BUG | `build_twin_html_fem.py` `lev_params()` | R=80mm special-cased straight to `params.yaml`'s own anchor while every other radius used the (buggy) `_lev_anchor()` — split SSOT. | Special case deleted; every radius goes through the same `_lev_anchor()` call now. R=80 reproduces `params.yaml`'s 11.7mm to within 0.24mm. | (this session) |
| — | STRUCT | `LEV_ANCHORS` dict | Hardcoded R=80/R=101 rows from the pre-2026-07-10 geometry, dead-wrong (`z_eq_5A_mm: 4.15`). | Deleted outright; every anchor is live-computed via `_lev_anchor()`. | (this session) |
| T1 | STRUCT | `build_twin_html_fem.py` `lumped_physics()` + `twin_core.py` `_rom_step` | Coil surface node got 100% of `P_ref` but only `coil_C_scale`=22.4% of the copper mass → 4.46× too-fast heat-up AND cooldown. | `P_ref` now split `P_ref_surf`/`P_ref_deep` in the same ratio as `C`/`C_deep`; steady state provably unchanged. Both `NodeCoeffs`/JS default to the old (100%-surface) behaviour if the new keys are absent. | (this session) |
| T2 | STRUCT | `build_twin_html_fem.py` `lumped_physics()` | Iron node `C = 0.5*C_plate` = 73.3 J/K — half the aluminium DISC's capacity, unrelated to iron. | Real `C_iron = rho_Fe*cp_Fe*(V_core+V_ring)` from `iron_core:`/`outer_iron_ring:` geometry + new `material_props.iron` block → 1676.3 J/K (23× larger). | (this session) |
| T3 | STRUCT | `twin_core.py` `_rom_step` / JS `romStep` | Disc ROM used ONE τ for heat-up and cooldown, but `rom.UA` came from a FEM with the coil-plume-enhanced bottom BC, which dies with the current. | New `disc_tau_cool_natural_frac(cfg)` (computed from `thermal_bc` h-values + disc geometry, = 0.5804) drives a runtime `tau_eff` in both β-target updates; β targets untouched, steady state unaffected. | (this session) |
| T4 | BUG | `params.yaml` `lumped_thermal.hA_inner/outer_W_per_K` | Refit with the LINEAR steady-state formula; deployed code applies the NONLINEAR `hAEff` correction on top — shipped model settled at 72.15/67.78°C at 7.8A/29°C instead of the calibrated 79.00/74.00°C (same bug class as B1, 2026-07-11). | New committed `refit_hA.py` root-finds hA through the ACTUAL `TwinState` integrator (with T1+T2 already applied) → hA_inner=2.4744, hA_outer=2.8885 (from 2.9493/3.4509). Reproduces 79.00/74.00°C exactly. | (this session) |
| T5 | OPEN | `params.yaml` `air_node_C/hA_far` | Both self-labelled "illustrative", never independently fit. | Left UNCHANGED — comments rewritten to state explicitly they are unidentified fudge factors, blocked on real cooldown data (promoted to top of CLAUDE.md NEXT list). | (this session, not fixed — documented) |
| V1 | FEAT | `build_twin_html_fem.py` JS `SCENARIOS` + `twin_core.py` | No fast start-up ramp; default scenario `step` snapped current to 5A in one frame. | New `quickstart` scenario (0→I over `transient.quickstart_ramp_s`=8s), now the HTML's default on load/reset. Added to both `SCENARIOS` dicts. | (this session) |
| V2 | BUG | `build_twin_html_fem.py` / `twin_core.py` `_lev_step`/`levStep` | `jit_fade_mm=0.5mm` killed ALL disc motion above ≈3.2A — the disc was perfectly rigid at every real operating current. | New `jit_lev` term, active whenever `z>0` (levitating), amplitude = COMPUTED `x_ripple_mm` (1-DOF forced-response to the real 100Hz ripple, ≈0.0249mm) × new `lev_ripple_display_gain=40` (`# DISPLAY ONLY`). Kept fully separate from the existing `jit_contact`. Verified: `mean(z+jit)` stays within 0.001mm of `z_gap_eq(I)` at every tested current — never biases the mean gap. | (this session) |
