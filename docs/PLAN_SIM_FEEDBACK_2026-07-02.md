# KẾ HOẠCH — Nâng cấp mô phỏng 3D theo feedback thực tế (2026-07-02)

Chia thành **4 work package (WP-A..D)** cho 3–4 agent Sonnet chạy song song.
Mỗi WP tự chứa: nguyên nhân gốc, thiết kế vật lý, vị trí code, các bước, và
tiêu chí nghiệm thu. Đọc CLAUDE.md trước khi bắt đầu.

> **QUAN TRỌNG — chống conflict:** cả 4 WP đều đụng `build_twin_html_fem.py`
> nhưng ở các VÙNG KHÁC NHAU (xem "Bản đồ conflict" cuối file). Mỗi agent làm
> trong **git worktree riêng**, merge theo thứ tự: **WP-C → WP-B → WP-A → WP-D**.
> WP-D là người tích hợp + kiểm thử cuối.

---

## Bối cảnh — 3 feedback từ quan sát rig thật

1. **Dao động levitation sai**: (a) tăng time-speed slider thì dao động KHÔNG
   nhanh theo; (b) thực tế đĩa rung lạch cạch từ ~0.1A, rung mạnh dần theo
   1→3A rồi mới nâng lên — mô phỏng hiện tại đứng im tuyệt đối dưới 4.54A;
   (c) sau khi ổn định ở 5A, tăng lên 7.75–8A thì gap chỉ nhích nhẹ và dao
   động NHỎ hơn nhiều so với lúc cất cánh — mô phỏng hiện tại dao động mạnh
   y như nhau mọi lúc.
2. **Cuộn dây nguội quá nhanh**: dây vừa nóng cần RẤT lâu để nguội trong không
   khí; model RC bậc-1 hiện tại cho τ nguội = τ nóng (~350s) — phi thực tế.
3. **Bán kính đĩa**: hiện tại R=80mm (Ø160mm). Muốn thêm đĩa lớn hơn che kín
   tới mép ngoài separator ring (r=101mm) → đĩa **R=101mm (Ø202mm)**.

---

## WP-A — Vật lý dao động levitation (agent 1)

> **STATUS: DONE (2026-07-02).** Xem CLAUDE.md Code status → mục "WP-A" cho đầy
> đủ kết quả. Tóm tắt: `levStep` chuyển sang nghiệm giải tích + sim-time (speed
> slider giờ hoạt động đúng), jitter dưới ngưỡng nâng đã có, ζ(I) đã theo I².
> **2 câu hỏi mở chưa trả lời được** (xem mục "Câu hỏi cần user trả lời" cuối
> file) — không chặn, code đã có chỗ điền sẵn.

### Nguyên nhân gốc (đã xác minh trong code)
- `build_twin_html_fem.py` dòng ~1150–1170: dao động là **lò xo–khối lượng
  tuyến tính hoá quanh z_eq**: `m·z̈ = mω²(z_eq−z) − 2ζω·m·ż` với
  `LEV_OMEGA = √(g/z0) ≈ 21.4 rad/s`, `LEV_ZETA = 0.02` (hằng số).
- Dòng ~1998: `levStep(I_display, wall_dt)` — tích phân theo **wall-time**
  (comment ghi rõ là cố ý). Đây là lý do speed slider không ảnh hưởng.
- Dòng ~1163: khi `I < I_LEV_MIN (4.54A)` thì `lev.z=0, lev.v=0` cứng → không
  có rung dưới ngưỡng nâng.

