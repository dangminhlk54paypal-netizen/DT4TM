# HANDOFF — Digital Twin for Thermal Management

> **Primary source of truth is [CLAUDE.md](../CLAUDE.md) + [README.md](../README.md).**
> This file is a quick handoff status summary. Last updated: 2026-07-02 (session 6).

## Next-session prompt (paste this to resume)
> Tiếp tục dự án digital twin nhiệt cho thiết bị levitator TEAM 28. Đọc CLAUDE.md trước —
> có các việc mở đang chờ:
> 1. **Power-supply / Variac dial — STEP 1 xong, STEP 2-3 còn mở** (session 6, 2026-07-02).
>    Đã xác định nguồn cấp là biến áp xoay tay Carroll & Meynell CMV 10 E-1 (240V vào,
>    0-270V ra, 50Hz) qua ampe kế, từ docs/rig_photo.jpg. Đã thêm bảng nội suy dial→I vào
>    params.yaml (`power_supply` block, 3 điểm neo: 0→0A, 220→5.00A, 270→7.78A) và một chế
>    độ "Variac Dial" trong cả build_twin_html_fem.py (HTML twin) và digital_twin.py (GUI
>    matplotlib) — kéo núm ảo giống núm thật thay vì gõ thẳng dòng điện. Còn THIẾU:
>    (a) đo dày thêm bảng dial→I (hiện chỉ 3 điểm, ~20 vạch/điểm sẽ tốt hơn),
>    (b) đo lại V tại đầu cực cuộn dây khi dial=220 — có mâu thuẫn giữa "dial 220 → 5A" và
>    multimeter cũ đo "190V → 5A" (2026-06-23), chưa rõ do sụt áp dưới tải hay lệch vạch núm,
>    (c) ghi độ cao levitation tại 7.78A (cũng lấp câu hỏi mở `Z_OBS_7_75A_MM` của WP-A),
>    (d) cảm biến dòng phần cứng thời gian thực (kẹp CT không xâm lấn, vd SCT-013) — MỤC
>    TIÊU CUỐI của người dùng là lấy I trực tiếp từ rig, KHÔNG dùng thermal sensor làm input
>    (sensor chỉ để validate). Xem CLAUDE.md mục "Power-supply integration".
> 2. **Câu hỏi vật lý chưa giải quyết (vẫn mở, không đổi từ trước)**: twin đang cho T_ss đĩa
>    nhôm (61.7°C @5.5A) CAO HƠN cuộn dây (~59°C), nhưng ảnh IR thực tế
>    (docs/thermal_test.png) cho thấy cuộn dây nóng hơn đĩa rất nhiều. Model cuộn dây đã
>    calibrate từ IR thật; model đĩa (ROM FEM, ΔT_max=27K@5A) CHƯA từng calibrate (h là số
>    đoán, vì IR đo đĩa nhôm bóng không tin được — ε thực ≈0.1 vs camera set ε=0.91). Cần đo
>    đĩa bằng thermocouple dán (không phải IR) rồi fit lại hệ số đối lưu h của đĩa trong
>    rom.py/thermal_solver.py.
> 3. **em_domain đã kiểm tra lại — KHÔNG còn là vấn đề mở.** params.yaml hiện đang ở
>    ±500mm (r_max_mm=500, z_min/max=±500), đúng như "locked decision" trong CLAUDE.md
>    (đã PASS validation Dirichlet vs Neumann, diff<0.06%). Nghi vấn ±1000mm ghi ở bản
>    HANDOFF.md cũ đã không còn tái hiện — có thể đã được ai đó revert; không cần hành động
>    thêm trừ khi phát hiện lại giá trị khác ±500mm.
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
- [x] build_twin_html.py — Phase 5: standalone digital_twin.html (double-click to run).
      **Deleted 2026-07-02 (commit ec64ec1), superseded by build_twin_html_fem.py.**
- [x] data_io.py + arduino/thermal_sensor.ino — sensor bridge implemented (`SensorReader`,
      `calibrate_from_file()`, `live_compare()`); mock-data tested end-to-end via
      `mock_sensor_data.csv` / `--port mock`. **Waiting on the real Arduino rig** to log
      actual data.
- [x] power_supply / Variac dial input — STEP 1 done (session 6, 2026-07-02): identified
      the rig's AC source (Carroll & Meynell CMV 10 E-1 variac), added `params.yaml
      power_supply` dial→I table + `Config.dial_to_current_A()` + a "Variac Dial" input
      mode in both `build_twin_html_fem.py` and `digital_twin.py`. **STEP 2 (denser
      calibration table + terminal-V re-measurement) and STEP 3 (live hardware current
      sensing) still open** — see CLAUDE.md and the next-session prompt above.

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
- **Session 6 (2026-07-02)**: Identified the rig's AC power supply (Carroll & Meynell
  CMV 10 E-1 variac, from docs/rig_photo.jpg) and wired a dial→current calibration table
  into params.yaml + a "Variac Dial" input mode into both twins — STEP 1 of driving the
  simulation directly from the rig's current/dial instead of thermal sensors (sensors stay
  validation-only). STEP 2 (denser table, terminal-V re-measurement, 7.78A gap
  measurement) and STEP 3 (live CT-clamp current sensing) are next.
- **Session 7**: Either (a) the disc/plate thermocouple calibration from Session 4/5's
  open question, or (b) power-supply steps 2-3 above — whichever data collection happens
  first in the next lab session should probably be done together (same lab visit).

## Run commands — see [README.md](../README.md) (note: `python config.py`, NOT `src/`).
