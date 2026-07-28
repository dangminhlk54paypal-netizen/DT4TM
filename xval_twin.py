"""xval_twin.py — pins twin_core.py's ported integrators against the ACTUAL
baked JS engine in outputs/digital_twin_fem.html, via Playwright and the
window.twinDebug.traceRom() hook (build_twin_html_fem.py, WP-HOOK/WP-XVAL).

Two INDEPENDENT assertions, each with its own error message (they catch
different failure modes and must never be conflated):

  A. INTEGRATOR PORT CORRECTNESS — twin_core's TwinState._rom_step/_lev_step
     must match traceRom()'s per-step trajectory to an ABSOLUTE 1e-9 (not a
     tolerance to "loosen for realism" — see justification below).
  B. BAKE FRESHNESS — outputs/digital_twin_fem.html's baked PARAMS.lumped /
     PARAMS.rom.tau must match a FRESH `lumped_physics(cfg, compute_losses(
     cfg))` / `ThermalROM().build(cfg, em).tau` computed from the CURRENT
     params.yaml, to a RELATIVE 1e-6. This is the exact bug class that
     shipped in commit d4f73d6/WP-5 (an edit to config.py/em_solver.py/
     build_twin_html_fem.py's own coefficient functions that never got
     baked into the committed HTML) — assertion A alone can NEVER catch it,
     because A only checks that twin_core agrees with whatever PARAMS
     happens to already be baked, stale or not.

Why 1e-9 for assertion A is not negotiable (do not silently raise it because
a future change makes the test red — that is what this comment is for):
JS `Number` is IEEE-754 float64, exactly like numpy's `float64`. Both sides
run the SAME forward-Euler update, the SAME dt, in the SAME operation order
(the "9 traps", see twin_core.py's _rom_step/_lev_step docstrings and
docs/archive/2026-07-28_PYVISTA_TWIN_PLAN.md) — so the only possible residual is ULP
noise from pow/exp/sin/log, which different JS engines and numpy build
against different libm implementations for. Every ODE integrated here is
CONTRACTIVE (every eigenvalue of the linearized system is negative — see
twin_core.py self-checks #2/#3/#5), so that noise DECAYS every step instead
of accumulating: empirically, over a 600-step run with a ~60K rise, the
observed drift is of order 1e-14 K, nine orders of magnitude under this
threshold. If a real port lands here and drifts past 1e-9, that is a PORT
BUG, full stop — "forward Euler is expected to drift" is not a valid excuse
for THIS test (it would be a valid excuse for a genuinely different
integrator, e.g. RK4-vs-Euler, which is exactly the scenario the next
paragraph is for).

The ONLY legitimate reason to touch these thresholds: a future twin_core.py
deliberately switches to a DIFFERENT integration scheme (e.g. semi-implicit
or RK4) than the JS's forward Euler. THAT is a real, expected divergence,
and the ceiling to reopen this comment for is documented as 1e-3 K / 1e-4 mm
(three-ish orders of magnitude under the JS's own dt=1s forward-Euler
truncation error, not "whatever makes CI green"). Anything short of that
justification: fix the port, don't widen the test.

Network policy: outputs/digital_twin_fem.html's <script type="importmap">
loads three.js from https://unpkg.com/... (build_twin_html_fem.py, search
"unpkg.com") — offline, the module never finishes evaluating, window.
twinDebug never gets defined, and every assertion below would fail with a
confusing "undefined has no method traceRom" instead of a physics error.
page.route() intercepts every request: unpkg.com URLs are served from a
persistent disk cache (outputs/.jscache/, gitignored — see repo .gitignore's
"outputs/*" blanket rule), downloaded once on first run and reused offline
forever after; everything else is aborted, so this script never depends on
network reachability beyond that one-time warm-up.

Run: `python xval_twin.py` — prints a max-abs-diff table per quantity per
test case, then PASS/FAIL for both assertions, exit 0 iff both pass.
"""
from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from twin_core import LevCoeffs, LumpedCoeffs, RomCoeffs, SCENARIOS, TwinState

ROOT = Path(__file__).resolve().parent
HTML_PATH = ROOT / "outputs" / "digital_twin_fem.html"
CACHE_DIR = ROOT / "outputs" / ".jscache"

TOL_INTEGRATOR_ABS = 1e-9   # assertion A — see module docstring, do not raise casually
TOL_STALE_REL = 1e-6        # assertion B

