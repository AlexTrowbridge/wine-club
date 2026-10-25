import json
import unicodedata
from collections import Counter
from decimal import Decimal

import pytest
from django.urls import reverse

from club import stats
from club.models import Country, Rating, Region
from club.region_details import (
    TEXT_FIELDS,
    create_curated_regions,
    fill_region_details,
    load_region_details,
)


def _markers(response):
    html = response.content.decode()
    start = html.index('<script id="region-markers" type="application/json">')
    payload = html[start:].split(">", 1)[1].split("</script>", 1)[0]
    return {(m["country"], m["name"]): m for m in json.loads(payload)}


def _tasted(markers):
    return {key: marker for key, marker in markers.items() if marker["tasted"]}


def _folded(name):
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def test_details_file_is_well_formed():
    details = load_region_details()
    assert ("Australia", "McLaren Vale") in details
    for entry in details.values():
        assert -90 <= entry["lat"] <= 90 and -180 <= entry["lng"] <= 180
        assert entry["summary"]


def test_details_have_no_near_duplicate_names():
    details = load_region_details()
    canonical = [key for key, entry in details.items() if not entry.get("variant_of")]
    counts = Counter((country, _folded(name)) for country, name in canonical)
    assert [key for key, n in counts.items() if n > 1] == []
    for (country, _name), entry in details.items():
        if entry.get("variant_of"):
            assert (country, entry["variant_of"]) in details


def test_migrations_create_untasted_regions(db):
    """The test database is migrated, so curated regions exist before any import."""
    tokaj = Region.objects.get(name="Tokaj", country__name="Hungary")
    assert tokaj.has_location
    assert "Furmint" in tokaj.typical_varietals
    assert not Region.objects.filter(name="Duoro").exists()  # workbook misspelling only


def test_create_curated_regions_is_idempotent_and_keeps_edits(db):
    wachau = Region.objects.get(name="Wachau")
    wachau.soils = "Our own notes"
    wachau.save()
    count = Region.objects.count()
    assert create_curated_regions(Region, Country) == 0
    assert Region.objects.count() == count
    wachau.refresh_from_db()
    assert wachau.soils == "Our own notes"

    wachau.delete()
    assert create_curated_regions(Region, Country) == 1
    assert Region.objects.get(name="Wachau").soils != "Our own notes"


def test_import_fills_region_details(imported):
    barossa = Region.objects.get(name="Barossa Valley")
    assert barossa.has_location
    assert "Shiraz" in barossa.typical_varietals


def test_fill_keeps_edited_fields(db):
    region = Region.objects.get(name="Clare Valley", country__name="Australia")
    region.soils = "Our own notes"
    region.latitude, region.longitude = Decimal("-1"), Decimal("2")
    region.climate = ""
    region.save()
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
    assert markers[("France", "Champagne")]["tasted"]


def test_map_shows_untasted_regions(client, organiser, imported):
    client.force_login(organiser)
    markers = _markers(client.get(reverse("region_map")))
    tokaj = markers[("Hungary", "Tokaj")]
    assert (tokaj["tasted"], tokaj["bottles"], tokaj["mean"]) == (False, 0, None)
    assert len(_tasted(markers)) < len(markers)


def test_untasted_region_panel(client, organiser, db):
    client.force_login(organiser)
    region = Region.objects.get(name="Tokaj")
    html = client.get(region.get_absolute_url(), headers={"HX-Request": "true"}).content.decode()
    assert "hasn't tasted a wine from this region yet" in html
    assert "Furmint" in html
    assert "All wines from Hungary" not in html


def test_wine_list_offers_only_countries_with_wines(client, organiser, imported):
    client.force_login(organiser)
    countries = client.get(reverse("wine_list")).context["countries"]
    names = {country.name for country in countries}
    assert "France" in names
    assert "Hungary" not in names


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
    region = Region.objects.get(name="McLaren Vale", country__name="Australia")
    tasting = open_session["tasting"]
    tasting.wine.region = region
    tasting.wine.save()
    Rating.objects.create(tasting=tasting, member=open_session["bob"], score=Decimal("9"))
    client.force_login(open_session["alice"].user)

    assert _tasted(_markers(client.get(reverse("region_map")))) == {}
    panel = client.get(region.get_absolute_url(), headers={"HX-Request": "true"})
    assert "9.00" not in panel.content.decode()
