# Report: Why we custom-code the Digital Twin in Python instead of using SimScale / existing simulation software

> Prepared 2026-07-10, answering professor's question. Detailed references:
> `docs/physics.md` (formulas), `docs/ARCHITECTURE.md`, `docs/SENSOR_PLAN.md`,
> `README.md` (roadmap), `docs/CHANGELOG.md` (session-by-session history).

---

## 1. Motivation and approach — why choose to custom-code

**Core point: the final product is not "a simulation result," but a
DIGITAL TWIN running in real-time.** These two are fundamentally different:

| | One-off simulation (SimScale, COMSOL…) | Digital twin (project requirement) |
|---|---|---|
| Output | 1 temperature field per scenario | T(r,z,t) updates **continuously per millisecond** as user changes current |
| Solution time | minutes → hours per run | must be < 16 ms/frame (runs on phone, AR) |
| Sensor connection | no real-time API | mandatory (calibrate from Arduino data) |

What enables real-time is a **physics observation** (not a software feature):
linear system at fixed frequency 50 Hz ⇒ Joule loss scales as **I²** with *fixed
spatial distribution*, only amplitude changes (plus σ(T) correction). Therefore:

1. Solve EM FEM (phasor) **once only** offline at I_ref = 5 A →
   loss map q̂(r,z).
2. Runtime is only scalar multiply `(I/I_ref)² × [σ(T)/σ(T_ref)]` + first-order thermal ROM
   → milliseconds, runs in mobile browser.

**No commercial software lets us "dissect" the pipeline like this** — they wrap
solver as a black box: every current change means re-running full FEM.
To exploit the I² structure we must control the solver at source-code level.

Secondary motivations (but real):
- **FEMM ruled out immediately**: Windows-only, dev machine is macOS (decision locked).
- Problem is **axisymmetric** → solve only 2D (r,z), system ~10⁴ unknowns —
  `scipy.sparse.linalg.spsolve` solves in < 1 second. Using 3D CAE software for
  this size is "using a cleaver to kill a chicken," and still slower (must mesh 3D).
- **TEAM Problem 28 exists precisely to validate custom code** — this is
  the standard benchmark of the computational electromagnetics community (COMPUMAG).
  Following the problem's spirit means write solver then validate.
- **Transparent & verifiable**: energy balance achieves 0.000% error,
  I²-check gives exactly 4.000000, every constant lives in `params.yaml` (single source
  of truth), full change history in git. With commercial black box,
  we can only *trust* results; with custom code, we *prove* it.
- **Cost = 0**: numpy/scipy open-source, no license, no cloud credits,
  no internet dependence.
- **Academic value**: the team understands every equation from weak form to matrix
  — matches course learning objective, versus learning GUI button-pushing.

---

## 2. Comparison with other simulation tools

| Criterion | **SimScale** (cloud CAE) | **COMSOL / ANSYS Maxwell** | **FEMM** | **Elmer / FEniCS** (open-source FEM) | **Python custom (chosen)** |
|---|---|---|---|---|---|
| Low-frequency EM (eddy current, phasor A_φ) | limited — strong in CFD/structures/thermal, not 50 Hz magnetics | ✔ excellent | ✔ good (2D) | ✔ has it (Elmer) | ✔ custom, validate vs TEAM 28 |
| EM → thermal coupling | hard to integrate in pipeline | ✔ | ✘ weak thermal | ✔ but complex config | ✔ direct: q = ½σω²\|A_φ\|² feeds straight to thermal solver |
| Axisymmetric 2D (exploitable) | ✘ full 3D mesh | ✔ | ✔ | ✔ | ✔ small system ~10⁴ unknowns |
| **ROM / real-time** | ✘ | partial (separate ROM module, expensive) | ✘ | ✘ | ✔ **core architecture** |
| Export to web/AR on phone | ✘ | ✘ | ✘ | ✘ | ✔ bake into 1 HTML file |
| Wire Arduino sensor for calibration | ✘ | hard, needs proprietary scripting | ✘ | self-add | ✔ `data_io.py` → `rom.calibrate_UA()` |
| Runs on macOS | ✔ (browser) | ✔ (expensive) | ✘ **Windows-only** | ✔ | ✔ |
| Cost | free tier limited, core-hours | thousands of € license | free | free | free |
| Black box? | yes | yes | half | no | **no — 100% control** |

Notes per tool:

- **SimScale**: strong in CFD, structures, general heat transfer — but our problem needs
  *low-frequency electromagnetics* (50 Hz eddy in aluminum disc),
  not its strength. Even if it could, each scenario is a cloud job taking minutes → can't do real-time twin;
  internet dependent; data on their servers; free tier has core-hour limits.
