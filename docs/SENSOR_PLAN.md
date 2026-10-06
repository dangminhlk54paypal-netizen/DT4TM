# SENSOR_PLAN — Thermal Validation Hardware

> Last updated: 2026-06-22. Professor feedback Juni 2026.
> "Schaut was es genau bräuchte und baut dann selbst eine kleine Lösung.
>  Arduino plus ein paar Sensoren... und dann einfach noch ein Infrarot Thermometer."

---

## Ziel

Temperatur an zwei Stellen messen, um die Simulation zu validieren:
1. **Kupferkern** (copper core) — Thermocouple/RTD am Kern befestigt
2. **Unterseite der Scheibe** (bottom of levitating disc) — IR Thermometer / Thermocouple

Plus die reale Spulenstromstärke I_rms(t) (ACS712-20A, siehe Abschnitt
"Echtzeit-Stromsensor" unten) — ersetzt die bisher angenommene feste
Stromkonstante `current_A=5.0` in params.yaml.

Die gemessenen Daten werden über `data_io.py` → `rom.calibrate_UA()` eingespeist,
um den thermischen Zeitkonstanten τ und den Kopplungsfaktor `k_coil_coupling_K_per_W`
zu kalibrieren.

---

## Hardware-Architektur

```
┌──────────────┐     ┌──────────────────┐
│ Thermocouple │────▶│ MAX31855 Breakout │──┐
│ (Typ K)      │     │ (SPI Interface)   │  │   ┌─────────────┐
└──────────────┘     └──────────────────┘  ├──▶│ Arduino Uno │──USB──▶ Laptop
┌──────────────┐     ┌──────────────────┐  │   │ / Nano      │        (Serial)
│ Thermocouple │────▶│ MAX31855 Breakout │──┘   └─────────────┘
│ (Typ K) #2   │     │ (SPI Interface)   │
└──────────────┘     └──────────────────┘

┌────────────────────┐
│ IR Thermometer     │──── Handheld / USB → manual spot checks
│ (kontaktlos)       │
└────────────────────┘
```

---

## Einkaufsliste (Reichelt / Conrad)

### Variante A: Minimal (empfohlen für Phase 1)

| # | Komponente | Beschreibung | Stück | ~Preis |
|---|---|---|---|---|
| 1 | Arduino Uno R3 (oder Nano) | Microcontroller Board | 1 | ~25 € |
| 2 | MAX31855 Breakout Board | Thermocouple-zu-Digital Konverter (SPI) | 2 | ~15 € × 2 |
| 3 | Thermocouple Typ K | Messbereich -200°C bis +1350°C, Ø1mm | 2 | ~8 € × 2 |
| 4 | Breadboard + Jumper Wires | Für Prototyping | 1 Set | ~10 € |
| 5 | USB-Kabel (Typ A-B oder A-Micro) | Arduino ↔ Laptop Verbindung | 1 | ~5 € |
| 6 | IR Thermometer (Handheld) | Kontaktlose Oberflächentemperatur | 1 | ~30–50 € |

**Geschätzte Gesamtkosten: ~120–140 €**

### Variante B: Erweitert (optional, höhere Genauigkeit)

| # | Zusätzliche Komponente | Beschreibung | ~Preis |
|---|---|---|---|
| 7 | PT100 RTD Sensor + Adafruit MAX31865 | Höhere Genauigkeit (±0.5°C vs ±2°C) | ~25 € |
| 8 | MLX90614 IR Sensor (I²C) | Kontaktlose Temperatur via Arduino (statt Handheld) | ~15 € |
| 9 | SD-Karten-Modul | Logging ohne Laptop | ~8 € |

---

## Messpunkte

```
        ← IR Thermometer (Oberseite)
   ┌──────────────────┐
   │   Al-Scheibe      │  ← Thermocouple #2 (Unterseite, Rand befestigt)
   └──────────────────┘
         ↕ Luft (3.8mm Gap)
   ┌──────────────────┐
   │   Spulen          │
   │  ┌────────────┐   │
   │  │ Kupferkern  │   │  ← Thermocouple #1 (am Kern befestigt)
   │  └────────────┘   │
   └──────────────────┘
```

---

