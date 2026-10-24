"""
Pytest global configuration and fixtures.
Configures Django settings early so Django/Ninja/DRF can be cleanly imported across all tests.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import socketserver
from typing import Any

# Speed up HTTPServer / ThreadingHTTPServer shutdown in tests (default 0.5s -> 0.01s)
_orig_serve_forever = socketserver.BaseServer.serve_forever


def _fast_serve_forever(
    self: socketserver.BaseServer, poll_interval: float = 0.01
) -> None:
    return _orig_serve_forever(self, poll_interval=poll_interval)


socketserver.BaseServer.serve_forever = _fast_serve_forever  # type: ignore[method-assign]

# Avoid slow external DNS / Windows NetBIOS broadcast timeouts on fake hostnames during unit tests
_orig_getaddrinfo = socket.getaddrinfo


def _fast_test_getaddrinfo(
    host: Any,
    port: Any,
    family: int = 0,
    type: int = 0,
    proto: int = 0,
    flags: int = 0,
) -> Any:
    if isinstance(host, str) and not os.environ.get("QB_IT_ENGINES"):
        h = host.strip().lower().strip("[]")
        if h not in (
            "localhost",
            "localhost.localdomain",
            "127.0.0.1",
            "::1",
            "0.0.0.0",
            "",
        ):
            try:
                ipaddress.ip_address(h)
            except ValueError as err:
                raise socket.gaierror(
                    socket.EAI_NONAME, f"Offline unit test mode: {host}"
                ) from err
    return _orig_getaddrinfo(host, port, family, type, proto, flags)


socket.getaddrinfo = _fast_test_getaddrinfo  # type: ignore[assignment]

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
