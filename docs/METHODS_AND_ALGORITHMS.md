# Methods and Algorithms — Thermal Digital Twin Implementation

**Document Date:** 2026-07-31

## Executive Summary

This document outlines the **concrete mathematical methods, equations, and open-source libraries** used for each component of the thermal digital twin. All code is pure Python with standard scientific libraries — no proprietary solvers or black-box approaches.

---

## 1. Electromagnetic Solver (`em_solver.py`)

### Method

**Finite Element Method (FEM) with Galerkin formulation**

- Element type: P1 triangles (linear basis functions)
- Formulation: weak form in 2D axisymmetric (r, z)
- Domain: 2D rectangular mesh with graded refinement (fine near device, coarse in far air)
- Only azimuthal vector potential A_φ is solved (3D axisymmetry reduction)

### Governing Equation (Phasor / Harmonic Formulation)

```
-∇·(ν ∇A_φ) + ν·A_φ/r² + jωσ·A_φ = J_s

where:
  ν = 1/μ = 1/(μ_r·μ₀)     [m/H] permeability reciprocal
  ω = 2πf = 100π           [rad/s] angular frequency (50 Hz → 100π rad/s in losses at 100 Hz)
  σ = conductivity          [S/m] in aluminum plate & iron
  J_s = source current      [A/m²] in coil windings
  j = complex unit
```

### Boundary Conditions

- **Dirichlet on axis (r=0):** A_φ = 0 (symmetry)
- **Dirichlet on outer boundary:** A_φ = 0 (field decays far away; placed at ±500 mm)

### Heat Source (Cycle-Averaged Joule Loss)

```
q(r,z) = ½·σ·ω²·|A_φ|²    [W/m³]

where the factor ½ arises from averaging sin²(ωt) over a cycle.
```

### Coil Ohmic Loss

```
P_coil = ½·î²·R

where R = N·(2π·r_mean)/(σ_Cu·A_wire) is the DC resistance of the coil.
```

### Solution Method

- **Linear system:** K·A = b (complex matrix)
- **Solver:** `scipy.sparse.linalg.spsolve()` (direct sparse LU decomposition)
- **Matrix assembly:** element-wise (one triangle at a time), using 2πr volume weight
- **I²-linearity check:** verify P(2î)/P(î) = 4.0 exactly (validates phasor linearity)

### Key Open-Source Libraries Used

- `numpy`: array operations, complex arithmetic
- `scipy.sparse`: sparse matrix construction (CSR format)
- `scipy.sparse.linalg.spsolve`: direct sparse solver

---

## 2. Thermal Solver (`thermal_solver.py`)

### Method

**Finite Element Method (FEM) with Galerkin formulation**

- Element type: P1 triangles (linear basis functions)
- Formulation: weak form in 2D axisymmetric (r, z) with 2πr volume weight
- Steady-state solve for temperature T(r, z)

### Governing Equation

**Steady-state (no time derivative):**

```
-∇·(k ∇T) = p(r,z)   in Ω (domain: aluminum plate ± payload)

where:
  k = thermal conductivity       [W/(m·K)]
  p(r,z) = heat source density   [W/m³] (from EM solver or placeholder)
  T = temperature                [K or °C]
```

**Transient (for time-stepping, implicit Euler):**

```
ρ·c_p·∂T/∂t = ∇·(k ∇T) + p(r,z)

where:
  ρ = density                    [kg/m³]
  c_p = specific heat capacity   [J/(kg·K)]
```

### Boundary Conditions

- **Natural (no BC needed) on axis r=0:** symmetry
- **Robin (convection) on exposed surfaces:**

  ```
  -k·∂T/∂n = h(T - T_ambient)

  where h = convection coefficient [W/(m²·K)]
  ```

### FEM Weak Form (Axisymmetric)

```
∫ k·∇T·∇v · 2πr dA + ∫_Γ h·T·v · 2πr ds
  = ∫ p·v · 2πr dA + ∫_Γ h·T_ambient·v · 2πr ds

Ω                      Ω                         Γ
```

where v are test functions and 2πr is the axisymmetric volume weight.

### Energy Balance Verification (MUST PASS)

```
Q_in = ∫ p(r,z) dV   [W]  (total heat generated)
Q_out = ∫ h(T - T_ambient) dA   [W]  (total convection loss)

At steady state: Q_in = Q_out to machine precision (we achieve 0.000% error).
```

### Solution Method

