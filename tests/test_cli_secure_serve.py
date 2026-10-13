"""``query-builder serve --secure`` / ``mcp``: flags, the start-up security notice, and the real path
from a ``--connections`` file to a server that isolates tenants."""

from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from query_builder.cli import _secure_server_options, main
from query_builder.pool import ConnectionPoolManager
from query_builder.server import create_server
from query_builder.server_security import ServerSecurity

ENV = ("QB_SECURITY_PROFILE", "QB_ALLOW_PRIVATE_NETWORKS", "QB_ENFORCE_TLS")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def _fake_server() -> MagicMock:
    server = MagicMock()
    server.server_address = ("127.0.0.1", 8000)
    server.serve_forever.side_effect = None
    return server


def _serve(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[MagicMock, MagicMock, Any]:
    with (
        patch(
            "query_builder.server.create_server", return_value=_fake_server()
        ) as create,
        patch("query_builder.config.configure_query_builder") as configure,
        patch(
            "query_builder.cli._secure_server_options", return_value={"security": "S"}
        ),
    ):
        assert main(["serve", *argv]) == 0
    return create, configure, capsys.readouterr()


def test_bare_serve_is_secure_by_default(capsys) -> None:  # type: ignore[no-untyped-def]
    create, configure, out = _serve([], capsys)
    configure.assert_called_once_with(profile="production")
    create.assert_called_once_with(host="127.0.0.1", port=8000, security="S")
    assert "SECURITY NOTICE" not in out.err
    assert "Secure mode: tenant from header 'X-Tenant-ID'" in out.out


def test_bare_serve_says_when_no_connection_is_registered(capsys) -> None:  # type: ignore[no-untyped-def]
    _, _, out = _serve([], capsys)
    assert "no --connections file" in out.err and "UNKNOWN_CONNECTION" in out.err


def test_insecure_serve_keeps_the_old_exact_call_and_prints_the_notice(capsys) -> None:  # type: ignore[no-untyped-def]
    # Control for the default above: the opt-out is the behaviour before 2.0, unchanged.
    create, configure, out = _serve(["--insecure"], capsys)
    create.assert_called_once_with(host="127.0.0.1", port=8000)
    configure.assert_not_called()
    assert (
        "SECURITY NOTICE (--insecure mode)" in out.err
        and "no authentication" in out.err
    )
    assert "drop --insecure" in out.err and "SECURE_DEPLOYMENT.md" in out.err
    assert "no --connections file" not in out.err


def test_secure_and_insecure_cannot_be_combined(capsys) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(SystemExit) as exc:
        main(["serve", "--secure", "--insecure"])
    assert exc.value.code == 2
    assert "not allowed with" in capsys.readouterr().err


@pytest.mark.parametrize(
    "extra", [["--connections", "c.json"], ["--allow-origin", "https://app.example"]]
)
def test_secure_only_options_are_refused_with_insecure(extra, capsys) -> None:  # type: ignore[no-untyped-def]
    with patch("query_builder.server.create_server") as create:
        assert main(["serve", "--insecure", *extra]) == 2
    create.assert_not_called()
    assert "only apply to secure mode" in capsys.readouterr().err


def test_explicit_secure_flag_still_works(capsys) -> None:  # type: ignore[no-untyped-def]
    create, _, _ = _serve(["--secure"], capsys)
    create.assert_called_once_with(host="127.0.0.1", port=8000, security="S")


def test_the_notice_can_be_silenced(capsys) -> None:  # type: ignore[no-untyped-def]
    _, _, out = _serve(["--insecure", "--no-security-notice"], capsys)
    assert "SECURITY NOTICE" not in out.err
    _, _, out = _serve(["--no-security-notice"], capsys)
    assert "no --connections file" not in out.err


def test_secure_serve_defaults_to_the_production_profile_and_passes_the_security(
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    create, configure, out = _serve(["--secure"], capsys)
    configure.assert_called_once_with(profile="production")
    create.assert_called_once_with(host="127.0.0.1", port=8000, security="S")
    assert "SECURITY NOTICE" not in out.err
    assert "Secure mode: tenant from header 'X-Tenant-ID'" in out.out


def test_an_explicit_profile_wins_in_secure_mode(capsys) -> None:  # type: ignore[no-untyped-def]
    _, configure, _ = _serve(["--secure", "--profile", "strict"], capsys)
    configure.assert_called_once_with(profile="strict")


def test_an_environment_profile_is_not_overridden_by_secure(
    capsys,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setenv("QB_SECURITY_PROFILE", "strict")
    _, configure, _ = _serve(["--secure"], capsys)
    configure.assert_not_called()


def test_mcp_prints_the_notice_to_stderr_and_nothing_to_stdout(capsys) -> None:  # type: ignore[no-untyped-def]
    with patch("query_builder.mcp_server.McpServer") as server:
        assert main(["mcp"]) == 0
    out = capsys.readouterr()
    assert "SECURITY NOTICE" in out.err and "AI agent" in out.err
    assert out.out == ""  # stdout belongs to the MCP protocol
    server.return_value.run_stdio.assert_called_once()


def test_mcp_notice_can_be_silenced_and_a_profile_applied(capsys) -> None:  # type: ignore[no-untyped-def]
    with (
        patch("query_builder.mcp_server.McpServer"),
        patch("query_builder.config.configure_query_builder") as configure,
    ):
        main(["mcp", "--no-security-notice", "--profile", "production"])
    assert "SECURITY NOTICE" not in capsys.readouterr().err
    configure.assert_called_once_with(profile="production")


# ----------------------------- the real path: connections file -> secure server -> tenants
def _args(connections: Path | None, **kw: Any) -> argparse.Namespace:
    return argparse.Namespace(
        connections=str(connections) if connections else None,
        tenant_header=kw.get("tenant_header", "X-Tenant-ID"),
        default_connection=kw.get("default_connection", "default"),
        allow_origin=kw.get("allow_origin", []),
    )


@pytest.fixture
def connections_file(tmp_path: Path) -> Path:
    db = tmp_path / "orders.db"
    con = sqlite3.connect(db)
    con.execute("create table orders (id integer, amount integer, tenant_id text)")
    con.executemany(
        "insert into orders values (?, ?, ?)",
        [(1, 10, "acme"), (2, 20, "acme"), (3, 999, "rival")],
    )
    con.commit()
    con.close()
    path = tmp_path / "connections.json"
    path.write_text(
        json.dumps(
            {"default": {"connector": "sqlite", "config": {"database": str(db)}}}
        )
    )
    return path


def test_the_options_built_by_serve_secure_isolate_tenants_end_to_end(
    connections_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = ConnectionPoolManager()
    monkeypatch.setattr(
        "query_builder.pool.get_connection_pool_manager", lambda: manager
    )
    options = _secure_server_options(_args(connections_file))
    assert manager.has_pool("default")
    assert isinstance(options["security"], ServerSecurity)

    server = create_server("127.0.0.1", 0, **options)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    spec = {"table": "orders", "columns": ["id", "amount", "tenant_id"]}

    def execute(headers: dict[str, str]) -> tuple[int, Any]:
        req = urllib.request.Request(
            base + "/api/v1/execute",
            data=json.dumps({"spec": spec}).encode(),
            headers={"Content-Type": "application/json", **headers},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    try:
        status, out = execute({"X-Tenant-ID": "acme"})
        assert status == 200 and {r["tenant_id"] for r in out["rows"]} == {"acme"}
        status, out = execute({})
        assert status == 401 and out["error"]["code"] == "TENANT_REQUIRED"
    finally:
        server.shutdown()
        server.server_close()


def test_a_custom_header_and_default_connection_are_honoured(
    connections_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = ConnectionPoolManager()
    monkeypatch.setattr(
        "query_builder.pool.get_connection_pool_manager", lambda: manager
    )
    options = _secure_server_options(
        _args(
            connections_file,
            tenant_header="X-Org",
            allow_origin=["https://app.example"],
        )
    )
    security = options["security"]
    assert security.tenant_resolver({"x-org": "acme"}) == "acme"
    assert security.tenant_resolver({"X-Tenant-ID": "acme"}) is None
    assert security.cors_origins == ("https://app.example",)


def test_a_connections_file_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("[]")
    with pytest.raises(ValueError, match="JSON object"):
        _secure_server_options(_args(bad))


def test_no_connections_file_registers_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ConnectionPoolManager()
    monkeypatch.setattr(
        "query_builder.pool.get_connection_pool_manager", lambda: manager
    )
    _secure_server_options(_args(None))
    assert not manager.has_pool("default")
