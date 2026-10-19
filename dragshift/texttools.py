"""Pure text-file tools (no UI here, so they're testable).

Everything works on ``convert.read_text`` (tolerant encoding detection) and
writes next to the source via ``util.sibling``. Only the stdlib is used.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import re
from pathlib import Path
from xml.dom import minidom
from xml.etree import ElementTree as ET

from .convert import read_text
from .util import sibling

MAX_PREVIEW_BYTES = 5_000_000


def _check_size(src: str | Path) -> str:
    text = read_text(src)
    if len(text.encode("utf-8", "ignore")) > MAX_PREVIEW_BYTES:
        from .util import UserError
        raise UserError("This file is too big for a quick text tool (over ~5 MB).")
    if "\0" in text[:8000]:
        from .util import UserError
        raise UserError("This looks like a binary file, not text.")
    return text


def _name(src: str | Path) -> str:
    return Path(src).name.lower()


JSON_EXTS = {".json", ".jsonc"}
XML_EXTS = {".xml", ".xsl", ".xsd", ".svg", ".plist", ".config", ".iml"}


def can_format(src: str | Path) -> bool:
    ext = Path(src).suffix.lower()
    return ext in JSON_EXTS or ext in XML_EXTS


def can_minify(src: str | Path) -> bool:
    ext = Path(src).suffix.lower()
    return ext in JSON_EXTS or ext in XML_EXTS or ext == ".css"


def can_mask(src: str | Path) -> bool:
    n = _name(src)
    return n == ".env" or n.startswith(".env.") or n.startswith(".env_")


def can_sort(src: str | Path) -> bool:
    n = _name(src)
    ext = Path(src).suffix.lower()
    if n in {".env"} or n.startswith(".env."):
        return True
    if ext in {".txt", ".log", ".csv", ".tsv", ".tab", ".psv"}:
        return True
    return n.endswith("ignore")


def tidy_text(src: str | Path) -> Path:
    """Strip trailing whitespace, expand tabs, ensure a single trailing newline."""
    text = _check_size(src)
    lines = [ln.expandtabs(4).rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    out = sibling(src, "Tidied")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return out


def convert_eol(src: str | Path, to_crlf: bool = False) -> Path:
    text = _check_size(src).replace("\r\n", "\n").replace("\r", "\n")
    label = "CRLF" if to_crlf else "LF"
    out = sibling(src, label)
    out.write_bytes(text.replace("\n", "\r\n").encode("utf-8") if to_crlf else text.encode("utf-8"))
    return out


def sort_text(src: str | Path) -> Path:
    """Sort lines A→Z, dropping exact duplicates. Comments stay on top for .env."""
    text = _check_size(src)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    n = _name(src)
    if n == ".env" or n.startswith(".env."):
        head = [ln for ln in lines if ln.strip().startswith("#")]
        body = sorted({ln for ln in lines if ln not in head})
        ordered = head + body
    else:
        ordered = sorted(set(lines))
    out = sibling(src, "Sorted")
    out.write_text("\n".join(ordered) + "\n", encoding="utf-8", newline="\n")
    return out


def mask_secrets(src: str | Path) -> Path:
    """Rewrite KEY=VALUE lines as KEY=*** (comments and blanks untouched)."""
    text = _check_size(src)
    out_lines = []
    for ln in text.replace("\r\n", "\n").split("\n"):
        m = re.match(r"^(\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_.-]*\s*=).*", ln)
        out_lines.append(f"{m.group(1)}***" if m and ln.split("=", 1)[1].strip() else ln)
    out = sibling(src, "Masked")
    out.write_text("\n".join(out_lines), encoding="utf-8", newline="\n")
    return out


def format_text(src: str | Path) -> Path:
    """Pretty-print JSON or XML. Raises UserError when the content is invalid."""
    from .util import UserError
    text = _check_size(src)
    ext = Path(src).suffix.lower()
    try:
        if ext in JSON_EXTS:
            pretty = json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"
        elif ext in XML_EXTS:
            pretty = minidom.parseString(text).toprettyxml(indent="  ", encoding=None)
            if not pretty.endswith("\n"):
                pretty += "\n"
        else:
            raise UserError("Format is only available for JSON and XML files.")
    except (json.JSONDecodeError, ET.ParseError, ValueError, OSError) as e:
        raise UserError(f"Couldn't parse this file: {e}")
    out = sibling(src, "Formatted")
    out.write_text(pretty, encoding="utf-8", newline="\n")
    return out


def minify_text(src: str | Path) -> Path:
    from .util import UserError
    text = _check_size(src)
    ext = Path(src).suffix.lower()
    try:
        if ext in JSON_EXTS:
            mini = json.dumps(json.loads(text), separators=(",", ":"), ensure_ascii=False)
        elif ext in XML_EXTS:
            root = ET.fromstring(text)
            mini = ET.tostring(root, encoding="unicode")
        elif ext == ".css":
            mini = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
            mini = re.sub(r"\s+", " ", mini).replace(" {", "{").replace("} ", "}").strip()
        else:
            raise UserError("Minify is only available for JSON, XML and CSS files.")
    except (json.JSONDecodeError, ET.ParseError, ValueError) as e:
        raise UserError(f"Couldn't parse this file: {e}")
    out = sibling(src, "Minified")
    out.write_text(mini, encoding="utf-8", newline="\n")
    return out


def text_stats(src: str | Path) -> dict[str, str]:
    text = _check_size(src)
    lines = text.splitlines()
    words = sum(len(ln.split()) for ln in lines)
    import hashlib
    digest = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:12]
    return {
        "Lines": str(len(lines)),
        "Words": str(words),
        "Size": f"{len(text.encode('utf-8'))} bytes",
        "SHA-256": digest + "…",
    }


def csv_delimiter(src: str | Path, to: str = ";") -> Path:
    """Rewrite a CSV/TSV with another delimiter (auto-detected via csv.Sniffer)."""
    from .util import UserError
    text = _check_size(src)
    try:
        dialect = csv.Sniffer().sniff(text[:16000], delimiters=[",", ";", "\t", "|"])
    except csv.Error:
        raise UserError("Couldn't detect the table delimiter in this file.")
    reader = csv.reader(io.StringIO(text), dialect)
    out = sibling(src, f"Delimiter {to if to != chr(9) else 'TAB'}")
    with out.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f, delimiter=to, lineterminator="\n").writerows(reader)
    return out
