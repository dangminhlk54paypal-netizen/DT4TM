# Kế hoạch Fix Lỗi Mô Phỏng HTML (DT4TM Project)

Tài liệu này phân tích 4 lỗi hiển thị trong mô phỏng HTML (file `build_twin_html_fem.py`) theo báo cáo của người dùng và chia nhỏ thành các task để giao cho các agent/mô hình nhỏ hơn thực hiện.

## Phân tích nguyên nhân và đề xuất giải quyết

### 1. Gap 8.7mm nhìn quá cao so với chiều cao model

- **Nguyên nhân:** Trong hàm `levLiftY()` (khoảng line 1277), code đang cộng thêm một giá trị `LIFT_BASE = modelH * 0.20` vào vị trí của đĩa. Với chiều cao model khoảng 50mm, `LIFT_BASE` tạo ra một khoảng không (offset) dư thừa lên tới ~10mm. Ngoài ra, thông số `display_z_exaggeration` trong `params.yaml` có thể đang phóng đại khoảng cách này lên gấp đôi.
- **Giải pháp:**
  - Loại bỏ biến `LIFT_BASE` (hoặc set = 0) trong tính toán `levLiftY()` và vị trí tọa độ Y của `plateM`.
  - Đảm bảo tọa độ vật lý Z được ánh xạ 1:1 sang Three.js Y, chỉ giữ lại `lev.z` (và phóng đại `Z_GAP_EXAG` nếu thực sự cần thiết, nhưng nên tắt mặc định).

### 2. Từ trường (Field B) đứng yên khi tăng giảm dòng I

- **Nguyên nhân:** Các đường sức từ (field-line) hiện tại chỉ là hiệu ứng hình ảnh thuần túy. Ở cuối hàm render (khoảng line 1950), biến `dashOffset` được cập nhật theo thời gian thực `(now / 1000) * FIELD_LINE_FLOW_SPEED` mà hoàn toàn không phụ thuộc vào dòng điện thực tế `I_display`. Do đó khi đổi I, tốc độ và cường độ của đường sức từ vẫn giữ nguyên.
- **Giải pháp:**
  - Gắn tốc độ di chuyển `FIELD_LINE_FLOW_SPEED` hoặc `opacity` của vật liệu `LineSegments` với biến `I_display`. Ví dụ: nếu `I_display == 0` thì field line biến mất, nếu `I` tăng thì độ đậm (opacity) và tốc độ chuyển động (flow speed) tăng theo.

### 3. Bề mặt cuộn dây không đổi màu khi nhiệt độ tăng

- **Nguyên nhân:** Hàm `paintMesh()` (line 1461) tính toán màu sắc cho cuộn dây thông qua biến `tnInner = (sim.T.inner - T_AMB_JS) / dT_inner_ss`. Tuy nhiên, `dT_inner_ss` lại phụ thuộc vào **dòng điện hiện tại** (`coilTss_inner(I_cur)`). Nghĩa là khi người dùng vừa vặn tăng dòng I, `dT_inner_ss` lập tức tăng vọt trong khi `sim.T.inner` vẫn còn nguội (do nhiệt độ cuộn dây cần nhiều phút để tăng). Kết quả là `tnInner` tụt xuống 0, khiến cuộn dây trông "nguội" ngay lập tức dù đang bắt đầu nóng lên.
- **Giải pháp:**
  - Đổi cách chuẩn hóa (normalize) nhiệt độ của cuộn dây từ hệ quy chiếu tương đối (theo I) sang hệ quy chiếu tuyệt đối (ví dụ dải từ `20°C` đến `60°C`). Như vậy khi `sim.T.inner` tăng dần theo thời gian, `tnInner` sẽ tăng từ từ và cuộn dây sẽ đỏ lên một cách chuẩn xác bất chấp người dùng đang chỉnh I ở mức nào.

