"""A disabled-feature refusal must reach a client as text built from the engine's own feature
names, never from the exception's string (CodeQL ``py/stack-trace-exposure``).

``DisabledFeatureError`` is raised in exactly one place with a fixed template, so today the text is
safe. This keeps it structurally safe: ``disabled_feature_message`` accepts a feature name only
when it is one the engine defines, so a future raise site that passes dynamic text (or a custom
``message``) cannot put it in front of a client. Each test POISONS the exception with recognisable
leak text and checks it never appears; each integration is also checked to give the SAME wording
as before for a genuinely disabled feature.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import fields
from pathlib import Path
from typing import Any
from unittest.mock import patch

import django
import pytest
from django.conf import settings

if not settings.configured:
    settings.configure(
        SECRET_KEY="test-secret-key-query-builder",
        ROOT_URLCONF=__name__,
        DATABASES={
            "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
        },
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "rest_framework",
        ],
    )
    django.setup()

from fastapi import FastAPI
from fastapi.testclient import TestClient

from query_builder.capabilities import (
    _KNOWN_FEATURES,
    DisabledFeatureError,
    EngineCapabilities,
    FeatureTier,
    disabled_feature_message,
)
from query_builder.connectors.sqlite import SQLiteConnector
from query_builder.exceptions import SecurityError
from query_builder.integrations.django import create_django_urls, create_drf_views
from query_builder.integrations.fastapi import create_query_builder_router

LEAK = "LEAK /var/lib/secret/db.sock Traceback (most recent call last)"
GENERIC = "A feature used by this query is disabled in the active engine capabilities."
CTE_SPEC = {
    "table": "users",
    "ctes": [{"name": "c", "query": {"table": "users", "columns": ["id"]}}],
    "columns": ["id"],
}


def poisoned(feature: str = "ctes") -> DisabledFeatureError:
    return DisabledFeatureError(feature, message=LEAK)


# ------------------------------------------------------------------------------ the helper
@pytest.mark.parametrize("name", _KNOWN_FEATURES)
def test_a_known_feature_gives_exactly_the_wording_clients_already_saw(
    name: str,
) -> None:
    exc = DisabledFeatureError(name)
    assert disabled_feature_message(exc) == str(exc)


def test_the_known_features_are_the_engines_own_flags() -> None:
    expected = tuple(
        f.name for f in fields(EngineCapabilities) if f.name != "custom_overrides"
    )
    assert _KNOWN_FEATURES == expected and "ctes" in _KNOWN_FEATURES


@pytest.mark.parametrize(
    "name",
    [
        "x'; DROP TABLE users; --",
        "../../etc/passwd",
        'Traceback (most recent call last):\n  File "/srv/app.py", line 3',
        "ctes\nINJECTED",
        "CTES",
        " ctes",
        "ctes ",
        "x" * 10_000,
        "",
        "‮gnirts",
    ],
)
def test_a_name_the_engine_does_not_define_never_reaches_the_message(name: str) -> None:
    message = disabled_feature_message(DisabledFeatureError(name))
    assert message == GENERIC
    assert name.strip() not in message or name.strip() == ""


def test_a_custom_exception_message_is_never_used() -> None:
    assert LEAK not in disabled_feature_message(poisoned("ctes"))
    assert LEAK not in disabled_feature_message(poisoned("not-a-feature"))


def test_the_integrators_own_override_names_are_allowed_only_when_active() -> None:
    caps = EngineCapabilities(custom_overrides={"my_feature": FeatureTier.DISABLED})
    exc = DisabledFeatureError("my_feature")
    assert "my_feature" in disabled_feature_message(exc, caps)
    assert disabled_feature_message(exc) == GENERIC  # not announced without them
    assert disabled_feature_message(exc, EngineCapabilities()) == GENERIC


# ----------------------------------------------------------------------------------- FastAPI
class _Conn:
    dialect_name = "sqlite"

    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise self.error or AssertionError("unexpected")

    def execute_raw(self, *args: Any, **kwargs: Any) -> Any:
        raise self.error or AssertionError("unexpected")

    def introspect_schema(self, *args: Any, **kwargs: Any) -> Any:
        return {"tables": {}}


def _fastapi(
    connector: Any, capabilities: EngineCapabilities | None = None
) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_query_builder_router(connector=connector, capabilities=capabilities)
    )
    return TestClient(app, raise_server_exceptions=False)


def test_fastapi_compile_does_not_echo_a_poisoned_disabled_feature_error() -> None:
    client = _fastapi(_Conn())
    with patch(
        "query_builder.integrations.fastapi.QueryCompiler.compile",
        side_effect=poisoned(),
    ):
        resp = client.post(
            "/compile", json={"spec": {"table": "users", "columns": ["id"]}}
        )
    assert resp.status_code == 403
    assert LEAK not in resp.text and "ctes" in resp.json()["detail"]


def test_fastapi_execute_does_not_echo_a_poisoned_disabled_feature_error() -> None:
    client = _fastapi(_Conn(poisoned()))
    resp = client.post("/execute", json={"spec": {"table": "users", "columns": ["id"]}})
    assert resp.status_code == 403 and LEAK not in resp.text


def test_fastapi_a_genuinely_disabled_feature_keeps_its_wording() -> None:
    client = _fastapi(_Conn(), EngineCapabilities.simple_only())
    resp = client.post("/compile", json={"spec": CTE_SPEC})
    assert resp.status_code == 403
    assert resp.json()["detail"] == str(DisabledFeatureError("ctes"))


def test_fastapi_security_errors_still_explain_why() -> None:
    client = _fastapi(_Conn(SecurityError("table 'secrets' is restricted")))
    resp = client.post(
        "/execute", json={"spec": {"table": "secrets", "columns": ["id"]}}
    )
    assert resp.status_code == 403 and "restricted" in resp.text


# ------------------------------------------------------------------------------------ Django
@pytest.fixture
def sqlite_conn(tmp_path: Path) -> SQLiteConnector:
    db = tmp_path / "users.db"
    raw = sqlite3.connect(str(db))
    raw.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, tenant_id TEXT, name TEXT)"
    )
    raw.execute("INSERT INTO users VALUES (1, 't1', 'Alice')")
    raw.commit()
    raw.close()
    return SQLiteConnector(database=str(db))


def _post(path: str, payload: dict[str, Any]) -> Any:
    from django.test import RequestFactory

    return RequestFactory().post(
        path, data=json.dumps(payload), content_type="application/json"
    )


def _views(conn: SQLiteConnector, **kwargs: Any) -> dict[str, Any]:
    urls = create_django_urls(
        conn, security={"enforce_tenant_isolation": False}, **kwargs
    )
    return {u.name: u.callback for u in urls}


SPEC = {"table": "users", "columns": ["id"]}


def test_django_compile_does_not_echo_a_poisoned_disabled_feature_error(
    sqlite_conn,
) -> None:  # type: ignore[no-untyped-def]
    views = _views(sqlite_conn)
    with patch(
        "query_builder.integrations.django.QueryCompiler.compile",
        side_effect=poisoned(),
    ):
        resp = views["query-builder-compile"](_post("/compile/", {"spec": SPEC}))
    body = resp.content.decode()
    assert resp.status_code == 403 and LEAK not in body and "ctes" in body


@pytest.mark.parametrize("name", ["query-builder-execute", "query-builder-export"])
def test_django_execute_and_export_do_not_echo_a_poisoned_error(
    sqlite_conn, name: str
) -> None:  # type: ignore[no-untyped-def]
    views = _views(sqlite_conn)
    with patch.object(sqlite_conn, "execute", side_effect=poisoned()):
        resp = views[name](_post("/x/", {"spec": SPEC}))
    assert resp.status_code == 403 and LEAK not in resp.content.decode()


def test_django_a_genuinely_disabled_feature_keeps_its_wording(sqlite_conn) -> None:  # type: ignore[no-untyped-def]
    views = _views(sqlite_conn, capabilities=EngineCapabilities.simple_only())
    resp = views["query-builder-compile"](_post("/compile/", {"spec": CTE_SPEC}))
    assert resp.status_code == 403
    assert json.loads(resp.content)["error"] == str(DisabledFeatureError("ctes"))


def test_django_security_errors_still_explain_why(sqlite_conn) -> None:  # type: ignore[no-untyped-def]
    views = _views(sqlite_conn)
    with patch.object(
        sqlite_conn, "execute", side_effect=SecurityError("table restricted")
    ):
        resp = views["query-builder-execute"](_post("/execute/", {"spec": SPEC}))
    assert resp.status_code == 403 and "table restricted" in resp.content.decode()


# ------------------------------------------------------------------------------- Django REST
def _drf_post(view: Any, payload: dict[str, Any]) -> Any:
    from rest_framework.test import APIRequestFactory

    return view(APIRequestFactory().post("/", payload, format="json"))


def test_drf_compile_does_not_echo_a_poisoned_disabled_feature_error(
    sqlite_conn,
) -> None:  # type: ignore[no-untyped-def]
    views = create_drf_views(sqlite_conn, security={"enforce_tenant_isolation": False})
    with patch(
        "query_builder.integrations.django.QueryCompiler.compile",
        side_effect=poisoned(),
    ):
        resp = _drf_post(views["CompileView"].as_view(), {"spec": SPEC})
    assert resp.status_code == 403
    assert LEAK not in json.dumps(resp.data, default=str)


def test_drf_a_genuinely_disabled_feature_keeps_its_wording(sqlite_conn) -> None:  # type: ignore[no-untyped-def]
    views = create_drf_views(sqlite_conn, capabilities=EngineCapabilities.simple_only())
    resp = _drf_post(views["CompileView"].as_view(), {"spec": CTE_SPEC})
    assert resp.status_code == 403
    assert str(resp.data["detail"]) == str(DisabledFeatureError("ctes"))


# ------------------------------------------------------------------------------------ Ninja
def _ninja_compile_view(conn: SQLiteConnector, **kwargs: Any) -> Any:
    pytest.importorskip("ninja")
    from query_builder.integrations.django import create_ninja_router

    router = create_ninja_router(
        conn, security={"enforce_tenant_isolation": False}, **kwargs
    )
    for path, ops in router.path_operations.items():
        for op in ops.operations:
            if op.methods[0] == "POST" and path == "/compile":
                return op.view_func
    raise AssertionError("no /compile operation")


def test_ninja_compile_does_not_echo_a_poisoned_disabled_feature_error(
    sqlite_conn,
) -> None:  # type: ignore[no-untyped-def]
    from django.test import RequestFactory
    from ninja.errors import HttpError

    view = _ninja_compile_view(sqlite_conn)
    with (
        patch(
            "query_builder.integrations.django.QueryCompiler.compile",
            side_effect=poisoned(),
        ),
        pytest.raises(HttpError) as err,
    ):
        view(RequestFactory().post("/compile"), payload={"spec": SPEC})
    assert err.value.status_code == 403
    assert LEAK not in str(err.value.message) and "ctes" in str(err.value.message)


def test_ninja_a_genuinely_disabled_feature_keeps_its_wording(sqlite_conn) -> None:  # type: ignore[no-untyped-def]
    from django.test import RequestFactory
    from ninja.errors import HttpError

    view = _ninja_compile_view(
        sqlite_conn, capabilities=EngineCapabilities.simple_only()
    )
    with pytest.raises(HttpError) as err:
        view(RequestFactory().post("/compile"), payload={"spec": CTE_SPEC})
    assert err.value.status_code == 403
    assert str(err.value.message) == str(DisabledFeatureError("ctes"))
