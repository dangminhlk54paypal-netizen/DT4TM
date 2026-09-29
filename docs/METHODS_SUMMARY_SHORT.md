# Technical Methods Summary (Brief) — Thermal Digital Twin

**Date:** 2026-07-31

---

## Quick Overview

This document summarizes the **core mathematical methods, governing equations, and open-source libraries** for the thermal digital twin simulation. All solvers are custom-implemented in Python (no commercial FE packages like FEMM, COMSOL, ANSYS).

---

## 1. Electromagnetic Problem

**Method:** Finite Element Method (FEM) + Galerkin formulation, P1 triangles, 2D axisymmetric

**Equation solved:**
```
-∇·(ν ∇A_φ) + ν·A_φ/r² + jωσ·A_φ = J_s    (phasor form, complex)
```

**Heat source:** q(r,z) = ½·σ·ω²·|A_φ|² [W/m³]

**Libraries:** `numpy`, `scipy.sparse`, `scipy.sparse.linalg.spsolve`

---

## 2. Thermal Problem

**Method:** Finite Element Method (FEM) + Galerkin formulation, P1 triangles, axisymmetric

**Equation solved (steady-state):**
```
-∇·(k ∇T) = p(r,z)
```

**Boundary conditions:** Robin (convection) on surfaces: -k·∂T/∂n = h(T - T_ambient)

**Energy balance check:** Q_in = ∫p dV must equal Q_out = ∫h(T-T_ambient) dA (0.000% error)

**Libraries:** `numpy`, `scipy.sparse`, `scipy.sparse.linalg.spsolve`, `scipy.interpolate`

---

## 3. Real-Time Model (ROM)

**Method:** Parametric I² scaling + first-order ODE transient + temperature-dependent conductivity σ(T)

**Equation (steady-state):**
```
ΔT(I, T̄) = ΔT_ref · (I/I_ref)² · [σ(T̄) / σ(T_ref)]
```

**Equation (transient):**
```
τ·(dβ/dt) = (I/I_ref)² - β
T(r,z,t) = T_ambient + β(t) · ΔT_ref(r,z)
```

**Integration:** Implicit Euler (unconditionally stable)

**Runtime:** O(1) per timestep → milliseconds (suitable for AR)

**Libraries:** `numpy`, `scipy.integrate.solve_ivp` (reference), `scipy.interpolate`

---

## 4. Levitation Model

**Method:** Spring-mass-damper coupled to EM lift force + lumped RC thermal network

**Equation (vertical motion, 1-DOF):**
```
m·d²z/dt² = F_lift(I, z) - m·g - c·(dz/dt)
```

**Thermal nodes:** Inner coil surface + core, outer coil surface + core, shared air, iron core

**Integration:** Implicit Euler

**Libraries:** `numpy` (standard library only in hot path)

---

## 5. Open-Source Libraries Used

| Library | Purpose |
|---------|---------|
| `numpy` ≥1.24 | Array operations, complex arithmetic |
| `scipy` ≥1.10 | Sparse matrices, direct solver (spsolve), interpolation |
| `pyyaml` ≥6.0 | Configuration (params.yaml) |
| `matplotlib` ≥3.7 | Interactive plotting |
| `trimesh` ≥4.0 | Mesh export (GLB/OBJ) |
| `qrcode` ≥7.4 | QR code generation |
| `pyvista` ≥0.45 (optional) | 3D visualization |

---

## 6. Key Validations

- **EM I²-linearity:** P(2î)/P(î) = 4.000 (exact)
- **Thermal energy balance:** Q_in = Q_out at steady-state (0.000% error)
- **ROM vs. FEM:** Cross-validation via `xval_twin.py` (integrator match < 1e-9)
- **Domain size:** Verified with Dirichlet vs. Neumann BC comparison (all diffs < 1%)

---

## References

- Full formulation: `docs/physics.md`
- Implementation details: `docs/METHODS_AND_ALGORITHMS.md` (this session)
- Design decisions: `CLAUDE.md`
