# Thermal Digital Twin — TEAM 28 (Electrodynamic Levitation Device)

A digital twin that predicts the **temperature field in real time** for the
aluminium plate of the TEAM 28 electrodynamic levitation device (at TEMF).
It is validated against the real physical setup, then visualized in 3D, and
finally delivered through an **AR app + QR code**. Operating current ≤ 5 A.

## Why real-time is possible
At a fixed frequency with linear materials, **Joule losses scale as I²** while
the *spatial loss pattern stays fixed*. So we run the high-fidelity FEM solve
**once** at a reference current `I_ref`, and at runtime any current `I` is just a
multiply by `(I/I_ref)²` → prediction in milliseconds. Verified: ΔT(5A)/ΔT(1A) = 25 = 5².

## Architecture decisions
- **No FEMM** (Windows-native; the dev machine is macOS). Pure **Python** instead.
- The problem is **axisymmetric** → we solve in 2D (r, z) and revolve to 3D for display.
- Core stack: `numpy + scipy + pyyaml + matplotlib` (Phase 1–2);
  `pyvista + meshio + qrcode` added later (Phase 4–5).

## Setup (macOS)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run
All source lives flat in the repo root (no `src/` subfolder).
```bash
python config.py            # print normalized parameters
python em_solver.py         # AC eddy losses + I² check + benchmark (z_eq≈10.9mm vs 11.3)
python thermal_solver.py    # solve heat + energy balance (expect "error=0.000%")
python rom.py               # real-time ROM demo (I² scaling + transient)
python digital_twin.py      # interactive live twin (slider I, plate selector)
python visualize.py --no-show   # revolve 2D→3D, export plate.glb
python sim_plates.py            # compare plates from plate_library
python build_twin_html.py 3D_model.stl   # bake standalone AR twin → digital_twin.html
```

## Layout (flat — everything in repo root)
```
params.yaml         # ALL knobs (units, current, materials, BCs, mesh)
config.py           # loads params, converts mm->m, derives P ~ I^2
thermal_solver.py   # axisymmetric heat FEM (pure numpy/scipy)
em_solver.py        # AC eddy currents -> real loss map + lift force + benchmark
rom.py              # real-time ROM: I^2 + first-order transient + σ(T)
digital_twin.py     # interactive live loop I(t) -> T(r,z,t)
visualize.py        # revolve 2D->3D, export GLB/OBJ (+ optional PyVista)
sim_plates.py       # compare thermal response across plate_library
build_twin_html.py  # bake STL + physics into a standalone digital_twin.html
3D_model.stl                    # colleague's CAD (source, meters, axisymmetric)
levitation_height_team28.csv    # Table I from the PDF (levitation height, validation)
physics.md                      # full formulation / derivations
```

## Roadmap
- [x] **Phase 1a** — Axisymmetric heat solver, verified by energy balance.
- [x] **Phase 1b** — EM solver (AC eddy currents) — real losses + benchmark z_eq≈10.9mm.
- [x] **Phase 2** — Real-time ROM (I² + first-order transient + σ(T) correction).
- [x] **Phase 3** — Twin loop (interactive). Measured-data ingestion: pending real sensors.
- [x] **Phase 4** — Revolve 2D→3D, export GLB/OBJ.
- [x] **Phase 5** — Standalone interactive AR twin (`digital_twin.html`). QR: optional.
- [ ] **Remaining** — `data_io.py` + thermal validation once sensor data exists.

## Axisymmetric FEM math (reference)
Weak form with volume weight `2πr dr dz`:

    ∫ k ∇T·∇v · 2πr dA  +  ∫_Γ h T v · 2πr ds
        =  ∫ p v · 2πr dA  +  ∫_Γ h T∞ v · 2πr ds

- P1 elements: `∇T` is constant per triangle → `Ke = 2π·k·(b bᵀ + c cᵀ)·A·r_c`.
- Convection edge (linear r weight):
  `Kedge = 2π·h·(L/12)·[[3rₐ+r_b, rₐ+r_b],[rₐ+r_b, rₐ+3r_b]]`.
- The axis r=0 is a symmetry boundary (natural condition, not imposed).
- **Required check:** at steady state Q_in (∫p dV) must equal Q_out (∫h(T−T∞)dA).
