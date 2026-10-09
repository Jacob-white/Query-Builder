"""Tests for .github/scripts/release_checks.py (the release workflow's gatekeeper)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1] / ".github" / "scripts" / "release_checks.py"
)
spec = importlib.util.spec_from_file_location("release_checks", SCRIPT)
assert spec and spec.loader
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)

CHANGELOG = """# Changelog

## Unreleased

### Added
- next thing

## [2.0.0] - 2026-11-01

### Breaking
- Python 3.11+

## [1.0.0] - 2026-01-01
- first
"""


def make_repo(tmp_path: Path, py="2.0.0", npm="2.0.0", changelog=CHANGELOG) -> Path:
    (tmp_path / "query_builder").mkdir(exist_ok=True)
    (tmp_path / "query_builder" / "__init__.py").write_text(
        f'"""doc"""\n__version__ = "{py}"\n', encoding="utf-8"
    )
    (tmp_path / "packages" / "react").mkdir(parents=True, exist_ok=True)
    (tmp_path / "packages" / "react" / "package.json").write_text(
        json.dumps({"name": "x", "version": npm}), encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return tmp_path


def test_matching_versions_pass(tmp_path):
    root = make_repo(tmp_path)
    assert rc.check_versions("v2.0.0", root) == []
    assert rc.check_versions(None, root) == []


def test_mismatches_are_reported(tmp_path):
    root = make_repo(tmp_path, npm="2.0.1")
    assert any("!= npm" in e for e in rc.check_versions(None, root))
    root = make_repo(tmp_path)
    assert any("does not match" in e for e in rc.check_versions("v2.0.1", root))
    assert any("must look like" in e for e in rc.check_versions("2.0.0", root))


def test_prerelease_versions_are_rejected(tmp_path):
    root = make_repo(tmp_path, py="2.0.0rc1", npm="2.0.0rc1")
    assert any("plain X.Y.Z" in e for e in rc.check_versions(None, root))


def test_missing_or_empty_changelog_section_fails(tmp_path):
    root = make_repo(tmp_path, py="3.0.0", npm="3.0.0")
    assert any("no '## [3.0.0]'" in e for e in rc.check_versions("v3.0.0", root))
    (tmp_path / "empty").mkdir()
    empty = make_repo(
        tmp_path / "empty", changelog="## [2.0.0] - x\n\n## [1.0.0]\n- a\n"
    )
    assert any("is empty" in e for e in rc.check_versions(None, empty))


def test_branch_dry_runs_may_skip_the_changelog_check(tmp_path):
    root = make_repo(tmp_path, py="3.0.0", npm="3.0.0")
    assert rc.check_versions(None, root, require_changelog=False) == []


def test_notes_extract_only_the_requested_section(tmp_path):
    root = make_repo(tmp_path)
    section = rc.changelog_section("2.0.0", root)
    assert section is not None
    assert "Python 3.11+" in section
    assert "next thing" not in section and "first" not in section
    assert rc.changelog_section("9.9.9", root) is None


def test_real_repository_is_self_consistent():
    # The checked-in versions must always agree (tag aside), even between releases.
    assert rc.python_version() == rc.npm_version()


def test_cli_entry_points(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(rc, "ROOT", tmp_path)
    make_repo(tmp_path)
    monkeypatch.setattr(rc, "python_version", lambda root=tmp_path: "2.0.0")
    monkeypatch.setattr(rc, "npm_version", lambda root=tmp_path: "2.0.0")
    monkeypatch.setattr(
        rc,
        "changelog_section",
        lambda v, root=tmp_path: "body" if v == "2.0.0" else None,
    )
    assert rc.main(["versions", "--tag", "v2.0.0"]) == 0
    assert capsys.readouterr().out.strip() == "2.0.0"
    assert rc.main(["versions", "--tag", "v2.0.1"]) == 1
    assert "does not match" in capsys.readouterr().err
    assert rc.main(["notes", "2.0.0"]) == 0
    assert capsys.readouterr().out.strip() == "body"
    assert rc.main(["notes", "1.2.3"]) == 1


def test_python_version_requires_marker(tmp_path):
    (tmp_path / "query_builder").mkdir()
    (tmp_path / "query_builder" / "__init__.py").write_text("x = 1\n")
    with pytest.raises(SystemExit):
        rc.python_version(tmp_path)