## Echtzeit-Stromsensor: ACS712-20A (2026-07-29, siehe docs/archive/Stromsensor_.docx)

Installationsplan für den Spulenstrom I_rms(t) — Innen- + Außenspule sind in Reihe
geschaltet (gemeinsamer Strom). Ersetzt `current_A=5.0` (fest angenommen) im ROM
durch eine echte Messung. Quelle: Carroll & Meynell CMV 10 E-1 Variac (0–270°),
Messbereich 0–7.8 A_rms.

**⚠ SICHERHEIT:** Der Spulenkreis führt 190–270V AC Netzspannung. ACS712 ist
Hall-Effekt-basiert (galvanisch getrennt, ~2.1kV) — **kein** Shunt-Widerstand
verwenden (keine Trennung, gefährlich). Variac-Dial vor jeder Verdrahtungsänderung
auf 0 stellen.

**Funktionsprinzip:** Der ACS712 hat einen internen Leiterpfad für den Hauptstrom;
das erzeugte Magnetfeld wird per Hall-Sensor ausgelesen und als analoge Spannung
ausgegeben (`Vout = Vcc/2 + 0.100 V/A × I(t)`, eingebauter Vcc/2-Offset, keine
externe Biasing-Schaltung nötig). Der Arduino tastet OUT mit ~8kHz ab (mehrere
volle 50Hz-Zyklen), berechnet den RMS-Wert um den GEMESSENEN Mittelwert (nicht
den angenommenen 2.5V-Offset, da sowohl die Arduino-5V-Schiene als auch der
Modul-Offset Toleranz haben) und sendet ihn als 4. CSV-Spalte.

### Einkaufsliste (Ergänzung)

| # | Komponente | Spezifikation | Menge | Anmerkung |
|---|---|---|---|---|
| 1 | ACS712-20A Modul | Breakout-Board, ±20A, 100mV/A | 1 | Hall-Effekt, galvanisch getrennt |
| 2 | Keramikkondensator | 0,1 µF, ≥16V | 1 | OUT→GND, filtert Rauschen |
| 3 | Jumper-Kabel | Stecker–Stecker / Stecker–Buchse | ~6 | Modul ↔ Arduino |
| 4 | Anschlussklemme | 2-polige Schraubklemme | 2 | aufgetrennte L-Zuleitung ↔ IP+/IP− (in Reihe) |

**Nicht verwenden:** CT-Stromwandler (bei 7,8A unnötig teuer), Shunt-Widerstand
(keine galvanische Trennung — gefährlich bei 190–270V).

### Anschlussplan

**⚠ IN REIHE, NICHT PARALLEL:** „Abgriff 1/2" sind die zwei Enden EINER aufgetrennten
Zuleitung (Phase L zwischen Variac-Ausgang und Spule), NICHT die beiden Spulenklemmen.
IP+/IP− an beide Spulenenden bei intakter Verdrahtung = Kurzschluss des Variac-Ausgangs
(Strompfad ~1.2 mΩ). Empfohlen: separates Mess-Zwischenkabel (Variac-Ausgang → Gehäuse
mit ACS712 → Spulenzuleitung), Rig selbst unverändert — genau dort, wo bei der
190V→5A-Messung das Multimeter (A-Modus, in Reihe) saß.

| VON | NACH | Hinweis |
|---|---|---|
| Variac-Ausgang L (Phase) | ACS712 IP+ | Hauptstromkreis, 190–270V AC |
| ACS712 IP− | Spulenzuleitung L (zur Spule) | Hauptstromkreis, 190–270V AC |
| Variac-Ausgang N | Spule N (unverändert, NICHT durch das Modul) | Hauptstromkreis |
| ACS712 VCC | Arduino 5V | Signalseite, sicher |
| ACS712 OUT (+ 0.1µF Cap → GND) | Arduino A0 | Signalseite, sicher |
| ACS712 GND | Arduino GND | Signalseite, sicher |

Linke Seite (IP+/IP−) = Netzspannungskreis, nur mit dem Modul verbunden, kein
Kontakt zur Arduino-Seite. Rechte Seite (VCC/OUT/GND) = sicheres 0–5V-Signal.

### Inbetriebnahme (vor dem ersten Netzspannungs-Test)

