"""twin_core.py — SSOT time integrators for the thermal digital twin.

Ports (bit-for-bit, same operation order) the three ODE integrators that used
to live ONLY inside the JS <script> template baked by build_twin_html_fem.py:
  1. the dual-source disc β model             (JS romStep,  :1485-1538)
  2. the lumped coil/iron/shared-air RC network (JS romStep, same function —
     the coil network and the disc β model are integrated together each step)
  3. the levitation spring-mass-damper + jitter (JS levStep, :1705-1735)

Consumers: digital_twin.py (matplotlib), the upcoming PyVista twin, and
data_io.py — all three should import RomCoeffs/LumpedCoeffs/LevCoeffs/TwinState
from here instead of re-deriving the physics. See docs/archive/2026-07-28_PYVISTA_TWIN_PLAN.md
for the "9 traps" this port has to reproduce exactly (each one is called out
at its corresponding line below).

STRICT CONSTRAINT (checked by self-check #6 and by
`python -c "import sys,twin_core; assert 'em_solver' not in sys.modules and
'matplotlib' not in sys.modules"`): this module may only import numpy +
stdlib. No config, em_solver, rom, matplotlib — those live in twin_model.py.
The heavy per-plate *coefficients* (lumped_physics/lev_params) also stay put
in build_twin_html_fem.py; only the *integrators* moved here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


# ---------------------------------------------------------------------------
# I(t) scenarios — verbatim port of digital_twin.py:31-45
# ---------------------------------------------------------------------------
def scenario_step(I: float = 5.0):
    return (lambda t: I), f"Step I={I}A"

def scenario_ramp(I: float = 5.0, t_r: float = 60.0):
    return (lambda t: min(t / t_r, 1.0) * I), f"Ramp 0→{I}A/{t_r:.0f}s"

def scenario_sine(I: float = 5.0):
    Im, Ia = I * 0.6, I * 0.4
    return (lambda t: max(0.0, Im + Ia * math.sin(2 * math.pi * t / 120))), f"Sin {Im:.1f}±{Ia:.1f}A"

def scenario_pulse(I: float = 5.0):
    return (lambda t: I if (t % 120) < 60 else 0.0), f"Pulse {I}A ON60/OFF60s"

def scenario_quickstart(I: float = 5.0, t_r: float = 8.0):
    """WP-SHIMMER V1 (2026-07-28, docs/archive/2026-07-28_BUG_REGISTER.md V1): fast
    0->I ramp, t_r from params.yaml transient.quickstart_ramp_s (default 8s,
    user asked for 5-10s). Same functional form as scenario_ramp (just a much
    shorter default ramp time + its own label) -- this is the HTML twin's
    on-load/on-reset DEFAULT scenario, so the disc visibly ramps up and bobs
    instead of snapping straight to its I=5A gap the way `step` does."""
    return (lambda t: min(t / t_r, 1.0) * I), f"Quickstart 0→{I}A/{t_r:.0f}s"

SCENARIOS = {"quickstart": scenario_quickstart, "step": scenario_step,
             "ramp": scenario_ramp, "sine": scenario_sine, "pulse": scenario_pulse}


# ---------------------------------------------------------------------------
# Dual-source access helper — lets every Coeffs.from_source() accept EITHER a
# live Python object (attribute access, e.g. a rom.py ThermalROM instance) OR
# a flat dict (e.g. twinDebug.PARAMS.rom / .lumped / .lev, pulled straight out
# of the baked HTML by the future xval_twin.py harness).
# ---------------------------------------------------------------------------
def _get(src, name, default=None):
    if isinstance(src, dict):
        return src.get(name, default)
    return getattr(src, name, default)


# ---------------------------------------------------------------------------
# RomCoeffs — dual-β disc model coefficients (JS ROM object, PARAMS.rom)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RomCoeffs:
    T_amb: float
    tau: float
    I_ref: float
    dT_mean_ref: float
    alpha: float
    # f_eddy=1/f_air=0 is the single-β model (digital_twin.py's DigitalTwin) —
    # dual-β is a strict generalization of it (docs/archive/2026-07-28_PYVISTA_TWIN_PLAN.md).
    f_eddy: float = 1.0
    f_air: float = 0.0
    # WP-COOL T3 (2026-07-28, docs/archive/2026-07-28_BUG_REGISTER.md T3): the disc's
    # heat-up τ (`tau` above) was derived from a FEM whose bottom BC includes
    # the coil-plume enhancement (h_bottom=25 W/m2K); that enhancement dies
    # with the current, so cooldown is physically slower than heat-up. 1.0
    # (the default) reproduces the OLD behaviour exactly (a single τ for both
    # directions) so an older baked HTML that never emits this key still loads
    # unchanged. See TwinState._rom_step's tau_eff computation.
    tau_cool_natural_frac: float = 1.0
    # Full per-mesh-node ΔT_ref field, ONLY available from a live rom.py object
    # (PARAMS.rom never carries the whole array — too large to bake as JSON
    # scalars). Needed for .T_field; not needed for the coil/lev integrators.
    dT_ref: "np.ndarray | None" = field(default=None, repr=False, compare=False)

    @classmethod
    def from_source(cls, src, *, f_eddy: float | None = None, f_air: float | None = None) -> "RomCoeffs":
        """src: a live rom.py `ThermalROM` instance, OR a flat dict shaped like
        build_twin_html_fem.py's `rom_params` (:911-930) / PARAMS.rom.
        f_eddy/f_air override the source's own values when given (a live
        ThermalROM object has no notion of the eddy/hot-air split — that is
        computed separately by build_twin_html_fem.compute_eddy_fraction();
        the dict path already carries "f_eddy"/"f_air" keys and needs no
        override)."""
        dT_ref = _get(src, "dT_ref")
        fe = f_eddy if f_eddy is not None else float(_get(src, "f_eddy", 1.0))
        fa = f_air if f_air is not None else float(_get(src, "f_air", 0.0))
        return cls(
            T_amb=float(_get(src, "T_amb")),
            tau=float(_get(src, "tau")),
            I_ref=float(_get(src, "I_ref")),
            dT_mean_ref=float(_get(src, "dT_mean_ref")),
            alpha=float(_get(src, "alpha")),
            f_eddy=fe,
            f_air=fa,
            tau_cool_natural_frac=float(_get(src, "tau_cool_natural_frac", 1.0)),
            dT_ref=None if dT_ref is None else np.asarray(dT_ref, dtype=float),
        )

    def sigma_scale(self, dT_mean_K: float) -> float:
        """Verbatim port of rom.py:119-121 `ThermalROM._sigma_scale` == JS
        romStep's `s` (build_twin_html_fem.py:1489)."""
        return 1.0 / (1.0 + self.alpha * max(dT_mean_K, 0.0))


