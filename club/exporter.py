"""Export the database back to a workbook laid out like the original spreadsheet."""

import io
import statistics

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from .models import Attendance, Member, Rating, Session, Tasting

BOLD = Font(bold=True)


def _bold_row(ws, row):
    for cell in ws[row]:
        cell.font = BOLD


def export_workbook(fh):
    members = list(Member.objects.all())
    wb = Workbook()
    raw = wb.active
    raw.title = "Raw Ratings"
    results = wb.create_sheet("Results")
    attendance = wb.create_sheet("Attendance")

    # Two header rows on every sheet, row-aligned, exactly as the original workbook
    # (so an export can be re-imported).
    raw.append([None, None, None, None, "Ratings"])
    raw.append(["#", "Wine", "Date", "Purchased by", "Average", *[m.display_name for m in members]])
    results.append(["Wine Details", None, None, None, None, "Ratings", "Other Details"])
    results.append(
        [
            "#",
            "Wine",
            "Date",
            "Wine #",
            "Purchased by",
            "Average",
            "Age Consumed",
            "Price",
            "Single Varietal/Blend",
            "Region",
            "Country",
            "Min",
            "Max",
            "MinMax Diff",
            "100 pt scale",
            "JH Score",
        ]
    )
    for ws in (raw, results):
        _bold_row(ws, ws.max_row)

    tastings = (
        Tasting.objects.visible()
        .select_related("wine__region__country", "session__era", "purchaser")
        .prefetch_related("ratings", "wine__winevarietal_set")
        .order_by("session__date", "position")
    )
    era = None
    for i, t in enumerate(tastings, start=1):
        if t.session.era_id != getattr(era, "pk", None):
            era = t.session.era
            raw.append(["", era.name])
            results.append(["", era.name])
            _bold_row(raw, raw.max_row)
            _bold_row(results, results.max_row)
        by_member = {r.member_id: r for r in t.ratings.all()}
        scores = [float(r.score) for r in by_member.values() if r.score is not None]
        avg = statistics.fmean(scores) if scores else None
        cells = []
        for m in members:
            r = by_member.get(m.pk)
            cells.append(None if r is None else ("x" if r.score is None else float(r.score)))
        raw.append([i, t.wine.full_name, t.session.date, t.purchaser_label, avg, *cells])
        wine = t.wine
        results.append(
            [
                i,
                wine.full_name,
                t.session.date,
                t.position,
                t.purchaser_label,
                avg,
                t.age_consumed,
                float(t.price) if t.price is not None else None,
                "Blend" if wine.blend else "Single Varietal",
                wine.region.name if wine.region else None,
                wine.region.country.name if wine.region else None,
                min(scores, default=None),
                max(scores, default=None),
                (max(scores) - min(scores)) if scores else None,
                50 * avg**0.3 if avg else None,
                wine.jh_score,
            ]
        )
        raw.cell(raw.max_row, 3).number_format = "dd/mm/yyyy"
        results.cell(results.max_row, 3).number_format = "dd/mm/yyyy"

    attendance.append([])
    attendance.append([None, None, None, *[m.display_name for m in members]])
    attendance.append([])
    attendance.append(["No.", "Date", "Theme"])
    _bold_row(attendance, 2)
    _bold_row(attendance, 4)
    present = set(Rating.objects.values_list("tasting__session_id", "member_id").distinct())
    present |= set(Attendance.objects.values_list("session_id", "member_id"))
    bought = set(
        Tasting.objects.filter(purchaser__isnull=False).values_list("session_id", "purchaser_id")
    )
    era = None
    for s in Session.objects.select_related("era").order_by("date"):
        if s.era_id != getattr(era, "pk", None):
            era = s.era
            attendance.append([era.name])
            _bold_row(attendance, attendance.max_row)
        marks = [
            "P" if (s.pk, m.pk) in bought else ("X" if (s.pk, m.pk) in present else None)
            for m in members
        ]
        attendance.append([s.number, s.date, s.theme or "-", *marks])
        attendance.cell(attendance.max_row, 2).number_format = "dd/mm/yyyy"

    for ws, widths in ((raw, {2: 60}), (results, {2: 60, 10: 20}), (attendance, {3: 20})):
        ws.freeze_panes = "C5" if ws is attendance else "C3"
        for col, width in widths.items():
            ws.column_dimensions[get_column_letter(col)].width = width
        ws.column_dimensions["C"].width = max(ws.column_dimensions["C"].width or 0, 12)

    buf = io.BytesIO()
    wb.save(buf)
    fh.write(buf.getvalue())