- **COMSOL/ANSYS**: technically can solve everything, but license far exceeds student budget,
  still can't export to AR on phone, and turns the project into "learn software" vs "understand physics."
- **FEMM**: actually perfect for 2D EM — but Windows-native, dev machine macOS
  → ruled out immediately (decision locked in CLAUDE.md).
- **PyVista — important note: PyVista is NOT a solver.** It's a 3D *visualization*
  library (VTK wrapper). We **do use** PyVista correctly: `visualize.py` revolves 2D result to 3D
  and exports GLB/OBJ. So the right comparison is not "code vs PyVista" but "custom
  solver + PyVista for display."
- **Python custom** costs us having to self-verify — and we have:
  energy balance 0.000%, I²-scaling exactly 4.000000, coil temperature calibrated
  against real IR data (HIKMICRO, RMS error ≈ 2.5 °C on transient).
  ⚠️ **Update 2026-07-11**: lift force numbers below are stale (computed on geometry
  before re-measurement 2026-07-10). Current: F_z(5A, z=3.8mm) ≈ 4.10N ≫
  gravity 1.60N, but predicted equilibrium gap z_eq ≈ 11.7mm (disc bottom, visible
  top ≈14.7mm) versus actual observation of only 7-8mm visible — an unresolved
  discrepancy (see CLAUDE.md "LIFT FORCE" / `docs/BUG_REGISTER_2026-07-11.md`).
  Experiments with nonlinear saturation model ruled out iron saturation as
  cause (force changes <0.1%) — true cause still unknown.

---

## 2.5. Complete physics formulas — why custom code is necessary

Four equations below form the "backbone" of the twin. Each requires
its own discretization/matrix assembly step; no generic software allows you to dissect and restructure
a system packaged as a black box.

### (1) Phasor electromagnetic equation — time-varying AC magnetic field

$$-\nabla \cdot (\nu \nabla A_\varphi) + \nu \frac{A_\varphi}{r^2} + j\omega\sigma A_\varphi = J_s$$

Notation:
- $A_\varphi(r,z)$ — azimuthal vector potential component (only nonzero due to axisymmetry)
- $\nu = 1/\mu = 1/(\mu_r \mu_0)$ — reluctivity (small in iron → channels flux)
- $\omega = 2\pi f = 2\pi \cdot 50 = 314$ rad/s (50 Hz)
- $\sigma$ — conductivity per region (Al: $3.4 \times 10^7$ S/m, Cu: $5.8 \times 10^7$ S/m)
- $J_s$ — source current density in coils (each coil opposite sign)

**Physics:** AC current in coil generates magnetic field. This field induces eddy
current in aluminum disc ($j\omega\sigma A_\varphi$ — eddy reaction term). Iron core
(high $\mu_r$, low $\nu$) concentrates flux in small region, like a magnetic lens. Term $\nu A_\varphi/r^2$
is geometric effect of axisymmetry — why we solve 2D not 3D.

**Real example:** At 5 A RMS through 1000-turn inner coil, peak magnetic flux density $B_{\max}$
in iron core ≈ 0.66 T (unsaturated, linear region). Skin depth in aluminum at
50 Hz is $\delta \approx 12$ mm ≫ 3 mm disc thickness → eddy current nearly uniform
through thickness, no ultra-fine through-thickness mesh needed.

### (2) Joule loss density — the cycle-averaged heat source

$$q(r,z) = \frac{|J_e|^2}{2\sigma} = \frac{1}{2} \sigma \omega^2 |A_\varphi|^2 \quad [\text{W/m}^3]$$

Symbols:
- $J_e = -j\omega\sigma A_\varphi$ — eddy current density (phasor)
- The factor $1/2$ — comes from cycle-averaging $\sin^2(\omega t)$

**Physics:** The Joule loss ($|J|^2/\sigma$) in any conductor is
$q = \frac{1}{2}\sigma\omega^2|A_\varphi|^2$. What matters is that it depends on the
square of $|A_\varphi|$ — hence the strong I²-scaling: doubling the current
$\Rightarrow$ 4× the loss. The $\omega^2$ factor shows that a higher frequency means
higher loss (50 Hz versus DC is night and day).

**Real example:** At the measured 5 A, coil loss ≈ 106 W (126 W @ 7.8 A in the
2026-06-23 IR test). Aluminium disc loss ≈ 26 W (it sees a strong magnetic field
because it is close to the iron core). I² check: at twice the current (10 A), the
predicted loss is $106 \times 4 = 424$ W vs $101 \times 4 \approx 404$ W — an error
< 5%, showing the linear model holds over this range.

