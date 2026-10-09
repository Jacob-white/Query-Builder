#!/usr/bin/env python
"""Run live-engine tests in one isolated, memory-safe batch.

    python scripts/it_batch.py --label b1 --engines postgres,mysql --services "postgres mysql"
    python scripts/it_batch.py --label arango --engines arangodb \\
        --compose docker/compose.nosql.yml --profile nosql --services arangodb

A batch is: wait for the machine-wide lock and enough free RAM -> ``docker compose up --wait``
(only the named services, project ``qb-integration``) -> ``pytest -m integration`` restricted
to the named engines -> ``docker compose down -v`` (always, even on failure or Ctrl-C) ->
release the lock. The lock serialises batches across processes, so several agents or people
can use the same machine without starting competing heavy stacks.

Nothing outside the ``qb-integration`` compose project is ever started, stopped or removed.
Run ``--help`` for all options. See ``docs/TESTING_LIVE.md``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COMPOSE = "docker/docker-compose.integration.yml"
PROJECT = "qb-integration"
LOCK_PATH = Path(tempfile.gettempdir()) / "qb_it_batch.lock"
STALE_AFTER_SECONDS = 4 * 3600


# --------------------------------------------------------------------------- memory


def free_memory_gb() -> float | None:
    """Available physical memory in GiB, or None when it cannot be determined."""
    try:
        if sys.platform == "win32":
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _Status()
            status.dwLength = ctypes.sizeof(_Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
            return status.ullAvailPhys / 1024**3
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            for line in meminfo.read_text().splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024**2
        if sys.platform == "darwin":
            out = subprocess.run(
                ["vm_stat"], capture_output=True, text=True, check=False
            ).stdout
            page = 4096
            pages = {}
            for line in out.splitlines():
                if ":" in line:
                    key, _, val = line.partition(":")
                    digits = "".join(ch for ch in val if ch.isdigit())
                    if digits:
                        pages[key.strip()] = int(digits)
            free = pages.get("Pages free", 0) + pages.get("Pages inactive", 0)
            return free * page / 1024**3
    except Exception:  # noqa: BLE001
        return None
    return None


def wait_for_memory(min_free_gb: float, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        free = free_memory_gb()
        if free is None or free >= min_free_gb:
            return
        if time.monotonic() > deadline:
            raise SystemExit(
                f"only {free:.1f} GiB free (< {min_free_gb} GiB required); not starting containers"
            )
        print(
            f"[it_batch] waiting for memory: {free:.1f} GiB free, need {min_free_gb}",
            flush=True,
        )
        time.sleep(15)


# ----------------------------------------------------------------------------- lock


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # type: ignore[attr-defined]
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _lock_is_stale(path: Path) -> bool:
    try:
        info = json.loads(path.read_text())
    except (OSError, ValueError):
        return True
    age = time.time() - float(info.get("started", 0))
    return age > STALE_AFTER_SECONDS or not _pid_alive(int(info.get("pid", 0)))


def acquire_lock(label: str, timeout: float, path: Path = LOCK_PATH) -> None:
    deadline = time.monotonic() + timeout
    payload = json.dumps({"pid": os.getpid(), "started": time.time(), "label": label})
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _lock_is_stale(path):
                with contextlib.suppress(OSError):
                    path.unlink()
                continue
            if time.monotonic() > deadline:
                raise SystemExit(
                    f"timed out waiting for the live-test lock held per {path}"
                ) from None
            try:
                holder = json.loads(path.read_text()).get("label", "?")
            except (OSError, ValueError):
                holder = "?"
            print(f"[it_batch] waiting for batch '{holder}' to finish...", flush=True)
            time.sleep(10)
            continue
        with os.fdopen(fd, "w") as fh:
            fh.write(payload)
        return


def release_lock(path: Path = LOCK_PATH) -> None:
    with contextlib.suppress(OSError):
        info = json.loads(path.read_text())
        if int(info.get("pid", -1)) == os.getpid():
            path.unlink()


# --------------------------------------------------------------------------- docker


def compose_cmd(compose_files: list[str], profiles: list[str]) -> list[str]:
    cmd = ["docker", "compose", "-p", PROJECT]
    for f in compose_files:
        cmd += ["-f", f]
    for p in profiles:
        cmd += ["--profile", p]
    return cmd


def run_batch(args: argparse.Namespace) -> int:
    compose_files = args.compose or [DEFAULT_COMPOSE]
    profiles = args.profile or []
    services = [
        s for chunk in (args.services or []) for s in chunk.replace(",", " ").split()
    ]
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report = report_dir / f"{args.label}.json"
    base = compose_cmd(compose_files, profiles)
    env = dict(os.environ)
    env["QB_IT_ENGINES"] = args.engines
    env["QB_IT_REPORT"] = str(report)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    code = 1
    acquire_lock(args.label, args.lock_timeout)
    try:
        if services:
            wait_for_memory(args.min_free_gb, args.memory_timeout)
            print(f"[it_batch] starting: {' '.join(services)}", flush=True)
            up = subprocess.run(
                base + ["up", "-d", "--wait", *services], cwd=ROOT, check=False
            )
            if up.returncode != 0:
                print("[it_batch] services did not become healthy", flush=True)
                return up.returncode
        if args.linux:
            code = subprocess.run(
                ["sh", "scripts/it_docker_run.sh", *args.engines.split(",")],
                cwd=ROOT,
                env=env,
                check=False,
            ).returncode
        else:
            pytest = [
                args.python or sys.executable,
                "-m",
                "pytest",
                "tests/integration",
                "-m",
                "integration",
                "-o",
                "addopts=",
                "-q",
                "-p",
                "no:cacheprovider",
                "--tb=short",
                "-rfE",
                *args.pytest_arg,
            ]
            code = subprocess.run(pytest, cwd=ROOT, env=env, check=False).returncode
    finally:
        if not args.keep_up:
            print("[it_batch] tearing down (compose down -v)", flush=True)
            subprocess.run(
                base + ["down", "-v"],
                cwd=ROOT,
                check=False,
                capture_output=True,
            )
        release_lock()
    print(f"[it_batch] report: {report}  exit={code}", flush=True)
    return code


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--label", required=True, help="report file name stem")
    p.add_argument(
        "--engines", required=True, help="comma separated engine names (QB_IT_ENGINES)"
    )
    p.add_argument(
        "--services", action="append", help="compose services to start (repeatable)"
    )
    p.add_argument(
        "--compose",
        action="append",
        help=f"compose file(s) (default {DEFAULT_COMPOSE})",
    )
    p.add_argument("--profile", action="append", help="compose profile(s) to enable")
    p.add_argument("--report-dir", default=str(ROOT / "tests/integration/.reports"))
    p.add_argument("--python", help="interpreter that has the drivers installed")
    p.add_argument(
        "--linux",
        action="store_true",
        help="run inside a Linux container (scripts/it_docker_run.sh)",
    )
    p.add_argument(
        "--keep-up",
        action="store_true",
        help="do not tear the services down afterwards",
    )
    p.add_argument("--min-free-gb", type=float, default=3.0)
    p.add_argument("--memory-timeout", type=float, default=1800)
    p.add_argument("--lock-timeout", type=float, default=4 * 3600)
    p.add_argument(
        "--pytest-arg",
        action="append",
        default=[],
        help="extra argument passed to pytest",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    return run_batch(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