# ---------------------------------------------------------------------------
# LumpedCoeffs — coil(×2, two-node) + iron + shared-air RC network
# (JS LUMPED object, PARAMS.lumped == build_twin_html_fem.lumped_physics())
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NodeCoeffs:
    P_ref: float
    C: float
    hA: float
    dT_cal: float
    C_deep: float | None = None   # inner/outer only (winding-core mass)
    G_wind: float = 0.0           # inner/outer only (surface<->deep conductance)
    G_cond: float = 0.0           # iron only (contact conduction FROM the inner coil)
    # WP-COOL T1 (2026-07-28, docs/archive/2026-07-28_BUG_REGISTER.md T1): P_ref split
    # across the surface/deep nodes in the SAME ratio as their heat capacity
    # (coil_C_scale), instead of dumping 100% of P_ref onto the surface node
    # while the deep node (holding most of the copper mass) got none -- that
    # made both heat-up AND cooldown ~4.5x too fast. None/None (both missing)
    # reproduces the OLD behaviour exactly (all power to the surface, none to
    # the deep node) so an older baked HTML that never emits these two keys
    # still loads and runs unchanged.
    P_ref_surf: float | None = None
    P_ref_deep: float | None = None

    @classmethod
    def from_source(cls, src) -> "NodeCoeffs":
        return cls(
            P_ref=float(_get(src, "P_ref")),
            C=float(_get(src, "C")),
            hA=float(_get(src, "hA")),
            dT_cal=float(_get(src, "dT_cal")),
            C_deep=(lambda v: None if v is None else float(v))(_get(src, "C_deep")),
            G_wind=float(_get(src, "G_wind", 0.0)),
            G_cond=float(_get(src, "G_cond", 0.0)),
            P_ref_surf=(lambda v: None if v is None else float(v))(_get(src, "P_ref_surf")),
            P_ref_deep=(lambda v: None if v is None else float(v))(_get(src, "P_ref_deep")),
        )


@dataclass(frozen=True)
class AirNodeCoeffs:
    C: float
    hA_far: float

    @classmethod
    def from_source(cls, src) -> "AirNodeCoeffs":
        return cls(C=float(_get(src, "C")), hA_far=float(_get(src, "hA_far")))


