# SENSOR_PLAN — Thermal Validation Hardware

> Last updated: 2026-06-22. Professor feedback Juni 2026.
> "Schaut was es genau bräuchte und baut dann selbst eine kleine Lösung.
>  Arduino plus ein paar Sensoren... und dann einfach noch ein Infrarot Thermometer."

---

## Ziel

Temperatur an zwei Stellen messen, um die Simulation zu validieren:
1. **Kupferkern** (copper core) — Thermocouple/RTD am Kern befestigt
2. **Unterseite der Scheibe** (bottom of levitating disc) — IR Thermometer / Thermocouple

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

## Software-Pipeline (implemented)

### Arduino Firmware
`arduino/thermal_sensor/thermal_sensor.ino` — Adafruit MAX31855 library, hardware SPI,
CS pins D10 (core) / D9 (disc). Every 1s prints:
```
millis,T_core_degC,T_disc_degC
```
On a thermocouple fault the affected field is "nan" and a `# FAULT ...` line precedes
it; both are skipped by the Python parser. Baudrate 9600.

### Python `data_io.py`
- `SensorReader(port, baudrate=9600)` — opens the serial port (pyserial). Pass
  `port=None` / `"mock"` to stream a synthetic first-order step response instead —
  no hardware needed to test the pipeline.
  - `read_stream()` → generator of `(t_s, T_core_degC, T_disc_degC)`.
  - `save_csv(filepath, duration_s=...)` → logs the stream to CSV.
  - `SensorReader.load_csv(filepath)` (static) → `(t, T_core, T_disc)` numpy arrays.
- `calibrate_from_file(csv_path, cfg=None, rom=None, target="disc")` — averages the
  trailing `steady_window_s` of the CSV as the steady-state measurement and calls
  `rom.calibrate_UA(I_meas, dT_meas)`.
- `live_compare(sensor_reader, rom, cfg)` — matplotlib animation, measured T_core/T_disc
  vs. ROM-simulated T_disc, one sensor sample per frame.
- `mock_sensor_data.csv` (repo root) — pre-generated mock log for testing `calibrate_from_file`
  without hardware or a live stream.

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
# I_meas: konstant 5A (kein Echtzeit-Stromsensor, siehe CLAUDE.md)
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
   (ROM: ~3.4 min) mit gemessenem Aufheizverhalten.

3. **Spatial Check**: IR Thermometer an verschiedenen Stellen der Scheibe. Vergleiche
   mit der simulierten radialen Temperaturverteilung.

---

## Offene Fragen

- [ ] Wo genau wird der Thermocouple an der Scheibe befestigt? (Unterseite Mitte vs. Rand)
- [ ] Ist die Scheibe während der Messung in Levitation? (Thermocouple-Kabel könnte stören)
- [ ] Reichelt oder Conrad — welcher Lieferant bevorzugt? (Professor klären)
- [ ] Soll auch die Spulentemperatur gemessen werden? (aktuell nicht im Plan)
