# Kế hoạch sửa 4 lỗi hiển thị — digital_twin_fem.html (2026-07-02)

**File cần sửa duy nhất:** `build_twin_html_fem.py` (template JS nằm trong chuỗi HTML của file này).
**Sau khi sửa phải regenerate:** `python build_twin_html_fem.py` → `outputs/digital_twin_fem.html`.
**Model thực hiện:** Sonnet (các phiên sau). Làm theo đúng thứ tự Task 1 → 4, mỗi task verify xong mới sang task kế.

> Nguồn: báo cáo user 2026-07-02 (ảnh `docs/z_achse_260701.png`, `docs/thermal_test.png`)
> + phân tích Gemini trong `docs/implemetation_Plan.md`. Claude (Fable) đã kiểm chứng
> từng nhận định trực tiếp trên code ngày 2026-07-02 — kết quả kiểm chứng ghi ở đầu mỗi task.
> Số dòng bên dưới đúng với build_twin_html_fem.py tại thời điểm 2026-07-02 (chưa sửa gì);
> nếu file đã đổi, tìm theo tên biến/hàm thay vì số dòng.

---

## Task 1 — Gap đĩa bay hiển thị quá cao so với model

### Kiểm chứng (Fable, 2026-07-02)
Gemini đúng một nửa. `LIFT_BASE = modelH * 0.20` (line 1275) có thật và là offset thừa,
nhưng **thủ phạm CHÍNH mà Gemini bỏ sót là `Z_GAP_EXAG = 8.0`** (line 1138) — và còn
một khoảng gap 3.8mm **đã bake sẵn vào geometry** của đĩa (Python line 496:
`z_disc_bot = z_coil_top + z_bottom_mm(3.8)`).

Tổng gap hiển thị hiện tại = 3.8 (baked) + LIFT_BASE (~14mm, vì modelH≈69.8mm)
+ `lev.z × 8.0`. Với gap vật lý 8.7mm như trong screenshot:
3.8 + 14 + 69.6 ≈ **87 display-mm** — cao hơn cả cụm coil 60mm → đúng như user thấy.
Lưu ý: `display_z_exaggeration: 2.0` trong params.yaml chỉ phóng đại ĐỘ DÀY đĩa
(3→6mm), KHÔNG ảnh hưởng gap — nghi ngờ của Gemini về thông số này là sai.

### Cách sửa
Mục tiêu: gap hiển thị = `lev.z × zex` với cùng hệ số phóng đại `zex=2.0` như độ dày đĩa
(nhất quán: mọi kích thước trục z của đĩa đều ×2). Tức 4.1mm @5A → 8.2 display-mm.

1. **Python** (line ~496): bỏ gap bake sẵn — build đĩa ngồi ngay trên coil top:
   ```python
   z_disc_bot = z_coil_top    # gap được cộng RUNTIME qua lev.z, không bake vào geometry
   ```
   (giữ nguyên key `z_bottom_mm` trong params.yaml, chỉ không dùng cho geometry nữa;
   hoặc xoá luôn phần đọc nó nếu không còn ai dùng.)
2. **JS**: `Z_GAP_EXAG = 8.0` → **2.0** (line 1138) — và sửa comment cho đúng.
3. **JS**: xoá `LIFT_BASE` (line 1275). `levLiftY()` (line 1277-1279) thành:
   ```javascript
   function levLiftY() { return lev.z * Z_GAP_EXAG; }
   ```
4. **Cập nhật các chỗ dùng LIFT_BASE cho nhất quán** (nếu quên sẽ lệch hình):
   - line 1294: `flPts.push(x, gapBot, z, x, gapTop + LIFT_BASE*0.9, z)` → thay
     `LIFT_BASE*0.9` bằng một hằng nhỏ theo model, ví dụ `modelH*0.10` (arc trang trí).
   - line 1368: `plateTopY = (bb.max.y-ctr.y) + LIFT_BASE + levGapEqMm(targetI)*Z_GAP_EXAG`
     → bỏ `LIFT_BASE`. (bb.max.y giờ = đỉnh đĩa ngồi sát coil, vẫn đúng nghĩa.)
   - line 1442: `particleTopY = gapTop + LIFT_BASE*0.9` → `gapTop + modelH*0.10`.
