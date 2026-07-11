# AUDIT & FIX PLAN — 2026-07-04

Kết quả audit toàn hệ thống (3 hướng song song: chuỗi solver vật lý, HTML twin 3D,
lớp tích hợp/params/docs) + kế hoạch vá lỗi chia thành các Work Package (WP) để
giao cho các agent Sonnet chạy **song song theo phase** (mỗi WP sở hữu file riêng,
không đụng file của WP khác trong cùng phase).

> Quy ước severity: **HIGH** = số liệu/hành vi sai hoặc rủi ro bảo mật thật;
> **MED** = mâu thuẫn/mơ hồ dễ gây sai về sau; **LOW** = dọn dẹp/docs.

---

## PHẦN 1 — ĐÁNH GIÁ TỔNG QUAN

Hệ thống về cơ bản **đúng ở lõi vật lý**: đã verify lại độc lập các điểm sau —
q = ½σω²|A_φ|² đúng công thức cycle-averaged; trọng số 2πr có mặt nhất quán ở cả
stiffness/load/biên convection của EM lẫn thermal; số hạng A_φ/r²; dấu cuộn ngược;
chiều σ(T) (eddy ∝ σ, chỉ áp cho plate); I²-scaling chính xác 4.000000; energy
balance 6.7e-9%; chuyển mm→m và coercion e-notation sạch; interpolation q_e có
renormalization bảo toàn năng lượng; `dial_to_current_A` Python và JS là cùng một
phép nội suy clamped, JS đọc từ PARAMS bake từ params.yaml (đúng SSOT); levStep
closed-form ổn định vô điều kiện; romStep có substepping chống dt lớn;
fetchAmbientC có AbortController timeout (không treo); history arrays bị chặn
3600 điểm; topology mesh 4 disc variant giống hệt nhau (2160 vertices) nên swap
buffer an toàn; resetSim reset đủ node sâu (inner_deep/outer_deep/iron/air).

**Nhưng có 5 lỗi HIGH thật** (bảng dưới) + một cụm mơ hồ đầu vào cần user/lab
chốt (Phần 4).

### Bảng lỗi chính

