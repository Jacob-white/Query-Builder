"""The network-egress check must see an address in EVERY shape a connector accepts.

A scan of all 138 connectors found 26 of 37 address formats (libpq ``host=... port=...``, JDBC,
Oracle ``//host`` and TNS, comma host lists, ``host:port`` / URLs inside ``host``, and the
driver-specific keys ``hosts``, ``servers``, ``connstr``, ``gateway_url``, ``supabase_url``, ...)
let the cloud-metadata address through under the default policy.
"""

from __future__ import annotations

from typing import Any

import pytest

from query_builder.config import NetworkSecurityConfig, SecurityConfig
from query_builder.connectors.base import SecurityError
from query_builder.connectors.registry import ConnectorRegistry
from query_builder.security import (
    collect_target_config,
    extract_address_targets,
    validate_network_target,
)

# Resolved at import time: other tests clear the global registry, which would make a lookup
# at test time depend on test order.
_CONNECTOR_CLASSES = {
    name: ConnectorRegistry._registry[name]
    for name in (
        "apache_flink",
        "async_apache_flink",
        "couchbase",
        "crate",
        "async_crate",
        "aql",
        "supabase",
        "influx",
        "redis",
    )
}

META = "169.254.169.254"
LOOSE = NetworkSecurityConfig(allow_private_networks=True, enforce_tls=False)

HOSTILE: dict[str, dict[str, Any]] = {
    "host with port": {"host": f"{META}:8080"},
    "host holding a url": {"host": f"http://{META}/x"},
    "comma host list": {"host": f"example.com,{META}"},
    "comma host list with ports": {"host": f"example.com:5432,{META}:5432"},
    "libpq conninfo": {"dsn": f"host={META} port=5432 dbname=x"},
    "libpq hostaddr": {"dsn": f"hostaddr={META} port=5432"},
    "libpq multi host": {"dsn": f"host=example.com,{META} port=5432"},
    "odbc server tcp": {"connection_string": f"Server=tcp:{META},1433;Database=d"},
    "odbc data source": {"connection_string": f"Data Source={META};Initial Catalog=d"},
    "db2 dsn": {"dsn": f"DATABASE=x;HOSTNAME={META};PORT=50000;"},
    "jdbc postgres": {"url": f"jdbc:postgresql://{META}:5432/db"},
    "jdbc sqlserver": {"url": f"jdbc:sqlserver://{META}:1433;databaseName=x"},
    "oracle easy connect": {"dsn": f"//{META}:1521/svc"},
    "oracle tns": {
        "dsn": f"(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST={META})(PORT=1521)))"
    },
    "userinfo scheme-less": {"dsn": f"user:pw@{META}:5432/db"},
    "mongo replica set": {"url": f"mongodb://example.com:27017,{META}:27017/db"},
    "contact point as url": {"contact_points": [f"http://{META}"]},
    "hosts list": {"hosts": [META]},
    "servers list": {"servers": [f"{META}:4200"]},
    "nodes list": {"nodes": [f"http://{META}:9200"]},
    "bootstrap servers": {"bootstrap_servers": f"{META}:9092"},
    "connstr": {"connstr": f"couchbase://{META}"},
    "gateway url": {"gateway_url": f"http://{META}:8083"},
    "base url": {"base_url": f"http://{META}:9090"},
    "endpoint url": {"endpoint_url": f"https://{META}"},
    "supabase url": {"supabase_url": f"https://{META}"},
    "jdbc url key": {"jdbc_url": f"jdbc:postgresql://{META}/db"},
    "conninfo key": {"conninfo": f"host={META} dbname=x"},
}


@pytest.mark.parametrize("config", HOSTILE.values(), ids=HOSTILE.keys())
def test_cloud_metadata_address_is_blocked_in_every_format(
    config: dict[str, Any],
) -> None:
    with pytest.raises(SecurityError):
        validate_network_target(config=config, network_config=LOOSE)


