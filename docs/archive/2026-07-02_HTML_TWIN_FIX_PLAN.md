# Plan to Fix 4 Display Issues — digital_twin_fem.html (2026-07-02)

**Only file to fix:** `build_twin_html_fem.py` (JS template is in this file's HTML string).
**After fixing, regenerate:** `python build_twin_html_fem.py` → `outputs/digital_twin_fem.html`.
**Implementation model:** Sonnet (subsequent sessions). Follow order Task 1 → 4; verify each task before moving to next.

> Source: user report 2026-07-02 (images `docs/z_achse_260701.png`, `docs/thermal_test.png`)
> + Gemini analysis in `docs/archive/2026-07-02_IMPLEMENTATION_PLAN.md`. Claude (Fable) verified
> each claim directly against code on 2026-07-02 — verification results noted at start of each task.
> Line numbers below are correct for build_twin_html_fem.py at 2026-07-02 (pre-fix);
> if file has changed, search by variable/function name instead of line number.

---

## Task 1 — Levitating disc gap displays too high relative to model

### Verification (Fable, 2026-07-02)
Gemini is half right. `LIFT_BASE = modelH * 0.20` (line 1275) exists and is extraneous,
but **the PRIMARY culprit Gemini missed is `Z_GAP_EXAG = 8.0`** (line 1138) — plus
a 3.8mm gap **already baked into disc geometry** (Python line 496:
`z_disc_bot = z_coil_top + z_bottom_mm(3.8)`).

Total displayed gap now = 3.8 (baked) + LIFT_BASE (~14mm, since modelH≈69.8mm)
+ `lev.z × 8.0`. With physical gap 8.7mm as in screenshot:
3.8 + 14 + 69.6 ≈ **87 display-mm** — higher than entire coil assembly 60mm → exactly what user sees.
Note: `display_z_exaggeration: 2.0` in params.yaml only enlarges disc THICKNESS
(3→6mm), does NOT affect gap — Gemini's concern about this parameter is wrong.

### How to fix
Goal: displayed gap = `lev.z × zex` with same exaggeration factor `zex=2.0` as disc thickness
(consistent: all z-dimensions of disc are ×2). That is, 4.1mm @5A → 8.2 display-mm.

1. **Python** (line ~496): remove baked gap — build disc sitting directly on coil top:
   ```python
   z_disc_bot = z_coil_top    # gap added at RUNTIME via lev.z, not baked into geometry
   ```
   (keep key `z_bottom_mm` in params.yaml as-is, just no longer use it for geometry;
   or delete it entirely if nothing else uses it.)
2. **JS**: `Z_GAP_EXAG = 8.0` → **2.0** (line 1138) — and fix comment accordingly.
3. **JS**: remove `LIFT_BASE` (line 1275). `levLiftY()` (line 1277-1279) becomes:
   ```javascript
   function levLiftY() { return lev.z * Z_GAP_EXAG; }
   ```
4. **Update all places using LIFT_BASE for consistency** (forgetting will skew appearance):
   - line 1294: `flPts.push(x, gapBot, z, x, gapTop + LIFT_BASE*0.9, z)` → replace
     `LIFT_BASE*0.9` with a small model-based constant, e.g. `modelH*0.10` (decorative arc).
   - line 1368: `plateTopY = (bb.max.y-ctr.y) + LIFT_BASE + levGapEqMm(targetI)*Z_GAP_EXAG`
     → remove `LIFT_BASE`. (bb.max.y now = disc top sitting flush on coil, still correct meaning.)
   - line 1442: `particleTopY = gapTop + LIFT_BASE*0.9` → `gapTop + modelH*0.10`.
5. Camera framing (line 1369-1370) keep as-is, just verify with screenshot.

### Verify
- Open HTML headless (Playwright, see test template at end of file): at I=5A after disc
  settles, measure `plateM.mesh.position.y` − position shift from I=0 should be ≈ `4.1 × 2.0 = 8.2` world-units.
- Screenshot: disc hovers immediately above coil, gap looks ~1/7 model height, not
  floating mid-air like in image `z_achse_260701.png`.
- Gap telemetry still displays PHYSICAL number (`lev.z`, mm) — unchanged.

---

## Task 2 — B-field does not respond when I changes

### Verification (Fable, 2026-07-02)
Gemini is correct. Field lines are STATIC geometry baked from contour ψ=r·A_φ at I_ref
(line 1301-1352); `dashOffset = -(now/1000) * FIELD_LINE_FLOW_SPEED` (line 1953)
runs on wall clock, unrelated to `I_display`; opacity only follows slider
(`applyFieldLineOpacity`, line 1353-1355). No mechanism for I to affect appearance.

Physical note (keep as-is, do NOT rebake geometry per I): linear problem → field-line SHAPE
unchanging with I, only MAGNITUDE scales linearly. So static geometry is correct;
what needs fixing is the intensity cue (opacity + flow speed) should follow I.

### How to fix
1. In the loop (line 1952-1955), replace the field-line block with:
   ```javascript
   if (fieldLineGroup.visible) {
     const iFrac = Math.min(2.0, Math.abs(I_display) / ROM.I_ref);  // 0→0A, 1→5A, capped at 2
     flFlowPhase += wall_dt * FIELD_LINE_FLOW_SPEED * iFrac;        // accumulate, no jump when I changes
     for (const o of fieldLineMats) {
       o.mat.dashOffset = -flFlowPhase;
       o.mat.opacity = fieldLineOpacityPct * (0.15 + 0.85 * o.amp) * Math.min(1, iFrac);
     }
   }
   ```
   Declare `let flFlowPhase = 0;` next to `FIELD_LINE_FLOW_SPEED` (line 1361).
   Use accumulated phase (instead of `now × speed`) so dash speed does not snap when I changes.
2. `applyFieldLineOpacity()` (slider handler) keep as-is — but since loop now overwrites
   opacity each frame when visible, you can DELETE the call in slider handler or leave it
   (harmless, loop overwrites next frame).
3. Desired behavior: I=0 → field lines fade to 0 + stand still; I rises → more opaque
   (capped) + flow faster.

### Verify
- Headless: enable vizMode 'bfield', set slider I=0 → sample a few `fieldLineMats[i].mat.opacity`
  must be 0; set I=13 → opacity > 0 and `dashOffset` changes between frames faster than at I=5.
- Visual: drag slider I from 0 upward, field lines appear gradually and flow faster.

---

## Task 3 — Coils do not change color when heating

### Verification (Fable, 2026-07-02)
Gemini got the root cause right. `paintMesh()` line 1467-1471: `tnInner = (sim.T.inner − T_AMB_JS)
/ dT_inner_ss` where `dT_inner_ss = coilTss_inner(I_cur) − T_AMB_JS` depends on **instantaneous** I
(∝ I²). Consequence:
- Raise I → denominator jumps → tnorm collapses to ~0 → coil "cools" instantly despite heating.
- Sine scenario (as in screenshot): denominator oscillates continuously → color flickers with I,
  not real temperature.
- At steady state tnorm→1 for ANY I → 5A and 13A both "orange" identically — wrong physics.
- `tnIron` (line 1477) also divides by same dynamic denominator → error spreads to core/separator.

### How to fix
Switch to a fixed ABSOLUTE scale anchored to real IR data (session 1: inner coil
79°C @7.8A is hottest ever measured):
```javascript
// Coil color scale ABSOLUTE: T_amb → T_COIL_HOT. Does not depend on instantaneous I —
// color only changes when REAL TEMPERATURE changes (IR session 1: inner coil max 79°C @7.8A).
const T_COIL_HOT = 80.0;   // °C, coil color scale top
const tnInner = (sim.T.inner - T_AMB_JS) / (T_COIL_HOT - T_AMB_JS);
const tnOuter = (sim.T.outer - T_AMB_JS) / (T_COIL_HOT - T_AMB_JS);
const tnIron  = (sim.T.iron  - T_AMB_JS) / (T_COIL_HOT - T_AMB_JS) * 1.8;  // boost: core/sep only reach ~45°C
```
- Delete `dT_inner_ss`/`dT_outer_ss` and `I_cur = getI()` if no longer used (line 1467-1469).
- `writeRampCopper`/`writeRampMetal` already clamp tnorm to [0,1] — verify; if not,
  add clamp.
- Boost factor 1.8 for tnIron: actual core/separator only reach ~45°C @7.8A (absolute tnorm
  ~0.31) — multiply by 1.8 to shift color noticeably, match IR photo (coil glows, ring moderately warm).
  This is a visual decision; adjust in range 1.5–2.0 if screenshot doesn't match
  `docs/thermal_test.png`.
- HISTORICAL NOTE: CLAUDE.md session 2026-07-02 once switched absolute → relative because
  "color froze". Root cause then was 29–125°C scale TOO WIDE + iron node missing conduction
  (fixed via `G_iron_cond_W_per_K`). New 29–80°C scale much narrower so old bug won't recur —
  do not revert to 125°C scale.

### Verify
- Headless: set I=13A step, run ~5 sim-minutes: coil color must GRADUALLY transition from chocolate brown
  → orange as time passes (take 3 screenshots t=0/2min/5min to compare), NOT snap when slider drags.
- Drag slider I from 13 down to 5 while coil is hot: coil color must STAY THE SAME (heat hasn't dropped yet),
  only cool down slowly over time.
- Compare final screenshot to `docs/thermal_test.png`: coil brightest, core/separator moderately warm.

---

## Task 4 — Turn off bloom glare + dull light-absorbing materials

### Verification (Fable, 2026-07-02)
Gemini is right. Three sources of "glare":
1. `bloomPass.strength = I_display > 0.01 ? 0.42 : 0.0` (line 1959) — bloom nearly always on
   (default I=5A), makes highlights bloom bright.
2. `scene.environment = PMREM(RoomEnvironment)` (line 1184-1185) + `envMapIntensity: 0.8`
   on ALL meshes in `makeMesh()` (line 1234-1235) — studio reflections slide across surfaces
   when rotating camera → impression "everything is shiny metal".
3. Current metalness: baseM 0.68, coilM 0.20, plateM 0.75, woodM 0.02 (line 1248-1251).

### How to fix
1. **Turn off bloom entirely**: delete line 1959 (or set constant `bloomPass.strength = 0.0` at init and
   remove line in loop). Cleanest: delete entire `EffectComposer`/`RenderPass`/
   `UnrealBloomPass`/`composer.addPass` (line 1196-1199 + import line ~909-911) and replace
   `composer.render()` (line 1964) with `renderer.render(scene, camera)`; remember to fix
   `composer.setSize` in resize handler too (line 1971). If you want lower risk, keep
   composer but strength=0 permanently — pick full delete if confident in verification.
2. **Allow envMapIntensity per mesh** — add parameter to `makeMesh(sub, roughness,
   metalness, envInt=0.8)` (line 1227) then set:
   ```javascript
   const baseM  = makeMesh(buildSub(r => r===3||r===5), 0.60, 0.30, 0.25); // core+separator: dull metal/oxide
   const coilM  = makeMesh(buildSub(r => r===1||r===2), 0.80, 0.05, 0.15); // varnish+insulation: matte, light-absorbing
   const woodM  = makeMesh(buildSub(r => r===4),        0.90, 0.00, 0.05); // plywood
   const plateM = makeMesh(buildSub(r => r===0),        0.45, 0.65, 0.45); // aluminum disc: still real metal
   ```
   Reason for keeping plateM metallic: aluminum disc IS actually shiny metal — user complained only about
   "the rings" (coil/ring/frame). Just reduce envMapIntensity on disc slightly to soften it.
3. Keep `renderer.toneMapping = ACESFilmic` (line 1177) — needed for env map not to blow out white.
   If after reducing envMapIntensity scene gets dark, gently raise AmbientLight 0.5 → 0.65 (line 1373).

### Verify
- Headless: rotate camera through 4-5 angles (set `twinDebug.camera.position`), take screenshots —
  no white glint streaks sliding across coil/frame as angle changes; coil is dull brown.
- 0 JS errors in console (especially if you deleted composer — easy to miss a reference).
- Compare to `docs/real_model.png`: coil dark brown matte, only aluminum disc has metallic sheen.

---

## Execution order & general rules

1. Follow order Task 1→2→3→4 (Task 1 changes Python geometry → must regenerate HTML before
   verifying later tasks; Task 4 touches render pipeline so save for last, cleanest verification).
2. After EVERY task: `python build_twin_html_fem.py` → verify headless → move to next task.
   (Script auto-reads cached ROM/EM; if it re-runs EM solve taking minutes, that's normal.)
3. DO NOT hardcode new physical numbers into JS — physical numbers come from params.yaml via Python
   (locked rule in CLAUDE.md). Pure VISUAL constants (Z_GAP_EXAG, T_COIL_HOT,
   boost 1.8, roughness/metalness) may live in JS template with explanatory comments.
4. After all 4 tasks: update CLAUDE.md (add one item "[x] build_twin_html_fem.py — 4 render
   fixes 2026-07-0x" briefly) + section 3D Body Geometry in docs/QUICK_START_FOR_AGENTS.md
   (Z_GAP_EXAG 8.0→2.0, material table, coil color scale absolute 29–80°C).
5. Commit when user requests, including `outputs/digital_twin_fem.html` (this file IS committed,
   see .gitignore).

## Headless verification template (Playwright, used in prior sessions)

```python
# scratchpad/verify_twin.py — run: python scratchpad/verify_twin.py
import asyncio, pathlib
from playwright.async_api import async_playwright

HTML = pathlib.Path("outputs/digital_twin_fem.html").resolve().as_uri()

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width":1600,"height":1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(HTML)
        await pg.wait_for_timeout(3000)
        # example: read state via window.twinDebug / DOM
        gap = await pg.text_content("#tLevGap")
        y   = await pg.evaluate("window.twinDebug && twinDebug.camera.position.y")
        await pg.screenshot(path="scratchpad/twin_check.png")
        print("JS errors:", errs, "| gap:", gap, "| camY:", y)
        await b.close()

asyncio.run(main())
```
Common criterion for all tasks: **0 JS errors** + screenshot matches task Verify description.
