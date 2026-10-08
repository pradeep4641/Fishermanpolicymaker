"""
report.py — PDF report generation via ReportLab.
generate_report() returns raw PDF bytes — caller streams them as a response.
"""

from io import BytesIO
from datetime import date
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT

from obis import get_occurrences_for_period, get_region_labels
from calculations import (
    regional_health_index,
    compare_periods,
    detect_anomalies,
)

# Brand colour
OCEAN_BLUE  = colors.HexColor("#1565C0")
TEAL        = colors.HexColor("#00838F")
LIGHT_BLUE  = colors.HexColor("#E3F2FD")
DARK_TEXT   = colors.HexColor("#1A237E")
WARN_RED    = colors.HexColor("#C62828")


def _styles():
    base = getSampleStyleSheet()
    custom = {
        "Title": ParagraphStyle(
            "OceanTitle", fontSize=22, textColor=OCEAN_BLUE,
            spaceAfter=6, alignment=TA_CENTER, fontName="Helvetica-Bold",
        ),
        "Subtitle": ParagraphStyle(
            "OceanSub", fontSize=12, textColor=TEAL,
            spaceAfter=4, alignment=TA_CENTER, fontName="Helvetica",
        ),
        "SectionHead": ParagraphStyle(
            "SectionHead", fontSize=13, textColor=DARK_TEXT,
            spaceBefore=14, spaceAfter=4, fontName="Helvetica-Bold",
        ),
        "Body": ParagraphStyle(
            "Body", fontSize=10, leading=14, spaceAfter=6, fontName="Helvetica",
        ),
        "Small": ParagraphStyle(
            "Small", fontSize=9, textColor=colors.grey, spaceAfter=4, fontName="Helvetica",
        ),
    }
    return custom


def _table(data: list[list], col_widths=None):
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0),  OCEAN_BLUE),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",     (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LIGHT_BLUE, colors.white]),
        ("GRID",         (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING",      (0, 0), (-1, -1), 5),
    ]))
    return t