| # | Sev | Vị trí | Lỗi |
|---|-----|--------|-----|
| H1 | HIGH | working tree `outputs/digital_twin_fem*.html` + `.claude/settings.json` | **Key Google thật đang nằm trong working tree của file được git track**; hook chặn commit chỉ soi `git diff --cached` → **`git commit -a` lọt lưới** (đúng kịch bản hiện tại: thay đổi chưa staged) |
| H2 | HIGH | `em_solver.py` (`material()` → `compute_lift_force()`, `run_rig_validation()`) | Dòng RMS (`cfg.I=5.0`) bị dùng làm **biên độ phasor** không nhân √2 → F_z thấp 2×; `run_rig_validation()` tự in kết luận sai "F_z không bracket được F_grav" (0.844N < 1.598N) dù đĩa thật bay được. Hệ quả ×2 hiện chỉ được vá tay ở caller (LEV_ANCHORS trong build_twin_html_fem) — quy ước ngầm, dễ nhân đôi hoặc quên |
| H3 | HIGH | `build_twin_html_fem.py:672-685` + JS `selectPlateVariant()` | Compare mode đa bán kính: `rom_params_v` **thiếu 6 key** (`B_max_iron, B_sat, saturated, I_em_ref, B_max, J_max`) → `Object.assign(ROM, v.rom)` giữ nguyên giá trị của đĩa cũ; telemetry J_max/B_plate trộn vật lý 2 đĩa vĩnh viễn sau khi đổi đĩa; badge bão hòa sắt (`tBmax`) chỉ chạy 1 lần lúc load, không bao giờ update |
| H4 | HIGH | `digital_twin.py:142-152` | Tên đĩa mặc định tự ghép `"Al Ø160mm"` (đường kính) không khớp `plate_library` (`"Al Ø80mm"` = bán kính) → ROM R=80 bị cache dưới nhãn `"Al Ø50mm"`, RadioButtons hiển thị sai đĩa đang active, click lần đầu vào chính nhãn đó bị no-op |
| H5 | HIGH | `README.md:33` + docs | `build_twin_html.py` **đã bị xóa** (commit 5c8598d) nhưng README/ARCHITECTURE/HANDOFF/3D_MODEL_UPDATE_PLAN/CLAUDE.md vẫn hướng dẫn chạy → lệnh fail ngay |
| M1 | MED | `params.yaml:228-234` | `plate_library` 5/6 entry dùng "Ø" cho **bán kính** ("Al Ø80mm" thực ra là đĩa Ø160mm); chỉ entry mới nhất "Al Ø202mm" đặt đúng theo đường kính — nghịch lý tên gọi lan sang UI matplotlib/sim_plates |
| M2 | MED | `build_twin_html_fem.py:650` | `PLATE_VARIANT_RADII_MM = (50,65,80,101)` hardcode, không đọc từ `plate_library` → vi phạm SSOT, sửa params không lan sang HTML |
| M3 | MED | `build_twin_html_fem.py:~2041` | Hiệu ứng hạt nhiệt so `sim.T` (init = T_AMB_JS, mặc định 29°C) với `ROM.T_amb` (=20°C vật lý) → **hạt nhiệt bốc lên từ cuộn dây lạnh ở I=0 ngay khi mở trang** (nghịch lý hiển thị) |
| M4 | MED | `build_twin_html_fem.py` lev_params vs params.yaml | z_decay **hai phương pháp fit lệch ~1.5×**: R=80 dùng 21.4mm (params.yaml, phương pháp F1/F_grav-crossing), mọi bán kính khác dùng `_lev_anchor()` F1/F5 (~13.6mm) → compare mode so "táo với cam" về độ nhạy gap theo I. Quan sát thật ("gap 7.75A chỉ nhích nhẹ") nghiêng về 13.6mm — cần quyết định (OQ-4) |
| M5 | MED | `em_solver.py:246-340` | Vòng lặp bão hòa (`solve_em_saturating`/`check_saturation`) chỉ xét `iron_core`, **bỏ qua `outer_iron_ring`** — hiện vô hại (μ_r=1) nhưng sẽ sai âm thầm nếu ring được xác nhận ferromagnetic và ai đó chỉ sửa μ_r. **[x] RESOLVED**: `solve_em_saturating` generalized 2026-07-10 (commit aa9537c, Phase C — ring được xác nhận ferromagnetic cùng ngày, xem OQ-6); `check_saturation` (hàm report riêng, bị Phase C bỏ sót) generalized 2026-07-11 bởi audit thứ hai, xem `docs/BUG_REGISTER_2026-07-11.md` B3. |
| M6 | MED | `em_solver.py:54` | `z_fine_top` không cộng `payload_model.thickness_mm` — payload dày >~10mm sẽ rơi một phần vào vùng mesh thô mà không cảnh báo |
| M7 | MED | README/ARCHITECTURE | Roadmap Phase 6a/6b vẫn `[ ]` dù đã xong; bảng size file stale |
| M8 | MED | `build_twin_html_fem.py` JS | Hardcode lẽ ra từ params: nhãn "Inner coil (1000t)"/"Outer coil (500t)" (4 chỗ, không đọc `cfg.coils.*.turns`), ngưỡng fade jitter 0.5mm, `T_COLOR_HI=125`, `CHART_WIN=600` |
| L1 | LOW | `params.yaml` | Block chết/không code nào đọc: `separator_ring` (trùng `outer_iron_ring`), `transient`, `units`; `validation_data` chỉ là tài liệu tham chiếu (calibration là hằng số tay, không auto-derive); `fill_factor: 0.6` khai báo nhưng chưa nối vào công thức (tự ghi chú đúng) |
| L2 | LOW | `thermal_solver.py:212` | `on_boundary()` dead code |
| L3 | LOW | `CLAUDE.md` | 653 dòng vs ngân sách tự đặt ~200 — tốn context mỗi session |

---

## PHẦN 2 — WORK PACKAGES CHO SONNET AGENTS

**Nguyên tắc phân chia**: mỗi WP trong cùng một phase sở hữu tập file RIÊNG
(không merge conflict → chạy song song an toàn). Phase 2 chỉ chạy sau khi
Phase 1 xong (vì đụng chung `build_twin_html_fem.py`). KHÔNG WP nào được sửa
`CLAUDE.md` trừ WPF-DOCS (tránh xung đột); mỗi WP ghi kết quả vào cuối file này
(mục "Execution log").

Chuẩn chung cho MỌI WP:
- Tuân `CLAUDE.md` (token discipline, không hardcode hằng số, secrets không commit).
- Trước khi claim xong: chạy lệnh verify của WP và dán output (verification-before-completion).
- Không commit — để user review diff.

### PHASE 1 (4 WP song song)

---

#### WP-SEC — Vá lỗ hổng hook secret + không để key thật trong file tracked
**Files sở hữu**: `.claude/settings.json` (KHÔNG đụng build_twin_html_fem.py — WP-HTML lo phần builder).
**Severity gốc**: H1 (một nửa — nửa kia ở WP-HTML).
1. Sửa hook PreToolUse `git commit *`: đổi kiểm tra `git diff --cached` →
   kiểm tra **cả** `git diff --cached` **và** `git diff HEAD` (bắt được cả
   trường hợp `git commit -a` auto-stage sau khi hook chạy). Giữ nguyên regex
   `AIzaSy[0-9A-Za-z_-]{20,}`, giữ cơ chế deny.
2. (Tùy chọn, nếu hook engine hỗ trợ) thêm hook tương tự cho `git push *`:
   grep `git log -p @{push}..HEAD -- .` (hoặc `origin/main..HEAD`) tìm cùng
   pattern, chặn push nếu key đã lỡ nằm trong commit.
