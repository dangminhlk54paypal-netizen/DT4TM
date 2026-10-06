"""data_io.py — Sensor data bridge: Arduino (ACS712 current sensor) -> the twin.

Pipeline:
  Arduino (arduino/thermal_sensor/thermal_sensor.ino) measures the coil's RMS current
  with an ACS712-20A Hall-effect sensor (see docs/archive/Stromsensor_.docx) and prints
  CSV lines over serial at 1 Hz:
      "millis,I_rms_A\n"
  data_io.py reads that stream (or a saved CSV, or a synthetic "mock" source when no
  hardware is connected) and drives the digital twin with the MEASURED current instead
  of the assumed-constant params.yaml excitation.current_A. Current is the twin's
  INPUT; the temperature field is what the model computes FROM it (--mode live).

  The rig has no temperature sensor. calibrate_from_file() fits UA from a measured
  TEMPERATURE, so it needs a log that actually contains one — mock_sensor_data.csv, or
  a 4-column "millis,T_core,T_disc,I_rms" log recorded with thermocouples attached.
  Both wire formats are accepted; the 2-column one simply reports temperature as NaN.

No hardware is required to exercise this file: pass --port mock (the default) to stream
a synthetic first-order step response, or point --csv at mock_sensor_data.csv.

Ambient temperature: a REAL log (--mode log on a serial port) also records the lab
ambient from the Google Weather API (weather_api.py) at start and every
params.yaml weather_api.log_refresh_s, as the columns T_amb_degC/T_amb_source.
calibrate_from_file() then measures the rise above THAT ambient instead of the
constant 20 °C. Without a live reading (mock, no key, key expired, offline) the
column holds the params.yaml fallback thermal_bc.T_ambient_degC.
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

from weather_api import describe as weather_describe

# The real rig streams 2 columns, "millis,I_rms_A": it measures current only —
# current is the twin's INPUT, temperature its OUTPUT, and the device carries no
# temperature sensor (arduino/thermal_sensor/thermal_sensor.ino). The 4-column
# form "millis,T_core,T_disc,I_rms" is still accepted, for mock_sensor_data.csv
# and for any log recorded with thermocouples attached.
_LINE_RE_I = re.compile(r"^\s*(-?\d+)\s*,\s*([^,]+)\s*$")
_LINE_RE_TI = re.compile(r"^\s*(-?\d+)\s*,\s*([^,]+)\s*,\s*([^,]+)\s*,\s*([^,]+)\s*$")
# Bare "I_rms_A" (one number per line, no millis) — the firmware's debug/plotter
# variant. Timestamped with the PC's clock on arrival instead of the Arduino's.
_LINE_RE_BARE = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|nan)\s*$", re.I)


# ---------------------------------------------------------------------------
# SensorReader — serial bridge to the Arduino (or a mock source)
# ---------------------------------------------------------------------------
class SensorReader:
    """Streams (t_s, T_core_degC, T_disc_degC, I_rms_A) from the Arduino over serial.

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
        """Generator yielding (t_s, T_core_degC, T_disc_degC, I_rms_A). Blocks for new samples.

        t_s is seconds since the first sample (not wall-clock time). Lines that are
        comments ("#...") or malformed are skipped with a printed warning rather than
        raising.

        Accepts both wire formats (see _LINE_RE_I / _LINE_RE_TI): the rig's 2-column
        "millis,I_rms_A" — the device measures current only — and the legacy/mock
        4-column "millis,T_core,T_disc,I_rms". The tuple shape is the same either
        way; the temperatures are simply NaN when the rig does not measure them.
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
            m = _LINE_RE_TI.match(line)
            mb = None if m else _LINE_RE_BARE.match(line)
            if m:
                ms_str, t1_str, t2_str, t3_str = m.groups()
            elif mb:
                ms_str, t3_str = str(int(time.monotonic() * 1000)), mb.group(1)
                t1_str = t2_str = "nan"
            else:
                m = _LINE_RE_I.match(line)
                if not m:
                    print(f"[SensorReader] skipping malformed line: {line!r}")
                    continue
                ms_str, t3_str = m.groups()
                t1_str = t2_str = "nan"
            try:
                T_core, T_disc, I_rms = float(t1_str), float(t2_str), float(t3_str)
            except ValueError:
                print(f"[SensorReader] skipping unparsable line: {line!r}")
                continue
            if math.isnan(I_rms):
                print(f"[SensorReader] skipping line with no valid current: {line!r}")
                continue
            if t0_ms is None:
                t0_ms = int(ms_str)
            yield (int(ms_str) - t0_ms) / 1000.0, T_core, T_disc, I_rms

    def _mock_stream(self):
        """Synthetic first-order step response, standing in for the real rig.

        Core (near the coils, P_coil dominates losses) heats faster and further
        than the disc (larger thermal mass, only eddy + coupled hot-air heating).
        I_rms mocks a Variac held at the 5A_rms operating point with sensor noise.

        NOTE: Hard-coded constants below are for TESTING ONLY. They do not read from
        params.yaml and do not match the current calibrated lumped_thermal values
        (hA_inner/hA_outer/coil_C_scale). This mock stream is used to test the
        data_io.py → rom.calibrate_UA() pipeline without needing the real hardware.
        For validation against actual measured data, use a real CSV from the Arduino
        sensor (see SENSOR_PLAN.md) or calibrate_from_file(csv_path).
        """
        T_amb, dT_core_ss, dT_disc_ss = 20.0, 25.0, 11.46  # Arbitrary test values
        tau_core_s, tau_disc_s = 300.0, 632.0  # Arbitrary test time constants [s]
        I_rms_mean = 5.0  # Arbitrary test value: mocks the 190V->5A_rms operating point
        t = 0.0
        while True:
            T_core = T_amb + dT_core_ss * (1 - math.exp(-t / tau_core_s)) + random.gauss(0, 0.15)
            T_disc = T_amb + dT_disc_ss * (1 - math.exp(-t / tau_disc_s)) + random.gauss(0, 0.15)
            I_rms = I_rms_mean + random.gauss(0, 0.03)
            yield t, T_core, T_disc, I_rms
            time.sleep(1.0 / self.mock_speed)  # wall-clock pacing only; t still advances 1s/sample
            t += 1.0

    # ------------------------------------------------------------------
    def save_csv(self, filepath: str, duration_s: float | None = None,
                 max_samples: int | None = None, ambient_fn=None,
                 refresh_s: float = 600.0) -> int:
        """Stream sensor data to a CSV file. Stops after duration_s or max_samples
        (whichever first), or never (Ctrl+C) if both are None. Returns sample count.

        ambient_fn() -> weather_api.ambient_now()-style dict; called at start and
        then every refresh_s (wall clock), its value written into every row. None
        -> the T_amb columns stay empty (NaN on load)."""
        n = 0
        amb, next_amb = None, 0.0
        with open(filepath, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_s", "T_core_degC", "T_disc_degC", "I_rms_A",
                        "T_amb_degC", "T_amb_source"])
            print(f"[SensorReader] logging to {filepath} ... (Ctrl+C to stop)")
            try:
                for t, T_core, T_disc, I_rms in self.read_stream():
                    if ambient_fn is not None and time.monotonic() >= next_amb:
                        amb = ambient_fn()
                        next_amb = time.monotonic() + refresh_s
                        print(f"  [weather] {weather_describe(amb)}")
                    amb_cols = ["", ""] if amb is None else \
                        [f"{amb['T_amb_degC']:.2f}", amb["source"]]
                    w.writerow([f"{t:.2f}", f"{T_core:.2f}", f"{T_disc:.2f}", f"{I_rms:.3f}",
                                *amb_cols])
                    f.flush()
                    n += 1
                    if n % 10 == 0:
                        print(f"  t={t:6.1f}s  T_core={T_core:6.2f}°C  T_disc={T_disc:6.2f}°C  I_rms={I_rms:5.2f}A")
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
        """Load a CSV written by save_csv(). Returns (t_s, T_core_degC, T_disc_degC, I_rms_A) arrays."""
        t, T_core, T_disc, I_rms = [], [], [], []
        with open(filepath, newline="") as f:
            reader = csv.reader(f)
            next(reader)  # header
            for row in reader:
                if not row:
                    continue
                t.append(float(row[0]))
                T_core.append(float(row[1]))
                T_disc.append(float(row[2]))
                I_rms.append(float(row[3]))
        return np.array(t), np.array(T_core), np.array(T_disc), np.array(I_rms)

    @staticmethod
    def load_ambient(filepath: str) -> np.ndarray:
        """The logged T_amb_degC column of a save_csv() file, one value per row;
        NaN where empty or for older 4-column logs (e.g. mock_sensor_data.csv)."""
        out = []
        with open(filepath, newline="") as f:
            reader = csv.reader(f)
            next(reader)
            for row in reader:
                if not row:
                    continue
                try:
                    out.append(float(row[4]))
                except (IndexError, ValueError):
                    out.append(math.nan)
        return np.array(out)


# ---------------------------------------------------------------------------
# Calibration — feed a logged CSV into ThermalROM.calibrate_UA()
# ---------------------------------------------------------------------------
def calibrate_from_file(csv_path: str, cfg=None, rom=None, target: str = "disc",
                         steady_window_s: float = 120.0) -> dict:
    """Calibrate ThermalROM.UA from a logged sensor CSV.

    Takes the mean of the last `steady_window_s` of the recording as the
    steady-state measurement, for both temperature and current — I_meas now comes
    from the ACS712 current sensor log (see docs/archive/Stromsensor_.docx), not
    the assumed-constant cfg.I placeholder.

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

    t, T_core, T_disc, I_rms = SensorReader.load_csv(csv_path)
    T_meas = T_disc if target == "disc" else T_core

    window = t >= (t[-1] - steady_window_s)
    if not window.any():
        window = np.ones_like(t, dtype=bool)
    if not np.isfinite(T_meas[window]).any():
        raise ValueError(
            f"{csv_path!r} has no valid '{target}' temperature in the last "
            f"{steady_window_s:.0f}s — UA is fitted from a measured TEMPERATURE, so a "
            f"current-only log cannot calibrate it. The rig measures current only "
            f"(the twin's input); calibration needs a log with thermocouple data."
        )
    T_ss = float(T_meas[window].mean())
    # Rise above the ambient RECORDED during the run (weather API), if the log
    # has one; otherwise the constant params.yaml ambient the ROM was built at.
    T_amb_log = SensorReader.load_ambient(csv_path)[window]
    if np.isfinite(T_amb_log).any():
        T_amb, amb_src = float(np.nanmean(T_amb_log)), "logged"
    else:
        T_amb, amb_src = float(rom.T_amb), "params.yaml"
    dT_meas = T_ss - T_amb

    I_meas = float(I_rms[window].mean())
    UA = rom.calibrate_UA(I_meas=I_meas, dT_meas=dT_meas)

    result = {
        "target": target, "T_ss_degC": T_ss, "T_amb_degC": T_amb, "T_amb_source": amb_src,
        "dT_meas_K": dT_meas, "I_meas_A": I_meas,
        "UA_W_per_K": UA, "tau_s": rom.tau, "C_J_per_K": rom.C,
    }
    print(f"[calibrate_from_file] target={target}  T_ss={T_ss:.2f}°C  "
          f"T_amb={T_amb:.2f}°C ({amb_src})  dT={dT_meas:.2f}K  "
          f"I={I_meas:.1f}A  ->  UA={UA:.4f} W/K  τ={rom.tau:.0f}s ({rom.tau/60:.1f} min)")
    return result


