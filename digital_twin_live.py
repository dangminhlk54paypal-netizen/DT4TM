"""digital_twin_live.py — OPTIONAL live-sensor mode: the twin driven by the MEASURED current.

A separate entry point, NOT part of the normal run. digital_twin.py and the HTML
twin are untouched and keep running on their sliders/scenarios; this script is the
feature to switch on once the ACS712 current sensor is wired into the rig.

    Arduino (thermal_sensor.ino, "millis,I_rms_A" @1Hz)
        -> data_io.SensorReader   (serial, or mock / replay without hardware)
        -> reader thread -> queue
        -> LiveDriver.push(t, I)  -> twin_core.TwinState.step(I, dt)
        -> T_inner / T_outer / T_iron / T_disc  (model OUTPUT — the rig has no T sensor)

The physics is exactly the shared TwinState (no second copy); only the SOURCE of I
changes. I_rms goes in as-is: the loss chain is calibrated on the multimeter's RMS
value (CLAUDE.md "CURRENT CONVENTION"), which is what the ACS712 firmware reports.

Input handling (LiveDriver):
  - Zero-order hold: the interval (t_{k-1}, t_k] is driven by the PREVIOUS sample's I.
    A 1 s input delay is thermally irrelevant (tau is minutes) and it lets a gap be
    bridged the same way as a normal step.
  - Zero offset (auto): for the first live_sensor.zero_cal_s seconds (Variac at 0!)
    the raw readings are collected and the model gets I=0; their RMS is the board's
    zero-current offset I0 (differs per Arduino: 0.248 A R4 Minima, ~0.345 A R4 WiFi).
    Afterwards every sample is corrected by live_sensor.zero_offset_mode:
    linear I = max(0, I_raw - I0) (default) or quadrature sqrt(max(0, I_raw^2 - I0^2)).
    An I0 above zero_cal_max_A means current was flowing -> rejected, and the
    board's default (live_sensor.board_offsets, matched by USB VID:PID) is used
    instead -- the offset differs per Arduino. "Re-zero" in the window repeats it.
    The raw value stays in the log (I_meas).
  - Dead-band: I < live_sensor.deadband_A -> 0 (applied after the offset correction).
  - Over-range: I > live_i_max_for(cfg) (= rig I_max + live_sensor.clamp_headroom_A)
    is clamped and flagged.
  - dt > max_gap_s: still integrated with the last I, but flagged "gap".
  - dt <= 0 (Arduino reset -> millis restarts): resync, no step, flagged "resync".
  - No sample for stale_after_s (wall clock): status turns STALE, the model holds.

Ambient (twin.T_amb): real serial port -> the live Google Weather reading
(weather_api.py), fetched at start and refreshed every weather_api.log_refresh_s
by a background thread; replay -> the T_amb_degC the log recorded; mock / no key
/ key expired / offline -> params.yaml thermal_bc.T_ambient_degC (20 °C). The
value in use is recorded in every exported CSV row (T_amb_degC, T_amb_source).

Run (from the repo root):
    python digital_twin_live.py                              # mock source, no hardware
    python digital_twin_live.py --port /dev/cu.usbmodem14101 # real Arduino
    python digital_twin_live.py --replay sensor_log.csv      # replay a data_io.py --mode log file
    python digital_twin_live.py --self-check                 # logic tests, no config/matplotlib/serial
"""
from __future__ import annotations
import csv
import math
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from twin_core import TwinState

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# LiveDriver — sensor samples -> TwinState steps (no GUI, no serial: testable)
# ---------------------------------------------------------------------------
@dataclass
class LiveDriver:
    twin: TwinState
    I_max: float
    deadband_A: float
    max_gap_s: float
    invalid_above_A: float = 20.0   # readings above this are not a current -> ignored
    n_invalid: int = 0
    zero_cal_s: float = 0.0         # auto zero-offset window [s sensor time]; 0 = off
    zero_cal_max_A: float = 1.0     # an offset above this means current was flowing
    zero_mode: str = "linear"       # linear: I_raw - I0 | quadrature: sqrt(I_raw^2 - I0^2)
    zero_default_A: float = 0.0     # offset used when the auto window is rejected
    I0_A: float = 0.0               # zero-current offset actually applied
    zero_state: str = "off"         # off | measuring | done | rejected
    zero_t0: "float | None" = None
    zero_buf: "list[float]" = field(default_factory=list)
    t_prev: "float | None" = None   # sensor time of the last accepted sample
    I_hold: float = 0.0             # ZOH current driving the NEXT interval
    t_axis: float = 0.0             # session clock for plotting (survives Arduino resets)
    n_samples: int = 0
    n_gaps: int = 0
    n_resyncs: int = 0
    n_overrange: int = 0
    hist: "dict[str, list]" = field(default_factory=lambda: {
        k: [] for k in ("t", "I_meas", "I_used", "T_inner", "T_outer", "T_iron",
                        "T_disc_mean", "T_disc_max", "z_mm", "T_core_meas",
                        "T_disc_meas", "T_amb", "T_amb_source", "flag")})
    T_amb_source: str = "params.yaml"   # where twin.T_amb came from (see set_ambient)

    def set_ambient(self, T_amb: float, source: str) -> None:
        """Switch the model's far-field ambient to a new reading (e.g. a weather
        refresh). The lumped nodes keep their temperatures and relax toward it."""
        self.twin.T_amb = float(T_amb)
        self.T_amb_source = source

    def __post_init__(self):
        if self.zero_cal_s > 0 and self.zero_state == "off":
            self.zero_state = "measuring"

    def start_zero_cal(self) -> None:
        """(Re)measure the zero-current offset — the Variac must be at 0."""
        self.zero_state, self.zero_t0, self.zero_buf = "measuring", None, []

    def _zero_cal_sample(self, t_s: float, I_raw: float) -> None:
        if self.zero_t0 is None:
            self.zero_t0 = t_s
        if not math.isnan(I_raw) and I_raw <= self.invalid_above_A:
            self.zero_buf.append(float(I_raw))
        if t_s - self.zero_t0 < self.zero_cal_s or not self.zero_buf:
            return
        I0 = math.sqrt(sum(x * x for x in self.zero_buf) / len(self.zero_buf))
        if I0 > self.zero_cal_max_A:
            self.zero_state, self.I0_A = "rejected", self.zero_default_A
            print(f"[LIVE] zero offset REJECTED: {I0:.3f} A > {self.zero_cal_max_A} A "
                  f"(current flowing?) -- using the default I0 = {self.zero_default_A:.3f} A. "
                  f"Set the Variac to 0 and Re-zero for this board's own value.")
        else:
            self.zero_state, self.I0_A = "done", I0
            print(f"[LIVE] zero offset I0 = {I0:.3f} A ({len(self.zero_buf)} samples), "
                  f"{self.zero_mode} removal")

    def condition(self, I_raw: float) -> "tuple[float, str]":
        """Measured I_rms -> current fed to the model, plus a flag."""
        if I_raw is None or math.isnan(I_raw):
            return 0.0, ""
        if self.zero_mode == "quadrature":
            I = math.sqrt(max(0.0, I_raw * I_raw - self.I0_A * self.I0_A))
        else:
            I = max(0.0, I_raw - self.I0_A)
        if I < self.deadband_A:
            return 0.0, ""
        if I > self.I_max:
            return self.I_max, "overrange"
        return I, ""

    def disc_T(self) -> "tuple[float, float]":
        """(mean, max) disc temperature. The full field needs a live rom (dT_ref);
        without it (self-check coefficients) fall back to the mean-only model."""
        tw = self.twin
        if tw.rom.dT_ref is not None:
            T = tw.T_field
            return float(T.mean()), float(T.max())
        T = tw.T_amb + tw.rom_state.beta * tw.rom.dT_mean_ref
        return T, T

    def push(self, t_s: float, I_raw: float, T_core_meas: float = math.nan,
             T_disc_meas: float = math.nan) -> str:
        """Feed one sensor sample. Returns its flag ("", first/gap/resync/overrange)."""
        if I_raw is not None and not math.isnan(I_raw) and I_raw > self.invalid_above_A:
            # not a current (e.g. raw ADC count) -> hold the last valid I, never clamp-and-heat
            I_used, flag = self.I_hold, "invalid"
            self.n_invalid += 1
            if self.zero_state == "measuring":
                self._zero_cal_sample(t_s, I_raw)   # advances the window, value not used
        elif self.zero_state == "measuring":
            self._zero_cal_sample(t_s, I_raw)
            I_used, flag = 0.0, "zerocal"   # Variac at 0 while the offset is measured
        else:
            I_used, flag = self.condition(I_raw)
        if flag == "overrange":
            self.n_overrange += 1

        if self.t_prev is None:
            flag = flag or "first"
        else:
            dt = t_s - self.t_prev
            if dt <= 0.0:
                flag = "resync"
                self.n_resyncs += 1
            else:
                if dt > self.max_gap_s:
                    flag = "gap"
                    self.n_gaps += 1
                self.twin.step(self.I_hold, dt)
                self.t_axis += dt
        self.t_prev = t_s
        self.I_hold = I_used
        self.n_samples += 1

        T_lump = self.twin.lumped_state.T
        Td_mean, Td_max = self.disc_T()
        h = self.hist
        for k, v in (("t", self.t_axis), ("I_meas", I_raw), ("I_used", I_used),
                     ("T_inner", T_lump["inner"]), ("T_outer", T_lump["outer"]),
                     ("T_iron", T_lump["iron"]), ("T_disc_mean", Td_mean),
                     ("T_disc_max", Td_max), ("z_mm", self.twin.lev_state.z),
                     ("T_core_meas", T_core_meas), ("T_disc_meas", T_disc_meas),
                     ("T_amb", self.twin.T_amb), ("T_amb_source", self.T_amb_source),
                     ("flag", flag)):
            h[k].append(v)
        return flag

    def reset(self) -> None:
        """Model back to ambient + clear history; the sensor link keeps running."""
        self.twin.reset()
        self.__init__(self.twin, self.I_max, self.deadband_A, self.max_gap_s,
                      invalid_above_A=self.invalid_above_A, zero_cal_s=self.zero_cal_s, zero_cal_max_A=self.zero_cal_max_A,
                      zero_mode=self.zero_mode, zero_default_A=self.zero_default_A,
                      I0_A=self.I0_A, zero_state=self.zero_state, zero_t0=self.zero_t0,
                      zero_buf=self.zero_buf, T_amb_source=self.T_amb_source)

    def export_csv(self, path: str) -> int:
        h = self.hist
        cols = list(h.keys())
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_s", "I_meas_A", "I_used_A", "T_inner_pred_degC",
                        "T_outer_pred_degC", "T_iron_pred_degC", "T_disc_mean_pred_degC",
                        "T_disc_max_pred_degC", "z_mm", "T_core_meas_degC",
                        "T_disc_meas_degC", "T_amb_degC", "T_amb_source", "flag"])
            for i in range(len(h["t"])):
                row = []
                for k in cols:
                    v = h[k][i]
                    row.append(v if isinstance(v, str) else f"{v:.4f}")
                w.writerow(row)
        return len(h["t"])


