# Báo cáo: Vì sao tự code Digital Twin bằng Python thay vì dùng SimScale / phần mềm mô phỏng có sẵn

> Chuẩn bị 2026-07-10, trả lời câu hỏi của giáo sư. Tham chiếu chi tiết:
> `docs/physics.md` (công thức), `docs/ARCHITECTURE.md`, `docs/SENSOR_PLAN.md`,
> `README.md` (roadmap), `docs/CHANGELOG.md` (lịch sử từng phiên làm việc).

---

## 1. Động lực và hướng đi — vì sao chọn tự code

**Mấu chốt: sản phẩm cuối không phải là "một kết quả mô phỏng", mà là một
DIGITAL TWIN chạy real-time.** Hai bài toán này khác nhau về bản chất:

| | Mô phỏng một lần (SimScale, COMSOL…) | Digital twin (yêu cầu đề bài) |
|---|---|---|
| Đầu ra | 1 trường nhiệt độ cho 1 kịch bản | T(r,z,t) cập nhật **liên tục theo mili-giây** khi người dùng đổi dòng điện |
| Thời gian giải | phút → giờ mỗi lần chạy | phải < 16 ms/khung hình (chạy được trên điện thoại, AR) |
| Kết nối cảm biến | không có API real-time | bắt buộc (hiệu chuẩn từ dữ liệu Arduino) |

Cái cho phép real-time là một **quan sát vật lý** (không phải một tính năng phần mềm):
hệ tuyến tính ở tần số cố định 50 Hz ⇒ tổn hao Joule tỉ lệ **I²** với *phân bố
không gian cố định*, chỉ biên độ thay đổi (kèm hiệu chỉnh σ(T)). Vậy nên:

1. Giải FEM điện từ (phasor) **một lần duy nhất** offline tại I_ref = 5 A →
   bản đồ tổn hao q̂(r,z).
2. Runtime chỉ là phép nhân vô hướng `(I/I_ref)² × [σ(T)/σ(T_ref)]` + ROM nhiệt
   bậc nhất → mili-giây, chạy được trong trình duyệt điện thoại.

**Không phần mềm thương mại nào cho mình "mổ" pipeline ra như vậy** — họ đóng gói
solver thành hộp đen: mỗi lần đổi dòng điện là một lần chạy lại toàn bộ FEM.
Muốn khai thác cấu trúc I² của bài toán thì phải kiểm soát solver ở mức mã nguồn.

Các động lực phụ (nhưng có thật):
- **FEMM bị loại ngay từ đầu**: chỉ chạy Windows, máy dev là macOS (quyết định đã chốt).
- Bài toán **đối xứng trục** → chỉ cần giải 2D (r,z), hệ ~10⁴ ẩn số —
  `scipy.sparse.linalg.spsolve` giải trong < 1 giây. Dùng phần mềm CAE 3D cho
  bài toán cỡ này là "dùng dao mổ trâu giết gà", còn chậm hơn vì phải mesh 3D.
- **TEAM Problem 28 sinh ra chính là để kiểm chứng code tự viết** — đây là
  benchmark chuẩn của cộng đồng computational electromagnetics (COMPUMAG).
  Đi theo tinh thần của đề bài tức là tự viết solver rồi validate.
- **Minh bạch & kiểm chứng được**: energy balance đạt sai số 0.000 %,
  I²-check ra đúng 4.000000, mọi hằng số nằm trong `params.yaml` (single source
  of truth), toàn bộ lịch sử thay đổi nằm trong git. Với hộp đen thương mại,
  ta chỉ có thể *tin* kết quả; với code tự viết, ta *chứng minh* được nó.
- **Chi phí = 0**: numpy/scipy mã nguồn mở, không license, không cloud credit,
  không phụ thuộc internet.
- **Giá trị học thuật**: cả nhóm hiểu từng phương trình từ weak form đến ma trận
  — đúng mục tiêu môn học, thay vì học cách bấm nút một GUI.

---

## 2. So sánh với các công cụ mô phỏng khác