1. Arduino OHNE Variac-Verbindung (IP+/IP− offen) per USB anschließen, Serial
   Monitor öffnen (9600 baud) → `I_rms_A` sollte nahe 0.00 liegen (reines ADC-Rauschen).
2. Variac-Dial auf 0 stellen, Netzstecker des Variacs ziehen, Mess-Zwischenkabel (L in Reihe über IP+/IP−) einstecken.
3. Variac langsam hochdrehen bis 190V (5A-Betriebspunkt), `I_rms_A` mit einem
   Multimeter am Spulenkreis gegenchecken (sollte ~5.0A zeigen, ±5–10%).
4. Erst danach auf 270V (7.8A, Kalibrierpunkt) gehen, falls nötig.

### Was die AC-Strommessung dem Twin bringt — nachgerechnet (2026-10-02)

Alle Zahlen aus params.yaml + dem echten `TwinState` (Skript: Session-Scratchpad,
nicht committet). Nichts davon ist gemessen außer 190V→5A und dem Rauschboden 0.248A.

| Größe | Wert | Quelle |
|---|---|---|
| ADC-LSB, 10 bit / 14 bit (R4 `analogReadResolution(14)`) | 48.9 mA / 3.1 mA | 5V/(2ⁿ−1) / 0.100 V/A |
| OUT-Hub bei 5 A_rms / 7.78 A_rms | 2.5 ± 0.707 V / 2.5 ± 1.100 V | Î=I·√2 → kein Clipping; ACS712-**05**B (±5A) würde clippen |
| Rausch-Bias (Quadratur, Boden 0.248 A) | 0.5A→+11.6%, 1A→+3.0%, 5A→+0.12% | √(I²+0.248²) |
| R_Spulen (Formel em_solver, Draht 1.2 mm nominal) | 4.185 + 4.330 = 8.515 Ω | — |
| \|Z\| aus Messung 190V/5A | 38.0 Ω → X = 37.0 Ω, R/Z = 0.22 | — |
| Stromabfall durch Spulenerwärmung bei festem Dial (5A, T_ss) | −0.46 % | σ_Cu(T), α=3.9e-3 |
| T_inner,ss @20°C bei 4.75 / 5.00 / 5.25 A | 42.06 / 44.00 / 46.01 °C | TwinState |
| Aufheizen 5A, inner: t63 / t90 | 1024 s / 2747 s | TwinState (coil_C_scale nur Größenordnung) |

Folgerungen: ±5 % Stromfehler → ≈ ±8 % ΔT. Die σ(T)-Drift bei festem Dial ist klein
(induktiv dominierte Last) — der Gewinn liegt woanders: (1) der echte Strom an jeder
Dial-Stellung (Tabelle hat nur 3 Stützstellen), (2) **exakte Zeitstempel** für
Rampen/Abschalten (Ramp-Test heute aus erzählter Zeitachse, ±~10 s), (3) Netzschwankungen
gehen beim Variac 1:1 in I und ≈2× in die Verluste.