@dataclass(frozen=True)
class LumpedCoeffs:
    convection_exponent: float
    nodes: "dict[str, NodeCoeffs]"   # insertion order MUST be inner, outer, iron
                                      # (matches the JS object's key order — see
                                      # romStep's `for (const k in LUMPED.nodes)`)
    air_node: AirNodeCoeffs

    @classmethod
    def from_source(cls, src) -> "LumpedCoeffs":
        """src: a dict shaped like build_twin_html_fem.lumped_physics()'s return
        value / PARAMS.lumped (both are already this exact nested shape)."""
        nodes_src = _get(src, "nodes")
        nodes = {
            "inner": NodeCoeffs.from_source(nodes_src["inner"]),
            "outer": NodeCoeffs.from_source(nodes_src["outer"]),
            "iron":  NodeCoeffs.from_source(nodes_src["iron"]),
        }
        return cls(
            convection_exponent=float(_get(src, "convection_exponent")),
            nodes=nodes,
            air_node=AirNodeCoeffs.from_source(_get(src, "air_node")),
        )

    @staticmethod
    def hA_eff(hA_cal: float, dT: float, dT_cal: float, conv_exp: float) -> float:
        """Verbatim port of JS hAEff (build_twin_html_fem.py:1475-1478) — trap 5:
        floors |ΔT| at 0.1 before the power-law convection correction."""
        dT_use = max(abs(dT), 0.1)
        return hA_cal * (dT_use / dT_cal) ** conv_exp

    # --- derived constants (JS :1439-1457, computed once at PARAMS load; here
    #     recomputed on demand — cheap, 3 nodes, and keeps LumpedCoeffs frozen) ---
    @property
    def air_P_sum_ref(self) -> float:
        return sum(nd.P_ref for nd in self.nodes.values())

    @property
    def air_dT_ss_ref(self) -> float:
        return self.air_P_sum_ref / self.air_node.hA_far

    @property
    def coil_dT_ss_ref(self) -> float:
        ai, ao = self.nodes["inner"], self.nodes["outer"]
        dT_air_ss = self.air_dT_ss_ref
        return (ai.P_ref * (ai.P_ref / ai.hA + dT_air_ss) +
                ao.P_ref * (ao.P_ref / ao.hA + dT_air_ss))

    def coil_air_drive(self, T_inner: float, T_outer: float, T_amb: float) -> float:
        """JS coilAirDrive() (build_twin_html_fem.py:1452-1457)."""
        ai, ao = self.nodes["inner"], self.nodes["outer"]
        num = ai.P_ref * (T_inner - T_amb) + ao.P_ref * (T_outer - T_amb)
        return max(0.0, num / self.coil_dT_ss_ref)

    def coil_Tss(self, node: str, I: float, I_ref: float, T_amb: float) -> float:
        """JS coilTss_inner/coilTss_outer (build_twin_html_fem.py:2295-2302) — a
        UI-only steady-state ESTIMATE that ignores the nonlinear hA_eff
        correction (and, for "inner", the iron contact-conduction correction
        baked into dT_cal). Exact only where hA_eff(dT_cal)==hA by
        construction: I==I_ref, or when G_cond==0 for the "inner" node."""
        nd = self.nodes[node]
        s2 = (I / I_ref) ** 2
        return T_amb + (nd.P_ref / nd.hA + self.air_dT_ss_ref) * s2


# ---------------------------------------------------------------------------
# LevCoeffs — levitation spring-mass-damper + sub-liftoff jitter
# (JS LEV object, PARAMS.lev == build_twin_html_fem.lev_params())
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LevCoeffs:
    z_gap_5A_mm: float
    z_decay_mm: float
    zeta0: float
    zeta1: float
    jit_mm: float
    jit_freq1: float
    jit_freq2: float
    z_gap_exaggeration: float
    jit_fade_mm: float
    # WP-SHIMMER V2 (2026-07-28, docs/archive/2026-07-28_BUG_REGISTER.md V2): sustained
    # shimmer while levitating, DISPLAY ONLY (see x_ripple_mm below for the
    # traceable physical number it's built on). gain=0.0 (default) reproduces
    # the OLD behaviour exactly (no sustained shimmer) so an older baked HTML
    # that never emits these keys still loads and runs unchanged.
    lev_ripple_display_gain: float = 0.0
    mains_omega_rad_s: float = 2.0 * math.pi * 50.0

    @classmethod
    def from_source(cls, src) -> "LevCoeffs":
        return cls(
            z_gap_5A_mm=float(_get(src, "z_gap_5A_mm")),
            z_decay_mm=float(_get(src, "z_decay_mm")),
            zeta0=float(_get(src, "zeta0")),
            zeta1=float(_get(src, "zeta1")),
            jit_mm=float(_get(src, "jit_mm")),
            jit_freq1=float(_get(src, "jit_freq1")),
            jit_freq2=float(_get(src, "jit_freq2")),
            z_gap_exaggeration=float(_get(src, "z_gap_exaggeration")),
            jit_fade_mm=float(_get(src, "jit_fade_mm", 0.5)),
            lev_ripple_display_gain=float(_get(src, "lev_ripple_display_gain", 0.0)),
            mains_omega_rad_s=float(_get(src, "mains_omega_rad_s", 2.0 * math.pi * 50.0)),
        )

    @property
    def omega(self) -> float:
        """JS LEV_OMEGA (:1678). NOTE: JS also has a dead `Z_OBS_7_75A_MM`
        override branch (:1668-1670) that is permanently disabled (hardcoded
        `null`) in the current build — intentionally NOT ported; if that
        anchor is ever filled in on the JS side this property must follow."""
        return math.sqrt(9.81 / (self.z_decay_mm * 1e-3))

    @property
    def I_lev_min(self) -> float:
        """JS I_LEV_MIN (:1671)."""
        return 5.0 * math.exp(-self.z_gap_5A_mm / (2.0 * self.z_decay_mm))

    @property
    def x_ripple_mm(self) -> float:
        """WP-SHIMMER V2: amplitude of the vertical disc response to the real
        100Hz (2x mains) force ripple (F ∝ i² → 100% modulated at Ω=2ω), from
        the 1-DOF forced-response transfer function
        |X/X_static| = 1/|1-(Ω/ω_n)²|, X_static=z_decay_mm (docs/physics.md
        §11). ~0.0249mm at the default R=80mm/50Hz constants -- computed here,
        never pasted, so it stays correct if z_decay_mm or the mains frequency
        change."""
        omega_n = self.omega
        Omega = 2.0 * self.mains_omega_rad_s
        return self.z_decay_mm / abs(1.0 - (Omega / omega_n) ** 2)

    def z_gap_eq_mm(self, I: float) -> float:
        """JS levGapEqMm (:1698-1701)."""
        if I <= self.I_lev_min:
            return 0.0
        return self.z_gap_5A_mm + 2.0 * self.z_decay_mm * math.log(I / 5.0)

    def zeta(self, I: float) -> float:
        """JS levZeta (:1702). NOTE the literal 5.0 (not I_ref) — the lift
        model is always normalized to the 5A rig operating point regardless
        of ROM.I_ref, ported verbatim."""
        return self.zeta0 + self.zeta1 * (I / 5.0) ** 2


