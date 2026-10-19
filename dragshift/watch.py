"""Hot-folder watcher: convert every stable file that lands in a folder.

Opt-in via Settings (hot_enable/hot_src/hot_to). Polls every 2 s; a file is
stable when size+mtime don't change between polls. Converted files get a
`.done` sidecar so they are not reconverted. Runs in the GUI thread.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QObject, QTimer


class HotFolder(QObject):
    def __init__(self, settings, submit, notify_parent=None):
        super().__init__()
        self.s = settings
        self.submit = submit
        self.seen: dict[str, tuple[int, float]] = {}
        self.timer = QTimer(self, interval=2000, timeout=self.poll)
        if bool(self.s.get("hot_enable")) and str(self.s.get("hot_src") or "").strip():
            self.timer.start()

    def _target(self) -> str:
        return str(self.s.get("hot_to") or "PDF").upper()

    def poll(self):
        try:
            if not bool(self.s.get("hot_enable")):
                return
            src = Path(str(self.s.get("hot_src") or ""))
            if not src.is_dir():
                return
            from .util import category
            from . import convert as _convert
            for p in sorted(src.iterdir()):
                if not p.is_file() or p.suffix == ".done" or p.name.endswith(".done"):
                    continue
                if (src / (p.name + ".done")).exists():
                    continue
                try:
                    st = (p.stat().st_size, p.stat().st_mtime)
                except OSError:
                    continue
                if self.seen.get(str(p)) != st:
                    self.seen[str(p)] = st
                    continue  # wait for stability
                cat = category(str(p))
                if cat is None:
                    (src / (p.name + ".done")).write_text("unsupported", encoding="utf-8")
                    continue
                target = self._target()
                try:
                    avail = _convert.targets_for(cat, p.suffix)
                except Exception:
                    avail = []
                if target not in avail:
                    (src / (p.name + ".done")).write_text(f"no-route:{target}", encoding="utf-8")
                    continue
                (src / (p.name + ".done")).write_text("queued", encoding="utf-8")
                paths = [str(p)]

                def _work(pp=str(p), cc=cat, tt=target):
                    outs = _convert.convert(pp, cc, tt)
                    (src / (Path(pp).name + ".done")).write_text("ok", encoding="utf-8")
                    return outs

                self.submit(f"convert:{target}", paths, _work, f"Hot folder → {target}…")
        except Exception:
            pass
