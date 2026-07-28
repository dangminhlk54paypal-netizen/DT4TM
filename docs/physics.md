# Physics & Backend Formulation — Thermal Digital Twin (TEAM 28-like Levitator)

Reference for everyone building the backend. All quantities in SI.
Device: aluminium plate above two copper coils (inner 1000 / outer 500 turns),
**with iron cores** (not in the original TEAM 28), driven at î ≈ 5 A, 50 Hz.

## 0. The three-step physics chain
1. **Electromagnetics** — AC coil current → time-varying B field → eddy currents
   in the aluminium plate (and iron, if solid).
2. **Joule heating** — ohmic loss in coils + eddy loss in plate/iron = heat source.
3. **Heat transfer** — Fourier conduction + convection/radiation → temperature field T(r,z,t).

The device is axisymmetric, so we solve in 2D (r, z) and revolve to 3D for display.

## 1. Electromagnetic problem (harmonic / phasor)
Only the azimuthal vector-potential component A_φ(r,z) is nonzero. As a complex
phasor it satisfies

    -∇·(ν ∇A_φ) + ν·A_φ/r² + jωσ·A_φ = J_s ,   ν = 1/μ = 1/(μ_r·μ0),  ω = 2πf

- `J_s` = source current density in the coils = ± N·î / S_coil (azimuthal).
  Inner and outer coils carry **opposite** signs (opposite winding sense).
- `jωσ·A_φ` is the induced-eddy reaction in any conductor (σ > 0): plate, iron.
- **Iron cores**: regions with large μ_r → small ν → they concentrate/steer flux.
- Boundary conditions: A_φ = 0 on the axis r=0 (symmetry) and on the far outer
  boundary (field decays; place it ~3–5× the device size away).

### Domain size (1×1×1 m bounding box)
Professor (Juni 2026): a 1×1 m box should be sufficient for the 2D axisymmetric
domain (r_max=500mm, z ∈ [−500, 500] mm). **Validation method**: run the same
problem with (a) Dirichlet BC (A_φ=0 on boundary) and (b) Neumann BC (∂A_φ/∂n=0).
If the field near the device is identical in both cases, the boundary is far enough
away. If not, enlarge the box.

Magnetic flux density: B_r = -∂A_φ/∂z, B_z = (1/r)∂(r A_φ)/∂r.

### Joule loss density (the heat source)
Eddy-current density (phasor) in a conductor: J_e = -jωσ·A_φ, so |J_e| = ωσ|A_φ|.
**Cycle-averaged** loss density (the ½ comes from averaging sin²):

    q(r,z) = |J_e|² / (2σ) = ½·σ·ω²·|A_φ|²      [W/m³]

(Note: the heat source is `q = |J|²/σ`, NOT `|∇T|²/σ` — correcting the handwritten note.)

Coil ohmic loss (more physical for many thin turns than the homogenized J_s):

    P_coil = ½·î²·R ,   R = N·(2π·r_mean)/(σ_Cu·A_wire),  A_wire = π(d_wire/2)²

## 2. The σ(T) question — "ODER?" answered: YES, include it
Aluminium/copper conductivity drops with temperature, α ≈ 0.0039 /K:

    σ(T) = σ0 / (1 + α·(T − T0))

A 70 K rise changes resistance ~27% — not negligible. The two effects oppose:
- Plate eddy loss ∝ σ_Al  → hotter plate slightly **lowers** its own eddy loss.
- Coil loss ∝ 1/σ_Cu      → hotter coil **raises** its ohmic loss.

**This does NOT break real-time.** In Model A the eddy reaction on the coils is
negligible, so the spatial field pattern is fixed by the coils alone — only the
*amplitude* of each loss map scales. The real-time law generalizes to:

    q_plate(r,z; î,T̄) = q̂_plate(r,z)·(î/î_ref)²·[σ_Al(T̄_plate)/σ_Al(T_ref)]
    q_coil (î,T̄)      = P̂_coil      ·(î/î_ref)²·[σ_Cu(T_ref)/σ_Cu(T̄_coil)]