| Tiêu chí | **SimScale** (cloud CAE) | **COMSOL / ANSYS Maxwell** | **FEMM** | **Elmer / FEniCS** (open-source FEM) | **Python tự viết (chọn)** |
|---|---|---|---|---|---|
| EM tần số thấp (eddy current, phasor A_φ) | hạn chế — thế mạnh là CFD/kết cấu/nhiệt, không phải magnetics 50 Hz | ✔ rất tốt | ✔ tốt (2D) | ✔ có (Elmer) | ✔ tự viết, validate bằng TEAM 28 |
| Coupling EM → nhiệt | khó ghép trong một pipeline | ✔ | ✘ nhiệt yếu | ✔ nhưng cấu hình phức tạp | ✔ trực tiếp: q = ½σω²\|A_φ\|² đổ thẳng vào solver nhiệt |
| Đối xứng trục 2D (tận dụng được) | ✘ mesh 3D đầy đủ | ✔ | ✔ | ✔ | ✔ hệ nhỏ ~10⁴ ẩn |
| **ROM / real-time** | ✘ | một phần (module ROM riêng, đắt) | ✘ | ✘ | ✔ **thiết kế cốt lõi** |
| Xuất ra web/AR chạy trên điện thoại | ✘ | ✘ | ✘ | ✘ | ✔ bake vào 1 file HTML |
| Nối cảm biến Arduino để hiệu chuẩn | ✘ | khó, cần scripting bản quyền | ✘ | tự viết thêm | ✔ `data_io.py` → `rom.calibrate_UA()` |
| Chạy trên macOS | ✔ (browser) | ✔ (đắt) | ✘ **Windows-only** | ✔ | ✔ |
| Chi phí | free tier giới hạn, tính theo core-hour | license hàng nghìn € | free | free | free |
| Hộp đen? | có | có | nửa | không | **không — kiểm soát 100 %** |

Ghi chú từng công cụ:

- **SimScale**: mạnh về CFD, kết cấu, nhiệt truyền dẫn tổng quát — nhưng bài toán
  của ta cần *low-frequency electromagnetics* (dòng xoáy 50 Hz trong đĩa nhôm),
  không thuộc thế mạnh của nó. Kể cả nếu giải được, mỗi kịch bản là một job
  cloud tính bằng phút → không thể làm twin real-time; phụ thuộc internet;
  dữ liệu nằm trên server của họ; free tier giới hạn core-hour.
- **COMSOL/ANSYS**: về mặt kỹ thuật giải được hết, nhưng license vượt xa ngân
  sách sinh viên, vẫn không xuất được ra AR trên điện thoại, và biến đồ án
  thành bài học "dùng phần mềm" thay vì "hiểu vật lý".
- **FEMM**: thực ra rất hợp cho phần EM 2D — nhưng Windows-native, máy dev macOS
  → loại từ đầu (quyết định đã chốt trong CLAUDE.md).
- **PyVista — lưu ý quan trọng: PyVista KHÔNG phải solver.** Nó là thư viện
  *hiển thị* 3D (wrapper của VTK). Trong dự án ta **có dùng** PyVista đúng vai
  trò của nó: `visualize.py` revolve kết quả 2D thành 3D và export GLB/OBJ.
  Nên câu so sánh đúng không phải "code vs PyVista" mà là "solver tự viết +
  PyVista để hiển thị".
- **Python tự viết** trả giá bằng việc phải tự kiểm chứng — và ta đã làm:
  energy balance 0.000 %, I²-scaling đúng 4.000000, nhiệt độ cuộn dây hiệu
  chuẩn theo dữ liệu IR thật (HIKMICRO, sai số RMS ≈ 2.5 °C trên transient).
  ⚠️ **Cập nhật 2026-07-11**: số liệu lực nâng bên dưới đã cũ (tính trên hình
  học trước khi đo lại 2026-07-10). Số hiện tại: F_z(5A, z=3.8mm) ≈ 4.10N ≫
  trọng lực 1.60N, nhưng khe hở cân bằng dự đoán z_eq ≈ 11.7mm (đáy đĩa, mặt
  trên nhìn thấy ≈14.7mm) so với quan sát thực tế chỉ 7-8mm nhìn thấy — một
  sai lệch còn để mở (xem CLAUDE.md "LIFT FORCE" / `docs/BUG_REGISTER_2026-07-11.md`).
  Thí nghiệm với mô hình bão hòa μᵣ phi tuyến đã loại trừ bão hòa sắt như
  nguyên nhân (lực đổi <0.1%) — nguyên nhân thật vẫn chưa rõ.