5. Camera framing (line 1369-1370) giữ nguyên, chỉ kiểm tra lại bằng screenshot.

### Verify
- Mở HTML headless (Playwright, xem mẫu test cuối file này): tại I=5A sau khi đĩa
  settle, đo `plateM.mesh.position.y` − vị trí lúc I=0 phải ≈ `4.1 × 2.0 = 8.2` world-units.
- Screenshot: đĩa lơ lửng NGAY trên coil, gap trông ~1/7 chiều cao model chứ không
  phải lơ lửng giữa trời như ảnh `z_achse_260701.png`.
- Gap telemetry vẫn hiển thị số VẬT LÝ (`lev.z`, mm) — không đổi.

---

## Task 2 — B-field không phản ứng khi thay đổi I

### Kiểm chứng (Fable, 2026-07-02)
Gemini đúng. Field lines là geometry TĨNH bake từ contour ψ=r·A_φ tại I_ref
(line 1301-1352); `dashOffset = -(now/1000) * FIELD_LINE_FLOW_SPEED` (line 1953)
chạy theo wall clock, không dính gì tới `I_display`; opacity chỉ theo slider
(`applyFieldLineOpacity`, line 1353-1355). Không có bất kỳ kênh nào để I ảnh hưởng hình ảnh.

Lưu ý vật lý (giữ nguyên, KHÔNG rebake geometry theo I): bài toán tuyến tính → HÌNH DẠNG
đường sức không đổi theo I, chỉ CƯỜNG ĐỘ scale tuyến tính. Vậy geometry tĩnh là đúng;
cái cần sửa là cue cường độ (opacity + tốc độ flow) phải theo I.

### Cách sửa
1. Trong loop (line 1952-1955), thay khối field-line bằng:
   ```javascript
   if (fieldLineGroup.visible) {
     const iFrac = Math.min(2.0, Math.abs(I_display) / ROM.I_ref);  // 0→0A, 1→5A, cap 2
     flFlowPhase += wall_dt * FIELD_LINE_FLOW_SPEED * iFrac;        // tích luỹ, không nhảy khi I đổi
     for (const o of fieldLineMats) {
       o.mat.dashOffset = -flFlowPhase;
       o.mat.opacity = fieldLineOpacityPct * (0.15 + 0.85 * o.amp) * Math.min(1, iFrac);
     }
   }
   ```
   Khai báo `let flFlowPhase = 0;` cạnh `FIELD_LINE_FLOW_SPEED` (line 1361).
   Dùng phase tích luỹ (thay vì `now × speed`) để khi I đổi tốc độ dash không giật.
2. `applyFieldLineOpacity()` (slider handler) giữ nguyên — nhưng vì loop giờ ghi đè
   opacity mỗi frame khi visible, có thể XOÁ call trong slider handler hoặc để nguyên
   (vô hại, loop ghi đè ngay frame sau).
3. Hành vi mong muốn: I=0 → đường sức mờ dần về 0 + đứng yên; I tăng → đậm hơn
   (tới cap) + chảy nhanh hơn.

### Verify
- Headless: bật vizMode 'bfield', set slider I=0 → sample vài `fieldLineMats[i].mat.opacity`
  phải = 0; set I=13 → opacity > 0 và `dashOffset` thay đổi giữa 2 frame nhanh hơn so với I=5.
- Mắt thường: kéo slider I từ 0 lên, đường sức hiện dần và chảy nhanh dần.

---

## Task 3 — Cuộn dây không đổi màu khi nóng lên

### Kiểm chứng (Fable, 2026-07-02)
Gemini đúng root cause. `paintMesh()` line 1467-1471: `tnInner = (sim.T.inner − T_AMB_JS)
/ dT_inner_ss` với `dT_inner_ss = coilTss_inner(I_cur) − T_AMB_JS` phụ thuộc I **tức thời**
(∝ I²). Hệ quả:
- Tăng I → mẫu số nhảy vọt → tnorm sập về ~0 → coil "nguội" ngay dù đang nóng lên.
- Scenario sine (như screenshot): mẫu số dao động liên tục → màu nhấp nháy theo I
  chứ không theo nhiệt độ thật.
- Ở steady state tnorm→1 với MỌI I → 5A và 13A đều "cam rực" như nhau — sai bản chất.
- `tnIron` (line 1477) cũng chia cùng mẫu số động đó → lỗi lây sang core/separator.

