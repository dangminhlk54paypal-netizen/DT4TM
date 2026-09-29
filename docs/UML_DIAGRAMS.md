# DT4TM — System UML Diagrams

> **Dự án:** Thermal Digital Twin cho Hệ Thống Nâng Điện Từ (Electrodynamic Levitator - TEAM 28)
> **Tài liệu:** Tổng hợp UML Diagrams (Sơ đồ Kiến trúc, Sơ đồ Lớp, Sơ đồ Tuần tự, Sơ đồ Trạng thái và Sơ đồ Dòng Dữ liệu)
> **Ngày cập nhật:** 2026-08-12

---

## 1. Sơ Đồ Thành Phần & Kiến Trúc Hệ Thống (System Component Diagram)

Sơ đồ mô tả cấu trúc phân tầng của hệ thống DT4TM, từ lớp Cấu hình (Single Source of Truth), lớp Mô phỏng Vật lý FEM (Offline), lớp Mô hình Thu nhỏ (ROM), Động cơ Tích phân Thời gian Thực SSOT (`twin_core.py`), đến các giao diện đầu ra (Matplotlib, Web AR, PyVista) và Tích hợp Phần cứng (Arduino Sensor).

```mermaid
flowchart TD
    subgraph Config["Configuration & SSOT"]
        P["params.yaml"] --> C["config.py: Raw Params"]
        C --> CC["Config Class: Coerced SI Units"]
    end

    subgraph Offline["Offline Multi-Physics FEM Engine"]
        CC --> EM["em_solver.py: Geometry, Materials, Excitation"]
        EM --> LM["Loss Map q_r_z & Lift Force F_z"]
        LM --> TH["thermal_solver.py: Mesh Interpolation LinearND"]
        TH --> TF["FEM Temperature Field T_fem_r_z"]
    end

    subgraph ROM["Model Order Reduction (ROM)"]
        TF --> RP["rom.py: Spatial Mode Extraction"]
        RP --> TR["ThermalROM: Rank-1 Modal Ansatz"]
    end

    subgraph SSOT["SSOT Real-Time Integration Core"]
        TR --> TM["twin_model.py: PlateCache & Variant Assembly"]
        TM --> TC["twin_core.py: RomCoeffs, LumpedCoeffs, LevCoeffs"]
        TC --> TS["TwinState Integrator: Sub-stepped Euler & Analytical Levitation"]
    end

    subgraph UI["Presentation & UI Outputs"]
        TS --> DT["digital_twin.py: Interactive Matplotlib GUI"]
        TS --> PYV["extensions/digital_twin_pyvista.py: Desktop 3D VTK Viewer"]
        TM --> BT["build_twin_html_fem.py: HTML Generator"]
        BT --> HTML["outputs/digital_twin_fem.html: Web AR Twin"]
        VIS["visualize.py"] --> GLB["outputs/plate.glb: 3D CAD Exporter"]
        QR["gen_qr.py"] --> PNG["outputs/qr_digital_twin.png: AR Access QR"]
    end

    subgraph Hardware["Hardware & Sensor Pipeline"]
        ARD["arduino/thermal_sensor.ino"] --> CSV["Serial CSV Stream 1Hz: T_core, T_disc, I_rms"]
        CSV --> DIO["data_io.py: SensorReader & calibrate_from_file"]
        DIO -.-> TR["ThermalROM: Calibrate UA"]
        
        VAL["params.yaml: validation_data"] --> REF["refit_hA.py: Coil Network Calibration"]
        REF --> P2["params.yaml: Update hA_inner/outer"]
    end

    subgraph Testing["Verification & Regression Testing"]
        XVAL["xval_twin.py: Bit-for-bit Parity Test 1e-9"] -.-> TC
        XVAL -.-> HTML
    end
```

---

## 2. Sơ Đồ Lớp & Cấu Trúc Module (Class & Module Diagram)

Sơ đồ lớp chi tiết thể hiện các đối tượng chính trong hệ thống Python, các Dataclass lưu trữ hệ số vật lý, và mối quan hệ giữa chúng. (Lưu ý: `em_solver`, `thermal_solver`, `twin_model` và `digital_twin` đều là module chứa hàm/dataclass độc lập — không có class kiểu "controller/app" nào bọc chúng; đã đối chiếu trực tiếp với source ngày 2026-08-12).

