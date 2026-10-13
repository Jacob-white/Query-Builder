"""Which network policy does a connector enforce? An explicit choice must win over the default.

A connector that has no policy of its own and finds no configuration applies a permissive default
(private networks allowed, TLS not enforced) so databases on your own network work out of the box.
That default used to apply even when the APPLICATION had chosen a policy:
``query-builder serve --profile production`` (which calls ``configure_query_builder``) and
``configure_security(...)`` left connectors permissive. Only the ``QB_SECURITY_PROFILE`` environment
variable and a per-connector ``security=`` were honoured.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from query_builder.config import (
    SecurityConfig,
    SecurityProfile,
    configure_query_builder,
    configure_security,
    reset_security_config,
    security_explicitly_configured,
)
from query_builder.connectors.base import effective_network_config
from query_builder.connectors.registry import ConnectorRegistry
from query_builder.exceptions import SecurityError

ENV = ("QB_SECURITY_PROFILE", "QB_ALLOW_PRIVATE_NETWORKS", "QB_ENFORCE_TLS")
POSTGRES = ConnectorRegistry._registry[
    "postgres"
]  # captured at import (tests clear the registry)


@pytest.fixture(autouse=True)
def clean_state(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    reset_security_config()
    yield
    reset_security_config()


def policy(**kwargs):  # type: ignore[no-untyped-def]
    net = effective_network_config(POSTGRES(host="db.internal", **kwargs))
    return net.allow_private_networks, net.enforce_tls


def test_nothing_configured_is_permissive() -> None:
    """The documented default (SECURITY.md 3.2): pinned so a change is deliberate."""
    assert policy() == (True, False)
    assert not security_explicitly_configured()


@pytest.mark.parametrize("profile", ["production", "strict"])
def test_configure_security_with_a_profile_is_honoured(profile: str) -> None:
    configure_security(SecurityProfile.from_name(profile))
    assert security_explicitly_configured()
    assert policy() == (False, True)


@pytest.mark.parametrize("profile", ["production", "strict"])
def test_configure_query_builder_profile_is_honoured(profile: str) -> None:
    """This is what ``query-builder serve --profile <p>`` calls."""
    configure_query_builder(profile=profile)
    assert policy() == (False, True)


def test_configure_security_keyword_overrides_are_honoured() -> None:
    configure_security(SecurityProfile.from_name("production"), profile="strict")
    assert policy() == (False, True)


def test_an_explicit_permissive_choice_stays_permissive() -> None:
    configure_security(SecurityProfile.from_name("development"))
    assert policy() == (True, False)


def test_a_connector_s_own_security_wins_over_the_global_choice() -> None:
    configure_security(SecurityProfile.from_name("production"))
    assert policy(security=SecurityProfile.from_name("development")) == (True, False)
    reset_security_config()
    assert policy(security=SecurityProfile.from_name("strict")) == (False, True)


def test_the_environment_profile_is_still_honoured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QB_SECURITY_PROFILE", "production")
    reset_security_config()
    assert policy() == (False, True)
    assert (
        not security_explicitly_configured()
    )  # came from the environment, not from code


def test_reset_restores_the_default() -> None:
    configure_security(SecurityProfile.from_name("strict"))
    reset_security_config()
    assert policy() == (True, False)
    assert not security_explicitly_configured()


def test_the_shared_helper_serves_every_connector_base() -> None:
    """Sync, async and Dremio all call ``effective_network_config``; it needs only these two."""
    owner = SimpleNamespace(_explicit_security=False)
    assert effective_network_config(owner).allow_private_networks is True
    configure_security(SecurityProfile.from_name("production"))
    assert effective_network_config(owner).allow_private_networks is False


def test_the_effect_is_visible_at_connect_time() -> None:
    """The point of it all: a private address passes by default and is refused once a profile is set."""
    conn = POSTGRES(host="10.0.0.5")
    conn._validate_network_target()  # permissive default: allowed
    configure_query_builder(profile="production")
    with pytest.raises(SecurityError, match="private"):
        POSTGRES(host="10.0.0.5")._validate_network_target()


@pytest.mark.parametrize("state", ["default", "production", "strict", "development"])
def test_the_cloud_credential_endpoint_is_refused_in_every_state(state: str) -> None:
    if state != "default":
        configure_security(SecurityProfile.from_name(state))
    with pytest.raises(SecurityError, match="metadata"):
        POSTGRES(host="169.254.169.254")._validate_network_target()


def test_security_config_objects_are_unaffected() -> None:
    assert (
        SecurityConfig().network.allow_private_networks is False
    )  # the config object itself
