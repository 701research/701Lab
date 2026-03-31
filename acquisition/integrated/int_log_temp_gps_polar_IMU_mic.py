#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
701 Lab Integrated Logger v1.3 (seq added + temp_c -> temp_raw) + Polar(Bleak) swap

IMU policy:
- IMUWorker does NOT write files directly.
- IMURawWriter writes raw IMU frames to run_dir/raw/imu_*.bin (high-rate safe).
- UnifiedWriter receives only minimal derived facts from IMUWorker:
    alive / timeout / rx_rate_hz / bad_checksum / resync / reconnect / drop

Audio policy:
- AudioRawWriter starts/stops arecord and writes run_dir/raw/audio*.wav
- AudioWorker emits only minimal health facts to UnifiedWriter (alive/proc/exit)

Temp policy:
- DS18B20 provides raw integer "t=" (milli-degC). This logger stores it as temp_raw.
  (Example: 23125 means 23.125°C)

Enable IMU:
    export IMU_ENABLE=1
Optional:
    export IMU_PORT=/dev/ttyUSB0
    export IMU_BAUD=115200

Enable Audio (USB mic via ALSA arecord):
    export AUDIO_ENABLE=1
Optional:
    export AUDIO_DEVICE=hw:3,0
    export AUDIO_RATE=48000
    export AUDIO_CHANNELS=1
    export AUDIO_FORMAT=S16_LE
    export AUDIO_FILE_WAV=audio.wav
    export AUDIO_CHUNK_SEC=0   # 0 = single file, >0 = arecord -d chunk seconds

Enable Polar (BLE HRM via Bleak):
    export POLAR_ENABLE=1
    export POLAR_DEVICE=24:AC:AC:12:4E:72

Optional (Bleak tuning):
    export POLAR_SCAN_TIMEOUT=8
    export POLAR_CONNECT_TIMEOUT=20
    export POLAR_POST_CONNECT_SLEEP=2.0
    export POLAR_POST_WAKE_SLEEP=0.5
    export POLAR_FIRST_NOTIFY_TIMEOUT=30
    export POLAR_NOTIFY_GAP_ABORT=15
    export POLAR_BACKOFF_INIT=2
    export POLAR_BACKOFF_MAX=20
    export POLAR_BACKOFF_MULT=1.5
    export POLAR_RECONNECT_DELAY_ON_SUCCESS=1.0

UUID override (rarely needed):
    export POLAR_HRM_CHAR=00002a37-0000-1000-8000-00805f9b34fb
    export POLAR_BSL_CHAR=00002a38-0000-1000-8000-00805f9b34fb
    export POLAR_BATTERY_CHAR=00002a19-0000-1000-8000-00805f9b34fb
