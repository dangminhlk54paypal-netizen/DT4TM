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
3. Levitation gap: z_eq(I)=4.1+2·21.4·ln(I/5) mm — LIÊN TỤC từ lift-off ≈4.54A
   (4.1mm @5A, ≈18.5mm @7A), kèm spring-mass dynamics (đĩa dao động ~9s rồi lắng).
   Display: `Z_GAP_EXAG=2.0` (SAME hệ số zex như độ dày đĩa) — gap KHÔNG còn bake
   vào geometry Python (`z_disc_bot = z_coil_top`, đĩa ngồi ngay trên coil top);
   toàn bộ gap hiển thị = `lev.z * 2.0` cộng ở runtime (JS `levLiftY()`).
4. Time history: inner/outer coil temps + plate T_max plotted live
5. Geometry 100% procedural from params.yaml — STL NOT used for body (see "3D body geometry" section below)
6. Geometry đã khớp thiết bị thật từ 2026-07-01 session 4 (khung gỗ r=174..194,
   air gaps để trống, coil màu vecni nâu sậm) — chi tiết trong section 3D Body
   Geometry bên dưới
7. **4 render fixes (2026-07-02)**: (a) gap display — xem mục 3 ở trên; (b) B-field
   lines giờ phản ứng với I: opacity + tốc độ dash flow scale theo `emScale =
   I_display/I_em_ref` (0 khi I=0, nhanh/đậm hơn khi I tăng, geometry hình dạng vẫn
   TĨNH vì bài toán tuyến tính); (c) màu coil chuyển sang thang TUYỆT ĐỐI cố định
   `T_COIL_HOT=80°C` (neo theo IR session 1: inner coil 79°C@7.8A) thay vì chia cho
   T_ss(I) — trước đây tăng I làm màu "nguội" tức thời; core/separator dùng cùng
   thang ×1.8 boost; (d) bỏ hẳn bloom (`EffectComposer`/`UnrealBloomPass` removed,
   `renderer.render()` trực tiếp) + vật liệu lì hơn cho coil/core/wood
   (`envMapIntensity` 0.8→0.15-0.25, chỉ đĩa nhôm giữ metallic 0.45).

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

## 3D Body Geometry trong digital_twin_fem.html (SUPERSEDED 2026-07-10 — xem GROUND TRUTH v2 bên dưới; giữ lại session-3 table cho lịch sử)

**Tất cả geometry được xây dựng PROCEDURALLY từ params.yaml — STL file chỉ dùng tham khảo hình dáng.**

### GROUND TRUTH v2 (2026-07-10, đo trực tiếp bằng thước trên rig thật — SUPERSEDES bảng session-3 bên dưới)
Bán kính và vật liệu chính xác, đọc từ `coils:`/`iron_core:`/`outer_iron_ring:` trong params.yaml:
```
r =    0..25.9   lõi trung tâm — SẮT (xác nhận hút nam châm 2026-07-10, mu_r=1000/sigma=1e6)
r =  25.9..27.9  AIR GAP 2mm
r =  27.9..61.9  INNER COIL, 1000 vòng, rộng 34mm (KHÁC session-3: khi đó ghi 28..78/50mm)
r =  61.9..64.9  AIR GAP 3mm
r =  64.9..79.9  IRON RING, rộng 15mm — SẮT (xác nhận hút nam châm 2026-07-10, cùng vật
                 liệu lõi trung tâm; KHÁC session-3: khi đó ghi 81..101/20mm)
r =  79.9..82.9  AIR GAP 3mm
r =  82.9..102.9 OUTER COIL, 500 vòng, rộng 20mm (KHÁC session-3: khi đó ghi 104..124)
r = 102.9..~130.4 AIR 25-30mm → vách trong khung gỗ
r ~130.4..~180.4  khung gỗ plywood BÁT GIÁC (8 cạnh), tổng ~50mm từ outer coil ra mép ngoài
```
⚠️ **OPEN QUESTION (chưa giải quyết)**: mu_r=1000 là placeholder mild-steel-like (chưa đo
B-H curve thật) — với giá trị này, lực nâng dự đoán z_eq≈11.7mm (khe nhìn thấy≈14.7mm),
NHƯNG quan sát thực tế là 7-8mm. Xem CLAUDE.md mục "LIFT FORCE" để biết chi tiết — KHÔNG
coi z_eq/khe hở hiện tại là đã validated.

