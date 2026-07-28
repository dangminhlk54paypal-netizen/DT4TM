# HANDOFF — Digital Twin for Thermal Management

> **Primary source of truth is [CLAUDE.md](../CLAUDE.md) + [README.md](../README.md).**
> This file is a short status snapshot. Last updated: **2026-07-28**.
>
> ⚠️ Rewritten 2026-07-28. The previous version was a 2026-07-02 (session 6)
> snapshot and had drifted badly out of date — it still quoted the pre-2026-07-10
> geometry, `220V → 5A`, `z_eq ≈ 7.1mm`, `τ ≈ 3.4 min` and a domain diff of
> `<0.06%`, all of which have since been superseded. Do not restore it; see
> `docs/CHANGELOG.md` if you need that history.

## Goal
A digital twin that predicts the **real-time temperature field** of the aluminium
plate in the TEAM 28-like electrodynamic levitation device (TEMF). Validate
against the real rig → 3D visualisation → AR app → QR code.

## Architecture decisions (locked)
- **No FEMM** (dev machine is macOS). Pure Python: `numpy + scipy + pyyaml +
  matplotlib` (+ `trimesh` for GLB, optional `pyvista`/`vtk` for the desktop 3D twin).
- Problem is **axisymmetric** → solve in 2D (r, z), revolve to 3D for display.
- **Real-time:** losses scale as I² with a fixed spatial pattern → run the FEM once
  at `I_ref = 5A`, then runtime is a scalar multiply. I²-scaling verified: 4.000000.
- All parameters live in [params.yaml](../params.yaml). Source scripts + input data
  stay **flat in the repo root**; docs in `docs/`, generated files in `outputs/`.
- **One integrator, not three.** `twin_core.py` is the SSOT time integrator shared
  by `digital_twin.py` (matplotlib), `extensions/digital_twin_pyvista.py` (VTK) and
  `data_io.py`. `build_twin_html_fem.py` bakes its own JS copy for the standalone
  HTML — `xval_twin.py` pins the two against each other so they cannot drift.

## Device numbers (current — all in params.yaml)
- Aluminium plate: **R = 80mm (Ø160mm)**, thickness **3mm (measured 2026-07-01)**,
  σ = 3.4e7 S/m.
- Current: **î = 5A RMS** measured (rig: **190V → 5A**, re-measured 2026-06-23),
  f = 50Hz. Second operating point 270V → 7.8A is the thermal calibration anchor.
- Turns: inner = 1000, outer = 500 (confirmed by thermal data — inner runs hotter).
- **Coil radii re-measured 2026-07-10** by ruler: core 0–25.9 | inner coil 27.9–61.9
  | iron ring 64.9–79.9 | outer coil 82.9–102.9 mm. This superseded the earlier
  estimates and materially changed the physics — the Ø160mm disc now overlaps the
  iron ring.
- **Centre core AND outer iron ring: both confirmed ferromagnetic** 2026-07-10
  (magnet-attracted). `mu_r = 1000` is still a mild-steel-*like* **placeholder**,
  never measured — see the open question below.
- T_ambient = 20°C for the FEM solve (professor: keep Phase 1 simple).
- EM domain: 1×1m box (±500mm), validated Dirichlet vs Neumann.

## Current quantitative state (î = 5A, T_amb = 20°C)
| Quantity | Value |
|---|---|
| Plate eddy loss | 25.81 W |
| Iron core + ring eddy loss | 5.86 W |
| Coil ohmic (inner 52.32 / outer 54.12) | 106.44 W |
| **Total** | **138.11 W** |
| Disc time constant τ (R=80mm) | 244.3 s ≈ 4.07 min |
| B_max in iron | 0.66 T (≪ B_sat = 1.5 T, unsaturated) |
| Calibrated coil network | hA_inner = 2.9493, hA_outer = 3.4509, coil_C_scale = 0.2241 |

## Status
- [x] `config.py`, `params.yaml`, `thermal_solver.py` (energy balance 0.000%)
- [x] `em_solver.py` — AC eddy losses, lift force, saturation check, domain validation
      (PASS, all diffs <1% at ±500mm)
- [x] `rom.py` — real-time ROM (I² + first-order transient + σ(T))
- [x] `twin_core.py` — SSOT integrator, 6/6 self-checks PASS, numpy+stdlib only
- [x] `twin_model.py` — heavy bridge (plate resolution, cache, live→coefficients)
- [x] `xval_twin.py` — pins `twin_core.py` against the baked JS (Playwright);
      two independent assertions (integrator match 1e-9 abs, bake freshness 1e-6 rel)
- [x] `digital_twin.py` — interactive matplotlib twin
- [x] `extensions/digital_twin_pyvista.py` — interactive PyVista/VTK desktop 3D twin (optional dep)
- [x] `build_twin_html_fem.py` — standalone HTML/three.js twin (the shippable deliverable)
- [x] `visualize.py`, `sim_plates.py` — 3D revolve/GLB export, cross-plate comparison
- [x] `data_io.py` + `arduino/thermal_sensor.ino` — sensor bridge, mock-tested end to end
- [ ] **Real sensor hardware** — not built yet. This is the main blocker for
      further calibration. See [SENSOR_PLAN.md](SENSOR_PLAN.md).

## Open questions (none are blocking day-to-day work)
1. **`mu_r = 1000` is unmeasured.** It makes the predicted levitation gap roughly
   2× the observed one (predicted z_eq ≈ 11.7mm plate-bottom / 14.7mm visible, vs
   an observed visible gap of 7–8mm). Saturation was tested and ruled out as the
   explanation (<0.1% change in F_z). Needs a real B-H / μ_r measurement, or
   acceptance as a known model limitation. **Do not treat z_eq as validated.**
2. **Original TEAM28 benchmark is PAUSED** at z_eq ≈ 14.5mm vs 11.3mm expected
   (28% overshoot). It was 40% *undershoot* until 2026-07-11, when a missed
   RMS-vs-peak call site was fixed; the sign flipped but a real residual remains.
3. **Plate-vs-coil temperature ordering** is only *tied* in the model, while IR
   data implies the coil should be clearly hotter. The coil model is calibrated
   from real IR; the disc model never has been (IR on shiny aluminium is
   unreliable, ε≈0.1 vs camera ε=0.91). Needs an adhesive thermocouple on the
   disc bottom, then a re-fit of the disc convection coefficient.
4. **Variac dial → I table has only 3 anchor points** (0→0A, 220→5.00A,
   270→7.78A). A denser sweep would sharpen the dial input mode. Also still open:
   re-measure V at the coil terminals at dial=220 (the "dial 220 → 5A" reading and
   the older "190V → 5A" multimeter reading have never been reconciled — load sag
   or dial offset, unknown), and record the levitation gap at 7.78A.
5. **Real-time current sensing** (non-invasive CT clamp, e.g. SCT-013) is the
   intended long-term input path — current comes from the rig, thermal sensors
   stay validation-only.

## Validation strategy
1. EM reproduces the original benchmark (960/576 turns, 20A, R=65mm, no iron) →
   lift force balances gravity at z ≈ 11.3mm. **PAUSED**, see open question 2.
2. Switch to the real rig (1000/500, iron, 5A) → loss maps. **Done.**
3. Losses → thermal solver → T field → validate against sensors.
   **Coil side calibrated from IR; disc side pending hardware.**
4. Domain validation: Dirichlet vs Neumann BC comparison. **Done, PASS.**

## Run commands
See [README.md](../README.md) — note scripts are in the repo root, not `src/`.
