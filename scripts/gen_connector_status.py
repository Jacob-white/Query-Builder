"""Generate docs/CONNECTORS.md (and the JSON status report) from evidence.

Usage::

    python scripts/gen_connector_status.py                 # rewrite docs/CONNECTORS.md
    python scripts/gen_connector_status.py --check         # fail if the doc is stale
    python scripts/gen_connector_status.py --json out.json # also write the JSON report
    python scripts/gen_connector_status.py --record-live a.json [b.json ...]
        # promote live-suite reports (merged by engine) to docs/live_results.json
        # (the evidence that earns the `certified` tier), then regenerate the doc.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from query_builder.connectors import status  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--check", action="store_true", help="exit 1 if CONNECTORS.md is stale"
    )
    ap.add_argument("--json", metavar="PATH", help="also write the JSON report here")
    ap.add_argument(
        "--record-live",
        metavar="REPORT",
        nargs="+",
        help="record one or more live-suite reports (merged by engine)",
    )
    args = ap.parse_args(argv)

    if args.record_live:
        reports = [
            json.loads(Path(p).read_text(encoding="utf-8")) for p in args.record_live
        ]
        status.record_live(reports, ROOT)
    data = status.build_report(ROOT)
    text = status.render_markdown(data)
    target = ROOT / "docs" / "CONNECTORS.md"
    if args.json:
        Path(args.json).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if args.check:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != text:
            print("docs/CONNECTORS.md is stale; run scripts/gen_connector_status.py")
            return 1
        return 0
    target.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {target} ({data['totals']['classes']} classes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
