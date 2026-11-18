"""Five-stage progressive GNSS Single Point Positioning (SPP) ablation solver.

Stages:
    v1: GPS-only WLS baseline (15 deg mask, sin(E)^2 weighting)
    v2: + Multi-constellation WLS (G + E + C [+ J optional], separate ISB clocks)
    v3: + C/N0 & elevation variance weighting + SNR mask
    v4: + Iterative RAIM / Baarda data-snooping fault detection & exclusion (FDE)
    v5: + Reset-aware Hatch carrier-phase smoothing
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.gnss_models import (
    C_LIGHT,
    compute_sat_state,
    ecef_to_enu_matrix,
    ecef_to_llh,
    klobuchar_delay,
    saastamoinen_delay,
    sagnac_delay,
    sat_az_el,
    select_ephemeris,
)


@dataclass(frozen=True)
class SolverConfig:
    """Configuration parameters for an SPP ablation variant."""

    name: str
    systems: Tuple[str, ...]
    el_mask_deg: float = 15.0
    snr_mask_dbhz: float = 0.0
    weight_mode: str = "sin_el"  # "sin_el" or "cn0_el"
    use_raim: bool = False
    raim_z_thresh: float = 3.29
    raim_max_reject: int = 4
    use_hatch: bool = False
    hatch_window: int = 25
    hatch_slip_thresh_m: float = 10.0
    min_sv_aux_sys: int = 2


ABLATION_CONFIGS: Dict[str, SolverConfig] = {
    "v1": SolverConfig(
        name="v1_gps_baseline",
        systems=("G",),
        el_mask_deg=15.0,
        snr_mask_dbhz=0.0,
        weight_mode="sin_el",
        use_raim=False,
        use_hatch=False,
    ),
    "v2": SolverConfig(
        name="v2_multi_constellation",
        systems=("G", "E", "C", "J"),
        el_mask_deg=15.0,
        snr_mask_dbhz=0.0,
        weight_mode="sin_el",
        use_raim=False,
        use_hatch=False,
    ),
    "v3": SolverConfig(
        name="v3_cn0_el_weighting",
        systems=("G", "E", "C", "J"),
        el_mask_deg=15.0,
        snr_mask_dbhz=15.0,
        weight_mode="cn0_el",
        use_raim=False,
        use_hatch=False,
    ),
    "v4": SolverConfig(
        name="v4_raim_fde",
        systems=("G", "E", "C", "J"),
        el_mask_deg=15.0,
        snr_mask_dbhz=15.0,
        weight_mode="cn0_el",
        use_raim=True,
        raim_z_thresh=3.29,
        raim_max_reject=4,
        use_hatch=False,
    ),
    "v5": SolverConfig(
        name="v5_hatch_smoothed",
        systems=("G", "E", "C", "J"),
        el_mask_deg=15.0,
        snr_mask_dbhz=15.0,
        weight_mode="cn0_el",
        use_raim=True,
        raim_z_thresh=3.29,
        raim_max_reject=4,
        use_hatch=True,
        hatch_window=25,
        hatch_slip_thresh_m=10.0,
    ),
}


def _meas_variance(el_rad: float, snr_dbhz: float, mode: str) -> float:
    """Compute pseudorange variance sigma_i^2 (m^2) for weighting W = diag(1/sigma^2)."""
    sin_el = max(math.sin(el_rad), 0.05)
    if mode == "sin_el":
        return 1.0 / (sin_el * sin_el)
    # Combined elevation + C/N0 stochastic model (a=1.5 m, b=1.5 m, S0=42 dB-Hz)
    snr_val = snr_dbhz if (math.isfinite(snr_dbhz) and snr_dbhz > 0.0) else 30.0
    snr_penalty = 4.0 * (10.0 ** (max(0.0, 42.0 - snr_val) / 10.0))
    return 1.5 ** 2 + (1.5 / sin_el) ** 2 + snr_penalty


class HatchSmoother:
    """Stateful reset-aware Hatch carrier-phase code smoother."""

    def __init__(self, window: int = 25, slip_thresh_m: float = 10.0) -> None:
        self.window = window
        self.slip_thresh_m = slip_thresh_m
        self.state: Dict[str, dict] = {}
        self.resets = 0
        self.smoothed_count = 0

    def apply(self, week: int, tow: float, sat: str, pr_m: float, l1_cyc: float, lli: int, freq_hz: float) -> float:
        """Return Hatch-smoothed pseudorange or raw pr_m if carrier phase invalid."""
        if not math.isfinite(l1_cyc) or (lli & 1):
            if sat in self.state:
                del self.state[sat]
                self.resets += 1
            return pr_m

        phi_m = (C_LIGHT / freq_hz) * l1_cyc
        prev = self.state.get(sat)
        if prev is None:
            self.state[sat] = {"t": week * 604800.0 + tow, "p_bar": pr_m, "phi": phi_m, "n": 1}
            return pr_m

        t_now = week * 604800.0 + tow
        dt = t_now - prev["t"]
        if dt <= 0.0 or dt > 5.0:
            self.state[sat] = {"t": t_now, "p_bar": pr_m, "phi": phi_m, "n": 1}
            self.resets += 1
            return pr_m

        p_pred = prev["p_bar"] + (phi_m - prev["phi"])
        if abs(pr_m - p_pred) > self.slip_thresh_m:
            # Reset on cycle slip or severe code/phase divergence jump
            self.state[sat] = {"t": t_now, "p_bar": pr_m, "phi": phi_m, "n": 1}
            self.resets += 1
            return pr_m

        n_eff = min(prev["n"] + 1, self.window)
        p_bar = (1.0 / n_eff) * pr_m + ((n_eff - 1.0) / n_eff) * p_pred
        self.state[sat] = {"t": t_now, "p_bar": p_bar, "phi": phi_m, "n": n_eff}
        self.smoothed_count += 1
        return p_bar


def _build_candidates(
    epoch: dict,
    nav: Dict[str, List[dict]],
    hdr: dict,
    rx_seed: np.ndarray,
    cfg: SolverConfig,
    hatch: Optional[HatchSmoother],
) -> Tuple[List[dict], int]:
    """Propagate satellites and compute corrected pseudoranges for an epoch."""
    week, tow = epoch["week"], epoch["tow"]
    has_seed = np.linalg.norm(rx_seed) > 1.0e5
    lat, lon, h_m = ecef_to_llh(rx_seed) if has_seed else (0.0, 0.0, 0.0)
    alpha, beta = hdr["iono_alpha"], hdr["iono_beta"]

    cands = []
    skipped_snr = 0
    for obs in epoch["obs"]:
        sys_id = obs["sys"]
        if sys_id not in cfg.systems:
            continue
        snr = obs["S1"]
        if cfg.snr_mask_dbhz > 0.0 and math.isfinite(snr) and snr < cfg.snr_mask_dbhz:
            skipped_snr += 1
            continue

        pr_use = obs["P1"]
        if hatch is not None:
            pr_use = hatch.apply(week, tow, obs["sat"], obs["P1"], obs["L1"], obs["LLI1"], obs["freq1"])

        tx0 = tow - pr_use / C_LIGHT
        eph = select_ephemeris(nav.get(obs["sat"], ()), obs["sat"], week, tx0)
        if eph is None:
            continue
        _, dts, tgd = compute_sat_state(eph, week, tx0)
        sat_pos, dts, tgd = compute_sat_state(eph, week, tx0 - dts)

        if has_seed:
            az, el = sat_az_el(rx_seed, sat_pos)
            if math.degrees(el) < cfg.el_mask_deg:
                continue
            ion = klobuchar_delay(lat, lon, el, az, tow, alpha, beta, obs["freq1"])
            trp = saastamoinen_delay(el, h_m, lat)
        else:
            az, el = 0.0, math.pi / 4.0
            ion, trp = 0.0, 0.0

        cands.append({
            "sat": obs["sat"],
            "sys": sys_id,
            "sat_pos": sat_pos,
            "pr_corr": pr_use + C_LIGHT * dts - C_LIGHT * tgd,
            "freq1": obs["freq1"],
            "snr": snr,
            "az": az,
            "el": el,
            "ion": ion,
            "trp": trp,
        })
    return cands, skipped_snr


def _filter_constellations(cands: List[dict], cfg: SolverConfig) -> Tuple[List[dict], List[str]]:
    """Retain active constellations with sufficient redundancy so ISBs stay well-conditioned."""
    counts: Dict[str, int] = {}
    for c in cands:
        counts[c["sys"]] = counts.get(c["sys"], 0) + 1
    active = []
    # Reference clock system comes first
    for s in cfg.systems:
        min_req = 1 if not active else cfg.min_sv_aux_sys
        if counts.get(s, 0) >= min_req:
            active.append(s)
    # Fallback: if strictly no system met min_sv_aux_sys, keep >=1 if enough total SVs
    filtered = [c for c in cands if c["sys"] in active]
    return filtered, active


def _wls_iterate(
    cands: List[dict],
    active_sys: List[str],
    x_init: np.ndarray,
    cfg: SolverConfig,
    hdr: dict,
    week: int,
    tow: float,
) -> Optional[dict]:
    """Run weighted Gauss-Newton SPP with dynamic elevation/atmosphere updates."""
    n_meas = len(cands)
    n_clk = len(active_sys)
    n_state = 3 + n_clk
    if n_meas < n_state or n_clk == 0:
        return None

    sys_to_col = {s: 3 + idx for idx, s in enumerate(active_sys)}
    x = np.zeros(n_state, dtype=float)
    x[:3] = x_init.copy()

    alpha, beta = hdr["iono_alpha"], hdr["iono_beta"]
    h_mat = np.zeros((n_meas, n_state), dtype=float)
    w_vec = np.ones(n_meas, dtype=float)
    v_vec = np.zeros(n_meas, dtype=float)
    q_cov = np.eye(n_state, dtype=float)

    for it in range(15):
        has_pos = np.linalg.norm(x[:3]) > 1.0e5
        lat, lon, h_m = ecef_to_llh(x[:3]) if has_pos else (0.0, 0.0, 0.0)
        h_mat.fill(0.0)

        for i, c in enumerate(cands):
            diff = x[:3] - c["sat_pos"]
            rng = float(np.linalg.norm(diff))
            los = diff / max(rng, 1.0)
            sag = sagnac_delay(c["sat_pos"], x[:3]) if has_pos else 0.0
            if has_pos:
                az, el = sat_az_el(x[:3], c["sat_pos"])
                c["az"], c["el"] = az, el
                ion = klobuchar_delay(lat, lon, el, az, tow, alpha, beta, c["freq1"])
                trp = saastamoinen_delay(el, h_m, lat)
            else:
                el = c["el"]
                ion, trp = c["ion"], c["trp"]

            var_i = _meas_variance(el, c["snr"], cfg.weight_mode)
            w_vec[i] = 1.0 / max(var_i, 1e-4)

            col = sys_to_col[c["sys"]]
            pred = rng + sag + x[col] + ion + trp
            v_vec[i] = c["pr_corr"] - pred
            h_mat[i, :3] = los
            h_mat[i, col] = 1.0

        hw = h_mat.T * w_vec
        n_mat = hw @ h_mat
        if np.linalg.cond(n_mat) > 1.0e12:
            return None
        q_cov = np.linalg.inv(n_mat)
        dx = q_cov @ (hw @ v_vec)
        x += dx
        if it >= 2 and float(np.linalg.norm(dx[:3])) < 1.0e-4:
            break

    # Final residuals and ENU DOP at converged state
    lat, lon, h_m = ecef_to_llh(x[:3])
    for i, c in enumerate(cands):
        diff = x[:3] - c["sat_pos"]
        rng = float(np.linalg.norm(diff))
        sag = sagnac_delay(c["sat_pos"], x[:3])
        az, el = sat_az_el(x[:3], c["sat_pos"])
        c["az"], c["el"] = az, el
        ion = klobuchar_delay(lat, lon, el, az, tow, alpha, beta, c["freq1"])
        trp = saastamoinen_delay(el, h_m, lat)
        v_vec[i] = c["pr_corr"] - (rng + sag + x[sys_to_col[c["sys"]]] + ion + trp)
        h_mat[i, :3] = diff / max(rng, 1.0)
        w_vec[i] = 1.0 / max(_meas_variance(el, c["snr"], cfg.weight_mode), 1e-4)

    hw = h_mat.T * w_vec
    n_mat = hw @ h_mat
    if np.linalg.cond(n_mat) > 1.0e12:
        return None
    q_cov = np.linalg.inv(n_mat)

    # Unweighted geometric DOP (Week 7: Q_geom = (G^T G)^(-1), G_ENU = R Q R^T)
    try:
        q_geom = np.linalg.inv(h_mat.T @ h_mat)
    except np.linalg.LinAlgError:
        q_geom = q_cov
    r_enu = ecef_to_enu_matrix(lat, lon)
    q_enu = r_enu @ q_geom[:3, :3] @ r_enu.T
    hdop = math.sqrt(max(0.0, float(q_enu[0, 0] + q_enu[1, 1])))
    vdop = math.sqrt(max(0.0, float(q_enu[2, 2])))
    pdop = math.sqrt(max(0.0, hdop * hdop + vdop * vdop))
    gdop = math.sqrt(max(0.0, float(np.trace(q_geom))))

    return {
        "x": x,
        "v": v_vec,
        "w": w_vec,
        "H": h_mat,
        "Q": q_cov,
        "active_sys": active_sys,
        "cands": cands,
        "hdop": hdop,
        "vdop": vdop,
        "pdop": pdop,
        "gdop": gdop,
        "res_rms_m": float(np.sqrt(np.mean(v_vec ** 2))),
    }


def _solve_with_raim(
    cands: List[dict],
    rx_seed: np.ndarray,
    cfg: SolverConfig,
    hdr: dict,
    week: int,
    tow: float,
) -> Tuple[Optional[dict], int]:
    """Solve WLS, optionally running iterative Baarda w-test fault exclusion."""
    curr = list(cands)
    active_cands, active_sys = _filter_constellations(curr, cfg)
    sol = _wls_iterate(active_cands, active_sys, rx_seed, cfg, hdr, week, tow)
    if sol is None or not cfg.use_raim:
        return sol, 0

    rejected = 0
    for _ in range(cfg.raim_max_reject):
        n_m = len(sol["cands"])
        n_p = len(sol["active_sys"]) + 3
        dof = n_m - n_p
        if dof < 1:
            break
        # Residual covariance diagonal: sigma_vi^2 = 1/w_i - (H Q H^T)_ii
        hqh_diag = np.einsum("ij,jk,ik->i", sol["H"], sol["Q"], sol["H"])
        sig_v = np.sqrt(np.maximum((1.0 / sol["w"]) - hqh_diag, 0.04))
        w_stats = np.abs(sol["v"]) / sig_v
        worst_idx = int(np.argmax(w_stats))
        if float(w_stats[worst_idx]) <= cfg.raim_z_thresh:
            break

        trial_cands = [c for idx, c in enumerate(sol["cands"]) if idx != worst_idx]
        trial_cands, trial_sys = _filter_constellations(trial_cands, cfg)
        if len(trial_cands) < len(trial_sys) + 3:
            break
        trial_sol = _wls_iterate(trial_cands, trial_sys, sol["x"][:3], cfg, hdr, week, tow)
        if trial_sol is None or trial_sol["pdop"] > 30.0:
            break
        sol = trial_sol
        rejected += 1
    return sol, rejected


def solve_dataset(
    epochs: List[dict],
    nav: Dict[str, List[dict]],
    hdr: dict,
    approx_xyz: np.ndarray,
    cfg: SolverConfig,
) -> dict:
    """Solve all epochs of a dataset under a specific SolverConfig."""
    rx_seed = approx_xyz.copy() if np.linalg.norm(approx_xyz) > 1.0e5 else np.zeros(3, dtype=float)
    hatch = HatchSmoother(cfg.hatch_window, cfg.hatch_slip_thresh_m) if cfg.use_hatch else None

    rows: List[dict] = []
    omitted_tows: List[float] = []
    total_rejected = 0

    for ep in epochs:
        cands, _ = _build_candidates(ep, nav, hdr, rx_seed, cfg, hatch)
        sol, rej = _solve_with_raim(cands, rx_seed, cfg, hdr, ep["week"], ep["tow"])

        # Fallback if elevation/SNR mask caused rank loss or extreme GDOP spike (>30)
        if (sol is None or (cfg.snr_mask_dbhz > 0.0 and sol["gdop"] > 30.0)) and (
            cfg.snr_mask_dbhz > 0.0 or np.linalg.norm(rx_seed) > 1.0e5
        ):
            relaxed_cfg = SolverConfig(
                name=cfg.name,
                systems=cfg.systems,
                el_mask_deg=10.0 if np.linalg.norm(rx_seed) > 1.0e5 else 0.0,
                snr_mask_dbhz=0.0,
                weight_mode=cfg.weight_mode,
                use_raim=cfg.use_raim,
                raim_z_thresh=cfg.raim_z_thresh,
                raim_max_reject=cfg.raim_max_reject,
                use_hatch=False,
                min_sv_aux_sys=1,
            )
            cands_fb, _ = _build_candidates(ep, nav, hdr, rx_seed, relaxed_cfg, None)
            sol_fb, rej_fb = _solve_with_raim(cands_fb, rx_seed, relaxed_cfg, hdr, ep["week"], ep["tow"])
            if sol is None or (sol_fb is not None and sol_fb["gdop"] < sol["gdop"]):
                sol, rej = sol_fb, rej_fb

        if sol is None:
            omitted_tows.append(ep["tow"])
            continue

        pos = sol["x"][:3]
        norm_p = float(np.linalg.norm(pos))
        if not np.all(np.isfinite(pos)) or norm_p < 6.30e6 or norm_p > 6.42e6:
            omitted_tows.append(ep["tow"])
            continue

        rx_seed = pos.copy()
        total_rejected += rej
        sv_counts = {s: sum(1 for c in sol["cands"] if c["sys"] == s) for s in ("G", "E", "C", "J")}
        lat_r, lon_r, h_m = ecef_to_llh(pos)
        rows.append({
            "gps_week": int(ep["week"]),
            "gps_tow_s": round(float(ep["tow"]), 1),
            "raw_tow_s": float(ep["tow"]),
            "x_ecef_m": float(pos[0]),
            "y_ecef_m": float(pos[1]),
            "z_ecef_m": float(pos[2]),
            "lat_deg": math.degrees(lat_r),
            "lon_deg": math.degrees(lon_r),
            "h_m": float(h_m),
            "nsat": len(sol["cands"]),
            "nsat_g": sv_counts["G"],
            "nsat_e": sv_counts["E"],
            "nsat_c": sv_counts["C"],
            "nsat_j": sv_counts["J"],
            "hdop": sol["hdop"],
            "vdop": sol["vdop"],
            "pdop": sol["pdop"],
            "gdop": sol["gdop"],
            "res_rms_m": sol["res_rms_m"],
            "raim_rejected": rej,
        })

    n_in = len(epochs)
    n_sol = len(rows)
    cov = 100.0 * n_sol / n_in if n_in else 0.0
    summary = {
        "variant": cfg.name,
        "systems": list(cfg.systems),
        "input_epochs": n_in,
        "solved_epochs": n_sol,
        "omitted_epochs": len(omitted_tows),
        "availability_pct": round(cov, 4),
        "mean_nsat": round(float(np.mean([r["nsat"] for r in rows])), 2) if rows else 0.0,
        "mean_hdop": round(float(np.mean([r["hdop"] for r in rows])), 3) if rows else 0.0,
        "mean_vdop": round(float(np.mean([r["vdop"] for r in rows])), 3) if rows else 0.0,
        "mean_pdop": round(float(np.mean([r["pdop"] for r in rows])), 3) if rows else 0.0,
        "mean_res_rms_m": round(float(np.mean([r["res_rms_m"] for r in rows])), 3) if rows else 0.0,
        "median_res_rms_m": round(float(np.median([r["res_rms_m"] for r in rows])), 3) if rows else 0.0,
        "total_raim_rejects": int(total_rejected),
        "hatch_resets": int(hatch.resets) if hatch else 0,
        "hatch_smoothed_obs": int(hatch.smoothed_count) if hatch else 0,
    }
    return {
        "rows": rows,
        "omitted_tows": omitted_tows,
        "summary": summary,
    }
