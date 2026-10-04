from django.db import migrations

ORGANISER_MODELS = [
    "member", "era", "session", "attendance", "country", "region",
    "varietal", "wine", "winevarietal", "tasting", "rating",
]


def forwards(apps, schema_editor):
    from django.contrib.auth.management import create_permissions

    from club.naming import VARIETALS

    # Permissions are normally created post-migrate; make sure they exist now.
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    group, _ = Group.objects.get_or_create(name="Organiser")
    group.permissions.set(
        Permission.objects.filter(
            content_type__app_label="club", content_type__model__in=ORGANISER_MODELS
        )
    )

    Varietal = apps.get_model("club", "Varietal")
    for name, aliases in VARIETALS.items():
        Varietal.objects.get_or_create(name=name, defaults={"aliases": ", ".join(aliases)})


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("club", "0001_initial"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