# ---------------------------------------------------------------------------
# Mutable per-simulation state
# ---------------------------------------------------------------------------
@dataclass
class RomState:
    beta: float = 0.0
    beta_eddy: float = 0.0
    beta_air: float = 0.0


@dataclass
class LumpedState:
    T: "dict[str, float]"   # keys: inner outer iron air inner_deep outer_deep

    @classmethod
    def at_ambient(cls, T_amb: float) -> "LumpedState":
        return cls(T={"inner": T_amb, "outer": T_amb, "iron": T_amb, "air": T_amb,
                       "inner_deep": T_amb, "outer_deep": T_amb})


@dataclass
class LevState:
    z: float = 0.0
    v: float = 0.0
    jit: float = 0.0
    jitPhase1: float = 0.0
    jitPhase2: float = 0.0
    # WP-SHIMMER V2: separate phase accumulators for the sustained levitating
    # shimmer (jit_lev), independent of jitPhase1/2's sub-liftoff contact buzz.
    jitLevPhase1: float = 0.0
    jitLevPhase2: float = 0.0


# ---------------------------------------------------------------------------
# TwinState — the three integrators, driven together by .step(I, dt_sim)
# ---------------------------------------------------------------------------
@dataclass
class TwinState:
    rom: RomCoeffs
    lumped: LumpedCoeffs
    lev: LevCoeffs
    T_amb: float   # runtime ambient (JS T_AMB_JS) — deliberately a SEPARATE
                   # value from rom.T_amb (the offline solve-time ambient); JS
                   # anchors every live temperature (coils/air/disc) to
                   # T_AMB_JS, which may diverge from PARAMS.rom.T_amb (see
                   # docs/archive/2026-07-28_PYVISTA_TWIN_PLAN.md's T_AMB_FALLBACK_C
                   # note). A caller that wants the two tied together (e.g.
                   # the matplotlib twin, offline-only) just passes the same
                   # value for both.
    current_clamp_A: float = 20.0
    # TODO(WP-cleanup, per docs/archive/2026-07-28_PYVISTA_TWIN_PLAN.md trap 8): the
    # asymmetric current clamp below (romStep clamps to current_clamp_A,
    # levStep does not) is ported VERBATIM from JS (build_twin_html_fem.py
    # :2721 vs :2763) because it is CURRENT, live behaviour — not because it
    # is correct. A future WP should decide on one clamp policy and apply it
    # to both integrators (and to digital_twin.py's own I_MAX clamp).
    t: float = 0.0
    rom_state: RomState = field(default_factory=RomState)
    lumped_state: "LumpedState | None" = None
    lev_state: LevState = field(default_factory=LevState)

    def __post_init__(self):
        if self.lumped_state is None:
            self.lumped_state = LumpedState.at_ambient(self.T_amb)

    def reset(self) -> None:
        """Port of JS resetSim() (build_twin_html_fem.py:1540-1548)."""
        self.rom_state = RomState()
        self.lumped_state = LumpedState.at_ambient(self.T_amb)
        self.lev_state = LevState()
        self.t = 0.0

    # -- romStep, build_twin_html_fem.py:1485-1538 --------------------------
    def _rom_step(self, I: float, dt: float) -> None:
        rom, lumped, T = self.rom, self.lumped, self.lumped_state.T
        rs = self.rom_state

        s2 = (I / rom.I_ref) ** 2
        # trap 2: σ-scale uses the TOTAL β of the PREVIOUS step, not β_eddy.
        dT_mean = rs.beta * rom.dT_mean_ref
        s = rom.sigma_scale(dT_mean)

        # trap 3: q_cond from the OLD T.inner/T.iron, fixed BEFORE the node loop.
        q_cond = lumped.nodes["iron"].G_cond * (T["inner"] - T["iron"])

        Qconv = 0.0
        for k, nd in lumped.nodes.items():   # insertion order: inner, outer, iron
            # WP-COOL T1: split P_ref across surface/deep in the coil's own
            # C-ratio instead of dumping 100% onto the surface node -- None on
            # either key (iron, or an older bake) means "no split", i.e. all
            # power on the surface / none on the deep node (old behaviour).
            q_surf = (nd.P_ref_surf if nd.P_ref_surf is not None else nd.P_ref) * s2
            q_deep = (nd.P_ref_deep if nd.P_ref_deep is not None else 0.0) * s2
            if k == "iron":
                q_surf += q_cond
            if k == "inner":
                q_surf -= q_cond
            dTsurf = T[k] - T["air"]   # trap 4: reads the OLD air temperature
            hA_use = LumpedCoeffs.hA_eff(nd.hA, dTsurf, nd.dT_cal, lumped.convection_exponent)
            out = hA_use * dTsurf
            if nd.G_wind:
                deep_key = f"{k}_deep"
                g = nd.G_wind * (T[deep_key] - T[k])
                T[k] += (q_surf + g - out) / nd.C * dt
                T[deep_key] += (q_deep - g) / nd.C_deep * dt
            else:
                T[k] += (q_surf - out) / nd.C * dt
            Qconv += out

        # trap 4: air node updated AFTER the node loop (every node above saw
        # the OLD air temperature, not this new one).
        T["air"] += (Qconv - lumped.air_node.hA_far * (T["air"] - self.T_amb)) / lumped.air_node.C * dt

        # trap 1: coil temperatures are already updated above, so coil_air_drive
        # below reads the FRESH T["inner"]/T["outer"] from this same step.
        air_drive = lumped.coil_air_drive(T["inner"], T["outer"], self.T_amb)
        # WP-COOL T3: the disc's τ was fit from a FEM with an "enhanced
        # convection facing coils" bottom BC (the coil plume) -- that
        # enhancement fades with the coils' own drive, so cooldown is slower
        # than heat-up. tau_cool_natural_frac=1.0 (old bakes) reproduces the
        # OLD single-tau behaviour exactly (tau_eff == rom.tau always). τ only
        # sets the RATE here, never the β targets below, so steady state is
        # unaffected -- see the bug register's proof.
        f_nat = rom.tau_cool_natural_frac
        tau_eff = rom.tau / (f_nat + (1.0 - f_nat) * min(1.0, air_drive))

        tgt_eddy = s2 * s
        rs.beta_eddy = max(0.0, rs.beta_eddy + (tgt_eddy - rs.beta_eddy) / tau_eff * dt)  # trap 6
        tgt_air = air_drive * s
        rs.beta_air = max(0.0, rs.beta_air + (tgt_air - rs.beta_air) / tau_eff * dt)       # trap 6

        rs.beta = rom.f_eddy * rs.beta_eddy + rom.f_air * rs.beta_air
        self.t += dt

    # -- levStep, build_twin_html_fem.py:1705-1735 ---------------------------
    def _lev_step(self, I: float, dt: float) -> None:
        lev, ls = self.lev, self.lev_state
        zt = lev.z_gap_eq_mm(I)
        zeta = lev.zeta(I)
        omega = lev.omega
        if zt <= 0 and ls.z <= 0:
            ls.z = 0.0
            ls.v = 0.0
        else:
            x0, v0 = ls.z - zt, ls.v
            wd = omega * math.sqrt(max(1e-6, 1 - zeta * zeta))
            decay = math.exp(-zeta * omega * dt)
            cwt, swt = math.cos(wd * dt), math.sin(wd * dt)
            A = (v0 + zeta * omega * x0) / wd
            ls.z = zt + decay * (x0 * cwt + A * swt)
            ls.v = decay * ((A * wd - zeta * omega * x0) * cwt - (x0 * wd + zeta * omega * A) * swt)
            if ls.z < 0:
                ls.z = 0.0
                if ls.v < 0:
                    ls.v = 0.0

        fade_in = max(0.0, 1.0 - ls.z / lev.jit_fade_mm)
        if I > 0.05 and fade_in > 0:
            ls.jitPhase1 += lev.jit_freq1 * dt
            ls.jitPhase2 += lev.jit_freq2 * dt
            amp = min(1.0, lev.jit_mm * (I / 5.0) ** 2)
            jit_contact = fade_in * amp * (math.sin(ls.jitPhase1) + 0.5 * math.sin(ls.jitPhase2))
        else:
            jit_contact = 0.0

        # WP-SHIMMER V2 (2026-07-28, docs/archive/2026-07-28_BUG_REGISTER.md V2):
        # sustained shimmer while actually levitating (z>0) -- jit_contact
        # above is gated OFF above jit_fade_mm=0.5mm, so every disc above
        # ~3.2A was previously perfectly rigid. This is an honest DISPLAY-ONLY
        # rendering of the real (but invisible, 25um/100Hz) vertical ripple
        # force -- see LevCoeffs.x_ripple_mm. Own phase accumulators so it
        # doesn't sync with jit_contact's.
        if I > 0.05 and ls.z > 0.0:
            ls.jitLevPhase1 += lev.jit_freq1 * dt
            ls.jitLevPhase2 += lev.jit_freq2 * dt
            amp_lev = lev.x_ripple_mm * lev.lev_ripple_display_gain * (I / 5.0) ** 2
            jit_lev = amp_lev * (math.sin(ls.jitLevPhase1) + 0.5 * math.sin(ls.jitLevPhase2))
        else:
            jit_lev = 0.0

        ls.jit = jit_contact + jit_lev

    def step(self, I: float, dt: float) -> None:
        """Signature kept IDENTICAL to the old DigitalTwin.step(I, dt)
        (digital_twin.py:64) so data_io.py:256/277 keeps working unmodified
        when it is later switched over to TwinState. `dt` here is dt_sim (a
        possibly-large, speed-multiplied step) — internally split into JS's
        τ-aware substeps (loop(), build_twin_html_fem.py:2718), NOT
        digital_twin.py's own speed-aware n_steps rule (:440-444)."""
        n_sub = max(1, math.ceil(dt / (self.rom.tau * 0.05)))
        dt_sub = dt / n_sub
        for _ in range(n_sub):
            # trap 8: romStep sees the clamped current; levStep (below) does
            # NOT — ported verbatim, see the TODO on current_clamp_A above.
            I_clamped = max(0.0, min(I, self.current_clamp_A))
            self._rom_step(I_clamped, dt_sub)
        # trap 7: levStep is called ONCE with the FULL dt, never substepped
        # (its closed-form solution is exact for any dt, unlike the coil/disc
        # forward-Euler ODEs above).
        # trap 9: levStep therefore sees I at t_{n+1} (self.t has already been
        # advanced by all n_sub romStep calls above), and sees the RAW
        # (unclamped) I — both match JS's loop() call order exactly.
        self._lev_step(I, dt)

    @property
    def T_field(self):
        """Matches DigitalTwin.T_field (digital_twin.py:76-78): T_amb +
        β·ΔT_ref. With f_air=0/f_eddy=1 this is bit-identical to the old
        single-β model; in general β = f_eddy·β_eddy + f_air·β_air (JS
        discVtxT, build_twin_html_fem.py:1803-1806, collapsed to a single
        field since twin_core has one ΔT_ref array, not two baked mesh
        fields — see RomCoeffs.dT_ref docstring)."""
        if self.rom.dT_ref is None:
            raise ValueError(
                "RomCoeffs.dT_ref is not set -- T_field needs a live `rom` "
                "object (RomCoeffs.from_source(rom_obj)), not a PARAMS dict."
            )
        return self.T_amb + self.rom_state.beta * self.rom.dT_ref


