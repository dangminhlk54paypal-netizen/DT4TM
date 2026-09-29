"""weather_api.py — live ambient temperature (Google Weather API) for real measurements.

The model's DEFAULT ambient is the constant params.yaml thermal_bc.T_ambient_degC
(20 °C, professor's "keep it simple" rule). During a REAL measurement on the rig the
lab temperature is not 20 °C, so the measurement tools (data_io.py --mode log,
digital_twin_live.py on a real serial port) call ambient_now() once at start and
then every weather_api.log_refresh_s, write the value into the log, and seed the
twin with it — the model then computes the rise ABOVE the real ambient.

Rules (params.yaml weather_api block):
  - The key is read ONLY from local/.env.local (gitignored) or the environment —
    load_key() is the single loader, also used by build_twin_html_fem.py.
  - key_active() is False after weather_api.key_valid_until (inclusive last day);
    from then on ambient_now() never calls the API and returns the fallback.
  - Any failure (no key, expired, offline, bad response) -> fallback, never an
    exception: a measurement must not stop because the weather lookup failed.
  - The key never appears in a return value, a log line, or an error message.

stdlib only (urllib), so it runs without numpy/scipy.
    python weather_api.py      # print the ambient the tools would use right now
"""
from __future__ import annotations

import datetime
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(HERE, "local", ".env.local")
PLACEHOLDER = "YOUR_KEY_HERE"
API_URL = "https://weather.googleapis.com/v1/currentConditions:lookup"
# Darmstadt (TEMF lab) — same point the HTML twin queries.
DEFAULT_LAT, DEFAULT_LON = 49.8728, 8.6512


def load_key() -> str:
    """GOOGLE_WEATHER_API_KEY from local/.env.local, else the environment, else
    the placeholder. The only place in the repo that reads the real key."""
    if os.path.isfile(ENV_FILE):
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("GOOGLE_WEATHER_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("GOOGLE_WEATHER_API_KEY", PLACEHOLDER)


def _block(raw: dict | None) -> dict:
    if raw is None:   # parse params.yaml ourselves only if no config was passed
        import yaml
        with open(os.path.join(HERE, "params.yaml"), encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    return raw.get("weather_api", {}) or {}


def key_valid_until(raw: dict | None = None) -> datetime.date:
    """Inclusive last day the key may be used. Missing -> treated as expired."""
    val = str(_block(raw).get("key_valid_until", ""))
    m = re.match(r"\d{4}-\d{2}-\d{2}$", val)
    return datetime.date.fromisoformat(val) if m else datetime.date.min


def key_active(raw: dict | None = None, today: datetime.date | None = None) -> bool:
    key = load_key()
    today = today or datetime.date.today()
    return bool(key) and key != PLACEHOLDER and today <= key_valid_until(raw)


def ambient_now(fallback_C: float, raw: dict | None = None,
                timeout_s: float = 4.0) -> dict:
    """Current outdoor temperature at the lab, or the fallback.

    Returns {"T_amb_degC": float, "source": "google_weather" | "fallback",
             "fetched_at": ISO local time, "note": short reason (fallback only)}.
    """
    now = datetime.datetime.now().isoformat(timespec="seconds")
    fb = {"T_amb_degC": float(fallback_C), "source": "fallback", "fetched_at": now}
    blk = _block(raw)
    if not key_active(raw):
        key = load_key()
        fb["note"] = ("no key in local/.env.local" if not key or key == PLACEHOLDER
                      else f"key expired (valid until {key_valid_until(raw)})")
        return fb
    query = urllib.parse.urlencode({
        "key": load_key(),
        "location.latitude": float(blk.get("lat", DEFAULT_LAT)),
        "location.longitude": float(blk.get("lon", DEFAULT_LON)),
        "unitsSystem": "METRIC",
    })
    try:
        with urllib.request.urlopen(f"{API_URL}?{query}", timeout=timeout_s) as r:
            data = json.load(r)
        t = data["temperature"]["degrees"]
        if not isinstance(t, (int, float)) or t != t:
            raise ValueError("malformed response")
    except urllib.error.HTTPError as e:     # str(e) carries no URL -> no key leak
        fb["note"] = f"HTTP {e.code}"
        return fb
    except Exception as e:                  # offline, timeout, bad JSON ...
        fb["note"] = type(e).__name__
        return fb
    return {"T_amb_degC": float(t), "source": "google_weather", "fetched_at": now}


def describe(amb: dict) -> str:
    """One-line human summary, e.g. for console/plot titles."""
    s = f"T_amb={amb['T_amb_degC']:.1f}°C ({amb['source']} @ {amb['fetched_at']}"
    return s + (f", {amb['note']})" if amb.get("note") else ")")


if __name__ == "__main__":
    import yaml
    with open(os.path.join(HERE, "params.yaml"), encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    fallback = float(raw["thermal_bc"]["T_ambient_degC"])
    print(f"[weather] key valid until {key_valid_until(raw)}  active={key_active(raw)}")
    print("[weather] " + describe(ambient_now(fallback, raw)))
