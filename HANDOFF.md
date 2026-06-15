# HANDOFF — Digital Twin nhiệt TEAM 28

> **Nguồn sự thật chính là [CLAUDE.md](CLAUDE.md) + [README.md](README.md).**
> File này chỉ tóm tắt nhanh trạng thái bàn giao. Cập nhật: 2026-06-15.

## Mục tiêu
Digital twin dự đoán **trường nhiệt độ real-time** của tấm nhôm trên hệ nâng
điện động TEAM 28 (TEMF). Validate với thiết bị thật → trực quan 3D → AR app → QR.

## Quyết định kiến trúc (đã chốt)
- **Không FEMM** (máy dev macOS). Pure Python: `numpy + scipy + pyyaml + matplotlib`
  (+ `trimesh` cho GLB). Bài toán **đối xứng trục** → giải 2D (r,z), quay thành 3D.
- **Real-time:** tổn hao ~ I², phân bố cố định → giải FEM 1 lần ở I_ref=5A,
  online chỉ nhân (I/I_ref)². Đã kiểm chứng I²-scaling = 4.000000.
- Mọi tham số trong [params.yaml](params.yaml). Code nằm **phẳng ở repo root**.

## Số liệu thiết bị (trong params.yaml)
- Tấm nhôm: **R=80mm (Ø16cm)**, dày 3mm (placeholder — cần ĐO lại), σ=3.4e7 S/m.
- Dòng: **î = 5 A** vận hành, f = 50 Hz (benchmark gốc dùng 20A).
- Số vòng: **inner=1000, outer=500**.
- **Có lõi sắt** (μ_r=1000, placeholder geometry — CẦN xác nhận với rig thật).
- payload_model (đĩa thép): placeholder, **tắt mặc định**.

## Trạng thái (đã xong gần hết)
- [x] config.py, params.yaml, thermal_solver.py (energy balance 0.000%)
- [x] em_solver.py — eddy AC + lift force, benchmark **z_eq=10.9mm vs 11.3mm (3.5%)**
- [x] rom.py — ROM real-time (I² + transient τ≈3.4 phút + σ(T))
- [x] digital_twin.py — twin tương tác (slider I, chọn tấm, kịch bản)
- [x] visualize.py — revolve 2D→3D, export plate.glb
- [x] sim_plates.py — so sánh các tấm trong plate_library
- [x] build_twin_html.py — Phase 5: digital_twin.html standalone (double-click chạy)
- [ ] data_io.py — đọc sensor CSV → calibrate_UA() (**chờ dữ liệu nhiệt thật**)

## Validation
1. EM tái tạo benchmark gốc (960/576, 20A, R=65mm, no iron) → lực cân bằng z≈11.3mm. ✓
2. Đổi sang rig (1000/500, iron, 5A) → loss maps.
3. Loss → thermal → trường T. **Validate nhiệt với cảm biến: khi có dữ liệu.**

## Lệnh chạy — xem [README.md](README.md) (lưu ý: `python config.py`, KHÔNG phải `src/`).
