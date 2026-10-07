"""Safe zip extraction with size and path-traversal guards."""

from __future__ import annotations

import zipfile
from pathlib import Path

MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_ZIP_ENTRIES = 5_000
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024


class UnsafeZipError(ValueError):
    pass


def _is_safe_member(name: str) -> bool:
    path = Path(name)
    if path.is_absolute():
        return False
    return ".." not in path.parts


def safe_extract_zip(archive_path: Path, dest: Path, *, max_bytes: int = MAX_ZIP_BYTES) -> None:
    raw = archive_path.read_bytes()
    if len(raw) > max_bytes:
        raise UnsafeZipError(f"Archive exceeds {max_bytes} bytes")

    total_uncompressed = 0
    with zipfile.ZipFile(archive_path, "r") as zf:
        members = zf.infolist()
        if len(members) > MAX_ZIP_ENTRIES:
            raise UnsafeZipError(f"Archive has more than {MAX_ZIP_ENTRIES} entries")
        for info in members:
            if not _is_safe_member(info.filename):
                raise UnsafeZipError(f"Unsafe path in archive: {info.filename}")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise UnsafeZipError("Archive uncompressed size exceeds limit")
        zf.extractall(path=dest)
