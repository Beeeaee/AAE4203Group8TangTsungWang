"""UBX binary telemetry inspector for Group 8 field data (G08_owndata_20261030.ubx)."""
from __future__ import annotations

from collections import Counter
import csv
import json
import math
from pathlib import Path
import struct
from typing import Dict, List, Tuple

import numpy as np

from src.gnss_models import llh_to_ecef


UBX_GNSS_NAMES = {
    0: "GPS",
    1: "SBAS",
    2: "Galileo",
    3: "BeiDou",
    5: "QZSS",
    6: "GLONASS",
}

UBX_CLASS_NAMES = {
    (0x01, 0x07): "NAV-PVT",
    (0x01, 0x14): "NAV-HPPOSLLH",
    (0x01, 0x13): "NAV-HPPOSECEF",
    (0x01, 0x22): "NAV-CLOCK",
    (0x01, 0x34): "NAV-ORB",
    (0x01, 0x35): "NAV-SAT",
    (0x01, 0x3B): "NAV-SVIN",
    (0x01, 0x3C): "NAV-RELPOSNED",
    (0x01, 0x43): "NAV-SIG",
    (0x02, 0x13): "RXM-SFRBX",
    (0x02, 0x15): "RXM-RAWX",
    (0x0A, 0x04): "MON-VER",
}


def iter_ubx_frames(raw: bytes):
    """Yield (msg_class, msg_id, payload) for checksum-validated UBX frames."""
    n = len(raw)
    i = 0
    while i <= n - 8:
        if raw[i] == 0xB5 and raw[i + 1] == 0x62:
            mcls = raw[i + 2]
            mid = raw[i + 3]
            mlen = struct.unpack_from("<H", raw, i + 4)[0]
            end = i + 6 + mlen
            if end + 2 <= n:
                ck_a = 0
                ck_b = 0
                for b in raw[i + 2 : end]:
                    ck_a = (ck_a + b) & 0xFF
                    ck_b = (ck_b + ck_a) & 0xFF
                if ck_a == raw[end] and ck_b == raw[end + 1]:
                    yield mcls, mid, raw[i + 6 : end]
                    i = end + 2
                    continue
        i += 1


