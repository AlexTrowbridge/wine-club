"""Curated wine-region details (map location, climate, soils, grapes) for the region map.

The details live in ``data/region_details.json``, keyed by region and country name exactly
as they appear in the workbook. They cover the club's tasted regions plus the world's other
established regions, which are created as regions of their own so the map can show them
before anyone has tasted from there. Entries with ``variant_of`` match a misspelling used
in the workbook; they fill details but are never created.

Curated values only fill blank fields, so anything an organiser has edited in the admin is
kept. New entries reach existing databases through a data migration (see 0007).
"""

import json
import logging
from decimal import Decimal
from functools import cache
from pathlib import Path

logger = logging.getLogger(__name__)

DETAILS_PATH = Path(__file__).parent / "data" / "region_details.json"
TEXT_FIELDS = ("summary", "climate", "soils", "typical_varietals", "blends")
COORDINATE_PLACES = Decimal("0.00001")


class RegionDetailsError(ValueError):
    """The curated details file is malformed."""


def _validated_entry(entry) -> dict:
    if not isinstance(entry, dict):
        raise RegionDetailsError(f"Region entry is not an object: {entry!r}")
    missing = {"name", "country", "lat", "lng", *TEXT_FIELDS} - entry.keys()
    if missing:
        raise RegionDetailsError(f"{entry.get('name')!r} is missing {sorted(missing)}")
    if not (-90 <= entry["lat"] <= 90 and -180 <= entry["lng"] <= 180):
        raise RegionDetailsError(f"{entry['name']!r} has coordinates out of range")
    return entry


def _check_variants(details: dict[tuple[str, str], dict]) -> None:
    for (country, name), entry in details.items():
        target = entry.get("variant_of")
        if target is not None and (country, target) not in details:
            raise RegionDetailsError(f"{name!r} is a variant of unknown region {target!r}")


@cache
def load_region_details() -> dict[tuple[str, str], dict]:
    """Curated details keyed by ``(country, region)`` name."""
    entries = json.loads(DETAILS_PATH.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise RegionDetailsError("Region details file must hold a list")
    details = {}
    for entry in map(_validated_entry, entries):
        key = (entry["country"], entry["name"])
        if key in details:
            raise RegionDetailsError(f"{entry['name']!r} appears twice for {entry['country']}")
        details[key] = entry
    _check_variants(details)
    return details


def _blank_fields_filled(region, entry) -> list[str]:
    """Copy curated values into the region's blank fields; return the fields changed."""
    changed = []
    if region.latitude is None or region.longitude is None:
        region.latitude = Decimal(str(entry["lat"])).quantize(COORDINATE_PLACES)
        region.longitude = Decimal(str(entry["lng"])).quantize(COORDINATE_PLACES)
        changed += ["latitude", "longitude"]
    for field in TEXT_FIELDS:
        if not getattr(region, field) and entry[field]:
            setattr(region, field, entry[field])
            changed.append(field)
    return changed


def create_curated_regions(region_model, country_model) -> int:
    """Create every curated region (and its country) not yet in the database.

    Existing regions are left alone; ``fill_region_details`` fills their blank fields.
    Takes the model classes so data migrations can pass their historical models.
    """
    created = 0
    for (country_name, name), entry in load_region_details().items():
        if entry.get("variant_of"):
            continue
        country, _ = country_model.objects.get_or_create(name=country_name)
        region, was_created = region_model.objects.get_or_create(name=name, country=country)
        if was_created:
            region.save(update_fields=_blank_fields_filled(region, entry))
            created += 1
    if created:
        logger.info("Created %d curated regions", created)
    return created


def fill_region_details(region_model) -> int:
    """Fill blank details on every known region; returns how many regions changed.

    Takes the model class so data migrations can pass their historical model.
    """
    details = load_region_details()
    updated = 0
    for region in region_model.objects.select_related("country"):
        entry = details.get((region.country.name, region.name))
        if entry is None:
            continue
        changed = _blank_fields_filled(region, entry)
        if changed:
            region.save(update_fields=changed)
            updated += 1
    if updated:
        logger.info("Filled curated details for %d regions", updated)
    return updated
