"""rom.py — Real-time Reduced-Order Model for the thermal digital twin.

Mechanism:
  1. BUILD: Run full FEM once at (I_ref, T_ref) → spatial mode ΔT_ref(r,z)
  2. STEADY: ΔT(I) = ΔT_ref × (I/I_ref)²  [+iterative σ(T) correction]
  3. TRANSIENT: first-order ODE  τ·dβ/dt = (I/I_ref)²·s(β) − β
               T(r,z,t) = T_amb + β(t)·ΔT_ref(r,z)

σ(T) correction:  σ(T) = σ0 / (1+α(T−T0))  →  P_plate(T) = P_ref × σ(T)/σ0
                  hotter aluminium conducts less → eddy losses decrease slightly.
"""
from __future__ import annotations
import math
import copy
import numpy as np
from scipy.integrate import solve_ivp
from scipy.interpolate import LinearNDInterpolator


# ---------------------------------------------------------------------------
class ThermalROM:
    """Real-time thermal ROM: I²-scaling + first-order RC transient + σ(T) correction.

    Typical usage:
        rom = ThermalROM().build(cfg)           # ~seconds (FEM once)
        T   = rom.T_steady(I=3.5)               # milliseconds
        T_t = rom.simulate(I_arr, t_arr)        # milliseconds per timestep
    """

    def __init__(self):
        self._built = False

    # ------------------------------------------------------------------
    # BUILD — run FEM at I_ref
    # ------------------------------------------------------------------
    def build(self, cfg=None, em_losses: dict | None = None,
              verbose: bool = True) -> "ThermalROM":
        """Run FEM once at I_ref; extract spatial mode and time constant.

        Args:
            cfg:       Config object (if None, loads from params.yaml)
            em_losses: Output of em_solver.compute_losses() at ANY current.
                       The ROM will rescale to I_ref via I² ratio.
                       If None: uses placeholder heat source.
            verbose:   Print ROM build info.
        """
        from config import load_config, Config
        from thermal_solver import solve_steady, energy_balance

        if cfg is None:
            cfg = load_config()

        cfg_ref = copy.deepcopy(cfg)
        I_ref = float(cfg.I_ref)
        I_cur = float(cfg.I)
        cfg_ref.raw["excitation"]["current_A"] = I_ref

        # Scale em_losses to I_ref if provided
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
            print(f"[ROM] Building at I_ref={I_ref}A (source: {src})...", end=" ", flush=True)

        res_ref = solve_steady(cfg_ref, em_losses=em_ref)
        energy_balance(res_ref)  # verify

        T_ref = res_ref["T"]
        T_amb = float(cfg.bc["T_ambient_degC"])
        dT_ref = T_ref - T_amb   # spatial mode [K] at I_ref

        # Thermal parameters for time constant
        rho = float(cfg.plate["rho_kg_per_m3"])
        cp  = float(cfg.plate["cp_J_per_kgK"])
        R   = cfg.geometry.plate_radius_m
        t   = cfg.geometry.plate_thickness_m
        V   = math.pi * R**2 * t         # plate volume [m³]
        C   = rho * cp * V                # heat capacity [J/K]

        P_ref    = res_ref["P_total"]     # [W] at I_ref
        dT_mean  = float(dT_ref.mean())   # [K] mean temperature rise
        UA       = P_ref / dT_mean        # overall heat transfer coefficient [W/K]

        alpha = float(cfg.plate.get("sigma_tempco_per_K", 3.9e-3))

        # Store state
        self.cfg       = cfg
        self.res_ref   = res_ref
        self.dT_ref    = dT_ref            # spatial mode [K], shape (N_nodes,)
        self.P_ref     = P_ref             # [W]
        self.I_ref     = I_ref             # [A]
        self.T_amb     = T_amb             # [°C]
        self.C         = C                 # heat capacity [J/K]
        self.UA        = UA                # [W/K]
        self.tau       = C / UA            # time constant [s]
        self.alpha     = alpha             # [1/K]
        self.dT_mean_ref = dT_mean         # [K] — normalization for ODE
        self._interp   = LinearNDInterpolator(res_ref["coords"], dT_ref, fill_value=0.0)
        self._built    = True

        if verbose:
            print("xong")
            print(f"  P_ref={P_ref:.3f} W | UA={UA:.4f} W/K | "
                  f"τ={self.tau:.0f} s ({self.tau/60:.1f} min) | "
                  f"ΔT_mean={dT_mean:.2f} K | ΔT_max={dT_ref.max():.2f} K")
        return self

    # ------------------------------------------------------------------
    # SIGMA(T) SCALING
    # ------------------------------------------------------------------
    def _sigma_scale(self, dT_mean_K: float) -> float:
        """Power scaling factor due to σ(T): P_actual = P_ref × σ(T)/σ0 = P_ref/(1+α·ΔT)."""
        return 1.0 / (1.0 + self.alpha * max(dT_mean_K, 0.0))

    # ------------------------------------------------------------------
    # STEADY STATE
    # ------------------------------------------------------------------
    def T_steady(self, I: float, sigma_correction: bool = True,
                 max_iter: int = 20, tol: float = 1e-5) -> np.ndarray:
        """Return steady-state temperature field [°C] at current I.

        Args:
            I:                 Current amplitude [A]
            sigma_correction:  Apply σ(T) correction (converges in ~3 iterations)
        Returns:
            T: array (N_nodes,) — temperature [°C]
        """
        assert self._built, "Call build() first"
        ratio2 = (I / self.I_ref) ** 2

        if not sigma_correction:
            return self.T_amb + self.dT_ref * ratio2

        dT_field = self.dT_ref * ratio2   # initial guess
        for _ in range(max_iter):
            s = self._sigma_scale(float(dT_field.mean()))
            dT_new = self.dT_ref * ratio2 * s
            if abs(dT_new.mean() - dT_field.mean()) < tol:
                return self.T_amb + dT_new
            dT_field = dT_new
        return self.T_amb + dT_field

    def dT_steady_mean(self, I: float, sigma_correction: bool = True) -> float:
        """Mean ΔT [K] at steady state — fast scalar path, no array needed."""
        ratio2 = (I / self.I_ref) ** 2
        if not sigma_correction:
            return self.dT_mean_ref * ratio2
        # τ·dβ/dt=0 → β = ratio2·s(β·ΔT_mean_ref)
        # ΔT = β·ΔT_mean_ref → ΔT = ratio2·ΔT_mean_ref/(1+α·ΔT)
        # → ΔT(1+αΔT) = ratio2·ΔT_mean_ref
        # → αΔT² + ΔT - ratio2·ΔT_mean_ref = 0  → solve quadratic
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
        """Simulate transient: first-order ODE for amplitude coefficient β(t).

        Equation:
            τ · dβ/dt = (I/I_ref)² · s(β·ΔT_mean_ref) − β

        Temperature field:  T(r,z,t) = T_amb + β(t) · ΔT_ref(r,z)

        Args:
            I_of_t:  Callable I(t) [A] OR array of same length as t_arr.
            t_arr:   Time points [s] — must be monotonically increasing.
            T0_field:  Initial T field [°C]; default = T_amb (β₀=0).
            sigma_correction: Apply σ(T) correction inside ODE.

        Returns:
            T_hist: array (len(t_arr), N_nodes) — T [°C] at each time step.
        """
        assert self._built, "Call build() first"
        t_arr = np.asarray(t_arr, dtype=float)

        if callable(I_of_t):
            I_arr = np.array([float(I_of_t(t)) for t in t_arr])
        else:
            I_arr = np.asarray(I_of_t, dtype=float)
            assert len(I_arr) == len(t_arr), "I_of_t and t_arr must have the same length"

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
        """Steady-state temperature [°C] at arbitrary (r,z) points.

        z is LOCAL coordinate within the plate: z ∈ [0, thickness].
        """
        T_field = self.T_steady(I, sigma_correction=sigma_correction)
        coords = self.res_ref["coords"]
        interp = LinearNDInterpolator(coords, T_field, fill_value=float(T_field.mean()))
        pts = np.c_[np.atleast_1d(r), np.atleast_1d(z)]
        return interp(pts)

    # ------------------------------------------------------------------
    # CALIBRATE UA from measurements
    # ------------------------------------------------------------------
    def calibrate_UA(self, I_meas: float, dT_meas: float,
                     sigma_correction: bool = True) -> float:
        """Calibrate UA from a real measurement.

        Args:
            I_meas:   Measured current [A]
            dT_meas:  Measured (T_plate_mean − T_ambient) [K]
        Returns:
            Updated UA [W/K]
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
        assert self._built, "Call build() first"
        lines = [
            "=" * 52,
            "ThermalROM — TEAM 28-like Levitator",
            "=" * 52,
            f"  I_ref       = {self.I_ref:.1f} A",
            f"  P_ref       = {self.P_ref:.4f} W  (plate losses at I_ref)",
            f"  UA          = {self.UA:.5f} W/K  (heat transfer coefficient)",
            f"  C_plate     = {self.C:.2f} J/K   (plate heat capacity)",
            f"  τ           = {self.tau:.1f} s = {self.tau/60:.2f} min",
            f"  ΔT_mean_ref = {self.dT_mean_ref:.3f} K  at I_ref",
            f"  ΔT_max_ref  = {self.dT_ref.max():.3f} K  at I_ref",
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

    # --- Run EM to get spatial loss map ---
    print(f"[EM] Solving at î={cfg.I}A... ", end="", flush=True)
    em = compute_losses(cfg)
    print(f"P_plate={em['P_plate_W']*1e3:.1f} mW  "
          f"P_coil={em['P_coil_W']:.1f} W")

    # --- Build ROM ---
    rom = ThermalROM().build(cfg, em_losses=em, verbose=True)
    print(rom.summary())

    # --- 1) Steady-state: I² scaling + σ(T) correction ---
    print("\nSteady-state scaling check:")
    print(f"  {'I (A)':>5}  {'ΔT_ss analytical':>17}  {'ΔT_max ROM':>12}  {'σ scale':>8}")
    for I in [1.0, 2.0, 3.0, 4.0, 5.0]:
        T_ss  = rom.T_steady(I, sigma_correction=True)
        dT_an = rom.dT_steady_mean(I, sigma_correction=True)
        s     = rom._sigma_scale(T_ss.mean() - rom.T_amb)
        print(f"  {I:>5.1f}  {dT_an:>17.4f} K     {T_ss.max()-rom.T_amb:>8.4f} K  {s:>8.5f}")

    # Verify I² scaling: ΔT(2·I)/ΔT(I) = 4
    dT1 = rom.T_steady(1.0, sigma_correction=False).max() - rom.T_amb
    dT2 = rom.T_steady(2.0, sigma_correction=False).max() - rom.T_amb
    print(f"\n  I² check: ΔT(2A)/ΔT(1A) = {dT2/dT1:.6f}  (expected 4.000000)")

    # --- 2) Transient: step I=5A ---
    t_arr  = np.linspace(0, 600, 601)
    I_step = np.full_like(t_arr, 5.0)
    print(f"\n[ROM] Simulating step transient I=5A (0→600s)... ", end="", flush=True)
    T_hist = rom.simulate(I_step, t_arr, sigma_correction=True)
    print("xong")

    T_mean_t = T_hist.mean(axis=1)
    T_max_t  = T_hist.max(axis=1)
    T_ss_5A  = rom.T_steady(5.0).max()

    # --- 3) Realistic scenario: ramp I from 0→5A over 60s, then hold steady ---
    t_ramp = np.linspace(0, 600, 601)
    I_ramp = np.where(t_ramp < 60, t_ramp * (5.0 / 60.0), 5.0)
    print(f"[ROM] Simulating ramp transient I=0→5A over 60s... ", end="", flush=True)
    T_hist_ramp = rom.simulate(I_ramp, t_ramp, sigma_correction=True)
    print("xong")

    # --- Plot ---
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle(
        f"Real-time Thermal ROM — TEAM 28-like Levitator\n"
        f"I_ref={rom.I_ref}A  |  τ={rom.tau/60:.1f} min  |  α={rom.alpha:.2e} /K",
        fontsize=12)

    # Subplot 1: steady-state T_max vs I
    ax = axes[0]
    I_range = np.linspace(0, 5, 200)
    T_max_corr   = [rom.T_steady(I, sigma_correction=True).max()  for I in I_range]
    T_max_nocorr = [rom.T_steady(I, sigma_correction=False).max() for I in I_range]
    ax.plot(I_range, T_max_corr,   "r-",  lw=2.0, label="with σ(T) correction")
    ax.plot(I_range, T_max_nocorr, "b--", lw=1.5, label="pure I² (no correction)")
    ax.axhline(rom.T_amb, ls=":", color="gray", lw=0.8, label=f"T_amb={rom.T_amb}°C")
    ax.set_xlabel("Current amplitude î (A)")
    ax.set_ylabel("Steady-state T_max (°C)")
    ax.set_title("Steady-state T_max vs. Current")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # Subplot 2: step transient response
    ax2 = axes[1]
    ax2.plot(t_arr / 60, T_max_t,  "r-",  lw=2.0, label="T_max (node)")
    ax2.plot(t_arr / 60, T_mean_t, "b--", lw=1.5, label="T_mean")
    ax2.axhline(T_ss_5A,    ls=":",  color="r",    lw=0.8, label=f"T_ss = {T_ss_5A:.1f}°C")
    ax2.axvline(rom.tau/60, ls="--", color="gray", lw=0.8, label=f"τ = {rom.tau/60:.1f} min")
    ax2.axhline(rom.T_amb,  ls=":",  color="gray", lw=0.6)
    ax2.set_xlabel("Time (min)")
    ax2.set_ylabel("Temperature (°C)")
    ax2.set_title(f"Transient response — step I=5A")
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.3)

    # Subplot 3: ramp scenario
    ax3 = axes[2]
    T_max_ramp  = T_hist_ramp.max(axis=1)
    T_mean_ramp = T_hist_ramp.mean(axis=1)
    ax3_i = ax3.twinx()
    ax3.plot(t_ramp / 60, T_max_ramp,  "r-",  lw=2.0, label="T_max")
    ax3.plot(t_ramp / 60, T_mean_ramp, "b--", lw=1.5, label="T_mean")
    ax3_i.plot(t_ramp / 60, I_ramp, "g:", lw=1.5, label="I(t) [A]")
    ax3.axhline(rom.T_amb, ls=":", color="gray", lw=0.6)
    ax3.set_xlabel("Time (min)")
    ax3.set_ylabel("Temperature (°C)")
    ax3_i.set_ylabel("Current (A)", color="g")
    ax3_i.tick_params(axis="y", labelcolor="g")
    ax3.set_title("Ramp scenario I: 0→5A over 60s")
    lines1, labs1 = ax3.get_legend_handles_labels()
    lines2, labs2 = ax3_i.get_legend_handles_labels()
    ax3.legend(lines1 + lines2, labs1 + labs2, fontsize=8)
    ax3.grid(alpha=0.3)

    plt.tight_layout()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rom_demo.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\nSaved: {out}")
    plt.show()