def board_offset(ls: dict, usb_id: "str | None") -> "tuple[str, float]":
    """(board name, default I0) for a USB "VVVV:PPPP" id from live_sensor.board_offsets;
    unknown board -> ("unknown board", zero_offset_default_A)."""
    for b in ls.get("board_offsets") or []:
        if usb_id and str(b["usb_id"]).lower() == usb_id.lower():
            return str(b["name"]), float(b["I0_A"])
    return "unknown board", float(ls.get("zero_offset_default_A", 0.0))


def port_usb_id(port: str) -> "str | None":
    """USB VID:PID ("2341:1002") of a serial port, or None if not a USB device."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    for p in list_ports.comports():
        if p.device == port and p.vid is not None:
            return f"{p.vid:04x}:{p.pid:04x}"
    return None


# ---------------------------------------------------------------------------
# Sample sources + reader thread
# ---------------------------------------------------------------------------
def replay_stream(csv_path: str, speed: float):
    """Replay a data_io.py --mode log CSV (t_s,T_core,T_disc,I_rms) at `speed`
    samples per wall-clock second — same tuple shape as SensorReader.read_stream()."""
    from data_io import SensorReader
    t, T_core, T_disc, I_rms = SensorReader.load_csv(csv_path)
    for row in zip(t, T_core, T_disc, I_rms):
        yield tuple(float(x) for x in row)
        time.sleep(1.0 / speed)


def start_reader(stream, q: "queue.Queue", stop: threading.Event,
                 drop_temps: bool = False) -> threading.Thread:
    """Pump `stream` into `q` from a daemon thread, so a blocking serial readline
    never freezes the GUI. Messages: ("sample", wall, t, T_core, T_disc, I),
    ("error", wall, msg), ("end", wall)."""
    def run():
        try:
            for t, T_core, T_disc, I in stream:
                if stop.is_set():
                    return
                if drop_temps:
                    T_core = T_disc = math.nan
                q.put(("sample", time.monotonic(), t, T_core, T_disc, I))
        except Exception as e:   # serial unplugged etc. -> shown in the status line
            q.put(("error", time.monotonic(), f"{type(e).__name__}: {e}"))
            return
        q.put(("end", time.monotonic()))
    th = threading.Thread(target=run, name="sensor-reader", daemon=True)
    th.start()
    return th


def start_ambient_refresher(fetch, q: "queue.Queue", stop: threading.Event,
                            refresh_s: float) -> threading.Thread:
    """Every refresh_s put ("ambient", wall, reading) on `q`, where
    reading = fetch() (weather_api.ambient_now-style dict). The first fetch is
    done by the caller before the GUI starts, so this waits one period first."""
    def run():
        while not stop.wait(refresh_s):
            q.put(("ambient", time.monotonic(), fetch()))
    th = threading.Thread(target=run, name="ambient-refresher", daemon=True)
    th.start()
    return th


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
def run_gui(driver: LiveDriver, q: "queue.Queue", stop: threading.Event,
            source_label: str, stale_after_s: float, window_s: float) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    from matplotlib.widgets import Button

    DARK_BG, DARK_AX, TEXT_CLR, TITLE_CLR = "#0f0f1e", "#12121e", "#aaaacc", "#ddddf5"
    fig = plt.figure(figsize=(13, 8))
    fig.patch.set_facecolor(DARK_BG)
    fig.canvas.manager.set_window_title("DT4TM — LIVE sensor mode")
    ax_T = fig.add_axes([0.07, 0.45, 0.90, 0.47])
    ax_I = fig.add_axes([0.07, 0.20, 0.90, 0.18], sharex=ax_T)
    ax_st = fig.add_axes([0.07, 0.02, 0.62, 0.11]); ax_st.axis("off")
    ax_rst = fig.add_axes([0.70, 0.05, 0.085, 0.06])
    ax_zero = fig.add_axes([0.79, 0.05, 0.085, 0.06])
    ax_csv = fig.add_axes([0.88, 0.05, 0.09, 0.06])

    for ax, title in ((ax_T, "Temperature — MODEL PREDICTION driven by measured I"),
                      (ax_I, "Measured current I_rms(t)")):
        ax.set_facecolor(DARK_AX)
        for sp in ax.spines.values(): sp.set_edgecolor("#334455")
        ax.tick_params(colors=TEXT_CLR, labelsize=8)
        ax.set_title(title, fontsize=9, color=TITLE_CLR)
        ax.grid(alpha=0.2)
    ax_T.set_ylabel("T (°C)", color=TEXT_CLR)
    ax_I.set_ylabel("I (A)", color=TEXT_CLR)
    ax_I.set_xlabel("session time (min)", color=TEXT_CLR)

    ln = {
        "T_inner":     ax_T.plot([], [], color="#ff6644", lw=2, label="inner coil")[0],
        "T_outer":     ax_T.plot([], [], color="#ffaa33", lw=2, label="outer coil")[0],
        "T_iron":      ax_T.plot([], [], color="#aa88ff", lw=1.5, label="iron")[0],
        "T_disc_mean": ax_T.plot([], [], color="#44ccff", lw=2, label="disc mean")[0],
        "T_disc_max":  ax_T.plot([], [], color="#44ccff", lw=1, ls="--", label="disc max")[0],
        # Only drawn if the source actually carries temperatures (thermocouple log / replay).
        "T_core_meas": ax_T.plot([], [], "o", ms=2.5, color="#ff6644", alpha=0.6,
                                  label="T_core (sensor)")[0],
        "T_disc_meas": ax_T.plot([], [], "o", ms=2.5, color="#44ccff", alpha=0.6,
                                  label="T_disc (sensor)")[0],
        "I_meas":      ax_I.plot([], [], color="#888899", lw=1, label="I measured")[0],
        "I_used":      ax_I.plot([], [], color="#ffcc44", lw=1.8, drawstyle="steps-post",
                                  label="I fed to model")[0],
    }
    def _legend_T(with_meas: bool):
        keys = ["T_inner", "T_outer", "T_iron", "T_disc_mean", "T_disc_max"]
        if with_meas:
            keys += ["T_core_meas", "T_disc_meas"]
        ax_T.legend([ln[k] for k in keys], [ln[k].get_label() for k in keys], fontsize=8,
                    loc="upper left", ncol=4, facecolor=DARK_AX, labelcolor=TEXT_CLR)
    _legend_T(False)
    ax_I.legend(fontsize=8, loc="upper left", ncol=2, facecolor=DARK_AX, labelcolor=TEXT_CLR)
    txt = ax_st.text(0.0, 1.0, "", transform=ax_st.transAxes, va="top",
                     family="monospace", fontsize=9, color=TEXT_CLR)

    link = {"last_wall": None, "state": "WAITING", "msg": "", "meas_legend": False}

    btn_rst = Button(ax_rst, "Reset model", color="#223355", hovercolor="#335588")
    btn_zero = Button(ax_zero, "Re-zero", color="#223355", hovercolor="#335588")
    btn_csv = Button(ax_csv, "Export CSV", color="#223355", hovercolor="#335588")
    for b in (btn_rst, btn_zero, btn_csv):
        b.label.set_color(TITLE_CLR); b.label.set_fontsize(9)

    def _on_reset(_ev):
        driver.reset()
        link["msg"] = "model reset to ambient"
    btn_rst.on_clicked(_on_reset)

    def _on_zero(_ev):
        driver.zero_cal_s = driver.zero_cal_s or 10.0
        driver.start_zero_cal()
        link["msg"] = "re-zero: keep the Variac at 0"
    btn_zero.on_clicked(_on_zero)

    def _on_csv(_ev):
        os.makedirs(os.path.join(HERE, "outputs"), exist_ok=True)
        path = os.path.join(HERE, "outputs",
                            time.strftime("live_session_%Y%m%d_%H%M%S.csv"))
        n = driver.export_csv(path)
        link["msg"] = f"exported {n} rows -> outputs/{os.path.basename(path)}"
        print(f"[LIVE] {link['msg']}")
    btn_csv.on_clicked(_on_csv)

    def update(_frame):
        while True:
            try:
                msg = q.get_nowait()
            except queue.Empty:
                break
            kind, wall = msg[0], msg[1]
            if kind == "sample":
                _, _, t, T_core, T_disc, I = msg
                flag = driver.push(t, I, T_core, T_disc)
                link["last_wall"], link["state"] = wall, "LIVE"
                if flag == "invalid":
                    link["msg"] = (f"INVALID reading {I:.0f} (> {driver.invalid_above_A:g} A, "
                                   f"raw ADC? check firmware) -- ignored, I held")
                elif flag in ("gap", "resync", "overrange"):
                    link["msg"] = f"{flag} at t={driver.t_axis:.0f}s"
            elif kind == "error":
                link["state"], link["msg"] = "DISCONNECTED", msg[2]
            elif kind == "end":
                link["state"], link["msg"] = "ENDED", "source finished (replay done)"
            elif kind == "ambient":
                amb = msg[2]
                driver.set_ambient(amb["T_amb_degC"], amb["source"])
                link["msg"] = f"ambient refreshed: {amb['T_amb_degC']:.1f}°C ({amb['source']})"

        if link["state"] == "LIVE" and link["last_wall"] is not None \
                and time.monotonic() - link["last_wall"] > stale_after_s:
            link["state"] = "STALE"

        h = driver.hist
        if h["t"]:
            t_min = [x / 60.0 for x in h["t"]]
            for k, line in ln.items():
                line.set_data(t_min, h[k])
            x_hi = max(t_min[-1], window_s / 60.0)
            ax_T.set_xlim(x_hi - window_s / 60.0, x_hi)
            ys = [v for k in ("T_inner", "T_outer", "T_iron", "T_disc_max",
                              "T_core_meas", "T_disc_meas")
                  for v in h[k] if not math.isnan(v)]
            ax_T.set_ylim(min(ys) - 1.0, max(ys) + 2.0)
            if not link["meas_legend"] and any(
                    not math.isnan(v) for k in ("T_core_meas", "T_disc_meas") for v in h[k]):
                _legend_T(True)
                link["meas_legend"] = True
            Is = [v for v in h["I_meas"] if not math.isnan(v)] or [0.0]
            ax_I.set_ylim(0.0, max(max(Is) * 1.15, 1.0))

        badge = {"LIVE": "● LIVE", "STALE": "⚠ STALE (no new sample)",
                 "DISCONNECTED": "✖ DISCONNECTED", "ENDED": "■ ENDED",
                 "WAITING": "… waiting for first sample"}[link["state"]]
        age = "" if link["last_wall"] is None else \
            f"  last sample {time.monotonic() - link['last_wall']:.1f}s ago"
        I_now = h["I_meas"][-1] if h["I_meas"] else math.nan
        I_use = h["I_used"][-1] if h["I_used"] else math.nan
        if driver.zero_state == "measuring":
            left = driver.zero_cal_s - (0.0 if driver.zero_t0 is None or driver.t_prev is None
                                        else driver.t_prev - driver.zero_t0)
            zero = f"ZERO-CAL: keep the Variac at 0 ... {max(left, 0):.0f}s left"
        else:
            zero = {"done": f"offset I0={driver.I0_A:.3f}A (auto, {driver.zero_mode})",
                    "rejected": f"auto offset REJECTED (current flowing) -> default "
                                f"I0={driver.I0_A:.3f}A; Re-zero at 0 A",
                    "off": "offset off"}[driver.zero_state]
        T_in = h["T_inner"][-1] if h["T_inner"] else math.nan
        Td = h["T_disc_mean"][-1] if h["T_disc_mean"] else math.nan
        z = h["z_mm"][-1] if h["z_mm"] else math.nan
        txt.set_text(
            f"{badge}   source: {source_label}{age}\n"
            f"I_meas={I_now:5.2f}A  I_used={I_use:5.2f}A  [{zero}]\n"
            f"T_inner={T_in:6.2f}°C  T_disc={Td:6.2f}°C  z_gap={z:5.2f}mm  "
            f"T_amb={driver.twin.T_amb:.1f}°C ({driver.T_amb_source})\n"
            f"samples={driver.n_samples}  gaps={driver.n_gaps}  resyncs={driver.n_resyncs}  "
            f"overrange={driver.n_overrange}  invalid={driver.n_invalid}\n{link['msg']}")
        txt.set_color("#ffcc44" if driver.zero_state in ("measuring", "rejected") else
                      {"LIVE": "#88ff99", "STALE": "#ffcc44"}.get(link["state"], TEXT_CLR))

    ani = FuncAnimation(fig, update, interval=200, cache_frame_data=False)
    fig._live_ani = ani   # keep a reference alive for the window's lifetime
    try:
        plt.show()
    finally:
        stop.set()


# ---------------------------------------------------------------------------
# Self-check — synthetic twin_core coefficients: no config/em/matplotlib/serial
# ---------------------------------------------------------------------------
def _self_check() -> bool:
    from twin_core import RomCoeffs, _synthetic_lev, _synthetic_lumped

    def fresh_twin():
        rom = RomCoeffs(T_amb=20.0, tau=100.0, I_ref=5.0, dT_mean_ref=43.0, alpha=3.9e-3,
                         f_eddy=0.7, f_air=0.3)
        return TwinState(rom=rom, lumped=_synthetic_lumped(), lev=_synthetic_lev(), T_amb=20.0)

    def fresh_driver():
        return LiveDriver(fresh_twin(), I_max=7.8, deadband_A=0.2, max_gap_s=10.0)

    results = []

    def check(name, ok, detail=""):
        print(f"[{len(results) + 1}] {name}: {detail}  {'PASS' if ok else 'FAIL'}")
        results.append(bool(ok))

    # 1. Constant 5A at 1Hz == calling TwinState.step(5, 1) directly (bit-identical):
    #    the driver adds no physics of its own.
    d, ref = fresh_driver(), fresh_twin()
    d.push(0.0, 5.0)
    for k in range(1, 601):
        d.push(float(k), 5.0)
        ref.step(5.0, 1.0)
    err = max(abs(d.twin.lumped_state.T[n] - ref.lumped_state.T[n]) for n in ref.lumped_state.T)
    err = max(err, abs(d.twin.rom_state.beta - ref.rom_state.beta))
    check("constant 5A stream == direct TwinState.step", err == 0.0, f"max|Δ|={err:.1e}")

    # 2. Zero-order hold: an interval is driven by the PREVIOUS sample's current.
    d = fresh_driver()
    d.push(0.0, 0.0); d.push(1.0, 5.0)          # interval (0,1] driven by 0A
    check("ZOH: first interval uses previous sample (0A)",
          d.twin.lumped_state.T["inner"] == 20.0, f"T_inner={d.twin.lumped_state.T['inner']:.6f}")

    # 3. Dead-band: sensor noise floor with the Variac at 0 does not heat anything.
    d = fresh_driver()
    for k in range(300):
        d.push(float(k), 0.15)
    check("dead-band: 0.15A noise -> no heating",
          d.twin.lumped_state.T["inner"] == 20.0 and d.hist["I_used"][-1] == 0.0,
          f"T_inner={d.twin.lumped_state.T['inner']:.6f}")

    # 4. Over-range: clamped to I_max and counted.
    d = fresh_driver()
    d.push(0.0, 12.0)
    check("over-range: 12A clamped to I_max=7.8A",
          d.hist["I_used"][-1] == 7.8 and d.n_overrange == 1 and d.hist["flag"][-1] == "overrange")

    # 5. Gap: flagged, but still integrated with the held current (clock advances).
    d = fresh_driver()
    d.push(0.0, 5.0); d.push(1.0, 5.0); d.push(31.0, 5.0)
    check("gap: 30s jump flagged + integrated", d.n_gaps == 1 and d.t_axis == 31.0
          and d.hist["flag"][-1] == "gap", f"t_axis={d.t_axis}")

    # 6. Arduino reset (millis restarts -> time goes backwards): resync, no step.
    d = fresh_driver()
    d.push(100.0, 5.0); d.push(101.0, 5.0)
    T_before, t_before = d.twin.lumped_state.T["inner"], d.twin.t
    d.push(-500.0, 5.0)
    check("resync: backwards time -> no step",
          d.n_resyncs == 1 and d.twin.t == t_before
          and d.twin.lumped_state.T["inner"] == T_before)
    d.push(-499.0, 5.0)
    check("resync: stepping resumes after the new time base", d.twin.t > t_before,
          f"twin.t {t_before:.0f}->{d.twin.t:.0f}")

    # 7. Cool-down: current off -> coil temperature falls.
    d = fresh_driver()
    for k in range(600):
        d.push(float(k), 5.0)
    T_hot = d.twin.lumped_state.T["inner"]
    for k in range(600, 900):
        d.push(float(k), 0.0)
    check("cool-down after I->0", d.twin.lumped_state.T["inner"] < T_hot,
          f"{T_hot:.2f} -> {d.twin.lumped_state.T['inner']:.2f} °C")

    # 8. Reader thread delivers every sample, then "end"; a crashing source -> "error".
    q, stop = queue.Queue(), threading.Event()
    src = ((float(k), math.nan, math.nan, 5.0) for k in range(5))
    start_reader(src, q, stop).join(timeout=2.0)
    kinds = [q.get_nowait()[0] for _ in range(q.qsize())]

    def broken():
        yield (0.0, math.nan, math.nan, 5.0)
        raise ConnectionError("unplugged")
    q2 = queue.Queue()
    start_reader(broken(), q2, stop).join(timeout=2.0)
    kinds2 = [q2.get_nowait()[0] for _ in range(q2.qsize())]
    check("reader thread: 5 samples + end / error on disconnect",
          kinds == ["sample"] * 5 + ["end"] and kinds2 == ["sample", "error"])

    # 9. Reset clears model + history, keeps settings.
    d.reset()
    check("reset -> ambient, empty history",
          d.twin.lumped_state.T["inner"] == 20.0 and not d.hist["t"] and d.I_max == 7.8)

    # 10. CSV export round-trip.
    import tempfile
    d = fresh_driver()
    for k in range(10):
        d.push(float(k), 5.0)
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "x.csv")
        n = d.export_csv(p)
        with open(p) as f:
            lines = f.read().strip().splitlines()
    check("CSV export", n == 10 and len(lines) == 11 and lines[0].startswith("t_s,I_meas_A"))

    # 11. Auto zero offset: 10 s of 0.25 A noise -> I0 = 0.25, model held at 0 meanwhile,
    #     then (quadrature mode) 5.006 A raw -> sqrt(5.006^2 - 0.25^2) = 5.000 A.
    d = LiveDriver(fresh_twin(), I_max=7.8, deadband_A=0.2, max_gap_s=10.0, zero_cal_s=10.0,
                   zero_mode="quadrature")
    for k in range(11):
        d.push(float(k), 0.25)
    held = d.twin.lumped_state.T["inner"] == 20.0 and set(d.hist["flag"]) == {"zerocal"}
    d.push(11.0, math.sqrt(5.0 ** 2 + 0.25 ** 2))
    check("zero offset: measured, model held at 0 during the window",
          d.zero_state == "done" and abs(d.I0_A - 0.25) < 1e-12 and held, f"I0={d.I0_A:.4f}")
    check("zero offset: removed in quadrature", abs(d.hist["I_used"][-1] - 5.0) < 1e-12,
          f"I_used={d.hist['I_used'][-1]:.6f}")
    d2 = LiveDriver(fresh_twin(), I_max=7.8, deadband_A=0.2, max_gap_s=10.0, zero_cal_s=5.0)
    for k in range(6):
        d2.push(float(k), 0.345)
    d2.push(6.0, 5.44)
    check("zero offset: linear (default) 5.44 A raw, I0=0.345 -> 5.095 A",
          d2.zero_mode == "linear" and abs(d2.hist["I_used"][-1] - 5.095) < 1e-12,
          f"I_used={d2.hist['I_used'][-1]:.4f}")
    d.reset()
    check("zero offset survives a model reset", d.zero_state == "done" and d.I0_A == 0.25)

    # 12. Current flowing during the zero window -> rejected, the default offset is used.
    d = LiveDriver(fresh_twin(), I_max=7.8, deadband_A=0.2, max_gap_s=10.0, zero_cal_s=5.0,
                   zero_default_A=0.345)
    for k in range(7):
        d.push(float(k), 5.0)
    check("zero offset: 5 A during the window -> rejected, default I0 used",
          d.zero_state == "rejected" and d.I0_A == 0.345
          and abs(d.hist["I_used"][-1] - 4.655) < 1e-12, f"I_used={d.hist['I_used'][-1]:.4f}")

    # 13. Per-board default offset by USB VID:PID.
    ls = {"board_offsets": [{"name": "UNO R4 WiFi", "usb_id": "2341:1002", "I0_A": 0.345},
                            {"name": "UNO R4 Minima", "usb_id": "2341:0069", "I0_A": 0.225}],
          "zero_offset_default_A": 0.0}
    check("board offset: WiFi / Minima / unknown",
          board_offset(ls, "2341:1002") == ("UNO R4 WiFi", 0.345)
          and board_offset(ls, "2341:0069") == ("UNO R4 Minima", 0.225)
          and board_offset(ls, "1a86:7523") == ("unknown board", 0.0)
          and board_offset(ls, None) == ("unknown board", 0.0))

    # 14. A raw ADC count (512) is not a current: ignored, last valid I held, no clamp-heating.
    d = fresh_driver()
    d.push(0.0, 5.0); d.push(1.0, 512.0); d.push(2.0, 5.0)
    check("invalid reading (raw ADC 512) -> ignored, 5 A held",
          d.hist["flag"][1] == "invalid" and d.hist["I_used"][1] == 5.0 and d.n_invalid == 1
          and d.n_overrange == 0)

    # 15. Bare "I_rms" serial lines (firmware without millis) are accepted.
    from data_io import _LINE_RE_BARE
    check("serial: bare number lines parse",
          [bool(_LINE_RE_BARE.match(x)) for x in ("4.987", "0.250", "nan", "12", "1,2", "# x")]
          == [True, True, True, True, False, False])

    print(f"\n{sum(results)}/{len(results)} PASS" + ("" if all(results) else "  -- FAILURES ABOVE"))
    return all(results)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="DT4TM live-sensor mode (optional, separate from digital_twin.py)")
    p.add_argument("--port", default=None,
                   help="Arduino serial port, or 'mock' (default: params.yaml live_sensor.port)")
    p.add_argument("--replay", default=None, metavar="CSV",
                   help="Replay a data_io.py --mode log CSV instead of reading serial")
    p.add_argument("--no-em", action="store_true", help="Skip the EM solve (placeholder losses, fast)")
    p.add_argument("--self-check", action="store_true", help="Run logic tests and exit")
    args = p.parse_args()

    if args.self_check:
        raise SystemExit(0 if _self_check() else 1)

    from config import load_config
    from data_io import SensorReader
    from rom import ThermalROM
    from twin_model import coeffs_from_live, live_i_max_for

    cfg = load_config()
    ls = cfg.raw.get("live_sensor")
    if ls is None:
        raise SystemExit("params.yaml has no `live_sensor` block — see the module docstring.")
    port = args.port or str(ls["port"])

    # Open the source BEFORE the (slow) model build, so a wrong port fails fast.
    reader = None
    is_mock = port.lower() == "mock"
    if args.replay:
        stream, label, drop = replay_stream(args.replay, float(ls["mock_speed"])), \
            f"replay {os.path.basename(args.replay)} @{ls['mock_speed']:g}x", False
    else:
        reader = SensorReader(port, int(ls["baudrate"]), mock_speed=float(ls["mock_speed"]))
        # The mock's temperatures are arbitrary test numbers (data_io._mock_stream),
        # unrelated to this model — never plot them as "sensor" data.
        stream, drop = reader.read_stream(), is_mock
        label = f"MOCK (synthetic 5A) @{ls['mock_speed']:g}x" if is_mock else \
            f"serial {port} @{ls['baudrate']} baud"

    # Ambient: live weather for a real rig, the logged value for a replay,
    # otherwise the constant params.yaml ambient (mock / no key / expired / offline).
    from weather_api import ambient_now, describe
    T_amb_fb = float(cfg.bc["T_ambient_degC"])
    live_weather = not args.replay and not is_mock
    if live_weather:
        amb = ambient_now(T_amb_fb, cfg.raw)
    elif args.replay:
        logged = [float(v) for v in SensorReader.load_ambient(args.replay) if not math.isnan(v)]
        amb = {"T_amb_degC": logged[0] if logged else T_amb_fb,
               "source": "logged" if logged else "fallback",
               "fetched_at": "from " + os.path.basename(args.replay)}
    else:
        amb = {"T_amb_degC": T_amb_fb, "source": "fallback",
               "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": "mock"}
    print(f"[weather] {describe(amb)}")

    em = None
    if not args.no_em:
        from em_solver import compute_losses
        print(f"[EM] Solving at î={cfg.I}A... ", end="", flush=True)
        em = compute_losses(cfg)
        print(f"P_plate={em['P_plate_W']:.2f} W  P_coil={em['P_coil_W']:.1f} W")
    rom = ThermalROM().build(cfg, em_losses=em, verbose=False)
    rom_c, lumped_c, lev_c = coeffs_from_live(cfg, em, rom)
    twin = TwinState(rom=rom_c, lumped=lumped_c, lev=lev_c, T_amb=amb["T_amb_degC"])
    # Auto zero-offset only for a real sensor: mock/replay values are already "clean".
    zero_cal_s = float(ls.get("zero_cal_s", 0.0)) if not (is_mock or args.replay) else 0.0
    usb_id = port_usb_id(port) if zero_cal_s > 0 else None
    board, I0_default = board_offset(ls, usb_id)
    if zero_cal_s > 0:
        print(f"[LIVE] board: {board} (USB {usb_id or '?'}) -> default I0 {I0_default:.3f} A "
              f"if the auto zero window is rejected")
    driver = LiveDriver(twin, I_max=live_i_max_for(cfg), deadband_A=float(ls["deadband_A"]),
                        invalid_above_A=float(ls.get("invalid_above_A", 20.0)),
                        max_gap_s=float(ls["max_gap_s"]), zero_cal_s=zero_cal_s,
                        zero_cal_max_A=float(ls.get("zero_cal_max_A", 1.0)),
                        zero_mode=str(ls.get("zero_offset_mode", "linear")),
                        zero_default_A=I0_default if zero_cal_s > 0 else 0.0,
                        T_amb_source=amb["source"])
    if zero_cal_s > 0:
        print(f"[LIVE] measuring the zero-current offset for {zero_cal_s:g}s -- "
              f"keep the Variac at 0 until the window says done")

    q, stop = queue.Queue(), threading.Event()
    start_reader(stream, q, stop, drop_temps=drop)
    if live_weather:
        start_ambient_refresher(lambda: ambient_now(T_amb_fb, cfg.raw), q, stop,
                                float(cfg.raw.get("weather_api", {}).get("log_refresh_s", 600.0)))
    print(f"[LIVE] source: {label}   I_max={driver.I_max:.2f}A  dead-band={driver.deadband_A}A")
    try:
        run_gui(driver, q, stop, label, float(ls["stale_after_s"]), float(ls["window_s"]))
    finally:
        stop.set()
        if reader is not None:
            reader.close()


if __name__ == "__main__":
    main()
