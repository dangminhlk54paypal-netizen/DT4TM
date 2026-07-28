# Plan: Digital Twin via PyVista (level C) — parallel with HTML version

## Context

The repo currently has **two** twins: `digital_twin.py` (matplotlib, 2D heatmap, disc only) and
`outputs/digital_twin_fem.html` (three.js, complete 3D, truly the "level C" version). The user
wants to add a **PyVista desktop 3D** version achieving feature parity with the HTML version,
existing in parallel rather than replacing it.

The core issue discovered during assessment: **physics is being split.**
`build_twin_html_fem.py` computes *coefficients* in Python (`lumped_physics`, `lev_params`,
`compute_em_field_lines`…) then bakes them to JS, but **the 3 time-integrators exist only
in JS**. Writing a PyVista version means porting those 3 to Python → creating a second copy
of the same physics. This repo has prior history of exactly that bug type (WP-PEAK missed call site
`run_benchmark_validation`, CLAUDE.md:186-196). The plan therefore makes **preventing divergence** the
central axis, not building 3D.

The user has chosen: **disciplined approach** (twin_core.py as SSOT + harness pins Python≡JS first,
3D afterward) and **minimal HTML edits** (add only `traceRom()`, touch nothing else).

---

## Assessment of prior reasoning (Haiku) — not achieved

