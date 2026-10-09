"""Release helpers used by .github/workflows/release.yml (stdlib only).

    python .github/scripts/release_checks.py versions [--tag vX.Y.Z]
    python .github/scripts/release_checks.py notes X.Y.Z > RELEASE_NOTES.md

``versions`` fails unless the Python package version, the npm package version and (when a tag
is given) the tag all agree, the version is a plain ``X.Y.Z`` release, and CHANGELOG.md has a
matching ``## [X.Y.Z]`` section. ``notes`` prints that section for the GitHub release body.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")


def python_version(root: Path = ROOT) -> str:
    text = (root / "query_builder" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("could not find __version__ in query_builder/__init__.py")
    return match.group(1)


def npm_version(root: Path = ROOT) -> str:
    package = json.loads((root / "packages/react/package.json").read_text("utf-8"))
    return str(package["version"])


def changelog_section(version: str, root: Path = ROOT) -> str | None:
    """Return the body of the ``## [version]`` section, or None if absent."""
    lines = (root / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    heading = re.compile(rf"^##\s+\[?{re.escape(version)}\]?(\s|$)")
    start = next((i for i, line in enumerate(lines) if heading.match(line)), None)
    if start is None:
        return None
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start + 1 : end]).strip()


def check_versions(
    tag: str | None, root: Path = ROOT, *, require_changelog: bool = True
) -> list[str]:
    errors: list[str] = []
    py, npm = python_version(root), npm_version(root)
    if py != npm:
        errors.append(f"python version {py} != npm version {npm}")
    if not VERSION_RE.fullmatch(py):
        errors.append(f"version {py!r} is not a plain X.Y.Z release version")
    if tag is not None:
        if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
            errors.append(f"tag {tag!r} must look like vX.Y.Z")
        elif tag[1:] != py:
            errors.append(f"tag {tag} does not match package version {py}")
    section = changelog_section(py, root)
    if not require_changelog:
        pass
    elif section is None:
        errors.append(f"CHANGELOG.md has no '## [{py}]' section (promote 'Unreleased')")
    elif not section:
        errors.append(f"CHANGELOG.md section for {py} is empty")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    versions = sub.add_parser("versions")
    versions.add_argument("--tag")
    versions.add_argument(
        "--no-changelog-check",
        action="store_true",
        help="dry runs from a branch: do not require a promoted CHANGELOG section",
    )
    notes = sub.add_parser("notes")
    notes.add_argument("version")
    args = parser.parse_args(argv)

    if args.command == "versions":
        errors = check_versions(args.tag, require_changelog=not args.no_changelog_check)
        for error in errors:
            print(f"::error::{error}", file=sys.stderr)
        if errors:
            return 1
        print(python_version())
        return 0

    section = changelog_section(args.version)
    if not section:
        print(f"no CHANGELOG.md section for {args.version}", file=sys.stderr)
        return 1
    print(section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
