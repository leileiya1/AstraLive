"""Actual owned process states behind Darwin's zombie-only group EPERM."""

import subprocess
import sys
import time

import psutil

from output_guardian.supervisor import group_is_quiescent


def test_live_owned_group_is_not_quiescent():
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"], start_new_session=True
    )
    try:
        assert not group_is_quiescent(process.pid)
    finally:
        process.kill()
        process.wait(timeout=2)


def test_unreaped_owned_zombie_group_is_quiescent():
    process = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    try:
        owned = psutil.Process(process.pid)
        for _ in range(100):
            if owned.status() == psutil.STATUS_ZOMBIE:
                break
            time.sleep(0.01)
        assert owned.status() == psutil.STATUS_ZOMBIE
        assert group_is_quiescent(process.pid)
    finally:
        process.wait(timeout=2)


def test_unreadable_group_census_is_not_quiescent(monkeypatch):
    class Inaccessible:
        pid = 1

    def denied(_):
        raise PermissionError("census denied")

    monkeypatch.setattr("output_guardian.supervisor.psutil.process_iter", lambda _: [Inaccessible()])
    monkeypatch.setattr("output_guardian.supervisor.os.getpgid", denied)
    assert not group_is_quiescent(12345)