where q̂ is computed **once** offline by the FEM EM solve. At runtime: one scalar
multiply per body. Because thermal dynamics are slow (seconds) vs EM (ms), update
σ from the previous step's mean temperature — weak one-way lagged coupling, no
inner iteration needed. Implementation: solve EM once at σ(T_ref); apply
`sigma_tempco_per_K` as a runtime multiplier (Phase 3).

## 3. Time-scale separation (avoid a common mistake)
Do NOT feed the instantaneous current i(t)=î·sin(ωt) into the heat source each
step. The 50 Hz current makes loss pulse at 100 Hz, but the thermal mass only
feels the **cycle average**. Solve EM once in **phasor form** and use the
cycle-averaged q above. Never time-step EM at 50 Hz inside the thermal loop.

## 4. Heat-transfer problem
Transient Fourier equation:

    ρ·c_p·∂T/∂t = ∇·(k ∇T) + q

Steady state: -∇·(k∇T) = q, with convection (Robin) BC: -k·∂T/∂n = h(T − T∞),
optional radiation εσ_SB(T⁴ − T∞⁴). Axisymmetric weak form uses the 2πr volume
weight (see README "Axisymmetric FEM math"). **Required check:** at steady state
Q_in (∫q dV) must equal Q_out (∫h(T−T∞)dA). The thermal solver passes this at 0.000%.

## 5. Iron cores — assumptions & caveats
- Modeled as a linear region with constant μ_r (e.g. 1000). At 5 A this is a
  first approximation; MMF = N·î = up to 5000 A-turns may push iron toward
  **saturation** → μ_r would drop and I²-linearity would weaken. Check B in the
  core; if |B| approaches ~1.5 T, add a nonlinear B–H curve (Phase 3+).
- If the core is **solid**, it has its own eddy loss (the solver computes it when
  σ_iron > 0). If **laminated**, set σ_iron ≈ 0 (or an effective low value).
- Confirm the actual core **geometry** with the rig — it strongly shapes the field.

## 6. Professor's three questions
**(a) How to discretize / mesh?** Skin depth in aluminium at 50 Hz is
δ = √(2/(ωμσ)) ≈ 12 mm, far larger than the 3 mm plate → eddy current is nearly
uniform through the thickness, so no ultra-fine through-thickness mesh is needed.
Refine instead near the coil–plate gap and outer edges. Iron skin depth is small;
if solid iron is included, refine near its surface. For EM, mesh the air too and
truncate far away (A=0).

**(b) Efficient solver libraries for large matrices / limited hardware?** In 2D
axisymmetric the system is small (~10⁴–10⁵ unknowns): `scipy.sparse.linalg.spsolve`
(direct) is enough. If it grows: CG + AMG (`pyamg`) for the SPD thermal system,
GMRES/BiCGSTAB for the complex EM system. The real answer for limited hardware is
the **ROM**: after the offline solve, runtime is O(n) vector math — runs on a phone.
For transient, use implicit Euler with a constant matrix → factor LU once, reuse every step.

**(c) Alternatives to per-element FEM each step?** Yes — recommended for the
real-time engine:
- **Modal decomposition**: linear system ⇒ T(t) = T_ss + Σ cᵢ·exp(-t/τᵢ)·φᵢ.
  Precompute eigenpairs once; transient becomes a sum of a few exponentials.
- **Lumped thermal RC network**: each body = a heat capacity C=ρc_pV linked by
  conductances; low-order ODEs, easy to **calibrate against sensors**. This is the
  natural bridge to measured data.
- POD/PGD or ML surrogates: later, if needed.

## 7. Real-time architecture (summary)
Offline (once): EM phasor solve → q̂_plate(r,z), P̂_coil, P̂_iron at (î_ref, T_ref).
Online (ms): given î and last T̄, scale by (î/î_ref)²·σ-factor → feed thermal ROM
(modal or RC) → T(r,z,t). Revolve to 3D for display / AR.

## 8. Validation strategy
1. EM solver must reproduce the ORIGINAL benchmark (config block
   `benchmark_team28_original`: 960/576 turns, 20 A, R=65 mm, no iron) — the lift
   force should balance gravity at z ≈ 11.3 mm (compare `levitation_height_team28.csv`).
2. Switch to the real rig (1000/500 turns, iron, 5 A) → loss maps.
3. Feed losses into the thermal solver → T field. Validate vs thermocouples/IR later.