- **Linear system (steady):** K·T = b (real, symmetric positive-definite SPD)
- **Solver:** `scipy.sparse.linalg.spsolve()` (direct sparse Cholesky equivalent for SPD)
- **Matrix assembly:** element-wise Galerkin assembly, edge convection integrated analytically (linear r weighting)

### Heat Source Interpolation

- EM solver runs on a coarser mesh (higher fidelity, ~10⁴–10⁵ unknowns)
- Thermal solver runs on a finer mesh locally around the plate (better discretization near high gradients)
- Heat source q_e is interpolated from EM mesh to thermal mesh via:
  - **Primary:** `scipy.interpolate.LinearNDInterpolator` (linear on EM convex hull)
  - **Fallback:** `scipy.interpolate.NearestNDInterpolator` (outside convex hull)

### Key Open-Source Libraries Used

- `numpy`: array operations, quadrature
- `scipy.sparse`: sparse matrix construction
- `scipy.sparse.linalg.spsolve`: direct sparse solver
- `scipy.interpolate`: LinearNDInterpolator, NearestNDInterpolator

---

## 3. Reduced-Order Model (ROM) — Real-Time Thermal Prediction (`rom.py`)

### Method

**Parametric ROM with I² scaling + first-order transient + temperature-dependent conductivity**

### Offline Phase (run once, ~seconds)

1. Solve full FEM EM solver to get heat source map q̂(r, z)
2. Solve full FEM thermal solver at reference current I_ref and temperature T_ref
3. Extract spatial mode: ΔT_ref(r, z) = T_FEM(r, z) - T_ambient
4. Compute time constant: τ = (ρ·c_p·V) / (h·A_avg) ≈ 4.07 min at 5 A

### Online (Real-Time) Phase — Steady State

```
ΔT_steady(I, T̄) = ΔT_ref · (I/I_ref)² · [σ_Al(T̄) / σ_Al(T_ref)]

where:
  (I/I_ref)² accounts for Joule loss scaling (eddy currents ∝ I²)
  σ(T) = σ₀ / (1 + α(T - T₀)) is temperature-dependent conductivity
  α ≈ 0.0039 /K for aluminum
```

### Online (Real-Time) Phase — Transient

```
τ·(dβ/dt) = (I/I_ref)² · s(β) - β

T(r,z,t) = T_ambient + β(t) · ΔT_ref(r,z)

where:
  β ∈ [0, 1] is the dimensionless temperature amplitude
  s(β) is the steady-state scaling (includes σ(T) correction)
```

This is a **first-order ODE** integrated via implicit Euler:

```
β_{n+1} = [β_n + (Δt/τ) · s(β_n)] / [1 + Δt/τ]
```

### Solution Method

- **ODE integration:** implicit Euler (scipy.integrate.solve_ivp for reference, but can run in one step)
- **Computational cost:** O(1) per timestep (just multiply by β and interpolate)
- **Runtime:** milliseconds (suitable for real-time AR)

### Key Open-Source Libraries Used

- `numpy`: array operations, interpolation
- `scipy.integrate.solve_ivp`: reference ODE integration (used for validation only)
- `scipy.interpolate.LinearNDInterpolator`: spatial mode field interpolation at runtime

---

## 4. Levitation Model (`twin_core.py`)

### Method

**Spring-mass-damper mechanical system coupled to EM lift force**

### Governing Equations

**Vertical motion (1 DOF):**

```
m·d²z/dt² = F_lift(I, z) - m·g - c·(dz/dt)

where:
  m ≈ 163 g        [kg] plate mass
  F_lift(I, z)     [N] lift force from EM solver (computed once, interpolated vs z)
  g = 9.81         [m/s²] gravitational acceleration
  c ≈ 0.025 N·s/m  [N·s/m] damping coefficient (tuned from oscillation data)
  z ∈ [0, z_max]   [m] vertical gap between plate and coil
```

**Equilibrium levitation height:**

```
z_eq: F_lift(I, z_eq) = m·g
```

**Discretized (implicit Euler for stability):**

```
z_{n+1} = [z_n + Δt·v_n + (Δt²/m)·(F_lift - m·g - c·v_n)] / [1 + c·Δt/m]
v_{n+1} = (z_{n+1} - z_n) / Δt
```

### Lumped Thermal RC Network (Coil + Iron + Air)

**Nodes:**

- T1: inner coil surface (exposed to air)
- T2: inner coil winding core (deep reservoir)
- T3: outer coil surface
- T4: outer coil winding core
- T5: shared air node (around device)
- T6: iron core (massive, slow)

**First-order ODEs (one per node):**

