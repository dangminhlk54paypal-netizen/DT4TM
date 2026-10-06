"""RUN.py -- one-click launcher for the thermal digital twin (HTML view).

Double-click RUN.command (macOS) or run `python RUN.py` from anywhere. It:
  1. re-bakes the HTML if it is missing or older than params.yaml / any
     physics module (FEM -> ROM -> HTML, ~50 s, mostly the levitation z_eq
     root-finds for the 4 disc radii),
  2. prints timing in the terminal: the offline build (per stage, or the last
     build's numbers if it was skipped) and the page load up to the first
     simulation step (measured in headless Chromium, fresh cache),
  3. opens it in the default browser.

Live weather (Google Weather API): up to and including
params.yaml `weather_api.key_valid_until`, and only if local/.env.local holds
a key, RUN.py builds outputs/digital_twin_fem_live.html (gitignored) with the
real key baked in. After that date it DELETES that live file and opens the
tracked outputs/digital_twin_fem.html, which only ever holds the placeholder.

Flags:
  --rebuild   always re-bake, even if the HTML looks up to date
  --no-build  never re-bake, just open the existing HTML
  --no-timing skip the headless page-load measurement (saves a few seconds)
  --sensor    drive the twin with the CURRENT MEASURED by the Arduino: opens the
              page in Chrome (Web Serial; Safari has none) in Sensor mode, which
              connects to the Arduino by itself (first time: one click on
              "Connect Arduino"). Keep the Variac at 0 for the first ~10 s -- the
              zero-current offset is measured then.

Uses the repo's .venv interpreter for the build (numpy/scipy live there), so
it also works when launched with a system Python that lacks them.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
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


def _print_last_build(html: Path) -> None:
    """Offline timing of the build that produced `html` (written by the builder)."""
    f = html.parent / "build_timing.json"
    try:
        t = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("[TIME] offline computation: no timing recorded yet (use --rebuild)")
        return
    if t.get("html") != html.name:
        print("[TIME] offline computation: last timing is for another HTML (use --rebuild)")
        return
    top = max(t["stages"], key=lambda st: st[1])
    print(f"[TIME] offline computation (last build {t['built_at']}): {t['total_s']:.1f} s "
          f"-- largest stage: {top[0]} {top[1]:.1f} s")


# (label, start mark, end mark) -- marks are ms since navigation start, set by
# the page's JS (window.__twinTiming) plus the browser's own domInteractive.
LOAD_STAGES = [
    ("read + parse HTML (baked data incl.)", None, "dom"),
    ("download + import three.js (CDN)", "dom", "three_loaded"),
    ("ambient T (Google Weather call / 20 °C)", "three_loaded", "ambient_ready"),
    ("decode baked FEM data", "ambient_ready", "data_decoded"),
    ("build 3D scene + UI", "data_decoded", "scene_built"),
    ("first simulation step + render", "scene_built", "first_step"),
]


def _measure_load(html: Path) -> int:
    """Runs under the .venv interpreter (Playwright lives there): open the page
    headless with a fresh cache, wait for the first simulation step, print stages."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[TIME] page load: skipped (playwright not installed in this Python)")
        return 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(html.as_uri())
            page.wait_for_function("window.__twinTiming && window.__twinTiming.first_step",
                                   timeout=60_000)
            t = page.evaluate("({...window.__twinTiming, dom: "
                              "performance.getEntriesByType('navigation')[0].domInteractive})")
            browser.close()
    except Exception as e:   # offline CDN, missing browser binary, ...
        print(f"[TIME] page load: measurement failed ({type(e).__name__}: {str(e).splitlines()[0]})")
        return 0
    print("[TIME] page load until ready to compute (headless Chromium, fresh cache):")
    for label, a, b in LOAD_STAGES:
        ms = t[b] - (t[a] if a else 0.0)
        print(f"[TIME]   {label:44s} {ms / 1000:7.2f} s")
    print(f"[TIME]   {'TOTAL (navigation -> first step)':44s} {t['first_step'] / 1000:7.2f} s")
    return 0


def _serial_ports_busy() -> list[str]:
    """Arduino-looking serial ports another program holds (e.g. the Arduino IDE's
    Serial Monitor, or digital_twin_live.py) -- the browser could not open them."""
    import glob
    busy = []
    for port in glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/cu.usbserial*"):
        try:
            out = subprocess.run(["lsof", "-t", port], capture_output=True, text=True).stdout
        except OSError:
            return []
        if out.strip():
            busy.append(port)
    return busy


def _open_in_chrome(url: str) -> bool:
    """Web Serial exists only in Chromium browsers -> prefer Google Chrome."""
    if sys.platform == "darwin":
        return subprocess.call(["open", "-a", "Google Chrome", url]) == 0
    try:
        webbrowser.get("chrome").open(url)
        return True
    except webbrowser.Error:
        return False


def _stale(html: Path) -> bool:
    if not html.exists():
        return True
    built = html.stat().st_mtime
    return any((HERE / s).exists() and (HERE / s).stat().st_mtime > built
               for s in SOURCES)


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)   # keep [RUN]/[TIME] lines in order with the build's
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--no-timing", action="store_true")
    ap.add_argument("--sensor", action="store_true")
    ap.add_argument("--measure-load", metavar="HTML", help=argparse.SUPPRESS)  # internal
    args = ap.parse_args()
    if args.measure_load:
        return _measure_load(Path(args.measure_load).resolve())

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
        t0 = time.perf_counter()
        rc = subprocess.call([_python(), str(BUILDER), *extra], cwd=HERE)
        if rc != 0:
            print(f"[RUN] build FAILED (exit {rc}) -- see the messages above.")
            return rc
        print(f"[TIME] offline build wall time incl. Python start-up: "
              f"{time.perf_counter() - t0:.1f} s")
    elif not html.exists():
        print(f"[RUN] {html} does not exist; run without --no-build first.")
        return 1
    else:
        print("[RUN] HTML is up to date, skipping build.")
        _print_last_build(html)

    if not args.no_timing:
        subprocess.call([_python(), str(Path(__file__).resolve()), "--measure-load", str(html)],
                        cwd=HERE)

    print(f"[RUN] opening {html}")
    print("[RUN] note: the 3D view loads three.js from the internet on first open.")
    if not args.sensor:
        webbrowser.open(html.as_uri())
        return 0

    import glob
    if not glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/cu.usbserial*") and sys.platform == "darwin":
        print("[RUN] sensor: no Arduino on USB yet -- plug it in (data cable); the page "
              "connects by itself when it appears")
    for port in _serial_ports_busy():
        print(f"[RUN] sensor: {port} is held by another program (Arduino IDE Serial "
              f"Monitor / digital_twin_live.py?) -- close it, the browser cannot share the port")
    print("[RUN] sensor mode: keep the Variac at 0 for the first ~10 s (zero-offset "
          "measurement), then turn it up")
    if not _open_in_chrome(html.as_uri() + "?sensor=1"):
        print("[RUN] Google Chrome not found -- open the page in Chrome or Edge and "
              "choose Sensor -> Connect Arduino")
        webbrowser.open(html.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
