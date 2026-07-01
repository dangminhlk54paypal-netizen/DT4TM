# Công thức Vật lý & Toán học — Digital Twin Nhiệt (TEAM 28-like Levitator)

> **Mục tiêu:** Dự đoán trường nhiệt độ T(r, z, t) theo thời gian thực khi dòng điện
> xoay chiều đi qua hai cuộn dây đồng. Thiết bị có đối xứng trục → giải 2D (r, z),
> hiển thị 3D bằng cách xoay tròn.

---

## 0. Tổng quan pipeline (đầu vào → đầu ra)

```
Dòng điện î (A), f = 50 Hz
         │
         ▼
┌─────────────────────────────┐
│   BƯỚC 1: EM Solve (FEM)    │  em_solver.py
│   Giải phương trình A_φ     │
│   → q(r,z) [W/m³] trên tấm │
│   → P_coil [W] (nhiệt Joule)│
└────────────┬────────────────┘
             │ q_e, P_coil
             ▼
┌─────────────────────────────┐
│  BƯỚC 2: Thermal Solve (FEM)│  thermal_solver.py
│  Giải phương trình nhiệt    │
│  → T_steady(r,z) tại I_ref  │
│  → ΔT_ref(r,z) [K] (mode)  │
└────────────┬────────────────┘
             │ ΔT_ref, UA, τ
             ▼
┌─────────────────────────────┐
│  BƯỚC 3: ROM (real-time)    │  rom.py
│  T(r,z,t) = T_amb           │
│     + β(t) · ΔT_ref(r,z)   │
│  ODE: τ·dβ/dt = (I/I_ref)² │
│            · s(β) − β       │
└────────────┬────────────────┘
             │ T(r,z,t)
             ▼
┌─────────────────────────────┐
│  BƯỚC 4: Hiển thị           │  digital_twin.py
│  Slider I(t), animation,    │  build_twin_html_fem.py
│  3D revolve, AR twin        │
└─────────────────────────────┘
```

**Tại sao real-time?** Hệ EM là **tuyến tính** và vật liệu không thay đổi theo tần số
→ A_φ ∝ î → q ∝ î². Chỉ cần **giải FEM một lần** ở I_ref; runtime chỉ là nhân vô
hướng (I/I_ref)².

---

## 1. Bước 1 — Bài toán Điện từ (EM Solver)

### 1.1 Tại sao chỉ dùng phasor?

Dòng điện là i(t) = î·sin(ωt), f = 50 Hz. Nhiệt học có hằng số thời gian τ ≈ 10 phút.
Nếu time-step EM theo 50 Hz thì sẽ cực kỳ lãng phí — nhiệt học không "thấy" được dao
động nhanh như vậy. Thay vào đó:

- Giải **một lần** bằng **phasor phức** A_φ(r,z) ∈ ℂ ở biên độ î.
- Lấy **trung bình chu kỳ** của công suất (hệ số ½ từ ∫sin²(ωt) dt = ½).

### 1.2 Phương trình chủ đạo (Magnetic Vector Potential)

Với giả thiết đối xứng trục, chỉ có thành phần phương vị A_φ(r,z) ≠ 0:

```
−∇·(ν ∇A_φ) + ν·A_φ/r²  + jωσ·A_φ = J_s

trong đó:
  ν  = 1/μ = 1/(μ_r · μ₀)   [H⁻¹/m]  reluctivity
  ω  = 2πf                             [rad/s]
  σ                                    [S/m]   độ dẫn điện
  J_s = ±N·î/S_coil                   [A/m²]  mật độ dòng nguồn
```

Ba số hạng có ý nghĩa vật lý:
| Số hạng | Ý nghĩa |
|---------|---------|
| `−∇·(ν ∇A_φ)` | Khuếch tán từ trường (curl-curl) |
| `ν·A_φ/r²` | Chỉnh hình dạng trục đối xứng (thành phần φ) |
| `jωσ·A_φ` | Dòng xoáy (eddy current) phản ứng lại trong tấm Al + lõi sắt |

**Điều kiện biên:**
- r = 0 (trục đối xứng): A_φ = 0 (điều kiện vật lý bắt buộc)
- Biên ngoài (r_max = 500 mm, z = ±500 mm): A_φ = 0 (Dirichlet, trường tắt dần xa thiết bị)