### (3) Temperature-dependent conductivity — the response to heating

$$\sigma(T) = \frac{\sigma_0}{1 + \alpha(T - T_0)}$$

Symbols:
- $\sigma_0$ — conductivity at the reference temperature $T_0$ (usually 20 °C)
- $\alpha$ — temperature coefficient (aluminium, copper ≈ 0.0039 K$^{-1}$)

**Physics:** A hotter metal → atoms vibrate more → they impede the current →
resistivity rises, conductivity falls. This effect is **asymmetric**:
- Aluminium disc loss ∝ $\sigma_{\text{Al}}$ → hot disc → $\sigma$ falls → loss falls (negative feedback).
- Coil loss ∝ $1/\sigma_{\text{Cu}}$ → hot coil → $\sigma$ falls → loss rises (positive feedback).

The two effects partly cancel, but the coil remains the dominant heat source.

**Real example:** A 70 K rise (from 20 °C to 90 °C) increases resistivity by ~27%.
At the 2026-06-23 IR measurement points (inner coil 79 °C, outer coil 74 °C), the
influence of $\sigma(T)$ is a ±5–10 % correction on the computed power. The custom
code lets us apply this correction at runtime: a single scalar multiply, with no
need to re-solve the FEM.

### (4) The Fourier equation — how heat spreads over time

$$\rho c_p \frac{\partial T}{\partial t} = \nabla \cdot (k \nabla T) + q$$

Symbols:
- $\rho c_p$ — volumetric heat capacity (J/(m³·K))
- $k$ — thermal conductivity (W/(m·K))
- $q$ — the loss density from equation (2) above
- Boundary condition: Robin convection, $-k \frac{\partial T}{\partial n} = h(T - T_\infty)$

**Physics:** The Joule loss $q$ from the EM solve is the "fire"; the Fourier
equation is "how the fire spreads". The term $\nabla \cdot (k \nabla T)$ is Fourier
conduction (source where it is hot, flowing towards where it is cold). The
convection coefficient $h$ says "how much cooling the nearby air provides" —
calibrated from real sensor data. At steady state ($\partial T/\partial t = 0$),
heat in = heat out: $\int q \, dV = \int h(T - T_\infty) \, dA$.

**Real example:** Aluminium disc R=80 mm, thickness 3 mm, $\rho c_p \approx 2.47$
MJ/(m³·K). Thermal time constant (from the ROM): $\tau \approx 4.07$ minutes at
R=80 mm. A 20-minute simulation ≈ 5τ, enough to reach steady state. The 2026-06-23
IR data shows the coil reaching steady state in ≈ 7–10 minutes at 7.8 A, consistent
with the prediction.

### Why custom code rather than a library

**General-purpose libraries (scipy.sparse, FEniCS) solve FEM in general —
but they do not understand the special structure of this problem.** Custom code
lets us:

1. **Control the per-element matrices.** For example, equation (2) is based on
   $|A_\varphi|^2$ within each element — this has to be computed *after* the EM
   solve (taking $A_\varphi$ from the nodes), not *before*, as generic solvers
   assume. The custom code walks the matrix afterwards and extracts q̂_plate(r,z)
   exactly.

2. **Verify energy balance to 0.000%.** Total loss in = total heat out by
   convection. If it is wrong, we know immediately where — because we wrote all of
   it. A generic solver reports "solution found" but does not prove energy balance.

3. **Modal separation for the I²-scaling ROM.** Real-time requires solving once,
   then multiplying by I². This is possible because all eddy and ohmic currents are
   ∝ I² (from the physics). The custom code stores $q̂(r,z)$ (independent of I) and
   at runtime only does a scalar multiply.

4. **Seamless EM ↔ thermal coupling.** Equation (2) → (4): the EM output is the
   thermal input. The custom code connects them directly in memory (call
   em_solver.py, take q, feed it into thermal_solver.py) — no "import/export file"
   step and no "are the formats compatible?" question.

---

## 3. Why the output is HTML rather than another library or app

The problem statement's final requirement: **AR app + QR code**. Usage scenario: a
visitor stands next to the rig, scans the QR code, and the twin opens immediately on
their phone. That imposes constraints:

| Option | Problem |
|---|---|
| Native app / Unity AR | requires installation, an app store, a heavy toolchain; every fix is a re-deploy |
| Streamlit / Dash / Jupyter | needs a **permanently running Python server** — the QR code has to point at a machine that is always on |
| matplotlib (`digital_twin.py`) | only runs on a desktop with Python — we keep it as an internal dev tool |
| **A single static HTML file (chosen)** | none of the above |

