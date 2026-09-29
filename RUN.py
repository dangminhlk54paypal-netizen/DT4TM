"""RUN.py -- one-click launcher for the thermal digital twin (HTML view).

Double-click RUN.command (macOS) or run `python RUN.py` from anywhere. It:
  1. re-bakes the HTML if it is missing or older than params.yaml / any
     physics module (FEM -> ROM -> HTML, ~2 s),
  2. opens it in the default browser.

Live weather (Google Weather API): up to and including
params.yaml `weather_api.key_valid_until`, and only if local/.env.local holds
a key, RUN.py builds outputs/digital_twin_fem_live.html (gitignored) with the
real key baked in. After that date it DELETES that live file and opens the
tracked outputs/digital_twin_fem.html, which only ever holds the placeholder.

Flags:
  --rebuild   always re-bake, even if the HTML looks up to date
  --no-build  never re-bake, just open the existing HTML

Uses the repo's .venv interpreter for the build (numpy/scipy live there), so
it also works when launched with a system Python that lacks them.
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
HTML_PUBLIC = HERE / "outputs" / "digital_twin_fem.html"      # tracked, placeholder key only
HTML_LIVE = HERE / "outputs" / "digital_twin_fem_live.html"   # gitignored, real key
BUILDER = HERE / "build_twin_html_fem.py"
ENV_FILE = HERE / "local" / ".env.local"
# Anything that changes the baked numbers or the page itself.
SOURCES = ["params.yaml", "config.py", "em_solver.py", "thermal_solver.py",
           "rom.py", "twin_core.py", "twin_model.py", "build_twin_html_fem.py"]


def _python() -> str:
    """The .venv interpreter if present, else whatever is running this file."""
    venv = HERE / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(venv) if venv.exists() else sys.executable


def _key_valid_until() -> datetime.date:
    """params.yaml weather_api.key_valid_until, parsed without PyYAML so this
    file also runs under a bare system Python. Missing -> treated as expired."""
    text = (HERE / "params.yaml").read_text(encoding="utf-8")
    m = re.search(r'key_valid_until:\s*"?(\d{4}-\d{2}-\d{2})', text)
    return datetime.date.fromisoformat(m.group(1)) if m else datetime.date.min


def _has_real_key() -> bool:
    if not ENV_FILE.exists():
        return False
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("GOOGLE_WEATHER_API_KEY="):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            return bool(val) and val != "YOUR_KEY_HERE"
    return False


def _stale(html: Path) -> bool:
    if not html.exists():
        return True
    built = html.stat().st_mtime
    return any((HERE / s).exists() and (HERE / s).stat().st_mtime > built
               for s in SOURCES)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--no-build", action="store_true")
    args = ap.parse_args()

    valid_until = _key_valid_until()
    key_active = datetime.date.today() <= valid_until and _has_real_key()

    if not key_active and HTML_LIVE.exists():
        # The "close" step: past the cutoff, no file with the real key may remain.
        HTML_LIVE.unlink()
        print(f"[RUN] weather key expired (valid until {valid_until}) -- "
              f"deleted {HTML_LIVE.name}")

    if key_active:
        html, extra = HTML_LIVE, ["--bake-key", "--out", HTML_LIVE.name]
        print(f"[RUN] live weather ON (key valid until {valid_until})")
    else:
        html, extra = HTML_PUBLIC, []
        print("[RUN] live weather OFF -- constant ambient temperature")

    if not args.no_build and (args.rebuild or _stale(html)):
        print(f"[RUN] building {html.name} (FEM -> ROM -> HTML) ...")
        rc = subprocess.call([_python(), str(BUILDER), *extra], cwd=HERE)
        if rc != 0:
            print(f"[RUN] build FAILED (exit {rc}) -- see the messages above.")
            return rc
    elif not html.exists():
        print(f"[RUN] {html} does not exist; run without --no-build first.")
        return 1
    else:
        print("[RUN] HTML is up to date, skipping build.")

    print(f"[RUN] opening {html}")
    print("[RUN] note: the 3D view loads three.js from the internet on first open.")
    webbrowser.open(html.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