**Acceptance / verify** (làm trong repo sandbox tạm ở scratchpad, KHÔNG trong repo thật):
- Tạo repo giả, file tracked chứa key giả khớp regex, KHÔNG staged →
  `git commit -a` phải bị deny.
- Staged → `git commit` bị deny (regression cũ vẫn giữ).
- Diff sạch → commit được phép.

---

#### WP-HTML — Sửa build_twin_html_fem.py: compare-mode telemetry, key gating, nghịch lý hiển thị, SSOT
**Files sở hữu**: `build_twin_html_fem.py`, `outputs/digital_twin_fem.html`,
`outputs/digital_twin_fem_R101.html`. (KHÔNG đụng params.yaml — nếu cần key
display mới trong params.yaml, phối hợp: WP-PARAMS thêm key, WP-HTML đọc bằng
`.get(key, default)` để không phụ thuộc thứ tự merge.)
**Severity gốc**: H1 (nửa builder), H3, M2, M3, M8.
1. **Key gating (H1)**: thêm flag CLI `--bake-key`. Mặc định (không flag):
   LUÔN ghi placeholder `"YOUR_KEY_HERE"` vào HTML kể cả khi `local/.env.local`
   tồn tại. Chỉ khi `--bake-key` mới nhúng key thật (dùng cho deploy local/test).
   In cảnh báo rõ khi bake key thật.
2. **Compare-mode stale telemetry (H3)**: `solve_plate_variant()` phải trả đủ
   trong `rom_params_v` mọi key mà build chính bake vào `rom_params`
   (`B_max_iron, B_sat, saturated, I_em_ref, B_max, J_max` — tính per-variant
   từ chính EM solve của variant đó, KHÔNG copy từ build chính). JS: gom block
   set badge `tBmax`/saturation (hiện chạy 1 lần lúc load, ~dòng 2472-2477)
   thành hàm `updateEmBadges()` gọi lúc init VÀ trong `selectPlateVariant()`.
3. **Hạt nhiệt lúc idle (M3)**: dòng ~2041 đổi `ROM.T_amb` → `T_AMB_JS`
   (nhất quán với mọi chỉ báo "hot" khác trong file).
4. **SSOT bán kính (M2)**: bỏ tuple hardcode `PLATE_VARIANT_RADII_MM`; derive
   từ `cfg.raw["plate_library"]` (lọc material=aluminium, thickness 3mm, unique
   `radius_mm`, sort). Chú ý: entry r=100.0 hiện có trong plate_library sẽ tự
   xuất hiện thêm nút Ø200mm — chấp nhận (đó là mục đích SSOT), nhưng verify
   mesh/telemetry với 5 variant thay vì 4.
5. **Hardcode JS (M8)**: nhãn coil "(1000t)"/"(500t)" (4 chỗ) → format từ
   `cfg.coils["inner"]["turns"]`/`["outer"]["turns"]` lúc bake. `T_COLOR_HI=125`
   → đọc `cfg.raw["levitating_disc"].get("plate_hot_display_C", 125.0)` (key do
   WP-PARAMS thêm). Ngưỡng fade jitter 0.5mm → `PARAMS.lev` (key
   `jit_fade_mm`, default 0.5). `CHART_WIN`, `N_HEAT_PARTICLES`, `N_THETA_FIELD`
   giữ nguyên literal + comment "cosmetic, cố ý hardcode".
6. Rebuild CẢ HAI file HTML (mặc định, không `--bake-key`).
**Acceptance / verify**:
- `grep -c 'AIzaSy' outputs/digital_twin_fem*.html` → 0 ở cả hai file.
- Headless Playwright cả hai file: 0 JS error; cycle qua TẤT CẢ nút disc variant
  và assert `ROM.J_max`/`ROM.B_max`/badge tBmax THAY ĐỔI theo variant (so giá
  trị baked trong `PARAMS.plate_variants[i].rom`).
- Ở I=0 sau load: không có hạt nhiệt hiển thị (kiểm tra biến `hot` === false).
- Regression: `levGapEqMm(5)` = 4.1000 (build R=80), `I_LEV_MIN` = 4.543A (R=80)
  / 6.450A (variant r=101) không đổi.

---

#### WP-PARAMS — Dọn params.yaml + sửa digital_twin.py plate matching
**Files sở hữu**: `params.yaml`, `digital_twin.py`, `sim_plates.py` (nếu cần).
**Severity gốc**: H4, M1, L1.
1. **Đổi tên plate_library theo ĐƯỜNG KÍNH thật (M1)**:
   `Al Ø100mm`(r=50), `Al Ø130mm`(r=65), `Al Ø160mm`(r=80), `Al Ø200mm`(r=100),
   `Al Ø202mm`(r=101, giữ nguyên), `Cu Ø160mm`(r=80). Thêm comment quy ước
   "Ø = đường kính, radius_mm = bán kính". Lưu ý Ø200 vs Ø202 rất gần nhau —
   ghi chú phân biệt ngay trong comment entry.