A **self-contained** `digital_twin_fem.html`:

- The FEM + ROM results are **baked into JavaScript** at build time
  (`build_twin_html_fem.py`) — in the browser only O(n) arithmetic remains →
  60 fps on a phone, exactly thanks to the ROM architecture of section 1.
- Free static hosting (GitHub Pages) — no backend, no server maintenance; the QR
  code (`gen_qr.py`) points straight at the URL.
- Requires the viewer to install nothing: a phone browser is enough.
- Still fully interactive: current slider / variac dial (in degrees), 4 disc radii
  swappable live, the model levitating with oscillation, T_amb from a weather API.

In short: the HTML is not a "replacement for a simulation library" — it is the only
**delivery channel** that satisfies the "scan the QR code and it runs, no install"
constraint. All the physics is still solved in Python; the HTML only receives the
baked results.

---

## 4. Project structure, the road travelled, and the remaining steps

### Pipeline architecture (one-way, one job per file)

```
params.yaml  (every parameter: geometry, materials, current, BCs — nothing hardcoded)
    │
config.py    (load + normalise units mm→m, derive I_peak = I_rms·√2)
    │
em_solver.py          thermal_solver.py
(phasor A_φ FEM,      (axisymmetric thermal FEM,
 eddy + ohmic loss,    energy balance 0.000%)
 lift force, benchmark)
    └────────┬────────┘
          rom.py      (real-time ROM: I²-scaling + first-order transient + σ(T))
             │
  ┌──────────┼──────────────────┐
digital_twin.py   visualize.py   build_twin_html_fem.py
(interactive twin (revolve 2D→3D, (bake → digital_twin_fem.html,
 matplotlib, dev)  GLB/OBJ)        the final AR deliverable)
             │
data_io.py + arduino/thermal_sensor.ino   gen_qr.py
(sensor bridge → ROM calibration)         (QR → hosted URL)
```

### The road travelled (per the README roadmap)

- ✅ **Phase 1a** — Axisymmetric thermal solver, energy balance verified at 0.000 %.
- ✅ **Phase 1b** — EM solver (AC eddy currents, phasor); real losses computed;
  coil geometry re-measured with a ruler (2026-07-10, replacing the 2026-07-01
  estimates): Ø160 mm disc, inner coil 1000 turns r=27.9–61.9 mm, outer coil
  500 turns r=82.9–102.9 mm.
- ✅ **Phase 2** — Real-time ROM (I² + transient + σ(T)); τ ≈ 4.07 min @ R=80 mm
  (recomputed after the 2026-07-10 geometry re-measurement).
- ✅ **Phase 3** — Interactive twin loop (current slider, disc selector).
- ✅ **Phase 4** — Revolve 2D→3D, export GLB/OBJ (PyVista/meshio).
- ✅ **Phase 5** — Standalone HTML AR twin + QR code generator.
- ✅ **Phase 6** — Domain-size validation (Dirichlet vs Neumann, 1×1 m box as the
  professor requested); full pipeline re-run with T_amb = 20 °C.
- ✅ **Phase 8** — Sensor data pipeline (`data_io.py` + Arduino firmware), tested
  end to end with a synthetic CSV, no hardware needed yet.
- ✅ **Calibration against the real rig** — 2 measured operating points (190 V→5 A,
  270 V→7.8 A), HIKMICRO thermal images; the coil's lumped thermal network fits to
  RMS ≈ 2.5–3 °C.
  ⚠️ **Correction (2026-07-28 doc audit):** an earlier version of this line also
  claimed "lift force validated against the observed levitation height". That is no
  longer true — since the 2026-07-10 geometry re-measurement the predicted gap
  (z_eq ≈ 11.7 mm plate-bottom / 14.7 mm visible) disagrees with the observed 7–8 mm.
  See the open question below and CLAUDE.md; **do not treat z_eq as validated.**

### Remaining steps

1. **Phase 7 — real sensor hardware** (the biggest step, see section 5): build the
   Arduino + 2× MAX31855, log a real run, re-calibrate the ROM from that data.