# ---------------------------------------------------------------------------
# Self-check — synthetic (hand-picked, NOT measured) coefficients so this
# file's own verification never needs config/em_solver/rom/matplotlib either.
# ---------------------------------------------------------------------------
def _synthetic_lumped(G_cond: float = 0.12, conv_exp: float = 0.25) -> LumpedCoeffs:
    """Physically-plausible but made-up coil/iron/air coefficients, solved the
    SAME way lumped_physics() derives dT_cal (build_twin_html_fem.py:378-394):
    the steady-state anchor point where hA_eff(dT_cal) == hA exactly."""
    P_inner, P_outer, P_iron = 50.0, 55.0, 6.0
    hA_inner, hA_outer, hA_iron, hA_far = 2.95, 3.45, 1.0, 5.0

    dT_air_cal = (P_inner + P_outer + P_iron) / hA_far
    A = np.array([[hA_inner + G_cond, -G_cond], [-G_cond, hA_iron + G_cond]])
    b = np.array([P_inner + hA_inner * dT_air_cal, P_iron + hA_iron * dT_air_cal])
    dT_inner_amb, dT_iron_amb = np.linalg.solve(A, b)

    # G_wind picked so the deep (winding-core) node's own time constant
    # (C_deep/G_wind) is comparable to the surface node's (C/hA) — with the
    # real params.yaml-scale numbers G_wind is ~2 orders of magnitude smaller
    # (deep node is DESIGNED to lag for minutes, CLAUDE.md's coil_C_scale
    # note), which would need a self-check horizon of hours of simulated time
    # to actually reach steady state; a synthetic self-check just needs BOTH
    # nodes to converge within a tractable step count.
    nodes = {
        "inner": NodeCoeffs(P_ref=P_inner, C=880.0, C_deep=3120.0, G_wind=20.0,
                             hA=hA_inner, dT_cal=float(dT_inner_amb - dT_air_cal)),
        "outer": NodeCoeffs(P_ref=P_outer, C=968.0, C_deep=3432.0, G_wind=20.0,
                             hA=hA_outer, dT_cal=P_outer / hA_outer),
        "iron":  NodeCoeffs(P_ref=P_iron, C=2000.0, hA=hA_iron,
                             dT_cal=float(dT_iron_amb - dT_air_cal), G_cond=G_cond),
    }
    return LumpedCoeffs(convection_exponent=conv_exp, nodes=nodes,
                         air_node=AirNodeCoeffs(C=500.0, hA_far=hA_far))


