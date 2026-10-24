"""Import the club's legacy ``Wine Club.xlsx`` workbook into the database.

Sheets used (cached values only, formulas are ignored):

* **Raw Ratings**: one row per bottle, member scores in columns F onwards
  (header row 2), "Era" header rows have no ``#``. ``x`` = tasted, no score.
* **Results**: the same rows (row-aligned with Raw Ratings) with metadata:
  Wine #, purchaser, age, price, single varietal/blend, region, country, JH score.
* **Attendance**: one row per session (No., Date, Theme), members in columns D
  onwards; ``P`` = brought a bottle, ``X`` = attended. Era header rows in column A.

The import is idempotent: sessions are keyed on number, tastings on their
spreadsheet ``#``, ratings on (tasting, member).
"""

import csv
import datetime as dt
import math
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import openpyxl
from django.db import IntegrityError, transaction

from .models import (
    Attendance,
    Country,
    Era,
    Member,
    Rating,
    Region,
    Session,
    Tasting,
    Varietal,
    Wine,
)
from .naming import VARIETALS, parse_wine_name
from .region_details import fill_region_details
from .services import set_varietals

# Known data-entry errors in the workbook, verified against session order:
# Attendance #43/#44 have day and month swapped; Raw Ratings #187-188 have the
# wrong year (the bottles sit between 2025 sessions and session #59 is 2025-03-07).
DATE_CORRECTIONS: dict[dt.date, dt.date] = {
    dt.date(2024, 5, 7): dt.date(2024, 7, 5),
    dt.date(2024, 5, 12): dt.date(2024, 7, 12),
    dt.date(2024, 3, 7): dt.date(2025, 3, 7),
}

SHARED_PURCHASER = "Everyone"
FIRST_MEMBER_COL = 5  # column F in Raw Ratings (0-based)
ATT_FIRST_MEMBER_COL = 3  # column D in Attendance
CLOSED_SESSION = {"status": Session.Status.CLOSED, "scores_revealed": True}


@dataclass
class ImportReport:
    members: int = 0
    sessions: int = 0
    wines: int = 0
    tastings: int = 0
    ratings: int = 0
    attendances: int = 0
    review: list[dict] = field(default_factory=list)  # rows for import_review.csv
    errors: list[str] = field(default_factory=list)
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def flag(self, legacy_number, name, issue):
        self.review.append({"#": legacy_number, "wine": name, "issue": issue})

    def check(self, label, ok, detail=""):
        self.checks.append((label, ok, detail))

    @property
    def ok(self):
        return not self.errors and all(ok for _, ok, _ in self.checks)

    def counts_line(self) -> str:
        return (
            f"Members: {self.members}  Sessions: {self.sessions}  "
            f"Wines: {self.wines} new  Tastings: {self.tastings}  "
            f"Ratings: {self.ratings}  Attendances: {self.attendances}"
        )

    def summary_text(self) -> str:
        """Plain-text report: counts, checks, errors and items to review."""
        lines = [self.counts_line()]
        for label, ok, detail in self.checks:
            lines.append(f"[{'ok' if ok else '!!'}] {label}")
            if detail:
                lines.append(f"     {detail}")
        lines += [f"ERROR: {error}" for error in self.errors]
        if self.review:
            lines.append(f"{len(self.review)} item(s) to review:")
            lines += [f"  #{item['#']} {item['wine']}: {item['issue']}" for item in self.review]
        return "\n".join(lines)

    def write_review_csv(self, path: Path):
        with open(path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["#", "wine", "issue"])
            writer.writeheader()
            writer.writerows(self.review)


def seed_varietals():
    for name, aliases in VARIETALS.items():
        Varietal.objects.update_or_create(name=name, defaults={"aliases": ", ".join(aliases)})


def _to_date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        d = value.date()
    elif isinstance(value, dt.date):
        d = value
    elif isinstance(value, (int, float)) and value > 0:
        d = (dt.datetime(1899, 12, 30) + dt.timedelta(days=value)).date()
    else:
        return None
    return DATE_CORRECTIONS.get(d, d)


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _text(value) -> str:
    return "" if _blank(value) else str(value).strip()


def _number(value):
    if _blank(value) or isinstance(value, str):
        return None
    return value


