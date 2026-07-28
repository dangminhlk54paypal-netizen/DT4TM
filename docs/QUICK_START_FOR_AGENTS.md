# Quick Start Guide for Agents — DT4TM Project

**Purpose:** get an agent (Claude, Gemini, etc.) up to speed on the project
architecture quickly enough to debug it.

> **Rewritten 2026-07-28.** The previous version was a 2026-07-02 snapshot written
> in Vietnamese, and had drifted badly out of date — it quoted the superseded coil
> radii (inner 28–78mm, outer 104–124mm), the old thermal calibration
> (hA_inner=3.5611 / hA_outer=4.3446), a benchmark result of z_eq≈7.1mm, a domain
> diff of <0.06%, and — most misleadingly — claimed the lift force was **validated**
> when it is now a known open mismatch. All of that is corrected below. Historical
> detail lives in `docs/CHANGELOG.md`.

## Reading order for the .md files

### 1. **CLAUDE.md** (start here)
- **Must be read first** — contains every locked decision.
- Device specs: R=80mm plate (Ø160mm), 3mm thick, I=5A RMS (peak=7.07A).
- Coil radii (re-measured 2026-07-10): core 0–25.9 | inner coil 27.9–61.9 |
  iron ring 64.9–79.9 | outer coil 82.9–102.9 mm.
- Current convention: `current_A` in params.yaml is the **RMS measured** value. The
  LOSS chain deliberately treats it as the amplitude (the ×2 error is absorbed into
  the calibrated hA). The FORCE chain needs the true amplitude — use `cfg.I_peak`.
  This distinction has caused a real bug twice; read that section carefully.
- Thermal calibration: hA_inner=2.9493, hA_outer=3.4509, coil_C_scale=0.2241
  (refitted 2026-07-11).
- ⚠️ Lift force is **NOT validated** — see the open questions below.
- Status codes: `[x]` done, `[ ]` paused/pending.

### 2. **README.md**
- Setup (`python3 -m venv` + `pip install -r requirements.txt`).
- How to run each script, in dependency order.
- Repo layout: source scripts flat in the root, `docs/`, `outputs/` (gitignored
  except the HTML deliverable).
- Roadmap Phase 1–8 (Phase 7 — real sensor hardware — is the only one still open).

### 3. **docs/physics.md**
- The formulation: eddy current → Joule loss q = ½σω²|A_φ|² [W/m³] (NOT |∇T|²/σ).
- σ(T) dependency: α ≈ 0.0039/K — applied as a runtime multiplier, never a re-solve.
- Time-scale separation: **do not** time-step the EM at 50Hz; use the phasor +
  cycle average.
- Iron core: linear μ_r, but check saturation if B approaches 1.5T.
- Thermal FEM check: Q_in (∫q dV) = Q_out (∫h(T−T∞)dA) must match to 0.000%.

### 4. **docs/ARCHITECTURE.md**
- File-by-file dependency graph and data flow. Kept current.

### 5. **docs/HANDOFF.md**
- Short status snapshot + the current open questions. Kept current.

### 6. **docs/SENSOR_PLAN.md**
- Hardware: Arduino + 2× MAX31855 thermocouple + IR thermometer.
- Pipeline: serial CSV → `data_io.py` → `calibrate_UA()` → ROM update.
- Status: mock-tested end to end; real hardware **not built yet**.

### 7. **docs/CHANGELOG.md** (historical)
- Session-by-session history. Go here to find out *why* a number changed.

---

## Key numbers to know (for debugging)