| Point | Haiku said | Actual measurement |
|---|---|---|
| PyVista status | "⚠️ Optional / Ready", has `--pyvista` flag | `pyvista` **and** `vtk` both **not installed**. `plot_pyvista()` ([visualize.py:324](visualize.py#L324)) is code **never run** |
| Physics source | Suggested writing new script using only `rom` | Completely missed: `build_twin_html_fem.py` **import-safe** (0.62s) and already has **14 reusable functions** |
| Real work | No mention | 3 integrators (dual-β, coil 2-node RC, levitation) are **JS-only**, must port — this is the hard part |
| Pseudocode | `add_slider_widget` + callback | Slider callback **cannot** create time evolution. Need `add_timer_event`; `Plotter.add_callback` **does not exist** |
| Risk | No mention | Didn't raise SSOT/divergence issue, didn't raise installation hurdle (~400 MB VTK) |

Conclusion: **"feasible" conclusion was right, but the path was wrong** — would lead to a second
physics copy drifting away from the HTML version with no detection mechanism.

---

## Verified facts (use as evidence, no re-measurement needed)

- `pyvista`/`vtk` **not installed**. `playwright` **present**. **No pytest, no `tests/`** →
  per repo convention: each module self-tests in `if __name__ == "__main__"`.
- ROM rebuild = **1.34 s** (`compute_losses` 1.30s + `ThermalROM.build` 0.04s).
  Docstring [digital_twin.py:551](digital_twin.py#L551) says "5-10s" is **stale** → fix it.
- `build_twin_html_fem.py` import-safe (guard `__main__` at :2851). Reusable:
  `lumped_physics`, `lev_params`, `compute_em_field_lines`, `compute_eddy_field`,
  `compute_eddy_fraction`, `power_supply_params`, `revolve`, `revolve_ring`,
  `build_disc_mesh`, `solve_plate_variant`, `build_octagonal_base/frame`,
  `build_separator_rings`, `build_solid_core`, `plate_variant_radii_mm`.
- ⚠️ `compute_em_field_lines` calls `matplotlib.use("Agg")` ([:260-262](build_twin_html_fem.py#L260))
  and is called from `solve_plate_variant` → **every disc swap forces backend to Agg**.
  → Rules out "separate matplotlib chart window". Must use `pv.Chart2D`.
- `revolve()` returns **triangle soup** `(nTri,3,3) float32`, mm, **no index**.
- `rom.res_ref` contains **disc only**, ~697 nodes, `z` **local** (starts at 0). Coil/iron not in it.
- `window.twinDebug` **already exists** ([:1972](build_twin_html_fem.py#L1972)) and exposes `sim`, `lev`,
  `levStep`, `levGapEqMm`, `levZeta`, `I_LEV_MIN`, `ROM`, `PARAMS`, `T_AMB_JS`.
  **Does not expose** `romStep`/`resetSim`/`paused`.
- ⚠️ HTML **requires network**: importmap pulls `https://unpkg.com/three@0.160.0/…` ([:1315](build_twin_html_fem.py#L1315)).
  Offline → module doesn't run → `twinDebug` undefined → harness fails with gibberish error.
- ⚠️ `T_AMB_FALLBACK_C = 29.0` ([:1343](build_twin_html_fem.py#L1343)) ≠ `params.yaml T_ambient_degC: 20.0`.
  → Harness **must** seed Python from `twinDebug.T_AMB_JS`, not from params.yaml.
- ⚠️ **Third call site** of `DigitalTwin`: [data_io.py:249](data_io.py#L249) (used at :256, :277).
  This is exactly the WP-PEAK trap in refactoring.

---

## Architecture decision

```
params.yaml
   │
   ├─► build_twin_html_fem.lumped_physics / lev_params      ◄── SSOT: COEFFICIENTS (keep in original location)
   │        │
   │        ├──────────────► twin_core.py                   ◄── SSOT: INTEGRATORS (Python, new)
   │        │                     ▲                                    │
   │        │                     │                    ┌───────────────┼───────────────┐
   │        │                     │                    ▼               ▼               ▼
   │        │                     │            digital_twin.py  digital_twin_   data_io.py
   │        │                     │            (matplotlib)      pyvista.py      (calibrate)
   │        │                     │
   │        └──────────────► baked JS ──── xval_twin.py ────┘   ◄── PIN: Playwright, tol 1e-9
```

**Two new modules, not one:**
- `twin_core.py` — **numpy + stdlib only**. 3 integrators + `SCENARIOS`. This constraint is *verifiable*:
  `python -c "import sys,twin_core; assert 'em_solver' not in sys.modules and 'matplotlib' not in sys.modules"`.
  Necessary because harness must load integrators **without** pulling in the `matplotlib.use("Agg")` landmine.
- `twin_model.py` — heavy part (config/em_solver/rom/build_twin_html_fem): resolve plate, cache, coefficients.

**Keep exactly ONE β model.** Dual-β is a tight generalization of single-β: set `f_air=0, f_eddy=1`
to get exactly [digital_twin.py:68](digital_twin.py#L68). No physics reason to keep both →
old `DigitalTwin` deleted, all consumers import from `twin_core`.

---

## 9 traps when porting JS → Python (REQUIRED reading before writing integrator)

Each one causes O(dt) drift—not rounding noise. This is the most valuable content in the plan.

1. **Coil integrates BEFORE β**, and `coilAirDrive()` reads `T.inner`/`T.outer` **just updated**
   ([:1493-1531](build_twin_html_fem.py#L1493)). Compute all derivatives from old state then update ⇒ drift.
2. **σ scale uses total β from previous step**, not `β_eddy` ([:1489-1491](build_twin_html_fem.py#L1489)).
3. **`q_cond` computed from old `T.inner`/`T.iron`**, before node loop ([:1497](build_twin_html_fem.py#L1497)).
4. **Air node updated AFTER loop** ⇒ every node uses old air **temperature** ([:1524](build_twin_html_fem.py#L1524)).
5. **`hAEff` clamps floor `|ΔT|` at 0.1** ([:1477-1480](build_twin_html_fem.py#L1477)).
6. **β clamped ≥0 INSIDE each substep** (`Math.max(0.0,…)`, :1533/:1537), not clamped at end.
7. **`levStep` called ONCE with full `dt_sim`, NO substepping**, while `romStep` has substepping
   (:2764 vs :2718-2723).
8. **Asymmetric current clamping**: `romStep` receives `max(0, min(getI(), 20.0))` (:2721); `levStep` receives
   `getI()` **unclamped** (:2763); and [digital_twin.py:443](digital_twin.py#L443) clamps at `I_MAX≈7.78`.
   → Port **exactly like JS**, make threshold a parameter, note for cleanup in later WP.
9. **`levStep` sees I at `t_{n+1}`** (after `romStep` has pushed `sim.t`), while `romStep` sees I at
   time before each substep.

Also: JS substepping rule is `nSub = ceil(dt_sim/(tau*0.05))` (τ-aware, :2718) — **different from**
matplotlib's speed-aware rule ([:440-444](digital_twin.py#L440)). Take **JS rule**, drop the other.

---

## Work packages

Physics is proven complete **before** installing VTK. If the VTK wheel breaks, WP-HOOK/CORE/XVAL/CORE2
retain independent value and the matplotlib version still improves.

| WP | Goal | Files | Done when |
|---|---|---|---|
| **HOOK** | Expose `traceRom()` for deterministic headless comparison | `build_twin_html_fem.py` (TEMPLATE only) | HTML rebuilt, 0 JS errors, screenshot unchanged |
| **CORE** | `twin_core.py` + `twin_model.py`, 3 integrators | 2 new files | 6 self-checks PASS |
| **XVAL** | Pin Python ≡ JS to 1e-9 | new `xval_twin.py` | Green **and** proven to go red |
| **CORE2** | Delete second β model | `digital_twin.py`, `data_io.py` | `grep -c "class DigitalTwin"` = 1 |
| *— install `pyvista`/`vtk` here —* | | | |
| **GEO** | Geometry + static render | new `digital_twin_pyvista.py` | Screenshot matches HTML version |
| **LOOP** | Timer loop, sliders, telemetry | nt | ≥25 FPS, slider drag smooth |
| **VIZ** | Field lines, eddy mode, toggle | nt | 4 modes match HTML |
| **CHART** | 2 panels with `pv.Chart2D` | nt | 600s @50×, camera still rotates |
| **PLATE** | Rebuild disc on worker thread | nt | Swap disc mid-flight, no stall |
| **DOC** | Sync documentation | CLAUDE.md, docs/, README | File tree has 4 new modules |

---

## Ready-to-use prompts for Sonnet

> Each prompt is self-contained. Paste one at a time, in order. Always start a new session by
> having Sonnet read `CLAUDE.md`.

### WP-HOOK
```
Read CLAUDE.md first. Repo /Users/minh/VSCode_Repo/DT4TM.

Add EXACTLY ONE debug function to the JS template in build_twin_html_fem.py, for comparing
numerical results headlessly between Python and JS. Absolute minimum: do NOT change any physics,
DOM, layout, or render behavior.

Add to the window.twinDebug object (currently around line ~1972) exactly one key `traceRom`:

  traceRom({I, dt, n, every}) →
    - set paused = true, call resetSim()
    - run n iterations: romStep(Math.max(0, Math.min(I, 20.0)), dt) then levStep(I, dt)
      (KEEP the asymmetric current clamping between romStep and levStep — that is current behavior,
       do not "fix" it in this WP)
    - every `every` steps, record one sample
    - return {t[], beta[], beta_eddy[], beta_air[], T_inner[], T_outer[], T_iron[],
              T_air[], T_inner_deep[], T_outer_deep[], z[], v[], jit[]}

traceRom defined in module scope so it can call romStep/resetSim/paused directly —
do NOT expose those three to window (user requested minimal changes).

Verify—must print output:
1. python build_twin_html_fem.py   (rebuild, must use placeholder key — see CLAUDE.md
   "Conventions"; NEVER commit HTML file with real key)
2. Playwright: open outputs/digital_twin_fem.html, assert 0 console errors, assert
   twinDebug.traceRom({I:5,dt:1,n:5,every:1}).beta.length === 6 and all values finite
3. Screenshot before/after, confirm no visual change
```

### WP-CORE
```
Read CLAUDE.md first. Repo /Users/minh/VSCode_Repo/DT4TM.

Create twin_core.py and twin_model.py. This step ports the 3 integrators that currently exist ONLY in JS
(inside the template string of build_twin_html_fem.py) to Python, so the matplotlib version,
upcoming PyVista version, and data_io.py share a single source of truth.

twin_core.py — ONLY numpy + stdlib allowed. No config, no em_solver, no rom,
no matplotlib. This constraint is mandatory and will be checked.
  - SCENARIOS: copy verbatim from digital_twin.py:31-45
  - Frozen dataclasses RomCoeffs / LumpedCoeffs / LevCoeffs, constructible from TWO sources:
    live Python object OR flat dict (harness WP-XVAL will feed twinDebug.PARAMS directly in)
  - RomState (dual-β), LumpedState (coil 2 node + iron + shared air node),
    LevState (closed-form damped oscillation + jitter)
  - TwinState combines all three, has step(I, dt_sim) applying JS substepping rule
    nSub = ceil(dt_sim/(tau*0.05)), and PRESERVES signatures .step(I,dt) + .T_field so
    data_io.py:256/277 doesn't break

Port from build_twin_html_fem.py: romStep :1485-1545, levStep :1705-1735, constants at :1437-1457.
MUST preserve exact ORDER OF OPERATIONS from JS. Nine traps must match:
 1. Coil integrates BEFORE β; coilAirDrive() reads T.inner/T.outer JUST UPDATED (:1493-1531)
 2. σ scale uses total β from previous step, not beta_eddy (:1489-1491)
 3. q_cond computed from old T.inner/T.iron, before node loop (:1497)
 4. Air node updated AFTER loop → every node uses old T_air (:1524)
 5. hAEff clamps floor |ΔT| at 0.1 (:1477-1480)
 6. β clamped ≥0 INSIDE each substep (:1533/:1537), not at end
 7. levStep called ONCE with full dt_sim, NO substepping (:2764 vs :2718-2723)
 8. Asymmetric current clamping: romStep uses min(I,20.0), levStep unclamped. Port exactly,
    make threshold a parameter, note TODO for later WP cleanup
 9. levStep sees I at t_{n+1} (after romStep pushed sim.t)

twin_model.py — heavy part: resolve_active_plate(cfg) (extracted from closure digital_twin.py:141-173,
keep honest label fallback), PlateCache (digital_twin.py:176),
i_max_for(cfg) (:236), build_plate_variant() wrapping solve_plate_variant,
coeffs_from_live(cfg, em, rom) calling lumped_physics/lev_params.
do NOT move lumped_physics/lev_params out of build_twin_html_fem.py — that file is checked by
Playwright after every change, touching it adds unnecessary risk.

Verify — `python twin_core.py` must print PASS for all 6:
 1. f_air=0 ⇒ matches digital_twin.py:68 error <1e-12 over 600s
 2. T_inner(t→∞) matches coilTss_inner (build_twin_html_fem.py:2271-2274) error <1e-6
 3. β(t→∞) = s²·s_σ
 4. z(t→∞) = levGapEqMm(I); I = I_LEV_MIN ⇒ z→0
 5. air node energy balance closes
 6. python -c "import sys,twin_core; assert 'em_solver' not in sys.modules and 'matplotlib' not in sys.modules"
```

### WP-XVAL
```
Read CLAUDE.md first. Repo /Users/minh/VSCode_Repo/DT4TM. Requires WP-HOOK and WP-CORE done.

Create xval_twin.py (placed flat in repo root per CLAUDE.md convention) — pin twin_core.py against
baked JS integrators using Playwright (already installed).

Method: open outputs/digital_twin_fem.html, read twinDebug.PARAMS and twinDebug.T_AMB_JS,
build twin_core coefficients FROM THAT DATA ITSELF (not from params.yaml — T_AMB_FALLBACK_C=29.0
in JS differs from T_ambient_degC=20.0 in params, wrong seed will fake integrator error). Call
twinDebug.traceRom(...) then run the exact dt schedule in Python, compare each quantity.

REQUIRED: block network. HTML loads three.js from unpkg via importmap (build_twin_html_fem.py:1315);
offline means twinDebug doesn't exist and error is gibberish. Use page.route("**/unpkg.com/**")
serve from cache outputs/.jscache/ (outputs/ already gitignored), self-download on first run.

Test suite: step 5A; step-to-0 from hot state; ramp; pulse crossing I_LEV_MIN; sine;
dt=1s and dt=25s (trigger nSub>1); 20A (trigger asymmetric clamping trap).

TWO INDEPENDENT assertions, error messages MUST DIFFER:
 A. Integrator match, absolute tolerance 1e-9. Rationale (write in docstring): JS Number is IEEE-754
    float64 like numpy; same forward Euler, same dt, same operation order ⇒ only ULP noise from
    pow/exp/sin/log. Every ODE here is contracting (all eigenvalues negative) so noise decays,
    no accumulation. Over 600 steps, error ~1e-14 K on background 60 K rise. Over 1e-9 = PORT ERROR,
    no exception for "Euler must drift".
 B. Stale HTML: PARAMS.lumped ≈ lumped_physics(cfg, compute_losses(cfg)) relative error 1e-6,
    and PARAMS.rom.tau ≈ ThermalROM().build(cfg,em).tau.
    Error message: "outputs/digital_twin_fem.html is STALE — re-run python build_twin_html_fem.py"
    (this is exactly the bug class that happened at commit d4f73d6/WP-5)

Add to docstring: thresholds 1e-3 K / 1e-4 mm ONLY apply if Python intentionally switches integrator.
Write it now so next session doesn't silently loosen 1e-9 to make test pass.

Verify: `python xval_twin.py` prints max-abs table per quantity, PASS, exit 0.
NOT DONE until proven it can go RED: temporarily reverse coil integrator to after β update in template,
rebuild, re-run, paste red output, then revert. This repo has WP-PEAK history — a pinning test
never seen red is a fake test.
```

### WP-CORE2
```
Read CLAUDE.md first. Repo /Users/minh/VSCode_Repo/DT4TM. Requires WP-CORE and WP-XVAL done.

Delete the second β model. After this WP repo has EXACTLY ONE Python integrator.

1. digital_twin.py: delete class DigitalTwin (:51-86), SCENARIOS (:31-45),
   _build_rom_for_plate (:92-123); import from twin_core/twin_model. Replace speed-aware
   substepping logic (:440-444) with JS's τ-aware rule now in twin_core.
2. data_io.py:249 — THIS IS THE EASIEST SITE TO MISS (exactly WP-PEAK bug pattern). Switch to
   twin_core. Check both :256 and :277.
3. Fix stale docstring at digital_twin.py:551: measured ROM rebuild is ~1.3s, not "5-10s".

Verify, print output for all three:
 - python digital_twin.py --no-em --speed 50  (window opens, T rises, radio disc swap rebuilds)
 - python data_io.py --mode calibrate --csv mock_sensor_data.csv  (still runs)
 - python xval_twin.py  (still green)
 - grep -rn "class DigitalTwin" *.py  → exactly 1 result, in twin_core.py
```

### WP-GEO → WP-PLATE (3D phase)
```
Read CLAUDE.md first. Repo /Users/minh/VSCode_Repo/DT4TM. Requires WP-CORE2 done.

Install first: pip install "pyvista>=0.45" "vtk>=9.3,<9.7"   (~400MB; arm64 macOS py3.11 wheel
prebuilt, no source compilation). Add to requirements.txt as OPTIONAL BLOCK with comment
not required for solver/digital_twin.py/build_twin_html_fem.py. Floor 0.45 because need
interaction_event (0.38+ renamed from event_type) and PolyData.from_regular_faces (0.44+).

Create digital_twin_pyvista.py. Must IMPORT SUCCESSFULLY without VTK (try/except around import pyvista,
exactly per visualize.py:327-332 pattern) so --self-check runs headless without VTK. No VTK
but interactive mode called → print correct pip install line, point to digital_twin.py, sys.exit(2).

Work sequentially, verify each step before moving to next:

WP-GEO — geometry + static render:
  - Reuse build_octagonal_base/frame, build_separator_rings, build_solid_core,
    revolve_ring, build_disc_mesh from build_twin_html_fem.py. Do NOT rewrite geometry.
  - Triangle soup (nTri,3,3) → PolyData: V = soup.reshape(-1,3);
    faces = arange(len(V)).reshape(-1,3); pv.PolyData.from_regular_faces(V, faces)
  - ABSOLUTELY do NOT weld/clean disc mesh: dT_eddy/dT_air/Je index by soup vertex
    (build_twin_html_fem.py:589-598); mesh.clean() merges and REORDERS points, silently
    misaligning all three scalar arrays while shape looks fine. Use smooth_shading=False.
    Only weld coil/core/ring/wood meshes (no per-vertex fields).
  - Keep original Z-up mm coordinates, do NOT switch to Y-up like JS (build_twin_html_fem.py:1406-1410) —
    VTK has no such convention. Set pl.camera.up = (0,0,1).
  - Verify: python digital_twin_pyvista.py --screenshot outputs/twin_pv.png --no-show
    → compare to docs/real_model.png and HTML version; 0 VTK warnings on stderr

WP-LOOP — real-time loop:
  - USE pl.add_timer_event(max_steps=2**31-1, duration=33, callback=...) register BEFORE pl.show().
    do NOT use show(interactive_update=True)+update() (flips event loop ownership, on macOS
    starves Cocoa event loop). Plotter.add_callback does NOT EXIST, don't use.
  - Inside callback: dt_wall = min(now-last, 0.1) — exactly 100ms ceiling like JS
    (build_twin_html_fem.py:2711); then twin.step(); then pl.render() exactly once.
  - Per-frame scalars: assign directly mesh["Temperature"] = T. update_scalars DEPRECATED since 0.43.
  - Levitation: set actor.position = (0,0,z...) — only changes 4×4 matrix, no VBO re-upload.
  - Slider: pl.add_slider_widget(..., interaction_event='always') — default 'end',
    omit and slider drag won't update. pointa/pointb are normalized viewport coordinates.
    MAX 3 sliders (I, Dial, Speed) lower-left strip; PyVista has no layout manager,
    4th slider will overlap annotation.
  - Remaining: use pl.add_key_event (Space=pause, r=reset, 1-4=mode, [/]=swap disc) and
    add_checkbox_button_widget (position in PIXELS, different from slider).
  - Disc selector ABSOLUTELY do NOT use slider: interaction_event='always' triggers
    1.3s rebuild per pixel drag.
  - Verify: python digital_twin_pyvista.py --speed 50 → disc reddens, coil heats,
    disc lifts and settles; drag I slider mid-flight no stutter; ≥25 FPS shown at corner

WP-VIZ — field lines + eddy:
  - compute_em_field_lines returns 21 contours {r,z,amp}. Build EXACTLY ONE PolyData, hand-stitch
    cell `lines` array, place at 4 azimuth corners (0/90/180/270°) → 84 polylines.
    do NOT use pv.MultipleLines or pv.lines_from_points: they create ONE bent line through
    all points, joining tail of contour k to head of contour k+1.
  - Eddy: keep both 'Temperature' and 'Je' on same mesh, switch via set_active_scalars.

WP-CHART — use pv.Chart2D + pl.add_chart (REQUIRED, not matplotlib: disc swap calls
  compute_em_field_lines → matplotlib.use("Agg") (build_twin_html_fem.py:260-262) kills
  live matplotlib window). Two separate charts (T and I) because Chart2D has only one y-axis.
  Sample 1 per SIMULATION SECOND, deque(maxlen=3600) — like JS :2730-2745; only call
  LinePlot2D.update() when actually new sample, do NOT call at 30 FPS.
  REQUIRED pl.set_chart_interaction(False), else click near chart will swallow camera rotation.

WP-PLATE — rebuild disc on worker thread:
  - solve_plate_variant doesn't touch VTK so worker thread safe; ALL VTK operations must
    stay on main thread. Worker finishes compute, assign to a cell, on_tick retrieves and swaps.
  - Call matplotlib.use("Agg") ONCE on main thread at startup, so worker call becomes
    no-op (matplotlib.use not thread-safe).
  - Keep simulation running on OLD ROM during rebuild, swap at frame boundary. Much better than
    matplotlib version now (paused + blocking GUI thread, digital_twin.py:296-323).
  - Wrap redirect_stdout around solve_plate_variant (em_solver prints unconditionally).
  - Verify: swap disc mid-flight, window still responsive; check tau, I_LEV_MIN, B_max, J_max
    ALL update per disc (bug from missing rom_params_v field at build_twin_html_fem.py:713-722).
```

### WP-DOC
```
Read CLAUDE.md first. Sync documentation after WP-PLATE done.
- CLAUDE.md "Code status" section: add twin_core.py (SSOT integrator), twin_model.py,
  digital_twin_pyvista.py, xval_twin.py; make clear xval_twin.py pins JS to twin_core
- docs/ARCHITECTURE.md: file tree + data flow
- docs/CHANGELOG.md: narrative WP-HOOK→WP-DOC
- README.md: run commands + note pyvista is optional dependency
At same time fix detected drift: CLAUDE.md WP-Z0 section still says z_gap_5A_mm=4.1/z_decay_mm=13.6,
but params.yaml:286-289 already 11.7/11.79 (has comment "superseding WP-Z0").
params.yaml is SSOT — fix CLAUDE.md to match.
```

---

## Overall verification

Run in order, each command must print output before claiming done:

```bash
python twin_core.py                       # 6 self-checks PASS
python xval_twin.py                       # max-abs table, PASS, exit 0
python digital_twin.py --no-em --speed 50 # matplotlib version still works
python data_io.py --mode calibrate --csv mock_sensor_data.csv
python build_twin_html_fem.py             # HTML still builds (placeholder key!)
python digital_twin_pyvista.py --self-check          # runs even without VTK
python digital_twin_pyvista.py --screenshot outputs/twin_pv.png --no-show
grep -rn "class DigitalTwin" *.py         # exactly 1 result
```

---

## Known risks

- **VTK ~400 MB** on a repo with only ~6 real lines in `requirements.txt`. Make it **optional**, floor 0.45.
- **macOS needs real window server** — run from local session, not SSH. `pv.start_xvfb()` Linux-only.
- **`pv.Chart2D` uglier than matplotlib** (coarse font, few theme controls). Accept: matplotlib
  option already ruled out by `matplotlib.use("Agg")`.
- **~20 FPS stutter during 1.3s rebuild** because scipy holds GIL. Acceptable; don't use
  multiprocessing (pickle cfg + re-import 1.5s costs more than what it saves).
- **Endgame not done**: generate JS integrator from `twin_core` (or use pyodide) to eliminate
  the copy entirely. Acknowledge, not now.
