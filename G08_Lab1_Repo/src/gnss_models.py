"""GNSS coordinate transforms, broadcast ephemeris, and atmospheric delay models.

References:
    - IS-GPS-200N (GPS broadcast ephemeris, Klobuchar, TGD)
    - Galileo OS-SIS-ICD v2.1 (Galileo F/NAV & I/NAV ephemeris, BGD)
    - BDS-SIS-ICD-B1I-3.0 (BeiDou MEO/IGSO & GEO ephemeris, BDT offset)
    - AAE4203 Lecture Notes Weeks 1, 2, 4, 5, 6, 7
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
from typing import Iterable, Optional, Tuple

import numpy as np

# Physical and geodetic constants
C_LIGHT = 299792458.0
WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)

MU_GPS = 3.9860050e14
MU_GAL = 3.986004418e14
MU_BDS = 3.986004418e14

OMEGA_E_GPS = 7.2921151467e-5
OMEGA_E_BDS = 7.2921150e-5
REL_F = -4.442807633e-10
REL_F_BDS = -2.0 * math.sqrt(MU_BDS) / (C_LIGHT * C_LIGHT)

BDT_OFFSET_S = 14.0  # BDT = GPST - 14 s continuously
GPST_EPOCH = datetime(1980, 1, 6, 0, 0, 0)

# Carrier frequencies (Hz)
FREQ_HZ = {
    ("G", "1"): 1575.42e6,
    ("G", "2"): 1227.60e6,
    ("G", "5"): 1176.45e6,
    ("E", "1"): 1575.42e6,
    ("E", "5"): 1176.45e6,
    ("E", "7"): 1207.14e6,
    ("C", "2"): 1561.098e6,  # BDS B1I (RINEX 3 obs code C2I)
    ("C", "1"): 1575.42e6,   # BDS B1C
    ("C", "7"): 1207.14e6,   # BDS B2I (RINEX 3 obs code C7I)
    ("J", "1"): 1575.42e6,
    ("J", "2"): 1227.60e6,
    ("J", "5"): 1176.45e6,
}


def cal_to_gpst(year: int, month: int, day: int, hour: int, minute: int, sec: float) -> Tuple[int, float]:
    """Convert calendar epoch in GPST (or BDT nominal calendar) to (week, sow)."""
    if year < 80:
        year += 2000
    whole_s = int(math.floor(sec))
    frac_s = sec - whole_s
    dt = datetime(year, month, day, hour, minute, 0) + timedelta(seconds=whole_s)
    total_s = (dt - GPST_EPOCH).total_seconds() + frac_s
    week = int(math.floor(total_s / 604800.0))
    sow = total_s - week * 604800.0
    return week, sow


def gpst_diff(week1: int, tow1: float, week0: int, tow0: float) -> float:
    """Return signed time difference (t1 - t0) in seconds."""
    return (week1 - week0) * 604800.0 + (tow1 - tow0)


def wrap_half_week(dt: float) -> float:
    """Wrap time offset to [-302400, 302400] s for ephemeris validity."""
    while dt > 302400.0:
        dt -= 604800.0
    while dt < -302400.0:
        dt += 604800.0
    return dt


def ecef_to_llh(xyz: np.ndarray) -> Tuple[float, float, float]:
    """Convert ECEF (m) to WGS-84 geodetic (lat_rad, lon_rad, h_m)."""
    x, y, z = float(xyz[0]), float(xyz[1]), float(xyz[2])
    p = math.hypot(x, y)
    lon = math.atan2(y, x)
    if p < 1e-9:
        lat = math.copysign(math.pi / 2.0, z)
        h = abs(z) - WGS84_A * math.sqrt(1.0 - WGS84_E2)
        return lat, lon, h
    lat = math.atan2(z, p * (1.0 - WGS84_E2))
    for _ in range(10):
        sin_lat = math.sin(lat)
        n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
        h = p / math.cos(lat) - n
        new_lat = math.atan2(z, p * (1.0 - WGS84_E2 * n / (n + h)))
        if abs(new_lat - lat) < 1e-13:
            lat = new_lat
            break
        lat = new_lat
    sin_lat = math.sin(lat)
    n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    h = p / max(math.cos(lat), 1e-12) - n
    return lat, lon, h


def llh_to_ecef(lat_rad: float, lon_rad: float, h_m: float) -> np.ndarray:
    """Convert WGS-84 (lat_rad, lon_rad, h_m) to ECEF (m)."""
    s_lat = math.sin(lat_rad)
    c_lat = math.cos(lat_rad)
    n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * s_lat * s_lat)
    x = (n + h_m) * c_lat * math.cos(lon_rad)
    y = (n + h_m) * c_lat * math.sin(lon_rad)
    z = (n * (1.0 - WGS84_E2) + h_m) * s_lat
    return np.array([x, y, z], dtype=float)


def ecef_to_enu_matrix(lat_rad: float, lon_rad: float) -> np.ndarray:
    """Return 3x3 rotation matrix R converting delta-ECEF vectors into ENU."""
    s_lat, c_lat = math.sin(lat_rad), math.cos(lat_rad)
    s_lon, c_lon = math.sin(lon_rad), math.cos(lon_rad)
    return np.array([
        [-s_lon,          c_lon,           0.0],
        [-s_lat * c_lon, -s_lat * s_lon,   c_lat],
        [ c_lat * c_lon,  c_lat * s_lon,   s_lat],
    ], dtype=float)


def sat_az_el(rx_ecef: np.ndarray, sat_ecef: np.ndarray) -> Tuple[float, float]:
    """Compute azimuth and elevation angles (rad) from receiver to satellite."""
    if np.linalg.norm(rx_ecef) < 1.0e5:
        return 0.0, math.pi / 4.0
    lat, lon, _ = ecef_to_llh(rx_ecef)
    r_mat = ecef_to_enu_matrix(lat, lon)
    enu = r_mat @ (sat_ecef - rx_ecef)
    horiz = math.hypot(enu[0], enu[1])
    el = math.atan2(enu[2], horiz)
    az = math.atan2(enu[0], enu[1])
    if az < 0.0:
        az += 2.0 * math.pi
    return az, el


def select_ephemeris(records: Iterable[dict], sat: str, week: int, tow: float) -> Optional[dict]:
    """Select the healthy broadcast ephemeris record closest to transmission time."""
    if not records:
        return None
    sys_id = sat[0]
    if sys_id == "C":
        # BDS nav toc/toe in RINEX are expressed in BDT = GPST - 14 s
        t_eval_tow = tow - BDT_OFFSET_S
    else:
        t_eval_tow = tow
    max_age = {"G": 14400.0, "J": 14400.0, "E": 14400.0, "C": 14400.0}.get(sys_id, 14400.0)
    best = None
    best_score = float("inf")
    for eph in records:
        if eph.get("svh", 0.0) != 0.0:
            continue
        if sys_id == "E":
            # Prefer I/NAV (bits 0 or 2 or bit 9 set) when multiple streams exist; fall back to F/NAV
            dt = abs(gpst_diff(week, t_eval_tow, eph["toc_week"], eph["toc_tow"]))
            if dt > max_age:
                continue
            src = int(round(eph.get("data_source", 0.0)))
            inav_pref = 0.0 if (src & 0x205) else 10.0
            score = dt + inav_pref
        else:
            dt = abs(gpst_diff(week, t_eval_tow, eph["toc_week"], eph["toc_tow"]))
            if dt > max_age:
                continue
            score = dt
        if score < best_score:
            best_score = score
            best = eph
    return best


def compute_sat_state(eph: dict, tx_week: int, tx_tow: float) -> Tuple[np.ndarray, float, float]:
    """Propagate Keplerian broadcast ephemeris to transmission time.

    Returns:
        sat_pos: ECEF position (m)
        sat_clk: Satellite clock bias including relativity (s)
        tgd_s: Applicable single-frequency L1/E1/B1I group delay (s)
    """
    sys_id = eph["sat"][0]
    prn = int(eph["sat"][1:])
    if sys_id == "C":
        mu, omega_e, rel_f = MU_BDS, OMEGA_E_BDS, REL_F_BDS
        # Broadcast toc/toe in mixed RINEX nav for BDS are in BDT
        t_sys_tow = tx_tow - BDT_OFFSET_S
        toe_week = int(eph["week"]) + 1356
        tk = wrap_half_week(gpst_diff(tx_week, t_sys_tow, toe_week, eph["toe"]))
        tc = wrap_half_week(gpst_diff(tx_week, t_sys_tow, eph["toc_week"], eph["toc_tow"]))
    else:
        mu, omega_e, rel_f = (MU_GAL if sys_id == "E" else MU_GPS), OMEGA_E_GPS, REL_F
        toe_week = int(eph["week"])
        if toe_week == 0:
            toe_week = eph["toc_week"]
        tk = wrap_half_week(gpst_diff(tx_week, tx_tow, toe_week, eph["toe"]))
        tc = wrap_half_week(gpst_diff(tx_week, tx_tow, eph["toc_week"], eph["toc_tow"]))

    a = eph["sqrtA"] ** 2
    n0 = math.sqrt(mu / (a ** 3))
    n = n0 + eph["delta_n"]
    mk = eph["M0"] + n * tk

    ek = mk
    e = eph["e"]
    for _ in range(15):
        ek_next = mk + e * math.sin(ek)
        if abs(ek_next - ek) < 1e-13:
            ek = ek_next
            break
        ek = ek_next

    sin_ek = math.sin(ek)
    cos_ek = math.cos(ek)
    denom = 1.0 - e * cos_ek
    vk = math.atan2(math.sqrt(max(1.0 - e * e, 0.0)) * sin_ek, cos_ek - e)
    phi_k = vk + eph["omega"]

    s2p, c2p = math.sin(2.0 * phi_k), math.cos(2.0 * phi_k)
    du = eph["cus"] * s2p + eph["cuc"] * c2p
    dr = eph["crs"] * s2p + eph["crc"] * c2p
    di = eph["cis"] * s2p + eph["cic"] * c2p

    uk = phi_k + du
    rk = a * denom + dr
    ik = eph["i0"] + di + eph["idot"] * tk

    x_orb = rk * math.cos(uk)
    y_orb = rk * math.sin(uk)
    cos_ik, sin_ik = math.cos(ik), math.sin(ik)

    is_bds_geo = (sys_id == "C") and (prn <= 5 or prn >= 59 or abs(eph["i0"]) < 0.35)
    if is_bds_geo:
        # BDS-SIS-ICD GEO orbit transformation: Rz(OMEGA_E * tk) * Rx(-5 deg)
        om_k = eph["OMEGA0"] + eph["OMEGA_DOT"] * tk - omega_e * eph["toe"]
        c_om, s_om = math.cos(om_k), math.sin(om_k)
        xg = x_orb * c_om - y_orb * cos_ik * s_om
        yg = x_orb * s_om + y_orb * cos_ik * c_om
        zg = y_orb * sin_ik

        phi_p = math.radians(-5.0)
        cp, sp = math.cos(phi_p), math.sin(phi_p)
        th = omega_e * tk
        ct, st = math.cos(th), math.sin(th)
        y_rot = yg * cp + zg * sp
        z_rot = -yg * sp + zg * cp
        xk = xg * ct + y_rot * st
        yk = -xg * st + y_rot * ct
        zk = z_rot
    else:
        om_k = eph["OMEGA0"] + (eph["OMEGA_DOT"] - omega_e) * tk - omega_e * eph["toe"]
        c_om, s_om = math.cos(om_k), math.sin(om_k)
        xk = x_orb * c_om - y_orb * cos_ik * s_om
        yk = x_orb * s_om + y_orb * cos_ik * c_om
        zk = y_orb * sin_ik

    dtr = rel_f * e * eph["sqrtA"] * sin_ek
    clk = eph["af0"] + eph["af1"] * tc + eph["af2"] * tc * tc + dtr

    if sys_id == "E":
        src = int(round(eph.get("data_source", 0.0)))
        # F/NAV uses BGD(E1,E5a) scaled; I/NAV E1-B uses BGD(E1,E5b) (tgd2) when available
        if (src & 0x205) and eph.get("tgd2", 0.0) != 0.0:
            tgd_s = eph["tgd2"]
        else:
            tgd_s = eph.get("tgd1", 0.0)
    else:
        tgd_s = eph.get("tgd1", 0.0)

    return np.array([xk, yk, zk], dtype=float), clk, tgd_s


def sagnac_delay(sat_ecef: np.ndarray, rx_ecef: np.ndarray) -> float:
    """Earth-rotation (Sagnac) range correction in meters (Week 5 / Lecture 4)."""
    return OMEGA_E_GPS / C_LIGHT * (sat_ecef[0] * rx_ecef[1] - sat_ecef[1] * rx_ecef[0])


def klobuchar_delay(
    lat_rad: float,
    lon_rad: float,
    el_rad: float,
    az_rad: float,
    tow_s: float,
    alpha: np.ndarray,
    beta: np.ndarray,
    freq_hz: float = 1575.42e6,
) -> float:
    """Klobuchar broadcast ionospheric delay in meters (scaled to freq_hz)."""
    if el_rad <= 0.0 or alpha is None or beta is None or np.allclose(alpha, 0.0):
        return 0.0
    lat_sc = lat_rad / math.pi
    lon_sc = lon_rad / math.pi
    el_sc = el_rad / math.pi

    psi = 0.0137 / (el_sc + 0.11) - 0.022
    phi_i = max(-0.416, min(0.416, lat_sc + psi * math.cos(az_rad)))
    lam_i = lon_sc + psi * math.sin(az_rad) / max(math.cos(phi_i * math.pi), 1e-6)
    phi_m = phi_i + 0.064 * math.cos((lam_i - 1.617) * math.pi)

    t = 43200.0 * lam_i + tow_s
    t = t % 86400.0

    amp = max(0.0, sum(alpha[k] * (phi_m ** k) for k in range(4)))
    per = max(72000.0, sum(beta[k] * (phi_m ** k) for k in range(4)))
    x = 2.0 * math.pi * (t - 50400.0) / per
    f_map = 1.0 + 16.0 * ((0.53 - el_sc) ** 3)

    if abs(x) < 1.57:
        delay_s = f_map * (5.0e-9 + amp * (1.0 - x * x / 2.0 + (x ** 4) / 24.0))
    else:
        delay_s = f_map * 5.0e-9

    freq_scale = (1575.42e6 / freq_hz) ** 2
    return C_LIGHT * delay_s * freq_scale


def saastamoinen_delay(
    el_rad: float,
    h_m: float,
    lat_rad: float = 0.3893,
    rel_hum: float = 0.7,
) -> float:
    """Saastamoinen zenith + obliquity tropospheric delay in meters (Week 5)."""
    if el_rad <= 0.0 or h_m < -1000.0 or h_m > 1e5:
        return 0.0
    h_clip = max(0.0, min(h_m, 15000.0))
    pres = 1013.25 * ((1.0 - 2.2557e-5 * h_clip) ** 5.2568)
    temp = 15.0 - 6.5e-3 * h_clip + 273.16
    e_v = 6.108 * rel_hum * math.exp((17.15 * temp - 4684.0) / (temp - 38.45))

    sin_el = max(math.sin(el_rad), 0.05)
    trph = 0.0022768 * pres / (1.0 - 0.00266 * math.cos(2.0 * lat_rad) - 0.00028 * (h_clip / 1000.0))
    trpw = 0.002277 * (1255.0 / temp + 0.05) * e_v
    return (trph + trpw) / sin_el