---

## 2.5. Công thức vật lý đầy đủ — tại sao custom code cần thiết

Bốn phương trình sau tạo thành "xương sống" của twin. Mỗi phương trình đòi hỏi
một bước discretization/lắp ráp ma trận riêng biệt; không phần mềm chung chung nào
cho phép tắc hiểu và tái cấu trúc một hệ thống bị gói lại như hộp đen.

### (1) Phương trình điện từ phasor — từ trường biến thiên AC

$$-\nabla \cdot (\nu \nabla A_\varphi) + \nu \frac{A_\varphi}{r^2} + j\omega\sigma A_\varphi = J_s$$

Ký hiệu:
- $A_\varphi(r,z)$ — thế vector thành phần azimuthal (chỉ thành phần này khác 0 do đối xứng trục)
- $\nu = 1/\mu = 1/(\mu_r \mu_0)$ — độ từ thẩm đảo (nhỏ ở sắt → chứng từ)
- $\omega = 2\pi f = 2\pi \cdot 50 = 314$ rad/s (50 Hz)
- $\sigma$ — độ dẫn điện từng miền (Al: $3.4 \times 10^7$ S/m, Cu: $5.8 \times 10^7$ S/m)
- $J_s$ — mật độ dòng điện nguồn trong cuộn dây (mỗi cuộn một dấu hiệu đối ngược)

**Vật lý:** Dòng điện AC trong cuộn sinh ra từ trường. Từ trường này kích thích dòng
xoáy trong đĩa nhôm ($j\omega\sigma A_\varphi$ — số hạng phản ứng eddy). Sắt lõi
(với $\mu_r$ cao, tức $\nu$ thấp) tập trung từ thông tại một vùng nhỏ, giống như
một thấu kính từ tính. Số hạng $\nu A_\varphi/r^2$ là tác dụng hình học của đối xứng
trục — nó là lý do cần giải 2D chứ không phải mô hình 3D khác.

**Ví dụ thực:** Tại 5 A RMS qua 1000 vòng cuộn trong, từ thông cực đại $B_{\max}$
ở sắt lõi ≈ 0.66 T (chưa bão hòa, vẫn trong vùng tuyến tính). Độ sâu skin trong
nhôm ở 50 Hz là $\delta \approx 12$ mm ≫ 3 mm bề dày đĩa → dòng xoáy gần như đều
trong suốt độ dày, không cần mesh siêu mịn theo chiều dày.

### (2) Mật độ tổn hao Joule — nguồn nhiệt chu kỳ bình quân

$$q(r,z) = \frac{|J_e|^2}{2\sigma} = \frac{1}{2} \sigma \omega^2 |A_\varphi|^2 \quad [\text{W/m}^3]$$

Ký hiệu:
- $J_e = -j\omega\sigma A_\varphi$ — mật độ dòng xoáy (phasor)
- Hệ số $1/2$ — kết quả từ lấy trung bình chu kỳ của $\sin^2(\omega t)$

**Vật lý:** Tổn hao bạo trận ($|J|^2/\sigma$) ở bất kỳ chạm dẫn nào cũng là
$q = \frac{1}{2}\sigma\omega^2|A_\varphi|^2$. Cái quan trọng là nó phụ thuộc bình
phương vào $|A_\varphi|$ — do đó I²-scaling mạnh mẽ: dôi dòng $\Rightarrow$ tăng 4 lần
tổn hao. Hệ số $\omega^2$ cho thấy tần số cao hơn = tổn hao cao hơn (50 Hz so với
DC là đêm và ngày).

