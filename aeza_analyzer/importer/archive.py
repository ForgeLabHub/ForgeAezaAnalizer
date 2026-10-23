"""Safe extraction of the organiser archive.

Guards implemented:
* path traversal / absolute paths (``..``, leading ``/``, drive letters);
* symlinks and other non-regular members (never followed or created);
* duplicate member names (collision on a case-insensitive filesystem);
* decompression-bomb ratios and an absolute uncompressed size ceiling;
* nested archives are reported, never auto-extracted.

Executable members are extracted as inert files only; nothing from the archive
is ever executed.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

MAX_MEMBERS = 5_000
MAX_TOTAL_UNCOMPRESSED = 512 * 1024 * 1024  # 512 MiB
MAX_COMPRESSION_RATIO = 200.0
NESTED_SUFFIXES = (".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar")


class ArchiveError(RuntimeError):
    """Raised when an archive is unsafe, corrupt or unsupported."""


@dataclass
class ExtractedArchive:
    archive_path: Path
    extract_dir: Path
    sha256: str
    members: list[str] = field(default_factory=list)
    nested_archives: list[str] = field(default_factory=list)
    total_uncompressed: int = 0


def _is_unsafe(member: zipfile.ZipInfo) -> str | None:
    name = member.filename
    if name.startswith("/") or name.startswith("\\"):
        return f"absolute path: {name}"
    pure = PurePosixPath(name)
    if pure.is_absolute():
        return f"absolute path: {name}"
    if ".." in pure.parts:
        return f"path traversal: {name}"
    if len(name) > 1 and name[1] == ":":
        return f"drive-letter path: {name}"
    # symlink / device / fifo markers in the external attributes.
    mode = member.external_attr >> 16
    if mode and (mode & 0o170000) not in (0, 0o100000, 0o040000):
        return f"non-regular member (mode {oct(mode)}): {name}"
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract(archive_path: Path, extract_dir: Path) -> ExtractedArchive:
    archive_path = Path(archive_path)
    if not archive_path.is_file():
        raise ArchiveError(f"archive not found: {archive_path}")
    if not zipfile.is_zipfile(archive_path):
        raise ArchiveError(f"not a valid ZIP archive: {archive_path}")

    extract_dir.mkdir(parents=True, exist_ok=True)
    root = extract_dir.resolve()
    members: list[str] = []
    nested: list[str] = []
    total = 0

    try:
        with zipfile.ZipFile(archive_path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_MEMBERS:
                raise ArchiveError(f"too many members: {len(infos)} > {MAX_MEMBERS}")

            seen: set[str] = set()
            for info in infos:
                problem = _is_unsafe(info)
                if problem:
                    raise ArchiveError(f"unsafe member: {problem}")

                normalised = str(PurePosixPath(info.filename))
                folded = normalised.casefold()
                if folded in seen and not info.is_dir():
                    raise ArchiveError(f"duplicate member name: {info.filename}")
                seen.add(folded)

                if info.is_dir():
                    continue

                total += info.file_size
                if total > MAX_TOTAL_UNCOMPRESSED:
                    raise ArchiveError(
                        f"uncompressed size exceeds {MAX_TOTAL_UNCOMPRESSED} bytes"
                    )
                if info.compress_size > 0:
                    ratio = info.file_size / info.compress_size
                    if ratio > MAX_COMPRESSION_RATIO and info.file_size > 1 << 20:
                        raise ArchiveError(
                            f"suspicious compression ratio {ratio:.1f} for {info.filename}"
                        )

                target = (root / normalised).resolve()
                if not target.is_relative_to(root):
                    raise ArchiveError(f"escapes extract dir: {info.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as dst:
                    while chunk := src.read(1 << 20):
                        dst.write(chunk)

                members.append(normalised)
                if normalised.lower().endswith(NESTED_SUFFIXES):
                    nested.append(normalised)
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"corrupt ZIP archive: {archive_path}: {exc}") from exc

    return ExtractedArchive(
        archive_path=archive_path,
        extract_dir=extract_dir,
        sha256=_sha256(archive_path),
        members=members,
        nested_archives=nested,
        total_uncompressed=total,
    )