| Quantity | Value | Unit | Source |
|----------|-------|------|--------|
| Plate radius | 80 | mm | measured 2026-07-01 |
| Plate thickness | 3 | mm | measured 2026-07-01 |
| Centre core (iron) | 0–25.9 | mm | ruler-measured 2026-07-10 |
| Inner coil (1000T) | 27.9–61.9 | mm | ruler-measured 2026-07-10 |
| Iron ring | 64.9–79.9 | mm | ruler-measured 2026-07-10 |
| Outer coil (500T) | 82.9–102.9 | mm | ruler-measured 2026-07-10 |
| Current (operating) | 5.0 | A (RMS) | measured 190V→5A |
| Current peak (for FORCE) | 7.07 | A | = 5×√2 (`cfg.I_peak`) |
| Plate eddy loss | 25.81 | W | `compute_losses` @5A |
| Iron core + ring loss | 5.86 | W | `compute_losses` @5A |
| Coil ohmic loss | 106.44 | W | inner 52.32 / outer 54.12 |
| **Total loss** | **138.11** | W | @5A, T_amb=20°C |
| Disc time constant τ | 244.3 (4.07 min) | s | ROM, R=80mm |
| B_max in iron | 0.66 | T | ≪ B_sat=1.5T → unsaturated |
| Domain size | ±500 | mm | Dirichlet vs Neumann, all diffs <1% (P_plate 0.767%) |
| σ_Al(20°C) | 3.4e7 | S/m | params.yaml |
| σ_Cu(20°C) | 5.96e7 | S/m | params.yaml |
| Frequency | 50 | Hz | AC mains |
| Skin depth (Al) | 12 | mm | ≫3mm plate → no fine through-thickness mesh |

---

## Open questions — do NOT assume these are solved

1. **Lift force / levitation gap MISMATCH.** F_z(5A peak) ≈ 4.10N ≫ F_gravity
   (163g) = 1.60N, so it levitates — but the predicted z_eq is **11.7mm**
   (plate bottom) / **14.7mm** visible, while the observed visible gap is **7–8mm**.
   Prime suspect: `mu_r=1000` is an unmeasured mild-steel-*like* placeholder.
   Saturation was tested and ruled out (<0.1% change in F_z).
   **Never report z_eq as validated.**
2. **Original TEAM 28 benchmark is PAUSED** at z_eq ≈ 14.5mm vs 11.3mm expected
   (28% overshoot). It read 40% *undershoot* until 2026-07-11, when a missed
   RMS-vs-peak call site was fixed — the sign flipped, a residual remains.
3. **Plate-vs-coil temperature ordering** is only *tied* in the model; IR data says
   the coil should be clearly hotter. The disc model has never been calibrated
   (IR on shiny aluminium is unreliable). Needs a contact thermocouple.

---

## Common debugging checkpoints

### EM solver
1. `config.py` output: `I_peak` = 7.07A when input is 5A RMS.
2. Losses: P_plate, P_iron, P_coil all > 0; I² check = 4.000 (double current → 4× power).
3. Domain: `validate_domain_size()` → Dirichlet vs Neumann, all diffs <1%.
4. Saturation: `check_saturation()` covers BOTH `iron_core` and `outer_iron_ring`.

### Thermal solver
1. Energy balance at steady state: Q_in = Q_out, error <0.001%.
2. Convection BC applied as a flux condition, not a fixed-temperature condition.

### ROM
1. I² scaling: T_ss(2I)/T_ss(I) = 4.0 exactly, no iteration.
2. σ(T) correction: a 70K rise → ~27% resistance change.

### Twins — there are three, sharing ONE integrator
- `twin_core.py` is the **SSOT time integrator** (numpy + stdlib only). Run
  `python twin_core.py` → 6/6 self-checks must PASS.
- `digital_twin.py` (matplotlib) and `extensions/digital_twin_pyvista.py` (VTK, optional
  dependency) both drive `twin_core.TwinState`. Neither has its own physics.
- `build_twin_html_fem.py` bakes a **separate JS copy** of the same integrators into
  `outputs/digital_twin_fem.html`.
- `xval_twin.py` pins the two against each other via Playwright. Run
  `python xval_twin.py` after ANY change to the integrators or coefficients.
  It has two independent assertions: **A** integrator match (1e-9 abs) and
  **B** bake freshness (1e-6 rel). Assertion B exists because a coefficient fix that
  never got re-baked into the HTML has already shipped once (commit d4f73d6).

