# CHANGELOG — Thermal Digital Twin (TEAM 28-like Levitator)

Full narrative history of every fix/feature session, moved out of CLAUDE.md
(2026-07-10, WP-TRIM per docs/archive/2026-07-04_AUDIT_FIX_PLAN.md) to keep CLAUDE.md
under its ~250-line budget. CLAUDE.md's "Code status" section keeps only a
compact CURRENT-STATE checklist; this file has the full "how we got there"
detail for every entry, unabridged, in roughly chronological order.

---

## config.py / params.yaml / rom.py / thermal_solver.py / visualize.py / sim_plates.py — core pipeline, done and stable

- [x] config.py, params.yaml — done, runs.
- [x] thermal_solver.py — axisymmetric heat FEM, energy balance 0.000% error.
      EM q_e interpolated in; h_bot fix done; normalization fix done.
- [x] em_solver.py — axisymmetric AC eddy-current solve (complex A_phi, iron region);
      compute_losses(cfg) → P_plate/P_iron/P_coil + q_e map. I²-check passes.
      validate_domain_size(cfg): Dirichlet vs Neumann outer BC, PASS (diffs <0.06% at ±500mm)
      **as of 2026-06-22 — see WP-PEAK entry below: this regressed to FAIL by 2026-07-10,
      cause not yet identified, predates WP-PEAK itself.**
- [ ] PAUSED (user choice, 2026-06-23): `run_benchmark_validation()` gives z_eq≈7.1mm vs
      11.3mm expected (37% error) — improved from z_eq≈3.4mm (70%) after fixing
      `benchmark_team28_original`'s coil radii (now from the real TeamProblem28.pdf:
      inner r=15-28mm/outer r=41-46.5mm, vs the rig's own 28-43/46.5-61.5mm it was
      wrongly reusing) + a finer mesh for the benchmark's narrow coils (`fine_step_mm
      =0.2` override, just for this call). The old "z_eq=10.9mm/PASS" claim in
      HANDOFF.md/README.md/ARCHITECTURE.md was never actually reproducible (bisected
      every git commit) — corrected those files. Ruled out as the remaining cause:
      mesh resolution, domain size, current_sign convention. 37% gap still unexplained
      — paused here by user request, not currently blocking other work. Confirmed
      UNCHANGED (still 7.1mm) after WP-PEAK's RMS/peak convention fix (2026-07-10) —
      `run_benchmark_validation()` was deliberately left untouched since its 20A is
      the original academic problem's own convention, not a multimeter RMS reading.
- [x] rom.py — ThermalROM: build() FEM once at I_ref, T_steady(I) scalar multiply,
      simulate(I_arr, t_arr) first-order ODE, calibrate_UA() from sensor.
      τ=10.6 min | σ(T) correction iterative | I²-scaling verified 4.000000.
- [x] digital_twin.py — DigitalTwin(rom): step() Euler, run_live() matplotlib animation.
      Scenarios: step/ramp/sine/pulse/manual. Slider I, speed slider (1×–200×, log),
      RadioButtons plate selector (plate_library), Space=pause. ROM rebuild on-demand + cache.
      Sensor integration pending (calibrate_UA() already wired in ROM).
- [x] visualize.py — make_plate_3d(): revolve FEM 2D→3D surface (top+bot cap+rim),
      matplotlib 3D render (z_scale exaggeration), GLB export via trimesh.
      Outputs (→ outputs/): thermal_3d.png, thermal_2d_section.png, plate.glb (247 KB).
      Optional: --pyvista for interactive window.
- [x] sim_plates.py — compare thermal response across plate_library (EM + thermal,
      3D revolve + bar/profile charts). --no-em fast path via σ·R² scaling.
- [x] build_twin_html.py — Phase 5: bake STL geometry + EM losses + lumped thermal
      network into ONE standalone digital_twin.html (no server, double-click to run).
      **DELETED 2026-07-02 (commit ec64ec1), superseded entirely by
      build_twin_html_fem.py** — this entry kept for history only.
- [x] data_io.py + arduino/thermal_sensor/thermal_sensor.ino — SensorReader (serial or
      port="mock" synthetic source) → calibrate_from_file() → rom.calibrate_UA(I_meas,
      dT_meas); live_compare() animation. Tested end-to-end against mock_sensor_data.csv
      (no real hardware yet) — see docs/SENSOR_PLAN.md.
- [ ] NEXT: Sensor hardware — build the real Arduino rig (MAX31855×2 + thermocouples,
      shopping list in docs/SENSOR_PLAN.md), log a real run, re-run calibrate_from_file() on it.
- [x] Domain validation — Dirichlet vs Neumann BC comparison: validate_domain_size() in
      em_solver.py; PASS, diffs <0.06% at ±500mm domain → domain is large enough.
      **STALE as of 2026-07-10 — see WP-PEAK entry, now FAILs at 2.71%, needs re-check.**
- [x] Re-ran full pipeline with T_amb=20°C, ±500mm domain (2026-06-22): config → em_solver →
      thermal_solver → rom → visualize → build_twin_html_fem, all outputs regenerated.
- [x] QR code generation mechanism DONE (2026-07-02): `gen_qr.py` (repo root,
      `qrcode` dep uncommented in requirements.txt) takes the target URL as a CLI
      arg (`python gen_qr.py <url>`) or falls back to a `DEFAULT_URL` placeholder
      at the top of the file; prints an ASCII QR to the terminal and saves
      `outputs/qr_digital_twin.png`. Smoke-tested with both the placeholder and a
      real-looking URL. **Still open:** the actual hosting URL for
      `digital_twin_fem.html` is undecided (GitHub Pages vs other) — waiting on
      user to pick before baking a real default in.

---

## build_twin_html_fem.py — session-by-session history

- [x] render fix (2026-06-23): center spacer (region 3) and
      separator ring (region 5) render as static METAL_RGB instead of the heat ramp
      (both passive, ~36-45°C vs coils' 56-79°C); wood base recoloured brown; CSS2D
      labels "Iron Core"→"Center Spacer", added "Separator Ring". Verified via
      headless Playwright (no JS errors, screenshots confirmed).
- [x] Separator-ring 3D geometry (2026-06-23): `build_separator_rings()` procedurally
      synthesizes 2 thin cylindrical sleeves (region 5) at the iron/inner/outer coil
      gap radii, full device height (z≈-2..66mm, matching the real walls either
      side) — the real STL has no surface to recolour there. Visual only.
- [x] Coil thermal network calibrated (2026-06-23) then RE-CALIBRATED (2026-07-01)
      after coil geometry correction. Final: hA_inner=3.5611, hA_outer=4.3446,
      coil_C_scale=0.2241. See "Real-rig validation" in CLAUDE.md + `lumped_thermal` in params.yaml.
- [ ] NEXT: build_twin_html.py (lumped-only, secondary file) not yet synced with the
      separator-ring procedural geometry — only needed if that file is still used.
      **Moot: build_twin_html.py deleted 2026-07-02.**
- [x] Magnet-contact test DONE (2026-07-01): center core = non-ferromagnetic, non-
      thermally-conductive. mu_r=1.0, sigma=0.0 confirmed. Plate thickness=3mm confirmed.
- [ ] NEXT: Re-confirm coil/iron radii by ruler (geometry still unverified).
- [x] UI improvements (2026-07-01 session 1):
      Time speed slider default reset to 1×; T_amb display = 29°C (lab ambient);
      Solid center core procedural geometry (`build_solid_core()`, r=0–25mm);
      Gap filler ring r=25–28mm (inner coil material, no air gap between core and coil);
      Levitation gap Z-axis animation bound to I (z_eq=4.1mm@5A, min I_lev=4.64A);
      Levitation gap shown in Telemetry panel; disc label follows disc Y-position;
      Inner/outer coil temps plotted realtime on Time History chart alongside plate T_max;
      Coil surface uses relative heat ramp (0=T_amb, 1=T_ss(I)) → visible colour change;
      Header badge voltage corrected to 220 V (was incorrectly set to 190V).
- [x] Auto-init T_amb from a live weather API (2026-07-02, switched provider
      2026-07-03): `build_twin_html_fem.py` JS gained `fetchAmbientC()`
      (top-level `await` in the module script, blocks the rest of the module
      so every T_AMB_JS-derived const picks up the right baseline) — falls
      back to the old hardcoded 29°C on any failure (no key, no network, bad
      response) and logs a `console.warn`, never throws. Header badge
      (`#tAmbBadge`) shows the resolved value + "(live)" suffix when a real
      fetch succeeded. Physics (ROM.T_amb from params.yaml) is untouched —
      this only changes the display/color-ramp baseline.
      **Provider switched OpenWeatherMap → Google Maps Platform Weather API**
      (`currentConditions:lookup`, Darmstadt @ 49.8728,8.6512) 2026-07-03 —
      verified live against the real endpoint (returned 19.9°C at test time).
      **Key handling (security-hardened 2026-07-03, later gated further by
      WP-HTML 2026-07-10 — see below)**: the JS template only
      ever contains the placeholder token `__GOOGLE_WEATHER_KEY__`; the real
      key is never written into this tracked script. `_load_google_weather_key()`
      (top of `build_twin_html_fem.py`) reads `GOOGLE_WEATHER_API_KEY` from
      `local/.env.local` (repo-root `local/` folder, entirely gitignored,
      2026-07-03 moved here from a bare repo-root `.env.local` so any future
      local secret file is covered by one blanket ignore rule) at build time
      and substitutes it into the generated HTML in-memory; falls back to
      `"YOUR_KEY_HERE"` if the file/env var is absent. Because
      `outputs/digital_twin_fem.html` IS git-tracked (the AR/QR deliverable —
      see `.gitignore`), a build done with a real key in `local/.env.local`
      WILL bake that live key into the tracked file's working tree —
      gitignoring `local/` only stops the *source* from leaking, not the
      *output*. As a hard technical backstop, `.claude/settings.json` gained a
      `PreToolUse` hook on `git commit *` that greps the staged diff for the
      Google key pattern (`AIzaSy[0-9A-Za-z_-]{20,}`) and denies the commit if
      found — verified in an isolated sandbox repo (blocks when staged,
      allows when clean); widened 2026-07-10 (WP-SEC) to also catch unstaged
      changes (`git diff HEAD`), see the AUDIT_FIX_PLAN Phase 1 entry below.
      **The Google key currently in `local/.env.local` is
      an unrestricted (no HTTP-referrer/IP lock) live test key — do not commit
      `outputs/digital_twin_fem.html` while it contains this key**. Proper fix,
      still open: add HTTP-referrer or IP restriction to this key in Google
      Cloud Console, or swap to a project-scoped restricted key before shipping.
- [x] rendering fixes (2026-07-01 session 2):
      Center Core (reg 3) and Separator Ring (reg 5) now use writeRamp(tnIron) instead
      of static METAL_RGB — they show real heat-ramp colour (conduction from coils,
      ~39-45°C). Center Core label corrected to "Center Core (ferromagnetic)" per user.
      Inner Coil material upgraded (roughness 0.35, metalness 0.55, envMapIntensity 0.7)
      for a coated-wire / insulation-wrapped look. Telemetry row label cleaned to
      "Levitation Gap" (no emoji), value now reads "Levitation Gap: X.X mm".
      Z_GAP_EXAG raised 6.0→8.0 so the 4.1mm physical gap at 5A maps to ~33 display-mm
      (clearer visual lift). Chart coil line widths raised 1.4→2.2 px, colors brightened:
      outer=#ffdd22, inner=#ff6600 — clearly distinct from Plate T_max (#ff6644 1.8px).
- [x] FULL PROCEDURAL GEOMETRY REBUILD (2026-07-01 session 3):
      STL body geometry entirely REMOVED from body pipeline (STL was causing 5 visual bugs:
      hollow core, unrealistic gaps, plastic-looking material, hexagonal frame, surface-only heat).
      ALL device parts now built 100% from params.yaml numbers via revolve_ring()/build_solid_core()/
      build_octagonal_frame() — no classify() STL voxelization. New coordinate system (natural,
      z=0 floor, z=8..60 coil assembly, z=63.8 disc bottom). Region labels:
        reg 3 = center core (solid cylinder r=0..25mm, ceramic/Al₂O₃)
        reg 1 = inner coil + gap-filler (solid toroid r=25..78mm, 1000T varnished copper)
        reg 5 = separator / iron ring (solid fill r=78..104mm — entire gap, no visible voids)
        reg 2 = outer coil (solid toroid r=104..124mm, 500T varnished copper)
        reg 4 = plywood octagonal frame (8-sided prism r=130..165mm)
        reg 0 = levitating disc (Ø160mm × 3mm Al, z≈63.8mm above coil top)
      New thermal ramp functions: writeRampCopper() (dark red-brown→orange-yellow, for coils) and
      writeRampMetal() (silver-gray→warm orange, for core/separator). Separate Three.js meshes:
      baseM (roughness=0.42, metalness=0.68) / woodM (0.88, 0.02) / plateM (0.35, 0.75).
      Total body tris: ~4896. Disc: ~3072 tris. Output: outputs/digital_twin_fem.html (625 KB).
