"""
Env-gated checks for managed cloud engines. They run only when the engine's
``QB_IT_<ENGINE>_*`` variables are set (see ``cloud.py`` / docs/TESTING_LIVE.md)
and are otherwise skipped with the variable names to set. Never run in CI by
default: nothing here can start a cloud service.
"""

from __future__ import annotations

import importlib
import traceback
from typing import Any

import pytest

from query_builder.connectors.registry import get_connector
from query_builder.security import SecurityError
from tests.integration.cloud import CLOUD, CloudEngine
from tests.integration.conftest import record_version

PARAMS = [pytest.param(n, marks=pytest.mark.qb_engine(n), id=n) for n in CLOUD]
WRONG_SECRET = "Wr0ng-S3cret-Pw!x"


def _skip_or_engine(name: str) -> CloudEngine:
    cloud = CLOUD[name]
    missing = cloud.missing()
    if missing:
        pytest.skip(
            f"{name}: set {', '.join(missing)} to run this test"
            + (f" ({cloud.note})" if cloud.note else "")
        )
    for module in cloud.drivers:
        try:
            importlib.import_module(module)
            break
        except ImportError:
            continue
    else:
        pytest.skip(f"{name}: driver not installed (pip install {cloud.pip})")
    return cloud


@pytest.fixture
def cloud_conn(request: pytest.FixtureRequest) -> Any:
    cloud = _skip_or_engine(request.param)
    connector = get_connector(cloud.connector, **cloud.kwargs(cloud.values()))
    connector._qb_cloud_name = cloud.name
    connector.connect()
    try:
        yield connector
    finally:
        connector.close()


@pytest.mark.qb_category("connect")
@pytest.mark.parametrize("cloud_conn", PARAMS, indirect=True)
def test_cloud_connect_and_test_connection(cloud_conn: Any) -> None:
    info = cloud_conn.test_connection()
    assert info["status"] == "healthy"
    assert info.get("engine_version")
    record_version(cloud_conn._qb_cloud_name, str(info["engine_version"]))


@pytest.mark.qb_category("read_projection")
@pytest.mark.parametrize("cloud_conn", PARAMS, indirect=True)
def test_cloud_select_literal_round_trip(cloud_conn: Any) -> None:
    res = cloud_conn.execute(sql="SELECT 1 AS one")
    assert [int(next(iter(r.values()))) for r in res["rows"]] == [1]


@pytest.mark.qb_category("introspect_tables")
@pytest.mark.parametrize("cloud_conn", PARAMS, indirect=True)
def test_cloud_introspection_returns_a_snapshot(cloud_conn: Any) -> None:
    snap = cloud_conn.introspect_schema()
    assert isinstance(snap["tables"], dict)


@pytest.mark.parametrize("cloud_conn", PARAMS, indirect=True)
@pytest.mark.parametrize(
    "sql", ["DELETE FROM qbit_x", "DROP TABLE qbit_x", "INSERT INTO qbit_x VALUES (1)"]
)
@pytest.mark.qb_category("write_refused")
def test_cloud_writes_rejected(cloud_conn: Any, sql: str) -> None:
    with pytest.raises(SecurityError):
        cloud_conn.execute(sql=sql)


@pytest.mark.qb_category("secrets")
@pytest.mark.parametrize("name", PARAMS)
def test_cloud_wrong_secret_never_leaks(name: str) -> None:
    cloud = _skip_or_engine(name)
    if cloud.secret_kw is None:
        pytest.skip(f"{name}: authenticates through the vendor SDK environment")
    kwargs = cloud.kwargs(cloud.values())
    kwargs[cloud.secret_kw] = WRONG_SECRET
    bad = get_connector(cloud.connector, **kwargs)
    with pytest.raises(Exception) as err:  # noqa: PT011
        bad.connect()
        bad.test_connection()
    text = "".join(
        traceback.format_exception(type(err.value), err.value, err.value.__traceback__)
    )
    assert WRONG_SECRET not in text
    assert WRONG_SECRET not in repr(bad) + str(bad)
    bad.close()


@pytest.mark.qb_category("registry")
def test_cloud_registry_is_wired() -> None:
    for cloud in CLOUD.values():
        assert cloud.connector_class_keys()
        assert cloud.env_name("X").startswith("QB_IT_")
