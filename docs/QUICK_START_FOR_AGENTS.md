# Quick Start Guide for Agents — DT4TM Project

**Mục đích:** Hướng dẫn các agent (Gemini, Claude, etc.) nhanh chóng hiểu kiến trúc dự án và có thể debug lỗi.

## Thứ tự đọc file .md

### 1. **CLAUDE.md** (bắt đầu ở đây)
- **Bắt buộc đọc trước tiên** — chứa tất cả quyết định đã khóa (locked decisions)
- Device specs: R=80mm plate, I=5A RMS (peak=7.07A), coil radii (inner 28–78mm, outer 104–124mm)
- Current convention: `current_A` trong params.yaml = **RMS measured**, nhưng EM solver cần **peak = RMS×√2**
- Thermal calibration: hA_inner=3.5611, hA_outer=4.3446, coil_C_scale=0.2241 (2026-07-01)
- Lift force validated: F_z≈1.85N > F_gravity(163g)=1.60N → z_eq≈4.1mm gap ✓
- Status code: cái nào [x] (done), cái nào [ ] (paused/pending)

### 2. **README.md**
- Cách setup (`python3 -m venv + pip install`)
- Chạy từng script (config.py → em_solver.py → thermal_solver.py → rom.py → digital_twin.py)
- Layout repo: source scripts flat (params.yaml, *.py), docs/ folder, outputs/ (gitignored)
- Roadmap Phase 1–8 (nhận biết Phase 6b, 7 chưa hoàn)

### 3. **docs/physics.md**
- Công thức chi tiết: eddy current → Joule loss q = ½σω²|A_φ|² [W/m³] (NOT |∇T|²/σ)
- σ(T) dependency: -0.39%/K (aluminum/copper) — dùng runtime multiplier, không re-solve EM
- Time-scale separation: **đừng** time-step EM at 50Hz, chỉ dùng phasor + cycle-average
- Iron core assumptions: linear μ_r, nhưng cần check saturation nếu B→1.5T
- Thermal FEM check: Q_in (∫q dV) = Q_out (∫h(T−T∞)dA) phải bằng nhau 0.000%

### 4. **docs/SENSOR_PLAN.md**
- Hardware: Arduino + MAX31855×2 thermocouple + IR thermometer
- Pipeline: serial CSV → data_io.py → calibrate_UA() → rom update
- Status: mock_sensor_data.csv đã test, real hardware chưa build (2026-07-01)

### 5. **docs/3D_MODEL_UPDATE_PLAN.md** (optional)
- 3D geometry: procedural vs STL model
- Separator ring rendering (region 5, r=81–101mm)

### 6. **docs/ARCHITECTURE.md** (optional, historical)
- Cũ, nhưng ghi chú về design tradeoffs

### 7. **docs/HANDOFF.md** (optional, historical)
- Cũ, reference cho phase trước

---

## Key Numbers to Know (để debug)

| Quantity | Value | Unit | Source |
|----------|-------|------|--------|
| Plate radius | 80 | mm | measured 2026-07-01 |
| Plate thickness | 3 | mm | measured 2026-07-01 |
| Inner coil r_min–r_max | 28–78 | mm | corrected 2026-07-01 |
| Outer coil r_min–r_max | 104–124 | mm | corrected 2026-07-01 |
| Current (operating) | 5.0 | A (RMS) | measured 190V→5A |
| Current peak (for EM) | 7.07 | A | =5×√2 (RMS→peak) |
| Lift force @ 5A | 1.85 | N | validates gravity (1.60N) ✓ |
| z_eq gap | 4.1 | mm | EM result, matches obs 2–3× |
| T_steady inner coil @ 5A | 40.5 | °C | at T_amb=20°C |
| T_steady outer coil @ 5A | 38.5 | °C | at T_amb=20°C |
| Domain size | ±500 | mm | validated Dirichlet vs Neumann <0.06% diff |
| Mesh refinement (EM) | — | — | domain-dependent, see em_solver.py |
| σ_Al(20°C) | 3.4e7 | S/m | params.yaml |
| σ_Cu(20°C) | 5.96e7 | S/m | params.yaml |
| Frequency | 50 | Hz | AC mains |
| Skin depth (Al) | 12 | mm | >>3mm plate → no fine through-thickness mesh |

