"""
Pytest global configuration and fixtures.
Configures Django settings early so Django/Ninja/DRF can be cleanly imported across all tests.
"""

from __future__ import annotations

# Configure settings directly if django is installed

try:
    import django
    from django.conf import settings

    if not settings.configured:
        settings.configure(
            SECRET_KEY="test-secret-key-query-builder",
            ROOT_URLCONF="tests.test_django_full_coverage",
            DATABASES={
                "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
            },
            INSTALLED_APPS=[
                "django.contrib.auth",
                "django.contrib.contenttypes",
                "rest_framework",
            ],
            REST_FRAMEWORK={},
        )
        django.setup()
except Exception:  # noqa: BLE001, S110
    pass
