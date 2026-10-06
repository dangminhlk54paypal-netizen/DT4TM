"""refit_hA.py — WP-COOL T4 (2026-07-28, docs/archive/2026-07-28_BUG_REGISTER.md T4).

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

Target: validation_data.thermal_anchor (params.yaml) -- the current, operating
point, ambient and inner/outer coil temperatures are READ from params.yaml
(never hardcoded here; until 2026-10-06 this script hardcoded I=7.8A,
79/74C, which turned out to be a bad current reading AND a non-steady run,
WP-ANCHOR). Root-finds (hA_inner, hA_outer) so TwinState, run to steady state
at that operating point, reproduces those two temperatures exactly.

If the anchor says `steady: false` (the coils were still heating when the run
stopped) the end temperatures are only a LOWER BOUND on the true steady state,
so the solved hA is an UPPER bound (the coolest prediction still consistent
with the data). The script then refuses to run unless `--lower-bound` is
passed, so nobody mistakes the result for a fitted value.

Run: python refit_hA.py [--lower-bound]
"""
from __future__ import annotations

import argparse
import sys

from scipy.optimize import fsolve

from config import load_config
from em_solver import compute_losses
from rom import ThermalROM
from build_twin_html_fem import lumped_physics
from twin_core import LevCoeffs, LumpedCoeffs, RomCoeffs, TwinState

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


def _anchor(cfg) -> dict:
    a = cfg.raw["validation_data"]["thermal_anchor"]
    return {"I": float(a["I_A"]), "T_amb": float(a["T_amb_C"]),
            "inner": float(a["inner_coil_C"]), "outer": float(a["outer_coil_C"]),
            "steady": bool(a.get("steady", False)), "source": str(a.get("source", "?"))}


def _steady_state(cfg, em, rom, hA_inner: float, hA_outer: float,
                  I_cal: float, T_amb_cal: float) -> tuple[float, float]:
    cfg.raw["lumped_thermal"]["hA_inner_W_per_K"] = float(hA_inner)
    cfg.raw["lumped_thermal"]["hA_outer_W_per_K"] = float(hA_outer)
    lumped = LumpedCoeffs.from_source(lumped_physics(cfg, em))
    twin = TwinState(rom=rom, lumped=lumped, lev=_DUMMY_LEV, T_amb=T_amb_cal)
    for _ in range(N_STEPS):
        twin.step(I_cal, DT_STEP)
    T = twin.lumped_state.T
    return T["inner"], T["outer"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lower-bound", action="store_true",
                    help="accept a non-steady anchor; the result is an hA UPPER bound")
    args = ap.parse_args()

    cfg = load_config()
    a = _anchor(cfg)
    print(f"Anchor ({a['source']}): I={a['I']}A  T_amb={a['T_amb']}C  "
          f"inner={a['inner']}C  outer={a['outer']}C  steady={a['steady']}")
    if not a["steady"] and not args.lower_bound:
        sys.exit("Anchor is NOT steady state -> only a lower bound on T_ss. Re-run with "
                 "--lower-bound to solve the matching hA UPPER bound.")
    em = compute_losses(cfg)
    rom = RomCoeffs.from_source(ThermalROM().build(cfg, em_losses=em, verbose=False))

    x0 = [float(cfg.raw["lumped_thermal"]["hA_inner_W_per_K"]),
          float(cfg.raw["lumped_thermal"]["hA_outer_W_per_K"])]
    print(f"Starting guess: hA_inner={x0[0]:.4f}  hA_outer={x0[1]:.4f}")

    def residual(x):
        T_inner, T_outer = _steady_state(cfg, em, rom, x[0], x[1], a["I"], a["T_amb"])
        return [T_inner - a["inner"], T_outer - a["outer"]]

    sol, info, ier, msg = fsolve(residual, x0, full_output=True, xtol=1e-8)
    hA_inner, hA_outer = float(sol[0]), float(sol[1])
    T_inner, T_outer = _steady_state(cfg, em, rom, hA_inner, hA_outer, a["I"], a["T_amb"])

    print(f"\nConverged (ier={ier}): {msg.strip()}")
    print(f"hA_inner_W_per_K = {hA_inner:.4f}")
    print(f"hA_outer_W_per_K = {hA_outer:.4f}")
    if not a["steady"]:
        print("NOTE: non-steady anchor -> these hA are UPPER bounds (coolest consistent model).")
    print(f"Verify @ I={a['I']}A T_amb={a['T_amb']}C (through TwinState, nonlinear hAEff active):")
    print(f"  T_inner = {T_inner:.3f} C  (target {a['inner']})")
    print(f"  T_outer = {T_outer:.3f} C  (target {a['outer']})")


if __name__ == "__main__":
    main()
