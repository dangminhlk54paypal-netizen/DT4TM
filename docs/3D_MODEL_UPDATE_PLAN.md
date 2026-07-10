# Kế hoạch Cập nhật 3D Model — Trạng thái (2026-06-23, cập nhật lần 2)

Bản gốc của file này là một kế hoạch do Gemini soạn (xem lịch sử git). Phần dưới đây
ghi lại CHÍNH XÁC những gì đã làm dựa trên dữ liệu thực tế (rig + camera nhiệt
HIKMICRO, 2 lần đo trong cùng ngày), thay cho bản kế hoạch cũ.

**Sửa lại một phát hiện SAI ở bản trước:** lần phân tích đầu nói tường thật trong STL
chỉ cao ~23mm (z≈21-43mm). Khi đào sâu thêm để build vành đệm, phát hiện đó SAI — các
tam giác "tường" thực ra có 1 đỉnh ở z=-2mm và 1 đỉnh ở z=66mm (CAO HẾT CHIỀU CAO thiết
bị); centroid trung bình ra ~20.7/43.3 chỉ là ảo giác do tam giác quá dài/mỏng. Tường
thật ở r≈25/59/79mm cao SUỐT từ đáy (z=-2mm) lên gần đỉnh (z=66mm).

## ĐÃ XONG (✓)

### 1. Màu vật liệu — `build_twin_html_fem.py` (TEMPLATE JS)
- `STRUCT_RGB` đổi từ xám trung tính → **nâu gỗ** `[160,100,55]/255` (vùng 4 = wood base).
- Thêm `METAL_RGB = [170,175,185]/255` (kim loại trắng-xám thụ động).
- `paintMesh()`: vùng 4 (gỗ) dùng `STRUCT_RGB`; vùng 3 (center spacer) và vùng 5
  (separator ring, xem mục 4) dùng `METAL_RGB` **TĨNH** (không `writeRamp` theo nhiệt
  độ); vùng 1/2 (cuộn trong/ngoài) vẫn dùng `writeRamp` (thang nhiệt động, vì đây là
  nguồn nhiệt thật). Lý do: cả 2 lần đo đều cho thấy lõi giữa + vành đệm chỉ
  36-45°C so với cuộn dây 56-79°C → gần như thụ động, tô theo thang nhiệt sẽ gây hiểu lầm.
- Nhãn CSS2D `'Iron Core'` → `'Center Spacer'`; thêm nhãn `'Separator Ring'`.
- Verify bằng Playwright (headless Chromium): không JS error; screenshot xác nhận gỗ
  nâu, center spacer + separator ring màu trắng-xám tĩnh dù cuộn ngoài đang đỏ rực.

### 2. Tài liệu hoá vật liệu + dữ liệu thật — `params.yaml`
- `excitation.voltage_V`: 220 → **190** (đo thật: 190V→5A). `current_A` giữ 5.0.
- Thêm `coils.fill_factor: 0.6` (placeholder, ghi chú CHƯA dùng để đổi công thức).
- Thêm block `separator_ring` (material nghi nhôm/oxit HOẶC sắt — xem mục B dưới,
  còn mở).
- Thêm block `validation_data` với 2 bộ dữ liệu: `thermal_at_7p8A` (giữ nguyên 7.8A
  ~6 phút, đạt steady-state) và `thermal_ramp_test` (lần đo thứ 2, 2 giai đoạn
  5A→7.75A, dùng để fit hằng số thời gian nhiệt — xem mục 3).
- `iron_core` + `separator_ring`: ghi rõ test nam châm/lift-force là **CIRCUMSTANTIAL,
  KHÔNG kết luận chắc** (xem mục B).
- `python config.py` parse OK sau mỗi lần sửa.

### 3. Calibrate mạng nhiệt cuộn dây (2 vòng fit) — `params.yaml` (`lumped_thermal`)
- **Vòng 1** (chỉ steady-state 7.8A: inner=79°C, outer=74°C): `hA_inner=2.2109`,
  `hA_outer=1.8889` W/K (từ hA đoán tay cũ 0.48/0.44). Khớp CHÍNH XÁC số đo steady.
- **Vòng 2** (thêm dữ liệu ramp-test để fit cả τ — transient, không chỉ steady-state):
  vòng 1 dự đoán transient CHẬM hơn thực tế ~10°C (ví dụ 38°C dự đoán vs 48.5°C đo
  tại t=300s). Thêm tham số `coil_C_scale=0.434` (khối nhiệt hiệu dụng cuộn dây chỉ
  ~43% so với giả định đồng nguyên chất — hợp lý vì cuộn dây có cách điện/khoảng hở,
  và `wire_diameter_mm=1.2` có thể là đường kính ĐÃ BỌC cách điện, không phải lõi đồng
  trần) → refit jointly: `hA_inner=2.2479`, `hA_outer=1.8788`, sai số còn lại ~2-5°C
  (so với ~10°C trước đó). Đây là fit THỰC NGHIỆM từ 1 lần đo với mốc thời gian đọc
  từ tường trình (sai số ước lượng ±10s) — coi τ là ĐÚNG BẬC ĐỘ LỚN, chưa chính xác
  tuyệt đối; cần 1 lần đo có log thời gian thật (không phải kể lại) để tinh chỉnh thêm.
- Cross-check tại I_ref=5A (T_amb=20°C, ambient baked của twin): dự đoán
  **T_inner≈40.5°C, T_outer≈38.5°C** (steady-state; chưa tính transient ở mức 5A).
