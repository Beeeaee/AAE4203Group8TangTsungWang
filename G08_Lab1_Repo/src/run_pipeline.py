"""End-to-end AAE4203 Lab 1 pipeline for Group 8 (G08)."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import sys
from typing import Dict, List, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.gnss_models import ecef_to_enu_matrix, ecef_to_llh
from src.rinex_io import parse_rinex_nav, parse_rinex_obs, read_rtklib_pos_xyz
from src.spp_solver import ABLATION_CONFIGS, SolverConfig, solve_dataset
from src.ubx_inspector import inspect_ubx
from tools.check_submission import check as check_submission_csv


SUBMISSION_HEADER = ["gps_week", "gps_tow_s", "x_ecef_m", "y_ecef_m", "z_ecef_m"]


def write_obs_epochs_csv(epochs: List[dict], out_csv: Path) -> None:
    """Export actual OBS GPST epoch grid (week, tow_s rounded to 0.1 s)."""
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["gps_week", "gps_tow_s"])
        for ep in epochs:
            w.writerow([int(ep["week"]), f"{ep['tow']:.1f}"])


def write_submission_csv(rows: List[dict], out_csv: Path) -> None:
    """Write submission-compliant ECEF CSV (omitting unsolved epochs cleanly)."""
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(SUBMISSION_HEADER)
        for r in rows:
            w.writerow([
                int(r["gps_week"]),
                f"{r['gps_tow_s']:.1f}",
                f"{r['x_ecef_m']:.3f}",
                f"{r['y_ecef_m']:.3f}",
                f"{r['z_ecef_m']:.3f}",
            ])


def write_detail_csv(rows: List[dict], out_csv: Path) -> None:
    """Save per-epoch diagnostic metrics for analysis and plotting."""
    if not rows:
        return
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    keys = list(rows[0].keys())
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def compute_reference_comparison(rows: List[dict], ref_tows: np.ndarray, ref_xyz: np.ndarray) -> dict:
    """Compare solved ECEF positions against a receiver/RTKLIB reference trajectory."""
    ref_map = {round(float(t), 1): xyz for t, xyz in zip(ref_tows, ref_xyz)}
    e_errs, n_errs, u_errs = [], [], []
    err_2d, err_3d = [], []

    for r in rows:
        key = round(float(r["gps_tow_s"]), 1)
        if key not in ref_map:
            continue
        p_ref = ref_map[key]
        p_sol = np.array([r["x_ecef_m"], r["y_ecef_m"], r["z_ecef_m"]], dtype=float)
        lat, lon, _ = ecef_to_llh(p_ref)
        r_mat = ecef_to_enu_matrix(lat, lon)
        enu = r_mat @ (p_sol - p_ref)
        e_errs.append(float(enu[0]))
        n_errs.append(float(enu[1]))
        u_errs.append(float(enu[2]))
        d2 = math.hypot(enu[0], enu[1])
        d3 = float(np.linalg.norm(enu))
        err_2d.append(d2)
        err_3d.append(d3)

    if not err_2d:
        return {"matched": 0}
    a2 = np.array(err_2d)
    a3 = np.array(err_3d)
    return {
        "matched": len(err_2d),
        "rmse_2d_m": round(float(np.sqrt(np.mean(a2 ** 2))), 3),
        "rmse_3d_m": round(float(np.sqrt(np.mean(a3 ** 2))), 3),
        "p95_2d_m": round(float(np.percentile(a2, 95)), 3),
        "p95_3d_m": round(float(np.percentile(a3, 95)), 3),
        "max_2d_m": round(float(np.max(a2)), 3),
        "mean_e_m": round(float(np.mean(e_errs)), 3),
        "mean_n_m": round(float(np.mean(n_errs)), 3),
        "mean_u_m": round(float(np.mean(u_errs)), 3),
    }


def read_nav_hpposecef_csv(csv_path: Path) -> Tuple[np.ndarray, np.ndarray]:
    """Read example/NAV-HPPOSECEF.csv (converted from UBX iTOW ms and cm ECEF)."""
    tows, xyzs = [], []
    with csv_path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            itow_ms = float(row["iTOW"])
            x = float(row["ecefX"]) * 1e-2
            y = float(row["ecefY"]) * 1e-2
            z = float(row["ecefZ"]) * 1e-2
            tows.append(itow_ms * 1e-3)
            xyzs.append([x, y, z])
    return np.array(tows, dtype=float), np.array(xyzs, dtype=float)


def compute_static_dwell_metrics(rows: List[dict], nav_pvt_csv: Path, tow_offset: int = 18) -> dict:
    """Measure horizontal scatter around median across Group 8 static dwell segments."""
    pvt = {}
    with nav_pvt_csv.open("r", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            # NAV-PVT iTOW uses GPST (s) -> round to 0.1 s matches RAWX
            key = round(float(r["i_tow_s"]), 1)
            pvt[key] = r

    static_pts_init = []
    static_pts_end = []
    # Identify initial static (<63s from start) and final static (last 20 epochs)
    t0 = rows[0]["gps_tow_s"] if rows else 0.0
    t_end = rows[-1]["gps_tow_s"] if rows else 0.0
    for r in rows:
        dt_start = r["gps_tow_s"] - t0
        dt_end = t_end - r["gps_tow_s"]
        xyz = np.array([r["x_ecef_m"], r["y_ecef_m"], r["z_ecef_m"]], dtype=float)
        if dt_start < 62.5:
            static_pts_init.append(xyz)
        elif dt_end < 19.5:
            static_pts_end.append(xyz)

    def _scatter(pts: List[np.ndarray]) -> dict:
        if len(pts) < 5:
            return {"count": len(pts)}
        arr = np.array(pts)
        med = np.median(arr, axis=0)
        lat, lon, _ = ecef_to_llh(med)
        r_mat = ecef_to_enu_matrix(lat, lon)
        enu = (r_mat @ (arr - med).T).T
        d2 = np.hypot(enu[:, 0], enu[:, 1])
        d3 = np.linalg.norm(enu, axis=1)
        return {
            "count": len(pts),
            "std_e_m": round(float(np.std(enu[:, 0])), 3),
            "std_n_m": round(float(np.std(enu[:, 1])), 3),
            "std_u_m": round(float(np.std(enu[:, 2])), 3),
            "cep95_m": round(float(np.percentile(d2, 95)), 3),
            "rms_2d_scatter_m": round(float(np.sqrt(np.mean(d2 ** 2))), 3),
            "rms_3d_scatter_m": round(float(np.sqrt(np.mean(d3 ** 2))), 3),
        }

    return {
        "initial_static_hold": _scatter(static_pts_init),
        "final_static_hold": _scatter(static_pts_end),
    }


def compute_trajectory_smoothness(rows: List[dict]) -> dict:
    """Compute second-difference 3D acceleration proxy (dt=1 s) as offline smoothness check."""
    jerks = []
    steps = []
    for k in range(1, len(rows) - 1):
        dt1 = rows[k]["gps_tow_s"] - rows[k - 1]["gps_tow_s"]
        dt2 = rows[k + 1]["gps_tow_s"] - rows[k]["gps_tow_s"]
        if abs(dt1 - 1.0) < 0.2 and abs(dt2 - 1.0) < 0.2:
            p0 = np.array([rows[k - 1]["x_ecef_m"], rows[k - 1]["y_ecef_m"], rows[k - 1]["z_ecef_m"]])
            p1 = np.array([rows[k]["x_ecef_m"], rows[k]["y_ecef_m"], rows[k]["z_ecef_m"]])
            p2 = np.array([rows[k + 1]["x_ecef_m"], rows[k + 1]["y_ecef_m"], rows[k + 1]["z_ecef_m"]])
            steps.append(float(np.linalg.norm(p1 - p0)))
            jerks.append(float(np.linalg.norm(p2 - 2.0 * p1 + p0)))
    return {
        "continuous_triplets": len(jerks),
        "mean_1s_step_m": round(float(np.mean(steps)), 3) if steps else None,
        "p95_jerk_3d_m": round(float(np.percentile(jerks, 95)), 3) if jerks else None,
        "rms_jerk_3d_m": round(float(np.sqrt(np.mean(np.array(jerks) ** 2))), 3) if jerks else None,
    }


def main() -> None:
    print("1. Inspecting Group 8 UBX log...")
    ubx_summary = inspect_ubx(
        REPO / "data/owndata/G08_owndata_20261030.ubx",
        REPO / "outputs/owndata",
    )
    print(json.dumps(ubx_summary, indent=2))

    # Parse all three datasets once
    print("\n2. Parsing RINEX 3 datasets...")
    ds_ex_eps, ds_ex_meta = parse_rinex_obs(REPO / "data/example/blockx_2025.obs")
    ds_ex_nav, ds_ex_hdr = parse_rinex_nav(REPO / "data/example/blockx_2025.nav")

    ds_own_eps, ds_own_meta = parse_rinex_obs(REPO / "data/owndata/G08_owndata_20261030.obs")
    ds_own_nav, ds_own_hdr = parse_rinex_nav(REPO / "data/owndata/G08_owndata_20261030.nav")
    write_obs_epochs_csv(ds_own_eps, REPO / "data/owndata/epochs.csv")

    ds_urb_eps, ds_urb_meta = parse_rinex_obs(REPO / "data/benchmark/urbannav_deep1.obs")
    ds_urb_nav, ds_urb_hdr = parse_rinex_nav(REPO / "data/benchmark/urbannav_deep1.nav")

    # References (receiver/RTKLIB standalone comparisons; no external ground truth!)
    ex_hp_tows, ex_hp_xyz = read_nav_hpposecef_csv(REPO / "data/example/NAV-HPPOSECEF.csv")
    ex_rtk_tows, ex_rtk_xyz, _ = read_rtklib_pos_xyz(REPO / "outputs/example/blockx_rtkpost_xyz.pos")
    own_rtk_tows, own_rtk_xyz, _ = read_rtklib_pos_xyz(REPO / "outputs/owndata/G08_owndata_rtkpost_xyz.pos")

    # Also read NAV-PVT ECEF reference from UBX
    own_pvt_tows, own_pvt_xyz = [], []
    with (REPO / "outputs/owndata/nav_pvt_reference.csv").open("r", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            own_pvt_tows.append(float(r["i_tow_s"]))
            own_pvt_xyz.append([float(r["x_ecef_m"]), float(r["y_ecef_m"]), float(r["z_ecef_m"])])
    own_pvt_tows_a = np.array(own_pvt_tows)
    own_pvt_xyz_a = np.array(own_pvt_xyz)

    all_ablation = {"example": {}, "owndata": {}, "benchmark": {}}

    for vname, cfg in ABLATION_CONFIGS.items():
        print(f"\n=== Running {vname} ({cfg.name}) ===")
        # Block X example
        res_ex = solve_dataset(ds_ex_eps, ds_ex_nav, ds_ex_hdr, ds_ex_meta["approx_xyz"], cfg)
        comp_hp = compute_reference_comparison(res_ex["rows"], ex_hp_tows, ex_hp_xyz)
        comp_ex_rtk = compute_reference_comparison(res_ex["rows"], ex_rtk_tows, ex_rtk_xyz)
        res_ex["summary"]["vs_nav_hpposecef"] = comp_hp
        res_ex["summary"]["vs_rtkpost"] = comp_ex_rtk
        res_ex["summary"]["smoothness"] = compute_trajectory_smoothness(res_ex["rows"])
        all_ablation["example"][vname] = res_ex["summary"]
        write_detail_csv(res_ex["rows"], REPO / f"outputs/example/{vname}_details.csv")
        print(f"  [Example]   cov={res_ex['summary']['availability_pct']:.2f}% nsat={res_ex['summary']['mean_nsat']} "
              f"vsHPPOSECEF(2D={comp_hp.get('rmse_2d_m')}m, 3D={comp_hp.get('rmse_3d_m')}m, P95={comp_hp.get('p95_2d_m')}m) "
              f"vsRTKPOST(2D={comp_ex_rtk.get('rmse_2d_m')}m)")

        # Group 8 owndata
        res_own = solve_dataset(ds_own_eps, ds_own_nav, ds_own_hdr, ds_own_meta["approx_xyz"], cfg)
        comp_own_rtk = compute_reference_comparison(res_own["rows"], own_rtk_tows, own_rtk_xyz)
        comp_own_pvt = compute_reference_comparison(res_own["rows"], own_pvt_tows_a, own_pvt_xyz_a)
        static_own = compute_static_dwell_metrics(res_own["rows"], REPO / "outputs/owndata/nav_pvt_reference.csv")
        res_own["summary"]["vs_rtkpost"] = comp_own_rtk
        res_own["summary"]["vs_nav_pvt_ecef"] = comp_own_pvt
        res_own["summary"]["static_dwell"] = static_own
        res_own["summary"]["smoothness"] = compute_trajectory_smoothness(res_own["rows"])
        all_ablation["owndata"][vname] = res_own["summary"]
        write_detail_csv(res_own["rows"], REPO / f"outputs/owndata/{vname}_details.csv")
        print(f"  [Owndata]   cov={res_own['summary']['availability_pct']:.2f}% nsat={res_own['summary']['mean_nsat']} "
              f"vsRTKPOST(2D={comp_own_rtk.get('rmse_2d_m')}m, 3D={comp_own_rtk.get('rmse_3d_m')}m) "
              f"vsNAV-PVT(2D={comp_own_pvt.get('rmse_2d_m')}m) init_cep95={static_own['initial_static_hold'].get('cep95_m')}m")

        # UrbanNav benchmark (offline availability, geometry, residuals, smoothness only)
        res_urb = solve_dataset(ds_urb_eps, ds_urb_nav, ds_urb_hdr, ds_urb_meta["approx_xyz"], cfg)
        res_urb["summary"]["smoothness"] = compute_trajectory_smoothness(res_urb["rows"])
        all_ablation["benchmark"][vname] = res_urb["summary"]
        write_detail_csv(res_urb["rows"], REPO / f"outputs/benchmark/{vname}_details.csv")
        print(f"  [UrbanNav]  cov={res_urb['summary']['availability_pct']:.2f}% ({res_urb['summary']['solved_epochs']}/{res_urb['summary']['input_epochs']}) "
              f"nsat={res_urb['summary']['mean_nsat']} HDOP={res_urb['summary']['mean_hdop']} "
              f"resRMS={res_urb['summary']['mean_res_rms_m']}m jerkRMS={res_urb['summary']['smoothness']['rms_jerk_3d_m']}m")

        if vname == "v5":
            own_sub = REPO / "submission/G08_owndata.csv"
            bench_sub = REPO / "submission/G08_benchmark.csv"
            write_submission_csv(res_own["rows"], own_sub)
            write_submission_csv(res_urb["rows"], bench_sub)

    (REPO / "outputs/ablation_summary.json").write_text(json.dumps(all_ablation, indent=2), encoding="utf-8")

    # Validate official submission CSVs using exact course checker
    print("\n3. Validating submission CSVs with tools/check_submission.py...")
    err_own, n_own, cov_own = check_submission_csv(
        REPO / "submission/G08_owndata.csv",
        week=2442,
        epochs=len(ds_own_eps),
        epoch_file=REPO / "data/owndata/epochs.csv",
    )
    print(f"G08_owndata.csv: errors={err_own}, rows={n_own}, coverage={cov_own:.2f}%")

    err_bm, n_bm, cov_bm = check_submission_csv(
        REPO / "submission/G08_benchmark.csv",
        week=2158,
        epochs=1534,
        epoch_file=REPO / "data/benchmark/gps_csv/epochs.csv",
    )
    print(f"G08_benchmark.csv: errors={err_bm}, rows={n_bm}, coverage={cov_bm:.2f}%")
    if err_own or err_bm or cov_bm < 90.0:
        raise RuntimeError(f"Submission validation failed! own={err_own}, bm={err_bm}, bm_cov={cov_bm}")
    print("\nPipeline complete and verified!")


if __name__ == "__main__":
    main()
