# Physics & Mathematics Formulation — Thermal Digital Twin (TEAM 28-like Levitator)

> **Objective:** Predict the temperature field T(r, z, t) in real time as alternating
> current flows through two copper coils. The device has axial symmetry → solve in 2D (r, z),
> display in 3D by revolution.

---

## 0. Pipeline overview (input → output)

```
Current î (A), f = 50 Hz
         │
         ▼
┌─────────────────────────────┐
│   STEP 1: EM Solve (FEM)    │  em_solver.py
│   Solve equation for A_φ    │
│   → q(r,z) [W/m³] on disc  │
│   → P_coil [W] (Joule heat) │
└────────────┬────────────────┘
             │ q_e, P_coil
             ▼
┌─────────────────────────────┐
│  STEP 2: Thermal Solve (FEM)│  thermal_solver.py
│  Solve heat equation        │
│  → T_steady(r,z) at I_ref   │
│  → ΔT_ref(r,z) [K] (mode)  │
└────────────┬────────────────┘
             │ ΔT_ref, UA, τ
             ▼
┌─────────────────────────────┐
│  STEP 3: ROM (real-time)    │  rom.py
│  T(r,z,t) = T_amb           │
│     + β(t) · ΔT_ref(r,z)   │
│  ODE: τ·dβ/dt = (I/I_ref)² │
│            · s(β) − β       │
└────────────┬────────────────┘
             │ T(r,z,t)
             ▼
┌─────────────────────────────┐
│  STEP 4: Display            │  digital_twin.py
│  Slider I(t), animation,    │  build_twin_html_fem.py
│  3D revolve, AR twin        │
└─────────────────────────────┘
```

**Why real-time?** The EM system is **linear** and material does not change with frequency
→ A_φ ∝ î → q ∝ î². Only need to **solve FEM once** at I_ref; runtime is just a scalar
multiply (I/I_ref)².

---

## 1. Step 1 — Electromagnetic Problem (EM Solver)

### 1.1 Why phasor only?

Current is i(t) = î·sin(ωt), f = 50 Hz. Heat transfer has time constant τ ≈ 10 minutes.
If we time-step EM at 50 Hz it would be extremely wasteful — thermal dynamics cannot
"feel" such rapid oscillations. Instead:

- Solve **once** using a **complex phasor** A_φ(r,z) ∈ ℂ at amplitude î.
- Take **cycle-averaged** power (the factor ½ comes from ∫sin²(ωt) dt = ½).

### 1.2 Governing equation (Magnetic Vector Potential)

With axisymmetric symmetry, only the azimuthal component A_φ(r,z) ≠ 0:

```
−∇·(ν ∇A_φ) + ν·A_φ/r²  + jωσ·A_φ = J_s

where:
  ν  = 1/μ = 1/(μ_r · μ₀)   [H⁻¹/m]  reluctivity
  ω  = 2πf                             [rad/s]
  σ                                    [S/m]   conductivity
  J_s = ±N·î/S_coil                   [A/m²]  source current density
```

Three terms with physical meaning:
| Term | Meaning |
|---------|---------|
| `−∇·(ν ∇A_φ)` | Magnetic field diffusion (curl-curl) |
| `ν·A_φ/r²` | Axisymmetric shape correction (azimuthal component) |
| `jωσ·A_φ` | Eddy current reaction in Al disc + iron core |

**Boundary conditions:**
- r = 0 (axis of symmetry): A_φ = 0 (physically mandatory)
- Outer boundary (r_max = 500 mm, z = ±500 mm): A_φ = 0 (Dirichlet, field decays away from device)

*Validate by switching to Neumann BC (∂A_φ/∂n = 0) and comparing — if the field near the device
is unchanged, domain is large enough. Already verified: difference < 0.06%.*

### 1.3 FEM discretization (P1 triangles on structured mesh)

The (r, z) rectangular mesh is subdivided into triangles (two triangles per quad):

```
a ─── b
│  \  │    → triangles [a, b, d] and [b, c, d]
d ─── c
```

With P1 triangular elements (linear basis functions), on each element e:

**Gradient of shape functions:** (b = dN/dr, c = dN/dz, independent of element coordinates)

```
b = [z_j−z_m, z_m−z_i, z_i−z_j] / (2·Area)
c = [r_m−r_j, r_i−r_m, r_j−r_i] / (2·Area)
```

**Local stiffness matrix K_e (complex) with 3 contributions:**

