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

## 9. First quantitative result (current config, î=5 A)
Plate eddy ≈ 3.0 W, iron eddy ≈ 0.6 W, coil ohmic ≈ 73 W → **coils dominate the
heating**. Coil loss depends strongly on the true wire gauge/turns — confirm those.
I²-scaling verified exactly (P(2î)/P(î) = 4.000). Absolute values await benchmark calibration.
