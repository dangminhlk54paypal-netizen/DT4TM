"""ar_i18n.py -- English UI variant of the AR twin page (WP-AR-EN).

build_ar_twin.py keeps ONE template (German UI). `--lang en` runs `translate_template()`
over the TEMPLATE text only (placeholders such as __TWIN_ENGINE__, __PARAMS_JSON__,
__APRILTAG_WASM_JS__ are still unexpanded at that point), so the physics engine block,
the baked data and the AprilTag WASM are never touched -- the English page satisfies the
same xval_twin.py AR-1/AR-2 identity checks as the German one.

Mechanism:
  * UI_EN = [(german, english), ...] exact substring pairs, applied in ONE regex pass
    (longest key first, so a short key never corrupts a longer one and no output is
    re-translated).
  * Every entry must match at least once, otherwise `StaleEntryError` names it -- the
    table cannot rot silently when the template text changes.
  * `find_german_leftovers()` then scans only what reaches the user (HTML text nodes,
    title/aria/placeholder attributes, JS string literals with comments stripped, CSS
    `content:` strings) for umlauts and common German UI words and fails the build.

Keys deliberately include delimiters/context (`>Sichtbar</button>`, quotes, ...) so they
cannot hit identifiers, CSS classes, element ids, localStorage keys or status codes the
code compares against (e.g. 'unruhig', 'plateOnly').
"""
from __future__ import annotations
import re

# Strings that are German but are CODE (compared in the page's JS), not UI text.
# The English page keeps them as is; the leftover scan ignores them.
CODE_STRINGS = {"unruhig"}

