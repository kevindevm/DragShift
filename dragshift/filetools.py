"""Universal file utilities: ZIP, hash, Base64, split/join, encrypt, QR, rename.

Works for *any* file type (binary-safe). No UI here.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

from .util import UserError, output_dir, sibling, unique_path

PART_SIZE = 10_000_000


def zip_files(srcs: list[str | Path], password: str | None = None) -> Path:
    if not srcs:
        raise UserError("Nothing to compress.")
    if password:
        try:
            import pyminizip
        except Exception:
            raise UserError("Password ZIP needs pyminizip (pip install pyminizip).")
        first = Path(srcs[0])
        out = unique_path(output_dir(first) / f"{first.stem} bundle.zip")
        pyminizip.compress_multiple([str(Path(s)) if Path(s).is_file() else str(Path(s)) for s in srcs
                                     if Path(s).is_file()],
                                    [], str(out), password, 5)
        return out
    first = Path(srcs[0])
    out = unique_path(output_dir(first) / f"{first.stem} bundle.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for s in srcs:
            p = Path(s)
            if p.is_dir():
                for f in sorted(p.rglob("*")):
                    if f.is_file():
                        z.write(f, f.relative_to(p.parent))
            elif p.is_file():
                z.write(p, p.name)
    return out


def sha256_file(src: str | Path) -> Path:
    h = hashlib.sha256()
    with open(src, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    out = sibling(src, ext=".sha256")
    out.write_text(f"{h.hexdigest()}  {Path(src).name}\n", encoding="utf-8")
    return out


def b64_encode(src: str | Path) -> Path:
    blob = Path(src).read_bytes()
    out = sibling(src, "Base64", ".txt")
    out.write_text(base64.b64encode(blob).decode("ascii"), encoding="utf-8")
    return out


def b64_decode(src: str | Path) -> Path:
    from .convert import read_text
    try:
        raw = base64.b64decode(read_text(src).strip(), validate=True)
    except Exception as e:
        raise UserError(f"Not valid Base64: {e}")
    out = sibling(src, "Decoded")
    out.write_bytes(raw)
    return out


def split_file(src: str | Path, part_size: int = PART_SIZE) -> list[Path]:
    outs: list[Path] = []
    with open(src, "rb") as f:
        i = 0
        while True:
            chunk = f.read(part_size)
            if not chunk:
                break
            i += 1
            out = sibling(src, f"part{i:03d}", f".part{i:03d}")
            out.write_bytes(chunk)
            outs.append(out)
    if not outs:
        raise UserError("Empty file, nothing to split.")
    return outs


def join_parts(srcs: list[str | Path]) -> Path:
    parts = sorted(srcs, key=lambda s: str(s))
    if not parts:
        raise UserError("No parts given.")
    first = Path(parts[0])
    m = re.match(r"^(.*)\.part\d+$", first.name)
    out = unique_path(first.with_name(m.group(1) if m else first.stem + " joined"))
    with out.open("wb") as w:
        for p in parts:
            with open(p, "rb") as f:
                shutil.copyfileobj(f, w)
    return out


def encrypt_file(src: str | Path, password: str) -> Path:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
    except Exception as e:
        raise UserError(f"Encryption needs cryptography: {e}")
    import os
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
    key = kdf.derive(password.encode("utf-8"))
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, Path(src).read_bytes(), None)
    out = sibling(src, ext=".enc")
    out.write_bytes(b"DSH1" + salt + nonce + ct)
    return out


def decrypt_file(src: str | Path, password: str) -> Path:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
    except Exception as e:
        raise UserError(f"Decryption needs cryptography: {e}")
    blob = Path(src).read_bytes()
    if not blob.startswith(b"DSH1") or len(blob) < 32:
        raise UserError("This .enc file wasn't made by DragShift.")
    salt, nonce, ct = blob[4:20], blob[20:32], blob[32:]
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
    key = kdf.derive(password.encode("utf-8"))
    try:
        pt = AESGCM(key).decrypt(nonce, ct, None)
    except Exception:
        raise UserError("Wrong password or corrupted file.")
    name = Path(src).name[:-4] if Path(src).suffix == ".enc" else Path(src).name + ".dec"
    out = unique_path(Path(src).with_name(name + " decrypted"))
    out.write_bytes(pt)
    return out


def qr_of_text(src: str | Path) -> Path:
    from .convert import read_text
    try:
        import qrcode
    except Exception as e:
        raise UserError(f"QR needs qrcode: {e}")
    text = read_text(src)
    if len(text.encode("utf-8")) > 2900:
        raise UserError("Text too long for a QR code (max ~3 KB). Hash it instead.")
    img = qrcode.make(text)
    out = sibling(src, "QR", ".png")
    img.save(out)
    return out


def batch_rename_preview(srcs: list[str | Path]) -> dict[str, str]:
    """Sanitize: lower, spaces->_, strip weird chars. Returns old->new mapping."""
    mapping: dict[str, str] = {}
    for s in srcs:
        p = Path(s)
        new = re.sub(r"[^a-z0-9_.\-]+", "", p.stem.lower().replace(" ", "_")) or "file"
        mapping[str(p)] = str(p.with_name(new + p.suffix.lower()))
    return mapping


def batch_rename(srcs: list[str | Path]) -> list[Path]:
    mapping = batch_rename_preview(srcs)
    manifest = Path(srcs[0]).parent / "DragShift rename undo.json"
    manifest.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    outs = []
    for old, new in mapping.items():
        dest = unique_path(new)
        Path(old).rename(dest)
        outs.append(dest)
    return outs


def diff_texts(a: str | Path, b: str | Path) -> Path:
    import difflib
    from .convert import read_text
    la = read_text(a).splitlines()
    lb = read_text(b).splitlines()
    html_doc = difflib.HtmlDiff().make_file(la, lb, str(Path(a).name), str(Path(b).name))
    out = sibling(a, f"vs {Path(b).stem} diff", ".html")
    out.write_text(html_doc, encoding="utf-8")
    return out


def playlist_m3u(srcs: list[str | Path]) -> Path:
    first = Path(srcs[0])
    out = unique_path(first.parent / "playlist.m3u")
    out.write_text("#EXTM3U\n" + "\n".join(str(Path(s).name) for s in sorted(srcs)) + "\n",
                   encoding="utf-8")
    return out