QUANTITIES = ["t", "beta", "beta_eddy", "beta_air", "T_inner", "T_outer",
              "T_iron", "T_air", "T_inner_deep", "T_outer_deep", "z", "v", "jit"]


# ---------------------------------------------------------------------------
# Network: cache-or-block route handler
# ---------------------------------------------------------------------------
def _cache_path_for(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    name = url.rstrip("/").split("/")[-1] or "index"
    return CACHE_DIR / f"{name}.{h}"


def _route(route) -> None:
    url = route.request.url
    if url.startswith("file://"):
        route.continue_()
        return
    if "unpkg.com" not in url:
        route.abort()   # MANDATORY network block: nothing else may reach the network
        return
    cpath = _cache_path_for(url)
    ctype_path = cpath.with_suffix(cpath.suffix + ".ctype")
    if cpath.exists():
        ctype = ctype_path.read_text().strip() if ctype_path.exists() else "application/javascript"
        route.fulfill(status=200, content_type=ctype, body=cpath.read_bytes())
        return
    # First run only: fetch the real module once and cache it to disk.
    response = route.fetch()
    body = response.body()
    ctype = response.headers.get("content-type", "application/javascript; charset=utf-8")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cpath.write_bytes(body)
    ctype_path.write_text(ctype)
    route.fulfill(response=response)


def _open_page(pw):
    if not HTML_PATH.exists():
        sys.exit(f"{HTML_PATH} not found -- run `python build_twin_html_fem.py` first.")
    browser = pw.chromium.launch()
    page = browser.new_page()
    console_errors: list[str] = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append(str(e)))
    page.route("**/*", _route)
    page.goto(HTML_PATH.as_uri())
    page.wait_for_function(
        "() => window.twinDebug && typeof window.twinDebug.traceRom === 'function'",
        timeout=15_000,
    )
    if console_errors:
        browser.close()
        sys.exit(
            "outputs/digital_twin_fem.html raised console errors on load -- "
            "fix the HTML before trusting any xval result:\n  " + "\n  ".join(console_errors)
        )
    return browser, page


# ---------------------------------------------------------------------------
# Test schedules: (name, I_schedule, dt, n, every)
# I_schedule is either a constant float (exercises traceRom's scalar path)
# or a list[float] of length n (exercises its per-step array path).
# ---------------------------------------------------------------------------
def _build_schedules(I_ref: float, I_lev_min: float) -> list[tuple[str, "float | list[float]", float, int, int]]:
    ramp_fn, _ = SCENARIOS["ramp"](I_ref, 60.0)
    pulse_fn, _ = SCENARIOS["pulse"](2.0 * I_lev_min)   # ON phase clears I_LEV_MIN, OFF phase is 0 < I_LEV_MIN
    sine_fn, _ = SCENARIOS["sine"](2.0 * I_lev_min)     # oscillates through I_LEV_MIN too (bonus coverage)

    def sched(fn, dt, n):
        return [fn(i * dt) for i in range(n)]   # I at the PRE-step time of step i+1 (t=i*dt)

    return [
        ("step_5A",                  I_ref,                 1.0, 600, 20),
        ("step_to_zero_from_hot",    [I_ref] * 300 + [0.0] * 300, 1.0, 600, 20),
        ("ramp",                     sched(ramp_fn, 1.0, 600),    1.0, 600, 20),
        ("pulse_cross_I_LEV_MIN",    sched(pulse_fn, 1.0, 600),   1.0, 600, 20),
        ("sine",                     sched(sine_fn, 1.0, 600),    1.0, 600, 20),
        ("step_5A_dt25",             I_ref,                 25.0, 100, 5),
        ("clamp_20A_asymmetry",      25.0,                  1.0, 200, 10),   # > current_clamp_A=20: trap 8
    ]


# ---------------------------------------------------------------------------
# Assertion A: raw integrator match
# ---------------------------------------------------------------------------
def _twin_from_params(params: dict, T_amb_js: float) -> TwinState:
    """Coefficients built from the LIVE PARAMS/T_AMB_JS just read out of the
    page -- NOT from params.yaml. T_amb_js (JS's T_AMB_FALLBACK_C=29.0,
    build_twin_html_fem.py) deliberately does NOT equal params["rom"]["T_amb"]
    (params.yaml's T_ambient_degC=20.0) -- seeding TwinState.T_amb from the
    wrong one would make every coil/air/disc quantity diverge from traceRom's
    own trajectory for a reason that has nothing to do with the integrator
    port, producing a false-alarm "assertion A" failure."""
    rom = RomCoeffs.from_source(params["rom"])
    lumped = LumpedCoeffs.from_source(params["lumped"])
    lev = LevCoeffs.from_source(params["lev"])
    return TwinState(rom=rom, lumped=lumped, lev=lev, T_amb=T_amb_js)


