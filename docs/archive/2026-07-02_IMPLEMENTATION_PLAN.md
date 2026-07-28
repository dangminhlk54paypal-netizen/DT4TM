# Fix Plan for HTML Simulation Errors (DT4TM Project)

This document analyzes 4 display errors in the HTML simulation (file `build_twin_html_fem.py`) per user report and breaks them into tasks to delegate to smaller agents/models.

## Root-cause analysis and proposed solutions

### 1. Gap 8.7mm appears too high compared to model height

- **Root cause:** In the `levLiftY()` function (around line 1277), the code is adding an extra value `LIFT_BASE = modelH * 0.20` to the disc position. With model height around 50mm, `LIFT_BASE` creates an excess offset of up to ~10mm. Additionally, the `display_z_exaggeration` parameter in `params.yaml` may be doubling this distance.
- **Solution:**
  - Remove the `LIFT_BASE` variable (or set = 0) from the `levLiftY()` calculation and the Y-coordinate position of `plateM`.
  - Ensure physical Z coordinate maps 1:1 to Three.js Y, keeping only `lev.z` (and apply `Z_GAP_EXAG` exaggeration only if truly necessary, but should be off by default).

### 2. Magnetic field (Field B) stays static when current I changes

- **Root cause:** The current field-line visualization is purely a visual effect. At the end of the render function (around line 1950), the `dashOffset` variable is updated by real time `(now / 1000) * FIELD_LINE_FLOW_SPEED` but is completely independent of the actual current `I_display`. Therefore when I changes, the speed and intensity of the field lines remain unchanged.
- **Solution:**
  - Tie the movement speed `FIELD_LINE_FLOW_SPEED` or `opacity` of the `LineSegments` material to the `I_display` variable. For example: if `I_display == 0` then field line disappears, if `I` increases then opacity and flow speed increase proportionally.

### 3. Coil surface color does not change when temperature increases

- **Root cause:** The `paintMesh()` function (line 1461) calculates coil color through `tnInner = (sim.T.inner - T_AMB_JS) / dT_inner_ss`. However, `dT_inner_ss` depends on **the current current** (`coilTss_inner(I_cur)`). That means when the user slightly increases current I, `dT_inner_ss` jumps immediately while `sim.T.inner` is still cool (since coil temperature takes many minutes to rise). As a result `tnInner` drops to 0, making the coil appear "cool" immediately even though it is starting to heat up.
- **Solution:**
  - Change the coil temperature normalization from a relative reference frame (based on I) to an absolute reference frame (e.g. range from `20°C` to `60°C`). This way when `sim.T.inner` gradually increases over time, `tnInner` will gradually increase and the coil will turn red accurately regardless of what I level the user is adjusting.

### 4. "Bloom/Glare" effect creates false metallic illusion

- **Root cause:**
  - Code is using the `UnrealBloomPass` effect in Three.js (around line 1957 with `bloomPass.strength = I_display > 0.01 ? 0.42 : 0.0;`) causing the entire object to glow when current flows.
  - The `metalness` and `roughness` variables of the material (in `makeMesh()`) are making the coil and frame reflect the environment too much, unlike real insulating material or varnish that absorbs light.
- **Solution:**
  - Disable `BloomPass` entirely or set `bloomPass.strength = 0`.
  - Adjust the coil material (increase `roughness`, lower `metalness` much lower, e.g. `metalness = 0.05`, `roughness = 0.8`) and reduce `envMapIntensity` strength so the surface becomes matte and absorbs light more like reality.

---

## Task assignment (Task Breakdown for smaller models)

To implement, you can delegate the following tasks to smaller models:

1. **Task 1 (Geometry & Rendering): Fix gap display error (Error 1)**
   - **File to edit:** `build_twin_html_fem.py`
   - **Description:** Find the `levLiftY()` function and the `LIFT_BASE` declaration. Fix `LIFT_BASE = 0.0` or remove it from the `levLiftY()` calculation and correct the `gapBot`, `gapTop` values of the `flPts` array accordingly so the flying disc displays close to the actual physical distance.

2. **Task 2 (Visual Effects): Make B-field respond to current I (Error 2)**
   - **File to edit:** `build_twin_html_fem.py`
   - **Description:** In the animation loop (animate function / render section), find the `dashOffset` calculation code. Modify it so the `FIELD_LINE_FLOW_SPEED` flow speed or `opacity` of the `fieldLineMats` material is proportional to the current `I_display` (larger current flows faster / darker).

3. **Task 3 (Logic & Colors): Fix temperature scale for coil (Error 3)**
   - **File to edit:** `build_twin_html_fem.py`
   - **Description:** In the `paintMesh(M)` function, change how `tnInner` and `tnOuter` are calculated. Instead of dividing by `dT_inner_ss` (which suddenly changes with `I_cur`), use a fixed absolute constant like `MAX_COIL_TEMP = 50.0` (degrees C) as the denominator: `tnInner = (sim.T.inner - T_AMB_JS) / (MAX_COIL_TEMP - T_AMB_JS)`. This helps the coil change color gradually as temperature truly rises.

4. **Task 4 (Materials & Post-processing): Disable glare and adjust materials (Error 4)**
   - **File to edit:** `build_twin_html_fem.py`
   - **Description:** Find and delete/disable the line assigning `bloomPass.strength = 0.42`. At the same time, find where `coilM` and `baseM` are initialized using the `makeMesh()` function, lower `metalness` very low (around 0.05) and increase `roughness` (up to around 0.8 - 0.9) to remove the mirror-like property of the metal.