---

## Common Debugging Checkpoints

### EM Solver
1. Check `config.py` output: current peak = 7.07A (if input 5A RMS)
2. Check benchmark: z_eq≈7.1mm (improved from 3.4mm, but not yet 11.3mm target)
3. Check losses: P_plate, P_iron, P_coil > 0; I²-check = 4.000 (double current → 4× power)
4. Domain size: run validate_domain_size() → Dirichlet vs Neumann diff <0.06%?

### Thermal Solver
1. Energy balance at steady state: Q_in (∫q dV) = Q_out (∫h(T−T∞)dA), error <0.001%
2. Convection BC: h_bot fix applied (q boundary condition, not T boundary)
3. Check temp range: plate 30–50°C, inner coil 35–45°C @ nominal 5A/20°C

### ROM
1. I² scaling: T_ss(2I)/T_ss(I) = 4.0 exactly (no iteration needed)
2. σ(T) correction: 70K rise → ~27% R change, visible in τ but small on T_ss

### HTML Twin (build_twin_html_fem.py)
1. No JS errors in headless Playwright test
2. Color: center core + separator ring use writeRampMetal() (silver→warm orange); coils use writeRampCopper() (dark red-brown→orange-yellow)
3. Levitation gap z_eq driven by I (z_eq=4.1mm @ 5A)
4. Time history: inner/outer coil temps + plate T_max plotted live
5. Geometry 100% procedural from params.yaml — STL NOT used for body (see "3D body geometry" section below)

---

## File Dependencies (for debugging integration)

```
params.yaml
    ↓
config.py (normalize units mm→m, derive I_peak from I_rms)
    ↓
em_solver.py (→ q_e map, P_plate/P_coil, lift F_z, benchmark check)
    ↓
thermal_solver.py (interp q_e, solve FEM, check energy balance)
    ├→ rom.py (build ROM from thermal FEM at I_ref)
    │   ├→ digital_twin.py (live GUI + I(t) → T(t))
    │   └→ build_twin_html_fem.py (bake into HTML)
    │
    └→ visualize.py (revolve 2D→3D, export GLB)

data_io.py (sensor CSV → calibrate_UA)
    └→ rom.calibrate_UA() (update τ from measurement)
```

---

## Mẹo cho Agent Debugging

1. **Luôn kiểm tra CLAUDE.md trước** — tất cả quyết định khóa ở đó
2. **Đọc kỹ comment "CORRECTED 2026-07-01"** — coil radii và thermal constants thay đổi
3. **Chú ý I_rms vs I_peak** — EM dùng peak (×√2), thermal dùng RMS (calibrated to RMS)
4. **σ(T) không phá vỡ real-time** — chỉ là scalar multiplier, không re-solve EM
5. **Energy balance là "source of truth"** — nếu không 0%, có lỗi tích phân hoặc BC
6. **Benchmark chưa hoàn** (z_eq≈7.1 vs 11.3 expected) — coi như known issue, không blocking
7. **Sensor pipeline testable mà không hardware** — dùng mock_sensor_data.csv

---

## 3D Body Geometry trong digital_twin_fem.html (updated 2026-07-01 session 3)

**Tất cả geometry được xây dựng PROCEDURALLY từ params.yaml — STL file chỉ dùng tham khảo hình dáng.**

### Coordinate System (Z-up, mm)
```
z = 0         → sàn (đáy tấm gỗ)
z = 8         → đáy cụm cuộn dây (coil assembly bottom)
z = 60        → đỉnh cụm cuộn dây (coil assembly top)
z = 63.8      → đáy đĩa nhôm levitating (z_coil_top + 3.8mm gap)
z = 63.8+zex  → đỉnh đĩa (zex = thickness × display_z_exaggeration từ params)
```