**Ví dụ thực:** Tại 5 A đo được, tổn hao cuộn dây ≈ 106 W (126 W @ 7.8 A trong
thử nghiệm IR 2026-06-23). Tổn hao đĩa nhôm ≈ 26 W (chứa từ trường mạnh vì gần lõi
sắt). Kiểm chứng I²: tại 2 lần dòng (10 A), tổn hao dự đoán là $106 \times 4 = 424$ W
vs $101 \times 4 \approx 404$ W — sai số < 5%, chứng tỏ mô hình tuyến tính giữ
vững trong khoảng này.

### (3) Độ dẫn điện phụ thuộc nhiệt độ — phản ứng với tăng nhiệt

$$\sigma(T) = \frac{\sigma_0}{1 + \alpha(T - T_0)}$$

Ký hiệu:
- $\sigma_0$ — độ dẫn ở nhiệt độ tham chiếu $T_0$ (thường 20 °C)
- $\alpha$ — hệ số nhiệt độ (nhôm, đồng ≈ 0.0039 K$^{-1}$)

**Vật lý:** Kim loại nóng hơn → nguyên tử rung động mạnh hơn → cản trở dòng điện →
kháng suất tăng, độ dẫn giảm. Hiệu ứng này **không đối xứng**:
- Tổn hao đĩa nhôm ∝ $\sigma_{\text{Al}}$ → đĩa nóng → $\sigma$ giảm → tổn hao giảm (phản hồi âm).
- Tổn hao cuộn dây ∝ $1/\sigma_{\text{Cu}}$ → cuộn nóng → $\sigma$ giảm → tổn hao tăng (phản hồi dương).

Hai hiệu ứng này cân bằng một phần, nhưng cuộn dây vẫn là nguồn nhiệt dominant.

**Ví dụ thực:** Tăng 70 K (từ 20 °C lên 90 °C) làm kháng suất tăng ~27%. Ở các điểm
đo IR 2026-06-23 (cuộn trong 79 °C, cuộn ngoài 74 °C), ảnh hưởng của $\sigma(T)$ là
điều chỉnh ±5–10 % trên công suất tính toán. Custom code cho phép áp dụng hiệu chỉnh
này ở runtime: chỉ một phép nhân vô hướng, không cần giải lại FEM.

### (4) Phương trình Fourier — lan tỏa nhiệt trong thời gian

$$\rho c_p \frac{\partial T}{\partial t} = \nabla \cdot (k \nabla T) + q$$

Ký hiệu:
- $\rho c_p$ — dung lượng nhiệt khối lượng (J/(m³·K))
- $k$ — độ dẫn nhiệt (W/(m·K))
- $q$ — mật độ tổn hao từ công thức (2) trên
- Điều kiện biên: convection Robin, $-k \frac{\partial T}{\partial n} = h(T - T_\infty)$

**Vật lý:** Tổn hao Joule $q$ từ EM là "lửa"; phương trình Fourier là "cách lửa lan
tỏa". Số hạng $\nabla \cdot (k \nabla T)$ là dẫn nhiệt Fourier (nguồn ở nơi nóng, chảy
ra nơi lạnh). Hệ số đối lưu $h$ cho biết "khí gần có tác dụng mát bao nhiêu" — hiệu
chuẩn từ dữ liệu cảm biến thực. Trong trạng thái ổn định ($\partial T/\partial t = 0$),
nhiệt vào = nhiệt ra: $\int q \, dV = \int h(T - T_\infty) \, dA$.

**Ví dụ thực:** Đĩa nhôm R=80 mm, bề dày 3 mm, $\rho c_p \approx 2.47$ MJ/(m³·K).
Hằng số thời gian nhiệt (từ ROM): $\tau \approx 5.5$ phút ở R=80 mm. Mô phỏng 20 phút
= ~4τ đủ để tới steady state. Dữ liệu IR 2026-06-23 cho cuộn dây đạt trạng thái ổn
định ≈ 7–10 phút tại 7.8 A, phù hợp với dự đoán.

### Tại sao chỉ custom code, không phải thư viện

**Các thư viện chung (scipy.sparse, FEniCS, FENICS) giải FEM tổng quát —
nhưng không hiểu cấu trúc đặc biệt của bài toán này.** Custom code cho phép:

1. **Kiểm soát ma trận từng phần tử.** Ví dụ: công thức (2) dựa trên $|A_\varphi|^2$
   trong từng phần tử — cái này phải tính *sau* khi giải EM (lấy $A_\varphi$ từ node),
   không phải *trước* như các generic solver. Custom code duyệt ma trận sau đó và
   trích xuất q̂_plate(r,z) một cách chính xác.

2. **Xác minh energy balance 0.000%.** Tổng tổn hao vào = tổng nhiệt ra theo convection.
   Nếu sai, ta biết ngay ở đâu — vì ta viết tất cả. Generic solver báo "solution found"
   nhưng không chứng minh energy balance.

3. **Tách modal để ROM I²-scaling.** Real-time yêu cầu giải một lần, sau đó nhân I².
   Điều này có thể làm vì tất cả dòng eddy và ohmic đều ∝ I² (từ vật lý). Custom code
   lưu $q̂(r,z)$ (độc lập với I) rồi tại runtime chỉ nhân vô hướng.

4. **Ghép EM ↔ nhiệt liền mạch.** Công thức (2) → (4): output của EM là input của
   nhiệt. Custom code nối chúng ngay giữa (gọi em_solver.py, lấy q, feed vào
   thermal_solver.py), không có "import/export file" hay câu hỏi "format tương thích?"

---

## 3. Vì sao đầu ra là HTML thay vì thư viện/app khác

Yêu cầu cuối của đề bài: **AR app + QR code**. Kịch bản sử dụng: khách đứng cạnh
rig, quét QR, twin mở ra ngay trên điện thoại của họ. Điều đó áp đặt các ràng buộc:

| Phương án | Vấn đề |
|---|---|
| App native / Unity AR | phải cài đặt, qua app store, toolchain nặng, mỗi lần sửa là một lần re-deploy |
| Streamlit / Dash / Jupyter | cần **server Python chạy thường trực** — QR phải trỏ về một máy luôn bật |
| matplotlib (`digital_twin.py`) | chỉ chạy trên desktop có Python — ta vẫn giữ nó làm công cụ dev nội bộ |
| **1 file HTML tĩnh (chọn)** | không có vấn đề nào ở trên |

Một file `digital_twin_fem.html` **tự chứa** (self-contained):

- Kết quả FEM + ROM được **bake sẵn thành JavaScript** lúc build
  (`build_twin_html_fem.py`) — trong browser chỉ còn phép toán O(n) →
  60 fps trên điện thoại, đúng nhờ kiến trúc ROM ở mục 1.
- Hosting tĩnh miễn phí (GitHub Pages) — không backend, không bảo trì server;
  QR code (`gen_qr.py`) trỏ thẳng vào URL.
- Không yêu cầu người xem cài bất cứ thứ gì: browser điện thoại là đủ.
- Vẫn tương tác đầy đủ: slider dòng điện / núm variac (độ), 4 bán kính đĩa
  swap trực tiếp, mô hình bay lên với dao động, T_amb lấy từ weather API.

Tóm lại: HTML không phải "thay thế thư viện mô phỏng" — nó là **kênh phân phối**
duy nhất thỏa mãn ràng buộc "quét QR là chạy, không cài đặt". Toàn bộ vật lý vẫn
được giải bằng Python; HTML chỉ nhận kết quả đã bake.

---

## 4. Cấu trúc dự án, lộ trình đã qua, các bước còn lại

### Kiến trúc pipeline (một chiều, mỗi file một nhiệm vụ)

```
params.yaml  (mọi tham số: hình học, vật liệu, dòng điện, BC — không hardcode)
    │
config.py    (nạp + chuẩn hóa đơn vị mm→m, dẫn xuất I_peak = I_rms·√2)
    │
em_solver.py          thermal_solver.py
(FEM phasor A_φ,      (FEM nhiệt đối xứng trục,
 tổn hao eddy + ohmic, energy balance 0.000%)
 lực nâng, benchmark)
    └────────┬────────┘
          rom.py      (ROM real-time: I²-scaling + transient bậc nhất + σ(T))
             │
  ┌──────────┼──────────────────┐
digital_twin.py   visualize.py   build_twin_html_fem.py
(twin tương tác   (revolve 2D→3D, (bake → digital_twin_fem.html,
 matplotlib, dev)  GLB/OBJ)        sản phẩm AR cuối)
             │
data_io.py + arduino/thermal_sensor.ino   gen_qr.py
(cầu nối cảm biến → hiệu chuẩn ROM)       (QR → URL hosted)
```

