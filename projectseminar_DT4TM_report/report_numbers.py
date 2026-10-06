"""report_numbers.py -- reproduces EVERY number quoted in project_course_final_v2.{md,tex}.

Run from the repo root:   .venv/bin/python projectseminar_DT4TM_report/report_numbers.py
(Optional) regenerate the ROM-vs-FEM figure:   ... report_numbers.py --figure

Each printed line is tagged [Nx] with the key used in Appendix A of the report,
so a reader can trace any number in the text back to the line that computed it.
Read-only: nothing in params.yaml or the core code is modified.
"""
from __future__ import annotations

import contextlib
import copy
import io
import math
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from config import load_config
import em_solver
import thermal_solver
from rom import ThermalROM
from build_twin_html_fem import lumped_physics, compute_eddy_fraction
from twin_core import LevCoeffs, LumpedCoeffs, RomCoeffs, TwinState

MU0 = 4e-7 * math.pi
_SINK = io.StringIO()


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(_SINK):
        return fn(*a, **kw)


def timed(fn, *a, n=5, **kw):
    ts, out = [], None
    for _ in range(n):
        t0 = time.perf_counter()
        out = quiet(fn, *a, **kw)
        ts.append(time.perf_counter() - t0)
    return out, float(np.median(ts))


def say(key, text):
    print(f"[{key}] {text}")


