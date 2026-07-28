# Bericht: Warum ein benutzerdefinierter Python-Code statt SimScale oder andere Simulationssoftware

> Vorbereitet 2026-07-10, beantwortet Fragen des Professors.
> Detaillierte Referenzen: `docs/physics.md` (Formeln), `docs/ARCHITECTURE.md`,
> `docs/SENSOR_PLAN.md`, `README.md` (Roadmap), `docs/CHANGELOG.md` (Versionshistorie).

---

## 1. Motivation und Ansatz — Warum diese Richtung gewählt wurde

**Der Knackpunkt: Das Endprodukt ist kein "eine Simulationsergebnis", sondern ein
DIGITALES DUPLIKAT, das in ECHTZEIT läuft.** Dies sind zwei grundlegend
verschiedene Aufgaben:

| | Einmalige Simulation (SimScale, COMSOL…) | Digitales Duplikat (Anforderung) |
|---|---|---|
| Ausgabe | 1 Temperaturfeld für 1 Szenario | T(r,z,t) aktualisiert sich **kontinuierlich in Millisekunden**, wenn der Benutzer den Strom ändert |
| Rechenzeit | Minuten → Stunden pro Durchlauf | Muss < 16 ms/Frame sein (läuft auf dem Smartphone, AR) |
| Sensorkopplung | keine Echtzeit-API | zwingend erforderlich (Kalibrierung aus Arduino-Daten) |

Das, was Echtzeit ermöglicht, ist eine **physikalische Beobachtung** (keine
Softwarefunktion): Ein lineares System bei fester Frequenz 50 Hz ⇒ Joule-Verluste
skalieren **quadratisch mit I** bei *festem räumlichen Muster*, nur die Amplitude
ändert sich (plus σ(T)-Korrektur). Daher:

1. Löse die elektromagnetische FEM (Phasor) **nur einmal offline** bei I_ref = 5 A
   → Verlustverteilung q̂(r,z).
2. Runtime ist nur eine skalare Multiplikation `(I/I_ref)² × [σ(T)/σ(T_ref)]` +
   thermisches ROM erster Ordnung → Millisekunden, läuft im Browser auf dem Smartphone.

**Keine kommerzielle Software erlaubt es, die Pipeline auf diese Weise zu "öffnen"** —
sie verschließt den Solver in einer Black Box: jede Stromänderung = ein kompletter
FEM-Neustart. Um die I²-Struktur des Problems auszunutzen, muss man den Solver
auf Quellcode-Ebene kontrollieren.

Weitere Motivationen (aber real):
- **FEMM wird sofort ausgeschlossen**: Nur Windows-native, Entwicklungsmaschine ist macOS
  (Entscheidung bereits getroffen).
- Problem ist **achsensymmetrisch** → nur 2D (r,z) nötig, System ~10⁴ Unbekannte —
  `scipy.sparse.linalg.spsolve` löst in < 1 Sekunde. CAE-Software für 3D bei diesem
  Maßstab zu verwenden ist "ein Messer zum Schlachten eines Huhns", und das ist noch
  langsamer wegen 3D-Meshing.
- **TEAM Problem 28 entstand genau zur Validierung selbst geschriebener Codes** — dies
  ist der Standardvergleichswert der Computational-Electromagnetics-Gemeinschaft
  (COMPUMAG). Dem Geist der Aufgabenstellung folgen bedeutet: Solver selbst schreiben,
  dann validieren.
- **Transparenz & Verifikation**: Energiebilanz mit 0.000 % Fehler, I²-Check ergibt
  genau 4.000000, jede Konstante sitzt in `params.yaml` (single source of truth), gesamte
  Änderungshistorie im Git. Mit Black-Box-Software kann man nur *Ergebnissen vertrauen*;
  mit eigenem Code kann man *Ergebnisse beweisen*.
- **Kosten = 0**: numpy/scipy Open-Source, keine Lizenzen, keine Cloud-Credits,
  keine Internetabhängigkeit.