UI_EN: list[tuple[str, str]] = [
    # ── <head> / error overlay ───────────────────────────────────────────────
    ('<html lang="de">', '<html lang="en">'),
    ('<title>TEAM 28 — WebAR Digitaler Zwilling</title>', '<title>TEAM 28 — WebAR Digital Twin</title>'),
    ("'⚠️ JavaScript Hinweis'", "'⚠️ JavaScript notice'"),
    ("'Skriptfehler'", "'Script error'"),
    # ── message box / header ─────────────────────────────────────────────────
    ('<h3 id="msgTitle">Hinweis</h3>', '<h3 id="msgTitle">Notice</h3>'),
    ('id="btnCloseMsg">Verstanden</button>', 'id="btnCloseMsg">Got it</button>'),
    ('<div id="trackingBadge">🟡 3D-Vorschau</div>', '<div id="trackingBadge">🟡 3D preview</div>'),
    # ── telemetry ────────────────────────────────────────────────────────────
    ('<span class="t-label">Strom I</span>', '<span class="t-label">Current I</span>'),
    ('<span class="t-label">Platte T</span>', '<span class="t-label">Plate T</span>'),
    ('<span class="t-label">Spule T</span>', '<span class="t-label">Coil T</span>'),
    ('<span class="t-label">Spalt Modell</span>', '<span class="t-label">Gap (model)</span>'),
    ("`Spalt gemessen ≈ ${M.gapMm.toFixed(1)} mm (Modell ${lev.z.toFixed(1)}) · Kipp ≈ ${M.tiltDeg.toFixed(1)}° · Dreh ≈ ${Math.round(M.spinRpm)} U/min`",
     "`Measured gap ≈ ${M.gapMm.toFixed(1)} mm (model ${lev.z.toFixed(1)}) · tilt ≈ ${M.tiltDeg.toFixed(1)}° · spin ≈ ${Math.round(M.spinRpm)} rpm`"),
    # ── start banner ─────────────────────────────────────────────────────────
    ('<h3>Kamera-Überlagerung (AR)</h3>', '<h3>Camera overlay (AR)</h3>'),
    ('<p>Starte die Kamera und richte sie auf die beiden AprilTag-Marker (PDF mit 100 % / Originalgröße drucken): '
     '<b>Seite 1 = Platten-Marker</b> auf die Platte kleben, <b>Seite 2 = Basis-Marker</b> fest neben den Prüfstand. '
     'Der Unterbau bleibt dann stehen, während die Platte dreht und schwebt.</p>',
     '<p>Start the camera and point it at the two AprilTag markers (print the PDF at 100 % / actual size): '
     '<b>page 1 = plate marker</b> goes on the plate, <b>page 2 = base marker</b> goes fixed next to the test rig. '
     'The base then stays put while the plate spins and levitates.</p>'),
    ('📷 Kamera starten', '📷 Start camera'),                    # button text (HTML + JS reset after a failed start)
    ('content: "Kamera auf Platten- und Basis-Marker richten"', 'content: "Point the camera at the plate and base markers"'),
    # ── sliders / pills ──────────────────────────────────────────────────────
    ('<span class="slider-title">Erregerstrom (RMS)</span>', '<span class="slider-title">Excitation current (RMS)</span>'),
    ('0.00 A (0V - Stillstand)', '0.00 A (0V - standstill)'),
    ('<span class="slider-title">Sim-Geschwindigkeit</span>', '<span class="slider-title">Sim speed</span>'),
    ('⚡ B-Feld', '⚡ B-field'),
    ('👁️ Röntgen', '👁️ X-ray'),
    ('⚙️ Anpassen', '⚙️ Adjust'),
    # ── adjust (calibration) panel ───────────────────────────────────────────
    ('<span class="calib-title">Unterbau (Basis-Marker)</span>', '<span class="calib-title">Base (base marker)</span>'),
    ('text-align:right; font-size:0.72rem;">noch nicht</span>', 'text-align:right; font-size:0.72rem;">not yet</span>'),
    ('📏 Unterbau einmessen (Platte liegt auf)', '📏 Calibrate base (plate resting)'),   # HTML + calUi() idle text
    ("'📏 Unterbau einmessen'", "'📏 Calibrate base'"),                                  # help dialog title
    ('font-size: 0.72rem;">zurücksetzen</button>', 'font-size: 0.72rem;">Reset</button>'),
    ('<span class="calib-title">Auto-Ausrichten</span>', '<span class="calib-title">Auto-align</span>'),
    ('📐 Kante zu mir einrasten', '📐 Snap edge toward me'),                             # HTML + reset after 2.2 s
    ('<span class="calib-title">Drehwinkel (Ecken)</span>', '<span class="calib-title">Rotation (corners)</span>'),
    ('title="Winkel umschalten"', 'title="Switch angle"'),
    ('<span class="calib-title">Neigung (Pitch)</span>', '<span class="calib-title">Tilt (pitch)</span>'),
    ('title="Zurücksetzen"', 'title="Reset"'),
    ('<span class="calib-title">Modellgröße</span>', '<span class="calib-title">Model size</span>'),
    ('<span class="calib-title">Position X (seitlich)</span>', '<span class="calib-title">Position X (lateral)</span>'),
    ('<span class="calib-title">Position Y (Tiefe)</span>', '<span class="calib-title">Position Y (depth)</span>'),
    ('<span class="calib-title">AR-Deckkraft</span>', '<span class="calib-title">AR opacity</span>'),
    ('<span class="calib-title">Platten-Overlay</span>', '<span class="calib-title">Plate overlay</span>'),
    ('<span class="calib-title">Holzgehäuse</span>', '<span class="calib-title">Wooden housing</span>'),
    ('>Sichtbar</button>', '>Visible</button>'),
    ("? 'Sichtbar' : 'Aus';", "? 'Visible' : 'Off';"),
    ('<span class="calib-title">Marker-Größe (Tag)</span>', '<span class="calib-title">Marker size (tag)</span>'),
    ('<span class="calib-title">Höhentrimmung (Z)</span>', '<span class="calib-title">Height trim (Z)</span>'),
    ('<span class="calib-title">Levitation simulieren</span>', '<span class="calib-title">Simulate levitation</span>'),
    ('>Aus (0mm)</button>', '>Off (0mm)</button>'),
    ("enableLevitation ? 'Ein (Sim-Gap)' : 'Aus (0mm)'", "enableLevitation ? 'On (sim gap)' : 'Off (0mm)'"),
    # ── calibration status (calUi) ───────────────────────────────────────────
    ("`⏳ Messe … (${c.samples.length})`", "`⏳ Measuring … (${c.samples.length})`"),
    ("'zu unruhig – Kamera ruhig halten'", "'too unsteady – hold the camera steady'"),
    ("'beide Marker im Bild halten'", "'keep both markers in view'"),
    ("`zu unruhig (${c.jitterMm == null ? '?' : c.jitterMm.toFixed(1)} mm) – nochmal`",
     "`too unsteady (${c.jitterMm == null ? '?' : c.jitterMm.toFixed(1)} mm) – try again`"),
    ("'zu wenige Bilder – beide Marker ruhig im Bild halten, nochmal'", "'too few frames – hold both markers steady in view, try again'"),
    ("'beide Marker nicht gleichzeitig erkannt'", "'both markers not detected at the same time'"),
    ("'vorläufig (automatisch) – bitte einmessen'", "'provisional (automatic) – please calibrate'"),
    ("`eingemessen ✓${F.cal.stored ? ' (gespeichert)' : ''}`", "`calibrated ✓${F.cal.stored ? ' (saved)' : ''}`"),
    ("'noch nicht (beide Marker zeigen)'", "'not yet (show both markers)'"),
    # ── tracking badge (trkBadge) ────────────────────────────────────────────
    ("`🟢 Platte ${tp}/4 + Basis ${tb}/4 Tags${prov ? ' · vorläufig' : ''}`",
     "`🟢 Tracking: both markers (${tp}/4 + ${tb}/4)${prov ? ' · provisional' : ''}`"),
    ("`🟢 Basis ${tb}/4 Tags · Platte: Modell`", "`🟢 Tracking: base ${tb}/4 · plate from model`"),
    ("`🟠 Nur Platte ${tp}/4 · Basis kamerafest`", "`🟠 Plate only ${tp}/4 – base locked to camera`"),
    ("'🟠 Basis erkannt – Platten-Marker zum Einmessen zeigen'", "'🟠 Base detected – show plate marker to calibrate'"),
    ("'🟡 Marker verdeckt – halte Pose'", "'🟡 Marker hidden – holding pose'"),
    ('"🟡 Suche Marker..."', '"🟡 Searching for marker…"'),
    ("'🟡 Suche Marker...'", "'🟡 Searching for marker…'"),
    # ── camera start / error dialogs ─────────────────────────────────────────
    ('"🔒 Kamera nicht verfügbar"', '"🔒 Camera unavailable"'),
    ('<p>Du hast die Datei als <b>lokale Datei oder im Datei-Viewer</b> geöffnet.</p>',
     '<p>You opened this page as a <b>local file or in a file viewer</b>.</p>'),
    ('<p>Apple Safari und Android Chrome verlangen aus Sicherheitsgründen eine <b>verschlüsselte HTTPS-Adresse</b> für den Kamerazugriff.</p>',
     '<p>For security reasons, Apple Safari and Android Chrome require an <b>encrypted HTTPS address</b> for camera access.</p>'),
    ('<li><b>Dauerhafte Lösung:</b> Auf <b>GitHub Pages</b> hosten: <code>https://&lt;user&gt;.github.io/DT4TM/outputs/ar_twin.html</code></li>',
     '<li><b>Permanent solution:</b> host it on <b>GitHub Pages</b>: <code>https://&lt;user&gt;.github.io/DT4TM/outputs/ar_twin_en.html</code></li>'),
    ('<li><b>WLAN-Test:</b> Am PC <code>python serve_ar.py</code> starten und QR-Code scannen.</li>',
     '<li><b>Wi-Fi test:</b> run <code>python serve_ar.py</code> on the PC and scan the QR code.</li>'),
    ('<li><b>Hinweis:</b> Im 3D-Vorschaumodus kannst du die gesamte Simulation hier bereits interaktiv mit Touch bedienen!</li>',
     '<li><b>Note:</b> In 3D preview mode you can already use the whole simulation here by touch!</li>'),
    ('<p>Dieser Browser unterstützt keinen Kamerazugriff oder die Berechtigung wurde blockiert.</p>',
     '<p>This browser does not support camera access, or the permission was blocked.</p>'),
    ('<p>Bitte überprüfe in den Browser-Einstellungen, ob der Kamerazugriff erlaubt ist.</p>',
     '<p>Please check in the browser settings that camera access is allowed.</p>'),
    ('"⌛ Kamera wird gestartet..."', '"⌛ Starting camera..."'),
    ('"⚠️ Kamera-Zugriff fehlgeschlagen"', '"⚠️ Camera access failed"'),
    ('<p>Fehlermeldung: <b>', '<p>Error message: <b>'),
    ('<p>Mögliche Ursachen:</p>', '<p>Possible causes:</p>'),
    ('<li>Kamera-Berechtigung im Browser abgelehnt (in den Website-Einstellungen auf "Erlauben" setzen).</li>',
     '<li>Camera permission was denied in the browser (set it to "Allow" in the site settings).</li>'),
    ('<li>Die Kamera wird bereits von einer anderen App blockiert.</li>', '<li>The camera is already in use by another app.</li>'),
    ('<li>Keine sichere HTTPS-Verbindung (z. B. <code>http://</code> statt <code>https://</code>).</li>',
     '<li>No secure HTTPS connection (e.g. <code>http://</code> instead of <code>https://</code>).</li>'),
    # ── auto-align feedback ──────────────────────────────────────────────────
    ("`✅ Eingerastet (${manualYawDeg", "`✅ Snapped (${manualYawDeg"),
    # ── calibrate-base help dialog ───────────────────────────────────────────
    ('<p>Kamera starten, <b>beide Marker</b> (Platte + Basis) ins Bild nehmen, Platte liegt auf den Spulen (kein Strom), dann erneut tippen.</p>',
     '<p>Start the camera, get <b>both markers</b> (plate + base) in view with the plate resting on the coils (no current), then tap again.</p>'),
]