*Validate bằng cách đổi sang Neumann BC (∂A_φ/∂n = 0) và so sánh — nếu trường gần thiết
bị không đổi, miền đủ lớn. Đã qua kiểm tra: sai khác < 0.06%.*

### 1.3 Rời rạc hóa FEM (P1 triangles trên lưới cấu trúc)

Lưới (r, z) hình chữ nhật được chia thành tam giác (hai tam giác mỗi ô):

```
a ─── b
│  \  │    → tam giác [a, b, d] và [b, c, d]
d ─── c
```

Với phần tử tam giác P1 (hàm thử bậc 1), trên mỗi phần tử e:

**Gradient của hàm dạng:** (b = dN/dr, c = dN/dz, không phụ thuộc vào tọa độ phần tử)

```
b = [z_j−z_m, z_m−z_i, z_i−z_j] / (2·Area)
c = [r_m−r_j, r_i−r_m, r_j−r_i] / (2·Area)
```

**Ma trận độ cứng cục bộ K_e (phức) gồm 3 đóng góp:**

```
Ke  =  ν·(b bᵀ + c cᵀ) · r_c · Area          ← curl-curl (từ trường)
    +  ν·(1/r_c)·Area·M̂                        ← A/r² (đối xứng trục)
    + jωσ·r_c·Area·M̂                           ← eddy current (mass matrix)

M̂ = [[2,1,1],[1,2,1],[1,1,2]] / 12            ← consistent mass matrix
r_c = (r_i + r_j + r_m)/3                     ← centroid radius
```

**Vector nguồn cục bộ:**

```
f_e = J_s · r_c · Area / 3    (trên mỗi node của phần tử nguồn)
```

Sau khi lắp ghép toàn cục và áp điều kiện biên, giải hệ tuyến tính phức:

```
K · A = F     →    A_φ(r,z) ∈ ℂ
```

bằng `scipy.sparse.linalg.spsolve` (trực tiếp, hệ ~10⁴–10⁵ ẩn số).

### 1.4 Tính công suất nhiệt Joule (hậu xử lý)

**Mật độ công suất tức thời** tại r,z trong vật dẫn:

```
J_e(r,z) = −jωσ · A_φ(r,z)    [A/m²]  (phasor dòng xoáy)
```

**Công suất nhiệt trung bình chu kỳ** (hệ số ½ từ sin²):

```
q(r,z) = |J_e|² / (2σ) = ½ · σ · ω² · |A_φ|²    [W/m³]
```

**Công suất tổng từng vùng** (tích phân thể tích axisymmetric, dV = 2πr dr dz):

```python
P_plate  = Σ_e  q_e · 2π · r_c · Area_e    (tấm Al)
P_iron   = Σ_e  q_e · 2π · r_c · Area_e    (lõi sắt)
```

**Tổn hao ohmic trong cuộn dây** (tính trực tiếp từ R dây, vật lý hơn là từ J_s FEM):

```
R_coil = N · (2π · r_mean) / (σ_Cu · A_wire)    [Ω]
P_coil = ½ · î² · R_coil                        [W]
```

*Kết quả tại 5A: P_plate ≈ 2.61 W, P_iron ≈ 0.63 W, P_coil ≈ 72.8 W → **cuộn dây
chiếm ưu thế**.*

### 1.5 Từ trường B và kiểm tra bão hòa sắt từ

Từ A_φ, tính B tại centroid mỗi phần tử:

```
B_r = −∂A_φ/∂z = −(c·A)           (phasor)
B_z = A_φ/r + ∂A_φ/∂r = A_c/r_c + (b·A)    (phasor)

|B|_rms = √(|B_r|² + |B_z|²) / √2
```

**Mô hình bão hòa Lorentzian** (Picard iteration):

```
μ_r_eff(B) = 1 + (μ_r_lin − 1) / (1 + (B/B_sat)²)
```

- B → 0: μ_r_eff → μ_r_lin = 1000 (tuyến tính)
- B → ∞: μ_r_eff → 1 (bão hòa hoàn toàn)
- Tại 5A: B_max ≈ 0.311 T < B_sat = 1.5 T → **không bão hòa**, μ_r_lin = 1000 hợp lệ.

