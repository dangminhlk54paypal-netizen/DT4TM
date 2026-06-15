"""rom.py — Real-time Reduced-Order Model cho digital twin nhiệt.

Cơ chế:
  1. BUILD: Giải FEM đầy đủ một lần tại (I_ref, T_ref) → spatial mode ΔT_ref(r,z)
  2. STEADY: ΔT(I) = ΔT_ref × (I/I_ref)²  [+hiệu chỉnh σ(T) lặp]
  3. TRANSIENT: ODE bậc một  τ·dβ/dt = (I/I_ref)²·s(β) − β
               T(r,z,t) = T_amb + β(t)·ΔT_ref(r,z)

σ(T) correction:  σ(T) = σ0 / (1+α(T−T0))  →  P_plate(T) = P_ref × σ(T)/σ0
                  tấm nhôm nóng dẫn điện kém hơn → tổn hao giảm nhẹ.
"""
from __future__ import annotations
import math
import copy
import numpy as np
from scipy.integrate import solve_ivp
from scipy.interpolate import LinearNDInterpolator


# ---------------------------------------------------------------------------
class ThermalROM:
    """ROM nhiệt real-time: I²-scaling + quá độ RC bậc nhất + σ(T) correction.

    Luồng sử dụng điển hình:
        rom = ThermalROM().build(cfg)           # ~seconds (FEM once)
        T   = rom.T_steady(I=3.5)               # milliseconds
        T_t = rom.simulate(I_arr, t_arr)        # milliseconds per timestep
    """

    def __init__(self):
        self._built = False

    # ------------------------------------------------------------------
    # BUILD — giải FEM tại I_ref
    # ------------------------------------------------------------------
    def build(self, cfg=None, em_losses: dict | None = None,
              verbose: bool = True) -> "ThermalROM":
        """Giải FEM một lần tại I_ref; trích xuất spatial mode và hằng số thời gian.

        Args:
            cfg:       Config object (nếu None, tự load từ params.yaml)
            em_losses: Kết quả từ em_solver.compute_losses() tại BẤT KỲ I nào.
                       ROM sẽ tự scale về I_ref qua tỉ lệ I².
                       Nếu None: dùng placeholder heat source.
            verbose:   In thông tin xây dựng ROM.
        """
        from config import load_config, Config
        from thermal_solver import solve_steady, energy_balance

        if cfg is None:
            cfg = load_config()

        cfg_ref = copy.deepcopy(cfg)
        I_ref = float(cfg.I_ref)
        I_cur = float(cfg.I)
        cfg_ref.raw["excitation"]["current_A"] = I_ref

        # Scale em_losses về I_ref nếu được cung cấp
        em_ref = None
        if em_losses is not None:
            em_ref = dict(em_losses)
            scale = (I_ref / I_cur) ** 2
            em_ref["P_plate_W"]   = em_losses["P_plate_W"] * scale
            em_ref["P_payload_W"] = em_losses.get("P_payload_W", 0.0) * scale
            em_ref["P_iron_W"]    = em_losses.get("P_iron_W",  0.0) * scale
            em_ref["P_coil_W"]    = em_losses.get("P_coil_W",  0.0) * scale
            em_ref["P_total_W"]   = em_losses.get("P_total_W", 0.0) * scale

        if verbose:
            src = "EM" if em_ref is not None else "placeholder"
            print(f"[ROM] Building tại I_ref={I_ref}A (nguồn: {src})...", end=" ", flush=True)

        res_ref = solve_steady(cfg_ref, em_losses=em_ref)
        energy_balance(res_ref)  # kiểm tra

        T_ref = res_ref["T"]
        T_amb = float(cfg.bc["T_ambient_degC"])
        dT_ref = T_ref - T_amb   # spatial mode [K] tại I_ref

        # Thông số nhiệt cho hằng số thời gian
        rho = float(cfg.plate["rho_kg_per_m3"])
        cp  = float(cfg.plate["cp_J_per_kgK"])
        R   = cfg.geometry.plate_radius_m
        t   = cfg.geometry.plate_thickness_m
        V   = math.pi * R**2 * t         # thể tích tấm [m³]
        C   = rho * cp * V                # nhiệt dung [J/K]

        P_ref    = res_ref["P_total"]     # [W] tại I_ref
        dT_mean  = float(dT_ref.mean())   # [K] trung bình
        UA       = P_ref / dT_mean        # hệ số truyền nhiệt [W/K]

        alpha = float(cfg.plate.get("sigma_tempco_per_K", 3.9e-3))

        # Lưu state
        self.cfg       = cfg
        self.res_ref   = res_ref
        self.dT_ref    = dT_ref            # spatial mode [K], shape (N_nodes,)
        self.P_ref     = P_ref             # [W]
        self.I_ref     = I_ref             # [A]
        self.T_amb     = T_amb             # [°C]
        self.C         = C                 # nhiệt dung [J/K]
        self.UA        = UA                # [W/K]
        self.tau       = C / UA            # hằng số thời gian [s]
        self.alpha     = alpha             # [1/K]
        self.dT_mean_ref = dT_mean         # [K] — chuẩn hóa cho ODE
        self._interp   = LinearNDInterpolator(res_ref["coords"], dT_ref, fill_value=0.0)
        self._built    = True

        if verbose:
            print("xong")
            print(f"  P_ref={P_ref:.3f} W | UA={UA:.4f} W/K | "
                  f"τ={self.tau:.0f} s ({self.tau/60:.1f} phút) | "
                  f"ΔT_mean={dT_mean:.2f} K | ΔT_max={dT_ref.max():.2f} K")
        return self

    # ------------------------------------------------------------------
    # SIGMA(T) SCALING
    # ------------------------------------------------------------------
    def _sigma_scale(self, dT_mean_K: float) -> float:
        """Hệ số công suất do σ(T): P_actual = P_ref × σ(T)/σ0 = P_ref/(1+α·ΔT)."""
        return 1.0 / (1.0 + self.alpha * max(dT_mean_K, 0.0))

    # ------------------------------------------------------------------
    # STEADY STATE
    # ------------------------------------------------------------------
    def T_steady(self, I: float, sigma_correction: bool = True,
                 max_iter: int = 20, tol: float = 1e-5) -> np.ndarray:
        """Trả về trường nhiệt độ [°C] tại trạng thái ổn định với dòng I.

        Args:
            I:                 Biên độ dòng điện [A]
            sigma_correction:  Hiệu chỉnh σ(T) (lặp hội tụ ~3 bước)
        Returns:
            T: array (N_nodes,) — nhiệt độ [°C]
        """
        assert self._built, "Gọi build() trước"
        ratio2 = (I / self.I_ref) ** 2

        if not sigma_correction:
            return self.T_amb + self.dT_ref * ratio2

        dT_field = self.dT_ref * ratio2   # khởi tạo
        for _ in range(max_iter):
            s = self._sigma_scale(float(dT_field.mean()))
            dT_new = self.dT_ref * ratio2 * s
            if abs(dT_new.mean() - dT_field.mean()) < tol:
                return self.T_amb + dT_new
            dT_field = dT_new
        return self.T_amb + dT_field

    def dT_steady_mean(self, I: float, sigma_correction: bool = True) -> float:
        """ΔT trung bình [K] tại ổn định — nhanh (scalar, không cần array)."""
        ratio2 = (I / self.I_ref) ** 2
        if not sigma_correction:
            return self.dT_mean_ref * ratio2
        # τ·dβ/dt=0 → β = ratio2·s(β·ΔT_mean_ref)
        # ΔT = β·ΔT_mean_ref → ΔT = ratio2·ΔT_mean_ref/(1+α·ΔT)
        # → ΔT(1+αΔT) = ratio2·ΔT_mean_ref
        # → αΔT² + ΔT - ratio2·ΔT_mean_ref = 0  → giải bậc 2
        a = self.alpha
        b = 1.0
        c = -ratio2 * self.dT_mean_ref
        disc = b * b - 4 * a * c
        return (-b + math.sqrt(disc)) / (2 * a)

    # ------------------------------------------------------------------
    # TRANSIENT
    # ------------------------------------------------------------------
    def simulate(self, I_of_t, t_arr: np.ndarray,
                 T0_field: np.ndarray | None = None,
                 sigma_correction: bool = True,
                 rtol: float = 1e-4, atol: float = 1e-6) -> np.ndarray:
        """Mô phỏng quá độ: ODE bậc nhất cho hệ số biên độ β(t).

        Phương trình:
            τ · dβ/dt = (I/I_ref)² · s(β·ΔT_mean_ref) − β

        Trường nhiệt độ:  T(r,z,t) = T_amb + β(t) · ΔT_ref(r,z)

        Args:
            I_of_t:  Callable I(t) [A] HOẶC array cùng kích thước với t_arr.
            t_arr:   Các mốc thời gian [s] — phải tăng dần.
            T0_field:  Trường T ban đầu [°C]; mặc định = T_amb (β₀=0).
            sigma_correction: Hiệu chỉnh σ(T) trong ODE.

        Returns:
            T_hist: array (len(t_arr), N_nodes) — T [°C] tại mỗi bước thời gian.
        """
        assert self._built, "Gọi build() trước"
        t_arr = np.asarray(t_arr, dtype=float)

        if callable(I_of_t):
            I_arr = np.array([float(I_of_t(t)) for t in t_arr])
        else:
            I_arr = np.asarray(I_of_t, dtype=float)
            assert len(I_arr) == len(t_arr), "I_of_t và t_arr phải cùng kích thước"

        if T0_field is None:
            beta0 = 0.0
        else:
            dT0 = np.asarray(T0_field, dtype=float) - self.T_amb
            beta0 = float(dT0.mean()) / self.dT_mean_ref

        dT_mr = self.dT_mean_ref

        def ode(t, beta_vec):
            beta = float(beta_vec[0])
            I_now = float(np.interp(t, t_arr, I_arr))
            ratio2 = (I_now / self.I_ref) ** 2
            s = self._sigma_scale(beta * dT_mr) if sigma_correction else 1.0
            dbeta = (ratio2 * s - beta) / self.tau
            return [dbeta]

        max_step = max((t_arr[-1] - t_arr[0]) / 500, 1.0)
        sol = solve_ivp(ode, (t_arr[0], t_arr[-1]), [beta0],
                        t_eval=t_arr, method="RK23",
                        rtol=rtol, atol=atol, max_step=max_step)

        beta_t = sol.y[0]   # (N_t,)
        # T(r,z,t) = T_amb + β(t)·ΔT_ref(r,z)
        T_hist = self.T_amb + np.outer(beta_t, self.dT_ref)   # (N_t, N_nodes)
        return T_hist

    # ------------------------------------------------------------------
    # POINT QUERY
    # ------------------------------------------------------------------
    def interpolate_T(self, I: float, r, z,
                      sigma_correction: bool = True) -> np.ndarray:
        """Nhiệt độ ổn định [°C] tại các điểm (r,z) tuỳ ý.

        z là toạ độ CỤC BỘ trong tấm: z ∈ [0, thickness].
        """
        T_field = self.T_steady(I, sigma_correction=sigma_correction)
        coords = self.res_ref["coords"]
        interp = LinearNDInterpolator(coords, T_field, fill_value=float(T_field.mean()))
        pts = np.c_[np.atleast_1d(r), np.atleast_1d(z)]
        return interp(pts)

    # ------------------------------------------------------------------
    # CALIBRATE UA từ phép đo
    # ------------------------------------------------------------------
    def calibrate_UA(self, I_meas: float, dT_meas: float,
                     sigma_correction: bool = True) -> float:
        """Hiệu chỉnh UA theo phép đo thực tế.

        Args:
            I_meas:   Dòng điện đo [A]
            dT_meas:  (T_tấm_trung_bình − T_môi) đo được [K]
        Returns:
            UA mới [W/K]
        """
        P = self.P_ref * (I_meas / self.I_ref) ** 2
        if sigma_correction:
            P *= self._sigma_scale(dT_meas)
        self.UA  = P / dT_meas
        self.tau = self.C / self.UA
        self.dT_mean_ref = self.P_ref / self.UA
        return self.UA

    # ------------------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------------------
    def summary(self) -> str:
        assert self._built, "Gọi build() trước"
        lines = [
            "=" * 52,
            "ThermalROM — TEAM 28-like Levitator",
            "=" * 52,
            f"  I_ref       = {self.I_ref:.1f} A",
            f"  P_ref       = {self.P_ref:.4f} W  (tổn hao tấm tại I_ref)",
            f"  UA          = {self.UA:.5f} W/K  (hệ số truyền nhiệt)",
            f"  C_nhiệt     = {self.C:.2f} J/K   (nhiệt dung tấm)",
            f"  τ           = {self.tau:.1f} s = {self.tau/60:.2f} phút",
            f"  ΔT_mean_ref = {self.dT_mean_ref:.3f} K  tại I_ref",
            f"  ΔT_max_ref  = {self.dT_ref.max():.3f} K  tại I_ref",
            f"  α (tempco)  = {self.alpha:.2e} /K",
            "=" * 52,
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI DEMO
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    import os
    import matplotlib.pyplot as plt

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from config import load_config
    from em_solver import compute_losses

    cfg = load_config()

    # --- Chạy EM để lấy spatial loss map ---
    print(f"[EM] Giải tại î={cfg.I}A... ", end="", flush=True)
    em = compute_losses(cfg)
    print(f"P_plate={em['P_plate_W']*1e3:.1f} mW  "
          f"P_coil={em['P_coil_W']:.1f} W")

    # --- Xây ROM ---
    rom = ThermalROM().build(cfg, em_losses=em, verbose=True)
    print(rom.summary())

    # --- 1) Steady-state: I² scaling + σ(T) correction ---
    print("\nKiểm tra steady-state scaling:")
    print(f"  {'I (A)':>5}  {'ΔT_ss analytical':>17}  {'ΔT_max ROM':>12}  {'σ scale':>8}")
    for I in [1.0, 2.0, 3.0, 4.0, 5.0]:
        T_ss  = rom.T_steady(I, sigma_correction=True)
        dT_an = rom.dT_steady_mean(I, sigma_correction=True)
        s     = rom._sigma_scale(T_ss.mean() - rom.T_amb)
        print(f"  {I:>5.1f}  {dT_an:>17.4f} K     {T_ss.max()-rom.T_amb:>8.4f} K  {s:>8.5f}")

    # Xác minh I² scaling: ΔT(2·I)/ΔT(I) = 4
    dT1 = rom.T_steady(1.0, sigma_correction=False).max() - rom.T_amb
    dT2 = rom.T_steady(2.0, sigma_correction=False).max() - rom.T_amb
    print(f"\n  Kiểm tra I²: ΔT(2A)/ΔT(1A) = {dT2/dT1:.6f}  (kỳ vọng 4.000000)")

    # --- 2) Quá độ: bước nhảy I=5A ---
    t_arr  = np.linspace(0, 600, 601)
    I_step = np.full_like(t_arr, 5.0)
    print(f"\n[ROM] Mô phỏng quá độ bước I=5A (0→600s)... ", end="", flush=True)
    T_hist = rom.simulate(I_step, t_arr, sigma_correction=True)
    print("xong")

    T_mean_t = T_hist.mean(axis=1)
    T_max_t  = T_hist.max(axis=1)
    T_ss_5A  = rom.T_steady(5.0).max()

    # --- 3) Kịch bản điều chỉnh thực tế: ramp I từ 0→5A trong 60s, sau đó ổn định ---
    t_ramp = np.linspace(0, 600, 601)
    I_ramp = np.where(t_ramp < 60, t_ramp * (5.0 / 60.0), 5.0)
    print(f"[ROM] Mô phỏng quá độ ramp I=0→5A trong 60s... ", end="", flush=True)
    T_hist_ramp = rom.simulate(I_ramp, t_ramp, sigma_correction=True)
    print("xong")

    # --- Vẽ ---
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle(
        f"ROM Nhiệt Real-time — TEAM 28-like Levitator\n"
        f"I_ref={rom.I_ref}A  |  τ={rom.tau/60:.1f} phút  |  α={rom.alpha:.2e} /K",
        fontsize=12)

    # Subplot 1: steady-state T_max vs I
    ax = axes[0]
    I_range = np.linspace(0, 5, 200)
    T_max_corr   = [rom.T_steady(I, sigma_correction=True).max()  for I in I_range]
    T_max_nocorr = [rom.T_steady(I, sigma_correction=False).max() for I in I_range]
    ax.plot(I_range, T_max_corr,   "r-",  lw=2.0, label="có hiệu chỉnh σ(T)")
    ax.plot(I_range, T_max_nocorr, "b--", lw=1.5, label="thuần I² (không hiệu chỉnh)")
    ax.axhline(rom.T_amb, ls=":", color="gray", lw=0.8, label=f"T_môi={rom.T_amb}°C")
    ax.set_xlabel("Biên độ dòng î (A)")
    ax.set_ylabel("T_max ổn định (°C)")
    ax.set_title("T_max ổn định vs. Dòng")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # Subplot 2: đáp ứng quá độ bước nhảy
    ax2 = axes[1]
    ax2.plot(t_arr / 60, T_max_t,  "r-",  lw=2.0, label="T_max (nút)")
    ax2.plot(t_arr / 60, T_mean_t, "b--", lw=1.5, label="T_trung bình")
    ax2.axhline(T_ss_5A,    ls=":",  color="r",    lw=0.8, label=f"T_ss = {T_ss_5A:.1f}°C")
    ax2.axvline(rom.tau/60, ls="--", color="gray", lw=0.8, label=f"τ = {rom.tau/60:.1f} phút")
    ax2.axhline(rom.T_amb,  ls=":",  color="gray", lw=0.6)
    ax2.set_xlabel("Thời gian (phút)")
    ax2.set_ylabel("Nhiệt độ (°C)")
    ax2.set_title(f"Đáp ứng quá độ — bước I=5A")
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.3)

    # Subplot 3: kịch bản ramp
    ax3 = axes[2]
    T_max_ramp  = T_hist_ramp.max(axis=1)
    T_mean_ramp = T_hist_ramp.mean(axis=1)
    ax3_i = ax3.twinx()
    ax3.plot(t_ramp / 60, T_max_ramp,  "r-",  lw=2.0, label="T_max")
    ax3.plot(t_ramp / 60, T_mean_ramp, "b--", lw=1.5, label="T_trung bình")
    ax3_i.plot(t_ramp / 60, I_ramp, "g:", lw=1.5, label="I(t) [A]")
    ax3.axhline(rom.T_amb, ls=":", color="gray", lw=0.6)
    ax3.set_xlabel("Thời gian (phút)")
    ax3.set_ylabel("Nhiệt độ (°C)")
    ax3_i.set_ylabel("Dòng điện (A)", color="g")
    ax3_i.tick_params(axis="y", labelcolor="g")
    ax3.set_title("Kịch bản ramp I: 0→5A trong 60s")
    lines1, labs1 = ax3.get_legend_handles_labels()
    lines2, labs2 = ax3_i.get_legend_handles_labels()
    ax3.legend(lines1 + lines2, labs1 + labs2, fontsize=8)
    ax3.grid(alpha=0.3)

    plt.tight_layout()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rom_demo.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\nĐã lưu: {out}")
    plt.show()
