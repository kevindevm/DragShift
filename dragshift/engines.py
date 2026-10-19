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
    eng = engines_root() / "libreoffice"
    if eng.exists():
        for cand in list(eng.rglob("soffice.exe")) + list(eng.rglob("soffice")):
            return cand
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
    local = engines_root() / "pandoc"
    if local.exists():
        for cand in list(local.rglob("pandoc.exe" if sys.platform == "win32" else "pandoc")):
            if cand.is_file() and os.access(cand, os.X_OK if sys.platform != "win32" else os.F_OK):
                return cand
    return None


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


LO_STABLE = "https://download.documentfoundation.org/libreoffice/stable/"


def libreoffice_latest() -> tuple[str, str]:
    """(version, msi_url) auto-detected from the stable directory. Raises UserError."""
    from .util import UserError
    import re
    import urllib.request

    def _get(url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": "DragShift"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")

    try:
        html = _get(LO_STABLE)
    except Exception as e:
        raise UserError(f"Couldn't reach LibreOffice downloads: {e}")
    vers = re.findall(r'href="(\d+\.\d+\.\d+)/"', html)
    if not vers:
        raise UserError("Couldn't list LibreOffice versions.")
    ver = sorted(vers, key=lambda v: tuple(int(x) for x in v.split(".")))[-1]
    try:
        sub = _get(f"{LO_STABLE}{ver}/win/x86_64/")
    except Exception as e:
        raise UserError(f"Couldn't list LibreOffice {ver} files: {e}")
    msis = re.findall(r'href="(LibreOffice_[\d.]+_Win_x86-64\.msi)"', sub)
    if not msis:
        # language packs layout / archive naming fallback
        msis = re.findall(r'href="((?:LibreOffice|LibO)[^"]*_Win_x86(?:-64|_64)\.msi)"', sub)
        msis = [m for m in msis if "helppack" not in m and "sdk" not in m]
    if not msis:
        raise UserError(f"No Windows MSI found for LibreOffice {ver}.")
    return ver, f"{LO_STABLE}{ver}/win/x86_64/{msis[0]}"


def libreoffice_install(progress=None) -> Path:
    """Download the MSI + administrative install (msiexec /a, no admin, no registry).

    ~400 MB download, ~1.3 GB on disk. Raises UserError on any failure.
    """
    from .util import UserError
    import subprocess
    import tempfile
    import urllib.request
    have = _soffice()
    if have and str(have).startswith(str(engines_root())):
        return have
    ver, url = libreoffice_latest()
    dest = engines_root() / "libreoffice"
    tmp = Path(tempfile.mkdtemp()) / f"libreoffice-{ver}.msi"

    def _hook(block, size, total):
        if progress and total > 0:
            try:
                progress(min(99, int(block * size * 100 / total)))
            except Exception:
                pass

    try:
        urllib.request.urlretrieve(url, tmp, reporthook=_hook)
    except Exception as e:
        raise UserError(f"Couldn't download LibreOffice {ver}: {e}")
    target = dest / ver.replace(".", "_")
    target.mkdir(parents=True, exist_ok=True)
    log_path = dest / "install.log"
    try:
        r = subprocess.run(["msiexec", "/a", f'"{tmp}"', f'TARGETDIR="{target}"', "/qn", "/L*v", f'"{log_path}"'],
                           capture_output=True, timeout=1800)
    except Exception as e:
        raise UserError(f"msiexec failed: {e}")
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    if r.returncode != 0:
        raise UserError(f"LibreOffice install failed (msiexec code {r.returncode}). See engines/install.log.")
    so = _soffice()
    if not so:
        raise UserError("Installed, but soffice.exe not found. Report this as a bug.")
    return so


# ---------------------------------------------------------------- vendored wheels
def _plat_tags() -> list[str]:
    if sys.platform == "win32":
        return ["win_amd64", "win32"]
    if sys.platform == "darwin":
        import platform as _p
        arm = _p.machine().lower().startswith("arm")
        return (["macosx_11_0_arm64", "macosx_12_0_arm64", "macosx_10_9_x86_64"]
                if arm else ["macosx_10_9_x86_64", "macosx_11_0_arm64"])
    return ["manylinux_2_27_x86_64", "manylinux_2_17_x86_64", "manylinux2014_x86_64"]


def wheel_importable(name: str, vendor: Path) -> bool:
    """Add a vendored wheel dir to the path (native DLLs included) and try import."""
    if vendor.exists():
        s = str(vendor)
        if s not in sys.path:
            sys.path.insert(0, s)
        if sys.platform == "win32":
            for d in (vendor,):
                try:
                    os.add_dll_directory(str(d))
                except Exception:
                    pass
        # frozen exe: its own dir already has the CRT; also expose it
        if getattr(sys, "frozen", False):
            try:
                os.add_dll_directory(sys._MEIPASS)
            except Exception:
                pass
    try:
        __import__(name)
        return True
    except Exception:
        return False


def download_wheel(name: str, vendor: Path, version: str | None = None,
                   progress=None) -> Path:
    """Download+verify+extract a PyPI wheel into vendor/. Raises UserError."""
    from .util import UserError
    import hashlib
    import json as _json
    import urllib.request
    import zipfile

    def _get(url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "DragShift"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()

    py = f"cp{sys.version_info.major}{sys.version_info.minor}"
    meta_url = (f"https://pypi.org/pypi/{name}/{version}/json" if version
                else f"https://pypi.org/pypi/{name}/json")
    try:
        meta = _json.loads(_get(meta_url).decode("utf-8"))
    except Exception as e:
        raise UserError(f"Couldn't reach PyPI for {name}: {e}")
    cands = []
    for u in meta.get("urls", []):
        fn = u.get("filename", "")
        if not fn.endswith(".whl"):
            continue
        low = fn.lower()
        py_ok = (py in low) or ("py3" in low and "cp" not in low) or ("py2.py3" in low)
        plat_ok = any(t in low for t in _plat_tags())
        if py_ok and plat_ok:
            cands.append(u)
    if not cands:
        raise UserError(f"No {name} wheel for this Python/platform. Use the Python version instead.")
    # prefer exact cp match, then smallest file
    cands.sort(key=lambda u: (f"-{py}-" not in u["filename"], u.get("size", 0)))
    pick = cands[0]
    data = _get(pick["url"])
    digest = hashlib.sha256(data).hexdigest()
    if digest != pick.get("sha256", digest):
        raise UserError(f"{name} download failed checksum.")
    vendor.mkdir(parents=True, exist_ok=True)
    try:
        import io as _io
        with zipfile.ZipFile(_io.BytesIO(data)) as z:
            z.extractall(vendor)
    except Exception as e:
        raise UserError(f"Couldn't unpack {name}: {e}")
    return vendor
