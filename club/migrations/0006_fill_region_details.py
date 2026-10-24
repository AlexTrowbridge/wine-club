from django.db import migrations

from club.region_details import fill_region_details


def fill_details(apps, schema_editor):
    """Regions already in the database get the curated map location and details."""
    fill_region_details(apps.get_model("club", "Region"))


class Migration(migrations.Migration):
    dependencies = [
        ("club", "0005_region_details"),
    ]

    operations = [
        migrations.RunPython(fill_details, migrations.RunPython.noop),
    ]