def _rows(ws):
    return list(ws.iter_rows(values_only=True))


def _members_from_header(header) -> list[str]:
    names = []
    for value in header[FIRST_MEMBER_COL:]:
        if _blank(value):
            break
        names.append(str(value).strip())
    return names


@transaction.atomic
def import_workbook(path) -> ImportReport:
    report = ImportReport()
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    raw = _rows(wb["Raw Ratings"])
    results = _rows(wb["Results"])
    attendance = _rows(wb["Attendance"])

    seed_varietals()

    # --- Members (column order of the spreadsheet) -------------------------------
    member_names = _members_from_header(raw[1])
    members: dict[str, Member] = {}
    for i, name in enumerate(member_names):
        members[name], _ = Member.objects.update_or_create(
            display_name=name, defaults={"sort_order": i}
        )
    report.members = len(members)

    # --- Sessions & attendance --------------------------------------------------
    att_members = [_text(v) for v in attendance[1][ATT_FIRST_MEMBER_COL:]]
    if att_members[: len(member_names)] != member_names:
        report.errors.append("Attendance member columns differ from Raw Ratings columns")

    sessions_by_date: dict[dt.date, Session] = {}
    expected_attendance: dict[str, int] = {}
    era = None
    for row in attendance[4:]:
        label, date_cell, theme = row[0], row[1], row[2]
        if isinstance(label, str) and label.strip() and date_cell is None:
            era_name = label.strip()
            era = Era.objects.filter(name=era_name).first()
            if era is None:
                era = Era(name=era_name)
            continue
        date = _to_date(date_cell)
        if not isinstance(label, (int, float)) or date is None:
            continue  # pre-numbered placeholder rows without a date
        if era is None:
            report.errors.append(f"Session {label} appears before any era header")
            continue
        if era.pk is None:
            era.start_date = date
            era.save()
        session_fields = {
            "date": date,
            "theme": "" if _text(theme) in ("", "-") else _text(theme),
            "era": era,
        }
        # Sessions already in the app keep their status, so re-importing the live
        # workbook doesn't close (or reveal) a session that's open for scoring.
        session, _ = Session.objects.update_or_create(
            number=int(label),
            defaults=session_fields,
            create_defaults={**session_fields, **CLOSED_SESSION},
        )
        sessions_by_date[date] = session
        for name, mark in zip(att_members, row[ATT_FIRST_MEMBER_COL:], strict=False):
            if _text(mark).upper() in ("P", "X") and name in members:
                Attendance.objects.get_or_create(session=session, member=members[name])
                expected_attendance[name] = expected_attendance.get(name, 0) + 1
    report.sessions = len(sessions_by_date)

    # --- Wines, tastings, ratings -------------------------------------------------
    regions: dict[tuple[str, str], Region] = {}
    seen_numbers = set()
    avg_mismatches = []
    for i, row in enumerate(raw[2:], start=2):
        number, name = row[0], _text(row[1])
        if not isinstance(number, (int, float)) or not name:
            continue  # era headers and empty pre-numbered rows
        number = int(number)
        meta = results[i] if i < len(results) else ()
        meta = tuple(meta) + (None,) * (16 - len(meta))
        if _text(meta[1]) != name:
            report.errors.append(f"#{number}: Results row does not match Raw Ratings ({name!r})")
            continue

        date = _to_date(row[2])
        session = sessions_by_date.get(date)
        if session is None:
            report.errors.append(f"#{number} {name}: no session on {date}")
            continue

        # Wine (catalogue entry; the same wine may be tasted more than once).
        parsed = parse_wine_name(name)
        for problem in parsed.problems:
            report.flag(number, name, problem)
        region = None
        region_name, country_name = _text(meta[9]), _text(meta[10])
        if region_name and country_name:
            key = (region_name, country_name)
            if key not in regions:
                country, _ = Country.objects.get_or_create(name=country_name)
                regions[key], _ = Region.objects.get_or_create(name=region_name, country=country)
            region = regions[key]
        else:
            report.flag(number, name, "missing region/country")
        blend_label = _text(meta[8])
        jh = _number(meta[15])
        wine, created = Wine.objects.update_or_create(
            full_name=name,
            defaults={
                "producer": parsed.producer,
                "vintage": parsed.vintage,
                "cuvee": parsed.cuvee,
                "region": region,
                "style": parsed.style,
                "is_blend": {"Blend": True, "Single Varietal": False}.get(blend_label),
                "jh_score": int(jh) if jh else None,
            },
        )
        set_varietals(wine, parsed.varietals)
        report.wines += created

        # Tasting.
        purchaser_name = _text(row[3])
        shared = purchaser_name == SHARED_PURCHASER
        purchaser = None if shared else members.get(purchaser_name)
        if purchaser_name and not shared and purchaser is None:
            report.flag(number, name, f"unknown purchaser {purchaser_name!r}")
        price = _number(meta[7])
        position = _number(meta[3])
        tasting, _ = Tasting.objects.update_or_create(
            legacy_number=number,
            defaults={
                "session": session,
                "wine": wine,
                "position": int(position) if position else 0,
                "purchaser": purchaser,
                "shared_purchase": shared,
                "price": Decimal(str(price)) if price is not None else None,
            },
        )
        report.tastings += 1

        age, computed_age = _number(meta[6]), tasting.age_consumed
        if age is not None and computed_age is not None and int(age) != computed_age:
            report.flag(number, name, f"age consumed {int(age)} in sheet, computed {computed_age}")

        # Ratings.
        scores = []
        for member_name, cell in zip(member_names, row[FIRST_MEMBER_COL:], strict=False):
            if _blank(cell):
                continue
            if isinstance(cell, str) and cell.strip().lower() == "x":
                score = None
            elif isinstance(cell, (int, float)):
                score = Decimal(str(cell))
                scores.append(cell)
            else:
                report.flag(number, name, f"unreadable score {cell!r} for {member_name}")
                continue
            Rating.objects.update_or_create(
                tasting=tasting, member=members[member_name], defaults={"score": score}
            )
            report.ratings += 1

        sheet_avg = _number(row[4])
        if scores and sheet_avg is not None:
            ours = sum(scores) / len(scores)
            if not math.isclose(ours, sheet_avg, abs_tol=1e-9):
                avg_mismatches.append(f"#{number}: sheet {sheet_avg:.4f} vs {ours:.4f}")
        seen_numbers.add(number)

    report.attendances = Attendance.objects.count()
    # New regions get their curated map location and details, if we have them.
    fill_region_details(Region)

    # --- Validation ---------------------------------------------------------------
    report.check(
        "Per-wine averages match the sheet",
        not avg_mismatches,
        "; ".join(avg_mismatches[:10]),
    )
    dupes = Tasting.objects.values("session", "position").order_by()
    report.check(
        "Every session has distinct pour positions",
        dupes.count() == len({(d["session"], d["position"]) for d in dupes}),
    )
    attendance_diffs = []
    for name, member in members.items():
        actual, expected = member.attendances.count(), expected_attendance.get(name, 0)
        if actual != expected:
            attendance_diffs.append(f"{name}: sheet {expected}, db {actual}")
    not_closed = sorted(
        session.number
        for session in sessions_by_date.values()
        if session.status != Session.Status.CLOSED
    )
    report.check(
        "Sessions in the sheet are closed in the app",
        not not_closed,
        ", ".join(f"#{number} is still open or planned" for number in not_closed),
    )
    report.check(
        "Attendance totals match the Attendance sheet "
        "(differences = scored without being marked present)",
        not attendance_diffs,
        "; ".join(attendance_diffs),
    )
    return report


def import_workbook_or_rollback(path) -> ImportReport:
    """Import, but leave the database untouched if anything goes wrong.

    ``import_workbook`` commits what it can and lists problems in ``report.errors``
    (useful when cleaning up the original spreadsheet). Imports of the live workbook
    should be all or nothing instead.
    """
    try:
        with transaction.atomic():
            report = import_workbook(path)
            if report.errors:
                transaction.set_rollback(True)
    except IntegrityError as exc:
        report = ImportReport()
        report.errors.append(f"Conflicts with data entered in the app: {exc}")
    except (KeyError, IndexError) as exc:
        report = ImportReport()
        report.errors.append(f"The workbook doesn't have the expected layout: {exc!r}")
    return report