def _synthetic_lev() -> LevCoeffs:
    return LevCoeffs(z_gap_5A_mm=4.1, z_decay_mm=13.6, zeta0=0.0, zeta1=0.02,
                      jit_mm=0.3, jit_freq1=27.0, jit_freq2=71.0,
                      z_gap_exaggeration=2.0, jit_fade_mm=0.5)


def _self_check_1() -> bool:
    """f_air=0 must collapse EXACTLY onto digital_twin.py's single-β model
    (DigitalTwin.step, digital_twin.py:64-69): β=max(0, β+(ratio²·s-β)/τ·dt),
    s=sigma_scale(β·dT_mean_ref). Reimplemented inline (NOT imported) so this
    self-check never needs matplotlib installed."""
    rom = RomCoeffs(T_amb=20.0, tau=100.0, I_ref=5.0, dT_mean_ref=43.0, alpha=3.9e-3,
                     f_eddy=1.0, f_air=0.0)
    twin = TwinState(rom=rom, lumped=_synthetic_lumped(), lev=_synthetic_lev(), T_amb=20.0)

    beta_ref = 0.0
    I_fn, _ = scenario_ramp(5.0, 60.0)
    dt = 1.0   # << rom.tau*0.05=5.0 => TwinState.step's n_sub==1, i.e. one Euler step/call
    max_err = 0.0
    for _ in range(600):
        I = I_fn(twin.t)
        twin.step(I, dt)
        ratio2 = (I / rom.I_ref) ** 2
        s = rom.sigma_scale(beta_ref * rom.dT_mean_ref)
        beta_ref = max(0.0, beta_ref + (ratio2 * s - beta_ref) / rom.tau * dt)
        max_err = max(max_err, abs(twin.rom_state.beta - beta_ref))
    ok = max_err < 1e-12
    print(f"[1] f_air=0 vs single-β digital_twin.py:68 model over 600s: "
          f"max|Δβ|={max_err:.3e}  {'PASS' if ok else 'FAIL'}")
    return ok