## 9. Current quantitative result (current config, î=5 A)
Values below are the CURRENT output of `compute_losses(cfg)` — re-verified
2026-07-28 against the geometry re-measurement of 2026-07-10 (see CLAUDE.md
"Device numbers"). They supersede the pre-remeasurement figures (plate 3.0 W /
iron 0.6 W / coil 73 W) that this section used to quote:

| Body | P [W] |
|---|---|
| Plate eddy (Al disc) | 25.81 |
| Iron core + outer iron ring eddy | 5.86 |
| Coil ohmic (inner 52.32 + outer 54.12) | 106.44 |
| **Total** | **138.11** |

**Coils still dominate the heating** (77% of the total), but the plate's share
grew ~8.5× when the re-measured geometry put the Ø160 mm disc over the outer
iron ring — the losses REDISTRIBUTED rather than simply scaling. Coil loss
depends strongly on the true wire gauge/turns. B_max in iron = 0.66 T ≪ B_sat,
so the linear-μ_r assumption of §5 still holds. I²-scaling verified exactly
(P(2î)/P(î) = 4.000).

## 10. Sensor validation plan (Juni 2026)
Professor: team designs own measurement solution for thermal validation.

**Hardware:**
- Arduino (e.g. Uno/Nano) + thermocouple breakout (MAX6675 / MAX31855) or RTD (PT100)
- Infrared thermometer (handheld or USB) for surface temperature
- Measure: (a) copper core temperature, (b) bottom surface of the levitating disc

**Data pipeline:**
- Arduino reads sensor(s), sends CSV via serial USB to laptop
- `data_io.py` ingests CSV → T_meas(t) → feeds `rom.calibrate_UA()` to fit τ
- Shopping list (Reichelt/Conrad) → professor purchases

See `SENSOR_PLAN.md` for the detailed component list and wiring plan.

## 11. Lumped-network defects found 2026-07-28 — RESOLVED same session (WP-COOL,
see docs/BUG_REGISTER_2026-07-28.md T1-T5 / docs/CHANGELOG.md)
Section 6(c) recommends the lumped RC network as "the natural bridge to measured
data". The implementation in `build_twin_html_fem.py lumped_physics()` +
`twin_core.py _rom_step()` violated that formulation in four ways (all found by
comparing the twin's cooldown against the real rig — user report: the rig cools
*very* slowly; the twin cooled in ~100 s). (a)-(d) below are fixed; (a)/(b)/(d)
are structural/numeric fixes with steady state provably unchanged, (c) only
changes the transient rate. T5 (the shared air node, not covered here) is
explicitly left unfit — see the bug register.

**(a) Power and capacity were split inconsistently — FIXED.** The two-node coil
model (IR-visible surface + winding-core reservoir) assigned the surface node
`C = coil_C_scale·C_solid` (22.4 %) but the *entire* `P_ref`; the deep node had
no source term at all. So `dT/dt|₀ = P/(0.2241·C_solid)` — 4.46× the physical
rate. Fix: for a body split into sub-volumes, ohmic loss is now distributed with
the mass: `P_i = P·(C_i/C_total)` (`P_ref_surf`/`P_ref_deep` in
`lumped_physics()`/`NodeCoeffs`). With that split the steady state is *unchanged*
(deep node: `P_deep = G(T_s−T_d)`, so the surface balance still reads
`P_surf+P_deep = hA(T_s−T_air)`), only the transient becomes physical.
Physical bound for the inner coil: `C_solid = 1101 J/K`, `hA = 2.949 W/K` → τ ≥ 373 s.

**(b) The iron node's capacity was the wrong body's — FIXED.** `C_iron` was
coded as `0.5·C_plate` — half the *levitating aluminium disc's* heat capacity.
From the params.yaml geometry (core r ≤ 25.9 mm, ring r = 64.9–79.9 mm, both
53 mm tall, ρc_p,Fe = 7870·450 = 3.5415e6 J/m³K) the true value is **1676 J/K**,
23× larger (verified: `lumped_physics()` now computes `C_iron` from this exact
geometry and a new `material_props.iron` params.yaml block, and prints it —
`[LUMPED] C_iron=1676.3 J/K`). The iron sits under both coils and the disc and
is the rig's largest slow reservoir.

