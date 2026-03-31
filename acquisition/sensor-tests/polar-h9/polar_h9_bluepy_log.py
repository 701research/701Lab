import time
import csv
from datetime import datetime, timezone

from bluepy.btle import Peripheral, DefaultDelegate, BTLEDisconnectError

POLAR_MAC = "24:AC:AC:12:4E:72"
ADDR_TYPE = "random"   # まず random を推奨（ダメなら "public" に）
HRM_VALUE_HANDLE = 0x0010
HRM_CCCD_HANDLE  = 0x0011

def parse_hrm(payload: bytes):
    # Heart Rate Measurement (0x2A37) parser
    if len(payload) < 2:
        return None, []
    flags = payload[0]
    hr_16bit = flags & 0x01
    rr_present = flags & 0x10

    idx = 1
    if hr_16bit:
        if len(payload) < idx + 2:
            return None, []
        hr = int.from_bytes(payload[idx:idx+2], "little")
        idx += 2
    else:
        hr = payload[idx]
        idx += 1

    rr_ms = []
    if rr_present:
        while len(payload) >= idx + 2:
            rr_1024 = int.from_bytes(payload[idx:idx+2], "little")
            idx += 2
            rr_ms.append(int(round(rr_1024 * 1000 / 1024)))
    return hr, rr_ms

class HRDelegate(DefaultDelegate):
    def __init__(self, writer, fhandle):
        super().__init__()
        self.writer = writer
        self.fhandle = fhandle

    def handleNotification(self, cHandle, data):
        if cHandle != HRM_VALUE_HANDLE:
            return
        hr, rr = parse_hrm(data)
        if hr is None:
            return
        t = time.time()
        iso = datetime.fromtimestamp(t, tz=timezone.utc).isoformat()
        self.writer.writerow([f"{t:.6f}", iso, hr, " ".join(map(str, rr))])
        self.fhandle.flush()
        if rr:
            print(f"{iso}  HR={hr:3d} bpm  RR(ms)={rr}")
        else:
            print(f"{iso}  HR={hr:3d} bpm")

def main():
    out_csv = f"polar_h9_bluepy_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    print(f"[INFO] output: {out_csv}")
    print("[INFO] Wear Polar H9 (electrodes wet). Turn OFF phone BT. Ctrl+C to stop.\n")

    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_unix", "t_iso_utc", "hr_bpm", "rr_ms_list"])

        while True:
            try:
                p = Peripheral(POLAR_MAC, addrType=ADDR_TYPE)
                p.setDelegate(HRDelegate(w, f))

                # CCCDへ 0x0001 を書いて notify enable
                p.writeCharacteristic(HRM_CCCD_HANDLE, b"\x01\x00", withResponse=True)
                print("[OK] connected + notify enabled. waiting...")

                while True:
                    # 1秒待って通知が来たら delegate が処理する
                    p.waitForNotifications(1.0)

            except KeyboardInterrupt:
                print("\n[INFO] stopped.")
                return
            except BTLEDisconnectError:
                print("[INFO] disconnected. retrying...\n")
                time.sleep(0.5)
            except Exception as e:
                print(f"[ERR] {repr(e)}. retrying...\n")
                time.sleep(1.0)

if __name__ == "__main__":
    main()