```
Ke  =  ν·(b bᵀ + c cᵀ) · r_c · Area          ← curl-curl (magnetic field)
    +  ν·(1/r_c)·Area·M̂                        ← A/r² (axisymmetric)
    + jωσ·r_c·Area·M̂                           ← eddy current (mass matrix)

M̂ = [[2,1,1],[1,2,1],[1,1,2]] / 12            ← consistent mass matrix
r_c = (r_i + r_j + r_m)/3                     ← centroid radius
```

**Local source vector:**

```
f_e = J_s · r_c · Area / 3    (for each node of source element)
```

After global assembly and boundary condition application, solve the complex linear system:

```
K · A = F     →    A_φ(r,z) ∈ ℂ
```

using `scipy.sparse.linalg.spsolve` (direct solver, ~10⁴–10⁵ unknowns).

### 1.4 Joule heat power calculation (post-processing)

**Instantaneous current density** at r,z in a conductor:

```
J_e(r,z) = −jωσ · A_φ(r,z)    [A/m²]  (eddy current phasor)
```

**Cycle-averaged thermal power** (factor ½ from sin²):

```
q(r,z) = |J_e|² / (2σ) = ½ · σ · ω² · |A_φ|²    [W/m³]
```

**Total power per region** (axisymmetric volume integral, dV = 2πr dr dz):

```python
P_plate  = Σ_e  q_e · 2π · r_c · Area_e    (Al disc)
P_iron   = Σ_e  q_e · 2π · r_c · Area_e    (iron core)
```

**Ohmic loss in coils** (computed directly from wire resistance R, more physical than from J_s FEM):

```
R_coil = N · (2π · r_mean) / (σ_Cu · A_wire)    [Ω]
P_coil = ½ · î² · R_coil                        [W]
```

*Result at 5A: P_plate ≈ 2.61 W, P_iron ≈ 0.63 W, P_coil ≈ 72.8 W → **coils dominate**.*

### 1.5 Magnetic field B and iron saturation check

From A_φ, compute B at each element centroid:

```
B_r = −∂A_φ/∂z = −(c·A)           (phasor)
B_z = A_φ/r + ∂A_φ/∂r = A_c/r_c + (b·A)    (phasor)

|B|_rms = √(|B_r|² + |B_z|²) / √2
```

**Lorentzian saturation model** (Picard iteration):

```
μ_r_eff(B) = 1 + (μ_r_lin − 1) / (1 + (B/B_sat)²)
```

- B → 0: μ_r_eff → μ_r_lin = 1000 (linear)
- B → ∞: μ_r_eff → 1 (fully saturated)
- At 5A: B_max ≈ 0.311 T < B_sat = 1.5 T → **unsaturated**, μ_r_lin = 1000 valid.

---

## 2. Step 2 — Heat Transfer Problem (Thermal Solver)

### 2.1 Differential equations

**Steady state:**

```
−∇·(k ∇T) = q(r,z)       in aluminum disc

Robin boundary condition (convection):
  −k ∂T/∂n = h·(T − T_∞)    on all surfaces
  r = 0: natural condition (symmetry, no need to impose)
```

**Constants:**
- k = 237 W/(m·K) — aluminum thermal conductivity
- h = `h_convection_W_per_m2K` (top), `h_bottom_W_per_m2K` (bottom, near coil)
- T_∞ = T_amb = 20°C (uniform) — per professor's feedback (simplest first)
- Disc bottom: `T_∞_bot = T_amb + k_coil_coupling · P_coil` (thermal coupling model coil→air→disc)

### 2.2 FEM discretization (P1, axisymmetric, dV = 2πr dr dz)

**Local thermal stiffness matrix** (weighted r integration):

```
Ke = 2π · k · (b bᵀ + c cᵀ) · Area · r_c      [W/K]
```

**Convection contribution on boundary edges** (linear r integration):

```
Kedge = 2π · h · (L/12) · [[3rₐ+r_b,  rₐ+r_b ],
                             [rₐ+r_b,  rₐ+3r_b]]     [W/K]

feconv = 2π · h · T_∞ · (L/12) · [[3rₐ+r_b, rₐ+r_b],
                                    [rₐ+r_b, rₐ+3r_b]] · [1,1]ᵀ  [W]
```

where L = edge length, rₐ,r_b = radii at edge endpoints.

**Heat source (vector F):**

```
F_i += q_e · 2π · r_c · Area / 3    for each node i of element e
```