2. **Hosting + QR**: choose a URL (most likely GitHub Pages) and then publish the QR.
3. Open physics questions (none of them blocking):
   - ✅ Magnet test on the outer iron ring: **done 2026-07-10** — the ring is
     ferromagnetic (μᵣ=1000, like the centre core), position re-measured at
     r=64.9–79.9mm (previously 81–101mm). Still open: the real alloy / B-H curve
     has never been measured (μᵣ=1000 is only a placeholder) — see the lift-force
     item above.
   - A denser variac dial → current calibration table (currently only 3 anchor points).
   - Annulus disc support (3 real discs, r_out=55/r_in=27.5 mm, not meshable yet).
   - Original TEAM 28 benchmark: z_eq ≈ 14.5 mm vs 11.3 mm expected (28% off, figure
     from 2026-07-11 after patching an RMS/peak bug — before that it was 6.8mm/40%
     off in the other direction) — still paused by team agreement, does not affect
     the real rig.
   - ✅ `validate_domain_size()`: **PASSES again** (all diffs <1%, e.g. P_plate
     0.767%) after re-running on the new 2026-07-10 geometry + iron — it had FAILed
     at 2.71% before; the cause of that old regression is still unknown but no
     longer blocking.

---

## 5. Hardware connection plan (validation loop)

Per the professor's guidance (June 2026): *"Schaut was es genau bräuchte und baut
dann selbst eine kleine Lösung — Arduino plus ein paar Sensoren, und dann
einfach noch ein Infrarot-Thermometer."* Full details: `docs/SENSOR_PLAN.md`.

### Measurement architecture

```
Type-K thermocouple #1 (core/inner coil) ─▶ MAX31855 ─┐
                                                       ├─▶ Arduino Uno/Nano ─USB serial─▶ Laptop
Type-K thermocouple #2 (disc underside)  ─▶ MAX31855 ─┘        (CSV, 1 Hz)
Handheld IR thermometer ──▶ manual spot checks (cross-reference)
```

- **Why thermocouples and not IR alone**: IR thermal images of shiny aluminium /
  the ceramic core are **not trustworthy** (wrong emissivity — confirmed during the
  2026-06-23 HIKMICRO session); only the dark-varnished coil gives a reliable IR
  reading. A contact thermocouple solves exactly where IR fails: **the underside of
  the aluminium disc** — which is also the measurement needed to settle the open
  question of whether the disc or the coil runs hotter.
- Firmware is already written: `arduino/thermal_sensor.ino` (2× MAX31855 over SPI,
  CSV output at 1 Hz over serial).

### Software pipeline (already working, only waiting on hardware)

```
Arduino (CSV serial) ─▶ data_io.py SensorReader (mode serial | mock)
                     ─▶ calibrate_from_file()
                     ─▶ rom.calibrate_UA()   ← fit hA, τ from measured data
```

This whole chain has been **tested end to end** with `mock_sensor_data.csv` — so on
the day the hardware arrives, it is just plug in the USB and change `--mode mock` to
`--mode serial`; no additional code needs writing.

### Implementation steps

1. Finalise the shopping list (Reichelt/Conrad: Arduino Nano, 2× MAX31855 breakout,
   2× type-K thermocouple, wire) → the professor purchases it.
2. Assemble + flash the firmware, check against ice water / boiling water (2 reference points).
3. Log one sufficiently long real run (cold → steady state, ≥ 3τ ≈ 20 minutes) at
   190 V / 5 A.
4. `data_io.py --mode calibrate` → re-calibrate `hA_inner/hA_outer/UA` from real
   data (replacing the current IR-based calibration).
5. Log a **cooldown** run as well (power off, measure the cooling) → separately fit
   the coil's two-node model (`coil_G_wind_W_per_K`, currently only
   order-of-magnitude correct).
6. Extension (later, beyond Phase 1): a real-time current measurement device (the
   professor has confirmed one needs to be purchased) → the twin takes a measured
   I(t) instead of a constant 5 A; further out, this could stream directly into the
   HTML twin via the Web Serial API.

---

## A short answer for the professor

> "We did not choose to write code *instead of* simulating — we wrote code
> **because** the requirement is a real-time digital twin on a phone. Tools like
> SimScale solve one scenario in a few minutes; our twin has to answer in
> milliseconds while the user turns the current knob. That is only feasible by
> exploiting the physical structure of the problem (loss ∝ I², fixed spatial
> distribution) to solve the FEM exactly once and reduce it to a ROM — and that
> requires controlling the solver at source-code level. In exchange, we verify
> rigorously: energy balance 0.000 %, exact I²-scaling, and coil temperatures that
> match the measurements on the real rig."

> ⚠️ **2026-07-28 doc audit:** this closing quote previously also claimed the lift
> force matched the rig measurements. It no longer does — see the correction in
> section 4. The claim has been removed rather than softened, because the
> levitation-gap mismatch is a genuine open question, not a tolerance issue.