### 4. Tính năng "chói lóa" (Bloom/Glare) gây ảo giác vật liệu kim loại

- **Nguyên nhân:**
  - Code đang sử dụng hiệu ứng `UnrealBloomPass` trong Three.js (khoảng line 1957 có `bloomPass.strength = I_display > 0.01 ? 0.42 : 0.0;`) khiến toàn bộ vật thể bị phát sáng (chói) khi có dòng điện chạy qua.
  - Các biến `metalness` và `roughness` của vật liệu (trong `makeMesh()`) đang làm cuộn dây và khung phản xạ môi trường quá nhiều, không giống vật liệu cách điện hay vecni thực tế có khả năng hấp thụ ánh sáng.
- **Giải pháp:**
  - Tắt hoàn toàn `BloomPass` hoặc set `bloomPass.strength = 0`.
  - Tinh chỉnh vật liệu của cuộn dây (tăng `roughness`, giảm `metalness` xuống thấp hơn, ví dụ `metalness = 0.05`, `roughness = 0.8`) và giảm cường độ `envMapIntensity` để bề mặt trở nên lì và hấp thụ ánh sáng giống đời thực hơn.

---

## Phân công công việc (Task Breakdown cho các model nhỏ)

Để triển khai, bạn có thể giao các task sau cho các model nhỏ:

1. **Task 1 (Geometry & Rendering): Sửa lỗi hiển thị Gap (Lỗi 1)**
   - **Tệp chỉnh sửa:** `build_twin_html_fem.py`
   - **Mô tả:** Tìm hàm `levLiftY()` và khai báo `LIFT_BASE`. Sửa `LIFT_BASE = 0.0` hoặc loại bỏ nó khỏi phép tính `levLiftY()` và sửa lại các `gapBot`, `gapTop` của mảng `flPts` tương ứng để đĩa bay hiển thị sát với khoảng cách vật lý thực tế.

2. **Task 2 (Visual Effects): Làm B-field phản ứng với dòng điện I (Lỗi 2)**
   - **Tệp chỉnh sửa:** `build_twin_html_fem.py`
   - **Mô tả:** Trong vòng lặp animation (hàm `animate` / phần render), tìm đoạn tính toán `dashOffset`. Chỉnh sửa sao cho tốc độ cuộn `FIELD_LINE_FLOW_SPEED` hoặc độ trong suốt (`opacity`) của `fieldLineMats` tỷ lệ thuận với dòng điện `I_display` (dòng lớn thì chạy nhanh / đậm hơn).

3. **Task 3 (Logic & Colors): Sửa thang đo nhiệt độ cho cuộn dây (Lỗi 3)**
   - **Tệp chỉnh sửa:** `build_twin_html_fem.py`
   - **Mô tả:** Trong hàm `paintMesh(M)`, thay đổi cách tính `tnInner` và `tnOuter`. Thay vì chia cho `dT_inner_ss` (vốn thay đổi đột ngột theo `I_cur`), hãy sử dụng một hằng số cố định tuyệt đối như `MAX_COIL_TEMP = 50.0` (độ C) để làm mẫu số: `tnInner = (sim.T.inner - T_AMB_JS) / (MAX_COIL_TEMP - T_AMB_JS)`. Điều này giúp cuộn dây đổi màu từ từ khi nhiệt độ thực sự tăng.

4. **Task 4 (Materials & Post-processing): Tắt độ chói lóa và chỉnh vật liệu (Lỗi 4)**
   - **Tệp chỉnh sửa:** `build_twin_html_fem.py`
   - **Mô tả:** Tìm và xóa/tắt dòng gán `bloomPass.strength = 0.42`. Đồng thời, tìm nơi khởi tạo `coilM` và `baseM` bằng hàm `makeMesh()`, hạ `metalness` xuống rất thấp (khoảng 0.05) và tăng `roughness` (lên khoảng 0.8 - 0.9) để loại bỏ tính chất phản gương của kim loại.