def main(make_figure: bool) -> None:
    cfg = load_config()
    raw = cfg.raw
    print("=" * 72)
    print("A. INPUT DATA (params.yaml) -- measured or assumed, not computed")
    print("=" * 72)
    say("N1", f"I_rms operating point = {cfg.I} A, f = {raw['excitation'].get('frequency_Hz', 50)} Hz, I_peak = {cfg.I_peak:.3f} A")
    say("N2", f"plate R = {cfg.geometry.plate_radius_m*1e3:.1f} mm, d = {cfg.geometry.plate_thickness_m*1e3:.1f} mm, "
              f"sigma_Al = {float(cfg.plate['sigma_S_per_m']):.3g} S/m, k = {cfg.plate['k_W_per_mK']}, "
              f"rho = {cfg.plate['rho_kg_per_m3']}, cp = {cfg.plate['cp_J_per_kgK']}, alpha = {cfg.plate.get('sigma_tempco_per_K')}")
    bc = raw["thermal_bc"]
    say("N3", f"h_top = {bc.get('h_W_per_m2K')} W/m2K, h_bottom = {bc.get('h_bottom_W_per_m2K')} W/m2K, "
              f"T_amb = {bc.get('T_ambient_degC')} C, k_coil_coupling = {bc.get('k_coil_coupling_K_per_W')} K/W")
    lt = raw["lumped_thermal"]
    say("N4", f"hA_inner = {lt['hA_inner_W_per_K']}, hA_outer = {lt['hA_outer_W_per_K']} W/K (calibrated), "
              f"air C = {lt.get('air_node_C_J_per_K')}, air hA_far = {lt.get('air_node_hA_far_W_per_K')}")
    vd = raw["validation_data"]
    say("N5", f"IR run B @6.175A (NOT steady, lower bound): {vd['thermal_session_B']}")
    say("N6", f"IR run A (ramp, first): {vd['thermal_session_A']}")

    print("=" * 72)
    print("B. EM FEM")
    print("=" * 72)
    res, t_em = timed(em_solver.solve_em, cfg)
    say("E1", f"EM mesh: {len(res['coords'])} nodes, {len(res['tris'])} triangles, complex unknowns; "
              f"linear solve median = {t_em:.3f} s")
    em, t_emfull = timed(em_solver.compute_losses, cfg, n=3)
    say("E2", f"compute_losses (default path, incl. mu(B) iteration) median = {t_emfull:.3f} s")
    say("E3", f"P_plate = {em['P_plate_W']:.2f} W, P_iron = {em['P_iron_W']:.2f} W, P_coil = {em['P_coil_W']:.2f} W, "
              f"P_total = {em['P_total_W']:.2f} W")
    lp = quiet(lumped_physics, cfg, em)
    Pin, Pout = lp["nodes"]["inner"]["P_ref"], lp["nodes"]["outer"]["P_ref"]
    say("E4", f"coil split: inner = {Pin:.2f} W, outer = {Pout:.2f} W; shares: coils = {em['P_coil_W']/em['P_total_W']*100:.1f} %, "
              f"plate = {em['P_plate_W']/em['P_total_W']*100:.1f} %, iron = {em['P_iron_W']/em['P_total_W']*100:.1f} %")
    B_lin, _ = em_solver.check_saturation(res, cfg)
    Bpk = B_lin * math.sqrt(2)          # phasor amplitude = cfg.I (loss-chain convention)
    say("E5", f"B_max in iron at phasor amplitude {cfg.I} A: RMS = {B_lin:.3f} T, peak = {Bpk:.3f} T; "
              f"real peak @5A_rms (amp {cfg.I_peak:.2f} A) = {Bpk*cfg.I_peak/cfg.I:.3f} T; "
              f"@6.175A_rms (dial max, amp {6.175*math.sqrt(2):.2f} A) = {Bpk*6.175*math.sqrt(2)/cfg.I:.3f} T; "
              f"B_sat (params) = {raw['iron_core'].get('B_sat_T')} T")
    cfg2 = copy.deepcopy(cfg)
    cfg2.raw["excitation"]["current_A"] = 2 * cfg.I
    em2 = quiet(em_solver.compute_losses, load_config() if False else cfg2)
    say("E6", f"I^2 check (full re-solve, default mu(B) path): P(2I)/P(I) = {em2['P_total_W']/em['P_total_W']:.4f}, "
              f"plate only = {em2['P_plate_W']/em['P_plate_W']:.4f}")
    r2 = quiet(em_solver.solve_em, cfg2)
    l1 = quiet(em_solver.compute_losses, cfg, res=res)
    l2 = quiet(em_solver.compute_losses, cfg2, res=r2)
    say("E6", f"I^2 check (linear solve, constant mu_r): P(2I)/P(I) = {l2['P_total_W']/l1['P_total_W']:.4f}, "
              f"plate only = {l2['P_plate_W']/l1['P_plate_W']:.4f}")
    dom = quiet(em_solver.validate_domain_size, cfg, verbose=False)
    say("E7", f"domain check Dirichlet vs Neumann: {dom}")
    omega = 2 * math.pi * 50.0
    delta = math.sqrt(2 / (omega * MU0 * float(cfg.plate["sigma_S_per_m"])))
    say("E8", f"skin depth Al @50Hz = {delta*1e3:.1f} mm  (d/delta = {cfg.geometry.plate_thickness_m/delta:.2f})")

    print("=" * 72)
    print("C. THERMAL FEM + ROM")
    print("=" * 72)
    cap = {}
    orig = thermal_solver.spla.spsolve

    def spy(K, F):
        cap["K"], cap["F"] = K, F
        return orig(K, F)

    thermal_solver.spla.spsolve = spy
    rom, t_rom = timed(ThermalROM().build, cfg, em_losses=em, n=5)
    thermal_solver.spla.spsolve = orig
    r = rom.res_ref
    say("T1", f"thermal mesh: {len(r['coords'])} nodes, {len(r['tris'])} triangles; build (FEM solve+ROM) median = {t_rom:.3f} s")
    Qin = float(np.sum(r["p_e"] * 2 * np.pi * r["rc_e"] * r["area_e"]))
    eb = quiet(thermal_solver.energy_balance, r)
    say("T2", f"energy balance: Q_in = {Qin:.4f} W; energy_balance() -> {eb}")
    say("T3", f"Tinf_bottom = {r['Tinf_bot']:.2f} C (= T_amb + k_coil*P_coil)")
    say("R1", f"C = rho*cp*V = {rom.C:.2f} J/K, P_ref = {rom.P_ref:.3f} W, mean dT_ref = {rom.dT_mean_ref:.3f} K, "
              f"UA = P/dT = {rom.UA:.4f} W/K, tau = C/UA = {rom.tau:.1f} s")
    say("R2", f"dT_ref range = {rom.dT_ref.min():.2f} .. {rom.dT_ref.max():.2f} K")
    h_bot = float(bc.get("h_bottom_W_per_m2K"))
    Bi = h_bot * (cfg.geometry.plate_thickness_m / 2) / float(cfg.plate["k_W_per_mK"])
    say("R3", f"Biot number (h_bottom, half thickness) = {Bi:.2e}")

    rho, cp = float(cfg.plate["rho_kg_per_m3"]), float(cfg.plate["cp_J_per_kgK"])
    M = np.zeros(len(r["coords"]))
    for e, (a, b, c) in enumerate(r["tris"]):
        M[[a, b, c]] += rho * cp * 2 * np.pi * r["rc_e"][e] * r["area_e"][e] / 3
    K, F = cap["K"].tocsc(), cap["F"]
    ones = np.ones(len(M))
    say("R4", f"sum(M) = {M.sum():.2f} J/K (= C), 1^T K 1 = {ones @ (K @ ones):.4f} W/K -> C/(1^T K 1) = {M.sum()/(ones @ (K @ ones)):.1f} s")
    Ms = sp.diags(1 / np.sqrt(M))
    A = Ms @ K @ Ms
    A = 0.5 * (A + A.T)
    lam = np.sort(spla.eigsh(A, k=6, sigma=0, which="LM", return_eigenvectors=False))
    taus = 1 / lam
    say("R5", f"eigen time constants tau_i = {np.round(taus, 3).tolist()} s; gap tau1/tau2 = {taus[0]/taus[1]:.1f}")

    Ta = rom.T_amb
    Tss = spla.spsolve(K, F)
    dt, Nt = 1.0, 1200
    lu = spla.splu((sp.diags(M / dt) + K).tocsc())
    T = np.full(len(M), Ta)
    ih = int(np.argmax(Tss))
    t_l, fem, m1, rm, e1, er = [], [], [], [], [], []
    for n in range(Nt):
        T = lu.solve(M / dt * T + F)
        tt = (n + 1) * dt
        b1 = 1 - (1 + dt * lam[0]) ** (-(n + 1))
        br = 1 - math.exp(-tt / rom.tau)
        T1 = Ta + b1 * (Tss - Ta)
        Tr = Ta + br * rom.dT_ref
        t_l.append(tt); fem.append(T[ih] - Ta); m1.append(T1[ih] - Ta); rm.append(Tr[ih] - Ta)
        e1.append(np.abs(T1 - T).max()); er.append(np.abs(Tr - T).max())
    dTmax = Tss[ih] - Ta
    say("R6", f"ROM vs transient FEM (I_ref, from ambient, dt=1s, 1200s): 1-mode(tau1) max err = {max(e1):.3f} K "
              f"({max(e1)/dTmax*100:.2f} %); code ROM(tau=C/UA) max err = {max(er):.3f} K ({max(er)/dTmax*100:.2f} %) "
              f"at t = {t_l[int(np.argmax(er))]:.0f} s; steady dT_max = {dTmax:.2f} K")
    t0 = time.perf_counter()
    for _ in range(200):
        T = lu.solve(M / dt * T + F)
    say("R7", f"one prefactored transient FEM step = {(time.perf_counter()-t0)/200*1e6:.1f} us")
    f_eddy = quiet(compute_eddy_fraction, cfg, em, rom)
    say("R8", f"f_eddy = {f_eddy:.4f}, f_air = {1-f_eddy:.4f}")

    print("=" * 72)
    print("D. LUMPED NETWORK, CALIBRATION, RUNTIME")
    print("=" * 72)
    for k in ("inner", "outer", "iron"):
        nd = lp["nodes"][k]
        say("L1", f"{k}: P_ref = {nd['P_ref']:.2f} W, C_surf = {nd['C']:.1f} J/K, C_deep = {nd.get('C_deep', 0):.1f} J/K, "
                  f"hA = {nd['hA']}, G_wind = {nd.get('G_wind')}, G_cond = {nd.get('G_cond')}")
    say("L2", f"air node: {lp['air_node']}")
    romc = RomCoeffs.from_source(rom, f_eddy=f_eddy, f_air=1 - f_eddy)
    lumped = LumpedCoeffs.from_source(lp)
    lev = LevCoeffs(z_gap_5A_mm=1.0, z_decay_mm=1.0, zeta0=0.0, zeta1=0.0, jit_mm=0.0, jit_freq1=1.0,
                    jit_freq2=1.0, z_gap_exaggeration=1.0, jit_fade_mm=0.5)
    for I_ss, Ta_ss in ((6.175, 29.0), (5.0, 20.0)):
        tw = TwinState(rom=romc, lumped=lumped, lev=lev, T_amb=Ta_ss)
        for _ in range(2000):
            tw.step(I_ss, 300.0)
        Tn = tw.lumped_state.T
        say("L3", f"steady state @{I_ss}A, T_amb={Ta_ss}C: " + ", ".join(f"{k} = {v:.2f}" for k, v in Tn.items())
                  + f", disc mean = {Ta_ss + tw.rom_state.beta*rom.dT_mean_ref:.1f} C  [IR run B end @6.175A (not steady): inner 79, outer 67, core 45 (unreliable)]")
    # transient run A (WP-ANCHOR 2026-10-06): 5.1A 0-300s, then 6.25A to 510s, from 33.7C coils
    A = vd["thermal_session_A"]
    tw = TwinState(rom=romc, lumped=lumped, lev=lev, T_amb=float(vd["ambient_C"]))
    for k in ("inner", "outer", "inner_deep", "outer_deep"):
        tw.lumped_state.T[k] = float(A["start"]["outer_coil_C"])
    rows = []
    for n in range(1, 511):
        tw.step(5.1 if n <= 300 else 6.25, 1.0)
        if n == 300:
            rows.append(("outer", 300, float(A["at_t300s"]["outer_coil_C"]), tw.lumped_state.T["outer"]))
    for key in ("inner", "outer"):
        rows.append((key, 510, float(A["at_t510s"][f"{key}_coil_C"]), tw.lumped_state.T[key]))
    for key, t, m, g in rows:
        say("L4", f"run A t = {t:3d} s {key} coil: IR = {m:.2f} C, model = {g:.2f} C, diff = {g - m:+.2f} K")
    rms = math.sqrt(sum((g - m) ** 2 for *_, m, g in rows) / len(rows))
    say("L5", f"run A RMS error (coils, {len(rows)} points) = {rms:.2f} K")
    tw = TwinState(rom=romc, lumped=lumped, lev=lev, T_amb=20.0)
    N = 20000
    t0 = time.perf_counter()
    for _ in range(N):
        tw.step(5.0, 1.0)
    t_step = (time.perf_counter() - t0) / N
    say("L6", f"TwinState.step(I, dt=1s) with REAL coefficients = {t_step*1e6:.2f} us "
              f"(n_sub = {max(1, math.ceil(1.0/(romc.tau*0.05)))}); speed-up vs one EM+thermal solve = {(t_emfull+t_rom)/t_step:.2e}")

    print("=" * 72)
    print("E. LEVITATION")
    print("=" * 72)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        em_solver.run_rig_validation()
    for line in out.getvalue().splitlines():
        if "z_eq" in line or "F_gravity" in line or "Observed" in line or "3.8" in line.split("  ")[0:3].__str__():
            say("V1", line.strip())

    if make_figure:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams.update({"font.size": 8, "font.family": "serif", "axes.spines.top": False, "axes.spines.right": False})
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(3.45, 3.6), sharex=True, gridspec_kw={"height_ratios": [1.6, 1]})
        tm = np.array(t_l) / 60
        a1.plot(tm, fem, color="#222222", lw=2.2, label=f"FEM, {len(M)} Unbekannte (Referenz)")
        a1.plot(tm, m1, color="#2a78d6", lw=1.4, ls="--", label=r"ROM, 1 Mode, $\tau_1$ aus Eigenproblem")
        a1.plot(tm, rm, color="#eb6834", lw=1.4, ls="-.", label=r"ROM im Code, $\tau=C/UA$")
        a1.set_ylabel(r"$\Delta T$ heißester Knoten [K]"); a1.legend(frameon=False, loc="lower right", fontsize=7)
        a1.grid(alpha=.25, lw=.5)
        a2.plot(tm, e1, color="#2a78d6", lw=1.4, ls="--"); a2.plot(tm, er, color="#eb6834", lw=1.4, ls="-.")
        a2.set_ylabel("max. Fehler [K]"); a2.set_xlabel("Zeit [min]"); a2.grid(alpha=.25, lw=.5)
        a2.annotate(f"{max(er):.1f} K", (t_l[int(np.argmax(er))] / 60, max(er)), xytext=(8, -2),
                    textcoords="offset points", fontsize=7)
        a2.annotate(f"{max(e1):.2f} K", (t_l[int(np.argmax(e1))] / 60, max(e1)), xytext=(6, 4),
                    textcoords="offset points", fontsize=7)
        fig.tight_layout()
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Figures", "rom_vs_fem")
        fig.savefig(base + ".pdf"); fig.savefig(base + ".png", dpi=200)
        print("figure written:", base + ".{pdf,png}")
        fig, ax = plt.subplots(figsize=(3.45, 1.9))
        idx = np.arange(1, len(taus) + 1)
        ax.bar(idx, taus, color=["#2a78d6"] + ["#9aa3ad"] * (len(taus) - 1), width=0.6)
        ax.set_yscale("log"); ax.set_xticks(idx)
        ax.set_xlabel("Eigenform $i$"); ax.set_ylabel(r"$\tau_i$ [s]")
        for i, tv in zip(idx, taus):
            ax.annotate(f"{tv:.3g} s", (i, tv), xytext=(0, 2), textcoords="offset points", ha="center", fontsize=7)
        ax.set_ylim(0.1, 1000); ax.grid(axis="y", alpha=.25, lw=.5)
        fig.tight_layout()
        base2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Figures", "eigen_spectrum")
        fig.savefig(base2 + ".pdf"); fig.savefig(base2 + ".png", dpi=200)
        print("figure written:", base2 + ".{pdf,png}")


if __name__ == "__main__":
    main("--figure" in sys.argv)