```mermaid
classDiagram
    class Geometry {
        +float plate_radius_m
        +float plate_thickness_m
        +float plate_z_bottom_m
    }

    class Config {
        +dict raw
        +Geometry geometry
        +float I
        +float I_peak
        +float I_ref
        +float freq
        +float omega
        +float power_ref_W
        +float total_power_W
        +dial_to_current_A(dial) float
        +dial_to_voltage_V(dial) float
    }

    namespace em_solver_py {
        class em_solver_functions {
            +solve_em(cfg) Tuple
            +solve_em_saturating(cfg) Tuple
            +compute_losses(cfg, res) Dict
            +compute_lift_force(cfg, res) float
            +check_saturation(res) float
        }
    }

    namespace thermal_solver_py {
        class thermal_solver_functions {
            +solve_steady(cfg, em_losses) Tuple
            +_interp_em_losses(em_losses, rc_e, zc_e) ndarray
            +energy_balance(res) float
        }
    }

    class ThermalROM {
        +Config cfg
        +float tau
        +float dT_mean_ref
        +ndarray dT_ref
        +float alpha
        +build(cfg, em_losses) ThermalROM
        +simulate(I_of_t, t_arr) Tuple
        +T_steady(I) ndarray
        +_sigma_scale(dT_mean_K) float
    }

    class RomState {
        +float beta
        +float beta_eddy
        +float beta_air
    }

    class LumpedState {
        +Dict~str, float~ T
        +at_ambient(T_amb) LumpedState
    }

    class LevState {
        +float z
        +float v
        +float jit
        +float jitPhase1
        +float jitPhase2
        +float jitLevPhase1
        +float jitLevPhase2
    }

    class TwinState {
        +RomCoeffs rom
        +LumpedCoeffs lumped
        +LevCoeffs lev
        +float T_amb
        +float current_clamp_A
        +float t
        +RomState rom_state
        +LumpedState lumped_state
        +LevState lev_state
        +step(I, dt) None
        +reset() None
        -_rom_step(I, dt) None
        -_lev_step(I, dt) None
    }
    note for TwinState "KHÔNG có _lumped_step() riêng: _rom_step()\ntự làm cả (a) mạng RC 5-nút inner/outer/iron/air\nLẪN (b) cập nhật dual-beta disc trong 1 hàm.\nstep() sub-step _rom_step() n_sub lần với I đã\nclamp, rồi gọi _lev_step() ĐÚNG 1 lần với dt đầy\nđủ và I CHƯA clamp — xem trình tự thật ở mục 3.2."

    class ActivePlate {
        +str name
        +dict spec
        +List~str~ plate_names
        +bool is_synthetic
    }

    class PlateVariant {
        +float radius_mm
        +ndarray V
        +ndarray dTe
        +ndarray dTa
        +ndarray Je
        +RomCoeffs rom
        +LevCoeffs lev
        +float P_plate_W
        +object field_lines
    }

    class PlateCache {
        -Config _cfg_base
        -dict _em_base
        -Dict~str, object~ _cache
        +__contains__(name) bool
        +get(name) object
        +get_or_build(name, plate_lib, verbose) object
    }
    note for PlateCache "Cache NHIỀU ROM theo tên tấm (đĩa) được chọn,\nkhông phải một bộ (rom,lumped,lev) cho một Config\nduy nhất — không có method from_config()."

    class twin_model_functions {
        +resolve_active_plate(cfg) ActivePlate
        +i_max_for(cfg) float
        +coeffs_from_live(cfg, em, rom) Tuple
        +build_plate_variant(base_cfg, radius_mm, z_disc_bot_mm) PlateVariant
    }

    class SensorReader {
        +str port
        +int baudrate
        +read_stream()
        +save_csv(filepath, duration_s)
        +load_csv(filepath)$ DataFrame
    }

    class digital_twin_functions {
        +run_live(...) None
    }
    note for digital_twin_functions "digital_twin.py là script thủ tục, KHÔNG có\nclass nào (không có DigitalTwinApp/TwinModel)."

    Config "1" --o "1" Geometry
    TwinState "1" *-- "1" RomState
    TwinState "1" *-- "1" LumpedState
    TwinState "1" *-- "1" LevState
    twin_model_functions ..> ActivePlate : trả về
    twin_model_functions ..> PlateVariant : trả về
    twin_model_functions ..> PlateCache : dùng
    digital_twin_functions ..> TwinState : điều khiển
    digital_twin_functions ..> twin_model_functions : dùng
```