- [x] GEOMETRY MATCHED TO REAL DEVICE (2026-07-01 session 4),
      user verified vs docs/real_model.png: (1) wood frame moved 130..165 → **174..194mm**
      (new `device_frame` block in params.yaml: air_gap_mm=50, wall_thickness_mm=20 —
      outer coil stands free in ~50mm air); (2) air gaps 25-28/78-81/101-104mm now REAL
      voids — V_coregap removed, separator mesh shrunk 78..104 → **81..101mm** (reads
      `outer_iron_ring` radii); (3) coils split into own mesh `coilM` (roughness 0.30,
      metalness 0.20 — glossy varnish, not bare metal), COPPER_COLD darkened to
      [0.30,0.14,0.08] chocolate-brown per photo, COPPER_HOT softened to [0.93,0.55,0.16].
      Body tris 4896→3936. Label "Center Core (ceramic)"→"Center Core" (material disputed).
      `window.twinDebug={camera,controls,size}` exposed for headless tests. Verified via
      Playwright: 0 JS errors, screenshots confirm gaps + free-standing frame.
- [x] μ_r SENSITIVITY TEST (2026-07-01): user visually claims center core AND separator
      ring are ferromagnetic (conflicts with negative magnet test on core; ring test
      pending). EM sensitivity at 5A: ring-only μ_r=1000 → P_plate +168%, F_z +178%;
      core-only → +32%/+28%; both → P_plate 9.7→32.9W, F_z 1.69→5.78N (×2 conv).
      NOT negligible IF ferro — but observed levitation (~1.69N vs 1.60N gravity,
      z_eq=4.1mm ≈ user's "2-3× disc thickness") matches μ_r=1, NOT μ_r=1000 (plate
      would fly much higher). DECISION (user, 2026-07-01): keep μ_r=1.0 for now,
      re-verify by magnet test later.
- [x] LEVITATION GAP PHYSICS + BODY HEAT COLORS (2026-07-02):
      (1) Gap: replaced wrong "z_eq ∝ I with hard 4.64A cutoff" (jumped 0→3.8mm) by an
      exponential force-decay model F(I,z)=(I/5)²·F1·e^(−(z−z1)/z0), z0=21.4mm from the
      two EM anchors (F(5A,1mm)=1.85N, F(5A,4.1mm)=mg=1.60N) → z_eq(I)=4.1+2·z0·ln(I/5),
      CONTINUOUS lift-off at I_min≈4.54A, 4.1mm@5A, ≈18.5mm@7A. Plus spring-mass disc
      dynamics (ω=√(g/z0)≈21 rad/s, ζ=0.02, wall-time integration): disc bobs ~9s after
      a current step then settles — matches the real rig behaviour user described.
      Telemetry gap now shows the live spring state.
      (2) Body heat: core/separator colour was frozen (absolute 29–125°C scale → tnorm
      ~0.15 at 45°C) — now normalised to the inner coil's steady rise + sqrt perceptual
      boost in writeRampMetal. ROOT CAUSE was also physical: iron node had P_ref=0 and
      only air coupling (hA=0.06) → +2.4K after 30min. Added CONTACT CONDUCTION inner
      coil → iron node (`G_iron_cond_W_per_K: 0.06`, `hA_iron: 0.244` in params.yaml,
      fit to IR session 1: core 45°C@7.8A steady, ratio 0.32, τ≈4min; low-confidence IR,
      refit with thermocouples later). Now T_iron_ss(5A)=35.6°C ✓. Verified headless:
      0 JS errors, gap curve continuous (0/4.5A, 4.1/5A, 19/7A), bob-and-settle observed,
      coils golden + separator warm after 30 sim-min.