---

## 2. Bước 2 — Bài toán Nhiệt (Thermal Solver)

### 2.1 Phương trình vi phân

**Trạng thái ổn định** (steady state):

```
−∇·(k ∇T) = q(r,z)       trong tấm nhôm

Điều kiện biên Robin (đối lưu):
  −k ∂T/∂n = h·(T − T_∞)    trên tất cả bề mặt
  r = 0: điều kiện tự nhiên (symmetry, không cần áp)
```

**Hằng số:**
- k = 237 W/(m·K) — hệ số dẫn nhiệt nhôm
- h = `h_convection_W_per_m2K` (phía trên), `h_bottom_W_per_m2K` (phía dưới, gần cuộn)
- T_∞ = T_amb = 20°C (đồng nhất) — theo phản hồi của giáo sư (đơn giản nhất trước)
- Phía đáy tấm: `T_∞_bot = T_amb + k_coil_coupling · P_coil` (mô hình kết nối nhiệt cuộn→không khí→tấm)

### 2.2 Rời rạc hóa FEM (P1, axisymmetric, dV = 2πr dr dz)

**Ma trận độ cứng nhiệt cục bộ** (tích phân trọng số r):

```
Ke = 2π · k · (b bᵀ + c cᵀ) · Area · r_c      [W/K]
```

**Đóng góp đối lưu trên cạnh biên** (tích phân tuyến tính theo r):

```
Kedge = 2π · h · (L/12) · [[3rₐ+r_b,  rₐ+r_b ],
                             [rₐ+r_b,  rₐ+3r_b]]     [W/K]

feconv = 2π · h · T_∞ · (L/12) · [[3rₐ+r_b, rₐ+r_b],
                                    [rₐ+r_b, rₐ+3r_b]] · [1,1]ᵀ  [W]
```

trong đó L = chiều dài cạnh biên, rₐ,r_b = bán kính hai đầu cạnh.

**Nguồn nhiệt (vector F):**

```
F_i += q_e · 2π · r_c · Area / 3    cho mỗi node i của phần tử e
```

Nguồn q_e lấy từ bản đồ EM (`q(r,z)`) bằng interpolation (`LinearNDInterpolator`).
Sau đó **normalize** để đảm bảo ∫q dV = P_total (bảo toàn năng lượng).

**Giải hệ:**

```
(K_cond + K_conv) · T = F_source + F_conv
```

**Kiểm tra cân bằng năng lượng:**

```
Q_in  = ∫ q dV = P_total
Q_out = Σ_edges  h·(T̄_edge − T_∞) · 2π·r̄_edge · L_edge

Error = |Q_in − Q_out| / Q_in × 100%  → phải = 0.000%
```

---

## 3. Bước 3 — Reduced-Order Model (ROM) — Công cụ real-time

### 3.1 Tách bài toán thành Mode + Biên độ

Quan sát then chốt: khi vật liệu tuyến tính và hình học cố định, **hình dạng không gian**
của trường nhiệt không thay đổi khi thay đổi I — chỉ có **biên độ** thay đổi.

Định nghĩa:

```
T(r,z,t) = T_amb + β(t) · ΔT_ref(r,z)

trong đó:
  ΔT_ref(r,z) = T_steady(I_ref) − T_amb    [K]  (tính một lần bằng FEM)
  β(t)        ∈ ℝ                           (vô thứ nguyên, tiến hóa theo thời gian)
```

### 3.2 Phương trình ODE cho β(t)

Mô hình RC gộp bậc nhất (first-order lumped):

```
τ · dβ/dt = (I/I_ref)² · s(β) − β

trong đó:
  τ  = C / UA              [s]   hằng số thời gian nhiệt (~10.6 phút)
  C  = ρ · c_p · V         [J/K] nhiệt dung tấm nhôm
  UA = P_ref / ΔT_mean_ref [W/K] hệ số truyền nhiệt tổng thể
  s(β) = 1/(1 + α · β · ΔT_mean_ref)     ← hiệu chỉnh σ(T)
```

