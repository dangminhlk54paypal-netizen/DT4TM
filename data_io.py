"""data_io.py — Sensor data bridge: Arduino (MAX31855 thermocouples) -> ThermalROM.

Pipeline:
  Arduino (arduino/thermal_sensor/thermal_sensor.ino) reads two Type-K thermocouples
  (copper core, disc bottom) and prints CSV lines over serial at 1 Hz:
      "millis,T_core_degC,T_disc_degC\n"
  data_io.py reads that stream (or a saved CSV, or a synthetic "mock" source when no
  hardware is connected), logs it, and feeds steady-state (I_meas, dT_meas) pairs into
  rom.ThermalROM.calibrate_UA() to fit the lumped heat-transfer coefficient UA.

No hardware is required to exercise this file: pass --port mock (the default) to stream
a synthetic first-order step response, or point --csv at mock_sensor_data.csv.
"""
from __future__ import annotations
import csv
import math
import os
import random
import re
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_LINE_RE = re.compile(r"^\s*(-?\d+)\s*,\s*([^,]+)\s*,\s*([^,]+)\s*$")


# ---------------------------------------------------------------------------
# SensorReader — serial bridge to the Arduino (or a mock source)
# ---------------------------------------------------------------------------
class SensorReader:
    """Streams (t_s, T_core_degC, T_disc_degC) from the Arduino over serial.

    Pass port=None or port="mock" to use a synthetic source (first-order step
    response with noise) instead of real hardware — useful for testing the
    pipeline before the sensors arrive.
    """

    def __init__(self, port: str | None, baudrate: int = 9600, timeout: float = 2.0,
                 mock_speed: float = 20.0):
        self.port = port
        self.mock_speed = mock_speed
        self._ser = None
        self._mock = port is None or str(port).lower() == "mock"

        if self._mock:
            return

        try:
            import serial
        except ImportError as e:
            raise ImportError(
                "pyserial not installed — run: pip install pyserial "
                "(or pass --port mock to test without hardware)"
            ) from e
        try:
            self._ser = serial.Serial(port, baudrate, timeout=timeout)
        except serial.SerialException as e:
            raise ConnectionError(
                f"Could not open serial port '{port}': {e}. Check the Arduino is "
                f"plugged in and the port name (macOS: `ls /dev/tty.usb*`)."
            ) from e
        time.sleep(2.0)  # Arduino resets on a new serial connection; let it boot.

    def __enter__(self) -> "SensorReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._ser is not None and self._ser.is_open:
            self._ser.close()

    # ------------------------------------------------------------------
    def read_stream(self):
        """Generator yielding (t_s, T_core_degC, T_disc_degC). Blocks for new samples.

        t_s is seconds since the first sample (not wall-clock time). Lines that are
        comments ("#..."), malformed, or report a thermocouple fault (NaN) are
        skipped with a printed warning rather than raising.
        """
        if self._mock:
            yield from self._mock_stream()
            return

        import serial
        t0_ms = None
        while True:
            try:
                raw = self._ser.readline()
            except serial.SerialException as e:
                raise ConnectionError(f"Lost serial connection to '{self.port}': {e}") from e
            if not raw:
                continue  # read timeout, no line yet
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line or line.startswith("#"):
                continue
            m = _LINE_RE.match(line)
            if not m:
                print(f"[SensorReader] skipping malformed line: {line!r}")
                continue
            ms_str, t1_str, t2_str = m.groups()
            try:
                T_core, T_disc = float(t1_str), float(t2_str)
            except ValueError:
                print(f"[SensorReader] skipping unparsable line: {line!r}")
                continue
            if math.isnan(T_core) or math.isnan(T_disc):
                print(f"[SensorReader] thermocouple fault reported: {line!r}")
                continue
            if t0_ms is None:
                t0_ms = int(ms_str)
            yield (int(ms_str) - t0_ms) / 1000.0, T_core, T_disc

    def _mock_stream(self):
        """Synthetic first-order step response, standing in for the real rig.

        Core (near the coils, P_coil dominates losses) heats faster and further
        than the disc (larger thermal mass, only eddy + coupled hot-air heating).
        """
        T_amb, dT_core_ss, dT_disc_ss = 20.0, 25.0, 11.46
        tau_core_s, tau_disc_s = 300.0, 632.0
        t = 0.0
        while True:
            T_core = T_amb + dT_core_ss * (1 - math.exp(-t / tau_core_s)) + random.gauss(0, 0.15)
            T_disc = T_amb + dT_disc_ss * (1 - math.exp(-t / tau_disc_s)) + random.gauss(0, 0.15)
            yield t, T_core, T_disc
            time.sleep(1.0 / self.mock_speed)  # wall-clock pacing only; t still advances 1s/sample
            t += 1.0

    # ------------------------------------------------------------------
    def save_csv(self, filepath: str, duration_s: float | None = None,
                 max_samples: int | None = None) -> int:
        """Stream sensor data to a CSV file. Stops after duration_s or max_samples
        (whichever first), or never (Ctrl+C) if both are None. Returns sample count."""
        n = 0
        with open(filepath, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_s", "T_core_degC", "T_disc_degC"])
            print(f"[SensorReader] logging to {filepath} ... (Ctrl+C to stop)")
            try:
                for t, T_core, T_disc in self.read_stream():
                    w.writerow([f"{t:.2f}", f"{T_core:.2f}", f"{T_disc:.2f}"])
                    f.flush()
                    n += 1
                    if n % 10 == 0:
                        print(f"  t={t:6.1f}s  T_core={T_core:6.2f}°C  T_disc={T_disc:6.2f}°C")
                    if duration_s is not None and t >= duration_s:
                        break
                    if max_samples is not None and n >= max_samples:
                        break
            except KeyboardInterrupt:
                print(f"\n[SensorReader] stopped by user after {n} samples.")
        print(f"[SensorReader] saved {n} samples -> {filepath}")
        return n

    @staticmethod
    def load_csv(filepath: str):
        """Load a CSV written by save_csv(). Returns (t_s, T_core_degC, T_disc_degC) arrays."""
        t, T_core, T_disc = [], [], []
        with open(filepath, newline="") as f:
            reader = csv.reader(f)
            next(reader)  # header
            for row in reader:
                if not row:
                    continue
                t.append(float(row[0]))
                T_core.append(float(row[1]))
                T_disc.append(float(row[2]))
        return np.array(t), np.array(T_core), np.array(T_disc)


# ---------------------------------------------------------------------------
# Calibration — feed a logged CSV into ThermalROM.calibrate_UA()
# ---------------------------------------------------------------------------
def calibrate_from_file(csv_path: str, cfg=None, rom=None, target: str = "disc",
                         steady_window_s: float = 120.0) -> dict:
    """Calibrate ThermalROM.UA from a logged sensor CSV.

    Takes the mean of the last `steady_window_s` of the recording as the
    steady-state measurement (assumes I was held constant until then — no
    real-time current sensor yet, see CLAUDE.md, so I_meas = cfg.I).

    Args:
        csv_path:         Path to a CSV from SensorReader.save_csv().
        cfg:              Config (loads params.yaml if None).
        rom:              Pre-built ThermalROM (built fresh via EM+thermal if None).
        target:           "disc" or "core" — which sensor to calibrate against.
        steady_window_s:  Trailing window [s] averaged for the steady-state value.

    Returns:
        dict with T_ss_degC, dT_meas_K, I_meas_A, UA_W_per_K, tau_s, C_J_per_K.
    """
    from config import load_config
    from rom import ThermalROM

    if cfg is None:
        cfg = load_config()
    if rom is None:
        from em_solver import compute_losses
        em = compute_losses(cfg)
        rom = ThermalROM().build(cfg, em_losses=em, verbose=False)

    t, T_core, T_disc = SensorReader.load_csv(csv_path)
    T_meas = T_disc if target == "disc" else T_core

    window = t >= (t[-1] - steady_window_s)
    if not window.any():
        window = np.ones_like(t, dtype=bool)
    T_ss = float(T_meas[window].mean())
    dT_meas = T_ss - rom.T_amb

    I_meas = cfg.I  # measured constant 220V->5A at the rig; no live current sensor yet
    UA = rom.calibrate_UA(I_meas=I_meas, dT_meas=dT_meas)

    result = {
        "target": target, "T_ss_degC": T_ss, "dT_meas_K": dT_meas, "I_meas_A": I_meas,
        "UA_W_per_K": UA, "tau_s": rom.tau, "C_J_per_K": rom.C,
    }
    print(f"[calibrate_from_file] target={target}  T_ss={T_ss:.2f}°C  dT={dT_meas:.2f}K  "
          f"I={I_meas:.1f}A  ->  UA={UA:.4f} W/K  τ={rom.tau:.0f}s ({rom.tau/60:.1f} min)")
    return result


# ---------------------------------------------------------------------------
# Live comparison — measured T vs. ROM-simulated T
# ---------------------------------------------------------------------------
def live_compare(sensor_reader: SensorReader, rom, cfg=None, I_const: float | None = None,
                  t_window_s: float = 600.0):
    """Live plot: measured T_core/T_disc vs. ROM-simulated T_disc, sample by sample.

    Drives the ROM forward by I_const [A] (constant — no current sensor yet) at the
    Δt between incoming sensor samples. One sensor sample is pulled per animation
    frame, so the plot updates at the Arduino's ~1 Hz rate (or --mock-speed for the
    mock source). Close the window or Ctrl+C to stop.
    """
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    from digital_twin import DigitalTwin

    if cfg is None:
        from config import load_config
        cfg = load_config()
    I_const = float(I_const if I_const is not None else cfg.I)

    twin = DigitalTwin(rom)
    stream = sensor_reader.read_stream()
    hist = {"t": [], "T_core": [], "T_disc": [], "T_sim": []}
    t_prev = [0.0]

    fig, ax = plt.subplots(figsize=(9, 5))
    fig.suptitle(f"Live sensor vs. ROM  (I={I_const:.1f}A, τ={rom.tau/60:.1f} min)")
    line_core, = ax.plot([], [], "o-", ms=3, color="#ff6644", label="T_core (measured)")
    line_disc, = ax.plot([], [], "o-", ms=3, color="#4488ff", label="T_disc (measured)")
    line_sim,  = ax.plot([], [], "--", color="#44ff88", lw=2, label="T_disc (ROM)")
    ax.set_xlabel("Time (min)"); ax.set_ylabel("Temperature (°C)")
    ax.legend(fontsize=9); ax.grid(alpha=0.3)

    def update(_frame):
        try:
            t, T_core, T_disc = next(stream)
        except StopIteration:
            return
        dt = max(t - t_prev[0], 0.0)
        t_prev[0] = t
        if dt > 0:
            twin.step(I_const, dt)

        hist["t"].append(t / 60.0)
        hist["T_core"].append(T_core)
        hist["T_disc"].append(T_disc)
        hist["T_sim"].append(float(twin.T_field.mean()))

        line_core.set_data(hist["t"], hist["T_core"])
        line_disc.set_data(hist["t"], hist["T_disc"])
        line_sim.set_data(hist["t"], hist["T_sim"])

        x_hi = max(hist["t"][-1], t_window_s / 60.0)
        x_lo = max(0.0, x_hi - t_window_s / 60.0)
        ax.set_xlim(x_lo, x_hi)
        y_all = hist["T_core"] + hist["T_disc"] + hist["T_sim"]
        ax.set_ylim(min(y_all) - 1, max(y_all) + 1)

    # Pulling next(stream) inside update() blocks the GUI for up to one sample
    # period (~1s real hardware, faster for mock) -- acceptable at this sample
    # rate and keeps the loop free of an extra reader thread.
    ani = FuncAnimation(fig, update, interval=200, cache_frame_data=False)
    plt.show()
    return ani


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Sensor data I/O — Arduino thermocouple bridge")
    p.add_argument("--port", default="mock",
                   help="Serial port (e.g. /dev/tty.usbmodem14101, COM3). "
                        "Default 'mock' streams synthetic data, no hardware needed.")
    p.add_argument("--baud", type=int, default=9600)
    p.add_argument("--csv", default=None, help="CSV path to write (log) or read (calibrate)")
    p.add_argument("--mode", choices=["log", "calibrate", "live"], default="log",
                   help="log: stream sensor->CSV | calibrate: fit UA from CSV | live: live compare plot")
    p.add_argument("--duration", type=float, default=120.0, help="Logging duration [s] (mode=log)")
    p.add_argument("--target", choices=["core", "disc"], default="disc",
                   help="Which sensor to calibrate against (mode=calibrate)")
    args = p.parse_args()

    from config import load_config
    cfg = load_config()
    HERE = os.path.dirname(os.path.abspath(__file__))

    if args.mode == "calibrate":
        csv_path = args.csv or os.path.join(HERE, "mock_sensor_data.csv")
        calibrate_from_file(csv_path, cfg=cfg, target=args.target)

    elif args.mode == "log":
        csv_path = args.csv or os.path.join(HERE, "sensor_log.csv")
        with SensorReader(args.port, args.baud) as sr:
            sr.save_csv(csv_path, duration_s=args.duration)

    elif args.mode == "live":
        from em_solver import compute_losses
        from rom import ThermalROM
        print(f"[EM] Solving at î={cfg.I}A... ", end="", flush=True)
        em = compute_losses(cfg)
        print(f"P_plate={em['P_plate_W']*1e3:.1f} mW  P_coil={em['P_coil_W']:.1f}W")
        rom = ThermalROM().build(cfg, em_losses=em, verbose=True)
        with SensorReader(args.port, args.baud) as sr:
            live_compare(sr, rom, cfg=cfg)
