"""The Django streaming download takes its headers from the fixed export tables, never from the request."""

from __future__ import annotations

import django
import pytest
from django.conf import settings

if not settings.configured:
    settings.configure(
        SECRET_KEY="test-secret-key-query-builder", ROOT_URLCONF=__name__
    )
    django.setup()

from query_builder.export import EXTENSIONS, MIME_TYPES  # noqa: E402
from query_builder.integrations.django import _stream_download  # noqa: E402


@pytest.mark.parametrize("fmt", sorted(MIME_TYPES))
def test_known_format_uses_the_table_values(fmt):
    resp = _stream_download(iter([b"x"]), fmt)
    assert resp["Content-Type"] == MIME_TYPES[fmt]
    assert (
        resp["Content-Disposition"]
        == f'attachment; filename="export.{EXTENSIONS[fmt]}"'
    )
    assert resp["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize(
    "fmt",
    [
        'csv"; filename="x.html',
        "text/html",
        "<script>alert(1)</script>",
        "CSV\r\nSet-Cookie: a=b",
        7,
        None,
    ],
)
def test_adversarial_format_never_reaches_a_header(fmt):
    resp = _stream_download(iter([b"x"]), fmt)
    assert resp["Content-Type"] == "application/octet-stream"
    assert resp["Content-Disposition"] == 'attachment; filename="export.bin"'
    assert "script" not in resp["Content-Disposition"]
    assert not resp.has_header("Set-Cookie")


def test_format_is_matched_case_insensitively_with_padding():
    resp = _stream_download(iter([b"x"]), "  CSV ")
    assert resp["Content-Type"] == MIME_TYPES["csv"]