### GROUND TRUTH v1 (2026-07-01 session 3, xem docs/real_model.png) — SUPERSEDED, giữ cho lịch sử
```
r =   0..25    lõi trung tâm — SẮT TỪ (user xác nhận trực quan; từng có "note conflict" với
               test 2026-07-01 nói KHÔNG hút — conflict này đã giải quyết 2026-07-10: user
               re-test xác nhận CÓ hút, xem GROUND TRUTH v2 ở trên)
r =  25..28    AIR GAP ~2–3mm (khe hở thật giữa lõi và inner coil)
r =  28..78    INNER COIL, 1000 vòng — dây đồng + lớp keo/nhựa thông cách điện màu nâu sậm
r =  78..81    AIR GAP ~3–3.5mm
r =  81..101   SEPARATOR / IRON RING — sắt từ (user xác nhận trực quan; magnet test PENDING)
r = 101..104   AIR GAP ~2mm
r = 104..124   OUTER COIL, 500 vòng — cấu tạo giống inner coil
r = 124..~174  AIR ~50mm — outer coil đứng HOÀN TOÀN ĐỘC LẬP, vách ngoài tiếp xúc không khí
r = ~174+      khung gỗ plywood BÁT GIÁC (8 cạnh) — KHÔNG ôm sát coil
```

### Coordinate System (Z-up, mm)
```
z = 0         → sàn (đáy tấm gỗ)
z = 8         → đáy cụm cuộn dây (coil assembly bottom)
z = 60        → đỉnh cụm cuộn dây (coil assembly top)
z = 60        → đáy đĩa nhôm trong BAKED geometry (= z_coil_top, KHÔNG bake gap —
                fixed 2026-07-02; gap vật lý được cộng ở JS runtime qua lev.z*2.0)
z = 60+zex    → đỉnh đĩa lúc nghỉ (zex = thickness × display_z_exaggeration từ params)
```

### Region Labels (reg) — theo thiết bị thật (code đã khớp từ 2026-07-01 session 4)
| reg | Phần | Material | r_in..r_out (mm) | z (mm) | Three.js mesh | Màu nhiệt |
|-----|------|----------|-----------------|--------|---------------|-----------|
| 0 | Levitating disc (đĩa nhôm) | Aluminium | 0..80 | 60..top (baked; gap runtime) | `plateM` | FEM vertex field (writeRamp) |
| 1 | Inner coil (1000T) | Đồng + keo cách điện nâu sậm | 28..78 | 8..60 | `coilM` | writeRampCopper |
| 2 | Outer coil (500T) | Đồng + keo cách điện nâu sậm | 104..124 | 8..60 | `coilM` | writeRampCopper |
| 3 | Center core (lõi giữa) | Sắt từ (per user; model hiện mu_r=1.0) | 0..25 | 8..60 | `baseM` | writeRampMetal |
| 4 | Plywood octagonal frame | Wood | 174..194 (từ `device_frame` trong params.yaml) | 0..60 | `woodM` | Flat brown (WOOD_RGB, static) |
| 5 | Separator / iron ring | Sắt từ (per user; magnet test pending) | 81..101 | 8..60 | `baseM` | writeRampMetal |
| — | Air gaps (KHÔNG mesh, để trống) | Air | 25..28, 78..81, 101..104, 124..174 | — | — | — |

### ✅ 3 sai lệch render đã FIX (2026-07-01 session 4)
User đối chiếu render với mô hình thật (real_model.png) và chỉ ra 3 lỗi; đã sửa
trong build_twin_html_fem.py, verify bằng headless Playwright (0 JS errors):
1. **Khung gỗ ôm sát coil** — TRƯỚC: `r_frame_in = r_o_out + 6.0` ≈ 130mm, nuốt mất
   ~50mm không khí. SAU: đọc từ block `device_frame` trong params.yaml
   (air_gap_mm=50, wall_thickness_mm=20) → frame r=174..194mm, outer coil đứng độc lập.
