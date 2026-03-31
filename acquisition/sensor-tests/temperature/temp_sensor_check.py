#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DS18B20 detector (w1)
- Lists connected DS18B20 sensors under /sys/bus/w1/devices/28-*/
- Reads temperature from each sensor (best-effort)
Usage:
  python3 temp_sensor_check.py
Note:
  On Raspberry Pi, enable 1-Wire (dtoverlay=w1-gpio) and load modules (w1-gpio, w1-therm).
"""

from __future__ import annotations

import glob
import time
from pathlib import Path
from typing import Optional, Tuple, List


W1_BASE = Path("/sys/bus/w1/devices")


def _read_w1_slave(sensor_dir: Path) -> str:
    p = sensor_dir / "w1_slave"
    return p.read_text(encoding="utf-8", errors="replace")


def _parse_temp_c_from_w1(text: str) -> Tuple[Optional[float], str]:
    """
    Returns (temp_c, status)
    status:
      - "OK"         : crc OK + temp parsed
      - "CRC_FAIL"   : crc not OK
      - "NO_T_FIELD" : no 't=' field
      - "PARSE_ERR"  : cannot parse
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None, "PARSE_ERR"

    # Typical:
    #   xx xx xx ... : crc=xx YES
    #   xx xx xx ... t=23125
    crc_ok = ("YES" in lines[0])  # simple but sufficient
    if not crc_ok:
        return None, "CRC_FAIL"

    t_idx = text.find("t=")
    if t_idx < 0:
        return None, "NO_T_FIELD"

    raw = text[t_idx + 2 :].strip()
    # raw may contain trailing chars, keep digits/sign only
    # e.g. "23125" -> 23.125
    try:
        raw_int = int(raw.split()[0])
        return raw_int / 1000.0, "OK"
    except Exception:
        return None, "PARSE_ERR"


def read_temp_c(sensor_dir: Path, retries: int = 3, retry_wait_sec: float = 0.2) -> Tuple[Optional[float], str]:
    """
    Read DS18B20 temperature with small retries to avoid transient CRC failures.
    """
    last_status = "PARSE_ERR"
    for _ in range(max(1, retries)):
        try:
            text = _read_w1_slave(sensor_dir)
            temp_c, status = _parse_temp_c_from_w1(text)
            if status == "OK":
                return temp_c, "OK"
            last_status = status
        except FileNotFoundError:
            return None, "NO_FILE"
        except PermissionError:
            return None, "PERMISSION"
        except Exception:
            last_status = "READ_ERR"
        time.sleep(max(0.0, retry_wait_sec))
    return None, last_status


def list_ds18b20_dirs() -> List[Path]:
    # DS18B20 family code is usually "28-"
    paths = sorted(glob.glob(str(W1_BASE / "28-*")))
    return [Path(p) for p in paths if Path(p).is_dir()]


def main() -> int:
    if not W1_BASE.exists():
        print(f"[ERR] {W1_BASE} does not exist. 1-Wire may be disabled or modules not loaded.")
        print("      Check: sudo raspi-config -> Interface Options -> 1-Wire -> Enable")
        print("      And:   lsmod | grep -E 'w1_(gpio|therm)'")
        return 2

    sensor_dirs = list_ds18b20_dirs()
    if not sensor_dirs:
        print("[WARN] No DS18B20 found (no /sys/bus/w1/devices/28-*).")
        print("       Wiring/pull-up (4.7k), 1-Wire enable, or sensor may be missing.")
        # Still show what's under w1 for debugging
        all_devs = sorted([p.name for p in W1_BASE.iterdir() if p.is_dir()])
        print(f"       Devices under w1: {all_devs}")
        return 1

    print(f"[OK] Found {len(sensor_dirs)} sensor(s):")
    for d in sensor_dirs:
        sensor_id = d.name  # e.g. 28-00000abcdef
        temp_c, status = read_temp_c(d)
        if status == "OK" and temp_c is not None:
            print(f"  - {sensor_id}: {temp_c:.3f} °C")
        else:
            print(f"  - {sensor_id}: (read failed) status={status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