class StaleEntryError(RuntimeError):
    pass


def translate_template(template: str, table=None) -> str:
    """Apply the table to the page TEMPLATE in one pass. Raises StaleEntryError for any
    entry that never matched (the template text changed under it)."""
    table = UI_EN if table is None else table
    keys = [de for de, _ in table]
    if len(set(keys)) != len(keys):
        dup = sorted({k for k in keys if keys.count(k) > 1})
        raise StaleEntryError(f"duplicate UI_EN keys: {dup}")
    mapping = dict(table)
    rx = re.compile("|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)))
    hits = dict.fromkeys(mapping, 0)

    def sub(m):
        hits[m.group(0)] += 1
        return mapping[m.group(0)]

    out = rx.sub(sub, template)
    stale = [k for k, n in hits.items() if n == 0]
    if stale:
        raise StaleEntryError(
            "UI_EN entries that match nothing in build_ar_twin.py's template (stale or shadowed by a longer key):\n  "
            + "\n  ".join(repr(k[:110]) for k in stale))
    return out


# ── leftover scan ────────────────────────────────────────────────────────────
_GERMAN_WORDS = (
    "und oder nicht bitte noch nochmal vorläufig automatisch gleichzeitig erkannt bild bilder ruhig zeigen "
    "kamera platte platten spule strom spalt basis unterbau einmessen eingemessen zurücksetzen sichtbar hinweis "
    "fehlermeldung verstanden erlauben messe neigung drehwinkel höhe gehäuse holzgehäuse röntgen geschwindigkeit "
    "erreger erregerstrom lösung kante deckkraft größe gespeichert wenige beide ein eine aus für ist wird nur mit "
    "dem den der das du dein deine kipp dreh suche verdeckt halte starten gestartet überlagerung vorschau"
).split()
_WORD_RX = re.compile(r"(?<![\w-])(" + "|".join(sorted(map(re.escape, _GERMAN_WORDS), key=len, reverse=True)) + r")(?![\w])", re.I)
_UMLAUT_RX = re.compile(r"[äöüÄÖÜß]")


def _strip_js_and_collect_literals(js: str) -> list[str]:
    """Tokenize JS just enough to drop comments and return string/template literal bodies."""
    lits, i, n = [], 0, len(js)
    while i < n:
        c = js[i]
        if c == "/" and js[i + 1:i + 2] == "/":
            j = js.find("\n", i)
            i = n if j < 0 else j
        elif c == "/" and js[i + 1:i + 2] == "*":
            j = js.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif c in "'\"`":
            q, j, buf = c, i + 1, []
            while j < n and js[j] != q:
                if js[j] == "\\":
                    buf.append(js[j:j + 2]); j += 2; continue
                if js[j] == "\n" and q != "`":
                    break                     # not a string (e.g. a regex quote) -- resync
                buf.append(js[j]); j += 1
            lits.append("".join(buf))
            i = j + 1
        else:
            i += 1
    return lits


def user_visible_texts(template: str) -> list[str]:
    """Everything in the TEMPLATE that can reach the user: HTML text nodes, attributes,
    JS string literals (comments dropped), CSS content strings."""
    t = re.sub(r'(<script type="text/plain" id="apriltag-src">).*?(</script>)', r"\1\2", template, flags=re.S)
    texts: list[str] = []
    for m in re.finditer(r"<script\b[^>]*>(.*?)</script>", t, flags=re.S):
        texts += _strip_js_and_collect_literals(m.group(1))
    for m in re.finditer(r"<style\b[^>]*>(.*?)</style>", t, flags=re.S):
        texts += re.findall(r'content:\s*"([^"]*)"', m.group(1))
    html = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", t, flags=re.S)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    texts += re.findall(r'\b(?:title|aria-[\w-]+|placeholder|alt)="([^"]*)"', html)
    texts += [s for s in re.split(r"<[^>]*>", html) if s.strip()]
    return texts


def find_german_leftovers(template: str) -> list[str]:
    bad = []
    for s in user_visible_texts(template):
        if s in CODE_STRINGS:
            continue
        hit = _UMLAUT_RX.findall(s) or _WORD_RX.findall(s)
        if hit:
            bad.append(f"{sorted(set(h.lower() for h in hit))}  in  {s.strip()[:100]!r}")
    return bad
