import io

import openpyxl
import pytest
from django.urls import reverse

from club.importer import import_workbook
from club.models import Rating, Tasting, Wine

PAGES = [
    ("dashboard", []),
    ("session_list", []),
    ("session_detail", [2]),
    ("session_score", [2]),
    ("wine_list", []),
    ("member_list", []),
    ("leaderboards", []),
    ("analysis", []),
    ("analysis", ["vintage"]),
    ("analysis", ["price"]),
    ("price_analysis", []),
    ("matrix", []),
    ("attendance", []),
]


@pytest.mark.parametrize("name, args", PAGES)
def test_pages_render(client, organiser, imported, name, args):
    client.force_login(organiser)
    assert client.get(reverse(name, args=args)).status_code == 200


def test_detail_pages_render(client, organiser, imported):
    client.force_login(organiser)
    wine = Wine.objects.first()
    assert client.get(wine.get_absolute_url()).status_code == 200
    member = Rating.objects.first().member
    assert client.get(member.get_absolute_url()).status_code == 200


def test_unknown_analysis_dimension_404(client, organiser, db):
    client.force_login(organiser)
    assert client.get("/analysis/nonsense/").status_code == 404


def test_export_round_trips(client, organiser, imported, tmp_path, django_db_reset_sequences):
    client.force_login(organiser)
    resp = client.get(reverse("export_xlsx"))
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert wb.sheetnames == ["Raw Ratings", "Results", "Attendance"]

    before = sorted(
        (t.wine.full_name, sorted((r.member.display_name, r.score) for r in t.ratings.all()))
        for t in Tasting.objects.all()
    )
    path = tmp_path / "export.xlsx"
    path.write_bytes(resp.content)
    Tasting.objects.all().delete()
    report = import_workbook(path)
    assert report.ok, (report.errors, report.checks)
    after = sorted(
        (t.wine.full_name, sorted((r.member.display_name, r.score) for r in t.ratings.all()))
        for t in Tasting.objects.all()
    )
    assert before == after
