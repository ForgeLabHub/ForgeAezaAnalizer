"""Tests for safe archive extraction."""

from __future__ import annotations

import zipfile

import pytest

from aeza_analyzer.importer.archive import ArchiveError, safe_extract


def _make_zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return path


def _real_zip():
    from pathlib import Path

    return Path(__file__).resolve().parent.parent / "датасет.zip"


def test_extracts_real_archive(tmp_path):
    result = safe_extract(_real_zip(), tmp_path / "out")
    assert "датасет/data.json" in result.members
    assert result.total_uncompressed > 0
    assert (result.extract_dir / "датасет" / "data.json").is_file()


def test_rejects_path_traversal(tmp_path):
    archive = _make_zip(tmp_path / "evil.zip", {"../escape.txt": "x"})
    with pytest.raises(ArchiveError, match="path traversal"):
        safe_extract(archive, tmp_path / "out")


def test_rejects_absolute_path(tmp_path):
    archive = _make_zip(tmp_path / "abs.zip", {"/etc/passwd": "x"})
    with pytest.raises(ArchiveError, match="absolute path"):
        safe_extract(archive, tmp_path / "out")


def test_rejects_duplicate_names(tmp_path):
    archive = tmp_path / "dup.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.txt", "1")
        zf.writestr("A.txt", "2")
    with pytest.raises(ArchiveError, match="duplicate"):
        safe_extract(archive, tmp_path / "out")


def test_rejects_corrupt_archive(tmp_path):
    bogus = tmp_path / "bad.zip"
    bogus.write_bytes(b"this is not a zip file")
    with pytest.raises(ArchiveError):
        safe_extract(bogus, tmp_path / "out")


def test_reports_nested_archives_without_extracting(tmp_path):
    archive = _make_zip(
        tmp_path / "nested.zip",
        {"outer/inner.zip": b"PK\x03\x04 not really", "outer/keep.txt": "hi"},
    )
    result = safe_extract(archive, tmp_path / "out")
    assert result.nested_archives == ["outer/inner.zip"]
    # The nested archive is stored as an inert file, never expanded.
    assert not (result.extract_dir / "outer" / "inner").exists()


def test_rejects_missing_archive(tmp_path):
    with pytest.raises(ArchiveError, match="not found"):
        safe_extract(tmp_path / "nope.zip", tmp_path / "out")