"""

from __future__ import annotations

import csv
import json
import os
import signal
import sys
import time
import glob
import re
import subprocess
import select
import struct
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from queue import Queue, Empty, Full
from threading import Event, Thread, Lock
from typing import Callable, Dict, Optional, Tuple, List, Any

# NOTE: Bleak is used only inside PolarWorker to avoid import-hard-fail at module import time.
# (If bleak is missing, PolarWorker will report ERROR and stop.)

# ============================================================
# Config
# ============================================================

@dataclass(frozen=True)
class Config:
    data_root_rel: Path = Path("701lab_data/runs")
    storage_candidates: Tuple[str, ...] = ("/mnt/usb", "/media/*/*")

    gpio_button: int = 27
    gpio_led_pwm: int = 13
    long_press_sec: float = 2.0
    debounce_sec: float = 0.03

    led_on_value: float = 0.5

    boot_slow_blink_period: float = 1.2
    idle_blink_period: float = 0.6
    stopping_fast_blink_period: float = 0.18
    error_pattern_period: float = 1.4

    # --- NEW: IDLE_GPS_OK "breathe" (soft fade) ---
    idle_gps_breathe_period: float = 2.6     # 1 cycle (up+down)
    idle_gps_breathe_min: float = 0.03       # PWM value (0..1)
    idle_gps_breathe_max: float = 0.18       # PWM value (0..1)
    idle_gps_breathe_step_sec: float = 0.03  # update interval


    error_on_t: float = 0.15
    error_off_t: float = 0.10

    allow_start_without_gps: bool = True
    storage_poll_sec: float = 0.5

    # Dummy worker settings
    dummy_period_sec: float = 0.25

    # Temp worker settings (DS18B20)
    temp_period_sec: float = 1.0
    temp_rescan_sec: float = 5.0
    temp_w1_base: Path = Path("/sys/bus/w1/devices")

    # GPS worker settings (UART NMEA -> derived facts)
    gps_period_sec: float = 1.0
    gps_timeout_sec: float = 2.5
    gps_port: str = "/dev/serial0"
    gps_baud: int = 9600
    gps_serial_read_timeout: float = 0.5
    gps_emit_speed: bool = True
    gps_emit_utc: bool = True

    # ========================================================
    # Polar worker settings (BLE HRM via Bleak)
    # ========================================================
    polar_enable: bool = bool(int(os.environ.get("POLAR_ENABLE", "0")))
    polar_device: str = os.environ.get("POLAR_DEVICE", "").strip()

    polar_scan_timeout: float = float(os.environ.get("POLAR_SCAN_TIMEOUT", "8.0"))
    polar_connect_timeout: float = float(os.environ.get("POLAR_CONNECT_TIMEOUT", "20.0"))

    polar_post_connect_sleep: float = float(os.environ.get("POLAR_POST_CONNECT_SLEEP", "2.0"))
    polar_post_wake_sleep: float = float(os.environ.get("POLAR_POST_WAKE_SLEEP", "0.5"))

    polar_first_notify_timeout: float = float(os.environ.get("POLAR_FIRST_NOTIFY_TIMEOUT", "30.0"))
    polar_notify_gap_abort: float = float(os.environ.get("POLAR_NOTIFY_GAP_ABORT", "15.0"))

    polar_backoff_init: float = float(os.environ.get("POLAR_BACKOFF_INIT", "2.0"))
    polar_backoff_max: float = float(os.environ.get("POLAR_BACKOFF_MAX", "20.0"))
    polar_backoff_mult: float = float(os.environ.get("POLAR_BACKOFF_MULT", "1.5"))
    polar_reconnect_delay_on_success: float = float(os.environ.get("POLAR_RECONNECT_DELAY_ON_SUCCESS", "1.0"))

    polar_alive_interval_sec: float = 1.0
    polar_drop_hr_zero: bool = True
    polar_emit_flags: bool = True

    polar_hrm_char: str = os.environ.get("POLAR_HRM_CHAR", "00002a37-0000-1000-8000-00805f9b34fb").strip()
    polar_bsl_char: str = os.environ.get("POLAR_BSL_CHAR", "00002a38-0000-1000-8000-00805f9b34fb").strip()
    polar_battery_char: str = os.environ.get("POLAR_BATTERY_CHAR", "00002a19-0000-1000-8000-00805f9b34fb").strip()

    # (Legacy env retained for compatibility; Bleak版では基本未使用)
    polar_cccd: str = os.environ.get("POLAR_CCCD", "0x0011").strip()
    polar_poll_sec: float = 0.5
    polar_idle_timeout_sec: float = 20.0
    polar_restart_wait_sec: float = 2.5
    polar_min_hex_bytes: int = 3

    # ---- IMU settings ----
    imu_enable: bool = bool(int(os.environ.get("IMU_ENABLE", "0")))
    imu_port: str = os.environ.get("IMU_PORT", "/dev/ttyUSB0").strip()
    imu_baud: int = int(os.environ.get("IMU_BAUD", "115200"))
    imu_serial_timeout: float = float(os.environ.get("IMU_SERIAL_TIMEOUT", "0.2"))
    imu_reconnect: bool = True
    imu_reconnect_backoff0: float = 1.0
    imu_reconnect_backoff_max: float = 20.0

    imu_alive_interval_sec: float = 1.0
    imu_rate_window_sec: float = 2.0
    imu_timeout_sec: float = 1.0

    # RawWriter settings
    imu_raw_filename: str = "imu_bwt901cl.bin"
    imu_raw_queue_max: int = 20000
    imu_raw_flush_interval_sec: float = 1.0
    imu_raw_write_chunk: int = 512

    # ---- Audio settings ----
    audio_enable: bool = bool(int(os.environ.get("AUDIO_ENABLE", "0")))
    audio_device: str = os.environ.get("AUDIO_DEVICE", "hw:3,0").strip()
    audio_format: str = os.environ.get("AUDIO_FORMAT", "S16_LE").strip()
    audio_rate: int = int(os.environ.get("AUDIO_RATE", "48000"))
    audio_channels: int = int(os.environ.get("AUDIO_CHANNELS", "1"))
    audio_file_wav: str = os.environ.get("AUDIO_FILE_WAV", "audio.wav").strip()
    audio_chunk_sec: int = int(os.environ.get("AUDIO_CHUNK_SEC", "0"))
    audio_nice: int = int(os.environ.get("AUDIO_NICE", "0"))

    # Stop policy (staged): SIGINT -> SIGTERM -> SIGKILL
    audio_sigint_timeout_sec: float = float(os.environ.get("AUDIO_SIGINT_TIMEOUT_SEC", "8.0"))
    audio_sigterm_timeout_sec: float = float(os.environ.get("AUDIO_SIGTERM_TIMEOUT_SEC", "4.0"))
    audio_kill_timeout_sec: float = float(os.environ.get("AUDIO_KILL_TIMEOUT_SEC", "2.0"))

    audio_alive_interval_sec: float = 1.0

    simulate: bool = bool(int(os.environ.get("SIMULATE", "0")))

CFG = Config()

# ============================================================
# Time helpers
# ============================================================

def now_mono() -> float:
    return time.monotonic()

def now_wall() -> float:
    return time.time()

def wall_iso(ts: Optional[float] = None) -> str:
    """ISO8601 (localtime) for readability in csv."""
    if ts is None:
        ts = now_wall()
    lt = time.localtime(ts)
    return time.strftime("%Y-%m-%dT%H:%M:%S", lt) + f".{int((ts - int(ts))*1000):03d}"

def wall_ms(ts: Optional[float] = None) -> int:
    if ts is None:
        ts = now_wall()
    return int(ts * 1000)

def mono_ns(ts_mono: Optional[float] = None) -> int:
    if ts_mono is None:
        ts_mono = now_mono()
    return int(ts_mono * 1_000_000_000)

# ============================================================
# Atomic JSON write
# ============================================================

def atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

# ============================================================
# Events / States
# ============================================================

class State(Enum):
    OFF = auto()
    BOOTING = auto()
    STORAGE_MISSING = auto()
    IDLE_NO_GPS = auto()
    IDLE_GPS_OK = auto()
    MEASURING = auto()
    STOPPING = auto()
    ERROR_LATCHED = auto()

class EventType(Enum):
    PWR_ON = auto()
    BOOT_DONE = auto()
    GPS_FIX_ON = auto()
    GPS_FIX_OFF = auto()
    BTN_SHORT = auto()
    BTN_LONG = auto()
    STOP_DONE = auto()
    FATAL_ERR = auto()
    RECOVERED = auto()
    STORAGE_OK = auto()
    SIGINT = auto()
    SIGTERM = auto()

@dataclass
class EventMsg:
    etype: EventType
    detail: str = ""

# ============================================================
# Storage detection
# ============================================================

def _try_make_writable_dir(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        test = p / ".write_test"
        with open(test, "w", encoding="utf-8") as f:
            f.write("ok")
        test.unlink(missing_ok=True)
        return True
    except Exception:
        return False

def find_writable_storage_root(cfg: Config) -> Optional[Path]:
    override = os.environ.get("LOGGER_STORAGE_ROOT", "").strip()
    if override:
        p = Path(override).expanduser()
        if _try_make_writable_dir(p):
            return p

    for pat in cfg.storage_candidates:
        for mp in sorted(glob.glob(pat)):
            mount_path = Path(mp)
            if not mount_path.exists():
                continue
            target = mount_path / cfg.data_root_rel
            if _try_make_writable_dir(target):
                return target
    return None

class StorageWatcher:
    def __init__(self, cfg: Config, out_q: Queue):
        self.cfg = cfg
        self.out_q = out_q
        self.interval_sec = cfg.storage_poll_sec
        self._stop = Event()
        self._storage_dir: Optional[Path] = find_writable_storage_root(cfg)
        self._thread = Thread(target=self._loop, daemon=True)
        self._thread.start()

    def get_dir(self) -> Optional[Path]:
        return self._storage_dir

    def ok(self) -> bool:
        return self._storage_dir is not None

    def _loop(self) -> None:
        last_ok = self.ok()
        while not self._stop.wait(self.interval_sec):
            cur_dir = find_writable_storage_root(self.cfg)
            self._storage_dir = cur_dir
            cur_ok = cur_dir is not None
            if cur_ok and (not last_ok):
                self.out_q.put(EventMsg(EventType.STORAGE_OK, f"storage={cur_dir}"))
            last_ok = cur_ok

    def close(self) -> None:
        self._stop.set()
        try:
            self._thread.join(timeout=1.0)
        except Exception:
            pass

# ============================================================
# GPIO Abstraction (real / simulate)
# ============================================================

class LEDDriver:
    """Switch LED behavior controller."""
    def __init__(self, pwm_pin: int, on_value: float, simulate: bool = False):
        self.simulate = simulate
        self.on_value = max(0.0, min(1.0, on_value))
        self._stop = Event()
        self._thread: Optional[Thread] = None
        self._mode = "off"
        self._pwm = None
        if not self.simulate:
            try:
                from gpiozero import PWMLED  # type: ignore
                self._pwm = PWMLED(pwm_pin)
                self._pwm.value = 0.0
            except Exception as e:
                print(f"[LED] GPIO init failed, fallback to simulate: {e}", file=sys.stderr)
                self.simulate = True

    def set_mode(
        self,
        mode: str,
        period: float = 1.0,
        error_on_t: float = 0.15,
        error_off_t: float = 0.10,
        breathe_min: float = 0.03,
        breathe_max: float = 0.18,
        breathe_step_sec: float = 0.03,
    ) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        self._stop_blink_thread()

        if mode == "off":
            self._write(0.0)
        elif mode == "on":
            self._write(self.on_value)
        elif mode in ("blink", "slow_blink", "fast_blink", "error", "breathe"):
            self._start_blink_thread(
                mode, period,
                error_on_t, error_off_t,
                breathe_min, breathe_max, breathe_step_sec
            )
        else:
            raise ValueError(f"Unknown LED mode: {mode}")


    def _write(self, value: float) -> None:
        if self.simulate:
            print(f"[LED] value={value:.2f} mode={self._mode}")
            return
        assert self._pwm is not None
        self._pwm.value = max(0.0, min(1.0, value))

    def _start_blink_thread(
        self,
        mode: str,
        period: float,
        error_on_t: float,
        error_off_t: float,
        breathe_min: float,
        breathe_max: float,
        breathe_step_sec: float,
    ) -> None:
        self._stop.clear()
        self._thread = Thread(
            target=self._blink_loop,
            args=(
                mode, float(period),
                error_on_t, error_off_t,
                float(breathe_min), float(breathe_max), float(breathe_step_sec)
            ),
            daemon=True
        )
        self._thread.start()



    def _stop_blink_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            self._stop.set()
            self._thread.join(timeout=1.0)
        self._thread = None
        self._stop.clear()

    def _blink_loop(
        self,
        mode: str,
        period: float,
        error_on_t: float,
        error_off_t: float,
        breathe_min: float,
        breathe_max: float,
        breathe_step_sec: float,
    ) -> None:
        # --- NEW: breathe + peak wink ---
        if mode == "breathe":
            p = max(0.8, float(period))
            step = max(0.01, float(breathe_step_sec))
            vmin = max(0.0, min(1.0, float(breathe_min)))
            vmax = max(0.0, min(1.0, float(breathe_max)))
            if vmax < vmin:
                vmin, vmax = vmax, vmin

            # ---- wink parameters (tweak here) ----
            wink_off_sec = 0.1          # OFF duration at peak (sec)
            wink_phase_width = 0.06     # window around peak (0..1, fraction of cycle)

            last_wink_cycle = -1

            while not self._stop.is_set():
                now = now_mono()
                cycle = int(now // p)
                phase = (now % p) / p  # 0..1

                # triangle wave 0..1..0
                tri = (2.0 * phase) if phase < 0.5 else (2.0 * (1.0 - phase))

                # --- peak wink: once per cycle ---
                if abs(phase - 0.5) < (wink_phase_width / 2.0) and cycle != last_wink_cycle:
                    self._write(0.0)
                    if self._stop.wait(wink_off_sec):
                        break
                    last_wink_cycle = cycle

                v = vmin + (vmax - vmin) * tri
                self._write(v)

                if self._stop.wait(step):
                    break
            return

        # --- existing blink modes ---
        if mode != "error":
            half = max(0.05, period / 2.0)
            while not self._stop.is_set():
                self._write(self.on_value)
                if self._stop.wait(half):
                    break
                self._write(0.0)
                if self._stop.wait(half):
                    break
            return

        # --- error: 2 blinks then pause ---
        on_t = max(0.05, error_on_t)
        off_t = max(0.05, error_off_t)
        while not self._stop.is_set():
            self._write(self.on_value)
            if self._stop.wait(on_t):
                break
            self._write(0.0)
            if self._stop.wait(off_t):
                break
            self._write(self.on_value)
            if self._stop.wait(on_t):
                break
            self._write(0.0)
            rest = max(0.1, period - (on_t + off_t + on_t))
            if self._stop.wait(rest):
                break



    def close(self) -> None:
        self._stop_blink_thread()
        self._write(0.0)
        if not self.simulate and self._pwm is not None:
            try:
                self._pwm.close()
            except Exception:
                pass

class ButtonDriver:
    def __init__(self, pin: int, long_press_sec: float, debounce_sec: float,
                 out_q: Queue, simulate: bool = False):
        self.simulate = simulate
        self.out_q = out_q
        self.long_press_sec = long_press_sec
        self._btn = None
        self._pressed_mono: Optional[float] = None

        if not self.simulate:
            try:
                from gpiozero import Button  # type: ignore
                self._btn = Button(pin, pull_up=True, bounce_time=debounce_sec)
                self._btn.when_pressed = self._on_pressed
                self._btn.when_released = self._on_released
            except Exception as e:
                print(f"[BTN] GPIO init failed, fallback to simulate: {e}", file=sys.stderr)
                self.simulate = True

        if self.simulate:
            self._thread = Thread(target=self._stdin_loop, daemon=True)
            self._thread.start()

    def _on_pressed(self) -> None:
        self._pressed_mono = now_mono()

    def _on_released(self) -> None:
        if self._pressed_mono is None:
            return
        dur = now_mono() - self._pressed_mono
        self._pressed_mono = None
        if dur >= self.long_press_sec:
            self.out_q.put(EventMsg(EventType.BTN_LONG, f"dur={dur:.3f}"))
        else:
            self.out_q.put(EventMsg(EventType.BTN_SHORT, f"dur={dur:.3f}"))

    def _stdin_loop(self) -> None:
        print("[SIM] type 's' short, 'l' long then Enter.")
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    time.sleep(0.05)
                    continue
                line = line.strip().lower()
                if line == "s":
                    self.out_q.put(EventMsg(EventType.BTN_SHORT, "sim"))
                elif line == "l":
                    self.out_q.put(EventMsg(EventType.BTN_LONG, "sim"))
            except Exception:
                break

    def close(self) -> None:
        if not self.simulate and self._btn is not None:
            try:
                self._btn.close()
            except Exception:
                pass

# ============================================================
# Run Manager (meta open/close only)
# ============================================================

class RunManager:
    def __init__(self):
        self.run_dir: Optional[Path] = None

    def _collect_env_snapshot(self) -> dict:
        """
        Record only relevant env vars (avoid dumping everything).
        """
        keys = [
            # IMU
            "IMU_ENABLE", "IMU_PORT", "IMU_BAUD", "IMU_SERIAL_TIMEOUT",

            # Audio
            "AUDIO_ENABLE", "AUDIO_DEVICE", "AUDIO_RATE", "AUDIO_CHANNELS",
            "AUDIO_FORMAT", "AUDIO_FILE_WAV", "AUDIO_CHUNK_SEC", "AUDIO_NICE",
            "AUDIO_SIGINT_TIMEOUT_SEC", "AUDIO_SIGTERM_TIMEOUT_SEC", "AUDIO_KILL_TIMEOUT_SEC",

            # Polar (Bleak)
            "POLAR_ENABLE", "POLAR_DEVICE",
            "POLAR_SCAN_TIMEOUT", "POLAR_CONNECT_TIMEOUT",
            "POLAR_POST_CONNECT_SLEEP", "POLAR_POST_WAKE_SLEEP",
            "POLAR_FIRST_NOTIFY_TIMEOUT", "POLAR_NOTIFY_GAP_ABORT",
            "POLAR_BACKOFF_INIT", "POLAR_BACKOFF_MAX", "POLAR_BACKOFF_MULT",
            "POLAR_RECONNECT_DELAY_ON_SUCCESS",
            "POLAR_HRM_CHAR", "POLAR_BSL_CHAR", "POLAR_BATTERY_CHAR",

            # Legacy (keep)
            "POLAR_CCCD",

            # Storage override / debug
            "LOGGER_STORAGE_ROOT", "SIMULATE",
        ]
        out = {}
        for k in keys:
            if k in os.environ:
                out[k] = os.environ.get(k, "")
        return out

    def _make_run_id(self) -> str:
        t = time.strftime("%Y%m%d_%H%M%S", time.localtime(now_wall()))
        suffix = int((now_mono() * 1000) % 1_000_000)
        return f"run_{t}_{suffix:06d}"

    def open_run(self, base_dir: Path, gps_fix_at_start: bool, gps_utc: Optional[str] = None) -> Path:
        base_dir.mkdir(parents=True, exist_ok=True)
        run_id = self._make_run_id()
        run_dir = base_dir / run_id
        (run_dir / "raw").mkdir(parents=True, exist_ok=False)
        meta_dir = run_dir / "meta"
        meta_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "open": {
                "t_mono": now_mono(),
                "t_wall": now_wall(),
                "gps_fix_at_start": gps_fix_at_start,
                "gps_utc_at_start": gps_utc,
            },
            "env": self._collect_env_snapshot(),
            "close": None,
            "version": "v1.3+seq+temp_raw+polar_bleak",
        }
        atomic_write_json(meta_dir / "meta.json", meta)
        self.run_dir = run_dir
        return run_dir

    def close_run(self, ok: bool, reason: str = "") -> None:
        if not self.run_dir:
            return
        meta_path = self.run_dir / "meta" / "meta.json"
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            meta = {}
        meta["close"] = {
            "t_mono": now_mono(),
            "t_wall": now_wall(),
            "ok": ok,
            "reason": reason,
        }
        atomic_write_json(meta_path, meta)
        self.run_dir = None

# ============================================================
# Writer (unified/status)
# ============================================================

@dataclass
class UnifiedEvent:
    t_mono: float
    t_wall: float
    source: str
    name: str
    value: str
    status: str = ""

@dataclass
class StatusEvent:
    t_mono: float
    t_wall: float
    level: str
    event: str
    detail: str = ""

class UnifiedWriter:
    """
    Single writer thread:
    - Receives UnifiedEvent / StatusEvent via in_q
    - Writes:
        unified.csv: seq,t_mono,t_wall,source,name,value,status
        status.csv:  seq,t_mono,t_wall,level,event,detail
    """
    def __init__(self) -> None:
        self.in_q: "Queue[Any]" = Queue()
        self._stop = Event()
        self._thread: Optional[Thread] = None

        self._unified_fp = None
        self._status_fp = None
        self._unified_w = None
        self._status_w = None
        self._seq_unified = 0
        self._seq_status = 0

    def start(self, run_dir: Path) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("UnifiedWriter already running")
        self._stop.clear()
        self._seq_unified = 0
        self._seq_status = 0

        self._unified_fp = open(run_dir / "unified.csv", "w", newline="", encoding="utf-8")
        self._status_fp = open(run_dir / "status.csv", "w", newline="", encoding="utf-8")

        self._unified_w = csv.DictWriter(
            self._unified_fp,
            fieldnames=["seq", "t_mono", "t_wall", "source", "name", "value", "status"]
        )
        self._status_w = csv.DictWriter(
            self._status_fp,
            fieldnames=["seq", "t_mono", "t_wall", "level", "event", "detail"]
        )
        self._unified_w.writeheader()
        self._status_w.writeheader()

        self.put_status("INFO", "writer_start", f"run_dir={run_dir}")

        self._thread = Thread(target=self._loop, daemon=True)
        self._thread.start()

    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def put_unified(self, source: str, name: str, value: str, status: str = "") -> None:
        if not self.active():
            return
        self.in_q.put(UnifiedEvent(now_mono(), now_wall(), source, name, value, status))

    def put_status(self, level: str, event: str, detail: str = "") -> None:
        if not self.active():
            return
        self.in_q.put(StatusEvent(now_mono(), now_wall(), level, event, detail))

    def stop_and_drain(self, timeout_sec: float = 5.0) -> None:
        if not self._thread:
            return
        self._stop.set()

        t0 = now_mono()
        while (now_mono() - t0) < timeout_sec:
            if self.in_q.empty():
                break
            time.sleep(0.02)

        try:
            self._thread.join(timeout=1.0)
        except Exception:
            pass

        self._close_files()
        self._thread = None
        self._stop.clear()

    def _close_files(self) -> None:
        try:
            if self._unified_fp:
                self._unified_fp.flush()
                os.fsync(self._unified_fp.fileno())
                self._unified_fp.close()
        except Exception:
            pass
        try:
            if self._status_fp:
                self._status_fp.flush()
                os.fsync(self._status_fp.fileno())
                self._status_fp.close()
        except Exception:
            pass

        self._unified_fp = None
        self._status_fp = None
        self._unified_w = None
        self._status_w = None

    def _loop(self) -> None:
        assert self._unified_w is not None
        assert self._status_w is not None
        assert self._unified_fp is not None
        assert self._status_fp is not None

        while True:
            if self._stop.is_set() and self.in_q.empty():
                break

            try:
                item = self.in_q.get(timeout=0.2)
            except Empty:
                continue

            try:
                if isinstance(item, UnifiedEvent):
                    self._seq_unified += 1
                    self._unified_w.writerow({
                        "seq": str(self._seq_unified),
                        "t_mono": f"{item.t_mono:.6f}",
                        "t_wall": wall_iso(item.t_wall),
                        "source": item.source,
                        "name": item.name,
                        "value": item.value,
                        "status": item.status,
                    })
                elif isinstance(item, StatusEvent):
                    self._seq_status += 1
                    self._status_w.writerow({
                        "seq": str(self._seq_status),
                        "t_mono": f"{item.t_mono:.6f}",
                        "t_wall": wall_iso(item.t_wall),
                        "level": item.level,
                        "event": item.event,
                        "detail": item.detail,
                    })
                else:
                    self._seq_status += 1
                    self._status_w.writerow({
                        "seq": str(self._seq_status),
                        "t_mono": f"{now_mono():.6f}",
                        "t_wall": wall_iso(now_wall()),
                        "level": "WARN",
                        "event": "writer_unknown_item",
                        "detail": f"type={type(item)}",
                    })
            except Exception as e:
                try:
                    self._seq_status += 1
                    self._status_w.writerow({
                        "seq": str(self._seq_status),
                        "t_mono": f"{now_mono():.6f}",
                        "t_wall": wall_iso(now_wall()),
                        "level": "ERR",
                        "event": "writer_exception",
                        "detail": str(e),
                    })
                except Exception:
                    pass

            try:
                self._unified_fp.flush()
                self._status_fp.flush()
            except Exception:
                pass

# ============================================================
# RawWriter Base + IMURawWriter + AudioRawWriter
# ============================================================

class RawWriterBase:
    def start(self, run_dir: Path) -> None:
        raise NotImplementedError
    def stop_and_drain(self, timeout_sec: float = 5.0) -> None:
        raise NotImplementedError

@dataclass
class IMURawSample:
    ts_mono_ns: int
    ts_wall_ms: int
    seq: int
    frame11: bytes  # exactly 11 bytes

class IMURawWriter(RawWriterBase):
    RECORD_STRUCT = struct.Struct("<qqI")  # ts_mono_ns, ts_wall_ms, seq (uint32)

    def __init__(self,
                 filename: str,
                 queue_max: int = 20000,
                 flush_interval_sec: float = 1.0,
                 write_chunk: int = 512):
        self.filename = filename
        self.queue_max = max(1000, int(queue_max))
        self.flush_interval_sec = max(0.2, float(flush_interval_sec))
        self.write_chunk = max(1, int(write_chunk))

        self.in_q: "Queue[IMURawSample]" = Queue(maxsize=self.queue_max)
        self._stop = Event()
        self._thread: Optional[Thread] = None
        self._fp = None

        self._count_written = 0
        self._count_drop = 0
        self._last_flush_mono = 0.0

    def start(self, run_dir: Path) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("IMURawWriter already running")
        self._stop.clear()
        self._count_written = 0
        self._count_drop = 0
        self._last_flush_mono = now_mono()

        out_path = run_dir / "raw" / self.filename
        self._fp = open(out_path, "wb")

        # header: magic + version
        header = b"701IMU\0" + b"\x01"
        self._fp.write(header)

        self._thread = Thread(target=self._loop, daemon=True)
        self._thread.start()

    def submit(self, sample: IMURawSample) -> bool:
        try:
            self.in_q.put_nowait(sample)
            return True
        except Full:
            self._count_drop += 1
            return False

    def stats(self) -> str:
        return f"written={self._count_written} drop={self._count_drop} qsize={self.in_q.qsize()}"

    def stop_and_drain(self, timeout_sec: float = 5.0) -> None:
        if not self._thread:
            return
        self._stop.set()

        t0 = now_mono()
        while (now_mono() - t0) < timeout_sec:
            if self.in_q.empty():
                break
            time.sleep(0.02)

        try:
            self._thread.join(timeout=1.0)
        except Exception:
            pass

        try:
            if self._fp:
                self._fp.flush()
                os.fsync(self._fp.fileno())
                self._fp.close()
        except Exception:
            pass

        self._fp = None
        self._thread = None
        self._stop.clear()

    def _loop(self) -> None:
        assert self._fp is not None
        buf = bytearray()

        while True:
            if self._stop.is_set() and self.in_q.empty():
                break

            got = 0
            while got < self.write_chunk:
                try:
                    s = self.in_q.get_nowait()
                except Empty:
                    break

                if not (isinstance(s.frame11, (bytes, bytearray)) and len(s.frame11) == 11):
                    continue

                buf.extend(self.RECORD_STRUCT.pack(int(s.ts_mono_ns), int(s.ts_wall_ms), int(s.seq) & 0xFFFFFFFF))
                buf.extend(s.frame11)
                self._count_written += 1
                got += 1

            if buf:
                try:
                    self._fp.write(buf)
                    buf.clear()
                except Exception:
                    buf.clear()

            now = now_mono()
            if (now - self._last_flush_mono) >= self.flush_interval_sec:
                try:
                    self._fp.flush()
                except Exception:
                    pass
                self._last_flush_mono = now

            if got == 0:
                time.sleep(0.005)

class AudioRawWriter(RawWriterBase):
    # (unchanged from your program)
    def __init__(self,
                 device: str,
                 fmt: str,
                 rate: int,
                 channels: int,
                 filename: str,
                 chunk_sec: int = 0,
                 nice: int = 0,
                 sigint_timeout_sec: float = 8.0,
                 sigterm_timeout_sec: float = 4.0,
                 kill_timeout_sec: float = 2.0):
        self.device = device
        self.fmt = fmt
        self.rate = int(rate)
        self.channels = int(channels)
        self.filename = filename
        self.chunk_sec = max(0, int(chunk_sec))
        self.nice = int(nice)

        self.sigint_timeout_sec = max(0.5, float(sigint_timeout_sec))
        self.sigterm_timeout_sec = max(0.5, float(sigterm_timeout_sec))
        self.kill_timeout_sec = max(0.5, float(kill_timeout_sec))

        self._stop = Event()
        self._thread: Optional[Thread] = None
        self._run_dir: Optional[Path] = None

        self._proc: Optional[subprocess.Popen] = None
        self._last_exit: Optional[int] = None
        self._chunks_written = 0
        self._restarts = 0
        self._last_start_mono = 0.0
        self._lock = Lock()

    def _spawn_arecord(self, cmd: List[str]) -> subprocess.Popen:
        kwargs = {}
        if hasattr(os, "setsid"):
            kwargs["preexec_fn"] = os.setsid  # type: ignore

        return subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs
        )

    def _build_cmd(self, out_path: Path, dur_sec: int = 0) -> List[str]:
        cmd = ["arecord", "-D", self.device, "-f", self.fmt, "-r", str(self.rate), "-c", str(self.channels)]
        if dur_sec > 0:
            cmd += ["-d", str(dur_sec)]
        cmd += [str(out_path)]
        if self.nice != 0:
            cmd = ["nice", "-n", str(self.nice)] + cmd
        return cmd

    def _safe_terminate(self) -> None:
        with self._lock:
            p = self._proc
        if p is None:
            return
        try:
            if p.poll() is not None:
                return
        except Exception:
            pass

        def _wait(t: float) -> bool:
            try:
                p.wait(timeout=max(0.0, t))
                return True
            except Exception:
                return False

        def _killpg(sig: int) -> bool:
            try:
                pgid = os.getpgid(p.pid)
                os.killpg(pgid, sig)
                return True
            except Exception:
                return False

        def _killproc(sig: int) -> None:
            try:
                os.kill(p.pid, sig)
            except Exception:
                pass

        try:
            if not _killpg(signal.SIGINT):
                _killproc(signal.SIGINT)
        except Exception:
            pass
        if _wait(self.sigint_timeout_sec):
            return

        try:
            if not _killpg(signal.SIGTERM):
                _killproc(signal.SIGTERM)
        except Exception:
            pass
        if _wait(self.sigterm_timeout_sec):
            return

        try:
            if not _killpg(signal.SIGKILL):
                _killproc(signal.SIGKILL)
        except Exception:
            pass
        _wait(self.kill_timeout_sec)

    def start(self, run_dir: Path) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("AudioRawWriter already running")
        self._stop.clear()
        self._run_dir = run_dir
        self._chunks_written = 0
        self._restarts = 0
        self._last_exit = None
        self._last_start_mono = 0.0
        with self._lock:
            self._proc = None

        self._thread = Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop_and_drain(self, timeout_sec: float = 5.0) -> None:
        if not self._thread:
            return
        self._stop.set()
        try:
            self._thread.join(timeout=max(0.2, timeout_sec))
        except Exception:
            pass
        if self.is_running():
            self._safe_terminate()
        with self._lock:
            self._proc = None
        self._thread = None
        self._stop.clear()

    def is_running(self) -> bool:
        with self._lock:
            p = self._proc
        return (p is not None) and (p.poll() is None)

    def stats(self) -> str:
        age = (now_mono() - self._last_start_mono) if self._last_start_mono > 0 else -1.0
        return f"running={int(self.is_running())} chunks={self._chunks_written} restarts={self._restarts} last_exit={self._last_exit} age={age:.1f}s"

    def _loop(self) -> None:
        assert self._run_dir is not None
        raw_dir = self._run_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        if CFG.simulate:
            self._last_start_mono = now_mono()
            while not self._stop.wait(0.5):
                pass
            return

        if self.chunk_sec <= 0:
            out_path = raw_dir / self.filename
            cmd = self._build_cmd(out_path, dur_sec=0)
            self._last_start_mono = now_mono()
            try:
                with self._lock:
                    self._proc = self._spawn_arecord(cmd)
                    p = self._proc
                if p is None:
                    return

                while True:
                    if self._stop.is_set():
                        self._safe_terminate()
                        break
                    rc = p.poll()
                    if rc is not None:
                        self._last_exit = rc
                        break
                    time.sleep(0.1)

            except Exception:
                self._last_exit = -999
                self._safe_terminate()
            finally:
                with self._lock:
                    self._proc = None
            return

        idx = 1
        while True:
            if self._stop.is_set():
                break

            out_path = raw_dir / f"audio_{idx:04d}.wav"
            cmd = self._build_cmd(out_path, dur_sec=self.chunk_sec)

            self._last_start_mono = now_mono()
            try:
                with self._lock:
                    self._proc = self._spawn_arecord(cmd)
                with self._lock:
                    p = self._proc
                if p is None:
                    self._last_exit = -998
                    break

                while not self._stop.is_set():
                    rc = p.poll()
                    if rc is not None:
                        self._last_exit = rc
                        break
                    time.sleep(0.1)

                if self._stop.is_set():
                    self._safe_terminate()
                    break

                if self._stop.is_set():
                    break

                self._chunks_written += 1
                idx += 1

                if self._last_exit not in (0, None):
                    self._restarts += 1
                    time.sleep(0.3)

            except Exception:
                self._last_exit = -997
                self._restarts += 1
                time.sleep(0.5)
            finally:
                if self._stop.is_set():
                    self._safe_terminate()
                with self._lock:
                    self._proc = None

# ============================================================
# RunContext + SensorWorker Base
# ============================================================

@dataclass(frozen=True)
class RunContext:
    run_dir: Path

class SensorWorker:
    name: str = "sensor"
    def start(self, ctx: RunContext) -> None:
        raise NotImplementedError
    def stop(self) -> None:
        raise NotImplementedError
    def join(self, timeout: float = 1.0) -> None:
        raise NotImplementedError
    def health(self) -> str:
        return "ok"

# ============================================================
# AudioWorker: emits minimal health only
# ============================================================

class AudioWorker(SensorWorker):
    name = "audio"
    def __init__(self, writer: UnifiedWriter, raw_writer: AudioRawWriter, alive_interval_sec: float = 1.0):
        self.writer = writer
        self.raw_writer = raw_writer
        self.alive_interval_sec = max(0.2, float(alive_interval_sec))
        self._stop = Event()
        self._thread: Optional[Thread] = None
        self._last_emit = 0.0

    def start(self, ctx: RunContext) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._last_emit = 0.0
        self._thread = Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.writer.put_status("INFO", "worker_start", f"name={self.name} alive={self.alive_interval_sec}s")

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float = 1.0) -> None:
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def health(self) -> str:
        return self.raw_writer.stats()

    def _loop(self) -> None:
        while not self._stop.wait(0.2):
            now = now_mono()
            if (now - self._last_emit) >= self.alive_interval_sec:
                self._last_emit = now
                self.writer.put_unified("audio", "alive", "1", "ok")
                self.writer.put_unified("audio", "stats", self.raw_writer.stats(), "ok")
                if (not self.raw_writer.is_running()) and (not CFG.simulate) and (not self._stop.is_set()):
                    self.writer.put_unified("audio", "proc", "not_running", "warn")

        self.writer.put_status("INFO", "worker_stop", f"name={self.name} {self.health()}")

# ============================================================
# DummyWorker
# ============================================================

class DummyWorker(SensorWorker):
    name = "dummy"
    def __init__(self, writer: UnifiedWriter, period_sec: float = 0.2):
        self.writer = writer
        self.period_sec = max(0.05, period_sec)
        self._stop = Event()
        self._thread: Optional[Thread] = None
        self._counter = 0

    def start(self, ctx: RunContext) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._counter = 0
        self._thread = Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.writer.put_status("INFO", "worker_start", f"name={self.name} period={self.period_sec}")

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float = 1.0) -> None:
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def health(self) -> str:
        return f"count={self._counter}"

    def _loop(self) -> None:
        t0 = now_mono()
        while not self._stop.wait(self.period_sec):
            self._counter += 1
            self.writer.put_unified("dummy", "counter", str(self._counter), "OK")
            self.writer.put_unified("dummy", "uptime_s", f"{now_mono() - t0:.3f}", "OK")
            self.writer.put_unified("dummy", "temp_raw", f"{2000 + (self._counter % 20)}", "OK")
        self.writer.put_status("INFO", "worker_stop", f"name={self.name} {self.health()}")

# ============================================================
# TempWorker (DS18B20): temp_raw (milli-degC integer)
# ============================================================

class TempWorker(SensorWorker):
    name = "temp"
    def __init__(self, writer: UnifiedWriter,
                 period_sec: float = 1.0,
                 rescan_sec: float = 5.0,
                 w1_base: Path = Path("/sys/bus/w1/devices")):
        self.writer = writer
        self.period_sec = max(0.2, float(period_sec))
        self.rescan_sec = max(self.period_sec, float(rescan_sec))
        self.w1_base = w1_base

        self._stop = Event()
        self._thread: Optional[Thread] = None
        self._sensor_dirs: Dict[str, Path] = {}
        self._next_rescan_mono: float = 0.0
        self._count_ok = 0
        self._count_err = 0

    def start(self, ctx: RunContext) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._count_ok = 0
        self._count_err = 0
        self._next_rescan_mono = 0.0
        self._thread = Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.writer.put_status(
            "INFO", "worker_start",
            f"name={self.name} period={self.period_sec} rescan={self.rescan_sec} w1_base={self.w1_base}"
        )

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float = 1.0) -> None:
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def health(self) -> str:
        return f"ok={self._count_ok} err={self._count_err} sensors={len(self._sensor_dirs)}"

    def _discover(self) -> None:
        found: Dict[str, Path] = {}
        try:
            if self.w1_base.exists():
                for p in sorted(self.w1_base.glob("28-*")):
                    if p.is_dir() and (p / "w1_slave").exists():
                        found[p.name] = p
        except Exception as e:
            self.writer.put_status("WARN", "temp_discover_failed", str(e))
            return

        prev = set(self._sensor_dirs.keys())
        cur = set(found.keys())
        added = sorted(cur - prev)
        removed = sorted(prev - cur)
        self._sensor_dirs = found

        if added:
            self.writer.put_status("INFO", "temp_sensor_added", ",".join(added))
        if removed:
            self.writer.put_status("WARN", "temp_sensor_removed", ",".join(removed))

        self.writer.put_status("INFO", "temp_sensors",
                               f"count={len(cur)} ids={','.join(sorted(cur))}")

    def _read_w1_slave(self, sensor_dir: Path) -> str:
        return (sensor_dir / "w1_slave").read_text(encoding="utf-8", errors="replace")

    def _parse_temp_raw(self, text: str) -> Tuple[Optional[int], str]:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            return None, "PARSE_ERR"
        if "YES" not in lines[0]:
            return None, "CRC_FAIL"
        t_idx = text.find("t=")
        if t_idx < 0:
            return None, "NO_T_FIELD"
        raw = text[t_idx + 2:].strip()
        try:
            raw_int = int(raw.split()[0])
            return raw_int, "OK"
        except Exception:
            return None, "PARSE_ERR"

    def _read_temp(self, sensor_dir: Path, retries: int = 3) -> Tuple[Optional[int], str]:
        last = "READ_ERR"
        for _ in range(max(1, retries)):
            try:
                txt = self._read_w1_slave(sensor_dir)
                temp_raw, st = self._parse_temp_raw(txt)
                if st == "OK":
                    return temp_raw, "OK"
                last = st
            except FileNotFoundError:
                return None, "NO_FILE"
            except PermissionError:
                return None, "PERMISSION"
            except Exception:
                last = "READ_ERR"
            time.sleep(0.05)
        return None, last

    def _loop(self) -> None:
        self._discover()
        self._next_rescan_mono = now_mono() + self.rescan_sec

        while not self._stop.wait(self.period_sec):
            if now_mono() >= self._next_rescan_mono:
                self._discover()
                self._next_rescan_mono = now_mono() + self.rescan_sec

            if not self._sensor_dirs:
                self._count_err += 1
                self.writer.put_unified("temp", "w1", "", "NO_SENSOR")
                continue

            batch: List[Tuple[str, str, str]] = []
            for sensor_id in sorted(self._sensor_dirs.keys()):
                sensor_dir = self._sensor_dirs[sensor_id]
                temp_raw, st = self._read_temp(sensor_dir)

                if st == "OK" and temp_raw is not None:
                    self._count_ok += 1
                    batch.append((sensor_id, str(int(temp_raw)), "OK"))
                else:
                    self._count_err += 1
                    batch.append((sensor_id, "", st))

            for sensor_id, value, st in batch:
                self.writer.put_unified("temp", sensor_id, value, st)

        self.writer.put_status("INFO", "worker_stop", f"name={self.name} {self.health()}")

# ============================================================
# Part 2 / 3
# - PolarWorker (Bleak版)
# - GPSWorker（そのまま）
# ============================================================

# ============================================================
# PolarWorker (Bleak)
# ============================================================

def _parse_hrm_bytes(payload: bytes) -> Tuple[int, List[float], int]:
    """
    BLE Heart Rate Measurement (0x2A37) payload parser.
    Returns: (hr, rr_ms_list, flags)
    """
    if not payload:
        raise ValueError("empty_payload")

    flags = payload[0]
    hr_16bit = (flags & 0x01) != 0
    rr_present = (flags & 0x10) != 0
    energy_present = (flags & 0x08) != 0

    idx = 1

    if hr_16bit:
        if len(payload) < idx + 2:
            raise ValueError("short_hr16")
        hr = int.from_bytes(payload[idx:idx + 2], "little")
        idx += 2
    else:
        if len(payload) < idx + 1:
            raise ValueError("short_hr8")
        hr = payload[idx]
        idx += 1

    if energy_present:
        if len(payload) < idx + 2:
            raise ValueError("short_energy")
        idx += 2  # ignore

    rr_ms: List[float] = []
    if rr_present:
        while idx + 2 <= len(payload):
            rr_1024 = int.from_bytes(payload[idx:idx + 2], "little")
            idx += 2
            rr_ms.append((rr_1024 / 1024.0) * 1000.0)

    return hr, rr_ms, flags


class PolarWorker(SensorWorker):
    """
    Bleak版 Polar HRM worker.

    方針：
    - BleakClientで接続し、HRM(2A37) notify を開始
    - notify callback で HR / RR を UnifiedWriter へ書く
    - notify が来ない時間が一定以上続いたら abort → 再接続
    - すべて worker thread 内で asyncio loop を回す（他Workerに影響させない）
    """
    name = "polar"

    def __init__(self,
                 writer: UnifiedWriter,
                 device: str,
                 hrm_char: str,
                 bsl_char: str,
                 battery_char: str,
                 scan_timeout: float = 8.0,
                 connect_timeout: float = 20.0,
                 post_connect_sleep: float = 2.0,
                 post_wake_sleep: float = 0.5,
                 first_notify_timeout: float = 30.0,
                 notify_gap_abort: float = 15.0,
                 backoff_init: float = 2.0,
                 backoff_max: float = 20.0,
                 backoff_mult: float = 1.5,
                 reconnect_delay_on_success: float = 1.0,
                 alive_interval_sec: float = 1.0,
                 drop_hr_zero: bool = True,
                 emit_flags: bool = True):
        self.writer = writer
        self.device = device.strip()
        self.hrm_char = hrm_char.strip()
        self.bsl_char = bsl_char.strip()
        self.battery_char = battery_char.strip()

        self.scan_timeout = max(1.0, float(scan_timeout))
        self.connect_timeout = max(2.0, float(connect_timeout))

        self.post_connect_sleep = max(0.0, float(post_connect_sleep))
        self.post_wake_sleep = max(0.0, float(post_wake_sleep))

        self.first_notify_timeout = max(1.0, float(first_notify_timeout))
        self.notify_gap_abort = max(1.0, float(notify_gap_abort))

        self.backoff_init = max(0.2, float(backoff_init))
        self.backoff_max = max(self.backoff_init, float(backoff_max))
        self.backoff_mult = max(1.01, float(backoff_mult))
        self.reconnect_delay_on_success = max(0.0, float(reconnect_delay_on_success))

        self.alive_interval_sec = max(0.2, float(alive_interval_sec))
        self.drop_hr_zero = bool(drop_hr_zero)
        self.emit_flags = bool(emit_flags)

        self._stop = Event()
        self._thread: Optional[Thread] = None

        # counters / state
        self._last_alive_emit_mono = 0.0
        self._last_notify_mono = 0.0
        self._count_notify = 0
        self._count_valid = 0
        self._count_parse_err = 0
        self._count_drop = 0
        self._count_restart = 0
        self._count_connect = 0
        self._count_disconnect = 0

        # for status
        self._last_err: str = ""

    def start(self, ctx: RunContext) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        self._last_alive_emit_mono = 0.0
        self._last_notify_mono = now_mono()

        self._count_notify = 0
        self._count_valid = 0
        self._count_parse_err = 0
        self._count_drop = 0
        self._count_restart = 0
        self._count_connect = 0
        self._count_disconnect = 0
        self._last_err = ""

        if CFG.simulate:
            self._thread = Thread(target=self._sim_loop, daemon=True)
        else:
            self._thread = Thread(target=self._loop, daemon=True)
        self._thread.start()

        self.writer.put_status(
            "INFO", "worker_start",
            f"name={self.name} device={self.device or '(empty)'} hrm_char={self.hrm_char} "
            f"scan_timeout={self.scan_timeout}s connect_timeout={self.connect_timeout}s "
            f"notify_gap_abort={self.notify_gap_abort}s"
        )

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float = 1.0) -> None:
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def health(self) -> str:
        age = (now_mono() - self._last_notify_mono) if self._last_notify_mono > 0 else -1.0
        return (f"notify={self._count_notify} valid={self._count_valid} parse_err={self._count_parse_err} "
                f"drop={self._count_drop} restart={self._count_restart} connect={self._count_connect} "
                f"disconnect={self._count_disconnect} age={age:.1f}s last_err={self._last_err}")

    def _emit_alive_if_needed(self) -> None:
        now = now_mono()
        if (now - self._last_alive_emit_mono) >= self.alive_interval_sec:
            self._last_alive_emit_mono = now
            self.writer.put_unified("polar", "alive", "1", "ok")

    def _sim_loop(self) -> None:
        hr = 85
        self._last_notify_mono = now_mono()
        while not self._stop.wait(0.2):
            self._emit_alive_if_needed()
            hr = 80 + int((now_mono() * 3) % 30)
            rr_ms_list = [700.0 + ((now_mono() * 10) % 80), 680.0 + ((now_mono() * 10) % 50)]
            self.writer.put_unified("polar", "hr", str(hr), "ok")
            for rr in rr_ms_list:
                self.writer.put_unified("polar", "rr_ms", f"{rr:.1f}", "ok")
            self._count_valid += 1
            self._count_notify += 1
            self._last_notify_mono = now_mono()
        self.writer.put_status("INFO", "worker_stop", f"name={self.name} {self.health()}")

    # ---- Bleak helpers ----

    def _normalize_mac(self, s: str) -> str:
        return s.strip().lower()

    def _looks_like_mac(self, s: str) -> bool:
        ss = self._normalize_mac(s)
        return bool(re.fullmatch(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", ss))

    def _loop(self) -> None:
        # Import here so script still runs without bleak when POLAR_ENABLE=0
        try:
            import asyncio
            from bleak import BleakClient, BleakScanner  # type: ignore
        except Exception as e:
            self._last_err = f"bleak_import_failed:{e}"
            self.writer.put_status("ERROR", "polar_bleak_import_failed", str(e))
            return

        async def _run_async() -> None:
            if not self.device:
                self._last_err = "polar_device_empty"
                self.writer.put_status("ERROR", "polar_device_empty", "set POLAR_DEVICE")
                return

            # テスト版に寄せる：常に “今見えてる個体(dev)” をscanで掴む
            async def _find_dev_by_address(addr: str):
                return await BleakScanner.find_device_by_address(addr, timeout=self.scan_timeout)

            async def _safe_disconnect(client: BleakClient):
                try:
                    await client.disconnect()
                except Exception:
                    pass

            backoff = self.backoff_init

            while not self._stop.is_set():
                self._emit_alive_if_needed()

                try:
                    target = self.device.strip()

                    # 1) 名前指定なら discover して address を確定（現状の仕様維持）
                    if not self._looks_like_mac(target):
                        self.writer.put_status("INFO", "polar_scan", f"query={target} timeout={self.scan_timeout}")
                        devs = await BleakScanner.discover(timeout=self.scan_timeout)
                        found = None
                        q = target.lower()
                        for d in devs:
                            name = (d.name or "").lower()
                            addr = (d.address or "").lower()
                            if q in name or q == addr:
                                found = d
                                break
                        if found is None:
                            raise RuntimeError("scan_not_found")
                        target_addr = found.address
                        self.writer.put_status("INFO", "polar_scan_found", f"address={target_addr} name={found.name}")
                    else:
                        target_addr = target

                    # 2) ★ここが肝：MACでも find_device_by_address で dev を掴む
                    dev = await _find_dev_by_address(target_addr)
                    if dev is None:
                        raise TimeoutError("device not found by scan (wear it, wet electrodes, close range)")

                    first_notify_evt = asyncio.Event()
                    self._last_notify_mono = 0.0  # notifyが来た時に更新
                    last_notify_local = 0.0       # gap判定用（time.monotonicでも可）

                    def _on_notify(_sender: int, data: bytearray) -> None:
                        nonlocal last_notify_local
                        self._count_notify += 1
                        nowm = now_mono()
                        self._last_notify_mono = nowm
                        last_notify_local = nowm

                        if not first_notify_evt.is_set():
                            try:
                                first_notify_evt.set()
                            except Exception:
                                pass

                        try:
                            hr, rr_ms_list, flags = _parse_hrm_bytes(bytes(data))
                        except Exception:
                            self._count_parse_err += 1
                            return

                        if self.drop_hr_zero and hr == 0:
                            self._count_drop += 1
                            return

                        self.writer.put_unified("polar", "hr", str(hr), "ok")
                        if self.emit_flags:
                            self.writer.put_unified("polar", "flags_hex", f"0x{flags:02x}", "ok")
                        for rr in rr_ms_list:
                            self.writer.put_unified("polar", "rr_ms", f"{rr:.1f}", "ok")

                        self._count_valid += 1

                    # 3) connect
                    self._count_connect += 1
                    self.writer.put_status("INFO", "polar_connect", f"address={dev.address} name={dev.name}")

                    # テストに寄せる：BleakClient(dev, timeout=CONNECT_TIMEOUT)
                    client = BleakClient(dev, timeout=self.connect_timeout)

                    try:
                        await client.connect()
                        if not client.is_connected:
                            raise RuntimeError("connect failed")

                        # connect成功後に “connect=1” を出す（ログ意味を正す）
                        self.writer.put_unified("polar", "connect", "1", "ok")

                        if self.post_connect_sleep > 0:
                            await asyncio.sleep(self.post_connect_sleep)

                        # 4) ★wake/read: 2A38（失敗は無視）
                        try:
                            _ = await client.read_gatt_char(self.bsl_char)
                        except Exception:
                            pass

                        # battery（失敗は無視）
                        try:
                            batt = await client.read_gatt_char(self.battery_char)
                            if batt:
                                self.writer.put_unified("polar", "battery_pct", str(int(batt[0])), "ok")
                        except Exception:
                            pass

                        if self.post_wake_sleep > 0:
                            await asyncio.sleep(self.post_wake_sleep)

                        # 5) notify start（落ちたら粘らず例外→再接続）
                        await client.start_notify(self.hrm_char, _on_notify)
                        self.writer.put_status("INFO", "polar_notify_started", f"char={self.hrm_char}")

                        # 6) first notify待ち
                        try:
                            await asyncio.wait_for(first_notify_evt.wait(), timeout=self.first_notify_timeout)
                            self.writer.put_unified("polar", "first_notify", "1", "ok")
                            self.writer.put_status("INFO", "polar_first_notify", "ok")
                        except asyncio.TimeoutError:
                            raise RuntimeError("first_notify_timeout")

                        # 成功したらバックオフリセット
                        backoff = self.backoff_init

                        if self.reconnect_delay_on_success > 0:
                            await asyncio.sleep(self.reconnect_delay_on_success)

                        # 7) gap監視
                        while (not self._stop.is_set()) and client.is_connected:
                            self._emit_alive_if_needed()

                            if last_notify_local > 0:
                                gap = now_mono() - last_notify_local
                                if gap > self.notify_gap_abort:
                                    raise TimeoutError(f"no notify for {self.notify_gap_abort}s -> reconnect")

                            await asyncio.sleep(0.5)

                    finally:
                        # stop_notify（失敗OK）
                        try:
                            if client.is_connected:
                                try:
                                    await client.stop_notify(self.hrm_char)
                                except Exception:
                                    pass
                        finally:
                            await _safe_disconnect(client)

                    self._count_disconnect += 1
                    self.writer.put_unified("polar", "disconnect", "1", "ok")


                except Exception as e:
                    self._count_restart += 1
                    self._last_err = str(e)
                    self.writer.put_unified("polar", "restart", "1", "warn")
                    self.writer.put_status("WARN", "polar_restart", f"err={e} count={self._count_restart}")

                    # backoff
                    t0 = now_mono()
                    while (not self._stop.is_set()) and ((now_mono() - t0) < backoff):
                        await asyncio.sleep(0.1)
                    backoff = min(self.backoff_max, backoff * self.backoff_mult)

            return


        # Run asyncio loop in this thread
        try:
            asyncio.run(_run_async())
        except Exception as e:
            self._last_err = f"asyncio_run_failed:{e}"
            self.writer.put_status("ERROR", "polar_asyncio_run_failed", str(e))

        self.writer.put_status("INFO", "worker_stop", f"name={self.name} {self.health()}")


# ============================================================
# GPSWorker (unchanged)
# ============================================================

@dataclass
class _GPSLatest:
    last_rx_mono: float = 0.0
    fix: Optional[int] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    speed_mps: Optional[float] = None
    utc_iso: Optional[str] = None

class GPSWorker(SensorWorker):
    name = "gps"

    def __init__(self, writer: UnifiedWriter,
                 port: str = "/dev/ttyS0",
                 baud: int = 9600,
                 heartbeat_sec: float = 1.0,
                 timeout_sec: float = 2.5,
                 read_timeout: float = 0.5,
                 emit_speed: bool = True,
                 emit_utc: bool = True):
        self.writer = writer
        self.port = port
        self.baud = int(baud)
        self.heartbeat_sec = max(0.2, float(heartbeat_sec))
        self.timeout_sec = max(self.heartbeat_sec, float(timeout_sec))
        self.read_timeout = max(0.1, float(read_timeout))
        self.emit_speed = bool(emit_speed)
        self.emit_utc = bool(emit_utc)

        self._stop = Event()
        self._rx_thread: Optional[Thread] = None
        self._hb_thread: Optional[Thread] = None

        self._lock = Lock()
        self._latest = _GPSLatest()
        self._ser = None  # type: ignore
        self._ser_lock = Lock()
        self._count_rx = 0
        self._count_parse_ok = 0
        self._count_parse_err = 0
        self._count_open_err = 0

    def start(self, ctx: RunContext) -> None:
        if (self._rx_thread and self._rx_thread.is_alive()) or (self._hb_thread and self._hb_thread.is_alive()):
            return
        self._stop.clear()

        with self._lock:
            self._latest = _GPSLatest()
            self._count_rx = 0
            self._count_parse_ok = 0
            self._count_parse_err = 0
            self._count_open_err = 0

        self._rx_thread = Thread(target=self._rx_loop, daemon=True)
        self._hb_thread = Thread(target=self._heartbeat_loop, daemon=True)
        self._rx_thread.start()
        self._hb_thread.start()

        self.writer.put_status(
            "INFO", "worker_start",
            f"name={self.name} port={self.port} baud={self.baud} hb={self.heartbeat_sec}s timeout={self.timeout_sec}s"
        )

    def stop(self) -> None:
        self._stop.set()
        self._close_serial()

    # ★ここに置く
    def _close_serial(self) -> None:
        with self._ser_lock:
            ser = self._ser
            self._ser = None
        if ser is None:
            return
        try:
            ser.close()
        except Exception:
            pass

    def join(self, timeout: float = 1.0) -> None:
        t_end = now_mono() + max(0.1, timeout)
        if self._hb_thread and self._hb_thread.is_alive():
            self._hb_thread.join(timeout=max(0.0, t_end - now_mono()))
        if self._rx_thread and self._rx_thread.is_alive():
            self._rx_thread.join(timeout=max(0.0, t_end - now_mono()))

    def health(self) -> str:
        with self._lock:
            age = now_mono() - self._latest.last_rx_mono if self._latest.last_rx_mono > 0 else -1.0
        return f"rx={self._count_rx} ok={self._count_parse_ok} err={self._count_parse_err} open_err={self._count_open_err} age={age:.2f}s"

    # ---- NMEA helpers ----

    def _nmea_checksum_ok(self, line: str) -> bool:
        try:
            if not line.startswith("$"):
                return False
            star = line.rfind("*")
            if star < 0:
                return False
            body = line[1:star]
            cs_hex = line[star+1:star+3]
            calc = 0
            for ch in body:
                calc ^= ord(ch)
            return f"{calc:02X}" == cs_hex.upper()
        except Exception:
            return False

    def _dm_to_deg(self, dm: str, hemi: str) -> Optional[float]:
        if not dm:
            return None
        try:
            v = float(dm)
            deg = int(v // 100)
            minutes = v - deg * 100
            out = deg + minutes / 60.0
            if hemi in ("S", "W"):
                out = -out
            return out
        except Exception:
            return None

    def _parse_rmc(self, fields: List[str]) -> None:
        if len(fields) < 10:
            raise ValueError("rmc_short")
        status = fields[2].strip().upper()
        fix = 1 if status == "A" else 0

        lat = self._dm_to_deg(fields[3].strip(), fields[4].strip().upper() if len(fields) > 4 else "")
        lon = self._dm_to_deg(fields[5].strip(), fields[6].strip().upper() if len(fields) > 6 else "")

        speed_mps = None
        if self.emit_speed:
            sog = fields[7].strip()
            if sog:
                try:
                    speed_knots = float(sog)
                    speed_mps = speed_knots * 0.514444
                except Exception:
                    speed_mps = None

        utc_iso = None
        if self.emit_utc:
            t_str = fields[1].strip()
            d_str = fields[9].strip()
            if len(t_str) >= 6 and len(d_str) == 6:
                try:
                    hh = int(t_str[0:2]); mm = int(t_str[2:4]); ss = int(t_str[4:6])
                    dd = int(d_str[0:2]); mo = int(d_str[2:4]); yy = int(d_str[4:6]) + 2000
                    utc_iso = f"{yy:04d}-{mo:02d}-{dd:02d}T{hh:02d}:{mm:02d}:{ss:02d}Z"
                except Exception:
                    utc_iso = None

        with self._lock:
            self._latest.last_rx_mono = now_mono()
            self._latest.fix = fix
            self._latest.lat = lat
            self._latest.lon = lon
            self._latest.speed_mps = speed_mps
            if utc_iso:
                self._latest.utc_iso = utc_iso

    def _parse_gga(self, fields: List[str]) -> None:
        if len(fields) < 7:
            raise ValueError("gga_short")
        fq = fields[6].strip()
        fix = 0
        if fq:
            try:
                fix = 1 if int(fq) > 0 else 0
            except Exception:
                fix = 0

        lat = self._dm_to_deg(fields[2].strip(), fields[3].strip().upper() if len(fields) > 3 else "")
        lon = self._dm_to_deg(fields[4].strip(), fields[5].strip().upper() if len(fields) > 5 else "")

        with self._lock:
            self._latest.last_rx_mono = now_mono()
            self._latest.fix = fix
            if lat is not None:
                self._latest.lat = lat
            if lon is not None:
                self._latest.lon = lon

    def _parse_zda(self, fields: List[str]) -> None:
        if not self.emit_utc:
            return
        if len(fields) < 5:
            raise ValueError("zda_short")
        t_str = fields[1].strip()
        dd = fields[2].strip()
        mm = fields[3].strip()
        yyyy = fields[4].strip()
        if len(t_str) >= 6 and dd and mm and yyyy:
            try:
                hh = int(t_str[0:2]); mi = int(t_str[2:4]); ss = int(t_str[4:6])
                utc_iso = f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d}T{hh:02d}:{mi:02d}:{ss:02d}Z"
            except Exception:
                utc_iso = None
            if utc_iso:
                with self._lock:
                    self._latest.last_rx_mono = now_mono()
                    self._latest.utc_iso = utc_iso

    def _handle_nmea_line(self, line: str) -> None:
        line = line.strip()
        if not line or not line.startswith("$"):
            return
        if "*" in line and not self._nmea_checksum_ok(line):
            raise ValueError("checksum_fail")

        star = line.find("*")
        if star > 0:
            payload = line[1:star]
        else:
            payload = line[1:]
        fields = payload.split(",")
        msg = fields[0].upper()

        if msg.endswith("RMC"):
            self._parse_rmc(fields)
        elif msg.endswith("GGA"):
            self._parse_gga(fields)
        elif msg.endswith("ZDA"):
            self._parse_zda(fields)
        else:
            with self._lock:
                self._latest.last_rx_mono = now_mono()

    def _rx_loop(self) -> None:
        if CFG.simulate:
            lat = 35.0
            lon = 137.0
            fix = 0
            last_toggle = now_mono()
            with self._lock:
                self._latest.last_rx_mono = now_mono()
                self._latest.fix = 0
            while not self._stop.wait(0.2):
                self._count_rx += 1
                if now_mono() - last_toggle > 8.0:
                    fix = 1 - fix
                    last_toggle = now_mono()
                if fix == 1:
                    lat += 0.00005
                    lon += 0.00005
                with self._lock:
                    self._latest.last_rx_mono = now_mono()
                    self._latest.fix = fix
                    self._latest.lat = lat if fix == 1 else None
                    self._latest.lon = lon if fix == 1 else None
                    self._latest.speed_mps = 10.0 if fix == 1 else None
                    self._latest.utc_iso = "2099-01-01T00:00:00Z"
                self._count_parse_ok += 1
            return

        try:
            import serial  # type: ignore
        except Exception as e:
            self._count_open_err += 1
            self.writer.put_status("ERROR", "gps_serial_import_failed", str(e))
            return

        while not self._stop.is_set():
            try:
                ser = serial.Serial(self.port, self.baud, timeout=self.read_timeout)

                # ★self._ser に保存（stop() から close できる）
                with self._ser_lock:
                    self._ser = ser

                try:
                    self.writer.put_status("INFO", "gps_serial_open", f"port={self.port} baud={self.baud}")
                    buf_err = 0
                    while not self._stop.is_set():
                        try:
                            line_b = ser.readline()
                            if not line_b:
                                continue
                            self._count_rx += 1
                            try:
                                line = line_b.decode("ascii", errors="ignore")
                            except Exception:
                                line = ""
                            if not line:
                                continue
                            self._handle_nmea_line(line)
                            self._count_parse_ok += 1
                        except ValueError as ve:
                            self._count_parse_err += 1
                            buf_err += 1
                            if buf_err % 50 == 0:
                                self.writer.put_status("WARN", "gps_parse_err", f"count={buf_err} last={ve}")
                        except Exception as e:
                            self._count_parse_err += 1
                            self.writer.put_status("WARN", "gps_rx_exception", str(e))
                            time.sleep(0.2)
                finally:
                    with self._ser_lock:
                        if self._ser is ser:
                            self._ser = None
                    self._close_serial()


            except Exception as e:
                self._count_open_err += 1
                self.writer.put_status("ERROR", "gps_serial_open_failed", f"{e}")
                time.sleep(1.0)


    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.heartbeat_sec):
            with self._lock:
                snap = _GPSLatest(
                    last_rx_mono=self._latest.last_rx_mono,
                    fix=self._latest.fix,
                    lat=self._latest.lat,
                    lon=self._latest.lon,
                    speed_mps=self._latest.speed_mps,
                    utc_iso=self._latest.utc_iso,
                )

            age = (now_mono() - snap.last_rx_mono) if snap.last_rx_mono > 0 else 1e9
            if age > self.timeout_sec:
                st = "timeout"
                fix_v = ""
                lat_v = ""
                lon_v = ""
                spd_v = ""
                utc_v = ""
            else:
                if snap.fix == 1 and snap.lat is not None and snap.lon is not None:
                    st = "ok"
                    fix_v = "1"
                    lat_v = f"{snap.lat:.7f}"
                    lon_v = f"{snap.lon:.7f}"
                    spd_v = f"{snap.speed_mps:.3f}" if (self.emit_speed and snap.speed_mps is not None) else ""
                    utc_v = snap.utc_iso or ""
                else:
                    st = "no_fix"
                    fix_v = "0" if snap.fix is not None else ""
                    lat_v = ""
                    lon_v = ""
                    spd_v = ""
                    utc_v = snap.utc_iso or ""

            batch: List[Tuple[str, str, str]] = [
                ("fix", fix_v, st),
                ("lat", lat_v, st),
                ("lon", lon_v, st),
            ]
            if self.emit_speed:
                batch.append(("speed_mps", spd_v, st))
            if self.emit_utc:
                batch.append(("utc", utc_v, st))

            for name, val, status in batch:
                self.writer.put_unified("gps", name, val, status)

        self.writer.put_status("INFO", "worker_stop", f"name={self.name} {self.health()}")

    def get_fix(self) -> bool:
        with self._lock:
            snap = _GPSLatest(
                last_rx_mono=self._latest.last_rx_mono,
                fix=self._latest.fix,
                lat=self._latest.lat,
                lon=self._latest.lon,
                speed_mps=self._latest.speed_mps,
                utc_iso=self._latest.utc_iso,
            )
        age = (now_mono() - snap.last_rx_mono) if snap.last_rx_mono > 0 else 1e9
        if age > self.timeout_sec:
            return False
        return (snap.fix == 1 and snap.lat is not None and snap.lon is not None)

    def get_utc(self) -> Optional[str]:
        with self._lock:
            utc = self._latest.utc_iso
            last_rx = self._latest.last_rx_mono
        age = (now_mono() - last_rx) if last_rx > 0 else 1e9
        if age > self.timeout_sec:
            return None
        return utc

# ============================================================
# Part 3 / 3
# - IMUWorker（そのまま）
# - Supervisor / GPSFixWatcher / StateMachine / App / main
# - App側の PolarWorker 生成部分を Bleak版Configに追従させる
# ============================================================

# ============================================================
# IMUWorker: USB-Serial frame capture -> RawWriter + minimal facts
# ============================================================

def _checksum_ok(frame: bytes) -> bool:
    return len(frame) == 11 and ((sum(frame[:10]) & 0xFF) == frame[10])

class IMUWorker(SensorWorker):
    """
    WITMOTION BWT901CL frame capture:
    - Resync on 0x55, read 11 bytes, verify checksum.
    - Send raw frames (11 bytes) to IMURawWriter with timestamps + seq.
    - Emit minimal facts to UnifiedWriter:
        alive=1 periodically
        timeout=1 when no valid frames for imu_timeout_sec
        rx_rate_hz (windowed)
        bad_checksum_count / resync_drop_count / submit_drop_count / reconnect_count
    """
    name = "imu"

    def __init__(self,
                 writer: UnifiedWriter,
                 raw_writer: IMURawWriter,
                 port: str,
                 baud: int,
                 timeout: float,
                 reconnect: bool = True,
                 backoff0: float = 1.0,
                 backoff_max: float = 20.0,
                 alive_interval_sec: float = 1.0,
                 rate_window_sec: float = 2.0,
                 noframe_timeout_sec: float = 1.0):
        self.writer = writer
        self.raw_writer = raw_writer
        self.port = port
        self.baud = int(baud)
        self.timeout = float(timeout)

        self.reconnect = bool(reconnect)
        self.backoff0 = max(0.2, float(backoff0))
        self.backoff_max = max(self.backoff0, float(backoff_max))

        self.alive_interval_sec = max(0.2, float(alive_interval_sec))
        self.rate_window_sec = max(0.5, float(rate_window_sec))
        self.noframe_timeout_sec = max(0.2, float(noframe_timeout_sec))

        self._stop = Event()
        self._thread: Optional[Thread] = None

        self._seq = 0
        self._buf = bytearray()

        self._last_alive_emit = 0.0
        self._last_valid_mono = 0.0

        # rate window
        self._win_start = 0.0
        self._win_count = 0

        # counters
        self._count_valid = 0
        self._count_bad_checksum = 0
        self._count_resync_drop = 0
        self._count_submit_drop = 0
        self._count_serial_err = 0
        self._count_reconnect = 0

        self._ser = None  # type: ignore

    def start(self, ctx: RunContext) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        self._seq = 0
        self._buf.clear()

        now = now_mono()
        self._last_alive_emit = 0.0
        self._last_valid_mono = now
        self._win_start = now
        self._win_count = 0

        self._count_valid = 0
        self._count_bad_checksum = 0
        self._count_resync_drop = 0
        self._count_submit_drop = 0
        self._count_serial_err = 0
        self._count_reconnect = 0

        if CFG.simulate:
            self._thread = Thread(target=self._sim_loop, daemon=True)
        else:
            self._thread = Thread(target=self._loop, daemon=True)
        self._thread.start()

        self.writer.put_status("INFO", "worker_start", f"name={self.name} port={self.port} baud={self.baud}")

    def stop(self) -> None:
        self._stop.set()
        self._close_serial()

    def join(self, timeout: float = 1.0) -> None:
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def health(self) -> str:
        age = now_mono() - self._last_valid_mono if self._last_valid_mono > 0 else -1.0
        return (f"valid={self._count_valid} badcs={self._count_bad_checksum} resync_drop={self._count_resync_drop} "
                f"submit_drop={self._count_submit_drop} serial_err={self._count_serial_err} reconnect={self._count_reconnect} "
                f"age={age:.2f}s raw[{self.raw_writer.stats()}]")

    def _open_serial(self) -> None:
        try:
            import serial  # type: ignore
        except Exception as e:
            raise RuntimeError(f"pyserial_import_failed:{e}")

        self._ser = serial.Serial(
            port=self.port,
            baudrate=self.baud,
            timeout=self.timeout,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
        )
        self.writer.put_status("INFO", "imu_serial_open", f"port={self.port} baud={self.baud}")

    def _close_serial(self) -> None:
        try:
            if self._ser is not None:
                self._ser.close()
        except Exception:
            pass
        self._ser = None

    def _emit_alive(self) -> None:
        now = now_mono()
        if (now - self._last_alive_emit) >= self.alive_interval_sec:
            self._last_alive_emit = now
            self.writer.put_unified("imu", "alive", "1", "ok")

    def _emit_timeout_if_needed(self) -> None:
        age = now_mono() - self._last_valid_mono
        if age >= self.noframe_timeout_sec:
            self.writer.put_unified("imu", "timeout", "1", "warn")

    def _emit_rate_if_needed(self) -> None:
        now = now_mono()
        if (now - self._win_start) >= self.rate_window_sec:
            dt = max(1e-6, now - self._win_start)
            hz = self._win_count / dt
            self.writer.put_unified("imu", "rx_rate_hz", f"{hz:.2f}", "ok")
            self.writer.put_unified("imu", "bad_checksum_count", str(self._count_bad_checksum), "ok")
            self.writer.put_unified("imu", "resync_drop_count", str(self._count_resync_drop), "ok")
            self.writer.put_unified("imu", "submit_drop_count", str(self._count_submit_drop), "ok")
            self.writer.put_unified("imu", "reconnect_count", str(self._count_reconnect), "ok")
            self._win_start = now
            self._win_count = 0

    def _sim_loop(self) -> None:
        self._last_valid_mono = now_mono()
        fid_cycle = [0x51, 0x52, 0x53, 0x54]
        i = 0
        while not self._stop.wait(0.01):
            self._emit_alive()
            self._emit_rate_if_needed()
            self._emit_timeout_if_needed()

            fid = fid_cycle[i % len(fid_cycle)]
            i += 1
            payload = bytes([0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07])
            frame10 = bytes([0x55, fid]) + payload
            cs = sum(frame10) & 0xFF
            frame = frame10 + bytes([cs])

            self._seq += 1
            s = IMURawSample(ts_mono_ns=mono_ns(), ts_wall_ms=wall_ms(), seq=self._seq, frame11=frame)
            ok = self.raw_writer.submit(s)
            if not ok:
                self._count_submit_drop += 1

            self._count_valid += 1
            self._win_count += 1
            self._last_valid_mono = now_mono()

        self.writer.put_status("INFO", "worker_stop", f"name={self.name} {self.health()}")

    def _loop(self) -> None:
        backoff = self.backoff0

        def ensure_connected() -> bool:
            nonlocal backoff
            if self._ser is not None:
                return True
            try:
                self._open_serial()
                backoff = self.backoff0
                return True
            except Exception as e:
                self._count_serial_err += 1
                self.writer.put_status("ERROR", "imu_serial_open_failed", str(e))
                return False

        if not ensure_connected():
            if not self.reconnect:
                self.writer.put_status("ERROR", "imu_disabled", "serial_open_failed and reconnect=0")
                return

        while not self._stop.is_set():
            self._emit_alive()
            self._emit_rate_if_needed()
            self._emit_timeout_if_needed()

            if self._ser is None:
                if not self.reconnect:
                    break
                self.writer.put_unified("imu", "reconnect", "1", "warn")
                t0 = now_mono()
                while not self._stop.is_set() and (now_mono() - t0) < backoff:
                    time.sleep(0.05)
                if self._stop.is_set():
                    break
                self._count_reconnect += 1
                ok = ensure_connected()
                if not ok:
                    backoff = min(backoff * 1.5, self.backoff_max)
                continue

            try:
                chunk = self._ser.read(256)
                if chunk:
                    self._buf.extend(chunk)

                while True:
                    if len(self._buf) < 11:
                        break

                    idx = self._buf.find(b"\x55")
                    if idx < 0:
                        self._count_resync_drop += len(self._buf)
                        self._buf.clear()
                        break
                    if idx > 0:
                        self._count_resync_drop += idx
                        del self._buf[:idx]

                    if len(self._buf) < 11:
                        break

                    frame = bytes(self._buf[:11])
                    del self._buf[:11]

                    if frame[0] != 0x55:
                        continue

                    if not _checksum_ok(frame):
                        self._count_bad_checksum += 1
                        continue

                    self._seq += 1
                    sample = IMURawSample(
                        ts_mono_ns=mono_ns(),
                        ts_wall_ms=wall_ms(),
                        seq=self._seq,
                        frame11=frame
                    )
                    ok = self.raw_writer.submit(sample)
                    if not ok:
                        self._count_submit_drop += 1

                    self._count_valid += 1
                    self._win_count += 1
                    self._last_valid_mono = now_mono()

                if not chunk:
                    time.sleep(0.005)

            except Exception as e:
                self._count_serial_err += 1
                self.writer.put_status("WARN", "imu_serial_read_exception", str(e))
                self._close_serial()
                if not self.reconnect:
                    break

        self._close_serial()
        self.writer.put_status("INFO", "worker_stop", f"name={self.name} {self.health()}")

# ============================================================
# Supervisor (RawWriters + Workers run sync)
# ============================================================

class RunSupervisor:
    def __init__(self, runmgr: RunManager, writer: UnifiedWriter,
                 raw_writers: List[RawWriterBase],
                 workers: List[SensorWorker]):
        self.runmgr = runmgr
        self.writer = writer
        self.raw_writers = raw_writers
        self.workers = workers
        self._ctx: Optional[RunContext] = None

    def active(self) -> bool:
        return self.runmgr.run_dir is not None

    def start_run(self, base_dir: Path, gps_fix_at_start: bool, gps_utc: Optional[str] = None) -> RunContext:
        if self.active():
            raise RuntimeError("run already active")

        run_dir = self.runmgr.open_run(base_dir, gps_fix_at_start=gps_fix_at_start, gps_utc=gps_utc)
        ctx = RunContext(run_dir=run_dir)

        self.writer.start(run_dir)
        self.writer.put_status("INFO", "run_open", f"gps_fix_at_start={gps_fix_at_start}")
        self.writer.put_unified("state", "run", "open", "OK")

        # start RawWriters first (Audio/IMU raw files)
        for rw in self.raw_writers:
            try:
                rw.start(run_dir)
            except Exception as e:
                self.writer.put_status("ERROR", "rawwriter_start_failed", f"type={type(rw).__name__} err={e}")
                for rrw in self.raw_writers:
                    try:
                        rrw.stop_and_drain(timeout_sec=1.0)
                    except Exception:
                        pass
                self.writer.stop_and_drain(timeout_sec=1.0)
                self.runmgr.close_run(ok=False, reason=f"rawwriter_start_failed:{e}")
                raise

        # start Workers (derive facts -> unified.csv)
        for w in self.workers:
            try:
                w.start(ctx)
            except Exception as e:
                self.writer.put_status("ERROR", "worker_start_failed", f"name={getattr(w,'name','?')} err={e}")
                for ww in self.workers:
                    try:
                        ww.stop()
                    except Exception:
                        pass
                for ww in self.workers:
                    try:
                        ww.join(timeout=1.0)
                    except Exception:
                        pass
                for rw in self.raw_writers:
                    try:
                        rw.stop_and_drain(timeout_sec=1.0)
                    except Exception:
                        pass
                self.writer.stop_and_drain(timeout_sec=1.0)
                self.runmgr.close_run(ok=False, reason=f"worker_start_failed:{e}")
                raise

        self._ctx = ctx
        self.writer.put_unified("state", "state", "MEASURING", "OK")
        return ctx

    def stop_run(self, reason: str, timeout_sec: float = 5.0) -> None:
        if not self.active():
            return

        if self.writer.active():
            self.writer.put_status("INFO", "stop_begin", f"reason={reason}")
            self.writer.put_unified("state", "state", "STOPPING", "OK")

        # stop workers first (so they stop emitting)
        for w in self.workers:
            try:
                w.stop()
            except Exception as e:
                if self.writer.active():
                    self.writer.put_status("WARN", "worker_stop_failed", f"name={getattr(w,'name','?')} err={e}")

        for w in self.workers:
            try:
                w.join(timeout=1.0)
            except Exception as e:
                if self.writer.active():
                    self.writer.put_status("WARN", "worker_join_failed", f"name={getattr(w,'name','?')} err={e}")

        # stop raw writers last (so arecord/imu raw closes)
        for rw in self.raw_writers:
            try:
                rw.stop_and_drain(timeout_sec=timeout_sec)
            except Exception as e:
                if self.writer.active():
                    self.writer.put_status("WARN", "rawwriter_stop_failed", f"type={type(rw).__name__} err={e}")

        self.writer.stop_and_drain(timeout_sec=timeout_sec)
        self.runmgr.close_run(ok=True, reason=reason)
        self._ctx = None

# ============================================================
# GPS Fix Watcher
# ============================================================

class GPSFixWatcherReal:
    def __init__(self, gps_worker: "GPSWorker", out_q: Queue, poll_sec: float = 0.5):
        self.gps_worker = gps_worker
        self.out_q = out_q
        self.poll_sec = max(0.1, float(poll_sec))
        self._stop = Event()
        self._thread = Thread(target=self._loop, daemon=True)
        self._last_fix = False
        self._thread.start()

    def _loop(self) -> None:
        self._last_fix = self.gps_worker.get_fix()
        while not self._stop.wait(self.poll_sec):
            cur = self.gps_worker.get_fix()
            if cur != self._last_fix:
                self._last_fix = cur
                self.out_q.put(EventMsg(EventType.GPS_FIX_ON if cur else EventType.GPS_FIX_OFF, "gps_worker"))

    def close(self) -> None:
        self._stop.set()
        try:
            self._thread.join(timeout=1.0)
        except Exception:
            pass

# ============================================================
# State Machine
# ============================================================

Action = Callable[["App", EventMsg], None]
TransitionKey = Tuple[State, EventType]
TransitionVal = Tuple[State, Action]

def noop_action(app: "App", ev: EventMsg) -> None:
    app.log_status("INFO", "noop", f"{app.state.name} {ev.etype.name} {ev.detail}")

def ignore_btn_storage_missing(app: "App", ev: EventMsg) -> None:
    msg = f"{ev.etype.name} ignored (storage missing) {ev.detail}"
    app._pre_storage_events.append((now_mono(), now_wall(), msg))
    app.log_status("WARN", "btn_ignored_storage_missing", ev.detail)

def start_run_action(app: "App", ev: EventMsg) -> None:
    app.log_status("INFO", "btn_short", "start_request")
    if app.storage_base_dir is None:
        ignore_btn_storage_missing(app, ev)
        app.state = State.STORAGE_MISSING
        app.set_led_for_state(app.state)
        return

    gps_fix = app.gps_worker.get_fix()
    gps_utc = app.gps_worker.get_utc()

    if (not gps_fix) and (not CFG.allow_start_without_gps):
        app.log_status("WARN", "start_blocked_no_gps", "gps_fix=false")
        return

    try:
        app.supervisor.start_run(app.storage_base_dir, gps_fix_at_start=gps_fix, gps_utc=gps_utc)
    except Exception as e:
        app.log_status("ERROR", "run_start_failed", str(e))
        try:
            app.supervisor.stop_run(reason=f"start_failed:{e}", timeout_sec=1.0)
        except Exception:
            pass
        return

    app.log_status("INFO", "run_started", f"run_dir={app.runmgr.run_dir}")
    app.state = State.MEASURING
    app.set_led_for_state(State.MEASURING)

def enter_booting(app: "App", ev: EventMsg) -> None:
    app.log_status("INFO", "booting", ev.detail)
    app.set_led_for_state(State.BOOTING)

def boot_done_action(app: "App", ev: EventMsg) -> None:
    app.log_status("INFO", "boot_done", ev.detail)
    if app.storage_base_dir is None:
        app.log_status("ERROR", "usb_not_mounted", "no writable storage found")
        app.state = State.STORAGE_MISSING
        app.set_led_for_state(app.state)
        return

    app.log_status("INFO", "storage_selected", str(app.storage_base_dir))
    app.state = State.IDLE_GPS_OK if app.gps_worker.get_fix() else State.IDLE_NO_GPS
    app.set_led_for_state(app.state)

def storage_ok_action(app: "App", ev: EventMsg) -> None:
    app.storage_base_dir = app.storage.get_dir()
    app.log_status("INFO", "storage_ok", ev.detail)
    if app.storage_base_dir is None:
        app.state = State.STORAGE_MISSING
        app.set_led_for_state(app.state)
        return
    app.log_status("INFO", "storage_selected", str(app.storage_base_dir))
    app.state = State.IDLE_GPS_OK if app.gps_worker.get_fix() else State.IDLE_NO_GPS
    app.set_led_for_state(app.state)

def gps_fix_on_action(app: "App", ev: EventMsg) -> None:
    app.log_status("INFO", "gps_fix_on", ev.detail)
    if app.writer.active():
        app.writer.put_unified("gps", "fix", "1", "OK")

def gps_fix_off_action(app: "App", ev: EventMsg) -> None:
    app.log_status("WARN", "gps_fix_off", ev.detail)
    if app.writer.active():
        app.writer.put_unified("gps", "fix", "0", "WARN")

def request_stop_action(app: "App", ev: EventMsg) -> None:
    if app.writer.active():
        app.writer.put_unified("ui", "btn_long", "stop_request", "OK")
    app.request_stop(reason="user_long_press")

def stopping_done_action(app: "App", ev: EventMsg) -> None:
    app.log_status("INFO", "stop_done", ev.detail)
    app.state = State.IDLE_GPS_OK if app.gps_worker.get_fix() else State.IDLE_NO_GPS
    app.set_led_for_state(app.state)

def sig_stop_action(app: "App", ev: EventMsg) -> None:
    app.log_status("WARN", "signal_stop", ev.etype.name)
    if app.state == State.MEASURING:
        app.request_stop(reason=f"signal:{ev.etype.name}")
    else:
        app._shutdown_requested.set()

TRANSITIONS: Dict[TransitionKey, TransitionVal] = {
    (State.OFF, EventType.PWR_ON): (State.BOOTING, enter_booting),
    (State.BOOTING, EventType.BOOT_DONE): (State.BOOTING, boot_done_action),

    (State.STORAGE_MISSING, EventType.BTN_SHORT): (State.STORAGE_MISSING, ignore_btn_storage_missing),
    (State.STORAGE_MISSING, EventType.BTN_LONG):  (State.STORAGE_MISSING, ignore_btn_storage_missing),
    (State.STORAGE_MISSING, EventType.STORAGE_OK): (State.IDLE_NO_GPS, storage_ok_action),

    (State.IDLE_NO_GPS, EventType.GPS_FIX_ON): (State.IDLE_GPS_OK, gps_fix_on_action),
    (State.IDLE_GPS_OK, EventType.GPS_FIX_OFF): (State.IDLE_NO_GPS, gps_fix_off_action),

    (State.IDLE_GPS_OK, EventType.BTN_SHORT): (State.MEASURING, start_run_action),
    (State.IDLE_NO_GPS, EventType.BTN_SHORT): (State.MEASURING, start_run_action),

    (State.MEASURING, EventType.BTN_SHORT): (State.MEASURING, noop_action),
    (State.MEASURING, EventType.BTN_LONG): (State.STOPPING, request_stop_action),
    (State.STOPPING, EventType.STOP_DONE): (State.STOPPING, stopping_done_action),
}

# ============================================================
# App
# ============================================================

class App:
    def __init__(self) -> None:
        self.q: Queue[EventMsg] = Queue()
        self.state: State = State.OFF

        self.led = LEDDriver(CFG.gpio_led_pwm, CFG.led_on_value, simulate=CFG.simulate)
        self.btn = ButtonDriver(CFG.gpio_button, CFG.long_press_sec, CFG.debounce_sec, self.q, simulate=CFG.simulate)

        # ---- Storage watcher ----
        self.storage = StorageWatcher(CFG, self.q)
        self.storage_base_dir: Optional[Path] = self.storage.get_dir()

        # ---- Run / Writer ----
        self.runmgr = RunManager()
        self.writer = UnifiedWriter()

        # ============================================================
        # GPS: ALWAYS-ON
        # ============================================================
        self.gps_worker = GPSWorker(
            self.writer,
            port=CFG.gps_port,
            baud=CFG.gps_baud,
            heartbeat_sec=CFG.gps_period_sec,
            timeout_sec=CFG.gps_timeout_sec,
            read_timeout=CFG.gps_serial_read_timeout,
            emit_speed=CFG.gps_emit_speed,
            emit_utc=CFG.gps_emit_utc,
        )
        self.gps_worker.start(RunContext(run_dir=Path(".")))
        self.gps_fix = GPSFixWatcherReal(self.gps_worker, self.q, poll_sec=0.5)

        # ---- RawWriters ----
        self.imu_raw_writer: Optional[IMURawWriter] = None
        if CFG.imu_enable:
            self.imu_raw_writer = IMURawWriter(
                filename=CFG.imu_raw_filename,
                queue_max=CFG.imu_raw_queue_max,
                flush_interval_sec=CFG.imu_raw_flush_interval_sec,
                write_chunk=CFG.imu_raw_write_chunk,
            )

        self.audio_raw_writer: Optional[AudioRawWriter] = None
        if CFG.audio_enable:
            self.audio_raw_writer = AudioRawWriter(
                device=CFG.audio_device,
                fmt=CFG.audio_format,
                rate=CFG.audio_rate,
                channels=CFG.audio_channels,
                filename=CFG.audio_file_wav,
                chunk_sec=CFG.audio_chunk_sec,
                nice=CFG.audio_nice,
                sigint_timeout_sec=CFG.audio_sigint_timeout_sec,
                sigterm_timeout_sec=CFG.audio_sigterm_timeout_sec,
                kill_timeout_sec=CFG.audio_kill_timeout_sec,
            )

        self.raw_writers: List[RawWriterBase] = []
        if self.imu_raw_writer is not None:
            self.raw_writers.append(self.imu_raw_writer)
        if self.audio_raw_writer is not None:
            self.raw_writers.append(self.audio_raw_writer)

        # ============================================================
        # Workers: RUN-TIED ONLY (GPSWorker は含めない)
        # ============================================================
        self.workers: List[SensorWorker] = [
            DummyWorker(self.writer, period_sec=CFG.dummy_period_sec),
            TempWorker(
                self.writer,
                period_sec=CFG.temp_period_sec,
                rescan_sec=CFG.temp_rescan_sec,
                w1_base=CFG.temp_w1_base,
            ),
        ]

        # ---- Polar (Bleak) ----
        if CFG.polar_enable and CFG.polar_device:
            # Bleak用のデフォルトUUID（標準HRM/Battery）
            HRM_CHAR = "00002a37-0000-1000-8000-00805f9b34fb"
            BATTERY_CHAR = "00002a19-0000-1000-8000-00805f9b34fb"

            self.workers.append(
                PolarWorker(
                    writer=self.writer,
                    device=CFG.polar_device,
                    hrm_char=CFG.polar_hrm_char,
                    bsl_char=CFG.polar_bsl_char,
                    battery_char=CFG.polar_battery_char,
                    scan_timeout=CFG.polar_scan_timeout,
                    connect_timeout=CFG.polar_connect_timeout,
                    post_connect_sleep=CFG.polar_post_connect_sleep,
                    post_wake_sleep=CFG.polar_post_wake_sleep,
                    first_notify_timeout=CFG.polar_first_notify_timeout,
                    notify_gap_abort=CFG.polar_notify_gap_abort,
                    backoff_init=CFG.polar_backoff_init,
                    backoff_max=CFG.polar_backoff_max,
                    backoff_mult=CFG.polar_backoff_mult,
                    reconnect_delay_on_success=CFG.polar_reconnect_delay_on_success,
                    alive_interval_sec=CFG.polar_alive_interval_sec,
                    drop_hr_zero=CFG.polar_drop_hr_zero,
                    emit_flags=CFG.polar_emit_flags,
                )
            )

        else:
            if CFG.polar_enable and not CFG.polar_device:
                print("[WARN] POLAR_ENABLE=1 but POLAR_DEVICE is empty -> PolarWorker not added", file=sys.stderr)

        # ---- IMU ----
        if CFG.imu_enable:
            if self.imu_raw_writer is None:
                print("[WARN] IMU_ENABLE=1 but IMURawWriter is None (unexpected)", file=sys.stderr)
            else:
                self.workers.append(
                    IMUWorker(
                        writer=self.writer,
                        raw_writer=self.imu_raw_writer,
                        port=CFG.imu_port,
                        baud=CFG.imu_baud,
                        timeout=CFG.imu_serial_timeout,
                        reconnect=CFG.imu_reconnect,
                        backoff0=CFG.imu_reconnect_backoff0,
                        backoff_max=CFG.imu_reconnect_backoff_max,
                        alive_interval_sec=CFG.imu_alive_interval_sec,
                        rate_window_sec=CFG.imu_rate_window_sec,
                        noframe_timeout_sec=CFG.imu_timeout_sec,
                    )
                )
        else:
            print("[INFO] IMU disabled (set IMU_ENABLE=1 to enable)")

        # ---- Audio ----
        if CFG.audio_enable:
            if self.audio_raw_writer is None:
                print("[WARN] AUDIO_ENABLE=1 but AudioRawWriter is None (unexpected)", file=sys.stderr)
            else:
                self.workers.append(
                    AudioWorker(
                        writer=self.writer,
                        raw_writer=self.audio_raw_writer,
                        alive_interval_sec=CFG.audio_alive_interval_sec,
                    )
                )
        else:
            print("[INFO] Audio disabled (set AUDIO_ENABLE=1 to enable)")

        self.supervisor = RunSupervisor(self.runmgr, self.writer, self.raw_writers, self.workers)

        self._shutdown_requested = Event()
        self._pre_storage_events: List[Tuple[float, float, str]] = []

        self._gps_suspended = False

        signal.signal(signal.SIGINT, self._handle_sig)
        signal.signal(signal.SIGTERM, self._handle_sig)

    def _handle_sig(self, signum, frame) -> None:
        if signum == signal.SIGINT:
            self.q.put(EventMsg(EventType.SIGINT, ""))
        elif signum == signal.SIGTERM:
            self.q.put(EventMsg(EventType.SIGTERM, ""))

    # ============================================================
    # GPS suspend / resume (power-load reduction during STOPPING)
    # ============================================================
    def gps_suspend(self, reason: str = "") -> None:
        """
        STOPPING中に電源負荷を下げるため、GPSを一時停止する。
        - FixWatcher 停止（イベント発火を止める）
        - GPSWorker stop+join（UART close / read stop）
        """
        if getattr(self, "_gps_suspended", False):
            return
        self._gps_suspended = True

        self.log_status("INFO", "gps_suspend_begin", reason)

        # 1) FixWatcher stop
        try:
            if getattr(self, "gps_fix", None) is not None:
                self.gps_fix.close()
        except Exception as e:
            self.log_status("WARN", "gps_fixwatcher_close_failed", str(e))

        # 2) GPS worker stop (close serial by exiting rx loop)
        try:
            self.gps_worker.stop()
            self.gps_worker.join(timeout=1.5)

            # ★追加：join後にまだ生きていたら警告（resumeが効かない原因）
            rx_th = getattr(self.gps_worker, "_rx_thread", None)
            hb_th = getattr(self.gps_worker, "_hb_thread", None)
            if (rx_th is not None and rx_th.is_alive()) or (hb_th is not None and hb_th.is_alive()):
                self.log_status("WARN", "gps_worker_still_alive", "thread alive after join")
        except Exception as e:
            self.log_status("WARN", "gps_worker_stop_failed", str(e))


        self.log_status("INFO", "gps_suspend_done", "")

    def gps_resume(self, reason: str = "") -> None:
        """
        STOPPING処理完了後にGPSを復帰する。
        - GPSWorker start
        - FixWatcher 再作成
        """
        if not getattr(self, "_gps_suspended", False):
            return
        self._gps_suspended = False

        self.log_status("INFO", "gps_resume_begin", reason)

        # 1) GPS worker start
        try:
            self.gps_worker.start(RunContext(run_dir=Path(".")))

            # ★追加：start後に起動確認（ダメなら明示）
            rx_th = getattr(self.gps_worker, "_rx_thread", None)
            hb_th = getattr(self.gps_worker, "_hb_thread", None)
            if not ((rx_th is not None and rx_th.is_alive()) and (hb_th is not None and hb_th.is_alive())):
                self.log_status("ERROR", "gps_worker_not_running_after_start", "start() returned but threads not alive")
        except Exception as e:
            self.log_status("ERROR", "gps_worker_start_failed", str(e))
            return


        # 2) FixWatcher recreate
        try:
            self.gps_fix = GPSFixWatcherReal(self.gps_worker, self.q, poll_sec=0.5)
        except Exception as e:
            self.log_status("ERROR", "gps_fixwatcher_create_failed", str(e))

        self.log_status("INFO", "gps_resume_done", "")



    def log_status(self, level: str, event: str, detail: str = "") -> None:
        if self.writer.active():
            self.writer.put_status(level, event, detail)
        print(f"[{level}] {event} {detail}")

    def set_led_for_state(self, state: State) -> None:
        if state == State.BOOTING:
            self.led.set_mode(
                "slow_blink", CFG.boot_slow_blink_period,
                error_on_t=CFG.error_on_t, error_off_t=CFG.error_off_t
            )

        elif state == State.STORAGE_MISSING:
            self.led.set_mode(
                "error", CFG.error_pattern_period,
                error_on_t=CFG.error_on_t, error_off_t=CFG.error_off_t
            )

        elif state == State.IDLE_NO_GPS:
            self.led.set_mode(
                "blink", CFG.idle_blink_period,
                error_on_t=CFG.error_on_t, error_off_t=CFG.error_off_t
            )

        elif state == State.IDLE_GPS_OK:
            # --- NEW: "breathe" so GPS OK idle is visible but calm ---
            self.led.set_mode(
                "breathe", CFG.idle_gps_breathe_period,
                error_on_t=CFG.error_on_t, error_off_t=CFG.error_off_t,
                breathe_min=CFG.idle_gps_breathe_min,
                breathe_max=CFG.idle_gps_breathe_max,
                breathe_step_sec=CFG.idle_gps_breathe_step_sec,
            )

        elif state == State.MEASURING:
            self.led.set_mode("on", error_on_t=CFG.error_on_t, error_off_t=CFG.error_off_t)

        elif state == State.STOPPING:
            self.led.set_mode(
                "fast_blink", CFG.stopping_fast_blink_period,
                error_on_t=CFG.error_on_t, error_off_t=CFG.error_off_t
            )

        else:
            self.led.set_mode("off", error_on_t=CFG.error_on_t, error_off_t=CFG.error_off_t)


    def request_stop(self, reason: str) -> None:
        self.state = State.STOPPING
        self.set_led_for_state(State.STOPPING)

        ok = True
        err_msg = ""

        # ★追加：STOP中はGPS停止して負荷を下げる（UART close & read stop）
        self.gps_suspend(reason=f"stop:{reason}")

        try:
            try:
                self.supervisor.stop_run(reason=reason, timeout_sec=5.0)
            except Exception as e:
                ok = False
                err_msg = str(e)
                self.log_status("ERROR", "stop_failed", err_msg)
                try:
                    self.writer.stop_and_drain(timeout_sec=1.0)
                except Exception:
                    pass
                try:
                    self.runmgr.close_run(ok=False, reason=f"close_failed:{e}")
                except Exception:
                    pass
        finally:
            # ★追加：stop処理（ファイル書き込み含む）が終わったらGPS復活
            self.gps_resume(reason=f"stop_done:{reason}")

        if ok:
            self.q.put(EventMsg(EventType.STOP_DONE, reason))


    def dispatch(self, ev: EventMsg) -> None:
        self.storage_base_dir = self.storage.get_dir()

        if ev.etype in (EventType.SIGINT, EventType.SIGTERM):
            sig_stop_action(self, ev)
            return

        key = (self.state, ev.etype)

        if key not in TRANSITIONS and ev.etype in (EventType.GPS_FIX_ON, EventType.GPS_FIX_OFF):
            if ev.etype == EventType.GPS_FIX_ON:
                gps_fix_on_action(self, ev)
                if self.state == State.IDLE_NO_GPS:
                    self.state = State.IDLE_GPS_OK
            else:
                gps_fix_off_action(self, ev)
                if self.state == State.IDLE_GPS_OK:
                    self.state = State.IDLE_NO_GPS

            # ★状態が変わった可能性があるのでLED反映
            self.set_led_for_state(self.state)
            return

        if key not in TRANSITIONS:
            self.log_status(
                "INFO",
                "unhandled_event",
                f"state={self.state.name} ev={ev.etype.name} {ev.detail}"
            )
            return

        next_state, action = TRANSITIONS[key]
        prev_state = self.state

        action(self, ev)
        if self.state == prev_state:
            self.state = next_state

        # ★追加：状態遷移が起きたら必ずLEDを更新
        if self.state != prev_state:
            self.set_led_for_state(self.state)


    def run(self) -> None:
        self.q.put(EventMsg(EventType.PWR_ON, ""))
        self.dispatch(self.q.get())

        time.sleep(0.2)
        self.q.put(EventMsg(EventType.BOOT_DONE, ""))

        self.log_status("INFO", "main_loop", f"simulate={CFG.simulate} storage_dir={self.storage_base_dir}")
        self.set_led_for_state(self.state)

        while not self._shutdown_requested.is_set():
            try:
                ev = self.q.get(timeout=0.2)
            except Empty:
                continue
            self.dispatch(ev)

        self.shutdown()

    def shutdown(self) -> None:
        if self.state == State.MEASURING:
            self.request_stop(reason="shutdown")

        try:
            if getattr(self, "gps_fix", None) is not None:
                self.gps_fix.close()
        except Exception:
            pass

        try:
            self.gps_worker.stop()
            self.gps_worker.join(timeout=1.0)
        except Exception:
            pass


        self.led.close()
        self.btn.close()
        self.storage.close()
        self.log_status("INFO", "shutdown", "done")


def main() -> int:
    app = App()
    try:
        app.run()
        return 0
    except Exception as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        try:
            app.led.set_mode("error", CFG.error_pattern_period,
                             error_on_t=CFG.error_on_t, error_off_t=CFG.error_off_t)
        except Exception:
            pass
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