**Kein 0.1 µF direkt an OUT:** laut Allegro-Datenblatt ACS712 ist die zulässige
Lastkapazität an VIOUT max. 10 nF (bitte in „Common Operating Characteristics" prüfen).
Glättung macht die RMS-Mittelung über ganze Netzperioden.

### Integrationsplan (WP-ACS2, noch NICHT implementiert)

1. **Firmware — volle Abdeckung:** RMS über das GANZE 1-s-Intervall (= 50 Perioden,
   100 % statt heute 10 % Abtast-Duty: 100 ms Burst pro 1000 ms). Verluste ∝ ⟨i²⟩ über
   den Zeitschritt → energie-exakter Input, auch wenn am Dial gedreht wird.
   Optional R4: 14-bit ADC. CSV-Format `millis,I_rms_A` bleibt.
2. **Python — Rauschkorrektur:** `I = √max(0, I_meas² − I_noise²)` in
   `LiveDriver.condition()`, `I_noise` als neuer Key `live_sensor.noise_floor_A` (0.248,
   gemessen). Rohwert bleibt im Log.
3. **Kalibrierung:** `ACS712_CAL_SCALE` an 190V→5A gegen das blaue Multimeter (es sitzt
   bereits in Reihe — ACS712 in dieselbe Leitung), zweiter Punkt bei Dial-Max als
   Linearitätscheck. Dabei jede Dial-Stellung ~10 s halten → `dial_to_current_A` verdichten.
4. **Messprotokoll für die Transient-Kalibrierung:** Strom loggen + HIKMICRO-Bilder mit
   Uhrzeit (Uhren synchronisieren). Aufheizen 5A ≥ ~50 min (t90 = 2747 s laut Modell),
   dann Abschalten und Abkühlen loggen (I=0 exakt datiert).
5. **`refit_transient.py`** (neu, analog `refit_hA.py`): fittet `coil_C_scale`,
   `coil_G_wind_W_per_K`, Luftknoten durch den echten `TwinState`, angetrieben vom
   GELOGGTEN I(t) statt angenommener Stufen. hA bleibt bei `refit_hA.py`.

---

## Software-Pipeline (implemented)

### Arduino Firmware
`arduino/thermal_sensor/thermal_sensor.ino` — Adafruit MAX31855 library (hardware
SPI, CS pins D10 core / D9 disc) + ACS712-20A on A0. Every 1s prints:
```
millis,T_core_degC,T_disc_degC,I_rms_A
```
On a thermocouple fault the affected field is "nan" and a `# FAULT ...` line precedes
it; both are skipped by the Python parser. Baudrate 9600.

### Python `data_io.py`
- `SensorReader(port, baudrate=9600)` — opens the serial port (pyserial). Pass
  `port=None` / `"mock"` to stream a synthetic first-order step response instead —
  no hardware needed to test the pipeline.
  - `read_stream()` → generator of `(t_s, T_core_degC, T_disc_degC, I_rms_A)`.
  - `save_csv(filepath, duration_s=...)` → logs the stream to CSV.
  - `SensorReader.load_csv(filepath)` (static) → `(t, T_core, T_disc, I_rms)` numpy arrays.
- `calibrate_from_file(csv_path, cfg=None, rom=None, target="disc")` — averages the
  trailing `steady_window_s` of the CSV as the steady-state measurement for BOTH
  temperature and I_rms, and calls `rom.calibrate_UA(I_meas, dT_meas)` — I_meas now
  comes from the ACS712 log, not the assumed-constant `cfg.I` placeholder.
- `live_compare(sensor_reader, rom, cfg)` — matplotlib animation, measured T_core/T_disc
  vs. ROM-simulated T_disc, one sensor sample per frame; drives the ROM with the
  live-measured I_rms(t) (falls back to `cfg.I` if a sample reports NaN/≤0, e.g.
  before the ACS712 is wired up).
- `mock_sensor_data.csv` (repo root) — pre-generated mock log (4 columns, incl.
  I_rms_A ≈ 5.0±0.03A) for testing `calibrate_from_file` without hardware or a live
  stream.

CLI:
```bash
python data_io.py --mode log      --port mock --duration 120 --csv sensor_log.csv
python data_io.py --mode calibrate --csv mock_sensor_data.csv --target disc
python data_io.py --mode live      --port /dev/tty.usbmodem14101
```

### Kalibrierung (rom.py)
```python
rom.calibrate_UA(I_meas, dT_meas)
# -> aktualisiert UA (W/K) und tau = C/UA
# I_meas: jetzt aus dem ACS712-Log (Mittelwert über steady_window_s), nicht mehr
#         die feste 5A-Annahme
# dT_meas: (T_gemessen_steady_state - T_amb)
```
`k_coil_coupling_K_per_W` (params.yaml) ist weiterhin manuell zu kalibrieren — dafür
braucht es getrennte Core- und Disc-Messungen bei mehreren Strömen I, nicht nur eine
einzelne `calibrate_UA()`-Anpassung.

---

## Validierungsstrategie

1. **Steady-State Check**: Gerät bei I=5A laufen lassen bis T stabilisiert (ca. 15–20 min).
   Vergleiche T_meas mit T_sim. Erwartete ΔT_plate ≈ 3–5 K über Umgebung.

2. **Transient Check**: Gerät einschalten, T(t) aufzeichnen. Vergleiche Zeitkonstante τ
   (ROM: ~4.07 min bei R=80mm, Stand 2026-07-10) mit gemessenem Aufheizverhalten.

3. **Spatial Check**: IR Thermometer an verschiedenen Stellen der Scheibe. Vergleiche
   mit der simulierten radialen Temperaturverteilung.

---

## Kontaktlose Scheiben-Validierung: Differenzmessung MIT/OHNE Scheibe (2026-07-02)

Idee (User): statt einen Sensor an der levitierenden Scheibe zu befestigen, eine
Größe an der QUELLE messen, die sich ändert, wenn die Scheibe aufgelegt wird —
die Wirbelströme der Scheibe reflektieren eine Impedanz in den Spulenkreis.

EM-Solver-Vorhersage (Impedanz aus komplexer Quellenleistung, Skript
`disc_impedance_prediction.py`, Scratch — Ansatz: Z = 2S/î², S = ½jω∫A·J_s dV):

| Größe | MIT Scheibe | OHNE Scheibe | Δ |
|---|---|---|---|
| Z_total | 11.03 + j27.29 Ω | 10.25 + j27.71 Ω | ΔR=+0.77 Ω, ΔL=−1.33 mH |
| I bei V=190 V fest | 6.455 A | 6.431 A | **+0.024 A — NICHT messbar** |
| P_wirk bei I=5 A_rms | 275.7 W | 256.3 W | **+19.4 W (+7.6%) — messbar** |
| cos φ | 0.375 | 0.347 | +0.028 |

- **Amperemeter allein reicht NICHT**: ΔR (Scheibe frisst Leistung, +0.77 Ω) und
  ΔL (Wirbelstrom-Abschirmung senkt Induktivität, −1.33 mH → X sinkt) heben sich
  in |Z| fast exakt auf → ΔI ≈ 0.02 A (~0.4%), unter der Ablesegenauigkeit.
- **Wirkleistungsmessung funktioniert**: ΔP ≈ 19 W bei gleichem Strom = direkt
  P_plate (physikalische Konvention, = 2× der 9.67 W in Solver-Konvention).
  Benötigt ein ECHTES Wattmeter / Energiekosten-Messgerät (cos φ ≈ 0.37 —
  V·I=950 VA ist NICHT die Wirkleistung!). → Einkaufsliste: Steckdosen-
  Leistungsmesser mit Wirkleistungsanzeige (~15–25 €), am Variac-EINGANG
  (240V-Seite) messen geht auch (Variac-Eigenverlust als Offset, kürzt sich
  in der MIT/OHNE-Differenz heraus).
- **Bonus-Befund (Modell-Check)**: |Z|_Modell = 29.4 Ω vs gemessen 190V/5A = 38 Ω
  (−23%). Modell-Impedanz zu klein — Kandidaten: AC-Widerstand der Wicklung
  (Skin/Proximity, Modell nutzt DC-R), Zuleitungen, ODER Separatorring doch
  ferromagnetisch (μ_r>1 → L größer). Eine simple V+I-Messung OHNE Scheibe
  trennt R- von L-Anteil (mit Wattmeter: R=P/I², X=√(|Z|²−R²)) und testet damit
  auch die offene μ_r-Frage des Rings — ganz ohne Magnettest.
- Scheibentausch Ø160→Ø202: ΔP nur ~4 W Unterschied → grenzwertig; die
  MIT/OHNE-Differenz (19 W) ist das robustere Experiment.
- Ergänzend, billigste Sofortmaßnahme fürs IR-Problem: **mattschwarzes
  Isolierband / Kaminlack-Punkt** auf die Scheibenunterseite (ε≈0.95 bekannt)
  → HIKMICRO-Ablesung wird vertrauenswürdig, ohne Kabel, Levitation ungestört.

---

## Offene Fragen

- [ ] Wo genau wird der Thermocouple an der Scheibe befestigt? (Unterseite Mitte vs. Rand)
- [ ] Ist die Scheibe während der Messung in Levitation? (Thermocouple-Kabel könnte stören)
- [ ] Reichelt oder Conrad — welcher Lieferant bevorzugt? (Professor klären)
- [ ] Soll auch die Spulentemperatur gemessen werden? (aktuell nicht im Plan)
