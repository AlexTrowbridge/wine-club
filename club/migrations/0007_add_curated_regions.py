from django.db import migrations

from club.region_details import create_curated_regions, fill_region_details


def add_regions(apps, schema_editor):
    """Established regions the club hasn't tasted from yet join the map, with their details."""
    region = apps.get_model("club", "Region")
    create_curated_regions(region, apps.get_model("club", "Country"))
    fill_region_details(region)


class Migration(migrations.Migration):
    dependencies = [
        ("club", "0006_fill_region_details"),
    ]

    operations = [
        migrations.RunPython(add_regions, migrations.RunPython.noop),
    ]
