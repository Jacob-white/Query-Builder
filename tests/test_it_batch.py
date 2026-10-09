"""scripts/it_batch.py: the machine-wide lock and memory guard that serialise live batches."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "it_batch.py"


@pytest.fixture(scope="module")
def it_batch():
    spec = importlib.util.spec_from_file_location("it_batch", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["it_batch"] = module
    spec.loader.exec_module(module)
    return module


def test_lock_is_exclusive_and_released_by_its_owner(it_batch, tmp_path):
    lock = tmp_path / "batch.lock"
    it_batch.acquire_lock("first", timeout=1, path=lock)
    assert json.loads(lock.read_text())["label"] == "first"
    with pytest.raises(SystemExit, match="timed out"):
        it_batch.acquire_lock("second", timeout=0, path=lock)
    it_batch.release_lock(lock)
    assert not lock.exists()
    it_batch.acquire_lock("second", timeout=1, path=lock)
    it_batch.release_lock(lock)


def test_stale_lock_of_a_dead_process_is_stolen(it_batch, tmp_path):
    lock = tmp_path / "batch.lock"
    # subprocess.run() returns only after the child exited and its handle was closed, so the
    # PID really is dead (a lingering Popen handle would keep it "alive" on Windows).
    out = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        capture_output=True,
        text=True,
        check=True,
    )
    dead_pid = int(out.stdout)
    lock.write_text(
        json.dumps({"pid": dead_pid, "started": time.time(), "label": "gone"})
    )
    it_batch.acquire_lock("alive", timeout=1, path=lock)
    assert json.loads(lock.read_text())["pid"] == os.getpid()
    it_batch.release_lock(lock)


def test_old_lock_is_stale_even_if_its_pid_is_alive(it_batch, tmp_path):
    lock = tmp_path / "batch.lock"
    lock.write_text(
        json.dumps(
            {"pid": os.getpid(), "started": time.time() - 5 * 3600, "label": "ancient"}
        )
    )
    assert it_batch._lock_is_stale(lock)


def test_release_does_not_remove_another_processes_lock(it_batch, tmp_path):
    lock = tmp_path / "batch.lock"
    lock.write_text(
        json.dumps({"pid": os.getpid() + 1, "started": time.time(), "label": "other"})
    )
    it_batch.release_lock(lock)
    assert lock.exists()


def test_corrupt_lock_file_counts_as_stale(it_batch, tmp_path):
    lock = tmp_path / "batch.lock"
    lock.write_text("{not json")
    assert it_batch._lock_is_stale(lock)


def test_free_memory_is_a_positive_number_or_unknown(it_batch):
    free = it_batch.free_memory_gb()
    assert free is None or free > 0


def test_memory_guard_refuses_when_not_enough_is_free(it_batch, monkeypatch):
    monkeypatch.setattr(it_batch, "free_memory_gb", lambda: 0.5)
    with pytest.raises(SystemExit, match="not starting containers"):
        it_batch.wait_for_memory(min_free_gb=3.0, timeout=0)
    monkeypatch.setattr(it_batch, "free_memory_gb", lambda: None)
    it_batch.wait_for_memory(min_free_gb=3.0, timeout=0)  # unknown memory: do not block


def test_compose_command_is_scoped_to_the_qb_project(it_batch):
    cmd = it_batch.compose_cmd(["docker/a.yml", "docker/b.yml"], ["nosql"])
    assert cmd[:4] == ["docker", "compose", "-p", "qb-integration"]
    assert cmd.count("-f") == 2 and cmd[-2:] == ["--profile", "nosql"]