Source q_e taken from EM map (`q(r,z)`) via interpolation (`LinearNDInterpolator`).
Then **normalize** to ensure ∫q dV = P_total (energy conservation).

**Solve system:**

```
(K_cond + K_conv) · T = F_source + F_conv
```

**Energy balance check:**

```
Q_in  = ∫ q dV = P_total
Q_out = Σ_edges  h·(T̄_edge − T_∞) · 2π·r̄_edge · L_edge

Error = |Q_in − Q_out| / Q_in × 100%  → must = 0.000%
```

---

## 3. Step 3 — Reduced-Order Model (ROM) — Real-time Tool

### 3.1 Decomposition into Mode + Amplitude

Key observation: when materials are linear and geometry is fixed, the **spatial shape**
of the thermal field does not change when I varies — only the **amplitude** changes.

Definition:

```
T(r,z,t) = T_amb + β(t) · ΔT_ref(r,z)

where:
  ΔT_ref(r,z) = T_steady(I_ref) − T_amb    [K]  (computed once by FEM)
  β(t)        ∈ ℝ                           (dimensionless, evolves in time)
```

### 3.2 ODE for β(t)

First-order lumped RC model:

```
τ · dβ/dt = (I/I_ref)² · s(β) − β

where:
  τ  = C / UA              [s]   thermal time constant (~10.6 min)
  C  = ρ · c_p · V         [J/K] heat capacity of aluminum disc
  UA = P_ref / ΔT_mean_ref [W/K] overall heat transfer coefficient
  s(β) = 1/(1 + α · β · ΔT_mean_ref)     ← σ(T) correction
```

**Solution:**
- Steady state: β_ss = (I/I_ref)² · s(β_ss)  → solve quadratic equation in β
- Transient: use `scipy.integrate.solve_ivp` (implicit Euler in digital_twin.py)

### 3.3 σ(T) correction — why needed?

Aluminum conductivity decreases with temperature:

```
σ(T) = σ₀ / (1 + α·(T − T₀))      α ≈ 3.9×10⁻³ K⁻¹
```

This affects power in opposite directions:

| Region | Power ∝ | Effect when hot |
|------|------------|-----------------|
| Aluminum disc (eddy) | P_plate ∝ σ_Al | Disc heats → σ drops → **P drops** |
| Coil (ohmic) | P_coil ∝ 1/σ_Cu | Coil heats → σ drops → **P rises** |

Correction function for the disc:

```
s(β) = 1 / (1 + α · ΔT_mean(β))    (< 1 when disc is hot)
```

Converges in ~2–3 iterations (one-way weak coupling — no heavy iterative solve needed).

### 3.4 I² rule — why it holds?

EM system is linear → A_φ ∝ î → q ∝ î² → P ∝ î² → ΔT ∝ î²

Verified numerically: P(2A)/P(1A) = **4.000000** (error < 1 ULP).

```
T_steady(r,z; I) ≈ T_amb + (I/I_ref)² · ΔT_ref(r,z)
```

---

## 4. Lumped thermal network for coils

Coils are not meshed in thermal_solver.py (only act as air heat source).
Instead, a 2-node RC network exists in `build_twin_html_fem.py`:

```
P_inner  →  [C_inner]  −−(hA_inner)−→  [T_air]  −−(hA_far)−→  T_amb
P_outer  →  [C_outer]  −−(hA_outer)−→  [T_air]
```

**Shared air node:**

```
C_air · dT_air/dt = (hA_inner·(T_inner−T_air) + hA_outer·(T_outer−T_air))
                  − hA_far·(T_air − T_amb)
```

**Thermal equation per coil:**

```
C_i · dT_i/dt = P_i − hA_i·(T_i − T_air)

C_inner = coil_C_scale · ρ_Cu · c_Cu · V_inner    (empirically ~43% of solid Cu)
```

**Parameters calibrated from real IR data** (7.8A, steady state):

| Parameter | Value | Source |
|---------|---------|-------|
| hA_inner | 2.2479 W/K | Fit from T_inner = 79°C at 7.8A |
| hA_outer | 1.8788 W/K | Fit from T_outer = 74°C at 7.8A |
| coil_C_scale | 0.434 | Fit transient (off τ ~10% worse without scale) |
| hA_far | 40 W/K | Air node → far field |
| C_air | 3000 J/K | Heat capacity of near air cluster |