### Thiết kế vật lý mới
1. **Tích phân theo sim-time**: gọi `levStep(I_display, dt_sim)` thay vì
   `wall_dt`. Vì ở speed 200× thì `dt_sim ≈ 3.3s/frame` mà ω=21 rad/s, KHÔNG
   dùng Euler substep (sẽ cần ~700 substep/frame) — thay bằng **nghiệm giải
   tích** của dao động tắt dần dưới-tới-hạn mỗi frame (exact, ổn định vô điều
   kiện):
   ```
   z(t+dt) = z_eq + e^(−ζωdt)·[ (z−z_eq)·cos(ω_d dt) + ((v+ζω(z−z_eq))/ω_d)·sin(ω_d dt) ]
   ω_d = ω√(1−ζ²)
   ```
   (cập nhật v tương ứng bằng đạo hàm của biểu thức trên). Giữ floor-contact
   clamp `z ≥ 0`.
2. **Rung dưới ngưỡng nâng (0.1A → I_min)**: lực AC tức thời
   `F(t) ∝ i(t)² = I²·(1−cos(2ωt))/2` → thành phần đập **100 Hz**. Đĩa nằm
   trên coil bị "rúc lăng bần bật". 100Hz không render nổi ở 60fps → mô phỏng
   bằng **jitter biên độ vật lý**: khi `lev.z < 0.5mm` và `I > 0.05A`, cộng
   displacement hiển thị `A_jit·sin(φ₁)+0.5·A_jit·sin(φ₂)` với 2 pha chạy
   nhanh không đồng bộ (aliased shimmer), biên độ:
   ```
   A_jit(I) = JIT_MM · (I / I_ref)²     (JIT_MM ≈ 0.3 display-mm, clamp ≤ 1mm)
   ```
   → 0.1A rung li ti, 3A rung rõ, biến mất mượt khi đĩa nâng lên (fade theo
   `max(0, 1 − lev.z/0.5)`).
3. **Damping tăng theo dòng** (eddy-current damping ∝ B² ∝ I²):
   ```
   ζ(I) = ζ0 + ζ1·(I/5)²    với ζ(5A) ≈ 0.02 (giữ settle ~9s lúc cất cánh),
                             ζ(7.75A) ≈ 0.05–0.08
   ```
   → bước dòng 5→7.75A dao động nhỏ + tắt nhanh hơn hẳn lúc lift-off, đúng
   quan sát.