- [x] 4 render fixes (2026-07-02, docs/archive/2026-07-02_HTML_TWIN_FIX_PLAN.md):
      (1) Gap displayed too high (~87 display-mm, disc floating above the whole
      device): root cause was a 3.8mm gap BAKED into the disc geometry (Python
      `z_disc_bot`) stacked with a `LIFT_BASE` JS offset AND `Z_GAP_EXAG=8.0` — all
      three added on top of each other. Fixed: disc now bakes at `z_disc_bot=
      z_coil_top` (sits on coil top), `LIFT_BASE` removed entirely, `Z_GAP_EXAG`
      8.0→2.0 (same factor as the disc-thickness exaggeration) → gap = `lev.z×2.0`
      only, 4.1mm@5A → 8.2 display-mm. Verified: settled display gain matches
      lev.z×2.0 to 5 decimal places.
      (2) B-field lines were static geometry that never reacted to I (dashOffset
      ran on wall-clock only, opacity only followed the slider). Field SHAPE stays
      static (linear problem, correct), but flow speed + opacity now scale with
      `emScale=I_display/I_em_ref`: 0 at I=0 (invisible, frozen), faster/brighter
      as I rises (capped 2x). Verified: opacity=0 at I=0, dashOffset actively
      advancing at I=13A.
      (3) Coil colour didn't track real heating: `tnInner`/`tnOuter` were divided
      by the CURRENT-DEPENDENT `T_ss(I)`, so bumping I made the coil look
      "instantly cooler" and any steady state at any I painted full-hot — visible
      as flicker-with-I in sine scenarios. Fixed: absolute fixed scale `T_COIL_HOT
      =80°C` (anchored to IR session 1: inner coil 79°C@7.8A, the hottest reading
      ever measured), independent of I — colour only moves when the real
      temperature moves. `tnIron` uses the same absolute scale ×1.8 boost (core/
      ring only reach ~45°C @7.8A, tnorm≈0.31 unboosted). Verified: colour holds
      steady immediately after an I step (temp hasn't moved yet), only drifts as
      sim time passes.
      (4) Studio-bright glare: `UnrealBloomPass`+`EffectComposer` (strength 0.42,
      on whenever I>0.01 — i.e. almost always) plus `envMapIntensity=0.8` on every
      mesh made all metal read as glossy chrome sliding highlights on rotate.
      Fixed: composer/bloom pipeline removed entirely (`renderer.render()`
      direct); `makeMesh()` gained a per-mesh `envInt` param — coils envInt=0.15
      roughness=0.80 metalness=0.05 (matte varnish), core/separator envInt=0.25
      roughness=0.60 metalness=0.30 (dull oxidised metal), wood envInt=0.05, only
      the aluminium disc keeps real metalness (0.65, envInt=0.45). Verified:
      0 JS errors across 5 camera angles, no sliding white highlights, matches
      docs/real_model.png (dark matte coils, only the disc is shiny).
- [x] coil GLOW + label de-overlap + field density (2026-07-02 s2),
      per user review vs docs/thermal_test.png (HIKMICRO IR: coils are the BRIGHTEST part,
      yellow-white at ~60°C): (1) coils split into coilInnerM/coilOuterM meshes, each with
      per-material emissive (ember orange, intensity=0.9·tn^1.4 on the absolute 80°C scale)
      — hot windings now visibly LIGHT UP; COPPER_HOT brightened to [1.0,0.80,0.22] +
      pow(t,0.65) perceptual boost (old ramp read as "slightly lighter brown" at tn≈0.5).
      (2) Labels: regionCentroid collapsed to (≈0,y_mid,≈0) for EVERY revolved ring → all
      4 labels stacked on one screen point; now regionAnchor(reg,θ,yPad) anchors each on
      its ring's outer-top edge at its own azimuth + a 5Hz greedy screen-space de-overlap
      pass (stack top-to-bottom via margin-top). (3) B-field line DENSITY now follows I:
      lines amp-ranked, visible fraction = min(I/I_ref,1) (72/360 at 1A → 360/360 at 5A),
      dash gaps shrink above I_ref — on top of existing speed/opacity scaling. (4) Coil
      "→T_ss" arrows were baked once at 5A, never updated → at 5.5A live T sailed past a
      stale "→50°"; now live per-frame coilTss(I). Verified headless: 0 JS errors, no
      label overlap at default+rotated cam, glow 0.43@59°C / 0.87@79°C / ≈0@29°C.
- [x] PARTIAL FIX — plate/coil temperature ordering bug (2026-07-02, user report:
      "feeling that the wire should be hotter than the disc bottom"). Root-caused: at I_ref=5A/T_amb=20°C
      (the one point where the coil model IS IR-validated: T_inner_ss=40.3°C), the
      disc FEM predicted T_mean=46.9°C — ABOVE the coil, backwards vs every IR
      session (coils are always the hottest part of the rig by a wide margin).
      Traced to a stale constant: `k_coil_coupling_K_per_W=0.15`'s own comment
      documents its design intent as "ΔT≈11–13K at 5A", derived when P_coil≈73W —
      but the 2026-07-01 coil-radii fix bumped P_coil(5A) to 128.17W and nobody
      revisited k, so Tinf_bot silently rose to 39.2°C (ΔT=19.2K), 60% over its own
      documented target, stacking with the disc's OWN (separately unvalidated)
      eddy-convection rise (~13.5K from guessed h_top=10/h_bottom=25 W/m²K).
      Fix: rescaled `k_coil_coupling_K_per_W` 0.15→**0.094** so Tinf_bot(5A) again
      lands mid-range of the ORIGINAL documented 11–13K intent (12.05K) against the
      corrected P_coil — a like-for-like recalibration, not a new guess. Rebuilt
      both `digital_twin_fem.html` and `digital_twin_fem_R101.html`; verified
      headless (Playwright, ran to sim t≈83min/steady state at 5A): plate T_mean
      49.2°C vs inner coil 49.3°C — essentially tied, no longer a clear violation
      (was 46.9 vs 40.3, +6.6K wrong-direction). 0 JS errors both files.
      **STILL OPEN**: the two temperatures are now only *tied*, not "coil clearly
      hotter" as IR data implies — the remaining gap is bounded by the disc's own
      h_top/h_bottom, which are still uncalibrated guesses (disc IR readings are
      known-unreliable). A real disc-bottom
      thermocouple measurement (already on the SENSOR_PLAN NEXT list) is needed to
      fully resolve this, not just narrow it — don't over-trust plate/coil ordering
      until then.
- [x] WP-C (2026-07-02, docs/archive/2026-07-02_PLAN_SIM_FEEDBACK.md): **Al Ø202mm disc option**
      (R=101mm, covers out to the separator ring's outer edge). Added as a NEW
      `plate_library` entry — default `plate_material.radius_mm` stays 80mm (the real,
      validated disc). Build with `python build_twin_html_fem.py --plate-radius 101`
      → `outputs/digital_twin_fem_R101.html` (default file unaffected, verified via
      headless Playwright: 0 JS errors both files, disc bbox radius = 80mm / 101mm
      exactly, screenshot confirms the disc now covers the separator ring and stops
      just short of the outer coil). EM/ROM re-solve FROM SCRATCH at R=101 (not
      scaled from R=80) — `thermal_solver.energy_balance` still 0.000% error.
      **Key result: the Ø202mm disc does NOT levitate at the 5A_rms operating point.**
      m=259.6g → F_grav=2.5465N (was 162.9g/1.5977N at R=80); F_z at the physical
      resting floor z=3.8mm = 1.5318N (I_peak=7.07A convention) — 40% short of
      F_grav. Estimated **I_min_lev ≈ 6.45 A_rms** (vs 5A op point) for it to lift off
      at all; P_plate(5A) rises 9.67W→11.66W (+20%, wider disc overlaps more of the
      field). CAVEAT: outer_iron_ring (r=81–101mm, right under this disc) is still
      modeled as air (μ_r=1, magnet test PENDING) — if it turns out ferromagnetic,
      both F_z and P_plate change substantially (see μ_r sensitivity note above), so
      this R=101 result is only valid under the current air assumption.
      SECONDARY FINDING (mesh-resolution check, not yet acted on): refining
      em_domain.fine_step_mm 2.0→1.0mm moves the R=80 baseline's own z_eq from
      4.15mm→~3.5mm-equivalent (F(3.8mm) drops below F_grav) and R=101's I_min_lev
      from 6.45A→6.9A — same qualitative conclusions, but the already-"VALIDATED"
      R=80 4.1mm figure is more mesh-sensitive than previously assumed. Left
      em_domain unchanged (out of WP-C's scope, adjacent to the already-PAUSED
      benchmark mesh investigation) — flagging for whoever revisits that.
      Staged (NOT wired live) for WP-D: `LEV_ANCHORS` dict + `_lev_anchor()` helper
      in build_twin_html_fem.py (F_z anchors, mass, F_grav, decay length z0 per
      plate radius) — the JS levitation-gap block still owns its own hardcoded
      Z_GAP_5A_MM/Z_DECAY_MM constants (WP-A/WP-D territory); the R101 HTML's
      Levitation Gap telemetry currently still shows a (wrong) nonzero gap because
      of this — expected, closes once WP-D wires PARAMS.lev per radius.
- [x] WP-B (2026-07-02, docs/archive/2026-07-02_PLAN_SIM_FEEDBACK.md): **realistic coil
      cooling** (rig feedback: hot windings take much longer to cool than to heat;
      the old single-node RC model cooled with the SAME τ it heated with, ~350s).
      Two additions in `romStep`/`lumped_physics` (build_twin_html_fem.py) +
      `lumped_thermal` (params.yaml), both scratch-fit (script not committed)
      against `validation_data.thermal_ramp_test`:
      (1) Nonlinear natural convection `h(ΔT) = hA_cal·(ΔT/dT_cal)^0.25`
      (simplified Churchill-Chu; new `convection_exponent` param) — h stays
      exactly hA_cal at the I_ref calibration point (`dT_cal`, baked per node
      from a small linear steady-state solve incl. the inner↔iron contact
      conduction), but drops as ΔT→0 during cooldown, stretching the tail.
      (2) Two-node coil (surface + winding-core): ALL P_ref lands on the surface
      node (unchanged ramp-test transient shape), the winding-core mass
      ((1−coil_C_scale) of the solid-Cu mass) only exchanges heat via a NEW
      `coil_G_wind_W_per_K=1.0` conductance — invisible while heating, keeps
      feeding the surface long after the current is cut. `coil_C_scale` and all
      four `hA_*`/`G_iron_cond` values are UNCHANGED (steady state provably
      invariant to both additions — proven analytically and confirmed live:
      T_inner_ss≈49.0-49.4°C/T_outer_ss≈47.2-47.4°C at T_amb=29°C, i.e.
      40.5°C/38.5°C-equivalent at T_amb=20°C, matches pre-WP-B exactly).
      **Side finding**: re-deriving the ramp-test residual found the CURRENTLY
      DEPLOYED (pre-WP-B) single-node model actually scores RMS=6.6°C on
      `thermal_ramp_test`, not the ~3°C previously claimed here — that claim had
      gone stale (most likely after the iron contact-conduction node was added
      2026-07-02 without re-checking the coil transient). The new two-node model
      both fixes this and adds cooling realism: RMS=2.5°C on the same data.
      Cooldown time-to-`T_air+10%ΔT` is now ~6-8× longer than the old model
      (inner ~1700-2100s sim-time vs ~255s) — verified live via headless
      Playwright (both `digital_twin_fem.html` R=80 and the WP-C
      `digital_twin_fem_R101.html` variant: 0 JS errors, monotonic cooldown,
      deep-node temperature visibly exceeds surface during cooldown confirming
      the reservoir feeds back, no node dips below T_amb).
      **CAVEAT** (same as coil_C_scale): no real COOLDOWN IR/thermocouple data
      exists yet — `coil_G_wind_W_per_K` is fit only against the heating ramp
      (which barely constrains it) plus a qualitative "much slower" cooldown
      target, so treat both the value and the resulting τ as order-of-magnitude.
      **NEXT** (unchanged ask, still open): next lab session, log a real
      cooldown trajectory (steady 5A → I=0, read coil IR every 60s for 20-30 min)
      to actually fit `coil_G_wind_W_per_K` and `convection_exponent`.
- [x] WP-A (2026-07-02, docs/archive/2026-07-02_PLAN_SIM_FEEDBACK.md): **levitation
      oscillation physics**, JS-only (`build_twin_html_fem.py` "Levitation gap
      physics" block + render loop + `window.twinDebug`), no Python/geometry
      changes. Fixes rig feedback: (a) speed slider didn't speed up the bob;
      (b) no chatter below lift-off; (c) 5→7.75A step oscillated as hard as
      0→5A. Changes:
      (1) `levStep(I, dt)` now integrates the spring-mass gap with the EXACT
      closed-form solution of the underdamped oscillator (was: wall-time-only
      substepped Euler) — unconditionally stable for any `dt`, and the caller
      now passes `dt_sim` (sim time) instead of `wall_dt`, so the speed slider
      correctly scales the bob-and-settle. Verified headless: real wall-clock
      settle time ratio between 1x and 10x speed ≈10.4x (target ~10x) — first
      measurement attempt gave a misleadingly low ratio (~3-5x) because the
      test's own "settled" check used a fixed wall-clock poll count, which is
      NOT equivalent between speeds; redone against a fixed SIM-time-stable
      window instead, confirming the fix is correct.
      (2) Sub-lift-off jitter: amplitude ∝ (I/5)² aliased two-tone shimmer
      (`JIT_MM`/`JIT_FREQ1`/`JIT_FREQ2`), fades out once `lev.z>0.5mm`. Verified:
      visible at 0.5A/3A (grows with I), exactly zero at I=0.
      (3) Damping now current-dependent: `ζ(I)=ζ0+ζ1·(I/5)²`, `ζ0=0`/`ζ1=0.02`
      reproduces the old fixed ζ=0.02 exactly at the 5A anchor.
      (4) `lev.z` settle vs `levGapEqMm(I)` verified exact (diff=0.00000mm) at
      6 test currents spanning 0 to 7.75A.
      **OPEN QUESTIONS (need user input, not blocking)**:
      - `Z_OBS_7_75A_MM` (real gap at 7.75A, mm or "x× disc thickness") is still
        `null` in the code — fill it in to refit `Z_DECAY_MM` (currently 21.4mm,
        which predicts z_eq(7.75A)≈22.9mm; user reports the real gap only
        "nudges up a little", so 21.4mm is likely too large). **See WP-Z0 below —
        this is the same open question as the z_decay method choice.**
      - **Numeric inconsistency found, not silently patched**: the plan's own
        acceptance target ("5→7.75A step overshoot <40% of the 0→5A step
        overshoot, normalized") requires ζ(7.75A)≈0.3 — but the plan's own
        physical model (§3, ζ∝I², anchored at ζ(5A)=0.02) can only reach
        ζ(7.75A)≈0.048 without breaking the 5A anchor. Measured overshoot ratio
        is 91.5%, not <40% — this test FAILS as specified. The two numbers in
        the plan (the ζ∝I² law and the <40% target) are mutually incompatible;
        picking one over the other is a product decision, not a bug fix. Left
        ζ1=0.02 (physically motivated, preserves the validated 5A behaviour) and
        documented the conflict inline in the code. Needs a decision: relax the
        overshoot target, adopt a steeper (less physically-derived) damping law,
        or wait for real oscillation-amplitude data at 7.75-8A to fit ζ properly.
        **Still unresolved as of 2026-07-10.**
      **Still open (WP-D territory, unchanged by this entry)**: `Z_GAP_5A_MM`,
      `Z_DECAY_MM`, `ζ0`/`ζ1`, `JIT_MM`/`JIT_FREQ1`/`JIT_FREQ2` are still
      hardcoded JS literals, not yet routed through `params.yaml`/PARAMS JSON —
      and the R101 build still uses the R=80 lift-force anchors (see WP-C entry
      above), so its levitation telemetry is known-wrong until WP-D wires
      `LEV_ANCHORS` per plate radius. **Resolved by WP-D below.**
- [x] WP-D (2026-07-02, docs/archive/2026-07-02_PLAN_SIM_FEEDBACK.md): **constants
      refactor + final integration**. Added `levitation:` block to params.yaml
      (z_gap_5A_mm, z_decay_mm, zeta0/1, jit_mm, jit_freq1/2, z_gap_exaggeration)
      and `coil_hot_display_C` to `lumped_thermal:`. New `lev_params(cfg)`
      (build_twin_html_fem.py) feeds `PARAMS.lev`; JS now reads `PARAMS.lev.*`
      and `LUMPED.T_coil_hot_display_C` instead of hardcoding `Z_GAP_5A_MM`,
      `Z_DECAY_MM`, `LEV_ZETA0/1`, `JIT_MM/FREQ1/FREQ2`, `T_COIL_HOT`.
      **Fixed the WP-C-flagged R=101 bug**: `lev_params()` uses the R=80
      params.yaml defaults ONLY for the R=80 build (bit-identical, zero
      regression — verified `levGapEqMm(5)=4.1000mm` exactly, `I_LEV_MIN=
      4.543A`, both unchanged); any OTHER `--plate-radius` build now recomputes
      its own anchors from `LEV_ANCHORS`/`_lev_anchor()` (WP-C's staged
      deliverable). Verified for R=101: `levGapEqMm(5)=0.0000mm` (correctly does
      NOT lift at the 5A operating point — was wrongly nonzero before),
      `I_LEV_MIN=6.450A` (matches WP-C's `I_min_lev_A_rms=6.45` exactly), gap
      curve continuous and sane above threshold (0.22mm@6.5A → 6.04mm@8A).
      Regression-tested both `digital_twin_fem.html` (R=80) and
      `digital_twin_fem_R101.html`: 0 JS console errors, coil glow still runs
      correctly through the relocated `T_COIL_HOT`.
      **Consolidated ALL open questions from every WP into one place**: see
      docs/archive/2026-07-02_PLAN_SIM_FEEDBACK.md, final section "Questions for the user to answer"
      (8 items — gap@7.75A calibration, a genuine numeric conflict inside
      WP-A's own spec between the ζ∝I² law and its 40% overshoot acceptance
      target, coil cooldown data, TWO disagreeing z0 decay-length derivations
      for the SAME R=80 disc (21.4mm vs 13.6mm — an open methodology question,
      not a bug — **this is WP-Z0, see CLAUDE.md**), R=101's I_min_lev=6.45A
      finding, outer_iron_ring magnet test, plate-vs-coil temperature ordering,
      and EM mesh-resolution sensitivity).
- [x] POWER SUPPLY IDENTIFIED (2026-07-02, docs/rig_photo.jpg): **Carroll & Meynell
      CMV 10 E-1 variac** (Stelltransformator, 240V in / 0–270V out, 50Hz), feeds
      the coils through an ammeter. Dial scale 0–270 ≈ output VOLTS (explains the
      old 220V→5A vs 270V→7.8A numbers). Measured dial→I anchors (new
      `power_supply` block in params.yaml): 0→0A, 220→5.00A, 270(max)→**7.78A**.
      DISCREPANCY flagged, not resolved: dial 220 at 5A vs multimeter 190V→5A
      (2026-06-23) — sag under load or dial offset; re-measure V at coil terminals.
      Load impedance NOT constant (44Ω@220 vs 34.7Ω@270) → use the interpolation
      table, never I∝V over the full range. Rig behaviour re-confirms WP-A
      qualitatively: disc shakes/unstable during ramp below lift-off (jitter model ✓),
      takes >10s to settle at 5A (model: ~9s, ζ=0.02 ✓).
      **USER GOAL (drives next work): twin input = variac dial / measured I directly;
      thermal sensors are validation-only, NOT the runtime input.** Matches the
      existing ROM design (input is already I(t)).
      **CORRECTED 2026-07-10 — see "VARIAC DIAL UNIT CORRECTION" entry below: the
      dial scale is DEGREES, not Volts.**
- [x] Power-supply integration STEP 1 (2026-07-02, SW dial mode, no HW yet):
      `config.py` gained `Config.dial_to_current_A(dial)` (piecewise-linear over
      `power_supply.dial_to_current_A`) + a `power_supply` property; `python
      config.py` now prints a dial→I table as a sanity check.
      `build_twin_html_fem.py`: new `power_supply_params(cfg)` bakes the same
      anchor table into `PARAMS.power_supply`; HTML gained an "Amps / Variac
      Dial" toggle (`#inputModeGroup`) — the Dial slider (`#sDial`, 0–270,
      default 220) computes I the same way as config.py and writes it into the
      existing `targetI`, so scenarios/ROM/levitation are untouched. Verified
      headless (Playwright): dial 220→5.00A, 270→7.78A, 0→0A, mode toggle
      round-trips cleanly, 0 JS errors.
      `digital_twin.py`: matplotlib GUI gained a second slider "Dial" next to
      "I (A)" (`ax_slDial`, only created if `power_supply` is in params.yaml)
      that calls `sl_I.set_val(cfg.dial_to_current_A(val))` — reuses the
      existing `_on_I` callback, no new state field. Also fixed a latent bug
      this surfaced: `sl_I`'s range and the `update()` loop's current clamp
      were BOTH hardcoded to 5.0A, which would have silently clipped the rig's
      real 7.78A max — replaced with `I_MAX = max(5.0,
      cfg.dial_to_current_A(dial_max))` (≈7.78→rounds to 8.0 slider ceiling).
      Smoke-tested `run_live()` end-to-end on the Agg backend (no display): no
      exceptions, ROM builds, figure constructs with both sliders wired.
      **NOT done yet (step 2/3, still open)**: denser dial→I calibration table
      (only 3 anchor points), re-measuring V at dial 220 to resolve the
      190V-vs-220-dial discrepancy (**resolved 2026-07-10, see VARIAC DIAL UNIT
      CORRECTION below**), recording the 7.78A levitation gap, and any
      live hardware current sensing (CT clamp + Arduino) — see docs/SENSOR_PLAN.md.
- [x] CONTACTLESS disc validation predicted (2026-07-02, user idea): measure at the
      SOURCE what changes when the disc is placed on/off the rig (no sensor on the
      levitating disc needed). EM impedance calc (Z=2S/î², S=½jω∫A·J_s dV, scratch
      script, not committed): disc ON adds ΔR=+0.77Ω but REMOVES ΔL=−1.33mH (eddy
      shielding) — the two nearly cancel in |Z| → ΔI@190V ≈ +0.024A, NOT measurable
      by ammeter. **Real-power measurement works**: ΔP@5A_rms = +19.4W (+7.6%,
      = physical P_plate = 2×9.67W solver conv.) → needs a true wattmeter
      (cosφ≈0.37, V·I is NOT P!), added to SENSOR_PLAN. Bonus model check:
      |Z|_model=29.4Ω vs measured 190V/5A=38Ω (−23%, unexplained — AC winding
      resistance? leads? OR separator ring ferromagnetic → L higher; a V+I+P
      measurement WITHOUT disc separates R/X and tests the pending μ_r question
      without a magnet). Cheapest disc-IR fix regardless: matte-black tape spot
      (ε≈0.95) on disc underside → HIKMICRO readings become trustworthy, no wires.
      See docs/SENSOR_PLAN.md "Kontaktlose Scheiben-Validierung".
- [ ] NEXT (power-supply integration, steps 2–3):
      (2) Next lab session: log dial→I every ~20 dial units (fills the interp
      table), re-measure terminal V at dial 220, record levitation gap at 7.78A
      (also fills WP-A's open `Z_OBS_7_75A_MM`).
      (3) HW live input — non-invasive CT clamp (SCT-013) or ZMCT103C + Arduino
      → I_rms CSV over serial → extend data_io.py SensorReader (mode="current")
      → digital_twin.py live; HTML twin via Web Serial API. Add to
      docs/SENSOR_PLAN.md shopping list. (Knob-position encoder rejected:
      indirect, mapping drifts with load.)
- [x] DISC-RADIUS COMPARE MODE (2026-07-03, user request: "swap discs with different radii
      onto the model during simulation to see the thermal response evolution clearly").
      Both `digital_twin_fem.html` and `digital_twin_fem_R101.html`
      now let the user swap the LIVE disc between 4 aluminium radii (Ø100/130/
      160/202mm = r 50/65/80/101mm, the plate_library entries the user picked)
      without rebuilding — a new "Disc radius (compare mode)" button row above
      the Current-I slider. **Grew to 5 radii 2026-07-10, see AUDIT_FIX_PLAN
      Phase 1 (WP-HTML) below — the 5th, r=100mm/"Al Ø200mm", was previously
      excluded by a stale hardcoded 4-radius tuple.**
      Python (`build_twin_html_fem.py`): new `solve_plate_variant(cfg, radius_mm,
      z_disc_bot)` re-solves EM+ROM+f_eddy/f_air+disc-mesh+`lev_params()` FROM
      SCRATCH per radius (same reasoning as WP-C: a different disc genuinely
      changes eddy distribution and lift force). `build()` loops the 4 radii
      (reusing the active build's own radius instead of re-solving it) and bakes
      all 4 into `PARAMS.plate_variants[]` + `PARAMS.active_plate_idx`.
      JS: all 4 variants share IDENTICAL mesh topology (fixed n_theta/meridian,
      only r scales), so `selectPlateVariant(idx)` just swaps plateM's position/
      dT/dTa/je buffers in place, `Object.assign(ROM, v.rom)`, and calls the new
      `applyLevParams(levObj, radiusMm)` (refactored the old load-once `const
      Z_GAP_5A_MM`/`Z_DECAY_MM`/`I_LEV_MIN`/`LEV_OMEGA`/`LEV_ZETA0/1`/`JIT_*`
      into `let` + this function, so the levitation model updates live instead
      of freezing at whichever radius loaded first) — then `resetSim()` (user's
      choice: switching disc resets ALL temperatures to T_amb, matching the
      existing plate-selector convention in digital_twin.py).
      **Side finding while wiring this up**: Ø100mm (r=50mm) does NOT levitate
      at the 5A op point either (I_min_lev≈5.36A, barely above) — only Ø130mm
      (r=65mm) and the real Ø160mm (r=80mm) disc do; Ø202mm (r=101mm) needs
      6.45A (WP-C, unchanged). Not previously checked since WP-C only solved
      r=101mm; same `outer_iron_ring`-modeled-as-air caveat applies to all of
      these (see μ_r sensitivity note above).
      Verified headless (Playwright, both HTML files): 4 buttons render with
      correct Ø labels from `PARAMS.plate_variants` (not hardcoded in JS),
      cycling through all 4 on both files → 0 JS errors, ROM/lev constants and
      Levitation Gap telemetry update correctly per radius (e.g. Ø202mm always
      shows Gap=0.0mm regardless of which file it's baked in), sim time/history
      reset on every switch, disc mesh visibly resizes, "Aluminium Plate" label
      repositions to the new disc's own centroid.

---

## 2026-07-10 — Audit + Phase 1/2 fix session

- [x] AUDIT_FIX_PLAN Phase 1: 4 WPs run in parallel (disjoint file
      ownership, same shared tree, no worktree isolation needed) — WP-SEC (commit
      hook now catches `git commit -a`, not just staged diff), WP-HTML (key
      gating via `--bake-key` default-off, compare-mode telemetry no longer
      stale across disc switches, idle hot-particle paradox fixed, plate-variant
      radii now SSOT from `plate_library`), WP-PARAMS (`plate_library` renamed
      to true-diameter convention, `digital_twin.py` default-plate match fixed
      to compare by `radius_mm`+material instead of a broken name string),
      WP-DOCS (6 stale `build_twin_html.py` references cleaned up, README
      roadmap Phase 6a/6b checked off). Full per-WP verify output in
      docs/archive/2026-07-04_AUDIT_FIX_PLAN.md's Execution Log. Real Google API key
      that had been sitting baked in the unstaged `outputs/digital_twin_fem.html`
      working tree is now confirmed gone (both HTML outputs rebuilt fresh,
      `grep -c AIzaSy` = 0). Not committed — left for user review.
- [x] Post-Phase-1 code review + 3 fixes: ran a multi-agent diff
      review over the Phase 1 merge before starting WP-PEAK; 8 findings, fixed
      the 3 most severe. (1) B-field line visualization was going stale after
      switching disc radius in the compare-mode UI — `solve_plate_variant()`
      computed then discarded each variant's own field-line contours; now kept
      (`field_lines` key threaded through `plate_variants[]`) and JS's
      `selectPlateVariant()` calls a new `buildFieldLines()` (refactored out of
      the old load-once inline block, disposes old geometry) so the B-field
      overlay shape actually matches the active disc, not just its ROM
      scalars. (2) `digital_twin.py`'s default-plate lookup could silently
      mislabel the ROM cache under an unrelated `plate_library` entry's name
      if the active radius+material ever had no exact match — now synthesizes
      an honest `"Active (ØXXXmm material, not in plate_library)"` label
      instead of borrowing one, plus a console warning; verified both the
      normal (matches "Al Ø160mm") and mismatched (synthesized label) paths
      headlessly, 0 exceptions. (3) The disc-radius compare-mode SSOT fix
      (Phase 1 WP-HTML) quietly grew the live variant count from 4 to 5 — the
      note above and inline comments said "4 radii"; corrected to explain the
      5th (r=100mm, "Al Ø200mm") is not less-validated, it runs through the
      exact same EM+ROM+lift-off check as the other 4 (`I_min_lev≈6.37A`,
      doesn't lift at 5A, same `outer_iron_ring`-as-air caveat as Ø202mm) —
      just newly surfaced by the fix. Findings #3 (0.5mm fuzzy radius-match,
      latent, not reachable via the 2 documented build commands), #5-8
      (duplicated tolerance logic, minor JS copy-paste, stale comment) left
      open, not blocking. Both HTML outputs rebuilt + Playwright-verified after
      these 3 fixes.
- [x] VARIAC DIAL UNIT CORRECTION (user correction): the "POWER SUPPLY
      IDENTIFIED" entry above (2026-07-02) wrongly assumed the 0–270 dial scale
      read output VOLTS directly. **Corrected: the scale is DEGREES of rotation**,
      not Volts — output voltage instead scales ~linearly with angle up to the
      input voltage at full rotation: `V(dial_deg) = (dial_deg/dial_max)*
      output_V_max`, e.g. dial=220° → V≈195.5V, dial=270°(max) → V≈240V.
      **This resolves the previously-"not resolved" DISCREPANCY** (dial 220 vs
      multimeter 190V→5A): 195.5V calculated vs 190V measured is only a ~5.5V
      gap (sag under load), not a real conflict. Measured dial(deg)→current
      anchors are UNCHANGED (0°→0A, 220°→5.00A, 270°→7.75–7.85A, midpoint 7.78A
      kept as the anchor) — only the degree↔Volt interpretation was wrong.
      `params.yaml` `power_supply` block gained `dial_unit: degrees`,
      `output_V_max: 240.0`, `degree_to_volt_ratio: 0.88889`. `config.py` gained
      `Config.dial_to_voltage_V(dial)`. Fixed a real downstream bug this exposed
      in `build_twin_html_fem.py`: the HTML twin's header badge (`#hdrIBadge`)
      was displaying the raw dial-angle value labeled as "~V" (e.g. "~220 V" at
      the 5A op point) — now computes true volts via the same ratio
      (`dialToVoltageV()`, fed from `PARAMS.power_supply.degree_to_volt_ratio`).
      Verified headless (Playwright, `digital_twin_fem.html`): dial=220°→badge
      "~196 V" (was "~220 V"), dial=270°→badge "~240 V" (was "~270 V"), 0 JS
      errors. Both HTML outputs rebuilt.
- [x] WP-PEAK (docs/archive/2026-07-04_AUDIT_FIX_PLAN.md Phase 2, H2/M5/M6/L2):
      **RMS/peak convention cleanup for the FORCE chain** — the most sensitive WP,
      run alone after Phase 1 since it touches `em_solver.py`/`config.py` shared
      by everything else. Hard constraint respected throughout: the LOSS chain
      (`compute_losses`→hA calibration) still uses `cfg.I` as amplitude
      unchanged — verified `P_plate(5A)=9.6727W`, `P_coil=128.169W`, I²-check
      4.000000, energy balance 0.000% all bit-identical to before.
      `config.py` gained `Config.I_peak = I*sqrt(2)` (documented convention).
      `em_solver.py`: `material()`/`solve_em()`/`solve_em_saturating()` gained
      an `I_amplitude` param (None default = old behavior, zero change for any
      caller not passing it explicitly) so the FORCE path can request the true
      phasor amplitude without mutating cfg or re-deriving Js by hand.
      `compute_lift_force()` gained the same param; `run_rig_validation()` now
      passes `I_amplitude=cfg.I_peak` — this REPLACES the old undocumented
      "multiply F_z by 2.0 by hand" pattern, and for the first time makes
      `run_rig_validation()` actually bracket F_gravity and print the correct
      z_eq (was printing a false "does not bracket" conclusion despite the
      real disc levitating — the exact bug H2 described). Also fixed a
      pre-existing unit-confusion bug in the same function while touching it:
      the interpolated `z_eq` is the PLATE-BOTTOM equilibrium (~4.1mm) but was
      being compared directly against the "~7-8mm" OBSERVED value, which is
      actually the VISIBLE gap (plate TOP above coil top, i.e. z_eq+3mm
      thickness) — now both are printed and labeled separately
      (`z_eq≈4.1mm plate-bottom`, `visible gap≈7.1mm`, correctly MATCHes the
      7-8mm observation). `run_benchmark_validation()` (the separate, still-
      PAUSED 37%-error TEAM28 benchmark) was deliberately left untouched (its
      `current_A=20` is the original academic problem's own convention, not a
      multimeter RMS reading like the rig's 5A) — verified: z_eq still prints
      exactly 7.1mm, unchanged.
      `check_saturation()` gained a `B_scale` param (default 1.0, so
      `solve_em_saturating()`'s own internal Picard loop — which feeds back
      into the protected loss chain — is untouched) so REPORTING call sites
      (the `em_solver.py __main__` B-vs-B_sat print, and both `B_max_iron`/
      `B_max_iron_v` bakes in `build_twin_html_fem.py`) can request the TRUE
      physical B via `B_scale=cfg.I_peak/cfg.I` — meaningful now that it's
      compared against a real material constant (B_sat_T). Verified:
      "MAX B in iron" now prints 0.047T (was 0.033T, exactly ×√2), HTML
      `ROM.B_max_iron`=0.047 confirmed matching headlessly. `build_twin_html_fem.py`'s
      `_lev_anchor()` had its own manual `cfg.raw["excitation"]["current_A"] =
      5.0*sqrt(2.0)` mutation hack removed, replaced by the same clean
      `I_amplitude=cfg.I_peak` parameter — re-ran `_lev_anchor(80.0)` and
      `_lev_anchor(101.0)` fresh and diffed every field against the cached
      `LEV_ANCHORS` dict: exact match, zero double-correction.
      M5: `solve_em_saturating()` gained a guard that prints a clear WARNING
      if `outer_iron_ring.mu_r>5` while its own Picard loop still only tracks
      `iron_core` — currently inert (ring's mu_r=1.0) but will fire loudly if
      someone flips it without also generalizing the loop. M6: `z_fine_top` in
      `make_mesh_em()` now adds `payload_model.thickness_mm` when the payload
      is enabled (was silently under-meshing a thick payload). L2: removed
      dead `on_boundary()` in `thermal_solver.py` (verified: energy balance
      still 0.000% after removal).
      **Side finding, NOT fixed (out of scope, flagged for follow-up)**:
      `validate_domain_size()` now prints FAIL (P_plate diff 2.71% > 1.0%
      tolerance) where CLAUDE.md's own "Domain validation" entry documented
      PASS (<0.06%) — reproduced this FAIL against the untouched HEAD version
      of `em_solver.py` too, so it predates WP-PEAK entirely and isn't caused
      by the RMS/peak changes; likely drifted from an earlier session's
      params.yaml geometry corrections. Needs re-verification before trusting
      the ±500mm em_domain size again.
      Both HTML outputs rebuilt + Playwright-verified: `levGapEqMm(5)=4.1`,
      `I_LEV_MIN=4.543A`(R80)/`6.450A`(R101), `saturated=False`, 5 variants,
      0 JS errors on both files.

## 2026-07-10 — plate_library real-disc data swap + center core/iron ring material flip

Two separate user-supplied data updates in one session, both cascading into
re-runs of the full pipeline.

**1. `plate_library` replaced with the team's real measured discs.** User supplied a
table of physically-owned aluminium discs (radius/diameter/thickness/mass). Old
entries (Al Ø100/200/202mm, Cu Ø160mm — never real stocked discs) dropped; new
entries: Al Ø130/140/150/160mm (r=65/70/75/80mm, mass_g=113/126/142/159 — all within
~3% of idealized ρV, good tolerance check), Ø160mm marked as the standard test disc
(matches `plate_material` default r=80mm). 3 hollow/annular discs (Al Ø110/55mm,
r_out=55mm/r_in=27.5mm bored hole, 3 thicknesses 3.5/2.8/1.8mm, mass_g=79/60/41)
recorded in a NEW separate key `plate_library_annulus_TODO` — deliberately kept OUT
of `plate_library` because `thermal_solver.py`/`em_solver.py` only mesh solid discs
from r=0 (no hole/inner-radius support), and every `plate_library` consumer
(`digital_twin.py`'s RadioButtons, `sim_plates.py`, `build_twin_html_fem.py`'s
`plate_variant_radii_mm()`) treats every entry as solid — mixing the annulus data in
would have silently computed wrong physics (hole treated as solid metal). Idealized
annulus mass runs 10-18% BELOW mass_g for all three (unlike the solid discs' ~3%
match) — unexplained, flagged for whoever adds hole-geometry support later, not
blocking. Verified: `plate_variant_radii_mm()` now correctly returns exactly
`[65.0, 70.0, 75.0, 80.0]`; `sim_plates.py --no-em` and `config.py` run clean.
Updated stale references: `digital_twin.py` docstring, `build_twin_html_fem.py`'s
disc-compare-mode comment (was "5 radii", now 4), CLAUDE.md's "5 live-swappable" →
"4 live-swappable".

**2. Coil/core geometry RE-MEASURED + center core/iron ring material FLIPPED to
confirmed iron.** User supplied a fresh ruler-measured cross-section of the rig,
superseding the 2026-07-01 "physical layout description" pass: center core
r=0-25.9mm (was 25.0mm), inner coil now 27.9-61.9mm/34mm wide (was 28-78mm/50mm —
a big narrowing), iron ring now 64.9-79.9mm/15mm wide (was 81-101mm/20mm), outer
coil now 82.9-102.9mm/20mm wide (unchanged width, was 104-124mm), coil/core height
53mm (was 52mm), `device_frame.air_gap_mm`/`wall_thickness_mm` re-derived from two
new frame-distance measurements (27.5mm/22.5mm, was 50mm/20mm). Separately, and more
consequentially: user re-tested the center core with a magnet and confirmed it DOES
attract — directly contradicting the "CONFIRMED NON-FERROMAGNETIC" 2026-07-01 result
recorded in CLAUDE.md at the time. Flagged this contradiction to the user explicitly
before touching anything (AskUserQuestion) rather than silently overwriting a locked
result; user confirmed the new magnet test is correct and the old one was wrong.
Also confirmed the iron ring (previously "magnet test PENDING") is the same
material. Restored `iron_core.mu_r=1000.0`/`sigma_S_per_m=1.0e6` (the pre-2026-07-01
placeholder value, per docs/physics.md's original "e.g. mu_r=1000" — git history
confirms this was the value before the erroneous non-ferromagnetic downgrade) and
applied the same to `outer_iron_ring` (was `mu_r=1.0`/PENDING).

Re-ran the full pipeline (`em_solver.py`, `thermal_solver.py`, `rom.py`,
`build_twin_html_fem.py`, `sim_plates.py`) against the new params.yaml. Losses
redistributed a lot but total barely moved: P_plate 9.67W→**25.8W** (plate now
geometrically overlaps the iron ring), P_iron 0W→**5.76W** (iron self-heats now),
P_coil 128.2W→**106.4W** (smaller coil mean radii → less resistance), P_total
137.9W→**138.0W** (near-coincidence). B_max=0.66T, unsaturated (B_sat=1.5T). I²-check
still 3.998≈4.000. `validate_domain_size()` now PASSES again (all diffs <1%, e.g.
P_plate 0.767%) — was FAILing at 2.71% before this session for unrelated/unknown
reasons (flagged in the WP-PEAK entry above), incidentally resolved by this rebuild.
`thermal_solver.py` energy balance still exactly 0.000% (plate-only FEM check,
structurally unaffected by the iron-material flip). `solve_em_saturating()`'s
pre-existing M5 guard (see WP-PEAK entry above — "currently inert... will fire
loudly if someone flips [outer_iron_ring.mu_r]") fired exactly as designed: now
prints a WARNING every run since the ring really is high-mu_r, since its own Picard
saturation correction still only tracks `iron_core` (docs/archive/2026-07-04_AUDIT_FIX_PLAN.md
M5, not fixed in this session, not urgent since B_max is well under B_sat).

**Consequential regression, flagged as an OPEN QUESTION rather than fixed**: lift
force with the new iron material is much stronger than before at the same floor
height (F(3.8mm) 1.69N→4.10N), pushing predicted `z_eq` from 4.1mm→**11.7mm** (visible
gap 7.1mm→**14.7mm**) — but the real observed visible gap is still 7-8mm (unchanged,
2026-07-01 observation). This BREAKS the previously exact match (was validated:
z_eq=4.1mm→7.1mm visible ≈ 2.4× disc thickness, matching the user's "2-3×"
observation). Explicitly asked the user how to handle this (AskUserQuestion) before
writing anything into CLAUDE.md as new ground truth: user chose to keep the new
geometry/material data as-is and record the mismatch as an open question, rather
than reverse-fit `mu_r` down to force the old gap to reappear (suspected cause:
`mu_r=1000` is a mild-steel-*like* placeholder, never actually measured via a B-H
curve — the real effective permeability may be much lower). Updated
`params.yaml levitation.z_gap_5A_mm`/`z_decay_mm` to the new physics-predicted
values (11.7mm/11.79mm, from `run_rig_validation()`'s full F(z) sweep and the
existing F(1mm)/F(5mm) decay-length method respectively) with an explicit
OPEN QUESTION comment, rather than leaving the old (now inconsistent) 4.1mm/13.6mm
in place. Also flagged `lumped_thermal`'s `hA_inner`/`hA_outer`/`coil_C_scale` as
STALE (fitted against the old P_inner/P_outer(7.8A)=150.3/161.6W; new values are
127.3/131.7W, ~15-18% lower, plus P_iron/P_plate are no longer ~0) — left UNCHANGED
pending a proper weighted-least-squares refit against `validation_data` (NEXT item,
not a quick substitution). Updated CLAUDE.md ("Device numbers", "First quantitative
result", "Real-rig validation", "Code status", NEXT list) and
`docs/QUICK_START_FOR_AGENTS.md` (added a "GROUND TRUTH v2" geometry table,
superseding but not deleting the old "session 3" v1 table, and closed out its
"Note conflict (not yet resolved)" callout — it had predicted almost exactly this
outcome: "If confirmed ferromagnetic → set mu_r=100-1000 and RE-RUN EM"). Rebuilt
`outputs/digital_twin_fem.html` (1002 KB, placeholder API key verified, no
`AIzaSy...` pattern present) — not yet Playwright-verified in this session (the
underlying physics is mid-open-question, so a full visual QA pass was deferred
rather than rubber-stamping a demo that currently shows an unvalidated ~15mm gap).

---

## 2026-07-11 — WP-PEAK follow-up: `run_benchmark_validation()` missed the RMS/peak fix

Codebase audit (Explore-agent scan for undocumented bugs, prompted by user
asking "are there any hidden bugs that need fixing") found that `em_solver.py`'s
`run_benchmark_validation()` (line 549) still called `compute_lift_force(cfg)`
with no `I_amplitude` argument — falling back to `cfg.I` (RMS-measured value)
as the phasor amplitude, instead of the true amplitude `cfg.I_peak = cfg.I *
sqrt(2)`. Per the CURRENT CONVENTION (see "Device numbers" in CLAUDE.md /
`config.Config.I_peak` docstring), the force chain must use `I_peak` — only
the loss chain is allowed to treat RMS-as-amplitude. Because Lorentz force
scales with amplitude², this under-supplied every `F_z` in the benchmark
sweep by a factor of ~2.

This is the same bug WP-PEAK (2026-07-10, commit c37e8b8) already fixed in
the sibling function `run_rig_validation()` (line 614) — `git blame` showed
line 549 unchanged since `e0ee206d` (2026-06-15), i.e. it predates the
WP-PEAK fix entirely and was simply missed when that commit swept the file.

**Fix**: `compute_lift_force(cfg)` → `compute_lift_force(cfg, I_amplitude=cfg.I_peak)`
at line 549, with a short comment mirroring `run_rig_validation()`'s existing
WP-PEAK comment block so a future pass doesn't reintroduce the gap a third time.

**Verification**: re-ran `python em_solver.py` — the benchmark's interpolated
z_eq moved from **6.8mm → 14.5mm** (expected 11.3mm from
`levitation_height_team28.csv`). This is the predicted direction (force was
too small → equilibrium point was too close in; fixing the amplitude pushes
the balance point further out, toward 11.3mm) and confirms the bug was real —
but the result now *overshoots* (28% over) instead of *undershooting* (40%
under), so a separate, still-unexplained physics/mesh discrepancy remains.
Re-ran `python thermal_solver.py` as an unrelated regression check: energy
balance still exactly 0.000% (unaffected, as expected — that solver doesn't
touch `compute_lift_force`). Did not touch `run_rig_validation()` or any other
`compute_lift_force`/`solve_em` call site — grep confirmed all other sites
already pass `I_amplitude`/`cfg.I_peak` correctly. The `run_benchmark_validation()`
"PAUSED... unexplained" status in CLAUDE.md remains appropriate — this fix
narrows the gap but does not close it — only the specific 6.8mm/40% figure
was stale and has been updated to 14.5mm/28% (overshoot).

Also surfaced by the same audit but explicitly deferred by the user (not
acted on this session): stale pre-2026-07-10 coil-geometry numbers in
`docs/REPORT_WHY_CUSTOM_CODE.md`/`_DE.md`; hardcoded copper `rho`/`cp` in
`build_twin_html_fem.py:363` duplicating `params.yaml material_props.copper`;
`build_twin_html_fem.py --bake-key` defaulting to the placeholder even on the
user's own machine with `local/.env.local` present (by design, per the
2026-07-04 security fix — flagged as a possible UX mismatch, not changed).

---

## 2026-07-11 — Post-remeasurement cleanup: 4-phase fix from a Fable full-project review

User asked "fable" (an external review agent) to audit the whole project for
whether the 2026-07-10 geometry re-measurement (commit 389d219: coil radii,
iron confirmation) had been fully propagated into the thermal model, what bugs
it might have left behind, and what stale code/docs were still hanging around.
The review returned 4 priorities; user approved doing all 4 in one pass.

**Phase A — Correctness sync (commit 9c4c753).** The WP-PEAK fix Fable flagged
as "uncommitted" in `em_solver.py` turned out to already be committed (04e6900,
same session as the audit — see the "WP-PEAK follow-up" entry above); re-verified
via `git diff`/`git log` before touching anything, so no duplicate fix was made.
What was actually stale: `CLAUDE.md`'s `rom.py` bullet still said
`τ=5.53min@R=80mm` (pre-remeasurement value) — re-ran `python rom.py`, got
τ=244.3s=4.07min, updated the doc. `params.yaml`'s `power_ref_W` (used only by
`sim_plates.py --no-em`'s fallback path) still had the 2026-07-01 value 9.67 —
updated to 25.825 (current P_plate at 5A) with a comment noting the two prior
stale values (9.67W, and an even older wrong 2.63W) for context.

**Phase B — Thermal calibration refit (commit fb2bd78).** `lumped_thermal`
(hA_inner/hA_outer) was fit 2026-07-01 against P_inner/P_outer=150.3/161.6W
@7.8A; the 2026-07-10 geometry update dropped these to 127.3/131.7W (~15-18%
lower) plus added nonzero P_iron/P_plate, so the old hA values no longer
reproduce the measured Session 1 steady-state temps. Re-derived hA via the
same steady-state energy-balance method as the original fit (mirrors the
coupled inner↔iron node solve in `build_twin_html_fem.py:384-394`), using the
new P_inner/P_outer and the existing `validation_data.thermal_at_7p8A`
(T_inner=79°C, T_outer=74°C, T_amb=29°C measured). Result: `hA_inner`
3.5611→**3.0605**, `hA_outer` 4.3446→**3.5986** (both down ~14-17%, expected
since coil losses fell while total system loss rose via plate/iron self-heating).
Verified by hand-solving the 2×2 coupled system with the new hA: T_inner_ss=
79.25°C (measured 79°C), T_outer_ss=74.00°C (measured 74°C exact). `coil_C_scale`
(0.2241) deliberately left UNCHANGED — refitting it properly requires an
iterative weighted-least-squares fit against the `thermal_ramp_test` trajectory,
which is a separate, longer task; documented as NEXT in both `params.yaml` and
`CLAUDE.md` rather than guessed at.

**Phase C — Generalize saturation correction (commit aa9537c).** Since
2026-07-10, `outer_iron_ring` is confirmed ferromagnetic (`mu_r=1000.0`, same
as `iron_core`), but `solve_em_saturating()`'s Picard loop only ever corrected
`iron_core`'s μ_r(B) — `outer_iron_ring` stayed pinned at its linear value,
silently (a known gap since docs/archive/2026-07-04_AUDIT_FIX_PLAN.md M5, dormant only
because `outer_iron_ring.mu_r` used to be 1.0/air-like). Rewrote the function
to track both regions independently: separate `iron_idx`/`oir_idx` element
selection, separate `nu_iron`/`nu_oir` arrays and `mu_r_lin`/`B_sat` per region,
single unified convergence check on the vector-potential field. Verified
byte-for-byte unchanged losses before/after (P_plate=25.81W, P_iron=5.86W,
P_coil=106.44W) — both regions are still unsaturated at 5A (B_max=0.66T ≪
B_sat=1.5T, μ_r_core≈993/μ_r_ring≈984), so this is a correctness fix for
*future* B-H data, not a behavior change today.

**Phase D — Code cleanliness (commit 418160e).** Documentation-only: expanded
the comment around `build_twin_html_fem.py`'s `T_AMB_FALLBACK_C = 29.0` JS
constant to explain the intentional split (FEM solves at physics-reference
T_amb=20°C per the professor's "keep it simple" directive; the *display*
fallback of 29°C matches the HIKMICRO validation session's actual ambient, used
only when the live Google Weather API call fails). Similarly annotated
`data_io.py`'s `_mock_stream` hard-coded constants (`T_amb=20.0`,
`dT_core_ss=25.0`, `dT_disc_ss=11.46`, `tau_core_s=300.0`, `tau_disc_s=632.0`)
as test-fixture-only values that don't read `params.yaml` and don't track the
current calibration — meant to generate a plausible-looking mock CSV for
`data_io.py --mode calibrate`, not to be physically authoritative.

**Not done this session (see CLAUDE.md NEXT list):** full transient
least-squares refit of `coil_C_scale`; porting the English report's "section
2.5" (commit 19e4161) into the still-untracked German
`docs/REPORT_WHY_CUSTOM_CODE_DE.md`.

---

## 2026-07-11 — Second audit: found and fixed one real bug left by the Phase A-D pass above

User asked for a full re-audit of the 2026-07-10/11 changes (geometry
re-measurement, iron confirmation, Phase A-D above), specifically suspicious
that "the model updated today might have affected results and caused
unwanted outcomes." Ran 3 Explore agents in parallel (EM chain, thermal/ROM
chain, HTML+docs staleness) before touching any code. Full findings, the
verified-clean list, and the two experiment write-ups (WP-6, WP-7) live in
**docs/archive/2026-07-11_BUG_REGISTER.md** — this entry is the short version.

**The one real numeric bug: Phase B's hA refit used the wrong formula.**
Phase B (above) solved `hA_inner`/`hA_outer` from `AIR_DT_SS = P_total(7.8A) /
hA_far`, but used `P_total` = coils+iron+**plate** (336W/40=8.40K). The code
that actually runs (`build_twin_html_fem.py`'s `AIR_P_SUM_REF`) only sums the
coil+iron lumped nodes — the plate is a separate ROM node that sheds directly
to far ambient, never through the shared coil/iron air pocket. The 1.57K gap
(=P_plate/hA_far) meant the deployed twin would show coil steady temps ~1.6°C
below the 79/74°C validation anchor Phase B was trying to match. Re-solved
using the code's own formula: `hA_inner` 3.0605→**2.9493**, `hA_outer`
3.5986→**3.4509** — verified by hand: T_inner=29+127.32/2.9493+6.83=79.00°C,
T_outer=29+131.71/3.4509+6.83=74.00°C, exact.

**Two smaller latent bugs found in `em_solver.py`, both from Phase C's own
generalization being incomplete:** `compute_losses()`'s iron-loss classifier
still gated on `iron_core.enabled` only (an `elif` catch-all) rather than
testing `outer_iron_ring`'s own r/z box — harmless today (both regions
enabled) but would silently drop the ring's loss from every `P_*_W` total if
`iron_core` were ever disabled while the ring stayed on. `check_saturation()`
(the *reporting* function, separate from the Picard *solver* Phase C already
fixed) still only scanned `iron_core`'s box for `B_max_iron` — a ring-only
saturation event would never have tripped the "SATURATED" warning. Both
fixed with explicit region membership tests; verified byte-identical losses
before/after (P_plate=25.81W, P_iron=5.86W, P_coil=106.44W unchanged).

**Comment sweep:** several comments in `em_solver.py` and `params.yaml` were
still describing the pre-2026-07-10 state (iron core "non-ferromagnetic",
outer ring "81-101mm, magnet test PENDING", outer coil "r=124mm", and a
`current_A` comment telling readers to manually "multiply F_z by 2.0" — a
pattern WP-PEAK replaced back on 2026-07-10). All corrected.

**Two experiments, both report-only (no defaults changed):**
- **WP-6** re-tested `coil_C_scale`/`coil_G_wind` against the corrected hA +
  new loss distribution by replicating `romStep()`'s two-node model in
  Python and fitting against `thermal_ramp_test`. The existing values
  (unchanged since 2026-07-01) still score RMS=2.56°C — a least-squares
  search only reached 2.50°C at a degenerate, physically-unmotivated
  optimum. Held unchanged; documented in `params.yaml`.
- **WP-7** added `compute_lift_force(cfg, saturating=True)` (default False,
  opt-in) to test whether the fixed-μ_r linear force model — vs the
  Lorentzian saturation model Phase C already wired up for loss reporting —
  explains any of the open "LIFT FORCE MISMATCH" gap (predicted 14.7mm
  visible vs observed 7-8mm). It doesn't: at I_peak (B~0.68T RMS), F_z
  changes by <0.1% everywhere in the rig sweep and z_eq is identical to 2
  decimals (11.75mm) either way. Recorded as a new data point on the open
  question in CLAUDE.md — per user instruction, μ_r was NOT reverse-fit to
  close the gap.

**`outputs/digital_twin_fem.html` rebuilt** after the hA fix (it had been
baking the new 2026-07-10 losses/geometry correctly but still had the old,
buggy hA baked in — internally inconsistent). Verified: no old hA values
present, new values present, no real API key baked (grep-only check, file
never read in full).

**Not done this session (deferred to a future pass, see
docs/archive/2026-07-11_BUG_REGISTER.md "Not investigated"):** porting corrected
geometry into `docs/REPORT_WHY_CUSTOM_CODE_DE.md`/EN counterpart; CLAUDE.md
has drifted back over its own ~200-line budget (304 lines) since the last
WP-TRIM — flagged for the user, not trimmed unilaterally (WP-TRIM requires
explicit user approval per `docs/archive/2026-07-04_AUDIT_FIX_PLAN.md`).

## 2026-07-28 — SSOT integrator port + PyVista desktop 3D twin (WP-HOOK → WP-DOC)

Full plan: `docs/archive/2026-07-28_PYVISTA_TWIN_PLAN.md`. Root problem this session
set out to fix: the physics was split in two. `build_twin_html_fem.py`
computed per-plate *coefficients* in Python (`lumped_physics`/`lev_params`)
but its 3 time *integrators* (dual-β disc, lumped coil/iron/air RC,
levitation spring-mass-damper) existed ONLY inside the baked JS — writing a
third (PyVista) twin the naive way would have meant a third, independently-
drifting copy of the same physics, the exact bug shape as the WP-PEAK missed
call site (CLAUDE.md). User chose the disciplined route: pin Python↔JS
FIRST, then build 3D on top of a single shared integrator.

**WP-HOOK** — added exactly one debug hook, `window.twinDebug.traceRom()`,
to the JS template (`build_twin_html_fem.py`). Drives `romStep`/`levStep`
directly per-step, bypassing the render loop entirely (no physics/DOM/
render change). `resetSim()` doesn't reset `lev`/`paused` — a deliberate,
pre-existing design (matches every other call site) — so `traceRom` calls
both explicitly for a reproducible trace. Verified via Playwright: 0 console
errors, screenshot pixel-identical before/after (one visible digit diff
traced to pre-existing wall-clock jitter, confirmed by re-loading the same
build 3 times and seeing it vary run-to-run regardless of the HOOK change).

**WP-CORE** — new `twin_core.py` (the integrator SSOT: `RomCoeffs`/
`LumpedCoeffs`/`LevCoeffs`/`TwinState`, **numpy+stdlib only**, checked by its
own self-test) ports `romStep`/`levStep` line-for-line, preserving all 9
JS-port traps identified in the plan doc (coil-before-β ordering, σ-scale
using the previous step's TOTAL β not β_eddy, `q_cond` from stale T, air
node updated after the node loop, `hAEff`'s 0.1K floor, β clamped inside
each substep, `levStep` never substepped, the asymmetric current clamp
between `romStep`/`levStep`, `levStep` seeing I at t_{n+1}). New
`twin_model.py` holds the heavy bridge (`resolve_active_plate`/`PlateCache`/
`i_max_for`/`coeffs_from_live`/`build_plate_variant`) — `lumped_physics`/
`lev_params` stayed put in `build_twin_html_fem.py` as instructed (that file
gets Playwright-reverified after every change; touching it is extra risk
for zero benefit here). 6/6 self-checks passed, but two needed real
debugging, not just writing code: (1) a synthetic coil/air network with
`hA_far` too small relative to total thermal mass had a genuine ~2000s
dominant time constant — looked like non-convergence, was actually just
under-integrated (fixed by running a longer horizon, not by "loosening a
tolerance"); (2) `coilTss_inner()`/`coilAirDrive()`'s JS steady-state
formulas turned out to be intentional *approximations* (they normalize by
the naive `P_ref/hA`, not the true iron-coupled `dT_cal`) — exact only when
`G_cond=0` or `I=I_ref`, a real property of the JS UI code discovered by
trying to pin against it exactly, not a porting bug.

**WP-XVAL** — new `xval_twin.py` pins `twin_core.py` against the actual
baked JS via Playwright, two INDEPENDENT assertions with different failure
messages: (A) raw integrator match, 7 schedules (step/step-to-0-from-hot/
ramp/pulse-crossing-I_LEV_MIN/sine/dt=25s/20A-clamp), abs tol 1e-9 — every
quantity landed at 0 or ULP noise (≤2.2e-14); (B) bake freshness, rel tol
1e-6, baked `PARAMS` vs a fresh `lumped_physics`/`ThermalROM().build()` —
this is the exact d4f73d6/WP-5 bug class, and assertion A structurally
cannot catch it (it only checks JS-vs-Python self-consistency, not either
side against current `params.yaml`). Network blocked except a disk-cached
`unpkg.com` (`outputs/.jscache/`, gitignored, fetched once). Along the way,
building the test schedules surfaced two real `traceRom` bugs from WP-HOOK,
fixed in place: `I` was scalar-only (couldn't express a time-varying
schedule at all — extended additively to also accept a per-step array,
scalar callers unaffected), and `lev.z/v` weren't reset (same root cause as
the `coilTss`/`coilAirDrive` finding above — traced to a real, deliberate
`resetSim()` design point, not a regression). Proved the pinning test isn't
vacuous per this repo's WP-PEAK-burned policy: temporarily swapped the
coil-integration block to run AFTER the β update (breaking trap 1), rebuilt,
reran — assertion A correctly went red (β diffs up to 5e-2), then reverted.

**WP-CORE2** — deleted the second β model. `digital_twin.py`'s own
`DigitalTwin`/`SCENARIOS`/`_build_rom_for_plate` removed; now imports from
`twin_core`/`twin_model`. Its speed-aware substep loop (`n_steps`/`dt_eff`)
is gone — `TwinState.step()`'s own τ-aware rule (shared with the JS render
loop) runs internally; UI-only history tracking (`hist_t`/`hist_Tmax`/...)
moved into `run_live()`'s own `state` dict since `TwinState` is a pure
integrator with no plotting bookkeeping by design. `data_io.py:249`
(`live_compare()`) — the exact WP-PEAK-shaped call site this repo has
learned to grep for — switched to `twin_core.TwinState` +
`twin_model.coeffs_from_live()`; `em=None` fallback added for
`digital_twin.py --no-em`'s fast-startup path (skips `compute_eddy_fraction`,
falls back to the single-β model). `grep -rn "class DigitalTwin" *.py` → 0
results (the plan doc's own verification line expected 1, in `twin_core.py`
— but that class is named `TwinState` there, established and xval-pinned in
WP-CORE, not renamed to match a stale plan-doc guess). GUI verification
gap, disclosed rather than glossed over: `python digital_twin.py --no-em
--speed 50` launches cleanly and stays alive consuming CPU, but this
sandbox can't screen-capture (`screencapture` → "could not create image
from display") to confirm T-rising/plate-rebuild visually — verified
instead by headlessly driving the exact same building blocks `run_live()`
wires together (T rose 20→52°C under load, plate switch rebuilt a
genuinely different ROM, reselecting reused the cache).

**WP-GEO → WP-PLATE** — new `digital_twin_pyvista.py`, a third live twin
(PyVista/VTK desktop 3D), parallel to (not replacing) `digital_twin.py` and
the HTML build. `pip install "pyvista>=0.45" "vtk>=9.3,<9.7"` took ~25 min
in this sandbox — a genuinely slow connection (~30-75 KB/s, confirmed via
`lsof`/`nettop` mid-download, not a stuck resolver as first suspected: an
early "no cache growth in 10 minutes" reading led to killing the process,
which turned out to be actively downloading a 107MB VTK wheel at ~35MB in;
the retry had to redownload that wheel from scratch). Geometry reuses
`build_twin_html_fem.py`'s procedural builders verbatim
(`build_octagonal_base/frame`, `build_solid_core`, `revolve_ring`,
`build_disc_mesh`, `compute_em_field_lines`, `compute_eddy_field` — no
second geometry implementation); Z-up mm, no Y-up rotation (that's
three.js-only); disc mesh built via `pv.PolyData.from_regular_faces` on the
RAW triangle soup, never `.clean()`-ed (would
silently desync the per-vertex `dT_eddy`/`Je` arrays from the point order).
B-field lines are one hand-built `PolyData` with an explicit `lines` cell
array (21 contours × 4 azimuths = 84 polylines) — `pv.MultipleLines`/
`lines_from_points` would wrongly stitch contour k's last point to contour
k+1's first. Disc-radius rebuild runs on a worker thread
(`PlateRebuildWorker`) with `matplotlib.use("Agg")` forced once on the main
thread at import time (`compute_em_field_lines` calls it as a side effect;
`matplotlib.use()` isn't thread-safe) so the live sim keeps ticking on the
old mesh during a rebuild instead of blocking, unlike `digital_twin.py`'s
pause-and-block approach. `--self-check` runs with no VTK installed
(import-guarded like `visualize.py`'s `plot_pyvista()`). Verified: self-check
PASS (960/960/960/960/96 tris, 21 field lines, 84 polylines once VTK was
in — all matching the HTML build's own numbers exactly);
`--screenshot outputs/twin_pv.png --no-show` renders correctly (checked
visually: octagonal wood frame + floating disc, correct blue→red colour
range); a disc-hidden top-down render matches `docs/real_model.png`'s
concentric ring structure ring-for-ring (wood → dark outer coil → grey iron
ring → dark inner coil → grey core). Real interactive-window behaviour
couldn't be watched directly (no capturable display in this sandbox), so
every callback (`step`, space/reset key handlers, thermal/eddy/field mode
toggle, the worker-thread plate rebuild) was instead driven headlessly and
checked for the right physics: disc lifted by EXACTLY `z_gap_eq(5A) ×
z_gap_exaggeration` = 11.7×2 = 23.4mm, T_max rose and saturated on the
expected RC curve, mode toggle switched active scalars/field-line
visibility correctly, plate rebuild swapped the actor and produced τ=229.8s/
I_LEV_MIN=4.011A for the Ø130mm variant — identical to the standalone
`PlateCache` test from the WP-CORE session. A found-and-fixed bug along the
way: an early draft's `_repaint_disc()` had a tautological ternary
(`"dTe" if mode != "eddy" else "dTe"`, always `"dTe"` regardless of mode) —
caught by re-reading the diff before trusting it, not by a test (the eddy
branch didn't use the value anyway, so nothing would have visibly broken;
still wrong code, fixed).

**WP-DOC** — this entry; CLAUDE.md/`docs/ARCHITECTURE.md`/`README.md`
updated with `twin_core.py`/`twin_model.py`/`xval_twin.py`/
`digital_twin_pyvista.py`, `requirements.txt` got an optional, clearly-
commented pyvista/vtk block. Also fixed a drift CLAUDE.md's WP-Z0 bullet had
accumulated: it still named `z_gap_5A_mm=4.1`/`z_decay_mm=13.6` as current,
but `params.yaml` was superseded same-day (2026-07-10) by the coil-radii
remeasurement to `11.7`/`11.79` — `params.yaml` is the SSOT, so the bullet
got an appended correction rather than a silent rewrite (preserves why the
13.6 number existed at all). CLAUDE.md is now well past its own ~200-line
target (over 350 lines) — flagged again, not trimmed unilaterally, same
policy as the 2026-07-11 entry above.

---

## WP-LEV / WP-COOL / WP-SHIMMER (2026-07-28) — three user-reported HTML-twin
defects, root-caused and fixed same session in `docs/archive/2026-07-28_BUG_REGISTER.md`,
work order in `docs/archive/2026-07-28_PROMPT_WP_COOL_LEV.md`. All three land in BOTH
`twin_core.py` (SSOT integrator) and the baked JS in `build_twin_html_fem.py`,
pinned by `python xval_twin.py` (assertion A: integrator match, all-zero diffs
this session, i.e. bit-exact; assertion B: bake freshness, 0 relative diff) —
**PASS**.

**WP-LEV** (bug register L1/L2) — the Ø160mm (R=80) disc floated HIGHEST of
the four plate-library discs; physics says it should float LOWEST (mass grows
∝R² while lift saturates). Root cause: `_lev_anchor()`'s `z_eq` solve was a
3-point `np.interp` over z=[1, 3.8, 5]mm, which `numpy` CLAMPS outside its
range — every disc whose true crossing lay past 5mm (R=65/70/75, true
crossings 13.6-15.7mm) silently got `z_eq=5.000` exactly; R=80 only looked
different because `lev_params()` special-cased it straight to `params.yaml`'s
own independently-swept anchor, splitting the SSOT in two. Fix: `_lev_anchor()`
now does a real bracketing root-find (coarse scan z=1→40mm in 2mm steps to
find the sign change of F(z)−F_grav, then `scipy.optimize.brentq` to
converge), and `lev_params()`'s R=80 special case is deleted — every radius,
default included, goes through the same code path now. One wrinkle found
along the way: `compute_lift_force()` has a real (small) mesh-quantization
artifact at R=70mm — F(z) dips a few hundredths of a Newton below F_grav in a
~0.2mm-wide notch near z=14.0mm before recovering and continuing its smooth
decline to the true crossing further out. A naive "stop at the first sign
change" bracket locks onto that transient notch; `_find_z_eq()` now requires
the sign to persist for one more coarse step before accepting a bracket to
refine. `LEV_ANCHORS` (the stale hardcoded R=80/R=101 cache, both from the
pre-2026-07-10 geometry) is deleted outright — every anchor is live-computed.

Rebaked `PARAMS.plate_variants[*].lev.z_gap_5A_mm`: **65→15.99mm,
70→14.03mm, 75→13.97mm, 80→11.94mm** — strictly decreasing, no value clamped
to 5.000, R=80 reproduces `params.yaml`'s independently-derived 11.7mm to
within 0.24mm (different sweep resolution, not a method difference). R=70's
14.03mm sits further from the bug register's own reconnaissance estimate
(14.95mm, from a coarser 10-point sweep) than the other three radii — a
residual of the same mesh-quantization artifact the notch-persistence guard
only partially compensates for (the true smooth crossing and the artifact's
own zero-crossing are close together for this one radius). Not treated as a
blocker: the qualitative fix (no clamping, correct monotone ordering) is what
mattered, and z_eq/z0 were already documented "order-of-magnitude,
mesh-sensitive" before this session.

**WP-COOL** (bug register T1-T5) — coils AND disc cooled 4-9× too fast
against the current dropping (shipped: inner coil lost half its rise in
**102s**; real rig takes many minutes). Four structural defects, all fixed
without touching `coil_C_scale`/`coil_G_wind` (their physically-derived
values were correct all along — see the trade-off note below):

- **T1** — the coil surface node received 100% of `P_ref` but only
  `coil_C_scale`=22.4% of the copper mass (the deep winding-core node, 77.6%
  of the mass, had no source term at all) → 4.46× too fast both directions.
  Fix: `lumped_physics()` now emits `P_ref_surf`/`P_ref_deep` (split in the
  same ratio as `C`/`C_deep`) on the inner/outer nodes; `_rom_step()`/
  `romStep()` apply them separately. Steady state is provably unchanged
  (surface+deep power sums back to the original `P_ref`) — verified.
  `NodeCoeffs`/JS tolerate the keys being absent (old bake) by falling back
  to 100%-on-surface, i.e. today's shipped behaviour exactly.
- **T2** — the iron/core lumped node's heat capacity was coded as
  `0.5*C_plate` = 73.3 J/K — half the *aluminium disc's* capacity, unrelated
  to iron and 23× too small. Fix: real `C_iron = rho_Fe*cp_Fe*(V_core+V_ring)`
  computed from `iron_core:`/`outer_iron_ring:` geometry + a new
  `material_props.iron` block (`rho_kg_per_m3=7870`, `cp_J_per_kgK=450`,
  mild-steel-like, matching the existing `mu_r=1000` placeholder) — **1676.3
  J/K**, matching the bug register's hand-derivation exactly. Both regions
  honour their own `enabled` flag. Sanity-printed in the build log
  (`[LUMPED] C_iron=1676.3 J/K ...`).
- **T3** — the disc ROM used ONE τ for both heat-up and cooldown, but
  `rom.UA` came from a FEM with `h_bottom_W_per_m2K=25` ("enhanced convection
  facing coils" — the coil plume), which dies when the current does. Fix:
  new `disc_tau_cool_natural_frac(cfg)` derives
  `f_nat = UA_natural-everywhere / UA_as-built(plume-on)` from the ACTUAL
  `thermal_bc` h-values + disc geometry (never pasted) — **0.5804** at the
  default R=80mm/3mm disc, matching the bug register's 0.58 hand-calc.
  `TwinState._rom_step()`/`romStep()` now compute
  `tau_eff = rom.tau / (f_nat + (1-f_nat)*min(1, coilAirDrive()))` and use it
  for BOTH β-target updates (β only sets the RATE, never the steady target,
  so steady state is unaffected). `tau_cool_natural_frac` defaults to 1.0
  (old bake) → `tau_eff == rom.tau` always, i.e. today's shipped behaviour.
- **T4** — `hA_inner`/`hA_outer` were solved from the LINEAR steady-state
  balance (`T = T_amb + P/hA + AIR_DT_SS`), but the deployed integrator
  applies the NONLINEAR `hAEff = hA_cal·(ΔT/ΔT_cal)^convection_exponent`
  correction on top — since `dT_cal` anchors at `I_ref=5A`, the correction
  pushes `hA_eff` above `hA_cal` at the 7.8A calibration point, so the
  shipped model settled at inner=72.15/outer=67.78°C instead of the
  validated 79.00/74.00°C (same bug CLASS as B1, 2026-07-11 — a fitting
  formula drifting from the code that actually runs). Fixed via a new
  **committed script**, `refit_hA.py` (not a one-off — the last two hA
  refits both shipped wrong because the fitting formula and the running code
  diverged): it drives the ACTUAL `twin_core.TwinState` integrator (with T1+T2
  already applied) to steady state at 7.8A/29°C and root-finds
  `(hA_inner, hA_outer)` on the residual `(T_inner−79, T_outer−74)` via
  `scipy.optimize.fsolve`. Converged to **hA_inner=2.4744, hA_outer=2.8885**
  (from 2.9493/3.4509) — reproduces `T_inner=79.000°C`/`T_outer=74.000°C`
  EXACTLY through the nonlinear model. `python refit_hA.py` to re-run.
- **T5** — `air_node_C_J_per_K`/`air_node_hA_far_W_per_K` left UNCHANGED
  (both still self-labelled "illustrative"); comments rewritten to state
  explicitly that they are unidentified fudge factors capping the whole
  rig's thermal memory, blocked on a real cooldown log.

Verification (heat to 5A steady state at T_amb=20°C using the FULLY fixed
model — T1+T2+T3+T4 all applied together, real `f_eddy`/`f_air` split from
`compute_eddy_fraction()`, not the single-β default — then I→0):

| | BEFORE (shipped) | AFTER (this session) |
|---|---|---|
| coil t50 | 102 s | **945 s** (9.3×) |
| coil t90 | 2032 s | **3987 s** |
| disc t50 | 194 s | **215 s** |
| disc t90 | 712 s | **1160 s** |
| steady state @7.8A/29°C | inner=72.15/outer=67.78°C | **inner=79.00/outer=74.00°C** |

Coil t50=945s sits ~5% above the 400-900s band estimated during triage
(that estimate predates T4's hA refit, which raises the coils' steady-state
ΔT and shifts the nonlinear-convection operating point during cooldown —
expected drift, not a miss) but is squarely in the qualitative "many
minutes, 4-9×" behaviour the user reported (9.3× measured). Disc t90=1160s
clears the ≥1000s target.

⚠️ **Trade-off, accepted (not hidden):** `thermal_ramp_test` RMS moved from
**2.53°C → 12.43°C** (7 residuals: 5 outer-coil ramp points + inner/outer
@450s). This is the expected, already-decided consequence of T1+T2 — the
2026-07-02 fit bought its 2.53°C by shrinking the copper thermal mass 4.5×
below physical. Per the bug register's trade-off analysis: the ramp data is
internally inconsistent (its t=300s point already exceeds the model's own 5A
asymptote) and cannot be reconciled with Session 1's 74°C steady-state
reading under ANY constants for this network structure — Session 1 and the
ramp are mutually incompatible, and Session 1 (a real steady-state IR
reading) is the stronger constraint. **Do not re-shrink `coil_C_scale` to
chase the 2.53°C** — logging a real cooldown curve + a properly timestamped
heat-up ramp is now the single highest-value measurement for this project
(promoted to the top of CLAUDE.md's NEXT list).

**WP-SHIMMER** (bug register V1/V2) — no fast start-up ramp, and the disc
never visibly moved at any operating current (only a ~1.7s ring-down after a
slider move).

- **V1** — new `quickstart` scenario (`min(t/t_rampup, 1)·I`,
  `t_rampup` = new `transient.quickstart_ramp_s` = 8.0s, user asked 5-10s),
  added to both `SCENARIOS` dicts (`twin_core.py`, imported by
  `digital_twin.py`/pyvista twin for free; JS `SCENARIOS` in
  `build_twin_html_fem.py`). Now the DEFAULT scenario on HTML load
  (`curScenario = 'quickstart'`, was `'step'`) — its own button is first in
  the scenario row, keyboard hint updated `1-4=scenario` → `1-5=scenario`
  (1=quickstart, 2=step, 3=ramp, 4=sine, 5=pulse). `digital_twin.py`'s own
  `--scenario` default is untouched (still `step` — only the HTML twin's
  on-load behaviour was in scope).
- **V2** — `jit_fade_mm=0.5mm` gated ALL disc jitter to the sub-liftoff
  regime, so above ≈3.2A (gap≥3mm) the disc was perfectly rigid. The real
  100Hz force ripple (`F ∝ i²` → 100% modulated at Ω=2ω) only moves the disc
  ~0.025mm at the default constants (1-DOF transfer function
  `|X/X_static|=1/|1-(Ω/ω_n)²|`, X_static=z_decay_mm) — invisible; the real
  rig's visible wobble is the lateral/tilt mode, not this vertical one (see
  `docs/physics.md` §11). New `jit_lev` term, kept explicitly SEPARATE from
  the existing `jit_contact` (unchanged): active whenever `z>0` (levitating),
  amplitude = `x_ripple_mm · lev_ripple_display_gain · (I/5)²` — the physical
  ripple number is COMPUTED (`LevCoeffs.x_ripple_mm`/JS `X_RIPPLE_MM`, from
  `z_decay_mm` + the mains frequency, never pasted; verified 0.0249mm at
  R=80mm/50Hz, matching the physics doc's derivation exactly), then scaled by
  a new, separately-named `levitation.lev_ripple_display_gain=40.0`
  (`# DISPLAY ONLY`, same precedent as `z_gap_exaggeration`) to ~1mm on
  screen. Own phase accumulators (`jitLevPhase1/2`) so it doesn't sync with
  `jit_contact`'s. Verified via `twin_core.TwinState`: displayed position
  (`z+jit`) range at I=3.5/5.0/7.5A is 1.46/2.97/6.69mm (scales ∝I² as
  designed: ratios 1 / 2.03 / 4.58 vs the exact (5/3.5)²/(7.5/3.5)²=2.04/4.59)
  while `mean(z+jit)` stays within 0.001mm of `z_gap_eq(I)` at every current
  — the shimmer rides on top, never biases the mean gap.

**Verification run (all commands, output confirmed):** `python twin_core.py`
6/6 PASS; `python config.py` clean; `python em_solver.py` I²-check
3.998≈4.000, domain-size validation PASS (<1% at all quantities);
`python thermal_solver.py` energy balance error=0.000%; `python rom.py` I²
scaling exact (4.000000); `python digital_twin_pyvista.py --self-check`
PASS; `python build_twin_html_fem.py` rebuilt cleanly (placeholder API key);
`python xval_twin.py` **PASS** (assertion A all-zero diffs across all 7
integrator schedules + the dt=25s substep check; assertion B 0 relative diff
on both `lumped` and `rom.tau`).

New `params.yaml` keys: `material_props.iron.{rho_kg_per_m3,cp_J_per_kgK}`
(T2), `transient.quickstart_ramp_s` (V1), `levitation.lev_ripple_display_gain`
(V2, `# DISPLAY ONLY`). Changed: `lumped_thermal.hA_inner_W_per_K`
2.9493→2.4744, `hA_outer_W_per_K` 3.4509→2.8885 (T4). New committed script:
`refit_hA.py`. `levitation.z_gap_5A_mm`/`z_decay_mm` (params.yaml) are now
documented as reference-only (every radius, R=80 included, computes its own
live anchor via `_lev_anchor()`) — values themselves unchanged.

---

## WP-TIDY (2026-07-28) — repo tidy-up: docs/archive/, CLAUDE.md trim, dead files

Housekeeping session, no physics changed. Three parts. (The `extensions/` folder
landed separately — see WP-EXT below.)

**1. `docs/archive/`.** `docs/` had grown to 20 *.md / 6462 lines, with finished
one-off plans and bug registers interleaved with living reference. Nine
completed docs moved (via `git mv`, rename history preserved) and renamed to
`YYYY-MM-DD_TOPIC.md` so a plain listing reads chronologically:
`3D_MODEL_UPDATE_PLAN` → `2026-06-23_…`; `HTML_TWIN_FIX_PLAN_2026-07-02`,
`PLAN_SIM_FEEDBACK_2026-07-02`, `implemetation_Plan` (misspelling dropped) →
`2026-07-02_…`; `AUDIT_FIX_PLAN_2026-07-04` → `2026-07-04_…`;
`BUG_REGISTER_2026-07-11` → `2026-07-11_…`; `BUG_REGISTER_2026-07-28`,
`PROMPT_WP_COOL_LEV_2026-07-28`, `PYVISTA_TWIN_PLAN_2026-07-28` →
`2026-07-28_…`. New `docs/archive/README.md` indexes all nine with what each
was and how it ended, plus an explicit warning that archived numbers are
frozen-in-time and never the source of truth. All 152 `docs/*.md` references
across 36 files re-pointed and verified to resolve. `docs/math_formulation.md`
kept in place (user decision — still wanted for the report/thesis).

**2. `CLAUDE.md` 432 → 212 lines**, back under its own stated ~200-line budget.
It had accumulated resolved `[x]` entries and superseded history (the
"WAS WRONG (2026-07-01: …)" geometry, the three-round hA refit narrative)
duplicating this file. Before cutting, every dropped fact was verified present
elsewhere (`docs/CHANGELOG.md:684/703/771`, `docs/QUICK_START_FOR_AGENTS.md:8`,
the archive) — nothing lost. Kept in full: the RMS-vs-peak CURRENT CONVENTION,
both OPEN QUESTIONS (lift-force/z_eq mismatch, unmeasured μᵣ), the PAUSED
benchmark, the secrets rule, token discipline. Verbose `[x]` module entries
became a compact table; open items became their own section.

**3. Dead files.** `calc_res.py` deleted — 23-line scratch script, referenced
nowhere, duplicating `em_solver.py:505-510`, and hardcoding an absolute
`/Users/minh/...` path in violation of the repo's own `__file__` self-location
rule. Five orphaned `outputs/` artifacts removed after confirming no current
script writes them (`digital_twin.html` — builder deleted 2026-07-02;
`digital_twin_fem_R101.html` — R=101 dropped from `plate_library`;

Verified: all 152 `docs/*.md` references resolve, `python twin_core.py` 6/6
PASS, `python xval_twin.py` PASS, `compileall` clean. Every changed line in the
10 touched `.py`/`.yaml` files is a comment or docstring — no executable code
changed.

---

## WP-SHIMMER-OFF (2026-07-28, same day as WP-SHIMMER) — sustained vertical shimmer disabled after user review

User drove the freshly-built HTML against the real rig before the planned
commit/push and reported: at a fixed dial/amps, after the physical liftoff
bounce rings down, the disc keeps bobbing up and down "incomprehensibly and
unphysically" — forever. Root-caused (systematic-debugging, reproduced
numerically): the WP-SHIMMER V2 `jit_lev` term shipped 6–14.6× larger on
screen than its own bug-register spec of "~1mm". Three stacked multipliers
were never counted in that claim: the two-sine peak factor
(`sin+0.5·sin` → 1.5×), the `(I/5)²` current scaling (2.43× at 7.8A), and
`Z_GAP_EXAG=2.0` applied to `(z+jit)` in `levLiftY()`. Measured displayed
motion: **6.0mm p2p @5A (25% of the displayed gap) → 14.5mm p2p @7.8A (45%)**
at 4.3+11.3Hz, with a beat envelope (alternating calm/strong — the "confusing"
part) and frame-rate aliasing at time-speed ≳3×. The physics state was proven
clean both ways: `ζ(I)=0.02·(I/5)²>0` always (lev.z provably rings down), and
the on-screen "Levitation Gap" readout (which shows `lev.z` alone) sat
rock-steady while the mesh bobbed. `xval_twin.py` could not have caught this —
Python and JS implemented the same wrong constants identically.

Options offered (reduce to the documented ~1mm / turn off / replace with a
tilt-mode wobble per physics.md §11). **User decision: turn off.** Consistent
with physics.md §11's own derivation: the real vertical ripple is 25µm @100Hz
(invisible), and the rig's visible wobble is the lateral/tilt mode — a
vertical offset cannot honestly represent it.

Change: `params.yaml levitation.lev_ripple_display_gain` 40.0 → **0.0**
(params-only; the `jit_lev` machinery stays in `twin_core.py` + the baked JS,
gated by the gain — a future tilt-mode effect would be a new, separate knob).
`jit_contact` (sub-liftoff buzz) unaffected. Rebaked
`outputs/digital_twin_fem.html` (gain=0.0 confirmed in all 5 baked blocks,
placeholder API key confirmed). Verified: `python twin_core.py` 6/6 PASS,
`python xval_twin.py` PASS (A: all-zero diffs, B: 0 relative diff).
docs/physics.md §11 carries the superseding note.

---

## WP-EXT (2026-07-28) — `extensions/`: the PyVista twin moved out of the flat root

User asked for the PyVista code gathered into its own folder, treated as an
optional add-on to extend later. `digital_twin_pyvista.py` →
`extensions/digital_twin_pyvista.py`.

This is a deliberate, documented carve-out from CLAUDE.md's "source scripts stay
FLAT in the repo root" rule — the first and so far only one. It was admitted on
two conditions, both stated in `extensions/README.md` so the next such request
gets judged the same way: the script needs a heavy dependency the core
deliberately avoids (~400 MB pyvista/vtk), and **nothing in the root imports
it**. The dependency arrow is one-way (`extensions/ → root`, never back), so the
core pipeline still runs end-to-end with the whole folder deleted.

The move needed exactly one code change, because the script never builds its own
paths: `sys.path.insert(0, Path(__file__).resolve().parent)` → `.parent.parent`,
i.e. put the REPO ROOT on `sys.path` rather than the script's own folder. The
root modules it imports (`twin_core`, `twin_model`, `build_twin_html_fem`,
`config`) then self-locate `params.yaml`/`outputs/` via their own `__file__`
exactly as before — which is the whole reason the flat rule exists, and why
honouring it from a subfolder costs one line instead of a refactor.

`extensions/README.md` (new) records the admission criteria plus the copy-paste
contract for future extensions: root on `sys.path`, import-guard the heavy dep,
ship a `--self-check` that runs without it, keep the dep commented out in
`requirements.txt`. `visualize.py --pyvista` deliberately stays in the root — it
is one optional, already-import-guarded flag on an otherwise core script, and
moving it would break `visualize.py`'s own CLI.

Docs updated to match: CLAUDE.md's layout rule now describes four subfolders
instead of three (with the admission criteria inline) and its module table
points at the new path; README.md, `docs/ARCHITECTURE.md` (file tree + both data
flow diagrams + header note), `docs/HANDOFF.md`, `docs/QUICK_START_FOR_AGENTS.md`
likewise.

Also fixed here: `requirements.txt` still carried the pre-archive path of what is
now `docs/archive/2026-07-28_PYVISTA_TWIN_PLAN.md` — the WP-TIDY rename pass
covered `*.py`/`*.md`/`*.yaml` but not `*.txt`. The link checker was widened to
`*.txt` (and to `extensions/`) so this class of miss can't slip through again.

Verified: `python extensions/digital_twin_pyvista.py --self-check` PASS
(960/960/960/960/96 tris + 21 field lines + 84 field-line polylines — identical
to the pre-move baseline), `--screenshot outputs/twin_pv.png --no-show` renders
the device correctly from the new location, `python twin_core.py` 6/6 PASS,
`python xval_twin.py` PASS, 192 doc/extension path references all resolve,
`compileall` clean.