def _self_check_2() -> bool:
    """T_inner(t→∞) at I=I_ref must match coilTss_inner(I_ref) — exact by
    construction there (hA_eff(dT_cal)==hA at the calibration point). Uses
    G_cond=0 because coilTss_inner's formula ignores the iron contact-
    conduction correction that a nonzero G_cond bakes into dT_cal (verified
    numerically: with G_cond>0 the two differ by ~0.3K here, a real property
    of the JS UI helper, not a porting bug — see LumpedCoeffs.coil_Tss docstring)."""
    rom = RomCoeffs(T_amb=20.0, tau=100.0, I_ref=5.0, dT_mean_ref=43.0, alpha=3.9e-3)
    lumped = _synthetic_lumped(G_cond=0.0)
    twin = TwinState(rom=rom, lumped=lumped, lev=_synthetic_lev(), T_amb=20.0)

    I = rom.I_ref
    # 2000 calls x 300s = 600,000 simulated seconds. The coupled coil/iron/air
    # network's SLOWEST mode is set by (total thermal mass)/(hA_far) -- heat
    # can only leave the whole lumped system through the single hA_far path,
    # everything else just redistributes it internally -- which is ~2000s
    # here, not any individual node's own bare C/hA (verified: 30_000 steps
    # of dt=1 previously left this ~10K off target; this horizon is >100x
    # that dominant time constant).
    for _ in range(2_000):
        twin.step(I, 300.0)
    T_inner_ss = twin.lumped_state.T["inner"]
    expect = lumped.coil_Tss("inner", I, rom.I_ref, twin.T_amb)
    err = abs(T_inner_ss - expect)
    ok = err < 1e-6
    print(f"[2] T_inner(t→∞, I=I_ref) vs coilTss_inner: {T_inner_ss:.6f} vs "
          f"{expect:.6f}  err={err:.3e}  {'PASS' if ok else 'FAIL'}")
    return ok


def _self_check_3() -> bool:
    """β(t→∞) == s²·s_σ at a NON-reference current (I=6A≠I_ref=5A). Needs BOTH
    conv_exp=0 (linear convection: dTsurf_ss scales exactly linearly with s²,
    proven by the node ODE's steady-state balance) AND G_cond=0. G_cond>0
    breaks exactness here for the SAME reason it broke self-check #2: JS's
    COIL_DT_SS_REF/coilAirDrive() normalize by the NAIVE P_ref/hA_inner
    (build_twin_html_fem.py:1449-1451), not by the true coupled dT_cal_inner
    (which includes the iron contact-conduction correction) — so
    coil_air_drive_ss(I) only equals s² exactly when that correction is zero,
    i.e. G_cond=0 (verified numerically: G_cond=0.12 leaves a ~5e-4 residual
    here, an intentional property of the JS UI normalization, not a porting
    bug). Self-check #5 below exercises G_cond>0 instead."""
    rom = RomCoeffs(T_amb=20.0, tau=100.0, I_ref=5.0, dT_mean_ref=43.0, alpha=3.9e-3,
                     f_eddy=0.84, f_air=0.16)
    lumped = _synthetic_lumped(G_cond=0.0, conv_exp=0.0)
    twin = TwinState(rom=rom, lumped=lumped, lev=_synthetic_lev(), T_amb=20.0)

    I = 6.0
    for _ in range(2_000):
        twin.step(I, 300.0)

    s2 = (I / rom.I_ref) ** 2
    beta_fp = s2
    for _ in range(500):   # fixed-point iteration: β = s²·sigma_scale(β·dT_mean_ref)
        beta_fp = s2 * rom.sigma_scale(beta_fp * rom.dT_mean_ref)

    err = abs(twin.rom_state.beta - beta_fp)
    ok = err < 1e-9
    print(f"[3] β(t→∞, I=6A) vs s²·s_σ fixed point: {twin.rom_state.beta:.9f} vs "
          f"{beta_fp:.9f}  err={err:.3e}  {'PASS' if ok else 'FAIL'}")
    return ok