**(c) The disc's UA was a heating UA used for cooling too — FIXED.** `rom.py`
derives `UA = P_ref/ΔT_mean` from a FEM whose bottom face carries
`h_bottom = 25 W/m²K` ("enhanced convection facing coils"). That enhancement is
the coil plume; it vanishes when the current does. Area-weighting the two h's
gives `UA_cool/UA_heat = 0.58`, i.e. `τ_cool ≈ 1.72·τ_heat` (244 s → 421 s,
consistent with the 350–700 s natural-convection estimate for a 3 mm Ø160 disc).
Fix: `disc_tau_cool_natural_frac(cfg)` computes this ratio from the ACTUAL
`thermal_bc` h-values + disc geometry (never pasted); `_rom_step()`/`romStep()`
scale τ by it via `coilAirDrive()` (the already-computed plume proxy) each step.
τ sets only the rate, so making it plume-dependent leaves the steady state exact.

**(d) The convection nonlinearity was calibrated out of the loop — FIXED.**
`hA_inner/hA_outer` were fit with the *linear* balance
`T = T_amb + P/hA + ΔT_air`, but the code applies
`hA_eff = hA·(ΔT/ΔT_cal)^0.25` with `ΔT_cal` anchored at `I_ref = 5 A`. At
7.8 A the correction overshoots and the coils settled at **72.15/67.78 °C**
instead of the calibrated 79.00/74.00 °C. Fix: a new committed script,
`refit_hA.py`, root-finds hA by driving the ACTUAL `twin_core.TwinState`
integrator to steady state (not a hand-derived formula) — nonlinear-consistent
values **2.4744 / 2.8885 W/K** (from 2.9493/3.4509), reproducing 79.00/74.00 °C
exactly.

### Why a levitating disc oscillates — and why the 1-DOF model can't show it
With `i(t) = Î sin ωt` and eddy-current lift `F ∝ i²`, the force is
`F(t) = F_dc·(1 − cos 2ωt)`: **100 % modulated** at Ω = 2ω = 628 rad/s. The
vertical mode is `ω_n = √(g/z₀) = 28.8 rad/s` (f ≈ 4.6 Hz), so the forced
response is attenuated by `1/|1 − (Ω/ω_n)²| = 0.00211`. With
`X_static = g/ω_n² = z₀ = 11.79 mm` the ripple amplitude is

    X_ripple = 11.79 mm × 0.00211 ≈ 0.025 mm  (25 µm, at 100 Hz)

— invisible, and far above any render frame rate. **The wobble seen on the real
rig is therefore not the vertical 100 Hz mode**; it is the lateral/tilt mode,
which has a much lower natural frequency (a few Hz) and is only marginally
stable. A 1-DOF vertical spring–mass–damper has no excitation term and *cannot*
sustain motion — after a step it rings down (ζ(5 A)=0.02 → dead in ~1.7 s) and
then sits still. Any sustained shimmer added to the twin is therefore a
**display effect**: derive the 0.025 mm honestly, then apply a separately-named
`lev_ripple_display_gain`, exactly as `z_gap_exaggeration = 2.0` is handled today.

**RESOLVED 2026-07-28 (WP-SHIMMER V2, docs/BUG_REGISTER_2026-07-28.md V2):**
implemented exactly as derived above. `LevCoeffs.x_ripple_mm`/JS `X_RIPPLE_MM`
compute this amplitude at runtime from `z_decay_mm` + the mains frequency
(never pasted — verified 0.0249mm at the default R=80mm/50Hz constants,
matching the hand-derivation to 4 significant figures), scaled by
`levitation.lev_ripple_display_gain=40.0` (`# DISPLAY ONLY`) to ~1mm on screen.
Kept as a separate `jit_lev` term, active whenever the disc is actually
levitating (`z>0`), fully independent from the pre-existing sub-liftoff
`jit_contact` term (own phase accumulators, no shared state). Before this fix
the disc was rigid above ≈3.2A (`jit_fade_mm=0.5mm` gates `jit_contact` off
entirely once the gap clears 0.5mm) — now it visibly moves at every operating
current, with the mean position provably unbiased (`mean(z+jit) ≈ z_gap_eq(I)`
to <0.001mm, verified numerically).
