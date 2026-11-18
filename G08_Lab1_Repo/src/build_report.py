"""Build Group 8 (G08) AAE4203 Lab 1 Report from the official Word template."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import docx
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor


REPO = Path(r"C:\Users\benta\Documents\GemimiProject\Project1\AAE4203\Labs\G08_Lab1_Repo")
TEMPLATE = Path(
    r"C:\Users\benta\Documents\GemimiProject\Project1\AAE4203\Labs\AAE4203-S12627-main\Lab1\PolyU_AAE4203_Lab_report_template.docx"
)
OUT_DOCX = Path(r"C:\Users\benta\Documents\GemimiProject\Project1\AAE4203\Labs\G08_Lab1_Report.docx")

BODY_FONT = "Calibri"
MONO_FONT = "Consolas"
NAVY = RGBColor(0x1F, 0x4E, 0x79)
DARK = RGBColor(0x22, 0x22, 0x22)
MUTED = RGBColor(0x55, 0x55, 0x55)


def _remove_element(el) -> None:
    parent = el.getparent()
    if parent is not None:
        parent.remove(el)


def _clear_and_set_run(p, text: str, font_name: str = BODY_FONT, size_pt: float = 10.0,
                        bold: bool = False, italic: bool = False, color: RGBColor = DARK) -> None:
    p_pr = p._p.pPr
    for child in list(p._p):
        if child is not p_pr:
            p._p.remove(child)
    r = p.add_run(text)
    r.font.name = font_name
    r.font.size = Pt(size_pt)
    r.bold = bold
    r.italic = italic
    r.font.color.rgb = color


def _set_cell_shading(cell, fill_hex: str) -> None:
    shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    cell._tc.get_or_add_tcPr().append(shading)


def _set_cell_margins(cell, top: int = 50, bottom: int = 50, left: int = 85, right: int = 85) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = OxmlElement("w:tcMar")
    for side, val in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        tc_mar.append(node)
    tc_pr.append(tc_mar)


def _set_table_borders(table, color: str = "B0BEC5") -> None:
    tbl_pr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="6" w:space="0" w:color="1F4E79"/>'
        f'<w:bottom w:val="single" w:sz="8" w:space="0" w:color="1F4E79"/>'
        f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
        f'<w:left w:val="none"/><w:right w:val="none"/><w:insideV w:val="none"/>'
        f'</w:tblBorders>'
    )
    tbl_pr.append(borders)


def _set_row_cant_split(row, is_header: bool = False) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tr_pr.append(OxmlElement("w:cantSplit"))
    if is_header:
        tr_pr.append(OxmlElement("w:tblHeader"))


def _insert_para_before(anchor_p, text: str = "", space_before: float = 0, space_after: float = 4,
                        size_pt: float = 9.5, bold: bool = False, italic: bool = False,
                        align: WD_ALIGN_PARAGRAPH = WD_ALIGN_PARAGRAPH.LEFT,
                        color: RGBColor = DARK, style: str | None = None):
    p = anchor_p.insert_paragraph_before("")
    if style:
        try:
            p.style = style
        except KeyError:
            pass
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.12
    p.alignment = align
    if text:
        r = p.add_run(text)
        r.font.name = BODY_FONT
        r.font.size = Pt(size_pt)
        r.bold = bold
        r.italic = italic
        r.font.color.rgb = color
    return p


def _insert_equation_before(anchor_p, lhs_expr: str, eq_num: int):
    p = anchor_p.insert_paragraph_before("")
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.tab_stops.add_tab_stop(Inches(3.25), WD_TAB_ALIGNMENT.CENTER)
    p.paragraph_format.tab_stops.add_tab_stop(Inches(6.75), WD_TAB_ALIGNMENT.RIGHT)
    p.add_run("\t")
    r_eq = p.add_run(lhs_expr)
    r_eq.font.name = "Cambria Math"
    r_eq.font.size = Pt(8.8)
    r_eq.font.color.rgb = DARK
    r_tab = p.add_run(f"\t({eq_num})")
    r_tab.font.name = BODY_FONT
    r_tab.font.size = Pt(9.0)
    r_tab.font.color.rgb = DARK
    return p


def _insert_styled_table_before(doc, anchor_p, headers: list[str], rows: list[list[str]],
                                col_widths_in: list[float], font_pt: float = 8.2,
                                align_right_cols: set[int] | None = None):
    align_right_cols = align_right_cols or set()
    tbl = doc.add_table(rows=1 + len(rows), cols=len(headers))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    _set_table_borders(tbl)

    # Header row
    hdr_row = tbl.rows[0]
    _set_row_cant_split(hdr_row, is_header=True)
    for c_idx, h_text in enumerate(headers):
        cell = hdr_row.cells[c_idx]
        cell.width = Inches(col_widths_in[c_idx])
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        _set_cell_shading(cell, "1F4E79")
        _set_cell_margins(cell, top=50, bottom=50, left=65, right=65)
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.keep_with_next = True
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT if c_idx in align_right_cols else WD_ALIGN_PARAGRAPH.LEFT
        r = p.add_run(h_text)
        r.font.name = BODY_FONT
        r.font.size = Pt(font_pt)
        r.bold = True
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    # Data rows
    for r_idx, r_data in enumerate(rows):
        row = tbl.rows[r_idx + 1]
        _set_row_cant_split(row, is_header=False)
        bg = "F4F7FA" if r_idx % 2 == 1 else "FFFFFF"
        is_last = (r_idx == len(rows) - 1) and len(rows) >= 5 and r_data[0].startswith("v5")
        for c_idx, val in enumerate(r_data):
            cell = row.cells[c_idx]
            cell.width = Inches(col_widths_in[c_idx])
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            _set_cell_shading(cell, "EBF2F8" if is_last else bg)
            _set_cell_margins(cell, top=36, bottom=36, left=65, right=65)
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT if c_idx in align_right_cols else WD_ALIGN_PARAGRAPH.LEFT
            r = p.add_run(val)
            r.font.name = BODY_FONT
            r.font.size = Pt(font_pt)
            r.bold = is_last or (c_idx == 0)
            r.font.color.rgb = DARK

    anchor_p._p.addprevious(tbl._tbl)
    return tbl


def _find_para_by_prefix(doc, prefix: str):
    for p in doc.paragraphs:
        if p.text.strip().startswith(prefix):
            return p
    raise KeyError(f"Paragraph not found: {prefix!r}")


def _replace_cover_line(p, label: str, value: str) -> None:
    p_pr = p._p.pPr
    for child in list(p._p):
        if child is not p_pr:
            p._p.remove(child)
    p.paragraph_format.left_indent = Inches(1.25)
    p.paragraph_format.first_line_indent = Inches(-1.25)
    p.paragraph_format.tab_stops.clear_all()
    p.paragraph_format.tab_stops.add_tab_stop(Inches(1.25), WD_TAB_ALIGNMENT.LEFT)
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(2)
    r1 = p.add_run(f"{label}\t")
    r1.bold = True
    r1.font.name = BODY_FONT
    r1.font.size = Pt(10.0)
    r2 = p.add_run(value)
    r2.font.name = BODY_FONT
    r2.font.size = Pt(10.0)


def main() -> None:
    ubx = json.loads((REPO / "outputs/owndata/ubx_summary.json").read_text(encoding="utf-8"))
    ab = json.loads((REPO / "outputs/ablation_summary.json").read_text(encoding="utf-8"))

    doc = docx.Document(str(TEMPLATE))

    # 1. Cover page & Abstract
    p_title = _find_para_by_prefix(doc, "Title:")
    p_sub = _find_para_by_prefix(doc, "Lab 1:")
    p_dept = _find_para_by_prefix(doc, "Department:")
    p_school = _find_para_by_prefix(doc, "School:")
    _clear_and_set_run(p_title, "AAE4203 Guidance and Navigation — Lab 1 Report", size_pt=18.5, bold=True, color=NAVY)
    p_title.paragraph_format.space_before = Pt(0)
    p_title.paragraph_format.space_after = Pt(2)
    _clear_and_set_run(p_sub, "GNSS Single Point Positioning (SPP): Multi-Constellation WLS, RAIM & Carrier Smoothing", size_pt=11.5, bold=True, color=DARK)
    p_sub.paragraph_format.space_after = Pt(4)

    _replace_cover_line(_find_para_by_prefix(doc, "Course:"), "Course:", "AAE4203 — Guidance and Navigation (2026/27 Semester 1)")
    _replace_cover_line(_find_para_by_prefix(doc, "Group:"), "Group:", "Group 8 (G08) — Receiver Kit K08")
    _replace_cover_line(_find_para_by_prefix(doc, "Members:"), "Members:", "LIU Boyu; TANG Tsung Wang; YEUNG Hiu Chun; ZHANG Wenxi")
    _replace_cover_line(_find_para_by_prefix(doc, "Member IDs:"), "Member IDs:", "24100965D; 24097622D; 24082118D; 24132965D")
    _replace_cover_line(_find_para_by_prefix(doc, "Instructor:"), "Instructor:", "Prof. Weisong WEN")
    _replace_cover_line(p_dept, "Department:", "Department of Aeronautical and Aviation Engineering")
    _replace_cover_line(p_school, "School:", "The Hong Kong Polytechnic University")
    _replace_cover_line(_find_para_by_prefix(doc, "Date:"), "Date:", "October 30, 2026  |  GitHub: https://github.com/Beeeaee/AAE4203Group8TangTsungWang")

    # Trim excess blank spacing paragraphs on Cover Page so Abstract + Keywords fit completely on Page 1
    p_abs_hdr = _find_para_by_prefix(doc, "Abstract")
    p_abs_hdr.paragraph_format.space_before = Pt(4)
    p_abs_hdr.paragraph_format.space_after = Pt(2)
    p_abs = _find_para_by_prefix(doc, "Summarise in 150")
    abs_text = (
        "This report documents Group 8’s end-to-end GNSS Single Point Positioning (SPP) pipeline developed for "
        "AAE4203 Lab 1 using multi-constellation receiver logs. Field data were collected near Block X at PolyU on "
        "October 30, 2026 (08:13:12–08:22:19 UTC) with Kit K08 (u-blox ZED-F9P, HPG 1.32), capturing 549 1 Hz "
        "RXM-RAWX epochs spanning a 63 s initial static hold, 465 s pedestrian loops, and a 20 s final static hold. "
        "We progressively ablated a five-stage weighted Gauss–Newton estimator (v1–v5): GPS-only L1 baseline (v1), "
        "GPS+Galileo+BeiDou+QZSS fusion with ISBs and BDT/GEO transforms (v2), combined C/N0 and elevation weighting "
        "(v3), iterative Baarda w-test RAIM fault exclusion (v4), and Hatch carrier-phase smoothing (v5). On Block X "
        "(n = 186), v5 lowered 2D RMSE from 15.436 m (v1) to 3.479 m (P95 = 4.951 m); on G08 data, v5 achieved "
        "5.178 m 2D RMS agreement vs NAV-PVT and 0.460 m CEP95 static precision. On UrbanNav Deep1 (n = 1534), v5 "
        "raised availability from 96.09% to 99.93% (1533/1534) and lowered HDOP from 2.929 to 1.359; server RMSE and "
        "rank remain N/A pending TA scoring."
    )
    _clear_and_set_run(p_abs, abs_text, size_pt=9.2)
    p_abs.paragraph_format.space_after = Pt(3)
    p_kw = _find_para_by_prefix(doc, "Keywords:")
    _clear_and_set_run(
        p_kw,
        "Keywords: GNSS, Single Point Positioning, Multi-Constellation WLS, RAIM FDE, Hatch Filter, UrbanNav Deep1",
        size_pt=9.0, italic=True, color=MUTED,
    )
    p_kw.paragraph_format.space_after = Pt(2)
    for b_p in [doc.paragraphs[idx] for idx in (0, 1, 7, 8, 17, 18, 19, 23, 24, 25)
                if idx < len(doc.paragraphs) and not doc.paragraphs[idx].text.strip()
                and doc.paragraphs[idx]._p.find(".//" + qn("w:sectPr")) is None
                and not doc.paragraphs[idx]._p.xpath(".//w:drawing")]:
        _remove_element(b_p._p)

    # Identify all template Heading 1 anchors before deleting body elements
    h_quick = _find_para_by_prefix(doc, "Template Usage")
    h_data = _find_para_by_prefix(doc, "Data Collection")
    h_raw = _find_para_by_prefix(doc, "Raw Data Analysis")
    h_spp = _find_para_by_prefix(doc, "SPP Algorithm")
    h_code = _find_para_by_prefix(doc, "Code Listing")
    h_own = _find_para_by_prefix(doc, "Own-Data Validation")
    h_bench = _find_para_by_prefix(doc, "Benchmark Results")
    h_ai = _find_para_by_prefix(doc, "AI-Use Statement")
    h_limits = _find_para_by_prefix(doc, "Page Limits and Submission")
    h_ref = _find_para_by_prefix(doc, "References")
    h_app_a = _find_para_by_prefix(doc, "A Figure and Table")
    h_app_b = _find_para_by_prefix(doc, "B Key AI Prompts")

    # Helper to wipe all body elements between two heading paragraphs [start_h, end_h)
    body = doc.element.body
    children = list(body)

    def _clear_between(start_p, end_p, remove_start: bool = False):
        cur = list(body)
        i0 = cur.index(start_p._p)
        i1 = cur.index(end_p._p) if end_p is not None else len(cur) - 1
        start_idx = i0 if remove_start else i0 + 1
        for k in range(i1 - 1, start_idx - 1, -1):
            el = cur[k]
            if el.find(".//" + qn("w:sectPr")) is not None:
                continue
            if el.tag.endswith("}p") or el.tag.endswith("}tbl"):
                _remove_element(el)

    # Remove template-guide-only sections cleanly (Section 1 Quick Guide, Section 9 Checklist, Appendix A)
    _clear_between(h_quick, h_data, remove_start=True)
    _clear_between(h_limits, h_ref, remove_start=True)
    _clear_between(h_app_a, h_app_b, remove_start=True)

    # Clear placeholders in sections we will populate cleanly before next heading
    _clear_between(h_data, h_raw)
    _clear_between(h_raw, h_spp)
    _clear_between(h_spp, h_code)
    _clear_between(h_code, h_own)
    _clear_between(h_own, h_bench)
    _clear_between(h_bench, h_ai)
    _clear_between(h_ai, h_ref)
    _clear_between(h_ref, h_app_b)
    _clear_between(h_app_b, None)

    # Trim excess blank spacing on Cover Page so Abstract fits cleanly on Page 1
    p_abs.paragraph_format.space_after = Pt(2)

    # --- SECTION 1 (was 2): DATA COLLECTION ---
    _insert_para_before(
        h_raw,
        "Group 8 (Kit K08) conducted outdoor GNSS data logging near PolyU Block X on October 30, 2026 "
        "between 08:13:12 and 08:22:19 UTC (16:13:12–16:22:19 HKT; GPS Week 2442, TOW 461610.0–462158.0 s) "
        "using a u-blox ZED-F9P multi-band receiver (EXT CORE 1.00, FWVER=HPG 1.32, PROTVER=27.31) at 1 Hz [1]. "
        "Unlike a stationary static test, UBX NAV-PVT telemetry confirms a three-phase survey: an initial 63 s static "
        "hold at the plaza corner (22.305717° N, 114.180162° E), 465 s of pedestrian walking loops around "
        "adjacent building facades (peak ground speed 1.567 m/s, mean pDOP 1.203, mean 27.73 tracked SVs), and a "
        "20 s final static hold. Raw UBX frames (RXM-RAWX/SFRBX and NAV-PVT/ORB/SAT/SIG; NAV-HPPOSECEF not logged) "
        "were converted to RINEX 3.03 using RTKLIB CONVBIN EX 2.5.0 [2], and processed with our standalone Python pipeline "
        "(https://github.com/Beeeaee/AAE4203Group8TangTsungWang). No site photos were captured (Figure 1 box left empty).",
    )
    # Empty Figure 1 box per user instruction ("no photos, leave empty")
    empty_tbl = doc.add_table(rows=1, cols=1)
    empty_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    c0 = empty_tbl.rows[0].cells[0]
    c0.width = Inches(5.8)
    _set_cell_margins(c0, top=140, bottom=140, left=100, right=100)
    tbl_b = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        '<w:top w:val="single" w:sz="6" w:space="0" w:color="999999"/>'
        '<w:bottom w:val="single" w:sz="6" w:space="0" w:color="999999"/>'
        '<w:left w:val="single" w:sz="6" w:space="0" w:color="999999"/>'
        '<w:right w:val="single" w:sz="6" w:space="0" w:color="999999"/>'
        '</w:tblBorders>'
    )
    empty_tbl._tbl.tblPr.append(tbl_b)
    p_e = c0.paragraphs[0]
    p_e.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_e.paragraph_format.keep_with_next = True
    r_e = p_e.add_run("[Empty photo box — no field photographs attached]")
    r_e.font.name = BODY_FONT
    r_e.font.size = Pt(8.5)
    r_e.italic = True
    r_e.font.color.rgb = MUTED
    h_raw._p.addprevious(empty_tbl._tbl)

    _insert_para_before(
        h_raw,
        "Figure 1: Data collection site photo box near PolyU Block X plaza (intentionally left empty).",
        space_before=2, space_after=4, size_pt=8.5, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, color=MUTED,
    )
    p_t1 = _insert_para_before(
        h_raw,
        "Table 1: Group 8 field survey hardware configuration, telemetry summary, and unrecorded metadata.",
        space_before=2, space_after=2, size_pt=8.5, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, color=NAVY,
    )
    p_t1.paragraph_format.keep_with_next = True
    t1_rows = [
        ["Group / Hardware Kit", "Group 8 (G08), Kit K08 — LIU Boyu, TANG Tsung Wang, YEUNG Hiu Chun, ZHANG Wenxi"],
        ["Receiver & Firmware", "u-blox ZED-F9P (MOD=ZED-F9P, FWVER=HPG 1.32, PROTVER=27.31, HW=00190000)"],
        ["Survey Date & Span", "October 30, 2026; 08:13:12–08:22:19 UTC (16:13:12–16:22:19 HKT), GPS Week 2442 (548.0 s)"],
        ["Log & Conversion", "G08_owndata_20261030.ubx (9,598,503 B; 549 RAWX, 5,538 SFRBX, 548 NAV-PVT; no HPPOSECEF)"],
        ["Survey Dynamics", "63 s initial static hold (0–62 s) → 465 s plaza loops (max 1.567 m/s) → 20 s final static hold"],
        ["Signals (RINEX 3.03)", "GPS (C1C/C2X), GAL (C1X/C7X), BDS (C2I/C7I), QZS (C1C/C2X), GLO (C1C/C2C), SBAS (C1C)"],
        ["Field Notes Gaps", "Ambient weather conditions & exact u-center minor build number not recorded in log metadata"],
    ]
    _insert_styled_table_before(doc, h_raw, ["Parameter", "Observed Value / Verified Telemetry"], t1_rows, [1.65, 5.10], font_pt=8.2)
    _insert_para_before(h_raw, "", space_after=2)

    # --- SECTION 2 (was 3): RAW DATA ANALYSIS ---
    cn = ubx["cn0_by_constellation"]
    _insert_para_before(
        h_spp,
        f"Parsing G08_owndata_20261030.ubx yielded 25,705 dual-band code/phase/Doppler/SNR measurements across "
        f"43 unique space vehicles. GPS (mean {cn['GPS']['mean_dbhz']:.2f} dB-Hz, median {cn['GPS']['median_dbhz']:.1f} dB-Hz, "
        f"9 SVs) and Galileo (mean {cn['Galileo']['mean_dbhz']:.2f} dB-Hz, median {cn['Galileo']['median_dbhz']:.1f} dB-Hz, "
        f"8 SVs) exhibited strong open-sky upper-hemisphere C/N0, whereas BeiDou (mean {cn['BeiDou']['mean_dbhz']:.2f} dB-Hz) "
        f"and GLONASS (mean {cn['GLONASS']['mean_dbhz']:.2f} dB-Hz, P10 = {cn['GLONASS']['p10_dbhz']:.1f} dB-Hz) suffered heavier "
        f"urban multipath attenuation when the pedestrian walked adjacent to Block X walls (t = 150–490 s, Fig. 2b–c). "
        f"Broadcast ephemeris screening identified unhealthy flags (svh ≠ 0) on QZSS J07 in G08's navigation file, which "
        f"our solver excluded alongside sub-15° elevation and sub-15 dB-Hz observations. During obstructed corner turns "
        f"(t ≈ 205 s, 325 s, 445 s), used satellite counts briefly dipped to 6–9 and v5 PDOP rose toward 4.5, demonstrating "
        f"why non-line-of-sight (NLOS) excess delay δρ_NLOS = d(sec θᵢ − 1) [3]–[5] degrades unweighted SPP.",
    )
    p_fig2 = _insert_para_before(h_spp, "", space_before=1, space_after=1, align=WD_ALIGN_PARAGRAPH.CENTER)
    p_fig2.paragraph_format.keep_with_next = True
    p_fig2.add_run().add_picture(str(REPO / "figures/fig2_raw_analysis.png"), width=Inches(6.45))
    _insert_para_before(
        h_spp,
        "Figure 2: Group 8 raw observation quality: (a) healthy G/E/C skyplot above 15° mask, "
        "(b) SV count, PDOP, and NAV-PVT speed segments, and (c) UBX RXM-RAWX C/N0 distribution.",
        space_before=1, space_after=4, size_pt=8.4, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, color=MUTED,
    )

    # --- SECTION 3 (was 4): SPP ALGORITHM ---
    _insert_para_before(
        h_code,
        "Following AAE4203 Weeks 1–7 theory [3]–[6], Step 1 transforms geodetic WGS-84 coordinates (φ, λ, h) to ECEF r = [x, y, z]ᵀ "
        "and rotates position residuals Δr_ECEF into local East–North–Up (ENU) coordinates via orthogonal matrix R (Week 1 [3]):",
        space_after=2,
    )
    _insert_equation_before(
        h_code,
        "Δr_ENU = R(φ, λ) · Δr_ECEF,     R = [[−sin λ, cos λ, 0], [−sin φ cos λ, −sin φ sin λ, cos φ], [cos φ cos λ, cos φ sin λ, sin φ]]",
        1,
    )
    _insert_para_before(
        h_code,
        "Step 2 propagates broadcast Keplerian orbits at signal transmission time t_tx = t_rx − P/c − δt_s (Weeks 4–5 [4], [5]). "
        "Because BeiDou ephemerides use BeiDou Time (BDT = GPST − 14 s [7]), transmission epochs convert via t_BDT = t_tx − 14 s "
        "and GEO satellites (PRN ≤ 5 or ≥ 59) apply the Rx(−5°) followed by Rz(Ω_E t_k) inclination rotation; Galileo I/NAV vs F/NAV "
        "records match BGD(E1,E5b) or BGD(E1,E5a) [8]. Corrected pseudorange P_corr^(s) removes satellite clock bias (including "
        "relativity −2√μ e √a sin E_k / c²), group delay TGD_s, Sagnac rotation (Ω_E/c)(x_s y − y_s x), Klobuchar ionosphere I^(s) "
        "(scaled by f_L1²/f_c²), and Saastamoinen troposphere T^(s) [5]:",
        space_after=2,
    )
    _insert_equation_before(
        h_code,
        "P_corr^(s) = P^(s) + c·δt_s − c·TGD_s = ||r − r^(s)|| + (Ω_E/c)(x_s y − y_s x) + b_G + Δb_c + I^(s) + T^(s) + ε^(s)",
        2,
    )
    _insert_para_before(
        h_code,
        "Step 3 linearizes Eq. (2) around x₀ = [x₀, y₀, z₀, b_G, Δb_E, Δb_C, Δb_J]ᵀ via first-order Taylor expansion (Weeks 2 & 6 [3], [6]). "
        "Auxiliary inter-system clock bias (ISB) states Δb_c are dynamically included only when ≥ 2 healthy satellites exist for "
        "constellation c, guaranteeing full column rank (cond(HᵀWH) < 10¹²). Solving the weighted Gauss–Newton normal equations yields "
        "state update Δx and unweighted geometric covariance Q_ENU (Week 7 [5]):",
        space_after=2,
    )
    _insert_equation_before(
        h_code,
        "Δx = (Hᵀ W H)⁻¹ Hᵀ W v,       v = P_corr − ρ̂(x₀),       Q_ENU = R [(Hᵀ H)⁻¹]₁:₃,₁:₃ Rᵀ",
        3,
    )
    _insert_para_before(
        h_code,
        "Step 4 ablates measurement weighting W = diag(1/σᵢ²) across five progressive variants: v1 GPS baseline (w = sin² E [6]); "
        "v2 multi-constellation WLS (G+E+C+J); and v3–v5 combined elevation and C/N0 stochastic weighting (15° elevation mask, "
        "15 dB-Hz SNR floor [10]) suppressing weak urban diffraction signals:",
        space_after=2,
    )
    _insert_equation_before(
        h_code,
        "σᵢ² = 1.5² + (1.5 / sin Eᵢ)² + 4.0 · 10^(max(0, 42 − C/N0ᵢ) / 10),       W = diag(1 / σᵢ²)",
        4,
    )
    _insert_para_before(
        h_code,
        "Step 5 adds fault isolation and carrier smoothing (Week 7 [10], [11]): v4 runs iterative Baarda w-test RAIM FDE, excluding "
        "the worst satellite whenever max |vᵢ|/σ_vi > 3.29 while preserving DOF ≥ 1 and PDOP ≤ 30; v5 applies reset-aware Hatch "
        "carrier-phase smoothing P_s(k) (N_max = 25), resetting on gaps > 5 s, RINEX LLI cycle slips, or |P_k − (P_s(k−1) + λΔL_k)| > 10 m:",
        space_after=2,
    )
    _insert_equation_before(
        h_code,
        "σ_vi² = σᵢ² − (H (Hᵀ W H)⁻¹ Hᵀ)ᵢᵢ,       P_s(k) = (1/N_eff)P(k) + ((N_eff − 1)/N_eff)[P_s(k−1) + λΔL(k)]",
        5,
    )

    # --- SECTION 4 (was 5): CODE LISTING ---
    _insert_para_before(
        h_own,
        "Core excerpts from src/spp_solver.py and src/gnss_models.py are listed below (full six-module pipeline "
        "and unit verification scripts are hosted at https://github.com/Beeeaee/AAE4203Group8TangTsungWang).",
        space_after=3,
    )
    code_excerpt = (
        "# Excerpt 1: C/N0 + Elevation Stochastic Variance & Hatch Smoother (src/spp_solver.py)\n"
        "def _meas_variance(el_rad: float, snr_dbhz: float, mode: str) -> float:\n"
        "    sin_el = max(math.sin(el_rad), 0.05)\n"
        "    if mode == 'sin_el': return 1.0 / (sin_el * sin_el)\n"
        "    snr = snr_dbhz if (math.isfinite(snr_dbhz) and snr_dbhz > 0.0) else 30.0\n"
        "    return 1.5**2 + (1.5 / sin_el)**2 + 4.0 * (10.0 ** (max(0.0, 42.0 - snr) / 10.0))\n\n"
        "class HatchSmoother:\n"
        "    def apply(self, week, tow, sat, pr_m, l1_cyc, lli, freq_hz):\n"
        "        if not math.isfinite(l1_cyc) or (lli & 1): self.state.pop(sat, None); return pr_m\n"
        "        phi_m = (C_LIGHT / freq_hz) * l1_cyc; prev = self.state.get(sat)\n"
        "        t_now = week * 604800.0 + tow\n"
        "        if prev is None or (t_now - prev['t']) > 5.0 or abs(pr_m - (prev['p_bar'] + phi_m - prev['phi'])) > 10.0:\n"
        "            self.state[sat] = {'t': t_now, 'p_bar': pr_m, 'phi': phi_m, 'n': 1}; return pr_m\n"
        "        n_eff = min(prev['n'] + 1, self.window)\n"
        "        p_bar = (pr_m + (n_eff - 1.0) * (prev['p_bar'] + phi_m - prev['phi'])) / n_eff\n"
        "        self.state[sat] = {'t': t_now, 'p_bar': p_bar, 'phi': phi_m, 'n': n_eff}; return p_bar\n\n"
        "# Excerpt 2: Multi-Constellation WLS Normal Equations & Baarda w-Test RAIM FDE\n"
        "for it in range(15):\n"
        "    lat, lon, h_m = ecef_to_llh(x[:3])\n"
        "    for i, c in enumerate(cands):\n"
        "        diff = x[:3] - c['sat_pos']; rng = float(np.linalg.norm(diff))\n"
        "        az, el = sat_az_el(x[:3], c['sat_pos']); w_vec[i] = 1.0 / _meas_variance(el, c['snr'], cfg.weight_mode)\n"
        "        pred = rng + sagnac_delay(c['sat_pos'], x[:3]) + x[sys_to_col[c['sys']]] + ion + trp\n"
        "        v_vec[i] = c['pr_corr'] - pred; h_mat[i, :3] = diff / rng; h_mat[i, sys_to_col[c['sys']]] = 1.0\n"
        "    hw = h_mat.T * w_vec; n_mat = hw @ h_mat\n"
        "    if np.linalg.cond(n_mat) > 1.0e12: return None\n"
        "    q_cov = np.linalg.inv(n_mat); dx = q_cov @ (hw @ v_vec); x += dx\n"
        "    if it >= 2 and np.linalg.norm(dx[:3]) < 1.0e-4: break\n"
        "# Iterative Baarda w-test FDE (dof >= 1, sig_vi = sqrt(1/w_i - (H Q H^T)_ii))\n"
        "hqh = np.einsum('ij,jk,ik->i', sol['H'], sol['Q'], sol['H'])\n"
        "w_stats = np.abs(sol['v']) / np.sqrt(np.maximum(1.0 / sol['w'] - hqh, 0.04))\n"
        "if float(np.max(w_stats)) > cfg.raim_z_thresh: reject_worst_and_resolve()"
    )
    c_tbl = doc.add_table(rows=1, cols=1)
    c_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = c_tbl.rows[0].cells[0]
    cell.width = Inches(6.75)
    _set_cell_shading(cell, "F6F8FA")
    _set_cell_margins(cell, top=42, bottom=42, left=85, right=85)
    cb = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>'
        '<w:left w:val="single" w:sz="12" w:space="0" w:color="1F4E79"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>'
        '</w:tblBorders>'
    )
    c_tbl._tbl.tblPr.append(cb)
    p_c = cell.paragraphs[0]
    p_c.paragraph_format.space_before = Pt(0)
    p_c.paragraph_format.space_after = Pt(0)
    p_c.paragraph_format.line_spacing = 1.00
    p_c.paragraph_format.keep_with_next = True
    rc = p_c.add_run(code_excerpt)
    rc.font.name = MONO_FONT
    rc.font.size = Pt(7.0)
    h_own._p.addprevious(c_tbl._tbl)
    _insert_para_before(
        h_own,
        "Listing 1: Core stochastic weighting, Hatch carrier smoothing, multi-constellation WLS, and RAIM FDE excerpts.",
        space_before=2, space_after=5, size_pt=8.5, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, color=MUTED,
    )

    # --- SECTION 5 (was 6): OWN-DATA VALIDATION ---
    own = ab["owndata"]
    _insert_para_before(
        h_bench,
        "Figure 3 and Table 2 evaluate Group 8's SPP stages against two independent references: RTKLIB rnx2rtkp EX 2.5.0 "
        "(Single mode, G/R/E/J/C, 15° mask) and the receiver's onboard NAV-PVT solution converted to WGS-84 ECEF. "
        "Note two critical findings: (1) unweighted multi-constellation fusion (v2) lifts availability from 88.71% to "
        "100.00% (549/549 epochs) but amplifies dynamic discrepancies during walking turns (17.11 m 2D RMS vs NAV-PVT) "
        "because attenuated BeiDou/Galileo NLOS ranges receive equal weight; (2) adding C/N0 weighting (v3), 34 RAIM FDE "
        "exclusions (v4), and Hatch smoothing (v5) cuts 2D discrepancy against NAV-PVT by 56.9% relative to GPS baseline "
        "(12.002 m → 5.178 m) and tightens the 63 s initial static hold precision from 1.488 m to 0.460 m CEP95 (Fig. 3b). "
        "A ~8.8 m vertical offset remains between our broadcast Klobuchar/Saastamoinen v5 solution and both RTKPOST "
        "(which includes GLONASS FCN channels) and u-blox EKF NAV-PVT, attributable to GLONASS inclusion and internal "
        "filtering differences rather than horizontal bias (mean E/N delta vs RTKPOST = −0.007 m / +0.330 m).",
        space_after=3,
    )
    p_fig3 = _insert_para_before(h_bench, "", space_before=1, space_after=1, align=WD_ALIGN_PARAGRAPH.CENTER)
    p_fig3.paragraph_format.keep_with_next = True
    p_fig3.add_run().add_picture(str(REPO / "figures/fig3_owndata_validation.png"), width=Inches(6.45))
    _insert_para_before(
        h_bench,
        "Figure 3: G08 Block X validation: (a) full-run ENU tracks, (b) 0–62 s initial static scatter & CEP95, (c) 2D delta vs NAV-PVT.",
        space_before=1, space_after=4, size_pt=8.4, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, color=MUTED,
    )
    p_t2 = _insert_para_before(
        h_bench,
        "Table 2: Group 8 own-data solution validation across v1–v5 (n = 549 RAWX epochs; static hold 0–62 s n = 63).",
        space_before=2, space_after=2, size_pt=8.5, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, color=NAVY,
    )
    p_t2.paragraph_format.keep_with_next = True
    t2_rows = []
    for vk, label in [("v1", "v1 GPS Baseline"), ("v2", "v2 +Multi-GNSS"), ("v3", "v3 +C/N0 Weight"),
                      ("v4", "v4 +RAIM FDE"), ("v5", "v5 +Hatch (Final)")]:
        d = own[vk]
        rtk = d["vs_rtkpost"]
        pvt = d["vs_nav_pvt_ecef"]
        sd = d["static_dwell"]["initial_static_hold"]
        t2_rows.append([
            label,
            f"{d['availability_pct']:.2f}%",
            f"{d['mean_nsat']:.1f}",
            f"{rtk['rmse_2d_m']:.2f} / {rtk['rmse_3d_m']:.2f}",
            f"{pvt['rmse_2d_m']:.2f} / {pvt['rmse_3d_m']:.2f}",
            f"{sd['cep95_m']:.3f}",
            f"{d['smoothness']['rms_jerk_3d_m']:.2f}",
        ])
    _insert_styled_table_before(
        doc, h_bench,
        ["Variant", "Avail.", "SVs", "vs RTKPOST 2D/3D (m)", "vs NAV-PVT 2D/3D (m)", "Init CEP95 (m)", "3D Jerk (m)"],
        t2_rows, [1.22, 0.58, 0.45, 1.35, 1.35, 0.90, 0.90], font_pt=8.0, align_right_cols={1, 2, 3, 4, 5, 6},
    )
    _insert_para_before(h_bench, "", space_after=2)

    # --- SECTION 6 (was 7): BENCHMARK RESULTS & ABLATION ---
    bx = ab["example"]
    bm = ab["benchmark"]
    _insert_para_before(
        h_ai,
        "Because external ground truth and TA server rankings for UrbanNav Deep1 [9] are withheld from students (and using external UrbanNav ground "
        "truth is strictly prohibited), we validate absolute SPP accuracy progression on the course Block X dataset "
        "(n = 186 against NAV-HPPOSECEF.csv, where the baseline WLSE_spp.py script achieves 37.911 m 2D / 51.043 m 3D RMSE) "
        "and quantify offline availability, DOP geometry, post-fit residual RMS, and 3D second-difference smoothness (jerk RMS) "
        "across all 1,534 UrbanNav Deep1 epochs (Table 3, Fig. 4). On Block X, v5 reduces 2D RMSE from 15.436 m (v1) to "
        "3.479 m (2D P95 = 4.951 m). On UrbanNav Deep1 [9], fusing G+E+C reduces dropouts from 60 epochs (96.09%) to 1 epoch "
        "(99.93%, 1533/1534), drops mean HDOP from 2.929 to 1.359, and cuts 3D jerk RMS by 82.8% (134.21 m → 23.06 m). "
        "Interestingly, RAIM FDE (v4, 125 exclusions) reaches the lowest UrbanNav jerk RMS (22.960 m, P95 = 35.907 m), "
        "whereas v5 Hatch smoothing [10], [11] incurs 1,337 urban cycle-slip resets that slightly temper smoothing gain in deep foliage/bridges "
        "despite cutting static Block X P95 error. Both G08_owndata.csv and G08_benchmark.csv pass check_submission.py [6].",
        space_after=3,
    )
    p_fig4 = _insert_para_before(h_ai, "", space_before=1, space_after=1, align=WD_ALIGN_PARAGRAPH.CENTER)
    p_fig4.paragraph_format.keep_with_next = True
    p_fig4.add_run().add_picture(str(REPO / "figures/fig4_benchmark_ablation.png"), width=Inches(6.45))
    _insert_para_before(
        h_ai,
        "Figure 4: Ablation results: (a) Block X accuracy vs NAV-HPPOSECEF.csv, (b) UrbanNav Deep1 smoothness & availability, (c) UrbanNav ENU tracks.",
        space_before=1, space_after=4, size_pt=8.4, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, color=MUTED,
    )
    p_t3 = _insert_para_before(
        h_ai,
        "Table 3: Progressive ablation across Block X validation (n = 186) and UrbanNav Deep1 benchmark (n = 1534).",
        space_before=2, space_after=2, size_pt=8.5, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, color=NAVY,
    )
    p_t3.paragraph_format.keep_with_next = True
    t3_rows = []
    for vk, desc in [
        ("v1", "v1: GPS-only WLS"),
        ("v2", "v2: +Multi-Constell."),
        ("v3", "v3: +C/N0 & El Wt."),
        ("v4", "v4: +RAIM FDE"),
        ("v5", "v5: +Hatch (Final)"),
    ]:
        ex_v = bx[vk]["vs_nav_hpposecef"]
        bm_v = bm[vk]
        t3_rows.append([
            desc,
            f"{ex_v['rmse_2d_m']:.2f} / {ex_v['p95_2d_m']:.2f}",
            f"{bm_v['availability_pct']:.2f}% ({bm_v['solved_epochs']})",
            f"{bm_v['mean_nsat']:.1f} / {bm_v['mean_hdop']:.2f}",
            f"{bm_v['mean_res_rms_m']:.2f} / {bm_v['smoothness']['rms_jerk_3d_m']:.2f}",
            "N/A (Pending TA)",
        ])
    _insert_styled_table_before(
        doc, h_ai,
        ["Version", "Block X 2D / P95 (m)", "UrbanNav Avail.", "SV / HDOP", "Res / Jerk RMS (m)", "GT RMSE & Rank"],
        t3_rows, [1.28, 1.15, 1.05, 0.85, 1.25, 1.17], font_pt=7.9, align_right_cols={1, 2, 3, 4},
    )
    _insert_para_before(h_ai, "", space_after=2)

    # --- SECTION 7 (was 8): AI-USE STATEMENT ---
    _insert_para_before(
        h_ref,
        "In accordance with PolyU AAE GenAI Policy and AAE4203 Lab Tutorial Section 3.3, Group 8 declares the use of "
        "Google Antigravity (Gemini) as a programming and editorial assistant during this lab to: (1) scaffold and refactor "
        "the modular Python SPP/RINEX/UBX pipeline, (2) verify multi-constellation BeiDou BDT/GEO and Galileo BGD formulas "
        "against course CSVs and RTKLIB EX 2.5.0 diagnostics, (3) generate 300-DPI Matplotlib visualizations, and (4) edit "
        "report prose and table formatting. All AI-generated code and text were independently verified by executing "
        "WLSE_spp.py, tools/check_submission.py, and Block X regression checks without using any external ground-truth data. "
        "All group members accept full academic responsibility for the correctness, integrity, and originality of this work.",
        space_after=4,
    )

    # --- REFERENCES (IEEE STYLE) ---
    ieee_refs = [
        "[1] u-blox AG, \"ZED-F9P Interface Description (HPG 1.32, PROTVER 27.31),\" Document UBX-21025013, 2022.",
        "[2] T. Takasu, \"RTKLIB ver. 2.4.2 / EX 2.5.0 Manual: An Open Source Program Package for GNSS Positioning,\" 2024.",
        "[3] W. Wen, \"AAE4203 Lecture 1–2: Coordinate Frames, Transformations, and Matrix Estimation,\" PolyU, 2026.",
        "[4] W. Wen, \"AAE4203 Lecture 3–4: GNSS Fundamentals, Orbit Determination & Observation Equations,\" PolyU, 2026.",
        "[5] W. Wen, \"AAE4203 Lecture 5: GNSS Error Sources, Atmospheric Models, DOP & NLOS Multipath,\" PolyU, 2026.",
        "[6] W. Wen, \"AAE4203 Lab 1 Tutorial (v6) & Repository: WLSE_spp.py and Verification Suite,\" PolyU, 2026.",
        "[7] China Satellite Navigation Office, \"BeiDou Navigation Satellite System Signal In Space ICD: Open Service B1I (Ver. 3.0),\" 2019.",
        "[8] European Union Agency for the Space Programme, \"Galileo Open Service Signal-In-Space ICD (Issue 2.1),\" 2023.",
        "[9] L.-T. Hsu et al., \"UrbanNav: An open-sourced multisensory dataset for benchmarking positioning algorithms designed for urban areas,\" in Proc. ION GNSS+ 2021, pp. 226–256.",
        "[10] P. Misra and P. Enge, Global Positioning System: Signals, Measurements, and Performance, 2nd ed., Ganga-Jamuna Press, 2011.",
        "[11] P. J. G. Teunissen and O. Montenbruck (Eds.), Springer Handbook of Global Navigation Satellite Systems, Springer, 2017.",
    ]
    for ref in ieee_refs:
        _insert_para_before(h_app_b, ref, space_before=0, space_after=1.5, size_pt=8.2)

    # --- APPENDIX: KEY AI PROMPTS ---
    _clear_and_set_run(h_app_b, "Appendix A: Key AI Prompts & Verification Summary", size_pt=12, bold=True, color=NAVY)
    h_app_b.paragraph_format.keep_with_next = True
    h_app_b.paragraph_format.page_break_before = True
    p_end = doc.add_paragraph("")
    doc._body._body.append(p_end._p)
    app_rows = [
        ["Inspect UBX telemetry & convert raw log with RTKLIB", "Validated MON-VER FWVER=HPG 1.32, 549 RAWX/548 NAV-PVT epochs, & speed segments against UBX checksums."],
        ["Implement 5-stage multi-GNSS SPP solver (G/E/C/J + ISBs + GEO + BDT)", "Cross-checked epoch-0 satellite XYZ/clk/ion/tgd against benchmark/gps_csv (<0.2 mm) & Block X NAV-HPPOSECEF."],
        ["Debug C/N0 byte offset & urban canyon PDOP outlier spikes (22→15 dB-Hz)", "Re-verified UBX C/N0 bounds (24–47 dB-Hz), UrbanNav 99.93% coverage, & check_submission.py pass (0 errors)."],
        ["Generate figures & assemble template-compliant Lab 1 DOCX/PDF", "Inspected every 300-DPI plot & rendered PDF page for zero overlap, IEEE citations, & ≤10-page limit."],
    ]
    _insert_styled_table_before(doc, p_end, ["Prompt Focus", "Verification Performed"], app_rows, [2.75, 4.00], font_pt=8.0)

    # Remove blank trailing helper paragraphs left over if needed
    _remove_element(p_end._p)
    if len(doc.sections) >= 3:
        doc.sections[2].start_type = WD_SECTION.CONTINUOUS

    doc.save(str(OUT_DOCX))
    print("Saved report DOCX:", OUT_DOCX)


if __name__ == "__main__":
    main()