4. **CALIBRATION MỞ — hỏi user**: model hiện tại `z_eq(I)=4.1+2·z0·ln(I/5)`
   với `z0=21.4mm` cho gap@7.75A ≈ 22.9mm (nâng RẤT nhiều), nhưng user quan
   sát gap chỉ "nâng lên một tý". Nhiều khả năng `Z_DECAY_MM` quá lớn. Việc
   của agent: viết công thức refit `z0 = (z_obs − 4.1)/(2·ln(7.75/5))` và ĐỂ
   SẴN chỗ điền `z_obs` (gap thật ở 7.75A, user ước lượng bằng mm hoặc "x lần
   bề dày đĩa"). Ghi chú: ω = √(g/(z0·1e-3)) đổi theo → cập nhật cùng nhau.
5. **(Tuỳ chọn, làm cuối)**: xoay tròn trang trí — thêm `lev.spin` (rad/s) tắt
   dần chậm (τ~60s), kích hoạt bằng nút "Poke disc" nhỏ trong panel; đĩa quay
   quanh trục Y khi spin ≠ 0. Chỉ làm nếu còn thời gian.

### Vùng code
JS: khối "Levitation gap physics" (~dòng 1129–1170), lời gọi trong render loop
(~dòng 1995–2000), telemetry gap (~dòng 2020–2022). KHÔNG đụng `romStep`,
KHÔNG đụng geometry Python.

### Nghiệm thu (headless Playwright, pattern có sẵn trong các session trước)
- 0 lỗi JS console.
- Speed 1× vs 10×: thời gian settle (wall) của dao động sau bước dòng phải
  ngắn hơn ~10× ở speed 10×.
- I=0.5A: đĩa jitter thấy được (đo bằng `twinDebug` / position sampling),
  I=0: đứng im tuyệt đối.
- Bước 5→7.75A sau khi settle: overshoot đỉnh < 40% overshoot của bước 0→5A
  (chuẩn hoá theo biên độ bước).
- `lev.z` settle vẫn đúng `levGapEqMm(I)` ±0.05mm.

---

## WP-B — Làm nguội cuộn dây thực tế hơn (agent 2)

> **STATUS: DONE (2026-07-02).** Xem CLAUDE.md Code status → mục "WP-B". Tóm
> tắt: đối lưu phi tuyến (h~ΔT^0.25) + coil 2-node (surface/winding-core,
> `coil_G_wind_W_per_K=1.0`) đã implement + fit lại từ đầu. RMS ramp-test=2.5°C
> (tốt hơn cả claim cũ), cooldown chậm hơn ~6-8× so với model cũ. Steady-state
> không đổi (verify được). **Phát hiện phụ**: model cũ (trước WP-B) thực ra có
> RMS=6.6°C trên `thermal_ramp_test`, không phải ~3°C như tài liệu cũ ghi — claim
> đó đã cũ, có lẽ lệch sau khi thêm iron contact-conduction mà không re-check.
> Chưa có dữ liệu NGUỘI thật để fit định lượng — xem câu hỏi cuối file.

### Nguyên nhân gốc
`romStep()` (~dòng 996–1035): mỗi coil là 1 node RC tuyến tính
`dT/dt = (P − hA·(T−T_air))/C` → nguội đối xứng với nóng, τ ≈ C/hA ≈ 350s.
Thực tế: (a) đối lưu tự nhiên yếu dần khi ΔT nhỏ (h ∝ ΔT^0.25) → đuôi nguội
rất dài; (b) fit hiện tại `coil_C_scale=0.2241` nghĩa là chỉ 22% khối đồng
"nhìn thấy được" bằng IR — phần lõi cuộn dây (78% khối lượng) trữ nhiệt sâu và
nhả ra chậm khi tắt dòng.

### Thiết kế vật lý mới (làm CẢ HAI, chúng bổ trợ nhau)
1. **Đối lưu phi tuyến** (mỗi node coil + iron):
   ```
   hA_eff(ΔT) = hA_cal · (max(ΔT, 0.1) / ΔT_cal)^0.25
   ```
   `ΔT_cal` = độ tăng nhiệt tại điểm calibrate (T_ss(5A) − T_air ≈ 11.5K
   inner) → steady-state tại 5A KHÔNG đổi, nhưng khi nguội ΔT nhỏ → hA giảm
   → đuôi nguội kéo dài. (Đây là định luật Churchill-Chu đơn giản hoá.)
2. **Coil 2 node** (surface + winding-core):
   - `C_surf = coil_C_scale · C_solid` (= giá trị fit hiện tại, IR nhìn thấy)
   - `C_deep = (1 − coil_C_scale) · C_solid` (phần đồng còn lại, có thật)
   - Liên kết `G_wind` (W/K) giữa 2 node, nguồn P chia vào cả hai theo tỷ lệ C.
   - `G_wind` là tham số fit MỚI: chọn sao cho transient NÓNG (ramp test
     session 2, `thermal_ramp_test` trong params.yaml) vẫn RMS ≤ 3.5°C
     (không tệ hơn fit cũ 3°C nhiều), tức G_wind đủ nhỏ để node deep gần như
     "tàng hình" trong 450s đầu, nhưng khi tắt dòng nó nhả nhiệt ngược ra
     surface → nguội chậm. Bắt đầu thử G_wind ≈ 1–3 W/K rồi fit.
3. **Fit lại**: viết script fit nhỏ (scratch, không commit) chạy lại ramp-test
   residual với model mới; ghi kết quả (hA giữ nguyên hay chỉnh nhẹ, G_wind,
   RMS mới) vào params.yaml comment.
4. **Đồng bộ 2 nơi**: model này sống ở JS (`romStep`) VÀ phải thêm các key mới
   vào `params.yaml` block `lumped_thermal` + phần Python export `LUMPED`
   (~dòng 185–210 của builder). Nếu `rom.py`/`digital_twin.py` dùng chung mạng
   lumped coil thì đồng bộ luôn (kiểm tra bằng grep `hA_inner`).
5. **TODO ghi vào CLAUDE.md**: chưa có dữ liệu NGUỘI thật — lần tới ra lab, log
   một trajectory cooldown bằng IR (tắt dòng từ steady 5A, đọc coil mỗi 60s
   trong 20–30 phút) để fit định lượng. Hiện tại chỉ nghiệm thu định tính.

### Vùng code
JS `romStep` + hằng LUMPED (~dòng 950–1035), Python export block (~185–210),
`params.yaml` (`lumped_thermal`), có thể `rom.py`. KHÔNG đụng khối levitation,
KHÔNG đụng geometry.

### Nghiệm thu
- Steady-state KHÔNG đổi: T_inner_ss(5A) ≈ 40.5°C, T_outer_ss ≈ 38.5°C (±0.3K).
- Heating ramp-test RMS ≤ 3.5°C.
- Cooldown test (JS, speed cao): từ steady 5A → I=0, thời gian để inner coil
  về `T_air + 0.1·ΔT` phải ≥ **3×** so với model cũ; nhiệt độ giảm nhanh lúc
  đầu, chậm dần về sau (kiểm tra dT/dt giảm đơn điệu và đuôi dài).
- 0 lỗi JS, energy sanity: không node nào xuống dưới T_amb.

---

## WP-C — Đĩa lớn Ø202mm + chạy lại EM (agent 3)

> **STATUS: DONE (2026-07-02).** Xem CLAUDE.md Code status → mục "WP-C" cho đầy
> đủ kết quả số + caveat. Tóm tắt: đĩa Ø202mm KHÔNG bay ở 5A_rms (thiếu 40% lực,
> cần I_min_lev≈6.45A) — kết quả khoa học, không phải lỗi. `LEV_ANCHORS` đã được
> tính sẵn trong build_twin_html_fem.py cho WP-D dùng, chưa nối vào JS sống.

### Trả lời câu hỏi
Đĩa hiện tại: **R = 80mm (Ø160mm)**, dày 3mm (`plate_material.radius_mm: 80.0`
trong params.yaml). Separator ring nằm ở r = 81–101mm → đĩa che kín mép ngoài
ring cần **R = 101mm (Ø202mm)**.

### Việc cần làm
1. **Thêm plate mới** vào `plate_library` trong params.yaml:
   `{name: "Al Ø202mm", radius_mm: 101.0, thickness_mm: 3.0, material: aluminium}`.
   KHÔNG đổi mặc định `plate_material.radius_mm` (80mm là đĩa thật đã
   validate) — thêm cách chọn đĩa khi bake, ví dụ CLI:
   `python build_twin_html_fem.py --plate-radius 101` (override radius trước
   khi build ROM/EM, output `outputs/digital_twin_fem_R101.html`).
2. **Chạy lại EM ở R=101mm** (bắt buộc — KHÔNG scale từ kết quả R=80, vì đĩa
   mới phủ lên vùng iron-ring/outer-coil, phân bố eddy khác hẳn):
   - `P_plate` mới, map `q_e` mới.
   - Đường cong lực `F_z(z)` tại I_rms=5A (nhớ **×2 convention**: solver dùng
     I_peak = I_rms·√2, xem CLAUDE.md "CURRENT CONVENTION").
   - Khối lượng mới: `m = 2700·π·0.101²·0.003 ≈ 0.2596 kg` → `mg ≈ 2.55N`
     (đĩa cũ 163g/1.60N).
   - Giải `F_z(z_eq) = mg` → z_eq mới; nếu `F_z_max(5A) < 2.55N` thì đĩa
     KHÔNG bay ở 5A → tính `I_min_lev` mới và BÁO CÁO rõ (đây là kết quả
     khoa học quan trọng, không phải lỗi).
3. **Bake anchor mới vào JS**: `Z_GAP_5A_MM`, `Z_DECAY_MM` (refit từ 2 điểm
   F_z(z) mới), khối lượng — phối hợp với WP-D: các hằng này phải đi qua
   PARAMS JSON chứ không hardcode (xem WP-D). Nếu WP-D chưa merge, tạm ghi
   giá trị vào một dict Python duy nhất `LEV_ANCHORS` để WP-D dùng.
4. **Nhiệt**: ROM build lại tự động với R=101 (P_plate mới) khi override —
   kiểm tra `thermal_solver` energy balance vẫn 0.000%.
5. **Cảnh báo trong báo cáo**: iron ring (r=81–101mm) đang model là AIR
   (μ_r=1, magnet test PENDING). Đĩa Ø202 nằm ngay trên ring → nếu ring hoá ra
   ferromagnetic thì F_z và P_plate đổi lớn (xem μ_r sensitivity trong
   CLAUDE.md). Kết quả R=101 hiện tại chỉ đúng với giả định ring = air.

### Vùng code
`params.yaml` (plate_library), `build_twin_html_fem.py` phần Python (argparse
+ bake, ~dòng 340–600), chạy `em_solver.py` qua API `compute_losses`/lift-force
(không sửa em_solver trừ khi cần expose hàm F_z(z) — nếu sửa, chỉ THÊM hàm).

### Nghiệm thu
- `python config.py` chạy sạch với params mới.
- Báo cáo số: P_plate(R101), F_z_max(5A), z_eq hoặc I_min_lev, so sánh bảng
  với R=80.
- `outputs/digital_twin_fem_R101.html`: 0 lỗi JS, đĩa render Ø202 phủ tới mép
  ngoài separator ring (screenshot xác nhận), file mặc định R=80 KHÔNG đổi
  hành vi.

---

## WP-D — Refactor hằng số + tích hợp + kiểm thử (agent 4, merge cuối)

> **STATUS: DONE (2026-07-02).** Block `levitation:` đã thêm vào params.yaml,
> `coil_hot_display_C` đã thêm vào `lumped_thermal:`. Python `lev_params(cfg)`
> đọc params + `LEV_ANCHORS`/`_lev_anchor()` (deliverable của WP-C) → JS đọc
> `PARAMS.lev.*` thay vì hardcode `Z_GAP_5A_MM`/`Z_DECAY_MM`/`ζ0`/`ζ1`/`JIT_*`;
> `LUMPED.T_coil_hot_display_C` thay `T_COIL_HOT`. **Bug WP-C cờ lại đã được
> sửa**: file R=101 giờ tính riêng anchor của nó thay vì dùng lại của R=80 —
> verify: R=80 gap@5A=4.1000mm (regression giữ nguyên tuyệt đối, chưa đổi 1 bit),
> R=101 gap@5A=0.0000mm + I_LEV_MIN=6.450A (đúng bằng số WP-C đã tính, KHÔNG còn
> gap sai ở R101 nữa). Cả 2 file: 0 lỗi JS console (Playwright headless).

### Lý do
Locked decision của repo: "All tunable parameters live in params.yaml. Never
hardcode constants" — nhưng JS đang hardcode: `Z_GAP_5A_MM=4.1`,
`Z_DECAY_MM=21.4`, khối lượng đĩa (ẩn trong 163g/1.60N), `T_COIL_HOT=80`,
`JIT_MM`/`ζ0`/`ζ1` mới của WP-A, key cooling mới của WP-B.

### Việc cần làm
1. Tạo block `levitation:` và mở rộng `lumped_thermal:` trong params.yaml chứa
   toàn bộ hằng trên (kèm comment nguồn gốc từng số).
2. Python builder đọc → nhét vào PARAMS JSON đã có (`ROM`/`LUMPED` pattern,
   ~dòng 580–600) → JS đọc từ `PARAMS.lev.*` thay literal.
3. **Merge coordinator**: merge theo thứ tự C → B → A, resolve conflict trong
   `build_twin_html_fem.py` (các vùng đã tách nhưng vẫn có thể chạm nhau ở
   PARAMS export + render loop).
4. **Kiểm thử tổng** (headless Playwright, cả file R=80 mặc định lẫn R101):
   toàn bộ checklist nghiệm thu của A, B, C + regression: gap 4.1mm@5A (file
   R=80), coil glow, label không chồng, B-field density theo I (các fix
   2026-07-02 trước đó không được hỏng).
5. Cập nhật CLAUDE.md (Code status + TODO log-cooldown-data + câu hỏi
   calibration z_obs@7.75A cho user) và README nếu cần.

---

## Bản đồ conflict trong build_twin_html_fem.py

> Lịch sử (tham khảo) — cả 4 WP đã DONE, không còn merge nào đang chờ. Trên
> thực tế cả 4 WP chạy tuần tự trong cùng một working tree (không dùng git
> worktree riêng như dự kiến ban đầu) nên không có conflict thật nào xảy ra.

| WP | Python | JS |
|----|--------|-----|
| A  | — | ~1129–1170 (lev physics), ~1995–2022 (loop/telemetry) |
| B  | ~185–210 (LUMPED export), params.yaml | ~950–1035 (romStep) |
| C  | ~340–600 (geometry/bake/argparse), params.yaml, em_solver API | hằng lev anchors |
| D  | ~580–600 (PARAMS export), params.yaml | thay literal → PARAMS.lev |

Điểm nóng: **PARAMS export (~580–600)** — B, C, D đều thêm key vào đây → mỗi
agent chỉ THÊM key mới (không sửa key cũ), D resolve cuối. **params.yaml** —
B thêm vào `lumped_thermal`, C thêm vào `plate_library`, D thêm block
`levitation` → vùng khác nhau, conflict dễ resolve.

## Câu hỏi cần user trả lời (cập nhật 2026-07-02, sau khi cả 4 WP xong)

Không cái nào chặn việc dùng twin hiện tại — đều là "độ chính xác", không phải
lỗi chạy. Xếp theo mức ưu tiên.

1. **[WP-A] Gap thật ở 7.75A ≈ bao nhiêu mm** (hoặc mấy lần bề dày đĩa)? Code
   đã có chỗ điền sẵn: biến `Z_OBS_7_75A_MM` (JS, khối "Levitation gap physics")
   — hiện `null`, điền số vào là `Z_DECAY_MM` tự refit. Hiện đang dùng
   `z_decay_mm=21.4mm` (params.yaml `levitation:`), dự đoán gap@7.75A≈22.9mm,
   nhưng bạn quan sát gap "chỉ nhích nhẹ" — 21.4mm nhiều khả năng quá lớn.

2. **[WP-A] Mâu thuẫn số liệu trong chính kế hoạch này, CHƯA tự ý sửa**: tiêu
   chí nghiệm thu WP-A đòi overshoot bước 5→7.75A phải <40% overshoot bước
   0→5A — muốn vậy cần ζ(7.75A)≈0.3. Nhưng công thức vật lý ζ(I)=ζ0+ζ1·(I/5)²
   neo tại ζ(5A)=0.02 (khớp quan sát settle ~9s) chỉ cho ra ζ(7.75A)≈0.048 —
   KHÔNG thể đạt 0.3 nếu không phá neo 5A. Đo được: overshoot ratio thực tế là
   91.5%, test FAIL theo tiêu chí gốc. Cần bạn quyết định: (a) nới tiêu chí
   overshoot, (b) đổi sang luật damping dốc hơn (kém "vật lý" hơn), hay (c) chờ
   dữ liệu dao động thật ở 7.75-8A để fit ζ cho đúng.

3. **[WP-B] Chưa có dữ liệu NGUỘI thật.** `coil_G_wind_W_per_K=1.0` hiện chỉ
   fit được từ đường NÓNG (ramp test) + mục tiêu định tính "chậm hơn nhiều" —
   coi là order-of-magnitude. Lần tới ra lab: giữ dòng ổn định ở 5A cho tới
   steady state, tắt dòng, đọc IR nhiệt độ coil mỗi 60s trong 20-30 phút → fit
   định lượng `coil_G_wind_W_per_K` và `convection_exponent`.

4. **[WP-C/D] Hai cách tính z0 (decay length) lệch nhau ~1.5×, đã tìm thấy khi
   nối WP-C vào WP-D, KHÔNG tự ý chọn 1 bên**: số đang DÙNG trong file R=80
   mặc định là `z0=21.4mm` (khớp F(1mm) và điểm cắt F=F_grav — cách tính gốc,
   2026-07-01). WP-C tính lại bằng cách khác (khớp F(1mm) và F(5mm) trực tiếp,
   không phụ thuộc khối lượng đĩa) ra `z0=13.6mm` cho CÙNG một đĩa R=80mm. Cả
   hai đều "đúng" theo cách định nghĩa riêng — chênh nhau vì F(z) không phải
   một hàm mũ sạch trên khoảng đó. R=101 hiện dùng cách tính của WP-C (13.6mm
   kiểu). Câu hỏi: có dữ liệu đo gap thực ở nhiều mức dòng để chọn cách nào mô
   phỏng đúng hơn không? (Câu hỏi #1 ở trên — gap@7.75A — sẽ giúp trả lời câu
   này luôn.)

5. **[WP-C] Đĩa Ø202mm KHÔNG bay ở dòng vận hành chuẩn 5A_rms** — cần
   I_min_lev≈6.45A (thiếu ~40% lực nâng so với 2.55N trọng lượng). Đây là kết
   quả mô phỏng, chưa kiểm chứng bằng đĩa thật. Nếu định thực sự đúc đĩa Ø202mm
   để thử trên rig, có đáng thử không, hay giữ đĩa Ø160mm hiện tại?

6. **[Nền, không riêng WP nào] Iron/separator ring (r=81-101mm) — magnet test
   CHƯA làm.** Đang model là air (μ_r=1). Nếu ferromagnetic thật, P_plate và
   F_z có thể đổi rất lớn (xem "μ_r SENSITIVITY TEST" trong CLAUDE.md) — ảnh
   hưởng cả kết quả R=101 (WP-C) lẫn các số levitation hiện tại. Cần magnet test
   thực tế trên vành ring này (giống test đã làm với center core).

7. **[Nền] Đĩa nóng hơn hay cuộn dây nóng hơn?** Twin hiện dự đoán
   T_ss(plate,5.5A)=61.7°C CAO HƠN cả cuộn dây (~59°C), nhưng dữ liệu IR nói
   cuộn dây nóng hơn đĩa nhiều. Model đĩa (FEM, ΔT_max=27K@5A) CHƯA từng được
   fit bằng dữ liệu thật (IR đĩa không đáng tin — đĩa nhôm bóng, ε sai). Cần đo
   nhiệt độ đĩa bằng thermocouple tiếp xúc thật (không phải IR) để fit hệ số h
   của đĩa.

8. **[Nền, phát hiện phụ của WP-C] Độ nhạy lưới (mesh)**: làm mịn lưới EM
   (`em_domain.fine_step_mm` 2.0→1.0mm) làm z_eq(R=80) đổi từ 4.15mm xuống
   ~3.5mm-tương-đương (đủ để đĩa R=80 lúc đó KHÔNG bay ở 5A nữa!), và
   I_min_lev(R=101) đổi từ 6.45A→6.9A. Tức con số "z_eq=4.1mm đã validated"
   nhạy với lưới hơn tưởng — chưa xử lý (nằm ngoài phạm vi WP-C, liên quan tới
   cuộc điều tra benchmark 37% đang PAUSED). Ai đó nên revisit khi có thời gian.