### HTML twin (`build_twin_html_fem.py`)
1. Zero JS errors under headless Playwright.
2. Geometry is **100% procedural from params.yaml** — the STL is not used for the body.
3. Coil colours use a fixed ABSOLUTE scale anchored at `T_COIL_HOT=80°C` (from the
   IR session: inner coil 79°C @ 7.8A), not divided by the current-dependent T_ss(I).
4. The levitation gap is **not** baked into the Python geometry (`z_disc_bot =
   z_coil_top`); the whole visible gap is added at JS runtime as `lev.z * 2.0`.
5. **Never commit a build that contains a real API key.** The default build uses the
   `YOUR_KEY_HERE` placeholder; `--bake-key` gates the real one. A `PreToolUse` hook
   in `.claude/settings.json` blocks commits containing a Google key pattern.

---

## File dependencies

```
params.yaml
    ↓
config.py (normalise mm→m, derive I_peak from I_rms)
    ↓
em_solver.py (→ q_e map, P_plate/P_coil/P_iron, lift F_z, benchmark)
    ↓
thermal_solver.py (interpolate q_e, solve FEM, check energy balance)
    ├→ rom.py (build ROM from the thermal FEM at I_ref)
    │   ├→ twin_model.py (coeffs_from_live: live solve → frozen coefficients)
    │   │      ↓
    │   │   twin_core.py (TwinState — the ONE integrator)
    │   │      ├→ digital_twin.py           (matplotlib live twin)
    │   │      ├→ extensions/digital_twin_pyvista.py  (PyVista/VTK 3D live twin)
    │   │      └→ data_io.py                (sensor comparison)
    │   │
    │   └→ build_twin_html_fem.py (bakes its own JS copy → HTML)
    │          ↑
    │       xval_twin.py (pins twin_core against that baked JS)
    │
    └→ visualize.py (revolve 2D→3D, export GLB)
```

---

## Tips for agent debugging

1. **Always read CLAUDE.md first** — every locked decision is there.
2. **Watch I_rms vs I_peak.** The force chain needs `cfg.I_peak`; the loss chain
   stays on `cfg.I`. Missing this at one call site is a bug that has shipped twice.
3. **σ(T) does not break real-time** — it is a scalar multiplier, never a re-solve.
4. **Energy balance is the source of truth** — if it is not ~0%, there is an
   integration or BC error.
5. **Run `xval_twin.py` after touching any integrator or coefficient.** A green
   assertion A with a red assertion B means the code is right but the HTML is stale.
6. **The sensor pipeline is testable without hardware** — use `mock_sensor_data.csv`.
7. **Never Read `outputs/digital_twin_fem.html` whole** (~1MB of baked JS) — grep for
   the section you need.

---

## 3D body geometry in `digital_twin_fem.html`

**All geometry is built PROCEDURALLY from params.yaml** — the STL file is only a
shape reference and is no longer read by the builder.

### Ground truth (2026-07-10, ruler-measured on the real rig)
Radii and materials read from `coils:` / `iron_core:` / `outer_iron_ring:` in params.yaml:
```
r =    0..25.9   centre core — IRON (magnet-attracted, confirmed 2026-07-10; mu_r=1000, sigma=1e6)
r =  25.9..27.9  AIR GAP 2mm
r =  27.9..61.9  INNER COIL, 1000 turns, 34mm wide
r =  61.9..64.9  AIR GAP 3mm
r =  64.9..79.9  IRON RING, 15mm wide — IRON (same magnet test, same material as the centre core)
r =  79.9..82.9  AIR GAP 3mm
r =  82.9..102.9 OUTER COIL, 500 turns, 20mm wide
r = 102.9..~130.4 AIR 25-30mm → inner wall of the wooden frame
r ~130.4..~180.4  OCTAGONAL plywood frame (8 sides), ~50mm from outer coil to outer edge
```
Note the Ø160mm disc (R=80mm) now **overlaps the iron ring** (64.9–79.9mm). This is a
structurally different EM picture from the pre-2026-07-10 geometry, and it is why the
plate's share of the losses grew ~8.5×.

