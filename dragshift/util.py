"""Shared helpers: output paths, file categories, sizes."""
from __future__ import annotations

import os
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".tif", ".tiff",
              ".avif", ".bmp", ".gif", ".ico"}
PDF_EXTS = {".pdf"}
DOCX_EXTS = {".docx"}
TEXT_EXTS = {".txt", ".md", ".markdown", ".csv", ".tsv", ".tab", ".psv", ".log",
             ".json", ".jsonc", ".xml", ".xsl", ".xsd", ".svg", ".plist", ".config",
             ".iml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
             ".properties", ".srt", ".vtt", ".ics", ".html", ".htm",
             ".rst", ".tex", ".org", ".textile", ".adoc",
             ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
             ".java", ".c", ".h", ".hpp", ".cpp", ".cc", ".cs",
             ".go", ".rs", ".php", ".rb", ".swift", ".kt", ".kts",
             ".scala", ".lua", ".pl", ".r", ".jl", ".dart",
             ".vue", ".svelte", ".sh", ".bash", ".zsh", ".ps1",
             ".bat", ".cmd", ".sql", ".css", ".scss", ".less",
             ".gradle", ".cmake", ".htaccess"}
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".oga", ".opus", ".flac", ".m4a", ".aac",
              ".wma", ".aiff", ".aif"}
VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".mpg", ".mpeg",
              ".wmv", ".flv", ".3gp"}
SHEET_EXTS = {".xlsx", ".ods", ".sqlite", ".sqlite3", ".db"}
PRESENT_EXTS = {".pptx", ".odp"}
EBOOK_EXTS = {".epub"}

# Exact file names (lowercase) that are plain text despite no (or odd) extension.
TEXT_NAMES = {
    ".env", ".gitignore", ".dockerignore", ".npmignore", ".prettierignore",
    ".eslintignore", ".editorconfig", ".npmrc", ".nvmrc", ".python-version",
    ".gitattributes", ".gitmodules", ".babelrc", ".browserslistrc", ".htaccess",
    "dockerfile", "makefile", "license", "licence", "readme", "changelog",
    "authors", "todo", "vagrantfile", "gemfile", "rakefile", "procfile",
    "cmakelists.txt",
}
# Basenames that also match with a dotted suffix: Dockerfile.dev, .env.local …
TEXT_BASENAMES = {"dockerfile", "makefile", "gemfile", "rakefile", "procfile",
                  "vagrantfile", "cmakelists"}


def category(path: str | Path) -> str | None:
    name = Path(path).name.lower()
    if name in TEXT_NAMES:
        return "text"
    if name.startswith(".env.") or name.startswith(".env_"):
        return "text"
    base = name[1:] if name.startswith(".") else name
    base = base.split(".")[0]
    if base in TEXT_BASENAMES:
        return "text"
    ext = Path(path).suffix.lower()
    if not ext:
        # .env / .gitignore have no suffix (caught above); other extensionless
        # files (LICENSE, README, TODO) are plain text too.
        return "text"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in PDF_EXTS:
        return "pdf"
    if ext in DOCX_EXTS:
        return "docx"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in SHEET_EXTS:
        return "sheet"
    if ext in PRESENT_EXTS:
        return "presentation"
    if ext in EBOOK_EXTS:
        return "ebook"
    if ext in TEXT_EXTS:
        return "text"
    return None


def unique_path(path: str | Path) -> Path:
    """Return `path`, or `name (1).ext`, `name (2).ext`... if it already exists."""
    p = Path(path)
    if not p.exists():
        return p
    i = 1
    while True:
        cand = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not cand.exists():
            return cand
        i += 1


class UserError(Exception):
    """An error with a message that's fine to show the user as-is."""


# Runtime options (filled from Settings at start-up; plain values so worker threads can read them)
CONFIG = {
    "output": "next",        # "next" = beside the original, "folder" = a "DragShift" subfolder
    "jpg_quality": 90,
    "pdf_dpi": 200,
}


def output_dir(src: str | Path) -> Path:
    d = Path(src).parent
    if CONFIG.get("output") == "folder":
        d = d / "DragShift"
        d.mkdir(exist_ok=True)
    return d


def sibling(src: str | Path, suffix_label: str = "", ext: str | None = None) -> Path:
    """Output path for `src`. sibling('a.jpg', 'Cropped') -> 'a Cropped.jpg' (never overwrites)."""
    s = output_dir(src) / Path(src).name
    # keep compound suffixes (.tar.gz) as one unit
    compound = "".join(s.suffixes[-2:]) if len(s.suffixes) >= 2 and s.suffixes[-1] in (
        ".gz", ".bz2", ".xz", ".zip") else s.suffix
    base = s.name[:-len(compound)] if compound and s.name.endswith(compound) else s.stem
    stem = f"{base} {suffix_label}".strip() if suffix_label else base
    new_ext = ext if ext is not None else compound
    if new_ext in ("", "."):
        new_ext = ""
    elif not new_ext.startswith("."):
        new_ext = "." + new_ext
    return unique_path(s.with_name(stem + new_ext))


def human_size(n: int | float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def file_size(path: str | Path) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


# ---------------------------------------------------------------- background job lifetime
# QThreadPool runs a QRunnable in C++, but the Python object (and the QObject carrying its
# signals) can be garbage-collected while it's still running: results then never arrive,
# or the app crashes. Keep every job alive until its result has been handled.
ALIVE: set = set()


def keep(job):
    job.setAutoDelete(False)
    ALIVE.add(job)
    return job


def release(job):
    ALIVE.discard(job)
