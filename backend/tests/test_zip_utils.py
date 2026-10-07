import io
import zipfile
from pathlib import Path

import pytest

from core.zip_utils import UnsafeZipError, safe_extract_zip


def _make_zip(entries: dict[str, str], dest: Path) -> Path:
    archive = dest / "test.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return archive


def test_safe_extract_allows_normal_paths(tmp_path):
    archive = _make_zip({"app/main.py": "print('ok')\n"}, tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    safe_extract_zip(archive, out)
    assert (out / "app" / "main.py").read_text(encoding="utf-8") == "print('ok')\n"


def test_safe_extract_blocks_path_traversal(tmp_path):
    archive = _make_zip({"../escape.txt": "bad"}, tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(UnsafeZipError, match="Unsafe path"):
        safe_extract_zip(archive, out)


def test_safe_extract_blocks_oversized_archive(tmp_path):
    archive = tmp_path / "big.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.txt", "x" * (51 * 1024 * 1024))
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(UnsafeZipError, match="exceeds"):
        safe_extract_zip(archive, out)
