"""Engines registry: built-in, bundled, or opt-in downloadable converters.

Modelled on Filee's engines.json idea: every heavy/optional capability is an
engine with detect() + status, shown in Settings → Opcionales. Nothing heavy
ships inside DragShift.exe; big engines download on demand into
%LOCALAPPDATA%/DragShift/engines (kept across updates).
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


def engines_root() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    d = base / "DragShift" / "engines"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Engine:
    id: str
    name: str
    desc: str
    size: str
    kind: str  # "builtin" | "bundled" | "optional"
    detect: object = None
    download_url: str = ""
    note: str = ""
    extra: dict = field(default_factory=dict)


def _which(names: list[str]) -> Path | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return Path(p)
    return None


def _soffice() -> Path | None:
    found = _which(["soffice", "libreoffice"])
    if found:
        return found
    for cand in (r"C:\Program Files\LibreOffice\program\soffice.exe",
                 r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                 "/Applications/LibreOffice.app/Contents/MacOS/soffice",
                 "/usr/bin/soffice", "/usr/local/bin/soffice"):
        if os.path.exists(cand):
            return Path(cand)
    return None


def _pandoc() -> Path | None:
    p = _which(["pandoc"])
    if p:
        return p
    local = engines_root() / "pandoc" / ("pandoc.exe" if sys.platform == "win32" else "pandoc")
    return local if local.exists() else None


PANDOC_URLS = {
    "win32": ("https://github.com/jgm/pandoc/releases/download/3.7/pandoc-3.7-windows-x86_64.zip",
              "pandoc.exe"),
    "darwin": ("https://github.com/jgm/pandoc/releases/download/3.7/pandoc-3.7-arm64-macOS.zip",
               "pandoc"),
    "linux": ("https://github.com/jgm/pandoc/releases/download/3.7/pandoc-3.7-linux-amd64.tar.gz",
              "pandoc"),
}


def _ffmpeg() -> Path | None:
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        p = Path(get_ffmpeg_exe())
        return p if p.exists() else None
    except Exception:
        return None


def _ai_model() -> Path | None:
    try:
        from . import bgremove
        m = bgremove.models_dir() / bgremove.MODEL_NAME
        return m if m.exists() else None
    except Exception:
        return None


def registry() -> list[Engine]:
    lo = _soffice()
    pd = _pandoc()
    ff = _ffmpeg()
    ai = _ai_model()
    plat = "win32" if sys.platform == "win32" else ("darwin" if sys.platform == "darwin" else "linux")
    return [
        Engine("ffmpeg", "FFmpeg (video/audio)", "Built in via imageio-ffmpeg. Powers every audio/video conversion.",
               "~25 MB", "builtin" if ff else "missing", detect=lambda: ff,
               note="Bundled with the app."),
        Engine("office", "Documents in-process", "DOCX/XLSX/PPTX/ODT/ODS/EPUB/CSV/SQLite via Python libs.",
               "included", "builtin", detect=lambda: True,
               note="Always available."),
        Engine("ai-bg", "AI background (u2net)", "Portrait cutout. Downloads the model once (~176 MB).",
               "~176 MB", "optional", detect=lambda: ai,
               note="Settings → Background removal → AI."),
        Engine("pandoc", "Pandoc (markup)", "Markdown↔DOCX/ODT/RTF/EPUB, Jupyter, man pages and 40+ markup formats.",
               "~42 MB", "optional", detect=lambda: pd,
               download_url=PANDOC_URLS.get(plat, ("", ""))[0],
               note="Auto-downloads from GitHub into the engines folder."),
        Engine("libreoffice", "LibreOffice (legacy + fidelity)", "DOC/XLS/PPT, ODT→PDF with real fidelity, PDF→SVG.",
               "~420 MB", "optional", detect=lambda: lo,
               note="Uses your install if found; otherwise opens the official download page."),
    ]


def status(e: Engine) -> tuple[str, str]:
    """(state, message): ready | missing."""
    try:
        found = e.detect() if callable(e.detect) else None
    except Exception:
        found = None
    if found:
        return "ready", f"Ready ({found})"
    return "missing", "Not installed"


def libreoffice_pdf(src: str | Path, out_dir: str | Path | None = None) -> Path:
    """Convert any Office doc to PDF with LibreOffice headless (fidelity route)."""
    from .util import UserError, sibling
    lo = _soffice()
    if not lo:
        raise UserError("LibreOffice not found. Settings → Opcionales → LibreOffice to install it.")
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run([str(lo), "--headless", "--convert-to", "pdf", "--outdir", d, str(src)],
                           capture_output=True, text=True)
        pdfs = list(Path(d).glob("*.pdf"))
        if r.returncode != 0 or not pdfs:
            raise UserError(f"LibreOffice failed: {(r.stderr or r.stdout)[-400:]}")
        out = sibling(src, ext=".pdf")
        out.write_bytes(pdfs[0].read_bytes())
        return out