**Giải nghiệm:**
- Steady state: β_ss = (I/I_ref)² · s(β_ss)  → giải phương trình bậc hai trong β
- Transient: dùng `scipy.integrate.solve_ivp` (Euler ẩn trong digital_twin.py)

### 3.3 Hiệu chỉnh σ(T) — tại sao cần?

Độ dẫn điện nhôm giảm theo nhiệt độ:

```
σ(T) = σ₀ / (1 + α·(T − T₀))      α ≈ 3.9×10⁻³ K⁻¹
```

Điều này ảnh hưởng ngược chiều đến công suất:

| Vùng | Công suất ∝ | Hệ quả khi nóng |
|------|------------|-----------------|
| Tấm nhôm (eddy) | P_plate ∝ σ_Al | Tấm nóng → σ giảm → **P giảm** |
| Cuộn dây (ohmic) | P_coil ∝ 1/σ_Cu | Cuộn nóng → σ giảm → **P tăng** |

Hàm hiệu chỉnh cho tấm:

```
s(β) = 1 / (1 + α · ΔT_mean(β))    (< 1 khi tấm nóng)
```

Hội tụ trong ~2–3 vòng lặp (hệ một chiều, yếu — không cần giải lặp nặng).

### 3.4 Quy tắc I² — tại sao giữ được?

Hệ EM tuyến tính → A_φ ∝ î → q ∝ î² → P ∝ î² → ΔT ∝ î²

Đã kiểm tra số học: P(2A)/P(1A) = **4.000000** (sai số < 1 ULP).

```
T_steady(r,z; I) ≈ T_amb + (I/I_ref)² · ΔT_ref(r,z)
```

---

## 4. Mô hình nhiệt gộp cho cuộn dây (Lumped Thermal Network)

Cuộn dây không được lưới hóa trong thermal_solver.py (chỉ là nguồn gây nóng không khí).
Thay vào đó có mạng RC gộp 2 node trong `build_twin_html_fem.py`:

```
P_inner  →  [C_inner]  −−(hA_inner)−→  [T_air]  −−(hA_far)−→  T_amb
P_outer  →  [C_outer]  −−(hA_outer)−→  [T_air]
```

**Node không khí chung (shared air node):**

```
C_air · dT_air/dt = (hA_inner·(T_inner−T_air) + hA_outer·(T_outer−T_air))
                  − hA_far·(T_air − T_amb)
```

**Phương trình nhiệt mỗi cuộn:**

```
C_i · dT_i/dt = P_i − hA_i·(T_i − T_air)

C_inner = coil_C_scale · ρ_Cu · c_Cu · V_inner    (empirically ~43% of solid Cu)
```

**Tham số đã hiệu chỉnh từ dữ liệu IR thực** (7.8A, steady state):

| Tham số | Giá trị | Nguồn |
|---------|---------|-------|
| hA_inner | 2.2479 W/K | Fit từ T_inner = 79°C tại 7.8A |
| hA_outer | 1.8788 W/K | Fit từ T_outer = 74°C tại 7.8A |
| coil_C_scale | 0.434 | Fit transient (tắt τ ~10% tệ hơn không có scale) |
| hA_far | 40 W/K | Node air → xa |
| C_air | 3000 J/K | Nhiệt dung cụm không khí gần |

*Dự đoán ở 5A (T_amb=20°C): T_inner ≈ 40.5°C, T_outer ≈ 38.5°C.*

---

## 5. Lực nâng (Lift Force) — Kiểm tra EM

Lực Lorentz theo trục z, trung bình chu kỳ (hệ số ½):

```
F_z = −½ · Re[ ∫∫ J_φ · B_r* · 2π r dA ]

     = −½ · Re[ ∫∫ (−jωσ·A_φ) · (−∂A_φ*/∂z) · 2π r dA ]
```

*Kết quả benchmark TEAM28 gốc (20A, 960/576 vòng, r_coil từ PDF gốc):
z_eq ≈ 7.1 mm vs 11.3 mm đo đạc (sai số 37%) — cải thiện từ 70% sau khi sửa bán kính cuộn;
nguyên nhân 37% còn lại chưa giải thích được, PAUSED.*

---

## 6. Kiểm tra chéo và số liệu thực

### Kết quả số tại I = 5A, T_amb = 20°C (sau xác nhận lõi không sắt từ, 2026-07-01)