*Prediction at 5A (T_amb=20°C): T_inner ≈ 40.5°C, T_outer ≈ 38.5°C.*

---

## 5. Lift Force — EM Validation

Lorentz force along z-axis, cycle-averaged (factor ½):

```
F_z = −½ · Re[ ∫∫ J_φ · B_r* · 2π r dA ]

     = −½ · Re[ ∫∫ (−jωσ·A_φ) · (−∂A_φ*/∂z) · 2π r dA ]
```

*Result for original TEAM28 benchmark (20A, 960/576 turns, coil radii from original PDF):
z_eq ≈ 7.1 mm vs 11.3 mm measured (37% error) — improved from 70% after fixing coil radii;
remaining 37% cause still unexplained, PAUSED.*

---

## 6. Cross-checks and real data

### Numerical results at I = 5A, T_amb = 20°C (after confirming non-ferromagnetic core, 2026-07-01)

| Quantity | Value | Note |
|-----------|---------|---------|
| P_plate (eddy Al) | **1.84 W** | Down from 2.61W — core no longer concentrates flux |
| P_iron (eddy core) | **0 W** | Core is non-conducting (ceramic/oxide) |
| P_coil (ohmic Cu) | 72.8 W | Unchanged |
| P_total | 74.66 W | |
| τ (disc time constant) | **13.6 min** | Up from 10.6 min (lower UA) |
| UA | 0.180 W/K | Down from 0.231 W/K |
| ΔT_max disc (steady) | ≈ 10.3 K | Down from 11.4 K |
| T_max disc | ≈ 30.3°C | |
| B_max in core (mu_r=1) | 0.036 T | Very small — no flux concentration |
| Energy balance | 0.000% | |

### Actual IR data measured (7.8A, steady state, HIKMICRO, 2026-06-23)

| Location | Measured | Note |
|--------|---------|---------|
| Inner coil | **79°C** | Reliable (dark varnish, ε≈0.91) |
| Outer coil | **74°C** | Reliable |
| Center core | 45°C | Unreliable (bright Al, true ε ≈ 0.1) |
| Separator ring | 40°C | May be lower in reality |
| Al disc (bottom) | 44/35°C | Unreliable (wrong ε) |
| Environment | 29°C | Lab |

---

## 7. Code ↔ Formula mapping

| File | Function | Formula |
|------|-----------|-----------|
| `config.py` | Load params.yaml, convert mm→m | No FEM |
| `em_solver.py → solve_em()` | Assemble complex K, solve A_φ | §1.2–§1.3 |
| `em_solver.py → compute_losses()` | q = ½σω²|A|², P_coil = ½I²R | §1.4 |
| `em_solver.py → solve_em_saturating()` | Picard iteration + Lorentzian μ_r | §1.5 |
| `thermal_solver.py → solve_steady()` | Thermal K + Robin BC, solve T | §2.2 |
| `thermal_solver.py → energy_balance()` | Q_in vs Q_out | §2.2 |
| `rom.py → ThermalROM.build()` | Compute ΔT_ref, C, UA, τ | §3.1 |
| `rom.py → T_steady()` | T = T_amb + (I/I_ref)²·s(β)·ΔT_ref | §3.2–§3.3 |
| `rom.py → simulate()` | solve_ivp on ODE τ·dβ/dt = ... | §3.2 |
| `digital_twin.py` | Real-time loop, Euler: β += (1/τ)·(rhs)·dt | §3.2 |
| `build_twin_html_fem.py` | JS: romStep(), coilAirDrive() | §3, §4 |

---

## 8. Current assumptions and limitations

1. **σ(T) is only a scalar multiplier** — no FEM re-solve with temperature.
   Valid when ΔT is small and field shape does not change appreciably.

2. **Iron core not yet confirmed** — levitation force observation is indirect; need to test
   with permanent magnet when power is off to confirm.

3. **Disc thickness = 3 mm is a placeholder** — needs actual measurement on the Ø16 cm disc.

4. **Skin depth in Al @ 50 Hz ≈ 12 mm >> 3 mm** → eddy current is nearly uniform
   across thickness → no fine z-direction mesh needed in disc.

5. **T_amb = 20°C constant** — do not use lab sensor data until results become inaccurate
   (professor's guidance).

6. **TEAM28 benchmark z_eq ≈ 7.1 mm vs 11.3 mm** (37% error) — EM solver is correct
   in sign and trend, but absolute lift force does not yet match; paused.