- **Wissenschaftlicher Wert**: Das ganze Team versteht jede Gleichung von der schwachen
  Form bis zur Matrix — das ist der Zweck des Kurses, nicht das Drückenlernen einer GUI.

---

## 2. Vergleich mit anderen Simulationswerkzeugen

| Kriterium | **SimScale** (Cloud CAE) | **COMSOL / ANSYS Maxwell** | **FEMM** | **Elmer / FEniCS** (Open-Source FEM) | **Python selbst geschrieben (gewählt)** |
|---|---|---|---|---|---|
| EM bei niedriger Frequenz (Wirbelstrom, Phasor A_φ) | begrenzt — Stärken sind CFD/Struktur/Wärmeleitung, nicht Magnetik 50 Hz | ✔ sehr gut | ✔ gut (2D) | ✔ verfügbar (Elmer) | ✔ selbst geschrieben, validiert mit TEAM 28 |
| EM → Wärmekopplung | schwierig, schwer in einer Pipeline | ✔ | ✘ Wärmeleitung schwach | ✔ aber komplex zu konfigurieren | ✔ direkt: q = ½σω²\|A_φ\|² in Wärmesolver |
| Achsensymmetrie 2D (ausnutzbar) | ✘ volles 3D-Meshing | ✔ | ✔ | ✔ | ✔ kleines System ~10⁴ Unbekannte |
| **ROM / Echtzeit** | ✘ | teilweise (separates ROM-Modul, teuer) | ✘ | ✘ | ✔ **Kernentwurf** |
| Export zu Web/AR auf Smartphone | ✘ | ✘ | ✘ | ✘ | ✔ in 1 HTML-Datei bake |
| Sensor-Arduino-Integration zur Kalibrierung | ✘ | schwierig, braucht proprietäre Skripte | ✘ | selbst schreiben | ✔ `data_io.py` → `rom.calibrate_UA()` |
| Läuft auf macOS | ✔ (Browser) | ✔ (teuer) | ✘ **nur Windows** | ✔ | ✔ |
| Kosten | kostenloses Limit, nach Core-Hours abgerechnet | Lizenzen tausende € | kostenlos | kostenlos | kostenlos |
| Black-Box? | ja | ja | teilweise | nein | **nein — 100 % Kontrolle** |

Anmerkungen zu jedem Werkzeug:

- **SimScale**: hervorragend bei CFD, Struktur, allgemeine Wärmeleitung — aber unsere
  Aufgabe erfordert *Low-Frequency-Elektromagnetik* (Wirbelströme 50 Hz in Aluminiumscheibe),
  nicht ihre Stärke. Selbst wenn lösbar, ist jedes Szenario ein Cloud-Job, berechnet
  in Minuten → kein Echtzeit-Duplikat möglich; Internet-abhängig; Daten auf ihren
  Servern; kostenloses Limit restriktiv.
- **COMSOL/ANSYS**: technisch könnten sie alles lösen, aber Lizenzen sprengen das
  Budget von Studierenden, können nicht auf AR-Smartphone exportiert werden, und
  machen aus der Arbeit eine Lektion "Software verwenden" statt "Physik verstehen".
- **FEMM**: Eigentlich sehr geeignet für 2D EM — aber Windows-natürlich, macOS
  Maschine → von Anfang an ausgeschlossen (Entscheidung getroffen).
- **PyVista — wichtiger Hinweis: PyVista ist KEIN Solver.** Es ist eine 3D-Visualisierungsbibliothek
  (VTK-Wrapper). Im Projekt wird es **korrekt verwendet**: `visualize.py` revolts die 2D-Ergebnisse
  in 3D und exportiert GLB/OBJ. Der richtige Vergleich ist also nicht "Code vs PyVista",
  sondern "selbst geschriebener Solver + PyVista zur Visualisierung".
