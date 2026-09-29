# Numerical Methods & Open-Source Libraries — Summary

> Prepared 2026-07-31, in direct response to the professor's Juli 2026 feedback: he
> confirmed reading `REPORT_WHY_CUSTOM_CODE.md` (why custom Python vs. commercial CAE)
> but asked for a short, explicit list of the concrete mathematical methods/algorithms
> solved in the code, and the open-source libraries used. Theory is secondary here —
> see `docs/physics.md` for the full physics formulation this implements.

## 1. Electromagnetics — `em_solver.py`

**Equation solved** (complex phasor PDE for the azimuthal vector potential):

    -∇·(ν∇A_φ) + ν·A_φ/r² + jωσ·A_φ = J_s      ν = 1/(μ_r·μ0), ω = 2πf

**Method:** axisymmetric Galerkin weak form (volume weight `2πr`), discretized with
**linear (P1) triangular finite elements** on a structured 2D (r,z) mesh
(`solve_em()`). Assembly produces a **complex-valued sparse matrix** `K` (complex
because of the `jωσ` term); solved with:

    scipy.sparse.linalg.spsolve(K.tocsc(), F)     # direct sparse LU, complex arithmetic

**Nonlinear extension** (`solve_em_saturating()`): iron saturation (B–H) handled by
**fixed-point (Picard) iteration** — re-solve with an updated local `ν(B)` each pass,
≤20 iterations, convergence tolerance 2%.

**Post-processing:**

- `B_r = -∂A_φ/∂z`, `B_z = (1/r)∂(r·A_φ)/∂r` from P1 element gradients.
- Joule loss density `q = ½·σ·ω²·|A_φ|²` (cycle-averaged).
- Lift force (`compute_lift_force()`): direct **Lorentz-force volume integral**
  `F_z = Σ_elements -½·Re[J_φ·B_r*]·2π·r_c·A_e` (cycle-averaged) — not a
  Maxwell-stress-tensor surface integral.

## 2. Thermal — `thermal_solver.py`

**Equation solved:** steady axisymmetric heat conduction with convective (Robin) BC:

    -∇·(k∇T) = q ,      -k·∂T/∂n = h(T - T∞)

**Method:** same P1 axisymmetric FEM (real-valued this time). Real sparse system
`K·T = F`, solved with `scipy.sparse.linalg.spsolve(K.tocsr(), F)`.

**Mesh-to-mesh mapping:** the EM loss map (computed on the EM mesh) is transferred
onto the thermal mesh via `scipy.interpolate.LinearNDInterpolator` (barycentric
interpolation), with `NearestNDInterpolator` as a fallback for points outside the
convex hull.

**Verification:** energy balance `∫q dV = ∫h(T-T∞) dA` — passes at 0.000% residual.

## 3. Reduced-order model (offline → real-time bridge) — `rom.py`

**Model reduction:** rank-1 modal ansatz — one fixed spatial mode from the FEM
steady solve, one time-varying scalar amplitude:

    T(r,z,t) = T_amb + β(t)·ΔT_ref(r,z)

**Governing ODE** for the amplitude (first-order lag + σ(T) nonlinear feedback
`s(·)`):

    τ·dβ/dt = (I/I_ref)²·s(β·ΔT_mean_ref) - β

**Solved with:** `scipy.integrate.solve_ivp`, explicit adaptive Runge–Kutta,
`method="RK23"` (Bogacki–Shampine, order 2(3)).

## 4. Real-time twin engine — `twin_core.py` (SSOT integrator, also baked as JS)

**Thermal side:** lumped-parameter RC network (multiple capacitive nodes — coil
surface, coil winding-core/"deep", iron, shared air), each node obeying
`C·dT/dt = ΣQ_in - ΣQ_out`. Integrated with **explicit (forward) Euler**,
sub-stepped (`n_sub = ceil(dt / (0.05·τ))`) for numerical stability against the
fastest node's time constant.

**Mechanical side (levitation):** linear 1-DOF spring–mass–damper. Integrated using
the **exact closed-form analytical solution** for underdamped decay
(`exp(-ζωt)·(cos ω_d t, sin ω_d t)` terms) rather than numerical time-stepping,
since the system is LTI within each control step — exact regardless of step size.

## 5. Calibration — `refit_hA.py`

**Problem:** inverse/calibration — find `hA_inner`, `hA_outer` such that the steady
state of the **actual nonlinear `TwinState` integrator** (not a hand-derived linear
formula) matches two measured coil temperatures.

**Method:** `scipy.optimize.fsolve` — multivariate root-finding (MINPACK `hybrd`, a
quasi-Newton method) on the 2-equation residual system.

## 6. Cross-validation — `xval_twin.py`

Not a simulation method — a **numerical regression test**: runs the Python
integrator and the equivalent JavaScript baked into `outputs/digital_twin_fem.html`
side-by-side via a headless browser (Playwright) and diffs them at machine
precision (abs 1e-9), plus a "bake freshness" check (rel 1e-6).

## Open-source libraries used

| Library                                     | Used for                                                                                                                                                                                                                                |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **NumPy**                                   | Dense array/linear algebra throughout                                                                                                                                                                                                   |
| **SciPy**                                   | `sparse` / `sparse.linalg.spsolve` (direct sparse solves, EM + thermal), `integrate.solve_ivp` (ROM transient), `optimize.fsolve` (hA calibration), `interpolate.LinearNDInterpolator` / `NearestNDInterpolator` (mesh-to-mesh mapping) |
| **PyYAML**                                  | Loading `params.yaml` (single source of truth for all parameters)                                                                                                                                                                       |
| **Matplotlib** (+ `mpl_toolkits.mplot3d`)   | 2D field plots, interactive twin (`digital_twin.py`), 3D revolve preview                                                                                                                                                                |
| **trimesh** (optional)                      | GLB export (`visualize.py`); falls back to a plain OBJ writer if not installed                                                                                                                                                          |
| **qrcode**                                  | QR code generation (`gen_qr.py`)                                                                                                                                                                                                        |
| **PyVista / VTK** (optional, `extensions/`) | Desktop 3D twin — kept out of the core dependency set (see `extensions/README.md`)                                                                                                                                                      |
| **Playwright** (dev/test only)              | Cross-validation of the baked JS twin against the Python integrator (`xval_twin.py`) — not part of the simulation itself                                                                                                                |
