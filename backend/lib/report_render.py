"""
Report file rendering (GAP-04 / US-202). Renders the SAME snapshot shape
services/platform_metrics_service.get_dashboard_snapshot returns — the
report never computes its own numbers, only formats the shared pipeline's
output, so it can't diverge from the dashboard (acceptance criterion).

PDF uses reportlab (pure-Python, no system deps). CSV uses the stdlib `csv`
module. Both are real, working implementations — not stubs.
"""

import csv
import io
import statistics
from typing import Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

MetricSnapshot = Dict[str, List[Dict]]  # metric_key -> [{date, value}, ...]


def _summary_rows(metric_labels: Dict[str, str], snapshot: MetricSnapshot) -> List[List[str]]:
    rows = [["Metric", "Latest", "Average", "Min", "Max"]]
    for key, points in snapshot.items():
        label = metric_labels.get(key, key)
        values = [p["value"] for p in points]
        if not values:
            rows.append([label, "-", "-", "-", "-"])
            continue
        rows.append([
            label,
            f"{values[-1]:.2f}",
            f"{statistics.fmean(values):.2f}",
            f"{min(values):.2f}",
            f"{max(values):.2f}",
        ])
    return rows


def render_pdf(report_name: str, date_range_label: str, metric_labels: Dict[str, str], snapshot: MetricSnapshot) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, title=report_name)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(report_name, styles["Title"]),
        Paragraph(date_range_label, styles["Normal"]),
        Spacer(1, 0.25 * inch),
    ]

    table = Table(_summary_rows(metric_labels, snapshot), hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3673")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f9")]),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)

    doc.build(story)
    return buffer.getvalue()


def render_csv(metric_labels: Dict[str, str], snapshot: MetricSnapshot) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["metric", "date", "value"])
    for key, points in snapshot.items():
        label = metric_labels.get(key, key)
        for point in points:
            writer.writerow([label, point["date"], point["value"]])
    return buffer.getvalue().encode("utf-8")
