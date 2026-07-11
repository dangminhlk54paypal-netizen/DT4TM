# CHANGELOG — Thermal Digital Twin (TEAM 28-like Levitator)

Full narrative history of every fix/feature session, moved out of CLAUDE.md
(2026-07-10, WP-TRIM per docs/AUDIT_FIX_PLAN_2026-07-04.md) to keep CLAUDE.md
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
- [x] 4 render fixes (2026-07-02, docs/HTML_TWIN_FIX_PLAN_2026-07-02.md):
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
      "cảm giác dây phải nóng hơn mặt dưới đĩa"). Root-caused: at I_ref=5A/T_amb=20°C
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
- [x] WP-C (2026-07-02, docs/PLAN_SIM_FEEDBACK_2026-07-02.md): **Al Ø202mm disc option**
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
- [x] WP-B (2026-07-02, docs/PLAN_SIM_FEEDBACK_2026-07-02.md): **realistic coil
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
- [x] WP-A (2026-07-02, docs/PLAN_SIM_FEEDBACK_2026-07-02.md): **levitation
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
- [x] WP-D (2026-07-02, docs/PLAN_SIM_FEEDBACK_2026-07-02.md): **constants
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
      docs/PLAN_SIM_FEEDBACK_2026-07-02.md, final section "Câu hỏi cần user trả
      lời" (8 items — gap@7.75A calibration, a genuine numeric conflict inside
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
- [x] DISC-RADIUS COMPARE MODE (2026-07-03, user request: "chuyển các đĩa với bán
      kính khác nhau lên mô hình trong quá trình mô phỏng để nhìn rõ trạng thái
      biến đổi nhiệt"). Both `digital_twin_fem.html` and `digital_twin_fem_R101.html`
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
      docs/AUDIT_FIX_PLAN_2026-07-04.md's Execution Log. Real Google API key
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
- [x] WP-PEAK (docs/AUDIT_FIX_PLAN_2026-07-04.md Phase 2, H2/M5/M6/L2):
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
saturation correction still only tracks `iron_core` (docs/AUDIT_FIX_PLAN_2026-07-04.md
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
"Note conflict (chưa giải quyết)" callout — it had predicted almost exactly this
outcome: "Nếu xác nhận ferromagnetic → set mu_r=100-1000 và RE-RUN EM"). Rebuilt
`outputs/digital_twin_fem.html` (1002 KB, placeholder API key verified, no
`AIzaSy...` pattern present) — not yet Playwright-verified in this session (the
underlying physics is mid-open-question, so a full visual QA pass was deferred
rather than rubber-stamping a demo that currently shows an unvalidated ~15mm gap).

---

## 2026-07-11 — WP-PEAK follow-up: `run_benchmark_validation()` missed the RMS/peak fix

Codebase audit (Explore-agent scan for undocumented bugs, prompted by user
asking "còn lỗi tiềm ẩn nào cần giải quyết không") found that `em_solver.py`'s
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
silently (a known gap since docs/AUDIT_FIX_PLAN_2026-07-04.md M5, dormant only
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
**docs/BUG_REGISTER_2026-07-11.md** — this entry is the short version.

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
docs/BUG_REGISTER_2026-07-11.md "Not investigated"):** porting corrected
geometry into `docs/REPORT_WHY_CUSTOM_CODE_DE.md`/EN counterpart; CLAUDE.md
has drifted back over its own ~200-line budget (304 lines) since the last
WP-TRIM — flagged for the user, not trimmed unilaterally (WP-TRIM requires
explicit user approval per `docs/AUDIT_FIX_PLAN_2026-07-04.md`).