def generate_report(
    region: str,
    period_a: str,
    period_b: str,
    scenario_result: dict | None = None,
) -> bytes:
    """
    Generate a PDF report and return raw bytes.

    period_a / period_b: "YYYY-MM-DD:YYYY-MM-DD" (start:end)
    scenario_result: optional what-if projection dict from calculations.project_scenario
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = _styles()
    region_label = get_region_labels().get(region, region.replace("_", " ").title())

    # Parse period strings
    def parse_period(p: str):
        parts = p.split(":")
        return parts[0], parts[1] if len(parts) == 2 else ("", "")

    a_start, a_end = parse_period(period_a)
    b_start, b_end = parse_period(period_b)

    records_a = get_occurrences_for_period(region, a_start, a_end)
    records_b = get_occurrences_for_period(region, b_start, b_end)

    story = []

    # ─── Title Block ────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("🌊 OCEANIX Marine Biodiversity Report", styles["Title"]))
    story.append(Paragraph(f"{region_label}", styles["Subtitle"]))
    story.append(Paragraph(
        f"Generated: {date.today().strftime('%B %d, %Y')} &nbsp;|&nbsp; "
        f"Period A: {a_start} → {a_end} &nbsp;|&nbsp; Period B: {b_start} → {b_end}",
        styles["Small"],
    ))
    story.append(HRFlowable(width="100%", thickness=1.5, color=OCEAN_BLUE, spaceAfter=10))

    # ─── Section 1: Regional Health Index ───────────────────────────────────
    story.append(Paragraph("1. Regional Health Index", styles["SectionHead"]))
    hi = regional_health_index(records_b, records_a)
    grade_color = (
        colors.green if hi["grade"] == "Excellent" else
        colors.orange if hi["grade"] in ("Good", "Fair") else
        WARN_RED
    )
    hi_data = [
        ["Metric", "Value"],
        ["Composite Score", f"{hi['score']}/100"],
        ["Grade", hi["grade"]],
        ["Biodiversity Component", f"{hi['components']['biodiversity']}/100"],
        ["Trend Component", f"{hi['components']['trend']}/100"],
        ["Stability Component", f"{hi['components']['stability']}/100"],
        ["Confidence Component", f"{hi['components']['confidence']}/100"],
    ]
    story.append(_table(hi_data, col_widths=[10 * cm, 6 * cm]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(f"<i>{hi['interpretation']}</i>", styles["Body"]))

    # ─── Section 2: Period Comparison Table ─────────────────────────────────
    story.append(Paragraph("2. Period Comparison", styles["SectionHead"]))
    cmp = compare_periods(records_a, records_b)
    cmp_data = [
        ["Metric", "Period A", "Period B", "Delta", "% Change"],
        [
            "Species Count",
            cmp["period_a"]["species_count"],
            cmp["period_b"]["species_count"],
            cmp["delta"]["species_count"],
            f"{cmp['pct_change']['species_count'] or 'N/A'}%",
        ],
        [
            "Occurrence Count",
            cmp["period_a"]["occurrence_count"],
            cmp["period_b"]["occurrence_count"],
            cmp["delta"]["occurrence_count"],
            f"{cmp['pct_change']['occurrence_count'] or 'N/A'}%",
        ],
        [
            "Avg SST (°C)",
            cmp["period_a"]["avg_sst"] or "N/A",
            cmp["period_b"]["avg_sst"] or "N/A",
            cmp["delta"]["avg_sst"] or "N/A",
            f"{cmp['pct_change']['avg_sst'] or 'N/A'}%",
        ],
    ]
    story.append(_table(cmp_data, col_widths=[5 * cm, 3 * cm, 3 * cm, 2.5 * cm, 2.5 * cm]))

    # ─── Section 3: Top 5 Species ────────────────────────────────────────────
    story.append(Paragraph("3. Top 5 Species by Occurrence Count", styles["SectionHead"]))
    from collections import Counter
    sp_counts = Counter(r["scientificName"] for r in records_b if r.get("scientificName"))
    top5 = sp_counts.most_common(5)
    if top5:
        sp_data = [["Rank", "Scientific Name", "Occurrences"]]
        for i, (name, count) in enumerate(top5, 1):
            sp_data.append([str(i), name, str(count)])
        story.append(_table(sp_data, col_widths=[2 * cm, 12 * cm, 3 * cm]))
    else:
        story.append(Paragraph("No species data available for Period B.", styles["Body"]))

    # ─── Section 4: Flagged Anomalies ────────────────────────────────────────
    story.append(Paragraph("4. Flagged Anomalies", styles["SectionHead"]))
    anom = detect_anomalies(records_b)
    flagged = anom.get("flagged", [])
    if flagged:
        anom_data = [["Type", "Date", "Value", "Reason"]]
        for f in flagged[:10]:
            anom_data.append([
                f["type"],
                f.get("date", ""),
                str(f.get("value", "")),
                Paragraph(f["reason"], styles["Small"]),
            ])
        story.append(_table(anom_data, col_widths=[3.5 * cm, 3 * cm, 2.5 * cm, 7 * cm]))
    else:
        story.append(Paragraph("✓ No significant anomalies detected in Period B.", styles["Body"]))

    # ─── Section 5: What-If Projection ───────────────────────────────────────
    story.append(Paragraph("5. What-If Scenario Projection", styles["SectionHead"]))
    if scenario_result and "error" not in scenario_result:
        proj_data = [
            ["Parameter", "Value"],
            ["Stressor", scenario_result.get("stressor_type", "N/A")],
            ["Severity", f"{float(scenario_result.get('severity', 0)):.0%}"],
            ["Target Year", str(scenario_result.get("target_year", "N/A"))],
            ["Current Species Count", str(scenario_result.get("current_species_count", "N/A"))],
            ["Projected Species Count", str(round(scenario_result.get("adjusted_projected_species", 0)))],
            ["Projected Health Index", f"{scenario_result.get('projected_health_index', 'N/A')}/100"],
        ]
        story.append(_table(proj_data, col_widths=[8 * cm, 8 * cm]))
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(f"<i>{scenario_result.get('interpretation', '')}</i>", styles["Body"]))
    else:
        story.append(Paragraph("No what-if scenario was run for this session.", styles["Body"]))

    # ─── Section 6: Policy Recommendations ───────────────────────────────────
    story.append(Paragraph("6. Policy Recommendations", styles["SectionHead"]))
    score = hi["score"]
    sp_delta = cmp["delta"].get("species_count") or 0
    sst_delta = cmp["delta"].get("avg_sst") or 0

    if score >= 80:
        rec = (
            f"The {region_label} is in excellent health (score: {score}/100). "
            "Continue current conservation measures and expand marine protected area coverage. "
            "Species richness is strong; focus on maintaining habitat integrity and reducing "
            "coastal pollution to sustain these gains."
        )
    elif score >= 60:
        rec = (
            f"The {region_label} shows good but improvable health (score: {score}/100). "
            f"Species count {'increased' if sp_delta >= 0 else 'declined'} by {abs(sp_delta)} "
            f"between periods. Targeted interventions for vulnerable species and SST monitoring "
            f"(trend: {sst_delta:+.2f}°C) are recommended."
        )
    elif score >= 40:
        rec = (
            f"The {region_label} is under stress (score: {score}/100). "
            f"Immediate measures include strengthening fishing regulations, establishing new "
            f"no-take zones, and accelerating coral/seagrass restoration programmes. "
            f"SST anomaly monitoring should be escalated."
        )
    else:
        rec = (
            f"⚠️ The {region_label} is in poor condition (score: {score}/100). "
            "Emergency conservation action is required: moratorium on high-impact fishing, "
            "urgent pollution remediation, and international support for habitat restoration. "
            "Coordinate with CMLRE and state fisheries departments immediately."
        )

    story.append(Paragraph(rec, styles["Body"]))

    # ─── Footer ──────────────────────────────────────────────────────────────
    story.append(Spacer(1, 1 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Paragraph(
        "Data Sources: OBIS (Ocean Biodiversity Information System) · "
        "Open-Meteo Marine API · Regional Health Index (Oceanix calculations) &nbsp;|&nbsp; "
        "Generated by Oceanix Platform",
        styles["Small"],
    ))

    doc.build(story)
    return buf.getvalue()