---

## 3. Sơ Đồ Tuần Tự (Sequence Diagrams)

### 3.1. Quy Trình Khởi Tạo & Tính Toán Offline FEM / ROM (Phase 1)

Quy trình giải bài toán trường điện từ AC Phasor, tính toán tổn hao Joule, truyền bản đồ tổn hao sang lưới nhiệt, và trích xuất mô hình thu nhỏ ROM.

```mermaid
sequenceDiagram
    autonumber
    actor User as "User / Script"
    participant C as "config.py (Config)"
    participant EM as "em_solver.py"
    participant TH as "thermal_solver.py"
    participant ROM as "rom.py (ThermalROM)"

    User->>C: Load params.yaml
    C-->>User: Return Config Instance (SI units)
    
    User->>EM: solve_em_saturating(cfg)
    activate EM
    note over EM: 1. Build 2D (r,z) Axisymmetric P1 FEM Mesh<br/>2. Assemble Complex Sparse Matrix K(j*omega*sigma)<br/>3. Picard Fixed-Point Iteration for Iron Saturation B-H
    EM-->>User: Return res (A_phi Phasor Solution)
    deactivate EM

    User->>EM: compute_losses(cfg, res)
    EM-->>User: Return em_losses dict (P_plate, q_e, P_coil, P_iron)

    User->>ROM: ThermalROM().build(cfg, em_losses)
    activate ROM
    ROM->>TH: solve_steady(cfg_ref, em_losses)
    activate TH
    note over TH: 1. Interpolate EM Loss Map -> Thermal Mesh (LinearND)<br/>2. Assemble Real Sparse Conductance Matrix K_th<br/>3. Apply Convective (Robin) Boundary Conditions<br/>4. Solve K_th * T = F
    TH-->>ROM: Return res_ref (T_fem Field Solution)
    deactivate TH
    note over ROM: 1. Extract Spatial Mode: dT_ref = T_fem - T_amb<br/>2. Compute tau, dT_mean_ref
    ROM-->>User: Return ThermalROM Instance
    deactivate ROM
```

---

### 3.2. Vòng Lặp Tích Phân Thời Gian Thực (Phase 2 Runtime - TwinState Integration)

Vòng lặp tính toán thời gian thực. **Không phải 3 bước "song song, đối xứng"**: `_rom_step` gộp CẢ dual-$\beta$ disc LẪN mạng RC 5-nút trong một hàm và bị sub-step nhiều lần với dòng điện đã clamp; `_lev_step` chỉ chạy 1 lần/step, với `dt` đầy đủ và dòng điện KHÔNG clamp, sau khi toàn bộ sub-step trên đã chạy xong (`twin_core.py` tự đánh số các điểm dễ nhầm này là "trap 1"–"trap 9").

```mermaid
sequenceDiagram
    autonumber
    participant UI as "GUI / AR Web Canvas"
    participant TS as "TwinState"

    UI->>TS: step(I, dt)
    activate TS
    note over TS: n_sub = ceil(dt / (tau*0.05)), dt_sub = dt / n_sub

    loop n_sub lần (sub-stepped Forward Euler)
        note over TS: I_clamped = clamp(I, 0, current_clamp_A) -- trap 8
        rect rgb(240, 248, 255)
            note over TS: (a) sigma_scale(dT_mean) dùng beta CỦA BƯỚC TRƯỚC, chưa phải beta mới (trap 2)
            TS->>TS: s = rom.sigma_scale(dT_mean)
        end
        rect rgb(255, 248, 240)
            note over TS: (b) Vòng lặp 5 node inner/outer/iron/air:<br/>mỗi coil đọc T_air CŨ (trap 4), rồi hA_eff(hA, dT, dT_cal, conv_exp) phi tuyến
            TS->>TS: for node in [inner, outer, iron]: cập nhật T_node (+ node_deep nếu có G_wind)
            TS->>TS: T_air += (Qconv - hA_far times T_air minus T_amb) / C_air * dt_sub (SAU vòng lặp trên -- trap 4)
        end
        rect rgb(240, 255, 240)
            note over TS: (c) beta_eddy/beta_air tiến về mục tiêu, dùng T_inner/T_outer MỚI vừa tính ở (b) (trap 1)
            TS->>TS: beta = f_eddy*beta_eddy + f_air*beta_air
        end
    end

    note over TS: _lev_step gọi ĐÚNG 1 LẦN, dt đầy đủ, I CHƯA clamp,<br/>sau khi t đã được cộng dồn bởi các sub-step ở trên (trap 7/9)
    rect rgb(230, 255, 230)
        note over TS: Lời giải đóng dao động tắt dần bậc 2 (underdamped closed-form),<br/>cộng thêm sub-liftoff jitter / (nếu bật) shimmer khi đang bay
        TS->>TS: _lev_step(I, dt) cập nhật lev_state (z, v, jit, jitPhase1/2, jitLevPhase1/2)
    end

    TS-->>UI: Return (State Updated)
    deactivate TS

    UI->>UI: Render 2D Heatmap / Revolve 3D Mesh / Update AR Overlay
```