# ---------------------------------------------------------------------------
# Live comparison — measured T vs. ROM-simulated T
# ---------------------------------------------------------------------------
def live_compare(sensor_reader: SensorReader, rom, cfg=None, em=None,
                  I_const: float | None = None, t_window_s: float = 600.0,
                  T_amb: float | None = None):
    """Live plot: measured T_core/T_disc vs. ROM-simulated T_disc, sample by sample.

    Drives the ROM forward by the ACS712-measured I_rms(t) at the Δt between
    incoming sensor samples (falls back to I_const, default cfg.I, if a sample
    reports NaN/non-positive current — e.g. before the sensor is wired up). One
    sensor sample is pulled per animation frame, so the plot updates at the
    Arduino's ~1 Hz rate (or --mock-speed for the mock source). Close the window
    or Ctrl+C to stop.
    """
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    from twin_core import TwinState
    from twin_model import coeffs_from_live

    if cfg is None:
        from config import load_config
        cfg = load_config()
    if em is None:
        from em_solver import compute_losses
        em = compute_losses(cfg)
    I_const = float(I_const if I_const is not None else cfg.I)

    rom_c, lumped_c, lev_c = coeffs_from_live(cfg, em, rom)
    T_amb = float(T_amb if T_amb is not None else rom_c.T_amb)   # live weather or 20 °C
    twin = TwinState(rom=rom_c, lumped=lumped_c, lev=lev_c, T_amb=T_amb)
    stream = sensor_reader.read_stream()
    hist = {"t": [], "T_core": [], "T_disc": [], "T_sim": []}
    t_prev = [0.0]

    fig, ax = plt.subplots(figsize=(9, 5))
    fig.suptitle(f"Live sensor vs. ROM  (I={I_const:.1f}A, τ={rom.tau/60:.1f} min, "
                 f"T_amb={T_amb:.1f}°C)")
    line_core, = ax.plot([], [], "o-", ms=3, color="#ff6644", label="T_core (measured)")
    line_disc, = ax.plot([], [], "o-", ms=3, color="#4488ff", label="T_disc (measured)")
    line_sim,  = ax.plot([], [], "--", color="#44ff88", lw=2, label="T_disc (ROM)")
    ax.set_xlabel("Time (min)"); ax.set_ylabel("Temperature (°C)")
    ax.legend(fontsize=9); ax.grid(alpha=0.3)

    def update(_frame):
        try:
            t, T_core, T_disc, I_rms = next(stream)
        except StopIteration:
            return
        dt = max(t - t_prev[0], 0.0)
        t_prev[0] = t
        I_drive = I_rms if (I_rms is not None and I_rms > 0 and not math.isnan(I_rms)) else I_const
        if dt > 0:
            twin.step(I_drive, dt)

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
    from weather_api import ambient_now
    cfg = load_config()
    HERE = os.path.dirname(os.path.abspath(__file__))
    T_amb_fallback = float(cfg.bc["T_ambient_degC"])
    is_mock = str(args.port).lower() == "mock"

    def ambient_fn():
        """Real rig -> live weather (or fallback); mock -> always the fallback,
        since the mock's temperatures are synthetic around 20 °C anyway."""
        if is_mock:
            return {"T_amb_degC": T_amb_fallback, "source": "fallback",
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": "mock"}
        return ambient_now(T_amb_fallback, cfg.raw)

    if args.mode == "calibrate":
        csv_path = args.csv or os.path.join(HERE, "mock_sensor_data.csv")
        calibrate_from_file(csv_path, cfg=cfg, target=args.target)

    elif args.mode == "log":
        csv_path = args.csv or os.path.join(HERE, "sensor_log.csv")
        refresh_s = float(cfg.raw.get("weather_api", {}).get("log_refresh_s", 600.0))
        with SensorReader(args.port, args.baud) as sr:
            sr.save_csv(csv_path, duration_s=args.duration, ambient_fn=ambient_fn,
                        refresh_s=refresh_s)

    elif args.mode == "live":
        from em_solver import compute_losses
        from rom import ThermalROM
        print(f"[EM] Solving at î={cfg.I}A... ", end="", flush=True)
        em = compute_losses(cfg)
        print(f"P_plate={em['P_plate_W']*1e3:.1f} mW  P_coil={em['P_coil_W']:.1f}W")
        rom = ThermalROM().build(cfg, em_losses=em, verbose=True)
        amb = ambient_fn()
        print(f"[weather] {weather_describe(amb)}")
        with SensorReader(args.port, args.baud) as sr:
            live_compare(sr, rom, cfg=cfg, em=em, T_amb=amb["T_amb_degC"])
