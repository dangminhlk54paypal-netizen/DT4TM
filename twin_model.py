"""twin_model.py — the HEAVY half of the twin split (config/em_solver/rom/
build_twin_html_fem-dependent code). Companion to twin_core.py (integrators
only, numpy+stdlib). See docs/PYVISTA_TWIN_PLAN_2026-07-28.md for the overall
architecture: build_twin_html_fem.py stays the SSOT for per-plate
*coefficients* (lumped_physics/lev_params/solve_plate_variant — reused here,
NOT reimplemented); twin_core.py is the SSOT for the time *integrators*;
twin_model.py is the bridge that turns a live (cfg, em, rom) into twin_core's
frozen coefficient objects, plus the plate-selection bookkeeping that used to
live inside digital_twin.py's run_live() closure.

Heavy imports (config, rom, em_solver, build_twin_html_fem) are deliberately
function-local (matching digital_twin.py's existing style) so `import
twin_model` alone stays cheap — the cost is paid only by whichever function
actually needs it.
"""
from __future__ import annotations

from dataclasses import dataclass

from twin_core import LevCoeffs, LumpedCoeffs, RomCoeffs


# ---------------------------------------------------------------------------
# resolve_active_plate — digital_twin.py:141-173 (run_live()'s plate-name-
# resolution closure), extracted so both the matplotlib twin and any future
# consumer share the same honest-fallback logic instead of re-deriving it.
# ---------------------------------------------------------------------------
@dataclass
class ActivePlate:
    name: str                    # display name (plate_library's, or a synthesized honest label)
    spec: dict | None            # the matching plate_library entry, or None if synthesized
    plate_names: list[str]       # full display list (fallback label prepended when synthesized)
    is_synthetic: bool           # True if no plate_library entry matched the active plate by value


def resolve_active_plate(cfg) -> ActivePlate:
    """Find the plate_library entry matching the ACTIVE plate (cfg.geometry /
    cfg.plate) by VALUE — radius_mm + material — never by re-deriving/string-
    matching a name. That was the original H4 bug (CLAUDE.md / docs/
    AUDIT_FIX_PLAN_2026-07-04.md): a RadioButtons entry could show as
    pre-selected while a DIFFERENT radius was actually running, and because
    the label already "matched", clicking it was a permanent no-op. If no
    entry matches, synthesize an honest, distinct label instead of
    mislabeling an unrelated plate_library entry (verbatim port of
    digital_twin.py:141-173)."""
    plate_lib = cfg.raw.get("plate_library", [])
    plate_names = [s["name"] for s in plate_lib]

    default_radius_mm = cfg.geometry.plate_radius_m * 1e3
    default_material = cfg.plate.get("name", "aluminium")
    default_spec = next(
        (s for s in plate_lib
         if abs(s["radius_mm"] - default_radius_mm) < 1e-6
         and s.get("material", "aluminium") == default_material),
        None,
    )
    if default_spec is not None:
        return ActivePlate(name=default_spec["name"], spec=default_spec,
                            plate_names=plate_names, is_synthetic=False)

    default_name = (f"Active (Ø{2 * default_radius_mm:.0f}mm "
                     f"{default_material}, not in plate_library)")
    plate_names = [default_name] + plate_names
    print(f"[twin_model] WARNING: active plate (radius_mm={default_radius_mm:.1f}, "
          f"material={default_material}) has no matching plate_library entry -- "
          f"showing it as '{default_name}' instead of mislabeling an unrelated entry.")
    return ActivePlate(name=default_name, spec=None,
                        plate_names=plate_names, is_synthetic=True)


# ---------------------------------------------------------------------------
# _build_rom_for_plate — verbatim port of digital_twin.py:92-123
# ---------------------------------------------------------------------------
def _build_rom_for_plate(cfg_base, spec: dict, em_base=None, verbose: bool = True):
    """Clone config, override plate, run EM+thermal -> ThermalROM."""
    import copy

    from config import Geometry
    from rom import ThermalROM

    cfg = copy.deepcopy(cfg_base)
    mat_name = spec["material"]
    mat = cfg_base.raw["material_props"][mat_name]
    pm = cfg.raw["plate_material"]
    pm["name"] = mat_name
    pm["radius_mm"] = float(spec["radius_mm"])
    pm["thickness_mm"] = float(spec.get("thickness_mm", pm["thickness_mm"]))
    for k, v in mat.items():
        pm[k] = float(v)
    cfg.geometry = Geometry(
        plate_radius_m=pm["radius_mm"] * 1e-3,
        plate_thickness_m=pm["thickness_mm"] * 1e-3,
        plate_z_bottom_m=cfg_base.geometry.plate_z_bottom_m,
    )

    em = None
    if em_base is not None:
        from em_solver import compute_losses
        if verbose:
            print(f"  [EM] Solving for {spec['name']}... ", end="", flush=True)
        em = compute_losses(cfg)
        if verbose:
            print(f"P={em['P_plate_W'] * 1e3:.1f} mW")

    rom = ThermalROM().build(cfg, em_losses=em, verbose=verbose)
    return rom