2. **digital_twin.py (H4)**: bỏ cách ghép chuỗi `default_name`; match entry
   mặc định bằng `radius_mm == cfg.geometry.plate_radius_m*1e3` (tolerance
   1e-6) **và** material — cache ROM và init RadioButtons theo entry khớp thật.
   Sau fix: mở app phải thấy "Al Ø160mm" được chọn sẵn và click "Al Ø100mm"
   (r=50) lần đầu PHẢI rebuild ROM (không còn no-op).
3. **Dọn block chết (L1)**: xóa `separator_ring:` (trùng `outer_iron_ring`).
   Thêm comment đầu `validation_data:` — "REFERENCE-ONLY: không code nào đọc;
   calibration lumped_thermal là hằng số derive tay". Block `transient:`: nối
   vào `digital_twin.py` argparse (`--dt`/`--window` default đọc từ đây) thay
   vì xóa. `units:`/`fill_factor` giữ (đã tự chú thích đúng).
4. Thêm key display cho WP-HTML: `levitating_disc.plate_hot_display_C: 125.0`
   và `levitation.jit_fade_mm: 0.5` (comment: display-only).
**Acceptance / verify**:
- `python config.py` chạy sạch, in bảng dial→I như cũ.
- `python -c` smoke: load params, assert plate_library names mới, không còn
  key `separator_ring`.
- `python digital_twin.py` smoke trên backend Agg (như CLAUDE.md mô tả WP cũ):
  không exception; assert `state["plate_name"] == "Al Ø160mm"`.
- `python sim_plates.py --no-em` chạy sạch với tên mới.

---

#### WP-DOCS — Đồng bộ tài liệu với thực tế code
**Files sở hữu**: `README.md`, `docs/ARCHITECTURE.md`, `docs/HANDOFF.md`,
`docs/3D_MODEL_UPDATE_PLAN.md`. (KHÔNG đụng CLAUDE.md trong phase này — mục
CLAUDE.md do user/main agent cập nhật cuối cùng để tránh conflict.)
**Severity gốc**: H5, M7, F9.
1. Xóa/sửa mọi tham chiếu `build_twin_html.py` như thể còn chạy được (README
   run-list + layout, ARCHITECTURE tree + bảng lệnh, HANDOFF, 3D_MODEL_UPDATE_PLAN)
   — ghi chú một dòng: "deleted 2026-07-02, superseded by build_twin_html_fem.py".
2. README roadmap: Phase 6a/6b → `[x]` (dẫn chiếu `validate_domain_size()`).
3. ARCHITECTURE: bỏ cột size file (hoặc cập nhật 853KB + ghi "sẽ drift").
4. Rà nhanh các lệnh còn lại trong README khớp thực tế (đối chiếu bảng smoke
   ở Phần 3 dưới).
**Acceptance / verify**: `grep -rn 'build_twin_html\.py' README.md docs/ | grep -v fem`
chỉ còn dòng ghi chú deletion; mọi lệnh trong README tồn tại file tương ứng.

### PHASE 2 (sau khi Phase 1 merge — 1 WP, vì đụng chung em_solver + build_twin_html_fem)

---

#### WP-PEAK — Chuẩn hóa quy ước RMS/peak trong lực nâng (H2, M5, M6, L2)
**Files sở hữu**: `config.py`, `em_solver.py`, `thermal_solver.py`,
`build_twin_html_fem.py` (phần LEV_ANCHORS/_lev_anchor), rebuild outputs.
**ĐÂY LÀ WP NHẠY CẢM NHẤT — ràng buộc cứng:**
- Quy ước hiện tại: chuỗi NHIỆT (compute_losses → hA calibration) cố ý dùng
  RMS-as-amplitude, sai số ×2 đã bị hấp thụ vào hA — **TUYỆT ĐỐI KHÔNG đổi
  P_plate/P_coil/q_e** (P_plate(5A) phải giữ 9.67W, P_coil 128.17W).
- Chuỗi LỰC hiện phải nhân tay ×2 ở caller (LEV_ANCHORS được tính với hệ số này).
1. `config.py`: thêm property `I_peak = I * sqrt(2)` (+ docstring quy ước).
2. `em_solver.py`: `compute_lift_force()` và `run_rig_validation()` (và
   `_compute_B_per_element`/`check_saturation` cho B thật) dùng biên độ peak —
   cách sạch nhất: tham số `I_amplitude=None` trong solve; force path truyền
   `cfg.I_peak`, loss path giữ `cfg.I` nguyên trạng. Xóa các hệ số `*2.0` vá
   tay ở MỌI caller lực (grep toàn repo `2.0` quanh F_z, `_lev_anchor`,
   LEV_ANCHORS trong build_twin_html_fem.py, docstrings) — kiểm tra KHÔNG
   double-correction: giá trị anchor sau refactor phải khớp số cũ đã đúng
   (F(5A,1mm)≈1.85N, z_eq≈4.1mm, I_min_lev(r101)=6.45A).