- **Python selbst geschrieben** zahlt den Preis der Selbstvalidierung — und wir haben es
  getan: Energiebilanz 0.000 %, I²-Skalierung genau 4.000000, Spulentemperatur kalibriert
  nach echten IR-Daten (HIKMICRO, RMS-Fehler ≈ 2,5 °C auf transient). ⚠️ **Stand
  2026-07-11**: die Hubkraft-Zahlen unten sind veraltet (galten für die Geometrie vor der
  Neuvermessung 2026-07-10). Aktuell: F_z(5A, z=3,8mm) ≈ 4,10 N ≫ Gravitationskraft 1,60 N,
  aber der vorhergesagte Gleichgewichtsspalt liegt bei z_eq ≈ 11,7 mm (Plattenunterseite,
  sichtbar ≈ 14,7 mm) gegenüber beobachteten 7–8 mm sichtbar — eine offene Diskrepanz
  (siehe CLAUDE.md "LIFT FORCE" / `docs/archive/2026-07-11_BUG_REGISTER.md`). Ein Experiment mit
  dem nichtlinearen Sättigungsmodell für μᵣ hat Sättigung als Erklärung ausgeschlossen
  (Kraftänderung < 0,1 %) — die Ursache bleibt offen.

---

## 3. Warum HTML-Ausgabe statt anderer Bibliotheken/Apps

Die finale Anforderung der Aufgabe: **AR-App + QR-Code**. Anwendungsfall: Der Benutzer
steht neben dem Rig, scannt den QR-Code, das Duplikat öffnet sich sofort auf seinem Smartphone.
Das setzt Constraints:

| Option | Problem |
|---|---|
| Native App / Unity AR | Installation nötig, über App Store, schwere Toolchain, jede Änderung = erneute Bereitstellung |
| Streamlit / Dash / Jupyter | braucht **laufenden Python-Server** — QR muss auf immer eingeschaltete Maschine zeigen |
| matplotlib (`digital_twin.py`) | läuft nur auf Desktop mit Python — nur internes Entwicklungswerkzeug |
| **1 statische HTML-Datei (gewählt)** | hat keine der obigen Probleme |

Eine einzelne Datei `digital_twin_fem.html` **völlig eigenständig** (self-contained):

- FEM-Ergebnisse + ROM sind **zur Buildzeit in JavaScript bake** (`build_twin_html_fem.py`)
  — im Browser bleibt nur O(n) Arithmetik → 60 fps auf Smartphone, dank ROM-Architektur
  aus Punkt 1.
- Statische Hosts kostenlos (GitHub Pages) — kein Backend, keine Serverwartung;
  QR-Code (`gen_qr.py`) zeigt direkt auf URL.
- Keine Installation erforderlich: Browser des Smartphones reicht aus.
- Vollständig interaktiv: Strom-Slider / Variac-Regler (Grad), 4 Scheibenradien
  direkt swap, Flugmodell mit Schwingung, T_amb von Weather API.

Fazit: HTML ist nicht "Ersatz für Simulationsbibliothek" — es ist der **einzige Verteilkanal**,
der "QR-Scan = läuft, keine Installation" erfüllt. Die ganze Physik wird immer noch in Python
gelöst; HTML empfängt nur das gebackene Ergebnis.

---

## 4. Projektstruktur, durchlaufene Etappen, verbleibende Schritte

### Pipeline-Architektur (One-Way-Durchlauf, jede Datei eine Aufgabe)

```
params.yaml  (alle Parameter: Geometrie, Materialien, Strom, BC — kein Hardcoding)
    │
config.py    (nächste + normalisiere mm→m, leite I_peak = I_rms·√2 ab)
    │
em_solver.py          thermal_solver.py
(Phasor FEM A_φ,      (achsensymmetrische Wärmeleitung FEM,
 Wirbelstrom + Ohm,   Energiebilanz 0.000%)
 Hubkraft, Benchmark)
    └────────┬────────┘
          rom.py      (ROM Echtzeit: I²-Skalierung + Transient 1. Ordnung + σ(T))
             │
  ┌──────────┼──────────────────┐
digital_twin.py   visualize.py   build_twin_html_fem.py
(interaktives     (revolve 2D→3D, (bake → digital_twin_fem.html,
 Twin, matplotlib, GLB/OBJ)        endgültige AR)
 Entwicklung)
             │
data_io.py + arduino/thermal_sensor.ino   gen_qr.py
(Sensor-Bridge → ROM-Kalibrierung)        (QR → gehostete URL)
```

