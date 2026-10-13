"""Generate the environment-variable table in SECURITY.md from ``query_builder/config.py``.

A security document that names a variable the code never reads is worse than none: operators set
it believing it restricts something and nothing happens (``QB_ALLOWED_HOSTS`` was documented while
the code reads ``QB_ALLOWED_HOSTNAMES``). The names and the per-profile defaults are therefore read
from the code, never typed by hand.

Usage::

    python scripts/gen_security_env_table.py            # rewrite the table in SECURITY.md
    python scripts/gen_security_env_table.py --check    # exit 1 if SECURITY.md is stale

The table sits between ``<!-- BEGIN:security-env-table -->`` and ``<!-- END:security-env-table -->``.
Adding a variable to ``load_security_config_from_env`` makes ``--check`` fail until it has an entry
in ``EFFECT`` / ``ORDER`` below.
"""

from __future__ import annotations

import argparse
import inspect
import re
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import query_builder.config as config  # noqa: E402

BEGIN = "<!-- BEGIN:security-env-table -->"
END = "<!-- END:security-env-table -->"
DOC = ROOT / "SECURITY.md"

EFFECT = {
    "QB_ALLOW_PRIVATE_NETWORKS": "Allow loopback, RFC 1918 and other internal targets (cloud credential endpoints are always blocked). Unset is *not* the same as `false` for connectors - see 3.2",
    "QB_ENFORCE_TLS": "Reject insecure URL schemes (`http`, `ws`, `ftp`, ...) and disabled TLS/SSL settings. Unset is *not* the same as `true` for connectors - see 3.2",
    "QB_VERIFY_SSL_CERTS": "Verify TLS certificates against trusted CA roots",
    "QB_CA_BUNDLE_PATH": "Path to a CA bundle (must exist)",
    "QB_SOCKET_TIMEOUT_SECONDS": "Socket / connect timeout in seconds (> 0)",
    "QB_ALLOWED_HOSTNAMES": "Comma-separated allow-list of target hostnames or IPs (supports `*.domain.com`). Empty means no allow-list. **Not** `QB_ALLOWED_HOSTS`",
    "QB_BLOCKED_HOSTNAMES": "Comma-separated extra blocked hostnames or IPs (supports `*.domain.com`). **Not** `QB_BLOCKED_HOSTS`",
    "QB_ENFORCE_READ_ONLY": "Put database sessions into read-only mode where the engine supports it",
    "QB_STATEMENT_TIMEOUT_MS": "Statement timeout in milliseconds (>= 0)",
    "QB_MAX_ROWS_LIMIT": "Hard row ceiling per query (> 0)",
    "QB_MAX_JOIN_DEPTH": "Maximum joins per query (>= 0)",
    "QB_MAX_COMPLEXITY_SCORE": "Maximum AST complexity score (> 0). **Not** `QB_MAX_AST_COMPLEXITY`",
    "QB_PREVENT_CARTESIAN_PRODUCTS": "Reject joins without a join condition",
    "QB_ENABLE_CACHE": "Enable the query-result cache",
    "QB_DEFAULT_TTL_SECONDS": "Default cache entry lifetime in seconds (>= 0)",
    "QB_MAX_CACHE_ENTRIES": "Maximum cache entries (> 0)",
    "QB_VALIDATE_AST": "Enforce AST safety validation of SQL",
    "QB_ALLOWED_STATEMENTS": "Comma-separated statement types the validator accepts (cannot be empty)",
    "QB_ALLOW_SYSTEM_CATALOGS": "Permit access to administrative catalog schemas",
    "QB_FILTER_SQL_COMMENTS": "Filter SQL comments in submitted SQL",
    "QB_ALLOW_CTE": "Permit `WITH` clauses",
    "QB_ALLOW_RECURSIVE_CTE": "Permit `WITH RECURSIVE`",
    "QB_ENFORCE_TENANT_ISOLATION": "Fail-closed tenant predicate injection",
    "QB_TENANT_COLUMN": "Column holding the tenant id (cannot be empty)",
    "QB_MASKING_STRATEGY": "Masking mode: `redact`, `hash` or `partial`",
    "QB_SENSITIVE_COLUMN_PATTERNS": "Comma-separated regexes naming sensitive columns (built-in password/secret/token patterns by default)",
    "QB_MASK_CREDENTIALS": "Mask credentials in `repr` / logs",
    "QB_REDACT_PARAMETERS": "Redact bound parameter values in logs / audit events",
    "QB_EMIT_AUDIT_EVENTS": "Emit structured audit events",
    "QB_SENSITIVE_KEY_PATTERNS": "Comma-separated regexes naming sensitive config keys to scrub",
}
ORDER = list(EFFECT)  # documentation order


def variables_read_by_the_code() -> dict[str, str]:
    """``{QB_VARIABLE: "section.attribute"}`` for every variable the loader reads."""
    src = inspect.getsource(config.load_security_config_from_env)
    found: dict[str, str] = {}
    blocks = re.split(r'\n    if "(QB_[A-Z_]+)" in source:', src)
    it = iter(blocks[1:])
    for var, body in zip(it, it, strict=False):
        match = re.search(r"config\.([a-z_]+\.[a-z_]+)\s*=", body)
        if match:
            found[var] = match.group(1)
    return found


def _value(profile: str, path: str) -> object:
    cfg = config.load_security_config_from_env({"QB_SECURITY_PROFILE": profile})
    obj: object = cfg
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def _cell(value: object) -> str:
    if isinstance(value, bool):
        return "`true`" if value else "`false`"
    if value is None:
        return "unset"
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        if not items:
            return "`[]`"
        if len(items) > 4 or any(len(str(i)) > 18 for i in items):
            return "built-in"
        return "`" + ",".join(str(i) for i in items) + "`"
    return f"`{value}`"


def _kind(value: object) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, (list, tuple, set, frozenset)):
        return "list"
    return "str"


def render() -> str:
    read = variables_read_by_the_code()
    unknown = sorted(set(read) ^ set(ORDER))
    if unknown:
        raise SystemExit(
            f"EFFECT/ORDER in {Path(__file__).name} are out of sync with config.py: {unknown}"
        )
    rows = [
        "| Variable | Type | `development` | `production` | `strict` | Effect |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
        "| `QB_SECURITY_PROFILE` | str | | | | Base profile: `development`, `production` or `strict` (the config object defaults to `production`; see the default-policy note in 3.2 for connectors) |",
    ]
    for var in ORDER:
        values = [_value(p, read[var]) for p in ("development", "production", "strict")]
        rows.append(
            f"| `{var}` | {_kind(values[1])} | {_cell(values[0])} | {_cell(values[1])} "
            f"| {_cell(values[2])} | {EFFECT[var]} |"
        )
    return "\n".join(rows)


def rewrite(text: str) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    start, end = text.find(BEGIN), text.find(END)
    if start == -1 or end == -1 or end < start:
        raise SystemExit(f"{DOC.name} is missing the {BEGIN} / {END} markers")
    table = render().replace("\n", newline)
    return text[: start + len(BEGIN)] + newline + table + newline + text[end:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if SECURITY.md is stale"
    )
    args = parser.parse_args(argv)
    warnings.simplefilter("ignore")
    current = DOC.read_bytes().decode("utf-8")
    updated = rewrite(current)
    if args.check:
        if updated != current:
            print(f"{DOC.name} is stale: run python scripts/gen_security_env_table.py")
            return 1
        return 0
    if updated != current:
        DOC.write_bytes(updated.encode("utf-8"))
        print(f"wrote {DOC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