```
C_i · dT_i/dt = P_i + Σ_j G_ij(T_j - T_i) + h_i·A_i·(T_ambient - T_i)

where:
  C_i = ρ·c_p·V_i     [J/K] heat capacity of node i
  G_ij = k·A/(Δx)     [W/K] thermal conductance between i and j
  P_i                 [W] ohmic heat generated in node i
  h_i·A_i             [W/K] convection conductance to ambient
```

### Time Integration

- **Method:** Implicit Euler (unconditionally stable)
- **Timestep:** Δt = 0.1 s (chosen to resolve transients at 4–6 Hz)
- **Calibration:** `hA_inner` and `hA_outer` fitted to match measured steady-state coil temperatures (79°C @ 7.8 A)

### Key Open-Source Libraries Used

- `numpy`: array operations, ODE state vectors
- `math`: standard library only (no scipy for rom.py's hot path)

---

## 5. Validation & Verification

### Energy Balance Check (EM Solver)

```
P_total = Σ P_body_eddy + Σ P_coil_ohmic    [W]

Verify: P_plate + P_iron = ∫ |J_e|²/(2σ) dV (numerically integrate FEM result)
        P_coil = Σ ½·î²·R_coil
```

Expected tolerance: <1% relative error.

### Energy Balance Check (Thermal Solver)

```
Q_in = ∫_Ω p(r,z) · 2πr dr dz     [W]
Q_out = ∫_Γ h(T - T_ambient) · 2πr ds   [W]

At steady state: Q_in = Q_out to machine precision.
```

Current performance: 0.000% error (verified every thermal solve).

### I² Scaling Validation

```
Run EM solver at I₁ and I₂.
Verify: P(I₂) / P(I₁) = (I₂/I₁)²

Example: P(10A) / P(5A) should equal (10/5)² = 4.000000
```

Current performance: 4.000000 verified exactly.

### Cross-validation (Python ↔ JavaScript)

- `xval_twin.py` runs the Python `twin_core.TwinState` integrator against
  the baked JavaScript engine in `outputs/digital_twin_fem.html`
- **Tolerance (integrator match):** abs error < 1e-9 over 7 test scenarios
- **Tolerance (coefficient freshness):** rel error < 1e-6 (catches stale bakes)

---

## 6. Summary Table: Open-Source Libraries

| Library        | Version | Purpose                                                                                                                                                      | Used in                                              |
| -------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------- |
| **numpy**      | ≥1.24   | Array operations, linear algebra, complex arithmetic                                                                                                         | em_solver, thermal_solver, rom, twin_core, visualize |
| **scipy**      | ≥1.10   | Sparse matrices (scipy.sparse), sparse solvers (scipy.sparse.linalg.spsolve), interpolation (scipy.interpolate), ODE integration (scipy.integrate.solve_ivp) | em_solver, thermal_solver, rom                       |
| **pyyaml**     | ≥6.0    | YAML parser for params.yaml (all configuration)                                                                                                              | config                                               |
| **matplotlib** | ≥3.7    | Interactive plotting, 2D field visualization                                                                                                                 | digital_twin, visualize                              |
| **trimesh**    | ≥4.0    | Mesh construction, GLB/OBJ export, STL I/O                                                                                                                   | visualize, build_twin_html_fem                       |
| **qrcode**     | ≥7.4    | QR code generation                                                                                                                                           | gen_qr                                               |
| **pyvista**    | ≥0.45   | 3D visualization (optional, ~400 MB dependency)                                                                                                              | extensions/digital_twin_pyvista                      |
| **vtk**        | 9.3–9.6 | Rendering backend for PyVista (optional)                                                                                                                     | extensions/digital_twin_pyvista                      |

**Note:** All other code uses only standard library (math, cmath, struct, copy, json, argparse).

---

## 7. No Proprietary / Closed-Source Tools

✓ **All solvers are custom-written FEM (Galerkin formulation) in pure Python/NumPy/SciPy**
✓ **No FEMM, COMSOL, ANSYS, or other commercial FE packages**
✓ **No machine-learning surrogate models or neural networks**
✓ **No black-box optimizers — all calibrations are transparent (refit_hA.py)**

---

## References

- See `docs/physics.md` for detailed physical formulations and assumptions
- See `CLAUDE.md` ("Locked decisions", "Key physics points") for design rationale
- See `docs/CHANGELOG.md` for history of calibration refinements and bug fixes
- See `docs/QUICK_START_FOR_AGENTS.md` for entry points to the codebase
