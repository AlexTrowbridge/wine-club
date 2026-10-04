from django.contrib.auth.models import User
from django.core.management import call_command


def test_creates_admin_from_env_password(db, settings):
    settings.ADMIN_USERNAME, settings.ADMIN_PASSWORD = "admin", "s3cret-pass"
    call_command("ensure_admin")
    admin = User.objects.get(username="admin")
    assert admin.is_superuser and admin.is_staff
    assert admin.check_password("s3cret-pass")


def test_leaves_existing_admin_password_alone(db, settings):
    User.objects.create_superuser("admin", password="changed-later")
    settings.ADMIN_USERNAME, settings.ADMIN_PASSWORD = "admin", "s3cret-pass"
    call_command("ensure_admin")
    assert User.objects.get(username="admin").check_password("changed-later")


def test_skips_without_password(db, settings):
    settings.ADMIN_PASSWORD = ""
    call_command("ensure_admin")
    assert not User.objects.exists()
