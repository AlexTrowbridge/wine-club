import os

os.environ.setdefault("SECRET_KEY", "test-only-not-secret")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite://:memory:")

from .settings import *  # noqa: E402, F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STORAGES["staticfiles"]["BACKEND"] = "django.contrib.staticfiles.storage.StaticFilesStorage"  # noqa: F405
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]  # noqa: F405