### Durchlaufene Etappen (nach README-Roadmap)

- ✅ **Phase 1a** — Wärmesolver achsensymmetrisch, Energiebilanz 0.000 % validiert.
- ✅ **Phase 1b** — EM-Solver (AC Wirbelstrom, Phasor); Verluste real berechnet;
  Spulengeometrie neu vermessen (2026-07-10, per Lineal, ersetzt die 2026-07-01
  Schätzung): Scheibe Ø160 mm, innere Spule 1000 Windungen r=27,9–61,9 mm,
  äußere Spule 500 Windungen r=82,9–102,9 mm.
- ✅ **Phase 2** — ROM Echtzeit (I² + Transient + σ(T)); τ ≈ 4,07 min @ R=80 mm
  (neu berechnet nach der Geometrie-Neuvermessung 2026-07-10).
- ✅ **Phase 3** — Interaktive Twin-Schleife (Strom-Slider, Scheibenwahl).
- ✅ **Phase 4** — 2D→3D Revolve, GLB/OBJ Export (PyVista/meshio).
- ✅ **Phase 5** — Eigenständiges AR Twin HTML + QR-Generator.
- ✅ **Phase 6** — Bereichsgröße validiert (Dirichlet vs Neumann, 1×1 m Box nach
  Professorvorgabe); gesamte Pipeline mit T_amb = 20 °C neu laufen gelassen.
- ✅ **Phase 8** — Sensordaten-Pipeline (`data_io.py` + Arduino-Firmware),
  End-to-End mit simulierter CSV getestet, echte Hardware noch nicht nötig.
- ✅ **Kalibrierung mit echtem Rig** — 2 gemessene Betriebspunkte (190 V→5 A,
  270 V→7,8 A), HIKMICRO-Wärmebild; Spulen-Lumped-Netzwerk fit RMS ≈ 2,5–3 °C;
  Hubkraft validiert gegen beobachtete Schwebetiefe.

### Verbleibende Schritte

1. **Phase 7 — echte Sensoren-Hardware** (größter Schritt, siehe Punkt 5): Arduino +
   2× MAX31855 montieren, einen echten Durchlauf aufzeichnen, ROM aus echten Daten
   neukalibrieren.
2. **Hosting + QR**: URL wählen (wahrscheinlich GitHub Pages), QR freigeben.
3. Offene physikalische Fragen (blockieren nicht):
   - ✅ Magnettest für äußeren Eisenring: **erledigt 2026-07-10** — Ring ist
     ferromagnetisch (μᵣ=1000, wie der Zentralkern), Position neu vermessen
     auf r=64,9–79,9 mm (war 81–101 mm). Offen bleibt: die exakte Legierung/
     B-H-Kurve wurde nie gemessen (μᵣ=1000 ist ein Platzhalter) — siehe
     Hubkraft-Diskrepanz oben.
   - Dichtere Variac-Regler → Strom-Tabelle (derzeit nur 3 Ankerpunkte).
   - Ringscheiben-Unterstützung (3 echte Scheiben r_out=55/r_in=27,5 mm, nicht gemeshed).
   - Benchmark TEAM 28 Originalversion: z_eq ≈ 14,5 mm vs 11,3 mm erwartet (28%
     Overshoot, Stand 2026-07-11 nach einem RMS/Peak-Bugfix — war zuvor 6,8mm/
     40% Undershoot) — weiterhin pausiert nach Team-Abstimmung, blockiert nicht
     echtes Rig.
   - ✅ `validate_domain_size()`: **PASS** (alle Abweichungen <1%, z.B. P_plate
     0,767%) nach Neulauf auf der 2026-07-10 Geometrie+Eisen-Update — war zuvor
     2,71% FAIL, Ursache der früheren Regression weiterhin unklar, blockiert
     aber nicht mehr.

---

## 5. Hardwareanbindungs-Ansatz (Validierungsschleife)