def _self_check_4() -> bool:
    """z(t→∞) == levGapEqMm(I); dropping I to I_LEV_MIN must decay z -> 0
    (the "<=" branch in z_gap_eq_mm returns exactly 0 there)."""
    rom = RomCoeffs(T_amb=20.0, tau=100.0, I_ref=5.0, dT_mean_ref=43.0, alpha=3.9e-3)
    lev = _synthetic_lev()
    twin = TwinState(rom=rom, lumped=_synthetic_lumped(), lev=lev, T_amb=20.0)

    twin.step(5.0, 60.0)   # settle near z_gap_eq_mm(5A) (closed-form: exact for any dt)
    z_at_5A = twin.lev_state.z
    expect_5A = lev.z_gap_eq_mm(5.0)
    err_5A = abs(z_at_5A - expect_5A)

    I_min = lev.I_lev_min
    twin.step(I_min, 60.0)   # long settle at the lift-off threshold current
    z_at_min = twin.lev_state.z
    ok = err_5A < 1e-6 and abs(z_at_min) < 1e-6
    print(f"[4] z(t→∞,I=5A)={z_at_5A:.6f}mm vs levGapEqMm(5A)={expect_5A:.6f}mm "
          f"(err={err_5A:.3e}); z(t→∞,I=I_LEV_MIN={I_min:.4f}A)={z_at_min:.3e}mm  "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


def _self_check_5() -> bool:
    """Air-node energy balance closes at steady state: Σ(node convection out)
    must equal BOTH hA_far·(T_air-T_amb) (the air node's own balance) AND
    Σ(P_ref)·s² (trap 3: q_cond must cancel exactly between inner/iron, since
    it is an internal transfer, not new generation). Uses the realistic
    coupled+nonlinear coefficients (G_cond>0, conv_exp>0) — the strongest
    available exercise of traps 3+4 together."""
    rom = RomCoeffs(T_amb=20.0, tau=100.0, I_ref=5.0, dT_mean_ref=43.0, alpha=3.9e-3)
    lumped = _synthetic_lumped(G_cond=0.12, conv_exp=0.25)
    twin = TwinState(rom=rom, lumped=lumped, lev=_synthetic_lev(), T_amb=20.0)

    I = 6.0
    for _ in range(2_000):
        twin.step(I, 300.0)

    T = twin.lumped_state.T
    Qconv = 0.0
    for k, nd in lumped.nodes.items():
        dTsurf = T[k] - T["air"]
        hA_use = LumpedCoeffs.hA_eff(nd.hA, dTsurf, nd.dT_cal, lumped.convection_exponent)
        Qconv += hA_use * dTsurf

    s2 = (I / rom.I_ref) ** 2
    Q_air_out = lumped.air_node.hA_far * (T["air"] - twin.T_amb)
    Q_gen_in = lumped.air_P_sum_ref * s2

    err_air = abs(Qconv - Q_air_out)
    err_gen = abs(Qconv - Q_gen_in)
    ok = err_air < 1e-6 and err_gen < 1e-6
    print(f"[5] Air-node energy balance @ steady state: Σout={Qconv:.6f}W  "
          f"hA_far·ΔT={Q_air_out:.6f}W (err={err_air:.3e})  "
          f"ΣP_ref·s²={Q_gen_in:.6f}W (err={err_gen:.3e})  {'PASS' if ok else 'FAIL'}")
    return ok


def _self_check_6() -> bool:
    """This module must stay import-clean: no em_solver, no matplotlib. Also
    independently re-verified by `python -c "import sys,twin_core; assert
    'em_solver' not in sys.modules and 'matplotlib' not in sys.modules"`
    from a completely fresh interpreter."""
    import sys
    ok = "em_solver" not in sys.modules and "matplotlib" not in sys.modules
    print(f"[6] twin_core import stays numpy+stdlib-only (no em_solver/matplotlib "
          f"in sys.modules): {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    results = [
        _self_check_1(),
        _self_check_2(),
        _self_check_3(),
        _self_check_4(),
        _self_check_5(),
        _self_check_6(),
    ]
    print(f"\n{sum(results)}/6 PASS" + ("" if all(results) else "  -- FAILURES ABOVE"))
    raise SystemExit(0 if all(results) else 1)
