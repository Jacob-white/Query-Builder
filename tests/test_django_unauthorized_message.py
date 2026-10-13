"""A 401 must carry our own wording, never the text of an OS PermissionError (it can hold a path)."""

from __future__ import annotations

import pytest

import query_builder.integrations.django as django_integration

# Other tests reload the module, so look the names up at run time, not import time.
LEAK = "[Errno 13] Permission denied: '/srv/secret/app.db'"


def test_deliberate_tenant_error_keeps_its_message():
    exc = django_integration.TenantResolutionError(
        "Unauthorized: TenantContext could not be resolved from request."
    )
    assert django_integration._unauthorized_message(exc) == str(exc)


def test_os_permission_error_text_never_reaches_the_client():
    out = django_integration._unauthorized_message(PermissionError(LEAK))
    assert out == "Unauthorized."
    assert "/srv" not in out and "Errno" not in out


def test_control_str_of_os_error_does_leak():
    # Control: this is what the views returned before the change.
    assert "/srv/secret/app.db" in str(PermissionError(LEAK))


def test_tenant_error_is_a_permission_error():
    assert issubclass(django_integration.TenantResolutionError, PermissionError)


@pytest.mark.parametrize("bad", [None, 5, object()])
def test_resolver_raises_the_dedicated_type(bad):
    with pytest.raises(django_integration.TenantResolutionError):
        django_integration._resolve_tenant_sync(object(), lambda r: bad)