### Region Labels (reg) — JavaScript coloring và Three.js mesh
| reg | Phần | Material | r_in..r_out (mm) | z (mm) | Three.js mesh | Màu nhiệt |
|-----|------|----------|-----------------|--------|---------------|-----------|
| 0 | Levitating disc (đĩa nhôm) | Aluminium | 0..80 | 63.8..top | `plateM` | FEM vertex field (writeRamp) |
| 1 | Inner coil + gap-filler | Copper wire | 25..78 | 8..60 | `baseM` | writeRampCopper (dark red-brown→orange-yellow) |
| 2 | Outer coil | Copper wire | 104..124 | 8..60 | `baseM` | writeRampCopper |
| 3 | Center core (lõi giữa) | Ceramic/Al₂O₃ | 0..25 | 8..60 | `baseM` | writeRampMetal (silver-gray→warm orange) |
| 4 | Plywood octagonal frame | Wood | 130..165 | 0..60 | `woodM` | Flat brown (WOOD_RGB, static) |
| 5 | Separator / iron ring | Passive metal | 78..104 | 8..60 | `baseM` | writeRampMetal |

### Three.js Mesh Split (materials)
```javascript
baseM  = makeMesh(metallic parts: reg 1,2,3,5)  // roughness=0.42, metalness=0.68
woodM  = makeMesh(plywood frame: reg 4)           // roughness=0.88, metalness=0.02
plateM = makeMesh(aluminium disc: reg 0)          // roughness=0.35, metalness=0.75
```

### Triangle Counts (geometry)
```
center core     : ~960 tris   r=0..25mm     (build_solid_core)
core→inner gap  : ~960 tris   r=25..28mm    (revolve_ring, seamless fill)
inner coil      : ~960 tris   r=28..78mm    (revolve_ring, solid toroid)
separator ring  : ~960 tris   r=78..104mm   (revolve_ring, fills entire gap)
outer coil      : ~960 tris   r=104..124mm  (revolve_ring, solid toroid)
wood frame      :  ~96 tris   r=130..165mm  (build_octagonal_base + build_octagonal_frame, 8 sides)
TOTAL body      : ~4896 tris
levitating disc :  ~3072 tris (build_disc_mesh, FEM field mapped)
```

### Lý do KHÔNG dùng STL cho body geometry
STL cũ gây 5 lỗi hình ảnh:
1. `classify()` dùng r=26..45mm cho inner coil nhưng thực tế r=28..78mm → 99%+ inner coil bị misclassify, chỉ có 260 tris ở z=-2mm (mặt đáy mỏng)
2. STL shell rỗng → nhìn thấy xuyên qua (hollow) từ dưới lên
3. Màu flat red của material gốc → trông như nhựa, không phải kim loại
4. Khung hexagonal 6 cạnh (STL) thay vì bát giác 8 cạnh (thực tế)
5. Heat ramp chỉ trên outer shell, không có seamless fill

### Tọa độ chú ý (Three.js Y/Z swap)
JS template (lines ~868-870) swaps y/z khi đọc từ buffer:
```javascript
positions[i+1] = z;   // Three.js Y = physical Z (chiều cao)
positions[i+2] = -y;  // Three.js Z = -physical Y
```
→ `bb.max.y - bb.min.y` = chiều cao model (height axis), không phải bán kính.

### Thermal Ramp Functions (JS)
```javascript
writeRamp(col, idx, tnorm)       // scientific: blue→cyan→green→yellow→red (plate + legacy)
writeRampCopper(col, idx, tnorm) // copper: dark red-brown (cold) → orange-yellow (hot)
writeRampMetal(col, idx, tnorm)  // metal: silver-gray (cold) → warm orange (hot)
```
`tnorm` = normalized temperature 0 (T_amb) → 1 (T_steady at current I).

---

## Tài liệu này cập nhật: 2026-07-01