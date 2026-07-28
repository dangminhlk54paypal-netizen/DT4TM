# docs/archive — completed plans & bug registers

**Historical record only.** Every file here describes work that has been finished and
shipped. They are kept because they carry the *evidence and reasoning* behind decisions
(measurements, root-cause chains, rejected alternatives) that the summaries elsewhere
don't have room for.

⚠️ **These files are NOT the source of truth for current behaviour.** They deliberately
preserve numbers as they stood on their own date, including values that later
measurements superseded (levitation gaps, iron-ring position/material, hA calibration
rounds). For what is true *now*, read in this order:

1. `params.yaml` — the SSOT for every physical constant
2. `CLAUDE.md` — current state, open questions, next steps
3. `docs/CHANGELOG.md` — session-by-session narrative of how it got there
4. `docs/physics.md` — the formulation

Files are named `YYYY-MM-DD_TOPIC.md`, dated by when the work was done, so a plain
directory listing reads chronologically.

| File | What it was | Outcome |
|---|---|---|
| `2026-06-23_3D_MODEL_UPDATE_PLAN.md` | Separator-ring / coil geometry update notes | Superseded by the 2026-07-10 ruler re-measurement; its open "is the core ferromagnetic?" item was closed by the 2026-07-10 magnet test (both core **and** ring are iron) |
| `2026-07-02_HTML_TWIN_FIX_PLAN.md` | Work order for 4 display bugs in `digital_twin_fem.html` | Done |
| `2026-07-02_IMPLEMENTATION_PLAN.md` | Earlier draft of the same 4-bug analysis (was `implemetation_Plan.md`, misspelled) | Superseded by the file above |
| `2026-07-02_PLAN_SIM_FEEDBACK.md` | 3D-simulation upgrades derived from real-rig feedback | Done |
| `2026-07-04_AUDIT_FIX_PLAN.md` | Repo-wide audit; H/M/L findings + OQ open questions | Done — remaining open items were promoted into `CLAUDE.md` |
| `2026-07-11_BUG_REGISTER.md` | Follow-up audit after the 2026-07-10 iron/geometry update | All findings resolved (notably B1: `P_plate` wrongly included in the shared-air-node hA balance) |
| `2026-07-28_BUG_REGISTER.md` | Three user-reported HTML-twin defect clusters (cooldown far too fast, levitation-gap clamp, no shimmer) | L1/L2, T1–T4, V1/V2 fixed. **T5 (shared air node) deliberately left unfit** — needs real cooldown data, see `CLAUDE.md` NEXT |
| `2026-07-28_PROMPT_WP_COOL_LEV.md` | Implementation work order for the register above | Done — shipped as WP-LEV / WP-COOL / WP-SHIMMER |
| `2026-07-28_PYVISTA_TWIN_PLAN.md` | Plan for the PyVista/VTK desktop 3D twin | Done — shipped as `digital_twin_pyvista.py` (+ `twin_core.py` SSOT, `xval_twin.py`) |