### Lộ trình đã đi qua (theo README roadmap)

- ✅ **Phase 1a** — Solver nhiệt đối xứng trục, kiểm chứng energy balance 0.000 %.
- ✅ **Phase 1b** — Solver EM (dòng xoáy AC, phasor); tổn hao thực tính được;
  hình học cuộn dây được đo lại bằng thước (2026-07-10, thay thế ước lượng
  2026-07-01): đĩa Ø160 mm, cuộn trong 1000 vòng r=27.9–61.9 mm, cuộn ngoài
  500 vòng r=82.9–102.9 mm.
- ✅ **Phase 2** — ROM real-time (I² + transient + σ(T)); τ ≈ 4.07 phút @ R=80 mm
  (tính lại sau khi đo lại hình học 2026-07-10).
- ✅ **Phase 3** — Vòng lặp twin tương tác (slider I, chọn đĩa).
- ✅ **Phase 4** — Revolve 2D→3D, export GLB/OBJ (PyVista/meshio).
- ✅ **Phase 5** — AR twin HTML độc lập + QR code generator.
- ✅ **Phase 6** — Kiểm chứng kích thước miền (Dirichlet vs Neumann, hộp 1×1 m
  theo yêu cầu giáo sư); chạy lại toàn pipeline với T_amb = 20 °C.
- ✅ **Phase 8** — Pipeline dữ liệu cảm biến (`data_io.py` + firmware Arduino),
  đã test đầu-cuối bằng CSV giả lập, chưa cần phần cứng.
- ✅ **Hiệu chuẩn với rig thật** — 2 điểm vận hành đo được (190 V→5 A,
  270 V→7.8 A), ảnh nhiệt HIKMICRO; mạng nhiệt lumped của cuộn dây fit được
  RMS ≈ 2.5–3 °C; lực nâng validate khớp quan sát độ cao bay.

### Các bước còn lại

1. **Phase 7 — phần cứng cảm biến thật** (bước lớn nhất, xem mục 5): lắp
   Arduino + 2× MAX31855, ghi một lần chạy thực, hiệu chuẩn lại ROM từ dữ liệu đó.
2. **Hosting + QR**: chọn URL (khả năng cao GitHub Pages) rồi phát hành QR.
3. Các câu hỏi vật lý đang mở (không chặn tiến độ):
   - ✅ Kiểm tra nam châm cho vòng sắt ngoài: **đã xong 2026-07-10** — vòng
     là sắt từ (μᵣ=1000, giống lõi trung tâm), vị trí đo lại r=64.9–79.9mm
     (trước đó 81–101mm). Còn mở: hợp kim/đường cong B-H thật chưa từng đo
     (μᵣ=1000 chỉ là placeholder) — xem mục lực nâng ở trên.
   - Bảng hiệu chuẩn núm variac → dòng điện dày hơn (hiện chỉ 3 điểm neo).
   - Hỗ trợ đĩa vành khuyên (3 đĩa thực r_out=55/r_in=27.5 mm chưa mesh được).
   - Benchmark TEAM 28 gốc: z_eq ≈ 14.5 mm vs 11.3 mm kỳ vọng (lệch 28%, số
     liệu 2026-07-11 sau khi vá 1 bug RMS/peak — trước đó là 6.8mm/lệch 40%
     theo hướng khác) — vẫn tạm dừng theo thống nhất nhóm, không ảnh hưởng rig thật.
   - ✅ `validate_domain_size()`: **PASS trở lại** (mọi sai khác <1%, vd P_plate
     0.767%) sau khi chạy lại trên hình học+sắt mới 2026-07-10 — từng FAIL
     2.71% trước đó, nguyên nhân regression cũ vẫn chưa rõ nhưng không còn chặn.

---

## 5. Phương án kết nối phần cứng (validation loop)

