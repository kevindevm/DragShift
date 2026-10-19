"""Archive support: ZIP/TAR(+GZ/BZ2/XZ)/7Z extract + create.

ZIP/TAR via stdlib. 7Z via py7zr (light, pure-python). RAR/CAB/ISO are detected
as archives but need external tools -> clear UserError.
"""
from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

from .util import UserError, output_dir, sibling, unique_path

READABLE = {".zip", ".tar", ".tgz", ".tar.gz", ".tar.bz2", ".tbz", ".tar.xz", ".txz",
            ".gz", ".bz2", ".xz", ".7z"}
CREATABLE = ("ZIP", "TAR.GZ", "7Z")


def _kind(src: str | Path) -> str:
    n = Path(src).name.lower()
    for ext in (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz", ".txz"):
        if n.endswith(ext):
            return ext
    return Path(src).suffix.lower()


def arch_list(src: str | Path, limit: int = 200) -> list[str]:
    k = _kind(src)
    try:
        if k == ".zip":
            with zipfile.ZipFile(src) as z:
                return z.namelist()[:limit]
        if k == ".7z":
            import py7zr
            with py7zr.SevenZipFile(src) as z:
                return z.getnames()[:limit]
        if k in (".gz", ".bz2", ".xz") and not _kind(src).startswith(".tar"):
            return [Path(src).stem]
        with tarfile.open(src, "r:*") as t:
            return t.getnames()[:limit]
    except Exception as e:
        raise UserError(f"Couldn't list archive: {e}")
    raise UserError(f"Unsupported archive: {Path(src).suffix}")


def arch_extract(src: str | Path) -> Path:
    k = _kind(src)
    folder = unique_path(output_dir(src) / f"{Path(src).stem} extracted")
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if k == ".zip":
            with zipfile.ZipFile(src) as z:
                z.extractall(folder)
        elif k == ".7z":
            import py7zr
            with py7zr.SevenZipFile(src) as z:
                z.extractall(folder)
        elif k in (".gz", ".bz2", ".xz"):
            import gzip, bz2, lzma
            opener = {"gz": gzip.open, "bz2": bz2.open, "xz": lzma.open}[k[1:]]
            with opener(src, "rb") as f, open(folder / Path(src).stem, "wb") as w:
                w.write(f.read())
        else:
            with tarfile.open(src, "r:*") as t:
                t.extractall(folder, filter="data")
        return folder
    except Exception as e:
        raise UserError(f"Couldn't extract: {e}")


def arch_create(srcs: list[str | Path], fmt: str = "ZIP") -> Path:
    fmt = fmt.upper()
    if not srcs:
        raise UserError("Nothing to compress.")
    first = Path(srcs[0])
    if fmt == "ZIP":
        from .filetools import zip_files
        return zip_files(srcs)
    if fmt == "TAR.GZ":
        out = unique_path(output_dir(first) / f"{first.stem} bundle.tar.gz")
        with tarfile.open(out, "w:gz") as t:
            for s in srcs:
                p = Path(s)
                t.add(p, arcname=p.name if p.is_file() else p.name)
        return out
    if fmt == "7Z":
        import py7zr
        out = unique_path(output_dir(first) / f"{first.stem} bundle.7z")
        with py7zr.SevenZipFile(out, "w") as z:
            for s in srcs:
                p = Path(s)
                if p.is_file():
                    z.write(p, p.name)
                elif p.is_dir():
                    z.writeall(p, p.name)
        return out
    raise UserError(f"Unknown archive format: {fmt}")