### Cách sửa
Chuyển sang thang TUYỆT ĐỐI cố định, neo theo dữ liệu IR thật (session 1: inner coil
79°C @7.8A là nóng nhất từng đo):
```javascript
// Thang màu coil TUYỆT ĐỐI: T_amb → T_COIL_HOT. Không phụ thuộc I tức thời —
// màu chỉ đổi khi NHIỆT ĐỘ thật đổi (IR session 1: inner coil max 79°C @7.8A).
const T_COIL_HOT = 80.0;   // °C, đỉnh thang màu coil
const tnInner = (sim.T.inner - T_AMB_JS) / (T_COIL_HOT - T_AMB_JS);
const tnOuter = (sim.T.outer - T_AMB_JS) / (T_COIL_HOT - T_AMB_JS);
const tnIron  = (sim.T.iron  - T_AMB_JS) / (T_COIL_HOT - T_AMB_JS) * 1.8;  // boost: core/sep chỉ lên ~45°C
```
- Xoá `dT_inner_ss`/`dT_outer_ss` và `I_cur = getI()` nếu không còn dùng (line 1467-1469).
- `writeRampCopper`/`writeRampMetal` đã clamp tnorm vào [0,1] — kiểm tra lại, nếu chưa
  clamp thì thêm clamp.
- Hệ số boost 1.8 cho tnIron: core/separator thật chỉ đạt ~45°C @7.8A (tnorm tuyệt đối
  ~0.31) — nhân 1.8 để dịch chuyển màu nhìn thấy được, khớp ảnh IR (coil rực, ring ấm vừa).
  Đây là quyết định thị giác, chỉnh trong khoảng 1.5–2.0 nếu screenshot chưa giống
  `docs/thermal_test.png`.
- LƯU Ý LỊCH SỬ: CLAUDE.md session 2026-07-02 từng chuyển từ absolute → relative vì
  "màu bị đóng băng". Nguyên nhân đóng băng khi đó là thang 29–125°C QUÁ RỘNG + iron
  node thiếu conduction (đã fix bằng `G_iron_cond_W_per_K`). Thang mới 29–80°C hẹp hơn
  nhiều nên không tái mắc lỗi cũ — đừng quay lại thang 125°C.

### Verify
- Headless: set I=13A step, chạy ~5 sim-min: màu coil phải chuyển DẦN từ nâu sô-cô-la
  → cam theo thời gian (chụp 3 screenshot t=0/2min/5min so sánh), KHÔNG đổi màu tức
  thì tại thời điểm kéo slider.
- Kéo slider I từ 13 về 5 khi coil đang nóng: màu coil phải GIỮ NGUYÊN (nhiệt chưa kịp
  giảm), chỉ nguội dần từ từ.
- So screenshot cuối với `docs/thermal_test.png`: coil sáng nhất, core/separator ấm vừa.

---

## Task 4 — Tắt chói lóa (bloom) + vật liệu hấp thụ ánh sáng

### Kiểm chứng (Fable, 2026-07-02)
Gemini đúng. Ba nguồn "chói":
1. `bloomPass.strength = I_display > 0.01 ? 0.42 : 0.0` (line 1959) — bloom bật gần như
   thường trực (I mặc định 5A), làm highlight nở sáng.
2. `scene.environment = PMREM(RoomEnvironment)` (line 1184-1185) + `envMapIntensity: 0.8`
   cho MỌI mesh trong `makeMesh()` (line 1234-1235) — phản xạ studio trượt trên bề mặt
   khi xoay camera → cảm giác "mọi thứ đều là kim loại bóng".
3. Metalness hiện tại: baseM 0.68, coilM 0.20, plateM 0.75, woodM 0.02 (line 1248-1251).

### Cách sửa
1. **Tắt bloom hẳn**: xoá line 1959 (hoặc set hằng `bloomPass.strength = 0.0` ngay khi
   khởi tạo và xoá dòng trong loop). Gọn nhất: xoá luôn `EffectComposer`/`RenderPass`/
   `UnrealBloomPass`/`composer.addPass` (line 1196-1199 + import line ~909-911) và thay
   `composer.render()` (line 1964) bằng `renderer.render(scene, camera)`; nhớ sửa cả
   `composer.setSize` trong resize handler (line 1971). Nếu muốn ít rủi ro hơn thì giữ
   composer nhưng strength=0 cố định — chọn phương án xoá hẳn nếu tự tin verify.