### Coordinate system (Z-up, mm)
```
z = 0         → floor (bottom of the wooden base)
z = 8         → bottom of the coil assembly
z = 60        → top of the coil assembly
z = 60        → disc underside in the BAKED geometry (= z_coil_top; the gap is NOT
                baked — it is added at JS runtime via lev.z * 2.0)
z = 60+zex    → disc top at rest (zex = thickness × display_z_exaggeration)
```

### Region labels (`reg`)
| reg | Part | Material | r_in..r_out (mm) | z (mm) | Mesh | Thermal colour |
|-----|------|----------|------------------|--------|------|----------------|
| 0 | Levitating disc | Aluminium | 0..80 | 60..top (gap at runtime) | `plateM` | FEM vertex field (`writeRamp`) |
| 1 | Inner coil (1000T) | Copper + dark varnish | 27.9..61.9 | 8..60 | `coilM` | `writeRampCopper` |
| 2 | Outer coil (500T) | Copper + dark varnish | 82.9..102.9 | 8..60 | `coilM` | `writeRampCopper` |
| 3 | Centre core | Iron (mu_r=1000) | 0..25.9 | 8..60 | `baseM` | `writeRampMetal` |
| 4 | Plywood octagonal frame | Wood | from `device_frame` in params.yaml | 0..60 | `woodM` | Flat brown (static) |
| 5 | Outer iron ring | Iron (mu_r=1000) | 64.9..79.9 | 8..60 | `baseM` | `writeRampMetal` |
| — | Air gaps (NOT meshed) | Air | 25.9–27.9, 61.9–64.9, 79.9–82.9, 102.9–130.4 | — | — | — |

### Triangle counts (verified 2026-07-28)
```
centre core     :  960 tris   (build_solid_core)
inner coil      :  960 tris   (revolve_ring)
iron ring       :  960 tris   (revolve_ring)
outer coil      :  960 tris   (revolve_ring)
wood frame      :   96 tris   (octagon, 8 sides)
TOTAL body      : 3936 tris
levitating disc :  720 tris   (build_disc_mesh, FEM field mapped)
GRAND TOTAL     : 4656 tris across 5 meshes, 13968 vertices
```
`extensions/digital_twin_pyvista.py --self-check` reproduces these exact counts — the two
renderers share the same geometry builders, so a mismatch means a real regression.

### Why the STL is not used for the body
The old STL path produced five visual defects: `classify()` used r=26..45mm for the
inner coil when it is really much wider, so almost the whole inner coil was
misclassified; the STL shell was hollow and see-through from below; the flat red
source material looked like plastic; the frame was a 6-sided hexagon instead of the
real 8-sided octagon; and the heat ramp only reached the outer shell.

### Three.js Y/Z swap (a recurring source of confusion)
The JS template swaps y/z when reading from the buffer:
```javascript
positions[i+1] = z;   // Three.js Y = physical Z (height)
positions[i+2] = -y;  // Three.js Z = -physical Y
```
→ `bb.max.y - bb.min.y` is the model **height**, not a radius.
`extensions/digital_twin_pyvista.py` deliberately does NOT do this — it stays Z-up in mm,
because the Y-up swap is a three.js convention, not a physical one.

### Thermal ramp functions (JS)
```javascript
writeRamp(col, idx, tnorm)       // scientific: blue→cyan→green→yellow→red (disc)
writeRampCopper(col, idx, tnorm) // copper: dark red-brown (cold) → orange-yellow (hot)
writeRampMetal(col, idx, tnorm)  // metal: silver-grey (cold) → warm orange (hot)
```
Disc (`writeRamp`): `tnorm` is adaptive — see `colorScaleMode` (auto/relative/absolute).
Coils/core/ring: `tnorm` is an ABSOLUTE scale `(T - T_amb) / (T_COIL_HOT − T_amb)`
with `T_COIL_HOT = 80°C`, anchored to the hottest real IR reading (inner coil 79°C
@ 7.8A). Core and ring apply the same scale with a ×1.8 boost, because they only
reach ~45°C in reality and would otherwise render as frozen silver.

---

## This document was last updated: 2026-07-28
