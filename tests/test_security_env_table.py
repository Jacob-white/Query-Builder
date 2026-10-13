"""SECURITY.md must name exactly the environment variables the code reads.

A documented variable the code ignores is a silent no-op (``QB_ALLOWED_HOSTS`` was documented
while the code reads ``QB_ALLOWED_HOSTNAMES``): an operator believes a restriction is in place and
none is. The table is generated from ``config.py`` and this test keeps it that way.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SECURITY = ROOT / "SECURITY.md"

# Names earlier versions of SECURITY.md listed although the code never read them. They may be
# mentioned ONLY to tell the reader they do nothing.
RETIRED = {
    "QB_ALLOWED_HOSTS",
    "QB_BLOCKED_HOSTS",
    "QB_MAX_AST_COMPLEXITY",
    "QB_MASK_SENSITIVE_COLUMNS",
    "QB_ENABLE_AUDIT_LOG",
}


@pytest.fixture(scope="module")
def gen():  # type: ignore[no-untyped-def]
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import gen_security_env_table as module
    finally:
        sys.path.pop(0)
    return module


def test_the_generated_table_is_current() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/gen_security_env_table.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_variable_the_code_reads_is_documented_and_nothing_else(gen) -> None:  # type: ignore[no-untyped-def]
    read = set(gen.variables_read_by_the_code())
    text = SECURITY.read_text(encoding="utf-8")
    table = text[text.index(gen.BEGIN) : text.index(gen.END)]
    documented = set(re.findall(r"^\| `(QB_[A-Z_]+)`", table, flags=re.MULTILINE))
    documented.discard(
        "QB_SECURITY_PROFILE"
    )  # read by the loader, not mapped to one field
    assert documented == read
    assert (
        len(read) >= 30
    )  # the extraction found the loader's variables, not an empty set


def test_security_md_mentions_no_unread_variable_except_the_retired_names(gen) -> None:  # type: ignore[no-untyped-def]
    read = set(gen.variables_read_by_the_code()) | {"QB_SECURITY_PROFILE"}
    mentioned = set(
        re.findall(r"\bQB_[A-Z][A-Z_]*\b", SECURITY.read_text(encoding="utf-8"))
    )
    stray = mentioned - read - RETIRED
    assert not stray, (
        f"SECURITY.md names variables the code does not read: {sorted(stray)}"
    )


def test_retired_names_really_are_not_read_by_the_code(gen) -> None:  # type: ignore[no-untyped-def]
    assert not RETIRED & set(gen.variables_read_by_the_code())


def test_a_retired_name_has_no_effect_on_the_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hazard itself: the variable is accepted silently and nothing changes."""
    from query_builder.config import load_security_config_from_env

    base = load_security_config_from_env({"QB_SECURITY_PROFILE": "production"})
    with_retired = load_security_config_from_env(
        {"QB_SECURITY_PROFILE": "production", "QB_ALLOWED_HOSTS": "db.internal"}
    )
    assert (
        with_retired.network.allowed_hostnames == base.network.allowed_hostnames == []
    )
    real = load_security_config_from_env(
        {"QB_SECURITY_PROFILE": "production", "QB_ALLOWED_HOSTNAMES": "db.internal"}
    )
    assert real.network.allowed_hostnames == ["db.internal"]
