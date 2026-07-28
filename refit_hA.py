"""refit_hA.py — WP-COOL T4 (2026-07-28, docs/BUG_REGISTER_2026-07-28.md T4).

Solves `lumped_thermal.hA_inner_W_per_K`/`hA_outer_W_per_K` through the ACTUAL
deployed integrator (twin_core.TwinState — the same code build_twin_html_fem.py
bakes and digital_twin.py drives), not the linear steady-state formula the
2026-07-11 refit used. The deployed model applies a NONLINEAR convection
correction (`hAEff`, `LumpedCoeffs.hA_eff`) on top of the calibrated hA, so a
hA solved from the linear formula settles COOLER than intended once the
nonlinear correction is active away from the I_ref=5A calibration point --
this shipped as a real bug (B1-class, 2026-07-11) that this script exists to
stop from recurring: root-find hA THROUGH the model that actually runs,
instead of hand-deriving a formula that has to be kept in sync with it.

Target: validation_data.thermal_at_7p8A (params.yaml) — inner=79.00C,
outer=74.00C at I=7.8A, T_amb=29C. Root-finds (hA_inner, hA_outer) so
TwinState, run to steady state at that operating point, reproduces those two
numbers exactly.

Run: python refit_hA.py
"""
from __future__ import annotations

from scipy.optimize import fsolve

from config import load_config
from em_solver import compute_losses
from rom import ThermalROM
from build_twin_html_fem import lumped_physics
from twin_core import LevCoeffs, LumpedCoeffs, RomCoeffs, TwinState

T_AMB_CAL = 29.0
I_CAL = 7.8
T_INNER_TARGET = 79.0
T_OUTER_TARGET = 74.0
# Settle time: mirrors twin_core.py's own self-check #2 ("Air-node/network
# balance") horizon (2000 x 300s = 600,000 simulated seconds) -- the coupled
# coil/iron/air network's SLOWEST mode is set by (total mass)/(hA_far), not
# any single node's own bare C/hA, so a short settle would converge to the
# wrong (transient) point instead of true steady state.
N_STEPS, DT_STEP = 2000, 300.0

# Dummy — the coil/iron/air network never reads LevCoeffs; TwinState just
# requires one to construct.
_DUMMY_LEV = LevCoeffs(z_gap_5A_mm=1.0, z_decay_mm=1.0, zeta0=0.0, zeta1=0.0,
                        jit_mm=0.0, jit_freq1=1.0, jit_freq2=1.0,
                        z_gap_exaggeration=1.0, jit_fade_mm=0.5)


def _steady_state(cfg, em, rom, hA_inner: float, hA_outer: float) -> tuple[float, float]:
    cfg.raw["lumped_thermal"]["hA_inner_W_per_K"] = float(hA_inner)
    cfg.raw["lumped_thermal"]["hA_outer_W_per_K"] = float(hA_outer)
    lumped = LumpedCoeffs.from_source(lumped_physics(cfg, em))
    twin = TwinState(rom=rom, lumped=lumped, lev=_DUMMY_LEV, T_amb=T_AMB_CAL)
    for _ in range(N_STEPS):
        twin.step(I_CAL, DT_STEP)
    T = twin.lumped_state.T
    return T["inner"], T["outer"]


def main() -> None:
    cfg = load_config()
    em = compute_losses(cfg)
    rom = RomCoeffs.from_source(ThermalROM().build(cfg, em_losses=em, verbose=False))

    x0 = [float(cfg.raw["lumped_thermal"]["hA_inner_W_per_K"]),
          float(cfg.raw["lumped_thermal"]["hA_outer_W_per_K"])]
    print(f"Starting guess: hA_inner={x0[0]:.4f}  hA_outer={x0[1]:.4f}")

    def residual(x):
        T_inner, T_outer = _steady_state(cfg, em, rom, x[0], x[1])
        return [T_inner - T_INNER_TARGET, T_outer - T_OUTER_TARGET]

    sol, info, ier, msg = fsolve(residual, x0, full_output=True, xtol=1e-8)
    hA_inner, hA_outer = float(sol[0]), float(sol[1])
    T_inner, T_outer = _steady_state(cfg, em, rom, hA_inner, hA_outer)

    print(f"\nConverged (ier={ier}): {msg.strip()}")
    print(f"hA_inner_W_per_K = {hA_inner:.4f}")
    print(f"hA_outer_W_per_K = {hA_outer:.4f}")
    print(f"Verify @ I={I_CAL}A T_amb={T_AMB_CAL}C (through TwinState, nonlinear hAEff active):")
    print(f"  T_inner = {T_inner:.3f} C  (target {T_INNER_TARGET})")
    print(f"  T_outer = {T_outer:.3f} C  (target {T_OUTER_TARGET})")


if __name__ == "__main__":
    main()
