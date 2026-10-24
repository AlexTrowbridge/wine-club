import json
from decimal import Decimal

import pytest
from django.urls import reverse

from club import stats
from club.models import Country, Rating, Region
from club.region_details import TEXT_FIELDS, fill_region_details, load_region_details


def _markers(response):
    html = response.content.decode()
    start = html.index('<script id="region-markers" type="application/json">')
    payload = html[start:].split(">", 1)[1].split("</script>", 1)[0]
    return {(m["country"], m["name"]): m for m in json.loads(payload)}


def test_details_file_is_well_formed():
    details = load_region_details()
    assert ("Australia", "McLaren Vale") in details
    for entry in details.values():
        assert -90 <= entry["lat"] <= 90 and -180 <= entry["lng"] <= 180
        assert entry["summary"]


def test_import_fills_region_details(imported):
    barossa = Region.objects.get(name="Barossa Valley")
    assert barossa.has_location
    assert "Shiraz" in barossa.typical_varietals


def test_fill_keeps_edited_fields(db):
    australia = Country.objects.create(name="Australia")
    region = Region.objects.create(
        name="Clare Valley",
        country=australia,
        soils="Our own notes",
        latitude=Decimal("-1"),
        longitude=Decimal("2"),
    )
    fill_region_details(Region)
    region.refresh_from_db()
    assert region.soils == "Our own notes"
    assert (region.latitude, region.longitude) == (Decimal("-1"), Decimal("2"))
    assert all(getattr(region, field) for field in TEXT_FIELDS)  # blank fields are filled


def test_map_shows_tasted_regions(client, organiser, imported):
    client.force_login(organiser)
    markers = _markers(client.get(reverse("region_map")))
    assert markers[("Australia", "Barossa Valley")]["bottles"] == 2
    assert markers[("France", "Champagne")]["bottles"] == 1


def test_same_region_name_in_two_countries_stays_separate(client, organiser, imported):
    """'Champagne' also appears under Australia in the real workbook."""
    champagne = Region.objects.get(name="Champagne")
    elsewhere = Region.objects.create(
        name="Champagne", country=Country.objects.create(name="Australia (typo)")
    )
    assert champagne.pk != elsewhere.pk
    data = stats.bottles()
    assert set(stats.region_means(data)) == set(stats.tastings_per_region())
    assert elsewhere.pk not in stats.tastings_per_region()


@pytest.mark.parametrize("htmx", [False, True])
def test_region_detail_renders(client, organiser, imported, htmx):
    client.force_login(organiser)
    region = Region.objects.get(name="Barossa Valley")
    headers = {"HX-Request": "true"} if htmx else {}
    html = client.get(region.get_absolute_url(), headers=headers).content.decode()
    assert "Typical varietals" in html
    assert "Pepperjack" in html
    assert ("<html" in html) is not htmx


def test_unrevealed_scores_stay_hidden_on_map(client, open_session):
    region = Region.objects.create(name="McLaren Vale", country=Country.objects.create(name="Aus"))
    region.latitude, region.longitude = Decimal("-35.2"), Decimal("138.5")
    region.save()
    tasting = open_session["tasting"]
    tasting.wine.region = region
    tasting.wine.save()
    Rating.objects.create(tasting=tasting, member=open_session["bob"], score=Decimal("9"))
    client.force_login(open_session["alice"].user)

    assert _markers(client.get(reverse("region_map"))) == {}
    panel = client.get(region.get_absolute_url(), headers={"HX-Request": "true"})
    assert "9.00" not in panel.content.decode()