3. `run_rig_validation()` sau fix phải bracket được F_grav và in z_eq≈4.1mm.
4. **M5**: `solve_em_saturating`/`check_saturation` thêm guard: nếu
   `outer_iron_ring.mu_r > 5` mà vòng saturation không xét region này → in
   WARNING rõ ràng (hoặc generalize vòng lặp cho cả 2 region sắt).
5. **M6**: `z_fine_top` cộng `payload.thickness_mm` khi payload enabled.
6. **L2**: xóa dead `on_boundary()` trong thermal_solver.py.
7. Rebuild cả 2 HTML (không `--bake-key`), chạy lại Playwright regression như WP-HTML.
**Acceptance / verify**:
- `python em_solver.py` full run: I²-check pass; P_plate(5A)=9.67W KHÔNG đổi;
  `run_rig_validation()` bracket OK, z_eq≈4.1mm; benchmark z_eq≈7.1mm không đổi
  (mục PAUSED giữ nguyên trạng thái).
- `python thermal_solver.py` energy balance 0.000%.
- `python rom.py` I²-scaling 4.000000.
- HTML: `levGapEqMm(5)`=4.1000, `I_LEV_MIN` per-variant không đổi, 0 JS error.

### PHASE 3 (tùy chọn, cần user duyệt trước)

- **WP-TRIM**: tái cấu trúc CLAUDE.md (653 dòng → <250): giữ trạng thái hiện
  hành, chuyển narrative WP-A/B/C/D + lịch sử calibration sang
  `docs/CHANGELOG.md`. Chỉ chạy khi user đồng ý (CLAUDE.md là bộ nhớ nhóm).
- **WP-Z0**: hợp nhất phương pháp z_decay (M4 / OQ-4) — CHỜ user chốt (xem
  Phần 4, câu 4). Nếu chọn phương pháp F1/F5 (13.6mm): đổi
  `levitation.z_decay_mm` trong params.yaml, verify gap(7.75A) dự đoán giảm từ
  ~22.9mm xuống mức "nhích nhẹ" khớp quan sát, cập nhật comment.

### Cách chạy tự động (gợi ý cho user)

- **Song song**: trong Claude Code, spawn 4 agent Sonnet (subagent chung/
  general-purpose, `isolation: worktree` nếu muốn diff tách bạch) với prompt =
  nội dung từng WP Phase 1 ở trên + "đọc docs/AUDIT_FIX_PLAN_2026-07-04.md
  mục WP-xxx, làm đúng scope, ghi kết quả vào Execution log". Merge/review,
  rồi chạy WP-PEAK (Phase 2) một mình.
- **Loop**: `/loop` với prompt "thực hiện WP tiếp theo chưa done trong
  docs/AUDIT_FIX_PLAN_2026-07-04.md theo thứ tự phase, mỗi vòng 1 WP, chạy
  verify trước khi đánh dấu done" — chậm hơn nhưng không cần merge.

---

## PHẦN 3 — SMOKE MATRIX ENTRYPOINT (trạng thái hiện tại)

| Lệnh README | Kết quả |
|---|---|
| `python config.py` / `em_solver.py` / `thermal_solver.py` / `rom.py` | OK |
| `python digital_twin.py` | Chạy, nhưng dính H4 (nhãn đĩa sai + click no-op) |
| `python visualize.py --no-show` / `sim_plates.py` | OK |
| `python build_twin_html.py 3D_model.stl` | **FAIL — file đã xóa (H5)** |
| `python build_twin_html_fem.py [--plate-radius 101]` | OK (arg STL là no-op có chủ đích) |
| `python data_io.py --mode calibrate --csv mock_sensor_data.csv` | OK |
| `python gen_qr.py <url>` | OK (URL hosting vẫn TBD) |

requirements.txt khớp import thực tế (pyvista optional có chủ đích). `3D_model.stl`,
`mock_sensor_data.csv` tồn tại và đúng schema.

---

## PHẦN 4 — CÂU HỎI CẦN USER/LAB TRẢ LỜI (không giao cho agent)

Gộp từ `docs/PLAN_SIM_FEEDBACK_2026-07-02.md` + phát hiện mới của audit này:

1. **Gap thật ở 7.75A** (mm hoặc "×lần bề dày đĩa")? — điền `Z_OBS_7_75A_MM`
   để refit z_decay. Model hiện dự đoán ~22.9mm, quan sát nói "chỉ nhích nhẹ".
   ⚠️ **Một phần bị supersede 2026-07-10**: geometry re-measurement + iron
   confirmation đó ngày đã đổi hẳn bức tranh EM (đĩa giờ overlap iron ring),
   z_eq(5A) dự đoán nhảy 4.1mm→11.7mm — số liệu z_decay cũ (fit trên geometry
   trước đó) cần re-derive trên geometry mới trước khi dùng câu trả lời này.
   Xem thêm CLAUDE.md "LIFT FORCE" bullet + `docs/BUG_REGISTER_2026-07-11.md`
   WP-7 (bão hòa sắt đã bị loại trừ như nguyên nhân, KHÔNG giải thích được gap).