2. **Air gaps bị lấp đặc** — TRƯỚC: khe 25..28mm lấp bằng vật liệu coil (`V_coregap`);
   separator lấp toàn bộ 78..104mm. SAU: bỏ hẳn V_coregap; separator chỉ còn đúng
   81..101mm (đọc từ `outer_iron_ring` trong params.yaml); cả 4 khe không khí
   (25-28, 78-81, 101-104, 124-174) là khoảng trống hình học thật.
3. **Coil trông như nhựa phát sáng** — TRƯỚC: COPPER_COLD=[0.52,0.18,0.07] đỏ bão hòa,
   metalness=0.68 chung với các phần kim loại. SAU: tách mesh `coilM` riêng
   (roughness=0.30, metalness=0.20 — vecni bóng phủ dây đồng, không phải kim loại
   trần); COPPER_COLD=[0.30,0.14,0.08] nâu sô-cô-la sậm khớp ảnh thật,
   COPPER_HOT=[0.93,0.55,0.16] cam ấm (bớt neon).
Ngoài ra: label "Center Core (ceramic)" → "Center Core" (vật liệu đang tranh chấp),
và expose `window.twinDebug = {camera, controls, size}` để test headless đặt camera.

### Three.js Mesh Split (materials) — matte pass 2026-07-02, xem "4 render fixes" ở trên
```javascript
// makeMesh(sub, roughness, metalness, envMapIntensity=0.8)
baseM  = makeMesh(core + separator: reg 3,5)  // roughness=0.60, metalness=0.30, envInt=0.25 — kim loại xỉn/oxit
coilM  = makeMesh(coils: reg 1,2)             // roughness=0.80, metalness=0.05, envInt=0.15 — vecni lì, hấp thụ sáng
woodM  = makeMesh(plywood frame: reg 4)       // roughness=0.90, metalness=0.00, envInt=0.05
plateM = makeMesh(aluminium disc: reg 0)      // roughness=0.45, metalness=0.65, envInt=0.45 — kim loại thật duy nhất
```
Bloom postprocessing (`EffectComposer`/`UnrealBloomPass`) đã bị XÓA hoàn toàn
(2026-07-02) — render trực tiếp qua `renderer.render(scene, camera)`. Trước đó
bloom.strength=0.42 gần như luôn bật (mặc định I=5A) gây chói/loá kim loại.

### Triangle Counts (geometry, sau fix session 4)
```
center core     : ~960 tris   r=0..25mm     (build_solid_core)
inner coil      : ~960 tris   r=28..78mm    (revolve_ring, solid toroid; khe 25-28 để trống)
separator ring  : ~960 tris   r=81..101mm   (revolve_ring; khe 78-81 và 101-104 để trống)
outer coil      : ~960 tris   r=104..124mm  (revolve_ring, solid toroid)
wood frame      :  ~96 tris   r=174..194mm  (octagon 8 cạnh, cách coil 50mm air)
TOTAL body      : ~3936 tris
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
Disc (`writeRamp`): `tnorm` adaptive/relative — see `colorScaleMode` (auto/relative/absolute).
Coils/core/ring (`writeRampCopper`/`writeRampMetal`, fixed 2026-07-02): `tnorm` = ABSOLUTE
scale `(T - T_amb) / (T_COIL_HOT=80°C - T_amb)`, anchored to IR session 1 (inner coil
79°C@7.8A, hottest ever measured) — NOT divided by the current-dependent T_ss(I) anymore
(that made the color flip "cold" instantly whenever I changed, and pin to full-hot at any
steady state). Core/separator (`tnIron`) apply the same absolute scale ×1.8 boost (real
core/ring only reach ~45°C, tnorm≈0.31 unboosted — would look frozen silver).

---

## Tài liệu này cập nhật: 2026-07-02