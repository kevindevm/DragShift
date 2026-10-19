"""Update checker: compare GitHub latest release tag vs local __version__."""
from __future__ import annotations

import json
import urllib.request

REPO = "kevindevm/DragShift"
API = f"https://api.github.com/repos/{REPO}/releases/latest"


def _norm(v: str) -> tuple:
    v = v.strip().lstrip("v")
    parts = []
    for p in v.split("."):
        try:
            parts.append(int("".join(c for c in p if c.isdigit()) or 0))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check(timeout: int = 8) -> tuple[bool, str, str]:
    """(is_newer, tag, url). Never raises: (False, '', '') on any failure."""
    try:
        from . import __version__
        req = urllib.request.Request(API, headers={"User-Agent": "DragShift", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        tag = str(data.get("tag_name", ""))
        url = str(data.get("html_url", ""))
        if not tag:
            return False, "", ""
        if tag == "latest":
            return False, tag, url  # rolling build, not a version
        return (_norm(tag) > _norm(__version__), tag, url)
    except Exception:
        return False, "", ""