2. **Xung đột ζ (damping)**: luật ζ∝I² (neo ζ(5A)=0.02, khớp settle ~9s) chỉ
   cho ζ(7.75A)≈0.048, trong khi target overshoot <40% của chính WP-A đòi ~0.3.
   Chọn: nới target / đổi luật damping / chờ data dao động thật 7.75-8A.
3. **Data cooldown thật**: giữ 5A đến steady → cắt dòng → log IR coil mỗi 60s
   trong 20-30 phút (fit `coil_G_wind_W_per_K` + `convection_exponent` — hiện
   chỉ là order-of-magnitude).
4. **Chọn phương pháp z_decay** (M4): 21.4mm (F1/F_grav-crossing, đang dùng cho
   R=80) vs 13.6mm (F1/F5, đang dùng cho MỌI bán kính khác) — lệch 1.5× cho
   CÙNG một đĩa. Khuyến nghị của audit: quan sát ở câu 1 nghiêng về giá trị
   nhỏ (13.6mm) → nếu xác nhận, chạy WP-Z0. Data đo gap ở ≥3 mức dòng sẽ chốt
   dứt điểm. **[x] User đã chốt 2026-07-10 (WP-Z0)**: chọn 13.6mm, đã áp dụng
   trong params.yaml. Xem note "supersede" ở câu 1 — geometry đổi sau đó cùng
   ngày, decision vẫn giữ nhưng z_eq tuyệt đối đã dịch chuyển.
5. **Đĩa Ø202mm**: mô phỏng nói KHÔNG bay ở 5A (cần ≥6.45A) — có đúc đĩa thử
   thật không, hay giữ Ø160mm?
6. **Magnet test cho separator ring (r=81-101mm)** — vẫn PENDING; nếu
   ferromagnetic thì P_plate/F_z đổi mạnh (μ_r sensitivity test đã có sẵn) và
   mọi kết quả R=101 phải tính lại. **[x] RESOLVED 2026-07-10**: user re-test
   xác nhận CẢ center core LẪN outer_iron_ring đều ferromagnetic (nam châm hút);
   ring cũng được đo lại vị trí (nay r=64.9-79.9mm, không còn 81-101mm). P_plate
   và F_z đã tính lại theo geometry mới — xem CLAUDE.md "Device numbers" +
   "First quantitative result".
7. **Thứ tự nhiệt đĩa vs coil**: model hiện hòa/tie, IR thật nói coil nóng hơn
   rõ — cần thermocouple tiếp xúc đáy đĩa (h_top/h_bottom đĩa chưa calibrate).
   (Băng keo đen ε≈0.95 dán đáy đĩa là cách rẻ nhất cho IR.)
8. **Nhạy mesh EM**: fine_step 2.0→1.0mm dịch z_eq(R=80) 4.15→~3.5mm và
   I_min_lev(R=101) 6.45→6.9A — con số "validated" 4.1mm nhạy mesh hơn tưởng;
   liên đới benchmark 37% đang PAUSED. Quyết định: có mở lại điều tra không?
9. **(Mới) Khóa API key Google**: key hiện tại KHÔNG bị giới hạn
   referrer/IP — vào Google Cloud Console thêm restriction (hoặc đổi key
   project-scoped) trước khi ship/host file HTML.

---

## EXECUTION LOG (agent ghi vào đây)

