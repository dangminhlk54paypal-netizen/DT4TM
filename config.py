"""Reads config/params.yaml, normalizes units (mm -> m) and provides handy accessors."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import math
import re
import yaml

_NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def _coerce(obj):
    """PyYAML treats '3.4e7' as string (missing sign in exponent). Coerce number-like strings -> float."""
    if isinstance(obj, dict):
        return {k: _coerce(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce(v) for v in obj]
    if isinstance(obj, str) and _NUM.match(obj.strip()):
        return float(obj)
    return obj

ROOT = Path(__file__).resolve().parent
DEFAULT_PARAMS = ROOT / "params.yaml"
MU0 = 4e-7 * math.pi


@dataclass
class Geometry:
    plate_radius_m: float
    plate_thickness_m: float
    plate_z_bottom_m: float


@dataclass
class Config:
    raw: dict
    geometry: Geometry

    # ---- excitation ----
    @property
    def I(self):       return float(self.raw["excitation"]["current_A"])
    @property
    def I_ref(self):   return float(self.raw["excitation"]["current_ref_A"])
    @property
    def freq(self):    return float(self.raw["excitation"]["frequency_Hz"])
    @property
    def omega(self):   return 2 * math.pi * self.freq

    # ---- thermal placeholder (used when EM is NOT available); EM will replace with real losses ----
    @property
    def power_ref_W(self):
        return float(self.raw["excitation"].get("power_ref_W", 5.0))
    @property
    def total_power_W(self):
        return self.power_ref_W * (self.I / self.I_ref) ** 2

    # ---- raw groups ----
    @property
    def plate(self):   return self.raw["plate_material"]
    @property
    def coils(self):   return self.raw["coils"]
    @property
    def iron(self):    return self.raw.get("iron_core", {"enabled": False})
    @property
    def em(self):      return self.raw["em_domain"]
    @property
    def bc(self):      return self.raw["thermal_bc"]
    @property
    def mesh(self):    return self.raw["mesh"]
    @property
    def power_supply(self): return self.raw.get("power_supply", {})

    def dial_to_current_A(self, dial: float) -> float:
        """Piecewise-linear interpolation over power_supply.dial_to_current_A anchors."""
        anchors = self.power_supply["dial_to_current_A"]
        dials = [a["dial"] for a in anchors]
        currents = [a["I"] for a in anchors]
        return float(_interp_clamped(dial, dials, currents))


def _interp_clamped(x, xs, ys):
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1 = xs[i - 1], xs[i]
            y0, y1 = ys[i - 1], ys[i]
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return ys[-1]


def load_config(path=DEFAULT_PARAMS) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        raw = _coerce(yaml.safe_load(f))
    p = raw["plate_material"]
    geom = Geometry(
        plate_radius_m=p["radius_mm"] * 1e-3,
        plate_thickness_m=p["thickness_mm"] * 1e-3,
        plate_z_bottom_m=p["z_bottom_mm"] * 1e-3,
    )
    return Config(raw=raw, geometry=geom)


if __name__ == "__main__":
    c = load_config()
    print(f"Aluminum plate: R={c.geometry.plate_radius_m*1e3:.0f}mm, thick "
          f"{c.geometry.plate_thickness_m*1e3:.1f}mm, σ={c.plate['sigma_S_per_m']:.2e}")
    print(f"Inner/outer coils: {c.coils['inner']['turns']}/{c.coils['outer']['turns']} turns")
    print(f"Iron core: enabled={c.iron['enabled']}, μ_r={c.iron.get('mu_r')}")
    print(f"î={c.I}A, f={c.freq}Hz, ω={c.omega:.1f} rad/s")
    if c.power_supply:
        print(f"Power supply: {c.power_supply['name']}")
        for d in (0, 100, 220, 250, 270):
            print(f"  dial {d:>3} -> {c.dial_to_current_A(d):.2f} A")
