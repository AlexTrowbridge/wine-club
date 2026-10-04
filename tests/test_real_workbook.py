"""Checks against the club's real workbook. Skipped when the file isn't present
(it holds personal data and is deliberately not committed)."""

from pathlib import Path

import pytest

from club import stats
from club.importer import import_workbook

WORKBOOK = Path(__file__).resolve().parent.parent / "Wine Club.xlsx"


@pytest.mark.skipif(not WORKBOOK.exists(), reason="Wine Club.xlsx not present")
def test_real_workbook_matches_stats_sheet(db):
    report = import_workbook(WORKBOOK)
    assert not report.errors
    assert (report.members, report.sessions, report.tastings) == (26, 84, 262)
    checks = {label: ok for label, ok, _ in report.checks}
    assert checks["Per-wine averages match the sheet"]

    data = stats.bottles()
    top = stats.top_wines(data, n=2)
    assert top[0].wine.full_name == "Isabel Estate 2022 Sauvignon Blanc"
    assert top[0].avg == 9
    assert top[1].avg == pytest.approx(8.8)

    by_country = {r["label"]: r for r in stats.breakdown(data, "country")}
    assert by_country["Australia"]["n"] == 217
    assert by_country["New Zealand"]["mean"] == pytest.approx(7.6342857142857143)

    single = {r["label"]: r for r in stats.breakdown(data, "single-varietal")}
    assert single["Pinot Meunier"]["mean"] == 8

    ms = stats.member_stats(data)
    best = stats.ranked(ms, lambda r: r.avg_of_purchases)
    assert best[0][1].member.display_name == "Laurence"
    diff = stats.ranked(ms, lambda r: r.purchase_difference)
    assert diff[0][1].member.display_name == "Zoe"
    assert diff[0][1].purchase_difference == pytest.approx(1.3571428571428568)