# ---------------------------------------------------------------------------
# PlateCache — digital_twin.py:176's `_rom_cache` dict, promoted to a class so
# a matplotlib/PyVista twin can swap discs without re-solving an
# already-seen radius/material combination.
# ---------------------------------------------------------------------------
class PlateCache:
    def __init__(self, cfg_base, default_name: str, default_rom, em_base=None):
        self._cfg_base = cfg_base
        self._em_base = em_base
        self._cache: dict[str, object] = {default_name: default_rom}

    def __contains__(self, name: str) -> bool:
        return name in self._cache

    def get(self, name: str):
        return self._cache.get(name)

    def get_or_build(self, name: str, plate_lib: list[dict], verbose: bool = True):
        """Return the cached ROM for `name`, building (and caching) it from
        `plate_lib` first if this is the first time it's been selected."""
        if name in self._cache:
            return self._cache[name]
        spec = next((s for s in plate_lib if s["name"] == name), None)
        if spec is None:
            raise KeyError(f"no plate_library entry named {name!r}")
        rom = _build_rom_for_plate(self._cfg_base, spec, em_base=self._em_base, verbose=verbose)
        self._cache[name] = rom
        return rom


# ---------------------------------------------------------------------------
# i_max_for — digital_twin.py:236
# ---------------------------------------------------------------------------
def i_max_for(cfg) -> float:
    """I_MAX covers the rig's real max current (variac dial 270 -> 7.78A
    measured 2026-07-02, docs/rig_photo.jpg), with headroom over 5.0A."""
    ps = cfg.power_supply
    return max(5.0, cfg.dial_to_current_A(ps["dial_max"])) if ps else 5.0


# ---------------------------------------------------------------------------
# coeffs_from_live — bridges a live (cfg, em_losses, ThermalROM) triple into
# twin_core's frozen coefficient objects, reusing build_twin_html_fem's OWN
# lumped_physics()/lev_params()/compute_eddy_fraction() (NOT reimplemented
# here — see CLAUDE.md token-discipline / the WP-CORE prompt: "do NOT move
# lumped_physics/lev_params out of build_twin_html_fem.py").
# ---------------------------------------------------------------------------
def coeffs_from_live(cfg, em: dict | None, rom) -> tuple[RomCoeffs, LumpedCoeffs, LevCoeffs]:
    """rom: a live rom.py `ThermalROM` instance already built for `cfg`/`em`.

    em=None (digital_twin.py's `--no-em` fast-startup path, where `rom` itself
    was also built with em_losses=None -> a placeholder heat source, see
    rom.py's build() docstring): compute_eddy_fraction/lumped_physics both
    need real loss numbers (P_plate_W/P_iron_W) that simply don't exist yet,
    so this falls back to the single-β model (f_eddy=1/f_air=0, RomCoeffs'
    own default) and a zero-iron-loss placeholder for lumped_physics (which
    only ever reads em["P_iron_W"] -- P_inner/P_outer come from I²R via cfg
    alone). lev_params(cfg) never needed em to begin with."""
    from build_twin_html_fem import compute_eddy_fraction, lev_params, lumped_physics

    if em is None:
        rom_coeffs = RomCoeffs.from_source(rom)   # f_eddy=1.0/f_air=0.0 default
        lumped_coeffs = LumpedCoeffs.from_source(lumped_physics(cfg, {"P_iron_W": 0.0}))
    else:
        f_eddy = compute_eddy_fraction(cfg, em, rom)
        rom_coeffs = RomCoeffs.from_source(rom, f_eddy=f_eddy, f_air=1.0 - f_eddy)
        lumped_coeffs = LumpedCoeffs.from_source(lumped_physics(cfg, em))
    lev_coeffs = LevCoeffs.from_source(lev_params(cfg))
    return rom_coeffs, lumped_coeffs, lev_coeffs


# ---------------------------------------------------------------------------
# build_plate_variant — thin wrapper around build_twin_html_fem.solve_plate_variant
# ---------------------------------------------------------------------------
@dataclass
class PlateVariant:
    """Everything a matplotlib/PyVista twin needs after swapping to a
    different disc radius: mesh arrays for re-rendering + this radius's own
    twin_core coefficients. Solved FROM SCRATCH per radius (never scaled) —
    a wider/narrower disc genuinely reshapes the EM field, see
    solve_plate_variant's own docstring."""
    radius_mm: float
    V: "object"
    dTe: "object"
    dTa: "object"
    Je: "object"
    rom: RomCoeffs
    lev: LevCoeffs
    P_plate_W: float
    field_lines: object


def build_plate_variant(base_cfg, radius_mm: float, z_disc_bot_mm: float) -> PlateVariant:
    """Reuses build_twin_html_fem.solve_plate_variant's EM+ROM+mesh solve
    verbatim (do NOT reimplement it here) and converts its "rom"/"lev" dicts
    into twin_core's frozen coefficient objects."""
    from build_twin_html_fem import solve_plate_variant

    data = solve_plate_variant(base_cfg, radius_mm, z_disc_bot_mm)
    # data["rom"] already carries "f_eddy"/"f_air" (build_twin_html_fem.py
    # :731-732), so RomCoeffs.from_source's dict path needs no override here.
    rom_coeffs = RomCoeffs.from_source(data["rom"])
    lev_coeffs = LevCoeffs.from_source(data["lev"])
    return PlateVariant(radius_mm=radius_mm, V=data["V"], dTe=data["dTe"], dTa=data["dTa"],
                         Je=data["Je"], rom=rom_coeffs, lev=lev_coeffs,
                         P_plate_W=data["P_plate_W"], field_lines=data["field_lines"])


if __name__ == "__main__":
    from config import load_config

    cfg = load_config()
    active = resolve_active_plate(cfg)
    print(f"[twin_model] active plate: {active.name}  "
          f"(synthetic={active.is_synthetic}, {len(active.plate_names)} plate_library entries)")
    print(f"[twin_model] I_MAX = {i_max_for(cfg):.2f} A")