LEGIT: dict[str, dict[str, Any]] = {
    "localhost": {"host": "localhost"},
    "host with port": {"host": "127.0.0.1:5432"},
    "ipv6 loopback": {"host": "::1"},
    "bracketed ipv6 url": {"url": "http://[::1]:8080/"},
    "unix socket": {"host": "/var/run/postgresql"},
    "libpq socket": {"dsn": "host=/var/run/postgresql dbname=x"},
    "sqlite url": {"url": "sqlite:///tmp/x.db"},
    "jdbc h2 memory": {"url": "jdbc:h2:mem:test"},
    "jdbc derby path": {"url": "jdbc:derby:/tmp/db;create=true"},
    "file path": {"url": "/data/x.duckdb"},
    "windows path": {"dsn": "C:\\data\\x.db"},
    "odbc dsn name": {"dsn": "MyDsn"},
    "private ip": {"host": "10.1.2.3"},
    "host list": {"hosts": ["10.0.0.1:9200", "localhost:9200"]},
    "mongo replica set": {"url": "mongodb://localhost:27017,127.0.0.1:27018/db"},
    "oracle tns": {"dsn": "(DESCRIPTION=(ADDRESS=(HOST=127.0.0.1)(PORT=1521)))"},
    "db2 dsn": {"dsn": "DATABASE=x;HOSTNAME=127.0.0.1;PORT=50000;"},
    "libpq": {"dsn": "host=localhost port=5432 dbname=x user=u password=p"},
    "empty values": {"host": "", "url": None, "hosts": []},
    "identifiers that are not addresses": {"region": "us-east-1", "account": "abc"},
    "port": {"host": "localhost", "port": 5432},
}


@pytest.mark.parametrize("config", LEGIT.values(), ids=LEGIT.keys())
def test_legitimate_addresses_are_still_allowed(config: dict[str, Any]) -> None:
    validate_network_target(config=config, network_config=LOOSE)


def test_extract_address_targets_understands_each_shape() -> None:
    assert extract_address_targets("a:1,b:2") == [("a", 1), ("b", 2)]
    assert extract_address_targets("jdbc:mysql://h:3306/db") == [("h", 3306)]
    assert extract_address_targets("host=h1,h2 port=5,6") == [("h1", 5), ("h2", 5)]
    assert extract_address_targets("user:pw@h:5432/db") == [("h", 5432)]
    assert extract_address_targets("[::1]:80") == [("::1", 80)]
    assert extract_address_targets("/var/run/x.sock") == []
    assert extract_address_targets("") == []


def test_multi_host_url_still_enforces_the_tls_scheme_rule() -> None:
    strict = NetworkSecurityConfig(allow_private_networks=True, enforce_tls=True)
    with pytest.raises(SecurityError, match="insecure scheme"):
        validate_network_target(
            config={"base_url": "http://localhost:1,127.0.0.1:2/x"},
            network_config=strict,
        )
    validate_network_target(
        config={"base_url": "https://localhost:1,127.0.0.1:2/x"}, network_config=strict
    )


def test_connector_attributes_outside_config_are_collected() -> None:
    """Flink keeps its address in ``self.gateway_url``, Supabase in ``self.supabase_url``;
    neither is in ``self.config``, so the egress check never saw them."""

    class _Owner:
        def __init__(self) -> None:
            self.config: dict[str, Any] = {"timeout": 5}
            self.gateway_url = f"http://{META}:8083"
            self.supabase_url = f"https://{META}"
            self.region_name = "us-east-1"
            self._private_url = "ignored"
            self.port = 8083

    target = collect_target_config(_Owner())
    assert target["gateway_url"].endswith(":8083") and "supabase_url" in target
    assert "region_name" not in target and "_private_url" not in target
    assert target["port"] == 8083


@pytest.mark.parametrize(
    ("connector", "kwargs"),
    [
        ("apache_flink", {"gateway_url": f"http://{META}:8083"}),
        ("async_apache_flink", {"gateway_url": f"http://{META}:8083"}),
        ("couchbase", {"connstr": f"couchbase://{META}"}),
        ("crate", {"servers": [f"{META}:4200"]}),
        ("async_crate", {"servers": [f"{META}:4200"]}),
        ("aql", {"hosts": [f"http://{META}:8529"]}),
        ("supabase", {"supabase_url": f"https://{META}"}),
        ("influx", {"host": f"http://{META}:8086"}),
        ("redis", {"host": f"{META}:6379"}),
    ],
)
def test_connectors_with_unusual_address_arguments_are_checked(
    connector: str, kwargs: dict[str, Any]
) -> None:
    """Each of these ignored its address in the egress check before the scan."""
    conn = _CONNECTOR_CLASSES[connector](**kwargs)
    sec = SecurityConfig()  # explicit: independent of any global security config
    sec.network = LOOSE
    with pytest.raises(SecurityError):
        conn._validate_network_target(sec)