def inspect_ubx(ubx_path: Path, out_dir: Path) -> dict:
    """Inspect Group 8 UBX binary file and save summary + NAV-PVT reference CSV."""
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = Path(ubx_path).read_bytes()
    counts: Counter = Counter()
    mon_ver: List[str] = []
    nav_pvt_rows: List[dict] = []
    rawx_rows: List[dict] = []
    cn0_by_sys: Dict[str, List[float]] = {k: [] for k in UBX_GNSS_NAMES.values()}
    unique_sv_by_sys: Dict[str, set] = {k: set() for k in UBX_GNSS_NAMES.values()}

    for mcls, mid, payload in iter_ubx_frames(raw):
        name = UBX_CLASS_NAMES.get((mcls, mid), f"0x{mcls:02X}-0x{mid:02X}")
        counts[name] += 1

        if (mcls, mid) == (0x0A, 0x04) and len(payload) >= 40:
            sw = payload[:30].split(b"\x00", 1)[0].decode("ascii", "replace").strip()
            hw = payload[30:40].split(b"\x00", 1)[0].decode("ascii", "replace").strip()
            ext = []
            for off in range(40, len(payload), 30):
                s = payload[off : off + 30].split(b"\x00", 1)[0].decode("ascii", "replace").strip()
                if s:
                    ext.append(s)
            mon_ver = [f"SW={sw}", f"HW={hw}"] + ext

        elif (mcls, mid) == (0x01, 0x07) and len(payload) >= 92:
            i_tow = struct.unpack_from("<I", payload, 0)[0]
            year, month, day, hour, minute, sec = struct.unpack_from("<HBBBBB", payload, 4)
            fix_type = payload[20]
            num_sv = payload[23]
            lon = struct.unpack_from("<i", payload, 24)[0] * 1e-7
            lat = struct.unpack_from("<i", payload, 28)[0] * 1e-7
            height_m = struct.unpack_from("<i", payload, 32)[0] * 1e-3
            hmsl_m = struct.unpack_from("<i", payload, 36)[0] * 1e-3
            h_acc_m = struct.unpack_from("<I", payload, 40)[0] * 1e-3
            v_acc_m = struct.unpack_from("<I", payload, 44)[0] * 1e-3
            g_speed_ms = struct.unpack_from("<i", payload, 60)[0] * 1e-3
            pdop = struct.unpack_from("<H", payload, 76)[0] * 0.01
            xyz = llh_to_ecef(math.radians(lat), math.radians(lon), height_m)
            nav_pvt_rows.append({
                "i_tow_s": i_tow * 1e-3,
                "utc": f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{sec:02d}Z",
                "fix_type": fix_type,
                "num_sv": num_sv,
                "lat_deg": lat,
                "lon_deg": lon,
                "height_m": height_m,
                "hmsl_m": hmsl_m,
                "h_acc_m": h_acc_m,
                "v_acc_m": v_acc_m,
                "g_speed_ms": g_speed_ms,
                "pdop": pdop,
                "x_ecef_m": float(xyz[0]),
                "y_ecef_m": float(xyz[1]),
                "z_ecef_m": float(xyz[2]),
            })

        elif (mcls, mid) == (0x02, 0x15) and len(payload) >= 16:
            rcv_tow, week, leap_s, num_meas = struct.unpack_from("<dHbB", payload, 0)
            sys_counts = Counter()
            for m in range(num_meas):
                off = 16 + m * 32
                if off + 32 > len(payload):
                    break
                gnss_id, sv_id, sig_id, _, _, cno, _ = struct.unpack_from("<BBBBHBB", payload, off + 20)
                sys_name = UBX_GNSS_NAMES.get(gnss_id, f"ID{gnss_id}")
                sys_counts[sys_name] += 1
                cn0_by_sys.setdefault(sys_name, []).append(float(cno))
                unique_sv_by_sys.setdefault(sys_name, set()).add((sv_id))
            rawx_rows.append({
                "week": week,
                "rcv_tow_s": rcv_tow,
                "leap_s": leap_s,
                "num_meas": num_meas,
                "sys_counts": dict(sys_counts),
            })

    # Write NAV-PVT reference trajectory CSV
    pvt_csv = out_dir / "nav_pvt_reference.csv"
    if nav_pvt_rows:
        with pvt_csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(nav_pvt_rows[0].keys()))
            writer.writeheader()
            writer.writerows(nav_pvt_rows)

    speeds = np.array([r["g_speed_ms"] for r in nav_pvt_rows], dtype=float)
    # Identify initial and trailing static segments cleanly from speed profile
    static_mask = speeds <= 0.15
    init_static_end = 0
    while init_static_end < len(static_mask) and static_mask[init_static_end]:
        init_static_end += 1
    trail_static_start = len(static_mask)
    while trail_static_start > init_static_end and static_mask[trail_static_start - 1]:
        trail_static_start -= 1

    cn0_stats = {}
    for k, vals in cn0_by_sys.items():
        if vals:
            arr = np.array(vals, dtype=float)
            cn0_stats[k] = {
                "obs_count": int(len(arr)),
                "unique_sv": int(len(unique_sv_by_sys.get(k, set()))),
                "mean_dbhz": round(float(np.mean(arr)), 2),
                "median_dbhz": round(float(np.median(arr)), 2),
                "p10_dbhz": round(float(np.percentile(arr, 10)), 2),
                "p90_dbhz": round(float(np.percentile(arr, 90)), 2),
            }

    summary = {
        "file_size_bytes": len(raw),
        "message_counts": dict(counts),
        "mon_ver": mon_ver,
        "rawx_epochs": len(rawx_rows),
        "rawx_week": rawx_rows[0]["week"] if rawx_rows else None,
        "rawx_tow_start_s": rawx_rows[0]["rcv_tow_s"] if rawx_rows else None,
        "rawx_tow_end_s": rawx_rows[-1]["rcv_tow_s"] if rawx_rows else None,
        "rawx_duration_s": round(rawx_rows[-1]["rcv_tow_s"] - rawx_rows[0]["rcv_tow_s"], 3) if rawx_rows else 0.0,
        "rawx_leap_s": rawx_rows[0]["leap_s"] if rawx_rows else None,
        "nav_pvt_epochs": len(nav_pvt_rows),
        "nav_pvt_utc_start": nav_pvt_rows[0]["utc"] if nav_pvt_rows else None,
        "nav_pvt_utc_end": nav_pvt_rows[-1]["utc"] if nav_pvt_rows else None,
        "nav_pvt_pdop_mean": round(float(np.mean([r["pdop"] for r in nav_pvt_rows])), 3) if nav_pvt_rows else None,
        "nav_pvt_num_sv_mean": round(float(np.mean([r["num_sv"] for r in nav_pvt_rows])), 2) if nav_pvt_rows else None,
        "nav_pvt_speed_max_ms": round(float(np.max(speeds)), 3) if len(speeds) else None,
        "initial_static_epochs": int(init_static_end),
        "walking_epochs": int(trail_static_start - init_static_end),
        "final_static_epochs": int(len(speeds) - trail_static_start),
        "cn0_by_constellation": cn0_stats,
    }
    (out_dir / "ubx_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
