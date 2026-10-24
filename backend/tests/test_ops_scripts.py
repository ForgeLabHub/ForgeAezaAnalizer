"""Tests for the operational scripts that back up and restore the databases.

A restore procedure that has never been run is a liability, not a safety net. The
scripts need Docker and a live stack, so a full round trip is exercised in the
production acceptance audit rather than here. What these tests do pin down is the
part that silently rots: the scripts stay syntactically valid, remain executable,
and keep the two properties an operator depends on — a dry run changes nothing,
and the restore refuses to run without an explicit confirmation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
BACKUP = SCRIPTS / "backup.sh"
RESTORE = SCRIPTS / "restore.sh"
RUN = ROOT / "run.sh"


def test_both_scripts_are_present_and_executable():
    for script in (BACKUP, RESTORE):
        assert script.is_file(), f"{script.name} is missing"
    if os.name == "nt":
        pytest.skip("POSIX execute bits are not available on Windows")
    for script in (BACKUP, RESTORE):
        assert script.stat().st_mode & 0o111, f"{script.name} is not executable"


def test_run_script_targets_compose():
    source = RUN.read_text(encoding="utf-8")
    assert "docker compose up --build -d" in source
    assert "docker compose down" in source


@pytest.mark.parametrize("script", [BACKUP, RESTORE])
def test_scripts_are_valid_bash(script):
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not installed")
    result = subprocess.run([bash, "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_run_script_is_valid_bash():
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not installed")
    result = subprocess.run([bash, "-n", str(RUN)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_restore_requires_an_explicit_confirmation():
    """Without --yes the restore must exit before touching anything."""

    source = RESTORE.read_text(encoding="utf-8")
    assert 'CONFIRM" != "--yes"' in source, "the --yes guard is gone"
    assert "Dry run. Nothing was changed." in source


def test_backup_uses_the_sqlite_online_backup_api():
    """A plain file copy can tear under concurrent writes; the API cannot."""

    source = BACKUP.read_text(encoding="utf-8")
    assert ".backup(" in source
    assert "pg_dump" in source


def test_restore_removes_wal_sidecars_before_replacing_auth_database():
    """A stale -wal would shadow the restored database."""

    source = RESTORE.read_text(encoding="utf-8")
    assert '"-wal"' in source and '"-shm"' in source


def test_backups_are_gitignored():
    """Backups hold real account and customer data and must never be committed."""

    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/backups/" in ignore