def _sample(twin: TwinState) -> dict:
    T = twin.lumped_state.T
    return {
        "t": twin.t, "beta": twin.rom_state.beta,
        "beta_eddy": twin.rom_state.beta_eddy, "beta_air": twin.rom_state.beta_air,
        "T_inner": T["inner"], "T_outer": T["outer"], "T_iron": T["iron"], "T_air": T["air"],
        "T_inner_deep": T["inner_deep"], "T_outer_deep": T["outer_deep"],
        "z": twin.lev_state.z, "v": twin.lev_state.v, "jit": twin.lev_state.jit,
    }


def _run_python_raw(twin: TwinState, I_sched, dt: float, n: int, every: int) -> dict:
    """Mirrors traceRom()'s literal loop: ONE raw _rom_step + _lev_step call
    per iteration at the caller-given dt. Deliberately calls the private
    _rom_step/_lev_step, NOT the public TwinState.step() -- traceRom itself
    never substeps (it has no access to loop()'s nSub logic, which lives
    outside romStep/levStep in the render loop), so .step()'s substep
    wrapper would compare apples to oranges here. That wrapper is exercised
    separately in _check_public_step_substeps() below."""
    twin.reset()
    out = {q: [] for q in QUANTITIES}

    def push():
        s = _sample(twin)
        for q in QUANTITIES:
            out[q].append(s[q])

    push()
    is_array = isinstance(I_sched, list)
    clamp = twin.current_clamp_A
    for i in range(1, n + 1):
        Ii = I_sched[i - 1] if is_array else I_sched
        twin._rom_step(max(0.0, min(Ii, clamp)), dt)
        twin._lev_step(Ii, dt)
        if i % every == 0:
            push()
    return out


def _max_abs_diff(a: list[float], b: list[float]) -> float:
    return max(abs(x - y) for x, y in zip(a, b)) if a else 0.0


def run_assertion_a(page, twin: TwinState, I_ref: float, I_lev_min: float) -> tuple[bool, list[dict]]:
    rows = []
    ok = True
    for name, I_sched, dt, n, every in _build_schedules(I_ref, I_lev_min):
        js_out = page.evaluate(
            "(args) => window.twinDebug.traceRom(args)",
            {"I": I_sched, "dt": dt, "n": n, "every": every},
        )
        py_out = _run_python_raw(twin, I_sched, dt, n, every)
        diffs = {q: _max_abs_diff(js_out[q], py_out[q]) for q in QUANTITIES}
        worst_q = max(diffs, key=diffs.get)
        case_ok = diffs[worst_q] <= TOL_INTEGRATOR_ABS
        ok &= case_ok
        rows.append({"case": name, "n_samples": len(js_out["t"]), "diffs": diffs,
                      "worst_q": worst_q, "worst": diffs[worst_q], "ok": case_ok})
    return ok, rows


def _check_public_step_substeps(twin: TwinState) -> bool:
    """Not part of assertion A (traceRom has no substep behavior to pin
    against) -- a small self-contained sanity check that TwinState.step()'s
    OWN JS-derived substep rule (nSub=ceil(dt/(tau*0.05)), see
    build_twin_html_fem.py loop():~2718) actually engages nSub>1 for dt=25s
    against the REAL baked tau, i.e. that the "dt=25s" test case is not
    vacuous for the substep machinery even though traceRom itself bypasses
    it. Also cross-checks .step(I, 25) against nSub manual calls to
    _rom_step for internal self-consistency."""
    n_sub = math.ceil(25.0 / (twin.rom.tau * 0.05))
    if n_sub <= 1:
        print(f"  [substep] WARNING: dt=25s gives nSub={n_sub} for tau={twin.rom.tau:.1f}s -- "
              f"not exercising nSub>1, the 'dt=25s' case only tests raw-Euler-at-larger-dt.")
        return True   # informational only, never fails the run
    twin.reset()
    twin.step(5.0, 25.0)
    via_public = _sample(twin)

    twin.reset()
    dt_sub = 25.0 / n_sub
    for _ in range(n_sub):
        twin._rom_step(max(0.0, min(5.0, twin.current_clamp_A)), dt_sub)
    twin._lev_step(5.0, 25.0)
    via_manual = _sample(twin)

    worst = max(abs(via_public[q] - via_manual[q]) for q in QUANTITIES)
    print(f"  [substep] dt=25s -> nSub={n_sub} (tau={twin.rom.tau:.1f}s); "
          f".step() vs manual nSub x _rom_step: max|Δ|={worst:.3e}")
    return worst < 1e-12


