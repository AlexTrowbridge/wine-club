"""The wine-region map, and each region's details (climate, soils, grapes, club figures)."""

from django.shortcuts import get_object_or_404, render

from . import stats
from .models import Region, Tasting, Wine

TOP_WINES_PER_REGION = 5


def _map_markers(regions, tastings, means):
    """JSON-ready marker data for every located region, tasted or not."""
    return [
        {
            "name": region.name,
            "country": region.country.name,
            "lat": float(region.latitude),
            "lng": float(region.longitude),
            "tasted": region.pk in tastings,
            "bottles": tastings.get(region.pk, 0),
            "mean": round(means[region.pk], 2) if region.pk in means else None,
            "url": region.get_absolute_url(),
        }
        for region in regions
        if region.has_location
    ]


def region_map(request):
    tastings = stats.tastings_per_region()
    regions = list(Region.objects.select_related("country"))
    tasted = [region for region in regions if region.pk in tastings]
    markers = _map_markers(regions, tastings, stats.region_means(stats.bottles()))
    return render(
        request,
        "club/region_map.html",
        {
            "markers": markers,
            "unlocated": [region for region in tasted if not region.has_location],
            "n_regions": len(tasted),
            "n_countries": len({region.country_id for region in tasted}),
            "n_untasted": sum(not marker["tasted"] for marker in markers),
        },
    )


def region_detail(request, pk):
    region = get_object_or_404(Region.objects.select_related("country"), pk=pk)
    tastings = Tasting.objects.filter(wine__region=region)
    data = stats.bottles(tastings)
    context = {
        "region": region,
        "n_bottles": tastings.visible().count(),
        "mean": stats.region_means(data).get(region.pk),
        "varietals": stats.varietal_counts(data),
        "top_wines": stats.top_wines(data, n=TOP_WINES_PER_REGION),
        "country_has_wines": Wine.objects.filter(region__country=region.country).exists(),
    }
    # Clicking a map marker loads just the panel; a direct visit gets the full page.
    template = "club/_region_panel.html" if request.headers.get("HX-Request") else None
    return render(request, template or "club/region_detail.html", context)