- `AIR.C_air` / `AIR.hA_far` trong JS không còn hardcode — đọc từ `LUMPED.air_node`.

### 4. "Separator ring" — ĐÃ RENDER bằng hình học sinh thủ tục (procedural)
STL thật KHÔNG có mặt nào ở đúng khoảng hở `params.yaml` ngụ ý (25-28mm: 0 tam giác;
43-46.5mm: 1 tam giác — không đủ để tô màu). Đã chọn phương án **(a) sinh hình học
mới**: hàm `build_separator_rings()` trong `build_twin_html_fem.py` tạo 2 ống trụ
mỏng (vùng 5) tại đúng 2 khoảng hở (lấy từ `iron_core`/`coils.inner`/`coils.outer`
trong cfg, không hardcode), cao SUỐT từ z=-2mm đến z=66mm — bằng đúng chiều cao tường
thật của center spacer bên cạnh (lấy động từ dữ liệu STL, không hardcode chiều cao),
để đứng "ngang hàng" về thị giác với lõi giữa và cuộn ngoài. Verify: build in ra
"separator (procedural): 1920 tris" (2 vành x 960 tam giác, không vành nào = 0);
Playwright xác nhận không JS error; screenshot cận cảnh thấy rõ vành xám đứng giữa
lõi và cuộn dây, nhãn "Separator Ring" đúng vị trí.
**Lưu ý:** đây là hình học MỚI (không có trong STL gốc), chỉ phục vụ hiển thị — không
ảnh hưởng EM/thermal solver (vẫn dùng `plate_material`/`coils`/`iron_core` như cũ).

## CÒN MỞ

### B. Sắt vs nhôm cho lõi giữa VÀ vành đệm — vẫn CHƯA xác nhận chắc chắn
User quan sát: khi có dòng điện, đĩa nhôm bị đẩy lên (lực từ) → suy ra lõi giữa là
sắt. **Đây là suy luận CHƯA chắc chắn**: lực đẩy đĩa nhôm là do dòng điện xoáy (eddy
current) cảm ứng trong chính đĩa nhôm phản ứng với từ trường biến thiên của cuộn dây
— hiện tượng này XẢY RA BẤT KỂ lõi giữa là sắt hay nhôm (lõi chỉ định hình/khuếch đại
từ trường, không phải vật bị đẩy). Test trực tiếp và dứt điểm hơn: áp NAM CHÂM VĨNH
CỬU vào lõi/vành đệm KHI CHƯA CẤP ĐIỆN, xem có bị hút không. Đến khi có test này:
- `iron_core.mu_r` GIỮ NGUYÊN 1000 (không tắt iron).
- `separator_ring.mu_r` GIỮ NGUYÊN 1.0 (dữ liệu ramp-test gọi vành đệm là "lõi sắt
  ngoài" nhưng KHÔNG có test riêng cho vành đệm, chỉ suy luận tương tự từ lõi giữa).
- Dữ liệu nhiệt (cả 2 lần đo) không phân biệt được — lõi+vành đệm luôn nguội hơn
  cuộn dây nhiều dù là sắt hay nhôm (P_iron chỉ ~0.6-1.5W).

## PHASE TIẾP (chờ test nam châm trực tiếp + đo đạc thêm)

1. **Test nam châm TRỰC TIẾP** (chạm nam châm vĩnh cửu vào lõi giữa VÀ vành đệm khi
   KHÔNG cấp điện) — kết luận chắc chắn hơn phép suy luận từ lực đẩy đĩa. Nếu cả 2 đều
   hút: giữ `iron_core.mu_r=1000` và đổi `separator_ring.mu_r` → 1000 (đồng bộ); nếu
   không: đổi cả 2 về `mu_r=1.0`. Đây là việc cần sửa em_solver.py (EM-core), KHÔNG
   làm trong vòng vừa qua theo đúng giới hạn đã thống nhất.
2. **Dán điểm sơn mờ (matte paint dot)** trên đĩa nhôm + lõi tâm + vành đệm, đo lại
   bằng IR/thermocouple — số IR trên kim loại bóng hiện KHÔNG đáng tin (ε thật ~0.1
   vs ε camera 0.91 → đọc thấp); áp dụng cho CẢ 2 lần đo, không chỉ lần đầu.
3. Đo lại ở **190V/5A** giữ đủ lâu để đạt steady-state, đối chiếu dự đoán
   T_inner≈40.5°C / T_outer≈38.5°C.
4. Nếu muốn τ (hằng số thời gian) chính xác hơn `coil_C_scale=0.434` hiện tại: lặp lại
   ramp-test với LOG THỜI GIAN THẬT (Arduino/đồng hồ bấm giờ ghi số, không kể lại từ
   trí nhớ) — sai số đọc mốc thời gian hiện tại (±10s) là nguồn sai số chính còn lại.
5. Đo thực tế bán kính các cuộn dây trên rig (so với `coils.inner/outer` hiện tại
   trong params.yaml) — STL và params.yaml không khớp hoàn toàn ở vài bán kính, nên
   CONFIRM lại bằng thước đo thật, không chỉ tin STL hoặc tin params.yaml.
6. ~~`build_twin_html.py` (bản lumped-only, không phải bản chính) CHƯA được đồng bộ
   vành đệm procedural — chỉ cần làm nếu user còn dùng file đó.~~ **Đã moot: file này
   đã bị xóa 2026-07-02, commit ec64ec1 — mục này không còn áp dụng.**
