from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import IntegrityError


class Command(BaseCommand):
    help = (
        "Create the default superuser ADMIN_USERNAME with password ADMIN_PASSWORD if it "
        "doesn't exist yet. An existing user is left alone, so password changes stick."
    )

    def handle(self, **options):
        username, password = settings.ADMIN_USERNAME, settings.ADMIN_PASSWORD
        if not password:
            self.stdout.write("ADMIN_PASSWORD not set; skipping default admin user.")
            return
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            self.stdout.write(f"Admin user {username!r} already exists.")
            return
        try:
            User.objects.create_superuser(username, password=password)
        except IntegrityError:
            # Another replica's init container created it first.
            self.stdout.write(f"Admin user {username!r} already exists.")
            return
        self.stdout.write(self.style.SUCCESS(f"Created admin user {username!r}."))