| WP | Agent/model | Trạng thái | Verify output (tóm tắt) | Ngày |
|----|-------------|-----------|--------------------------|------|
| WP-SEC | Sonnet (parallel, shared tree) | DONE | Hook giờ check cả `git diff --cached` và `git diff HEAD`. Verified trong sandbox (`scratchpad/hook_test`): unstaged key → deny (bug cũ đã tái hiện và fix); staged → deny (regression); clean → allow. Side-finding: xác nhận độc lập lần nữa `outputs/digital_twin_fem.html` có key thật trong unstaged diff tại thời điểm chạy. Chỉ sửa `.claude/settings.json`. | 2026-07-10 |
| WP-HTML | Sonnet (parallel, shared tree) | DONE | (1) `--bake-key` flag thêm, mặc định ghi `YOUR_KEY_HERE`; verified `grep -c AIzaSy` = 0 cả 2 file. (2) `solve_plate_variant()` giờ tính đủ 6 key thiếu (B_max_iron/B_sat/saturated/I_em_ref/B_max/J_max) per-variant; `updateEmBadges()` gọi cả lúc load lẫn trong `selectPlateVariant()`; verified cycling 5 variant → ROM.J_max đổi đúng khớp PARAMS baked. (3) hot-particle check đổi `ROM.T_amb`→`T_AMB_JS`; verified hot=false lúc I=0. (4) `PLATE_VARIANT_RADII_MM` hardcode xoá, derive từ plate_library → 5 variant (50/65/80/100/101mm) thay vì 4. (5) nhãn turns/T_COLOR_HI/jit_fade_mm đọc từ PARAMS/.get(default). (6) Rebuild cả 2 HTML (không --bake-key) — 0 JS error qua Playwright headless, regression levGapEqMm(5)=4.1000/I_LEV_MIN=4.543A(R80)/6.450A(R101) không đổi. Re-rebuilt lần cuối bởi orchestrator SAU khi WP-PARAMS xong để đảm bảo params.yaml final state (tên plate mới) được bake đúng — cả 2 file lại pass key-check=0. Chỉ sửa build_twin_html_fem.py + 2 file HTML output. | 2026-07-10 |
| WP-PARAMS | Sonnet (parallel, shared tree) | DONE | plate_library đổi tên theo đường kính thật (Ø100/130/160/200/202mm + Cu Ø160mm); thêm comment quy ước Ø=đường kính + cảnh báo Ø200 vs Ø202. digital_twin.py: match plate mặc định bằng radius_mm+material (tolerance 1e-6) thay vì string ghép sai — verified suptitle "Al Ø160mm" đúng. Xoá `separator_ring:` (grep xác nhận không code nào đọc). Thêm comment REFERENCE-ONLY cho validation_data. Wire `transient:` (dt_s/t_end_s) vào digital_twin.py argparse --dt/--window (trùng giá trị hardcode 1.0/600.0 cũ). Thêm `levitating_disc.plate_hot_display_C=125.0` + `levitation.jit_fade_mm=0.5`. Verify: config.py sạch, smoke test tên mới, Agg-backend run_live() 0 exception, sim_plates.py --no-em sạch. Chỉ sửa params.yaml + digital_twin.py (sim_plates.py không cần sửa — đã generic). | 2026-07-10 |
| WP-DOCS | Sonnet (parallel, shared tree) | DONE | Sửa 6/6 tham chiếu `build_twin_html.py` thành ghi chú deletion (README:37,56; ARCHITECTURE:24,153; HANDOFF:78; 3D_MODEL_UPDATE_PLAN:102). README Phase 6a/6b → [x] (dẫn `validate_domain_size()` xác nhận tồn tại). ARCHITECTURE file-size table: bỏ dòng chết, thêm ghi chú "sizes drift". Verify: grep còn lại 100% là ghi chú lịch sử, không còn dòng đọc như lệnh chạy được. Chỉ sửa 4 file docs, KHÔNG đụng CLAUDE.md (xác nhận). Flag thêm (chưa sửa, ngoài scope): `docs/ARCHITECTURE.md`'s Generated-files tree (~line 47) vẫn còn 1 dòng nhắc `digital_twin.html` cũ, có thể cũng nên dọn sau. | 2026-07-10 |
| WP-PEAK | Sonnet (solo, sau Phase 1) | DONE | `config.I_peak` mới; `material/solve_em/solve_em_saturating/compute_lift_force` thêm `I_amplitude` (default None = hành vi cũ y hệt); `run_rig_validation()` giờ bracket được F_grav, in z_eq=4.1mm (plate bottom) + visible gap=7.1mm MATCH; `run_benchmark_validation()` KHÔNG đổi (z_eq=7.1mm y hệt, đã verify). `check_saturation` thêm `B_scale` (mặc định 1.0 không đổi hành vi nội bộ Picard loop); 3 call site báo cáo (`em_solver.py __main__`, 2 chỗ trong `build_twin_html_fem.py`) dùng `B_scale=cfg.I_peak/cfg.I` → "MAX B in iron" 0.033T→0.047T (đúng ×√2). `_lev_anchor()` bỏ hack mutate `current_A`, dùng `I_amplitude=cfg.I_peak` sạch — verify lại từng field khớp 100% với `LEV_ANCHORS` cache cũ. M5: thêm WARNING guard nếu `outer_iron_ring.mu_r>5` mà Picard loop không xét (hiện vô hại vì mu_r=1). M6: `z_fine_top` cộng `payload.thickness_mm`. L2: xoá `on_boundary()` chết. Verify: `P_plate(5A)=9.6727W`/`P_coil=128.169W` bit-identical; I²=4.000000; energy balance 0.000%; cả 2 HTML rebuild + Playwright: `levGapEqMm(5)=4.1`, `I_LEV_MIN` đúng cả 2 build, 0 JS error. **Side-finding ngoài scope**: `validate_domain_size()` hiện FAIL (2.71% > 1% tolerance) — reproduce lại trên bản HEAD chưa sửa, xác nhận đây là vấn đề CÓ TRƯỚC WP-PEAK (không phải do thay đổi hôm nay), nhưng khiến CLAUDE.md's "PASS <0.06%" claim bị stale — cần re-verify domain size ở phiên sau. | 2026-07-10 |
| WP-TRIM | Sonnet (solo, sau user duyệt) | DONE | CLAUDE.md 780→224 dòng (dưới ngưỡng 250). Toàn bộ narrative lịch sử (mọi session render-fix, 2 vòng calibration, WP-A/B/C/D/PEAK) chuyển nguyên vẹn sang `docs/CHANGELOG.md` (651 dòng, không mất thông tin). "Code status" trong CLAUDE.md giờ chỉ còn current-state compact (1 đoạn/component + pointer sang CHANGELOG). Tiện thể sửa luôn: CURRENT CONVENTION bullet cập nhật theo API `cfg.I_peak` mới (WP-PEAK), bỏ hướng dẫn "×2.0 thủ công" đã lỗi thời; Real-rig validation section rút gọn (giữ số liệu cuối, bỏ narrative 2 vòng); sửa 1 chỗ tham chiếu `build_twin_html.py` sót lại trong CLAUDE.md (WP-DOCS trước đó chỉ sửa README/docs/, không đụng CLAUDE.md). | 2026-07-10 |
| WP-Z0 | Sonnet (solo, sau user chốt OQ-4) | DONE | User chọn phương pháp F1/F5 (13.6mm) qua AskUserQuestion — xác nhận quan sát thực tế rig "gap chỉ nhích nhẹ" ở 7.75A khớp giá trị nhỏ hơn. Đổi `levitation.z_decay_mm` 21.4→13.6 trong params.yaml (kèm comment giải thích quyết định), cập nhật fallback default trong `lev_params()` Python + comment JS liên quan. Verify: z_eq(7.75A) dự đoán giảm đúng như tính tay: 22.86mm→16.02mm; `levGapEqMm(5)`=4.1 KHÔNG đổi (đúng, vì z_gap_5A_mm không đổi); `I_LEV_MIN`(R80) đổi 4.543→4.300A (ĐÚNG NHƯ MONG ĐỢI — hệ quả tất yếu của đổi z_decay, không phải regression); `I_LEV_MIN`(R101)=6.450A KHÔNG đổi (đúng, dùng anchor riêng qua `_lev_anchor()`, không phụ thuộc z_decay của R=80). Cả 2 HTML rebuild, 0 JS error. | 2026-07-10 |

