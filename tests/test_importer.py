from decimal import Decimal

import pytest

from club.importer import import_workbook
from club.models import Attendance, Era, Member, Rating, Session, Tasting, Wine


def test_import_counts_and_checks(imported):
    assert imported.ok, (imported.errors, imported.checks)
    assert imported.members == 4
    assert imported.sessions == 2
    assert imported.tastings == 4
    assert Wine.objects.count() == 4
    assert Rating.objects.count() == 14
    assert list(Era.objects.values_list("name", flat=True)) == ["Old Era", "New Era"]


def test_import_details(imported):
    s2 = Session.objects.get(number=2)
    assert s2.theme == "Grenache Day"
    assert s2.era.name == "New Era"
    assert s2.status == Session.Status.CLOSED

    henschke = Tasting.objects.get(wine__producer="Henschke")
    assert henschke.purchaser.display_name == "Ben"
    assert henschke.price == Decimal("33")
    assert henschke.wine.jh_score == 92
    assert henschke.wine.is_blend is True
    assert henschke.wine.region.country.name == "Australia"
    assert [v.name for v in henschke.wine.varietals.order_by("winevarietal__order")] == [
        "Shiraz",
        "Grenache",
        "Mourvèdre",
        "Viognier",
    ]
    # "x" = tasted, no score.
    dev = henschke.ratings.get(member__display_name="Dev")
    assert dev.score is None

    bolly = Tasting.objects.get(wine__producer="Bollinger")
    assert bolly.shared_purchase and bolly.purchaser is None
    assert bolly.purchaser_label == "Everyone"


def test_attendance_imported(imported):
    dev = Member.objects.get(display_name="Dev")
    assert Attendance.objects.filter(member=dev).count() == 1


def test_import_is_idempotent(imported, sample_workbook):
    counts = (Wine.objects.count(), Tasting.objects.count(), Rating.objects.count())
    report = import_workbook(sample_workbook)
    assert report.ok
    assert report.wines == 0
    assert (Wine.objects.count(), Tasting.objects.count(), Rating.objects.count()) == counts


def test_import_reports_scores_without_attendance(db, tmp_path):
    from .workbook import MEMBERS, SAMPLE, build_workbook

    sample = [(era, [dict(s) for s in sessions]) for era, sessions in SAMPLE]
    sample[1][1][0]["attendance"] = {"Ben": "P", "Cleo": "P"}  # Ava & Dev scored, not marked
    path = tmp_path / "wb.xlsx"
    build_workbook(path, MEMBERS, sample)
    report = import_workbook(path)
    failed = [label for label, ok, _ in report.checks if not ok]
    assert any("Attendance" in label for label in failed)


@pytest.mark.parametrize("value", ["bad", 3])
def test_bad_score_cells_are_flagged(db, tmp_path, value):
    from .workbook import MEMBERS, SAMPLE, build_workbook

    sample = [(era, [dict(s) for s in sessions]) for era, sessions in SAMPLE]
    bottle = dict(sample[0][1][0]["bottles"][0])
    bottle["scores"] = {**bottle["scores"], "Dev": value}
    sample[0][1][0]["bottles"] = [bottle]
    path = tmp_path / "wb.xlsx"
    build_workbook(path, MEMBERS, sample)
    report = import_workbook(path)
    flagged = any("unreadable score" in r["issue"] for r in report.review)
    assert flagged == (value == "bad")
