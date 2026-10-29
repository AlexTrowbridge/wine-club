import io

import openpyxl
import pytest
from django.urls import reverse

from club import stats
from club.importer import import_workbook
from club.models import Rating, Tasting, Wine

PAGES = [
    ("dashboard", []),
    ("session_list", []),
    ("session_detail", [2]),
    ("session_score", [2]),
    ("wine_list", []),
    ("region_map", []),
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


@pytest.mark.parametrize(
    "name, args",
    [("analysis", []), ("analysis", ["price"]), ("price_analysis", []), ("matrix", [])],
)
def test_analysis_pages_show_every_tab(client, organiser, imported, name, args):
    client.force_login(organiser)
    html = client.get(reverse(name, args=args)).content.decode()
    for key in stats.DIMENSIONS:
        assert f'href="{reverse("analysis", args=[key])}"' in html
    assert f'href="{reverse("price_analysis")}"' in html
    assert f'href="{reverse("matrix")}"' in html


def test_price_dimension_is_not_shadowed_by_price_analysis(client, organiser, imported):
    client.force_login(organiser)
    response = client.get(reverse("analysis", args=["price"]))
    assert response.resolver_match.url_name == "analysis"
    assert response.context["dimension"] == "price"


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


@pytest.mark.parametrize(
    "name, params",
    [
        ("leaderboards", {"n": "abc"}),
        ("leaderboards", {"n": "-1"}),
        ("wine_list", {"country": "abc", "year": "x", "era": "1;", "purchaser": " "}),
        ("session_score", {"member": "abc"}),
    ],
)
def test_bad_query_params_do_not_crash(client, organiser, imported, name, params):
    client.force_login(organiser)
    args = [2] if name == "session_score" else []
    assert client.get(reverse(name, args=args), params).status_code in (200, 404)


def test_readyz_hides_error_details(client, db, monkeypatch):
    class BrokenConnection:
        def cursor(self):
            raise RuntimeError("db at secret-host:5432")

    monkeypatch.setattr("club.views.connection", BrokenConnection())
    resp = client.get(reverse("readyz"))
    assert resp.status_code == 503
    assert b"secret-host" not in resp.content