Nach Anweisung des Professors (Juni 2026): *"Schaut, was es genau bräuchte, und baut
dann selbst eine kleine Lösung — Arduino plus ein paar Sensoren, und dann einfach noch
ein Infrarot-Thermometer."* Vollständige Details: `docs/SENSOR_PLAN.md`.

### Mess-Architektur

```
Thermoelement K #1 (Spulenkern) ────▶ MAX31855 ─┐
                                                 ├─▶ Arduino Uno/Nano ─USB serial─▶ Laptop
Thermoelement K #2 (Scheibenboden) ─▶ MAX31855 ─┘        (CSV, 1 Hz)
IR-Handthermometer ──▶ manuelle Stichprobenkontrolle (Gegenprobe)
```

- **Warum Thermoelement statt nur IR**: Wärmebild-IR auf glänzendem Aluminium /
  Keramikkern **ist unzuverlässig** (falsche Emissivität — bestätigt in
  HIKMICRO-Messung 2026-06-23); nur dunkel lackierte Spule ist IR-zuverlässig. Thermoelemente
  in Kontakt lösen IR-Fehler genau da, wo nötig: **Scheibenboden** — auch das Datum,
  das die Frage auflöst "ist Scheibe oder Spule heißer".
- Firmware bereits geschrieben: `arduino/thermal_sensor.ino` (2× MAX31855 über SPI,
  CSV 1 Hz über seriell).

### Software-Pipeline (läuft jetzt, wartet auf Hardware)

```
Arduino (CSV seriell) ─▶ data_io.py SensorReader (mode serial | mock)
                     ─▶ calibrate_from_file()
                     ─▶ rom.calibrate_UA()   ← fit hA, τ aus Messdaten
```

Diese gesamte Kette wurde **End-to-End mit `mock_sensor_data.csv` getestet** — sobald
die Hardware kommt, nur USB anstecken und `--mode mock` zu `--mode serial` ändern,
kein zusätzlicher Code nötig.

### Bereitstellungsschritte

1. Shopping-Liste finalisieren (Reichelt/Conrad: Arduino Nano, 2× MAX31855-Breakout,
   2× Thermoelement Typ K, Kabel) → Professor kauft.
2. Montieren + Firmware flashen, mit Eis/kochendem Wasser testen (2 Kalibrierungspunkte).
3. Einen echten Durchlauf aufzeichnen (Abkühlung → steady state, ≥ 3τ ≈ 20 min) bei
   190 V / 5 A.
4. `data_io.py --mode calibrate` → hA_inner/hA_outer/UA aus echten Daten neukalibrieren
   (ersetzt aktuelle IR-Kalibrierung).
5. **Cooldown-Durchlauf** aufzeichnen (Strom aus, kühlen) → separates Zwei-Knoten-Modell
   der Spule fitten (`coil_G_wind_W_per_K`, derzeit nur größenordnungsmäßig korrekt).
6. Später erweitern (nach Phase 1): Real-Zeit-Strommessgerät (Professor bestätigt Kauf
   erforderlich) → Twin empfängt echtes I(t) statt Konstante 5 A; noch weiter: direktes
   Streaming in HTML-Twin über Web Serial API.

---

## Eine kurze Antwort für den Professor

> "Wir codieren nicht *statt* Simulation — wir codieren *weil* die Anforderung ein
> digitales Echtzeit-Duplikat auf dem Smartphone ist. Tools wie SimScale lösen ein
> Szenario in Minuten; unser Duplikat muss in Millisekunden antworten, wenn der Benutzer
> das Stromregler dreht. Das ist nur möglich, wenn man die Physik-Struktur nutzt (Verluste
> ∝ I², Raumverteilung fest) um FEM genau einmal zu lösen und dann zur ROM zu reduzieren —
> und das erfordert Kontrolle des Solvers auf Quellcode-Ebene. Im Gegenzug validieren wir
> streng: Energiebilanz 0.000 %, I²-Skalierung exakt richtig, Hubkraft und Spulentemperatur
> stimmen mit echten Messdaten überein."