2. **Cho phép envMapIntensity theo mesh** — thêm tham số vào `makeMesh(sub, roughness,
   metalness, envInt=0.8)` (line 1227) rồi set:
   ```javascript
   const baseM  = makeMesh(buildSub(r => r===3||r===5), 0.60, 0.30, 0.25); // core+separator: kim loại mờ/oxit
   const coilM  = makeMesh(buildSub(r => r===1||r===2), 0.80, 0.05, 0.15); // vecni+keo cách điện: lì, hấp thụ sáng
   const woodM  = makeMesh(buildSub(r => r===4),        0.90, 0.00, 0.05); // plywood
   const plateM = makeMesh(buildSub(r => r===0),        0.45, 0.65, 0.45); // đĩa nhôm: vẫn là kim loại thật
   ```
   Lý do giữ plateM metallic: đĩa nhôm THẬT là kim loại bóng — user chỉ phàn nàn về
   "các vòng tròn" (coil/ring/khung). Chỉ giảm nhẹ envMapIntensity của đĩa cho đỡ gắt.
3. Giữ `renderer.toneMapping = ACESFilmic` (line 1177) — cần cho env map không cháy trắng.
   Nếu sau khi giảm envMapIntensity mà scene tối, tăng nhẹ AmbientLight 0.5 → 0.65 (line 1373).

### Verify
- Headless: xoay camera qua 4-5 góc (set `twinDebug.camera.position`), chụp screenshot —
  không còn vệt sáng trắng trượt trên coil/khung khi đổi góc; coil màu nâu lì.
- 0 JS errors trong console (đặc biệt nếu xoá composer — dễ sót reference).
- Đối chiếu `docs/real_model.png`: coil nâu sậm lì, chỉ đĩa nhôm có ánh kim.

---

## Trình tự thực hiện & quy tắc chung

1. Làm đúng thứ tự Task 1→2→3→4 (Task 1 đổi geometry Python → phải regen HTML trước khi
   verify các task sau; Task 4 đụng render pipeline nên để cuối, verify screenshot sạch nhất).
2. Sau MỖI task: `python build_twin_html_fem.py` → verify headless → mới sang task kế.
   (Script tự đọc ROM/EM đã cache; nếu nó chạy lại EM solve mất vài phút là bình thường.)
3. KHÔNG hardcode số vật lý mới vào JS — số vật lý lấy từ params.yaml qua Python
   (quy tắc locked trong CLAUDE.md). Hằng THỊ GIÁC thuần túy (Z_GAP_EXAG, T_COIL_HOT,
   boost 1.8, roughness/metalness) được phép nằm trong template JS, có comment giải thích.
4. Xong cả 4 task: cập nhật CLAUDE.md (thêm 1 mục "[x] build_twin_html_fem.py — 4 render
   fixes 2026-07-0x" ngắn gọn) + mục 3D Body Geometry trong docs/QUICK_START_FOR_AGENTS.md
   (Z_GAP_EXAG 8.0→2.0, material table, thang màu coil tuyệt đối 29–80°C).
5. Commit khi user yêu cầu, kèm `outputs/digital_twin_fem.html` (file này ĐƯỢC commit,
   xem .gitignore).

## Mẫu verify headless (Playwright, đã dùng các session trước)

```python
# scratchpad/verify_twin.py — chạy: python scratchpad/verify_twin.py
import asyncio, pathlib
from playwright.async_api import async_playwright

HTML = pathlib.Path("outputs/digital_twin_fem.html").resolve().as_uri()

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width":1600,"height":1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(HTML)
        await pg.wait_for_timeout(3000)
        # ví dụ: đọc trạng thái qua window.twinDebug / DOM
        gap = await pg.text_content("#tLevGap")
        y   = await pg.evaluate("window.twinDebug && twinDebug.camera.position.y")
        await pg.screenshot(path="scratchpad/twin_check.png")
        print("JS errors:", errs, "| gap:", gap, "| camY:", y)
        await b.close()

asyncio.run(main())
```
Tiêu chí chung mọi task: **0 JS errors** + screenshot khớp mô tả Verify của task.