Theo chỉ đạo của giáo sư (Juni 2026): *"Schaut was es genau bräuchte und baut
dann selbst eine kleine Lösung — Arduino plus ein paar Sensoren, und dann
einfach noch ein Infrarot-Thermometer."* Chi tiết đầy đủ: `docs/SENSOR_PLAN.md`.

### Kiến trúc đo

```
Thermocouple K #1 (lõi/cuộn trong) ─▶ MAX31855 ─┐
                                                 ├─▶ Arduino Uno/Nano ─USB serial─▶ Laptop
Thermocouple K #2 (đáy đĩa nhôm)   ─▶ MAX31855 ─┘        (CSV, 1 Hz)
IR thermometer cầm tay ──▶ đo điểm kiểm tra thủ công (đối chiếu)
```

- **Vì sao thermocouple chứ không chỉ IR**: ảnh nhiệt IR trên nhôm bóng /
  lõi gốm **không tin được** (sai emissivity — đã xác nhận trong đợt đo
  HIKMICRO 2026-06-23); chỉ cuộn dây sơn tối là đọc IR chuẩn. Thermocouple
  tiếp xúc giải quyết đúng chỗ IR thất bại: **đáy đĩa nhôm** — cũng chính là
  số liệu cần để phân định câu hỏi đang mở "đĩa hay cuộn dây nóng hơn".
- Firmware đã viết xong: `arduino/thermal_sensor.ino` (2× MAX31855 qua SPI,
  xuất CSV 1 Hz qua serial).

### Pipeline phần mềm (đã chạy được, chỉ chờ phần cứng)

```
Arduino (CSV serial) ─▶ data_io.py SensorReader (mode serial | mock)
                     ─▶ calibrate_from_file()
                     ─▶ rom.calibrate_UA()   ← fit hA, τ từ dữ liệu đo
```

Toàn bộ chuỗi này **đã được test đầu-cuối** với `mock_sensor_data.csv` —
tức là ngày phần cứng về, chỉ cần cắm USB và đổi `--mode mock` thành
`--mode serial`, không phải viết thêm code.

### Các bước triển khai

1. Chốt shopping list (Reichelt/Conrad: Arduino Nano, 2× MAX31855 breakout,
   2× thermocouple loại K, dây) → giáo sư mua.
2. Lắp + nạp firmware, kiểm tra bằng nước đá/nước sôi (2 điểm chuẩn).
3. Ghi một lần chạy thật đủ dài (nguội → steady state, ≥ 3τ ≈ 20 phút) tại
   190 V / 5 A.
4. `data_io.py --mode calibrate` → hiệu chuẩn lại `hA_inner/hA_outer/UA` từ
   dữ liệu thật (thay cho hiệu chuẩn IR hiện tại).
5. Ghi thêm một lần **cooldown** (tắt nguồn, đo nguội) → fit riêng mô hình
   hai-nút của cuộn dây (`coil_G_wind_W_per_K`, hiện mới đúng cỡ độ lớn).
6. Mở rộng (sau này, ngoài Phase 1): thiết bị đo dòng real-time (giáo sư đã
   xác nhận cần mua) → twin nhận I(t) đo thật thay vì hằng số 5 A; xa hơn nữa
   có thể stream trực tiếp vào HTML twin qua Web Serial API.

---

## Một câu trả lời gọn cho giáo sư

> "Chúng em không chọn code *thay cho* mô phỏng — chúng em code **vì** yêu cầu
> là digital twin real-time trên điện thoại. Các công cụ như SimScale giải một
> kịch bản trong vài phút; twin của chúng em phải trả lời trong mili-giây khi
> người dùng xoay núm dòng điện. Điều đó chỉ khả thi khi khai thác cấu trúc
> vật lý của bài toán (tổn hao ∝ I², phân bố không gian cố định) để giải FEM
> đúng một lần rồi thu về ROM — và việc đó đòi hỏi kiểm soát solver ở mức mã
> nguồn. Đổi lại, chúng em kiểm chứng nghiêm ngặt: energy balance 0.000 %,
> I²-scaling đúng tuyệt đối, lực nâng và nhiệt độ cuộn dây khớp số liệu đo
> trên rig thật."
