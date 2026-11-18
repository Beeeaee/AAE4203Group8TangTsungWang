# AAE4203 Lab 1 — GNSS Single Point Positioning (Group 8)

- **Course:** AAE4203 Guidance and Navigation (2026/27 Semester 1) — Hong Kong Polytechnic University
- **Instructor:** Prof. Weisong WEN
- **Group & Kit:** Group 8 (`G08`), Hardware Kit `K08`
- **Members:** LIU Boyu (`24100965D`), TANG Tsung Wang (`24097622D`), YEUNG Hiu Chun (`24082118D`), ZHANG Wenxi (`24132965D`)
- **Repository:** <https://github.com/Beeeaee/AAE4203Group8TangTsungWang>

## Repository Structure

```text
G08_Lab1_Repo/
├── README.md
├── requirements.txt
├── .gitignore
├── data/
│   ├── owndata/        # Group 8 UBX (G08_owndata_20261030.ubx), RINEX 3.03 OBS/NAV, epochs.csv
│   ├── example/        # Block X validation dataset (blockx_2025.obs/.nav, NAV-HPPOSECEF.csv)
│   └── benchmark/      # UrbanNav Deep1 benchmark (urbannav_deep1.obs/.nav, gps_csv/epochs.csv)
├── src/
│   ├── gnss_models.py  # WGS-84/ENU math, GPS/GAL/BDS/QZS ephemeris propagation, Klobuchar, Saastamoinen
│   ├── rinex_io.py     # RINEX 3.0x observation/navigation parser & RTKLIB .pos reader
│   ├── ubx_inspector.py# UBX binary stream parser (MON-VER, NAV-PVT, RXM-RAWX telemetry)
│   ├── spp_solver.py   # 5-stage progressive ablation WLS SPP engine (v1..v5)
│   ├── run_pipeline.py # End-to-end solver, ablation metrics, & CSV submission validator
│   └── generate_figures.py # Generates 300-DPI figures for Sections 3, 6, and 7
├── tools/
│   └── check_submission.py # Course CSV submission format & coverage checker
├── submission/
│   ├── G08_owndata.csv     # Validated 549/549 epoch ECEF submission (100.00%)
│   └── G08_benchmark.csv   # Validated 1533/1534 epoch ECEF submission (99.93%)
├── outputs/
│   ├── ablation_summary.json # Complete metrics for v1..v5 on Block X, G08, UrbanNav Deep1
│   ├── owndata/              # NAV-PVT telemetry, RTKLIB .pos baselines, v1..v5 per-epoch CSVs
│   ├── example/              # Block X RTKLIB .pos baseline & v1..v5 per-epoch CSVs
│   └── benchmark/            # UrbanNav Deep1 RTKLIB .pos baseline & v1..v5 per-epoch CSVs
└── figures/
    ├── fig2_raw_analysis.png
    ├── fig3_owndata_validation.png
    └── fig4_benchmark_ablation.png
```

## Five-Stage SPP Ablation Architecture (`src/spp_solver.py`)

| Version | Pipeline Stage | Summary Effect (Block X `n=186` vs `NAV-HPPOSECEF`) | UrbanNav Deep1 (`n=1534`) |
| :--- | :--- | :--- | :--- |
| `v1` | GPS-only WLS (`sin(E)^2`, 15 deg mask) | 60.75% cov, 15.436 m 2D RMSE | 96.09% cov, 134.21 m P95/RMS jerk = 103.94 / 134.21 m |
| `v2` | + Multi-Constellation (`G+E+C+J`, separate ISBs) | 100.00% cov, 6.507 m 2D RMSE | 99.93% cov, 1.305 HDOP, 25.49 m RMS jerk |
| `v3` | + `C/N0` & Elevation Weighting (`snr >= 15 dB-Hz`) | 100.00% cov, 3.604 m 2D RMSE | 99.93% cov, 24.33 m RMS jerk, 39.89 m P95 jerk |
| `v4` | + Iterative Baarda *w*-test RAIM FDE (`|w| > 3.29`) | 100.00% cov, 3.539 m 2D RMSE | 99.93% cov, 22.96 m RMS jerk, 125 FDE rejections |
| `v5` | + Reset-aware Hatch Carrier Smoothing (`N_max = 25`) | **100.00% cov, 3.479 m 2D RMSE, 4.951 m P95** | **99.93% cov**, 23.06 m RMS jerk *(1337 cycle-slip resets)* |

*Note: UrbanNav Deep1 external ground-truth RMSE and leaderboard rank are server-evaluated only (`N/A` offline); no external ground-truth files are included or used anywhere in this repository.*

## Quick Reproduction

```bash
pip install -r requirements.txt
python src/run_pipeline.py
python src/generate_figures.py
```

Verify submission CSV compliance independently:

```bash
python tools/check_submission.py submission/G08_owndata.csv --week 2442 --epochs 549 --epoch-file data/owndata/epochs.csv
python tools/check_submission.py submission/G08_benchmark.csv --week 2158 --epochs 1534 --epoch-file data/benchmark/gps_csv/epochs.csv
```
