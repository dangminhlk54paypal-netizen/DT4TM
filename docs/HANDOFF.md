# HANDOFF — Digital Twin for Thermal Management

> **Primary source of truth is [CLAUDE.md](../CLAUDE.md) + [README.md](../README.md).**
> This file is a quick handoff status summary. Last updated: 2026-07-02.

## Next-session prompt (paste this to resume)
> Tiếp tục dự án digital twin nhiệt cho thiết bị levitator TEAM 28.
> Đọc CLAUDE.md trước — có 2 việc mở đang chờ:
> 1. **Câu hỏi vật lý chưa giải quyết**: twin đang cho T_ss đĩa nhôm (61.7°C @5.5A) CAO HƠN
>    cuộn dây (~59°C), nhưng ảnh IR thực tế (docs/thermal_test.png) cho thấy cuộn dây nóng
>    hơn đĩa rất nhiều. Model cuộn dây đã calibrate từ IR thật; model đĩa (ROM FEM,
>    ΔT_max=27K@5A) CHƯA từng calibrate (h là số đoán, vì IR đo đĩa nhôm bóng không tin
>    được — ε thực ≈0.1 vs camera set ε=0.91). Cần đo đĩa bằng thermocouple dán (không phải
>    IR) rồi fit lại hệ số đối lưu h của đĩa trong rom.py/thermal_solver.py.
> 2. **params.yaml `em_domain` đã bị đổi r_max/z_min/z_max từ ±500mm → ±1000mm** (không rõ
>    do ai/khi nào — phát hiện lúc commit ngày 2026-07-02, KHÔNG phải do tôi chỉnh). Điều
>    này mâu thuẫn với "locked decision" trong CLAUDE.md ghi domain ±500mm đã PASS validation
>    (Dirichlet vs Neumann, diff<0.06%). Cần hỏi người dùng có chủ đích hay không, rồi hoặc
>    (a) re-run `em_solver.validate_domain_size()` ở ±1000mm và cập nhật CLAUDE.md, hoặc
>    (b) revert về ±500mm nếu là nhầm lẫn.
> Sau đó tiếp tục theo mục "Pending tasks" trong CLAUDE.md / docs/HANDOFF.md.

## Goal
A digital twin that predicts the **real-time temperature field** of the aluminium plate
in the TEAM 28 electrodynamic levitation device (TEMF). Validate against the real rig
→ 3D visualization → AR app → QR code.

## Architecture decisions (finalized)
- **No FEMM** (dev machine is macOS). Pure Python: `numpy + scipy + pyyaml + matplotlib`
  (+ `trimesh` for GLB export). Problem is **axisymmetric** → solve in 2D (r, z), revolve to 3D.
- **Real-time:** losses scale as I², spatial pattern stays fixed → run FEM once at I_ref=5A,
  online inference is just a multiply by (I/I_ref)². I²-scaling verified: 4.000000.
- All parameters live in [params.yaml](../params.yaml). Source scripts + input data are
  **flat in the repo root**; docs live in `docs/`, generated files in `outputs/`.

## Device numbers (in params.yaml)
- Aluminium plate: **R=80mm (Ø16cm)**, thickness 3mm (placeholder — needs to be MEASURED), σ=3.4e7 S/m.
- Current: **î = 5 A** MEASURED (rig: 220V → 5A), f = 50 Hz. voltage_V=220 in params.
- Turns: **inner=1000, outer=500**.
- **Iron cores present** (μ_r=1000, placeholder geometry — CONFIRM with the real rig).
- payload_model (steel disc): placeholder, **disabled by default**.
- **T_ambient = 20°C** (professor: keep it simple for Phase 1).
- **EM domain: 1×1m box** (±500mm; professor: validate via Dirichlet vs Neumann BC).

## Professor Feedback (Juni 2026)
- Domain: 1×1m box OK, validate with BC comparison
- T_amb: constant 20°C, no lab sensor needed yet
- Excitation: 220V/5A measured, no real-time Messgerät yet
- Sensors: Arduino + thermocouple + IR thermometer, team builds, professor buys parts
- Scope: disc-only simulation as starting point is also OK

## Status (mostly done)
- [x] config.py, params.yaml, thermal_solver.py (energy balance 0.000%)
- [x] em_solver.py — AC eddy currents + lift force computed; original-benchmark check
      **IMPROVED but not yet matching** (z_eq≈7.1mm vs 11.3mm expected, was 3.4mm before
      2026-06-23 — the "10.9mm/PASS" once logged here was never actually reproduced,
      bisected through git history. Fixed root cause: benchmark was reusing the rig's
      coil radii instead of the original 960/576-turn problem's own geometry from
      TeamProblem28.pdf — now uses the real radii, halving the error. Remaining 37% gap
      unexplained — see CLAUDE.md)
- [x] rom.py — real-time ROM (I² + transient τ≈3.4 min + σ(T) correction)
- [x] digital_twin.py — interactive twin (current slider, plate selector, scenarios)
- [x] visualize.py — revolve 2D→3D, export plate.glb
- [x] sim_plates.py — compare plates across plate_library
- [x] build_twin_html.py — Phase 5: standalone digital_twin.html (double-click to run)
- [x] data_io.py + arduino/thermal_sensor.ino — sensor bridge implemented (`SensorReader`,
      `calibrate_from_file()`, `live_compare()`); mock-data tested end-to-end via
      `mock_sensor_data.csv` / `--port mock`. **Waiting on the real Arduino rig** to log
      actual data.

## Validation
1. EM reproduces original benchmark (960/576, 20A, R=65mm, no iron) → lift force balances at z≈11.3mm. **NOT YET** (z_eq≈7.1mm after fixing the coil geometry, see CLAUDE.md) — 37% error remains, unexplained.
2. Switch to real rig (1000/500, iron, 5A) → loss maps.
3. Losses → thermal solver → T field. **Thermal validation: Arduino + thermocouple + IR thermometer (see SENSOR_PLAN.md).**
4. Domain validation: Dirichlet vs Neumann BC comparison (Session 2).

## Next Sessions
- **Session 2**: Domain & BC validation (Dirichlet vs Neumann comparison) — DONE at ±500mm
  (see CLAUDE.md), but params.yaml `em_domain` now shows ±1000mm uncommitted — re-validate
  or revert (see prompt above).
- **Session 3**: Re-run pipeline with T_amb=20°C, regenerate HTML twin — DONE.
- **Session 4 (2026-07-02)**: HTML twin visual fixes — coil emissive glow, label
  de-overlap, B-field line density vs I, live coil T_ss arrows. See CLAUDE.md for detail.
  Surfaced an open question: plate T_ss > coil T_ss contradicts IR data — plate model is
  uncalibrated (see prompt above).
- **Session 5**: Build the real Arduino rig, log a real run, calibrate `data_io.py`
  against actual sensor data instead of `mock_sensor_data.csv` — also use this run to
  calibrate the disc/plate convection coefficient (currently uncalibrated FEM guess).

## Run commands — see [README.md](../README.md) (note: `python config.py`, NOT `src/`).