| Đại lượng | Giá trị | Ghi chú |
|-----------|---------|---------|
| P_plate (eddy Al) | **1.84 W** | Giảm từ 2.61W — lõi không còn tập trung từ thông |
| P_iron (eddy lõi) | **0 W** | Lõi không dẫn điện (ceramic/oxide) |
| P_coil (ohmic Cu) | 72.8 W | Không đổi |
| P_total | 74.66 W | |
| τ (hằng số thời gian tấm) | **13.6 phút** | Tăng từ 10.6 min (UA nhỏ hơn) |
| UA | 0.180 W/K | Giảm từ 0.231 W/K |
| ΔT_max tấm (steady) | ≈ 10.3 K | Giảm từ 11.4 K |
| T_max tấm | ≈ 30.3°C | |
| B_max trong lõi (mu_r=1) | 0.036 T | Rất nhỏ — không tập trung từ thông |
| Cân bằng năng lượng | 0.000% | |

### Dữ liệu IR thực đo (7.8A, steady state, HIKMICRO, 2026-06-23)

| Vị trí | Đo được | Ghi chú |
|--------|---------|---------|
| Inner coil | **79°C** | Đáng tin cậy (varnish đen, ε≈0.91) |
| Outer coil | **74°C** | Đáng tin cậy |
| Lõi trung tâm | 45°C | Không tin cậy (Al sáng, ε thực ≈ 0.1) |
| Separator ring | 40°C | Có thể thấp hơn thực |
| Tấm Al (mặt đáy) | 44/35°C | Không đáng tin (ε sai) |
| Môi trường | 29°C | Phòng thí nghiệm |

---

## 7. Kết nối code ↔ công thức

| File | Chức năng | Công thức |
|------|-----------|-----------|
| `config.py` | Tải params.yaml, chuyển mm→m | Không có FEM |
| `em_solver.py → solve_em()` | Lắp ghép K phức, giải A_φ | §1.2–§1.3 |
| `em_solver.py → compute_losses()` | q = ½σω²|A|², P_coil = ½I²R | §1.4 |
| `em_solver.py → solve_em_saturating()` | Picard iteration + Lorentzian μ_r | §1.5 |
| `thermal_solver.py → solve_steady()` | K nhiệt + biên Robin, giải T | §2.2 |
| `thermal_solver.py → energy_balance()` | Q_in vs Q_out | §2.2 |
| `rom.py → ThermalROM.build()` | Tính ΔT_ref, C, UA, τ | §3.1 |
| `rom.py → T_steady()` | T = T_amb + (I/I_ref)²·s(β)·ΔT_ref | §3.2–§3.3 |
| `rom.py → simulate()` | solve_ivp trên ODE τ·dβ/dt = ... | §3.2 |
| `digital_twin.py` | Loop real-time, Euler: β += (1/τ)·(rhs)·dt | §3.2 |
| `build_twin_html_fem.py` | JS: romStep(), coilAirDrive() | §3, §4 |

---

## 8. Các giả thiết và giới hạn hiện tại

1. **σ(T) chỉ là multiplier vô hướng** — không giải lại FEM theo nhiệt độ.
   Hợp lệ khi ΔT nhỏ và hình dạng trường không thay đổi đáng kể.

2. **Lõi sắt chưa xác nhận** — quan sát lực nâng là gián tiếp; cần thử
   nam châm vĩnh cửu khi tắt điện để xác nhận.

3. **Chiều dày tấm = 3 mm là placeholder** — cần đo thực tế trên tấm Ø16 cm.

4. **Skin depth Al @ 50 Hz ≈ 12 mm >> 3 mm** → dòng xoáy gần như đồng đều
   qua chiều dày → không cần lưới mịn theo z trong tấm.

5. **T_amb = 20°C hằng số** — không dùng dữ liệu cảm biến phòng thí nghiệm
   cho đến khi kết quả không chính xác (lệnh của giáo sư).

6. **Benchmark TEAM28 z_eq ≈ 7.1 mm vs 11.3 mm** (37% sai số) — EM solver
   đúng về dấu và xu hướng, nhưng lực nâng tuyệt đối chưa khớp; đang paused.
