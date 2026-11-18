"""Generate publication-grade 300-DPI figures for AAE4203 Lab 1 Report (Group 8)."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.gnss_models import (
    C_LIGHT,
    compute_sat_state,
    ecef_to_enu_matrix,
    ecef_to_llh,
    sat_az_el,
    select_ephemeris,
)
from src.rinex_io import parse_rinex_nav, parse_rinex_obs, read_rtklib_pos_xyz
from src.ubx_inspector import iter_ubx_frames, UBX_GNSS_NAMES
import struct


plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.titleweight": "bold",
    "axes.labelsize": 9,
    "legend.fontsize": 8,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "axes.grid": True,
    "grid.alpha": 0.3,
})

SYS_COLORS = {
    "G": "#1f77b4",
    "E": "#ff7f0e",
    "C": "#2ca02c",
    "J": "#9467bd",
    "GPS": "#1f77b4",
    "Galileo": "#ff7f0e",
    "BeiDou": "#2ca02c",
    "QZSS": "#9467bd",
    "GLONASS": "#8c564b",
    "SBAS": "#7f7f7f",
}


def make_fig2_raw_analysis(out_path: Path) -> None:
    """Figure 2: Own-data skyplot, timeline/PDOP/speed, and C/N0 distributions."""
    eps, meta = parse_rinex_obs(REPO / "data/owndata/G08_owndata_20261030.obs")
    nav, _ = parse_rinex_nav(REPO / "data/owndata/G08_owndata_20261030.nav")
    v5_df = pd.read_csv(REPO / "outputs/owndata/v5_details.csv")
    pvt_df = pd.read_csv(REPO / "outputs/owndata/nav_pvt_reference.csv")

    rx_pos = np.median(v5_df[["x_ecef_m", "y_ecef_m", "z_ecef_m"]].values, axis=0)
    # Sample every 5 epochs for smooth clean skyplot tracks
    sky_tracks = {}
    for ep in eps[::5]:
        for o in ep["obs"]:
            if o["sys"] not in ("G", "E", "C", "J"):
                continue
            eph = select_ephemeris(nav.get(o["sat"], ()), o["sat"], ep["week"], ep["tow"] - o["P1"] / C_LIGHT)
            if eph is None:
                continue
            pos, _, _ = compute_sat_state(eph, ep["week"], ep["tow"] - o["P1"] / C_LIGHT)
            az, el = sat_az_el(rx_pos, pos)
            el_deg = math.degrees(el)
            if el_deg > 0.0:
                sky_tracks.setdefault(o["sat"], []).append((az, 90.0 - el_deg))

    # Extract actual UBX C/N0 arrays per constellation
    cn0_lists = {k: [] for k in ("GPS", "Galileo", "BeiDou", "QZSS", "GLONASS", "SBAS")}
    raw_bytes = (REPO / "data/owndata/G08_owndata_20261030.ubx").read_bytes()
    for mcls, mid, payload in iter_ubx_frames(raw_bytes):
        if (mcls, mid) == (0x02, 0x15) and len(payload) >= 16:
            num_meas = payload[11]
            for m in range(num_meas):
                off = 16 + m * 32
                if off + 32 > len(payload):
                    break
                gnss_id, _, _, _, _, cno, _ = struct.unpack_from("<BBBBHBB", payload, off + 20)
                name = UBX_GNSS_NAMES.get(gnss_id)
                if name in cn0_lists and cno > 0:
                    cn0_lists[name].append(float(cno))

    fig = plt.figure(figsize=(12.6, 4.2))
    gs = fig.add_gridspec(1, 3, width_ratios=[1.05, 1.35, 1.0], wspace=0.44)

    # Panel (a) Skyplot
    ax1 = fig.add_subplot(gs[0, 0], projection="polar")
    ax1.set_theta_zero_location("N")
    ax1.set_theta_direction(-1)
    ax1.set_ylim(0, 90)
    ax1.set_yticks([15, 45, 75])
    ax1.set_yticklabels(["75°", "45°", "15°"], fontsize=7)
    ax1.tick_params(axis="x", pad=3)
    th = np.linspace(0, 2 * np.pi, 360)
    ax1.plot(th, np.full_like(th, 75.0), "--", color="#d62728", lw=1.0, label="15° Mask")
    plotted_sys = set()
    for sat, pts in sorted(sky_tracks.items()):
        s = sat[0]
        azs, r_z = zip(*pts)
        lbl = {"G": "GPS", "E": "Galileo", "C": "BeiDou", "J": "QZSS"}[s] if s not in plotted_sys else None
        plotted_sys.add(s)
        ax1.plot(azs, r_z, "-", color=SYS_COLORS[s], lw=1.6, alpha=0.85, label=lbl)
        ax1.plot(azs[-1], r_z[-1], "o", color=SYS_COLORS[s], ms=3.5)
        ax1.text(azs[-1], max(5.0, r_z[-1] - 3.5), sat, fontsize=6.5, color=SYS_COLORS[s], ha="center")
    ax1.set_title("(a) G08 Skyplot (Block X Plaza)", pad=12)
    ax1.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3, frameon=True, fontsize=7)

    # Panel (b) Time series: active SVs, PDOP, motion speed
    ax2 = fig.add_subplot(gs[0, 1])
    t_rel_v5 = v5_df["gps_tow_s"].values - v5_df["gps_tow_s"].values[0]
    t_rel_pvt = pvt_df["i_tow_s"].values - v5_df["gps_tow_s"].values[0]
    ax2.axvspan(0, 62.5, color="#e6f5c9", alpha=0.5, label="Initial Static (0–62 s)")
    ax2.axvspan(528, 548, color="#cbd5e8", alpha=0.5, label="Final Static (528–547 s)")
    l1, = ax2.plot(t_rel_v5, v5_df["nsat"].values, color="#1f77b4", lw=1.3, label="v5 Used SVs")
    ax2.set_xlabel("Elapsed Survey Time (s)")
    ax2.set_ylabel("Used Satellites (count)", color="#1f77b4")
    ax2.set_ylim(0, 26)
    ax2_r = ax2.twinx()
    ax2_r.grid(False)
    l2, = ax2_r.plot(t_rel_v5, v5_df["pdop"].values, color="#d62728", lw=1.0, ls="-", label="v5 PDOP")
    l3, = ax2_r.plot(t_rel_pvt, pvt_df["g_speed_ms"].values, color="#ff7f0e", lw=1.1, alpha=0.9, label="NAV-PVT Speed (m/s)")
    ax2_r.set_ylabel("PDOP / Speed (m/s)", color="#d62728")
    ax2_r.set_ylim(0, 5.5)
    ax2.set_title("(b) SV Count, PDOP & Speed", pad=10)
    ax2.legend(handles=[l1, l2, l3], loc="upper right", fontsize=7, frameon=True, ncol=1)

    # Panel (c) C/N0 distributions
    ax3 = fig.add_subplot(gs[0, 2])
    order = ["GPS", "Galileo", "BeiDou", "QZSS", "GLONASS", "SBAS"]
    data = [cn0_lists[k] for k in order]
    bp = ax3.boxplot(data, tick_labels=order, patch_artist=True, showfliers=False)
    for patch, k in zip(bp["boxes"], order):
        patch.set_facecolor(SYS_COLORS[k])
        patch.set_alpha(0.65)
    for med in bp["medians"]:
        med.set_color("#111111")
        med.set_linewidth(1.5)
    ax3.axhline(15.0, color="#d62728", ls="--", lw=1.0, label="15 dB-Hz Floor")
    ax3.set_ylabel("C/N0 (dB-Hz)")
    ax3.set_title("(c) RXM-RAWX C/N0 Distribution")
    ax3.tick_params(axis="x", rotation=25)
    ax3.legend(loc="lower right", fontsize=7)

    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def _to_enu(xyz: np.ndarray, origin: np.ndarray) -> np.ndarray:
    lat, lon, _ = ecef_to_llh(origin)
    r = ecef_to_enu_matrix(lat, lon)
    return (r @ (xyz - origin).T).T


def make_fig3_owndata_validation(out_path: Path) -> None:
    """Figure 3: G08 full-run ENU trajectory, initial static scatter, and 2D error series."""
    v1_df = pd.read_csv(REPO / "outputs/owndata/v1_details.csv")
    v2_df = pd.read_csv(REPO / "outputs/owndata/v2_details.csv")
    v5_df = pd.read_csv(REPO / "outputs/owndata/v5_details.csv")
    pvt_df = pd.read_csv(REPO / "outputs/owndata/nav_pvt_reference.csv")
    rtk_tows, rtk_xyz, _ = read_rtklib_pos_xyz(REPO / "outputs/owndata/G08_owndata_rtkpost_xyz.pos")

    t0 = float(v5_df["gps_tow_s"].iloc[0])
    # Origin at v5 median initial static hold (< 62.5 s)
    init_mask = (v5_df["gps_tow_s"].values - t0) < 62.5
    origin = np.median(v5_df.loc[init_mask, ["x_ecef_m", "y_ecef_m", "z_ecef_m"]].values, axis=0)

    enu_v1 = _to_enu(v1_df[["x_ecef_m", "y_ecef_m", "z_ecef_m"]].values, origin)
    enu_v2 = _to_enu(v2_df[["x_ecef_m", "y_ecef_m", "z_ecef_m"]].values, origin)
    enu_v5 = _to_enu(v5_df[["x_ecef_m", "y_ecef_m", "z_ecef_m"]].values, origin)
    enu_pvt = _to_enu(pvt_df[["x_ecef_m", "y_ecef_m", "z_ecef_m"]].values, origin)
    enu_rtk = _to_enu(rtk_xyz, origin)

    fig = plt.figure(figsize=(12.2, 4.1))
    gs = fig.add_gridspec(1, 3, width_ratios=[1.15, 0.95, 1.2], wspace=0.28)

    # Panel (a) Full ENU Track
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.plot(enu_v1[:, 0], enu_v1[:, 1], ".", color="#999999", ms=2.2, alpha=0.55, label="v1 (GPS Baseline)")
    ax1.plot(enu_rtk[:, 0], enu_rtk[:, 1], "-", color="#ff7f0e", lw=1.0, alpha=0.75, label="RTKLIB rnx2rtkp")
    ax1.plot(enu_pvt[:, 0], enu_pvt[:, 1], "--", color="#2ca02c", lw=1.2, alpha=0.85, label="NAV-PVT (u-blox)")
    ax1.plot(enu_v5[:, 0], enu_v5[:, 1], "-", color="#1f77b4", lw=1.4, label="v5 (Final SPP)")
    ax1.set_xlim(-60, 60)
    ax1.set_ylim(-60, 45)
    ax1.set_xlabel("East (m)")
    ax1.set_ylabel("North (m)")
    ax1.set_title("(a) G08 Campus Loop Track (ENU)")
    ax1.legend(loc="lower left", fontsize=7, frameon=True)

    # Panel (b) Initial Static Scatter
    ax2 = fig.add_subplot(gs[0, 1])
    ab_own = json.loads((REPO / "outputs/ablation_summary.json").read_text(encoding="utf-8"))["owndata"]
    for name, df_s, col, marker in [
        ("v1", v1_df, "#7f7f7f", "^"),
        ("v2", v2_df, "#ff7f0e", "s"),
        ("v5", v5_df, "#1f77b4", "o"),
    ]:
        m = (df_s["gps_tow_s"].values - t0) < 62.5
        xyz_s = df_s.loc[m, ["x_ecef_m", "y_ecef_m", "z_ecef_m"]].values
        med_ecef = np.median(xyz_s, axis=0)
        pts = _to_enu(xyz_s, med_ecef)
        cep95 = float(ab_own[name]["static_dwell"]["initial_static_hold"]["cep95_m"])
        ax2.scatter(pts[:, 0], pts[:, 1], s=14, alpha=0.65, color=col, marker=marker,
                    label=f"{name} (CEP95={cep95:.2f} m)")
        ax2.add_patch(Circle((0, 0), cep95, fill=False, ls="--", lw=1.2, color=col))
    ax2.set_aspect("equal")
    ax2.set_xlim(-2.2, 2.2)
    ax2.set_ylim(-2.2, 2.2)
    ax2.set_xlabel("Delta East vs Median (m)")
    ax2.set_ylabel("Delta North vs Median (m)")
    ax2.set_title("(b) Static Hold Scatter (0–62 s)")
    ax2.legend(loc="upper right", fontsize=7, frameon=True)

    # Panel (c) 2D Delta vs NAV-PVT time series
    ax3 = fig.add_subplot(gs[0, 2])
    pvt_map = {round(float(r["i_tow_s"]), 1): np.array([r["x_ecef_m"], r["y_ecef_m"], r["z_ecef_m"]])
               for _, r in pvt_df.iterrows()}
    for name, df_s, col, alpha, lw in [
        ("v1 (12.00 m RMSE)", v1_df, "#999999", 0.6, 0.9),
        ("v2 (17.11 m RMSE)", v2_df, "#ff7f0e", 0.65, 0.9),
        ("v5 (5.18 m RMSE)", v5_df, "#1f77b4", 0.95, 1.3),
    ]:
        ts, d2s = [], []
        for _, r in df_s.iterrows():
            k = round(float(r["gps_tow_s"]), 1)
            if k in pvt_map:
                ref = pvt_map[k]
                lat, lon, _ = ecef_to_llh(ref)
                e = ecef_to_enu_matrix(lat, lon) @ (np.array([r["x_ecef_m"], r["y_ecef_m"], r["z_ecef_m"]]) - ref)
                ts.append(k - t0)
                d2s.append(math.hypot(e[0], e[1]))
        ax3.plot(ts, d2s, color=col, alpha=alpha, lw=lw, label=name)
    ax3.axvspan(0, 62.5, color="#e6f5c9", alpha=0.45)
    ax3.axvspan(528, 548, color="#cbd5e8", alpha=0.45)
    ax3.set_ylim(0, 60)
    ax3.set_xlabel("Elapsed Survey Time (s)")
    ax3.set_ylabel("2D Difference vs NAV-PVT (m)")
    ax3.set_title("(c) Horizontal Agreement vs NAV-PVT")
    ax3.legend(loc="upper right", fontsize=7, frameon=True)

    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def make_fig4_benchmark_ablation(out_path: Path) -> None:
    """Figure 4: Block X accuracy, UrbanNav offline ablation, and UrbanNav track."""
    ab = json.loads((REPO / "outputs/ablation_summary.json").read_text(encoding="utf-8"))
    variants = ["v1", "v2", "v3", "v4", "v5"]
    labels = ["v1\nGPS", "v2\n+Multi", "v3\n+C/N0", "v4\n+RAIM", "v5\n+Hatch"]

    bx_2d = [ab["example"][v]["vs_nav_hpposecef"]["rmse_2d_m"] for v in variants]
    bx_p95 = [ab["example"][v]["vs_nav_hpposecef"]["p95_2d_m"] for v in variants]

    urb_cov = [ab["benchmark"][v]["availability_pct"] for v in variants]
    urb_jerk = [ab["benchmark"][v]["smoothness"]["rms_jerk_3d_m"] for v in variants]
    urb_p95j = [ab["benchmark"][v]["smoothness"]["p95_jerk_3d_m"] for v in variants]
    urb_hdop = [ab["benchmark"][v]["mean_hdop"] for v in variants]

    u_v1 = pd.read_csv(REPO / "outputs/benchmark/v1_details.csv")
    u_v5 = pd.read_csv(REPO / "outputs/benchmark/v5_details.csv")
    orig = u_v5[["x_ecef_m", "y_ecef_m", "z_ecef_m"]].values[0]
    u_enu1 = _to_enu(u_v1[["x_ecef_m", "y_ecef_m", "z_ecef_m"]].values, orig)
    u_enu5 = _to_enu(u_v5[["x_ecef_m", "y_ecef_m", "z_ecef_m"]].values, orig)

    fig = plt.figure(figsize=(12.6, 4.2))
    gs = fig.add_gridspec(1, 3, width_ratios=[1.05, 1.15, 1.15], wspace=0.46)

    # Panel (a) Block X Accuracy Ablation
    ax1 = fig.add_subplot(gs[0, 0])
    x = np.arange(len(variants))
    w = 0.36
    b1 = ax1.bar(x - w / 2, bx_2d, w, color="#1f77b4", label="2D RMSE (m)")
    b2 = ax1.bar(x + w / 2, bx_p95, w, color="#ff7f0e", label="2D P95 (m)")
    for rect in list(b1) + list(b2):
        h = rect.get_height()
        ax1.text(rect.get_x() + rect.get_width() / 2, h + 0.4, f"{h:.1f}", ha="center", va="bottom", fontsize=7)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    ax1.set_ylabel("Horizontal Metric vs NAV-HPPOSECEF (m)")
    ax1.set_ylim(0, 29)
    ax1.set_title("(a) Block X Regression Accuracy (n=186)")
    ax1.legend(loc="upper right", fontsize=7, frameon=True)

    # Panel (b) UrbanNav Offline Diagnostics
    ax2 = fig.add_subplot(gs[0, 1])
    l1, = ax2.plot(x, urb_jerk, "o-", color="#d62728", lw=1.6, label="3D Jerk RMS (m)")
    l2, = ax2.plot(x, urb_p95j, "s--", color="#ff7f0e", lw=1.4, label="3D Jerk P95 (m)")
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels)
    ax2.set_ylabel("Trajectory Jerk (m)", color="#d62728")
    ax2.set_ylim(0, 155)
    ax2_r = ax2.twinx()
    ax2_r.grid(False)
    l3, = ax2_r.plot(x, urb_cov, "^-", color="#2ca02c", lw=1.5, label="Availability (%)")
    ax2_r.set_ylabel("Solved Availability (%)", color="#2ca02c")
    ax2_r.set_ylim(94.0, 100.8)
    ax2.set_title("(b) UrbanNav Deep1 Offline Ablation")
    ax2.legend(handles=[l1, l2, l3], loc="center right", fontsize=7, frameon=True)

    # Panel (c) UrbanNav ENU Track
    ax3 = fig.add_subplot(gs[0, 2])
    ax3.plot(u_enu1[:, 0], u_enu1[:, 1], ".", color="#d62728", ms=2.0, alpha=0.35, label="v1 (GPS, 96.1%)")
    ax3.plot(u_enu5[:, 0], u_enu5[:, 1], "-", color="#1f77b4", lw=1.2, alpha=0.95, label="v5 (Final, 99.9%)")
    ax3.set_xlim(-500, 450)
    ax3.set_ylim(-250, 650)
    ax3.set_xlabel("East vs Epoch 0 (m)")
    ax3.set_ylabel("North vs Epoch 0 (m)")
    ax3.set_title("(c) UrbanNav Deep1 ENU Track")
    ax3.legend(loc="lower right", fontsize=7, frameon=True)

    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    fig_dir = REPO / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    make_fig2_raw_analysis(fig_dir / "fig2_raw_analysis.png")
    make_fig3_owndata_validation(fig_dir / "fig3_owndata_validation.png")
    make_fig4_benchmark_ablation(fig_dir / "fig4_benchmark_ablation.png")
    print("Generated all figures in", fig_dir)


if __name__ == "__main__":
    main()