---

### 3.3. Quy Trình Hiệu Chỉnh Phần Cứng (Phase 3 Hardware Calibration)

Quy trình hiệu chỉnh chia làm 2 luồng độc lập: Hiệu chỉnh mô hình đĩa (ROM UA) thông qua dữ liệu CSV thời gian thực, và Hiệu chỉnh mạng nhiệt cuộn dây (Coil Network) thông qua dữ liệu chuẩn (validation_data).

```mermaid
sequenceDiagram
    autonumber
    
    box rgb(245, 245, 255) Disc ROM Calibration (data_io.py)
    actor Sensor as "Arduino (MAX31855)"
    participant IO as "data_io.py (SensorReader)"
    participant ROM as "rom.py (ThermalROM)"
    
    Sensor->>IO: Serial Stream CSV cols t, T_core, T_disc, I_rms
    IO->>IO: save_csv() & load_csv()
    IO->>IO: calibrate_from_file()
    IO->>ROM: calibrate_UA(I_meas, dT_meas)
    ROM-->>IO: Return Optimized UA
    end

    box rgb(255, 245, 245) Coil Network Calibration (refit_hA.py)
    participant OPT as "refit_hA.py (fsolve)"
    participant CORE as "twin_core.py (TwinState)"
    participant CFG as "params.yaml"

    OPT->>CFG: Read I_CAL, T_INNER_TARGET, T_OUTER_TARGET
    activate OPT
    OPT->>CORE: Run TwinState 600,000s with trial (hA_inner, hA_outer)
    CORE-->>OPT: Return T_inner_sim, T_outer_sim
    OPT->>OPT: Compute Residuals (Sim - Target) via scipy.optimize.fsolve
    OPT-->>CFG: Print/Update Calibrated hA_inner_W_per_K, hA_outer_W_per_K
    deactivate OPT
    end
```

---

## 4. Sơ Đồ Trạng Thái (State Diagrams)

### 4.1. Trạng Thái Vận Hành Của Digital Twin (`TwinState Lifecycle`)

> ⚠️ Đây là góc nhìn khái niệm (conceptual) để minh hoạ hành vi liên tục của các ODE trong
> `TwinState`, **không phải một FSM/enum thật trong code** — không có `State` class hay
> `if state == ...` nào trong `twin_core.py`. `Overheat_Warning` bên dưới cũng không phải
> một ngưỡng cứng trong code; nó minh hoạ cho `current_clamp_A` (mặc định 20.0 A trong
> `TwinState`, [twin_core.py](../twin_core.py)) và ghi chú của CLAUDE.md: *"Raise it (e.g.
> 20A) only for an exaggerated heating demo"*.

```mermaid
stateDiagram-v2
    [*] --> Uninitialized : Program Start / Load Config
    
    Uninitialized --> Idle_Cold : Initialize TwinState (t=0, T=T_amb, z=0)
    
    state Operational {
        Idle_Cold --> Quickstart_Ramp : Apply Current I > 0 (Quickstart Scenario)
        Quickstart_Ramp --> Heating_Levitating : Ramp Reaches Target Current I_set (e.g. 5A)
        
        state Heating_Levitating {
            [*] --> Transient_Heating : Heat accumulates in Plate & Coils
            Transient_Heating --> Steady_State : t > 3*tau (dT/dt ~ 0, T_coil ~ 79°C @7.8A)
            Steady_State --> Overheat_Demo : I_set > 5A operating point, up to current_clamp_A=20A (Exaggerated Demo, không phải cảnh báo vật lý thật)
            Overheat_Demo --> Steady_State : Current Reduced to 5A
        }

        Heating_Levitating --> Natural_Cooldown : Power Cut (I = 0A)
        Natural_Cooldown --> Idle_Cold : T_nodes approach T_amb (t > 5*tau_cool)
    }

    Operational --> Idle_Cold : Reset Simulation
```

