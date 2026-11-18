"""RINEX 3.0x observation/navigation parser and reference solution I/O."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.gnss_models import FREQ_HZ, cal_to_gpst


# Preferred observation priority per constellation for L1/B1I/E1 and secondary frequency
PRIMARY_CODE_PRIORITY = {
    "G": ("C1C", "C1W", "C1P", "C1X", "C1S", "C1L"),
    "E": ("C1C", "C1X", "C1B", "C1Z"),
    "C": ("C2I", "C1I", "C1X", "C1P", "C2X"),
    "J": ("C1C", "C1X", "C1S", "C1L"),
}

SECONDARY_CODE_PRIORITY = {
    "G": ("C2W", "C2X", "C2L", "C2S", "C2P", "C5Q", "C5X"),
    "E": ("C7X", "C7Q", "C5X", "C5Q", "C7I", "C5I"),
    "C": ("C7I", "C6I", "C7X", "C5X", "C5P"),
    "J": ("C2X", "C2L", "C2S", "C5Q", "C5X"),
}


def _parse_float(field: str) -> float:
    text = field.strip()
    if not text:
        return 0.0
    return float(text.replace("D", "E").replace("d", "e"))


def _split_nav_fields(line: str, has_epoch: bool = False) -> List[float]:
    if has_epoch:
        body = line[23:]
    else:
        body = line[4:]
    padded = body.ljust(76)
    vals = []
    for k in range(4 if not has_epoch else 3):
        chunk = padded[k * 19 : (k + 1) * 19]
        vals.append(_parse_float(chunk))
    return vals


def parse_rinex_nav(nav_path: Path) -> Tuple[Dict[str, List[dict]], dict]:
    """Parse RINEX 3.0x mixed navigation file into per-satellite ephemeris lists."""
    lines = Path(nav_path).read_text(encoding="utf-8", errors="ignore").splitlines()
    header = {
        "iono_alpha": np.zeros(4, dtype=float),
        "iono_beta": np.zeros(4, dtype=float),
        "gal_ai": np.zeros(3, dtype=float),
        "bds_alpha": np.zeros(4, dtype=float),
        "bds_beta": np.zeros(4, dtype=float),
        "leap_seconds": 18,
    }
    i = 0
    while i < len(lines):
        line = lines[i]
        label = line[60:80].strip() if len(line) >= 60 else ""
        if "IONOSPHERIC CORR" in label:
            tag = line[:4].strip()
            vals = [
                _parse_float(line[5:17]),
                _parse_float(line[17:29]),
                _parse_float(line[29:41]),
                _parse_float(line[41:53]),
            ]
            if tag == "GPSA":
                header["iono_alpha"] = np.array(vals, dtype=float)
            elif tag == "GPSB":
                header["iono_beta"] = np.array(vals, dtype=float)
            elif tag == "BDSA":
                header["bds_alpha"] = np.array(vals, dtype=float)
            elif tag == "BDSB":
                header["bds_beta"] = np.array(vals, dtype=float)
            elif tag == "GAL":
                header["gal_ai"] = np.array(vals[:3], dtype=float)
        elif "LEAP SECONDS" in label:
            try:
                header["leap_seconds"] = int(line[:6].strip())
            except ValueError:
                pass
        elif "END OF HEADER" in label:
            i += 1
            break
        i += 1

    nav: Dict[str, List[dict]] = {}
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        sys_id = line[0]
        if sys_id in ("R", "S"):
            i += 4
            continue
        if sys_id not in ("G", "E", "C", "J", "I"):
            i += 1
            continue
        if i + 7 >= n:
            break
        sat = line[:3].replace(" ", "0")
        sat = sys_id + f"{int(line[1:3]):02d}"
        year = int(line[4:8])
        month = int(line[9:11])
        day = int(line[12:14])
        hour = int(line[15:17])
        minute = int(line[18:20])
        sec = float(line[21:23])
        toc_week, toc_tow = cal_to_gpst(year, month, day, hour, minute, sec)
        if sys_id == "C":
            # In mixed RINEX 3 nav, BDS toc header row is BDT, convert week to GPST-aligned frame
            toc_week += 0  # kept in BDT nominal week; cal_to_gpst uses GPST_EPOCH -> BDT week+1356 equals toc_week

        o0 = _split_nav_fields(lines[i], has_epoch=True)
        o1 = _split_nav_fields(lines[i + 1])
        o2 = _split_nav_fields(lines[i + 2])
        o3 = _split_nav_fields(lines[i + 3])
        o4 = _split_nav_fields(lines[i + 4])
        o5 = _split_nav_fields(lines[i + 5])
        o6 = _split_nav_fields(lines[i + 6])
        o7 = _split_nav_fields(lines[i + 7])

        rec = {
            "sat": sat,
            "sys": sys_id,
            "toc_week": toc_week,
            "toc_tow": toc_tow,
            "af0": o0[0],
            "af1": o0[1],
            "af2": o0[2],
            "iode": o1[0],
            "crs": o1[1],
            "delta_n": o1[2],
            "M0": o1[3],
            "cuc": o2[0],
            "e": o2[1],
            "cus": o2[2],
            "sqrtA": o2[3],
            "toe": o3[0],
            "cic": o3[1],
            "OMEGA0": o3[2],
            "cis": o3[3],
            "i0": o4[0],
            "crc": o4[1],
            "omega": o4[2],
            "OMEGA_DOT": o4[3],
            "idot": o5[0],
            "data_source": o5[1],
            "week": int(round(o5[2])),
            "ura": o6[0],
            "svh": o6[1],
            "tgd1": o6[2],
            "tgd2": o6[3],
            "ttm": o7[0],
        }
        nav.setdefault(sat, []).append(rec)
        i += 8
    return nav, header


def _pick_obs_indices(obs_codes: List[str], sys_id: str, priority: Tuple[str, ...]) -> Optional[dict]:
    """Select code, carrier-phase, Doppler, and SNR slot indices for a constellation."""
    for pr_code in priority:
        if pr_code in obs_codes:
            band = pr_code[1]
            attr = pr_code[2]
            c_idx = obs_codes.index(pr_code)
            l_code = f"L{band}{attr}"
            d_code = f"D{band}{attr}"
            s_code = f"S{band}{attr}"
            return {
                "code": pr_code,
                "band": band,
                "freq_hz": FREQ_HZ[(sys_id, band)],
                "c_idx": c_idx,
                "l_idx": obs_codes.index(l_code) if l_code in obs_codes else None,
                "d_idx": obs_codes.index(d_code) if d_code in obs_codes else None,
                "s_idx": obs_codes.index(s_code) if s_code in obs_codes else None,
            }
    return None


def parse_rinex_obs(obs_path: Path, allowed_sys: Tuple[str, ...] = ("G", "E", "C", "J")) -> Tuple[List[dict], dict]:
    """Parse RINEX 3.0x observation file epoch by epoch."""
    lines = Path(obs_path).read_text(encoding="utf-8", errors="ignore").splitlines()
    obs_types: Dict[str, List[str]] = {}
    approx_xyz = np.zeros(3, dtype=float)
    i = 0
    current_sys: Optional[str] = None
    while i < len(lines):
        line = lines[i]
        label = line[60:80].strip() if len(line) >= 60 else ""
        if "APPROX POSITION XYZ" in label:
            parts = line[:60].split()
            if len(parts) >= 3:
                approx_xyz = np.array([float(parts[0]), float(parts[1]), float(parts[2])], dtype=float)
        elif "SYS / # / OBS TYPES" in label:
            if line[0] != " ":
                current_sys = line[0]
                tokens = line[7:60].split()
                obs_types[current_sys] = list(tokens)
            elif current_sys is not None:
                obs_types[current_sys].extend(line[7:60].split())
        elif "END OF HEADER" in label:
            i += 1
            break
        i += 1

    sig_map = {}
    for sys_id, codes in obs_types.items():
        if sys_id not in allowed_sys:
            continue
        p1 = _pick_obs_indices(codes, sys_id, PRIMARY_CODE_PRIORITY.get(sys_id, ()))
        p2 = _pick_obs_indices(codes, sys_id, SECONDARY_CODE_PRIORITY.get(sys_id, ()))
        sig_map[sys_id] = {"primary": p1, "secondary": p2}

    epochs: List[dict] = []
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.startswith(">"):
            i += 1
            continue
        # Header: > YYYY MM DD HH MM SS.sssssss  flag nsat
        year = int(line[2:6])
        month = int(line[7:9])
        day = int(line[10:12])
        hour = int(line[13:15])
        minute = int(line[16:18])
        sec = float(line[19:29])
        flag = int(line[31:32])
        nsat = int(line[32:35])
        week, tow = cal_to_gpst(year, month, day, hour, minute, sec)

        if flag > 1:
            i += 1 + nsat
            continue

        obs_list = []
        for k in range(1, nsat + 1):
            if i + k >= n:
                break
            sline = lines[i + k]
            if len(sline) < 4:
                continue
            sys_id = sline[0]
            if sys_id not in sig_map or sig_map[sys_id]["primary"] is None:
                continue
            try:
                prn = int(sline[1:3])
            except ValueError:
                continue
            sat = f"{sys_id}{prn:02d}"
            pmap = sig_map[sys_id]["primary"]
            smap = sig_map[sys_id]["secondary"]

            def _read_slot(slot_idx: Optional[int]) -> Tuple[float, int]:
                if slot_idx is None:
                    return math.nan, 0
                pos = 3 + slot_idx * 16
                if len(sline) <= pos:
                    return math.nan, 0
                val_str = sline[pos : pos + 14].strip()
                if not val_str:
                    return math.nan, 0
                val = float(val_str)
                lli_ch = sline[pos + 14 : pos + 15] if len(sline) > pos + 14 else " "
                lli = int(lli_ch) if lli_ch.isdigit() else 0
                return val, lli

            p1, _ = _read_slot(pmap["c_idx"])
            if not math.isfinite(p1) or p1 <= 1.0e5:
                continue
            l1_cyc, lli1 = _read_slot(pmap["l_idx"])
            d1, _ = _read_slot(pmap["d_idx"])
            snr1, _ = _read_slot(pmap["s_idx"])

            p2, l2_cyc, s2 = math.nan, math.nan, math.nan
            freq2 = math.nan
            if smap is not None:
                p2, _ = _read_slot(smap["c_idx"])
                l2_cyc, _ = _read_slot(smap["l_idx"])
                s2, _ = _read_slot(smap["s_idx"])
                freq2 = smap["freq_hz"]

            obs_list.append({
                "sat": sat,
                "sys": sys_id,
                "prn": prn,
                "code1": pmap["code"],
                "freq1": pmap["freq_hz"],
                "P1": p1,
                "L1": l1_cyc,
                "LLI1": lli1,
                "D1": d1,
                "S1": snr1,
                "code2": smap["code"] if smap else None,
                "freq2": freq2,
                "P2": p2,
                "L2": l2_cyc,
                "S2": s2,
            })

        epochs.append({
            "week": week,
            "tow": tow,
            "obs": obs_list,
        })
        i += 1 + nsat

    meta = {
        "approx_xyz": approx_xyz,
        "obs_types": obs_types,
        "sig_map": {k: {"primary": v["primary"]["code"] if v["primary"] else None,
                        "secondary": v["secondary"]["code"] if v["secondary"] else None}
                    for k, v in sig_map.items()},
    }
    return epochs, meta


def read_rtklib_pos_xyz(pos_path: Path) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read RTKLIB .pos file (GPST YYYY/MM/DD HH:MM:SS.SSS ECEF-XYZ) -> (tow, xyz, ns)."""
    tows, xyzs, nss = [], [], []
    for line in Path(pos_path).read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip() or line.startswith("%"):
            continue
        parts = line.split()
        y, m, d = [int(x) for x in parts[0].split("/")]
        hh, mm, ss = parts[1].split(":")
        _, tow = cal_to_gpst(y, m, d, int(hh), int(mm), float(ss))
        tows.append(tow)
        xyzs.append([float(parts[2]), float(parts[3]), float(parts[4])])
        nss.append(int(parts[6]))
    return np.array(tows, dtype=float), np.array(xyzs, dtype=float), np.array(nss, dtype=int)