# ---------------------------------------------------------------------------
# Assertion B: bake freshness
# ---------------------------------------------------------------------------
def _max_rel_diff(a, b, path: str = "") -> tuple[float, str]:
    if isinstance(a, dict):
        worst = (0.0, path)
        for k in a:
            d, p = _max_rel_diff(a[k], b[k], f"{path}.{k}" if path else k)
            if d > worst[0]:
                worst = (d, p)
        return worst
    fa, fb = float(a), float(b)
    denom = max(abs(fa), abs(fb), 1e-12)
    return abs(fa - fb) / denom, path


def run_assertion_b(params: dict) -> tuple[bool, dict]:
    from config import load_config
    from em_solver import compute_losses
    from build_twin_html_fem import lumped_physics
    from rom import ThermalROM

    cfg = load_config()
    em = compute_losses(cfg)
    lumped_fresh = lumped_physics(cfg, em)
    rom_fresh = ThermalROM().build(cfg, em_losses=em, verbose=False)

    lumped_rel, lumped_path = _max_rel_diff(lumped_fresh, params["lumped"])
    tau_rel = abs(rom_fresh.tau - params["rom"]["tau"]) / max(
        abs(rom_fresh.tau), abs(params["rom"]["tau"]), 1e-12)

    ok = lumped_rel <= TOL_STALE_REL and tau_rel <= TOL_STALE_REL
    return ok, {"lumped_rel": lumped_rel, "lumped_worst_path": lumped_path, "tau_rel": tau_rel}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    with sync_playwright() as pw:
        browser, page = _open_page(pw)
        try:
            params = page.evaluate("() => window.twinDebug.PARAMS")
            T_amb_js = page.evaluate("() => window.twinDebug.T_AMB_JS")

            twin = _twin_from_params(params, T_amb_js)
            print(f"Seeded from live page: T_amb_js={T_amb_js}  (params['rom']['T_amb']="
                  f"{params['rom']['T_amb']}, deliberately different -- see module docstring)")
            print(f"I_ref={twin.rom.I_ref}A  tau={twin.rom.tau:.2f}s  I_LEV_MIN={twin.lev.I_lev_min:.3f}A\n")

            ok_a, rows = run_assertion_a(page, twin, twin.rom.I_ref, twin.lev.I_lev_min)

            header = f"{'case':<24}{'samples':>8}  " + "  ".join(f"{q:>13}" for q in QUANTITIES)
            print(header)
            print("-" * len(header))
            for r in rows:
                line = f"{r['case']:<24}{r['n_samples']:>8}  " + "  ".join(
                    f"{r['diffs'][q]:>13.3e}" for q in QUANTITIES)
                print(line + ("  PASS" if r["ok"] else "  FAIL"))
            print()

            substeps_ok = _check_public_step_substeps(twin)
            print()
        finally:
            browser.close()

    ok_b, b_info = run_assertion_b(params)

    print(f"[A] Integrator match (tol={TOL_INTEGRATOR_ABS:g} abs): "
          f"{'PASS' if ok_a else 'FAIL'}")
    if not ok_a:
        print("    INTEGRATOR MISMATCH -- twin_core.py has diverged from the baked JS engine "
              "(a real port bug, not a tolerance issue -- see module docstring).")

    print(f"[B] Bake freshness (tol={TOL_STALE_REL:g} rel): "
          f"lumped worst={b_info['lumped_rel']:.3e} @ {b_info['lumped_worst_path']}  "
          f"tau={b_info['tau_rel']:.3e}  {'PASS' if ok_b else 'FAIL'}")
    if not ok_b:
        print("    outputs/digital_twin_fem.html is STALE -- re-run python build_twin_html_fem.py")

    all_ok = ok_a and ok_b and substeps_ok
    print(f"\n{'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