---

### 4.2. Trạng Thái Cơ Học Nâng (Levitation Mechanics States)

> ⚠️ Góc nhìn khái niệm, không phải FSM thật (xem caveat ở 4.1). Ba điểm cần đọc kèm:
> 1. `I_liftoff` **không phải hằng số cố định** — nó là `LevCoeffs.I_lev_min =
>    5·exp(-z_gap_5A_mm / (2·z_decay_mm))`, tính từ tham số hình học/độ suy giảm
>    ([twin_core.py:291](../twin_core.py#L291)); ~2.5A chỉ là giá trị xấp xỉ ở bộ tham số mặc định.
> 2. `z_eq (~11.7mm)` **CHƯA được validate** — CLAUDE.md mục "OPEN QUESTIONS" ghi rõ lệch
>    ~7mm so với khe hở đo thực tế (7–8mm), nghi do `mu_r=1000` (đặt tạm, chưa đo) — không
>    nên coi số này là đã kiểm chứng.
> 3. `Shimmer_Hovering`: với tham số mặc định hiện tại `lev_ripple_display_gain = 0.0`
>    (đã tắt từ WP-SHIMMER V2, xem `docs/physics.md` §11 "SUPERSEDED same day") nên trạng
>    thái này **không tạo rung hiển thị nào** — chỉ còn rung sub-liftoff (`jit_contact`,
>    trạng thái `Sub_Liftoff_Jitter`) là còn hoạt động theo mặc định.

```mermaid
stateDiagram-v2
    [*] --> Resting_On_Coil : I = 0A (z = 0mm)
    
    Resting_On_Coil --> Sub_Liftoff_Jitter : 0 < I < I_lev_min (formula-based, ~2.5A ở tham số mặc định)
    note right of Sub_Liftoff_Jitter
        F_lift < F_gravity
        Plate stays on frame with 50Hz micro-vibration (jitter)
    end note
    
    Sub_Liftoff_Jitter --> Liftoff_Transition : I >= I_lev_min (F_lift > F_gravity)
    
    state Liftoff_Transition {
        [*] --> Underdamped_Oscillation : Transient overshoot
        Underdamped_Oscillation --> Stable_Hovering : Damping zeta settles z(t) -> z_eq (~11.7mm, CHƯA validated)
    }

    Stable_Hovering --> Shimmer_Hovering : Main frequency AC current ripple (jit_lev, gain=0.0 mặc định = không hiển thị)
    Shimmer_Hovering --> Liftoff_Transition : Step change in Current I
    Liftoff_Transition --> Resting_On_Coil : Power OFF (I = 0A, Gravity drop)
```

---

## 5. Sơ Đồ Hoạt Động & Dòng Dữ Liệu (Data Flow & Activity Diagram)

Sơ đồ thể hiện sự chuyển hóa giữa **Chuỗi Tính Toán Tốn Chi Phí (Offline Heavy Computation Pipeline)** và **Chuỗi Thời Gian Thực (Online Real-time Execution Pipeline)**.

```mermaid
flowchart TD
    subgraph OFFLINE_FEM["1. Heavy Offline FEM Pipeline (scipy/numpy)"]
        A["params.yaml"] --> B["config.py: Parse & Coerce Params"]
        B --> C["em_solver.py: Assemble P1 Galerkin Complex Matrix K_em"]
        C --> D{"Iron Saturation?"}
        D -- Yes --> E["Picard Fixed-Point B-H Iteration"]
        D -- No --> F["Direct Sparse Solve: spsolve K_em * A = F"]
        E --> F
        F --> G["Compute Joule Loss Map q_e r,z & Lorentz Force F_z"]
        G --> H["rom.py: ThermalROM.build"]
        H --> I["thermal_solver.py: Interpolate Loss Map onto Thermal Mesh"]
        I --> J["Direct Sparse Solve: spsolve K_th * T = F_th"]
        J --> K["rom.py: Extract Rank-1 Spatial Mode dT_ref & Time Constant tau"]
    end

    subgraph ONLINE_RUNTIME["2. Light Online Real-time Pipeline (twin_core.py)"]
        K --> L["Pack Coefficients into RomCoeffs, LumpedCoeffs, LevCoeffs"]
        L --> M["Initialize TwinState"]
        N["User Input / Dial / Scenario I_t"] --> O["TwinState.step I, dt"]
        M --> O
        O --> P["Sub-stepped Euler: Dual-beta Disc ODE"]
        O --> Q["Sub-stepped Euler: 5-Node RC Coil/Iron/Air Network"]
        O --> R["Closed-Form Exact Solution: 1-DOF Underdamped Levitation"]
        P & Q & R --> S["State Vector: lumped_state, lev_state, rom_state"]
        S --> T["Spatial Reconstruction: T r,z,t = T_amb + beta*dT_ref r,z"]
    end

    subgraph PRESENTATION["3. Presentation Layer"]
        T --> U["Matplotlib Interactive Twin digital_twin.py"]
        T --> V["Standalone AR Web Twin outputs/digital_twin_fem.html"]
        T --> W["Desktop 3D PyVista Twin extensions/digital_twin_pyvista.py"]
    end

    style OFFLINE_FEM fill:#f9f9f9,stroke:#333,stroke-width:2px
    style ONLINE_RUNTIME fill:#e6f3ff,stroke:#0066cc,stroke-width:2px
    style PRESENTATION fill:#e6ffe6,stroke:#009933,stroke-width:2px
```

---

## 6. Kiểm Trợ & Đồng Bộ Cross-Validation Diagram

Sơ đồ mô tả quy trình kiểm định tự động (`xval_twin.py`) đảm bảo tính đồng nhất 100% (bằng số bit) giữa động cơ Python `twin_core.py` và động cơ JavaScript được nướng vào trang Web AR HTML `outputs/digital_twin_fem.html`. **Lưu ý quan trọng:** không có method `TwinState.step_scenario()` nào cả — Assertion A cố ý gọi TRỰC TIẾP `_rom_step`/`_lev_step` (bỏ qua `TwinState.step()` công khai) để mirror đúng vòng lặp thô của `traceRom()` phía JS, tránh việc sub-stepping/clamp của `step()` làm nhiễu phép so sánh. `xval_twin.py` còn có Assertion B (bake-freshness, rel-diff) không nằm trong sơ đồ gốc — đã bổ sung bên dưới vì đây là nửa còn lại của cùng một test.

```mermaid
sequenceDiagram
    autonumber
    participant Test as "xval_twin.py (Test Runner)"
    participant PyCore as "twin_core.py (TwinState, raw _rom_step/_lev_step)"
    participant PW as "Playwright Headless Browser"
    participant JSBake as "outputs/digital_twin_fem.html (Baked JS)"

    note over Test, PyCore: Assertion A (TOL=1e-9): gọi thẳng _rom_step/_lev_step<br/>theo đúng schedule I(t), KHÔNG qua step() công khai
    Test->>PyCore: theo schedule, gọi twin._rom_step(I, dt) rồi twin._lev_step(I, dt)
    PyCore-->>Test: Return Python Trajectory Array P_py[t]

    Test->>PW: Launch Chromium Headless & Open digital_twin_fem.html
    PW->>JSBake: Expose window.twinDebug.traceRom()
    Test->>PW: Evaluate window.twinDebug.traceRom(args) (cùng schedule I)
    JSBake-->>PW: Execute Baked JS romStep() & levStep()
    PW-->>Test: Return JavaScript Trajectory Array P_js[t]

    rect rgb(255, 235, 235)
        Test->>Test: Assertion A: max(|P_py - P_js|)
        alt Difference < 1e-9 (Machine Precision)
            Test-->>Test: PASS: Bit-for-bit Parity Confirmed
        else Difference >= 1e-9
            Test-->>Test: FAIL: Port Drift / Regression Detected
        end
    end

    rect rgb(235, 245, 255)
        note over Test: Assertion B: so sánh params.yaml (qua Config) voi<br/>các hằng số đã nướng sẵn trong JS -- bắt lỗi kiểu<br/>'coefficient fixed but never rebaked'
        Test->>Test: max relative diff giua Python params va JS baked constants
        alt Difference < 1e-6
            Test-->>Test: PASS: Bake Freshness Confirmed
        else Difference >= 1e-6
            Test-->>Test: FAIL: HTML chua duoc rebake sau khi doi params.yaml
        end
    end
```
