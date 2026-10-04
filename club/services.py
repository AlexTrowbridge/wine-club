from .models import Country, Region, Varietal, Wine, WineVarietal
from .naming import parse_wine_name


def set_varietals(wine: Wine, names: list[str]):
    WineVarietal.objects.filter(wine=wine).delete()
    lookup = {v.name: v for v in Varietal.objects.filter(name__in=names)}
    WineVarietal.objects.bulk_create(
        WineVarietal(wine=wine, varietal=lookup[n], order=i)
        for i, n in enumerate(names)
        if n in lookup
    )


def get_region(region_name: str, country_name: str) -> Region | None:
    region_name, country_name = region_name.strip(), country_name.strip()
    if not (region_name and country_name):
        return None
    country, _ = Country.objects.get_or_create(name=country_name)
    region, _ = Region.objects.get_or_create(name=region_name, country=country)
    return region


def get_or_create_wine(full_name: str, region: Region | None = None) -> tuple[Wine, bool]:
    """Find a wine by its spreadsheet-style name, or create it by parsing the name."""
    full_name = " ".join(full_name.split())
    wine = Wine.objects.filter(full_name__iexact=full_name).first()
    if wine:
        if region and not wine.region:
            wine.region = region
            wine.save(update_fields=["region"])
        return wine, False
    parsed = parse_wine_name(full_name)
    wine = Wine.objects.create(
        full_name=full_name,
        producer=parsed.producer,
        vintage=parsed.vintage,
        cuvee=parsed.cuvee,
        style=parsed.style,
        region=region,
    )
    set_varietals(wine, parsed.varietals)
    return wine, True