| AUDIT-0711 | Sonnet (solo, second-pass audit) | DONE | User nghi ngờ 2026-07-10/11 updates (geometry re-measure, iron confirm, Phase A-D) gây lỗi. 3 Explore agent song song (EM chain/thermal-ROM chain/HTML+docs) trước khi sửa. Kết quả đầy đủ: `docs/BUG_REGISTER_2026-07-11.md`. Tóm tắt: 1 bug số liệu thật (Phase B's hA refit dùng sai công thức AIR_DT_SS, đã fix hA_inner 3.0605→2.9493/hA_outer 3.5986→3.4509, verify tay khớp 79.00/74.00°C); 2 lỗi latent trong em_solver.py (`compute_losses` iron-ring loss có thể bị rơi nếu core disabled; `check_saturation` không generalize theo ring như Phase C đã làm cho solver) — cả hai fix, verify P_plate/P_iron/P_coil bit-identical trước/sau; sweep comment stale (M5 dòng trên, radii cũ, quy ước ×2.0 cũ). WP-6 (test coil_C_scale, giữ nguyên, RMS=2.56°C) + WP-7 (thêm `saturating=` kwarg cho `compute_lift_force`, thí nghiệm cho thấy bão hòa KHÔNG giải thích được lift-force mismatch — F_z đổi <0.1%, z_eq bất biến 11.75mm) đều report-only, không đổi default. Rebuild `outputs/digital_twin_fem.html` sau fix hA. Đánh dấu OQ-6 resolved, note OQ-1/OQ-4 partial-supersede ở trên. CLAUDE.md/CHANGELOG.md đồng bộ. Verify: I²=3.998, energy balance 0.000%, ROM I²=4.000000, domain validation PASS. | 2026-07-11 |

**Ghi chú vận hành**: cả 4 WP chạy song song TRỰC TIẾP trên cùng working tree (không dùng `git worktree` isolation) vì file ownership của Phase 1 hoàn toàn rời nhau (đã verify trước khi chạy: WP-HTML không đụng params.yaml, WP-PARAMS không đụng build_twin_html_fem.py, v.v.) — không có merge conflict nào xảy ra, `git diff --stat` sau khi cả 4 xong khớp chính xác với union các file mỗi WP tự báo cáo. Điểm phụ thuộc duy nhất (WP-HTML's SSOT-radii đọc params.yaml lúc build) được thiết kế để không phụ thuộc thứ tự (derive theo `radius_mm` giá trị, không theo `name` string) — verify lại: orchestrator rebuild HTML một lần cuối sau khi tất cả 4 WP báo DONE để loại trừ hoàn toàn race-condition nghi ngờ, kết quả không đổi.