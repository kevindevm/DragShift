"""DragShift: Shift+drag any file to convert or edit it from a radial liquid-glass menu."""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QDir, QObject, QPointF, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QColor, QCursor, QDesktopServices, QGuiApplication, QIcon, QPainter,
                           QPixmap)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon, QWidget

from . import __version__, convert, glass, imaging, report, tools
from .radial import Item, RadialMenu
from .settings import Settings, SettingsWindow, WelcomeWindow, TRIGGERS
from .toasts import ToastStack
from .trigger import DragShiftWatcher
from .util import UserError, category, file_size, human_size, keep, release

APP_NAME = "DragShift"
TIP_URL = "https://cash.app/$AtikaKadesha"
VERSION = __version__
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
from .handoff import ipc_name
IPC_NAME = ipc_name()

GLYPHS = {"Compress": "⇲", "Metadata": "ⓘ", "Redact": "▮", "Crop": "⌗", "Edit": "☼",
          "Annotate": "✎", "Add BG": "▣", "Resize": "⤢", "Split": "✂", "Rotate": "⟳",
          "Merge": "⧉", "Protect": "⚿", "Extract": "⧈", "Tidy": "✦", "Sort": "⇅",
          "Mask": "◍", "Format": "{ }", "Minify": "–", "EOL LF": "↵", "EOL CRLF": "⏎",
          "Voice": "🎙", "Sample": "✂", "CleanTags": "🧹", "Mute": "🔇",
          "ZIP": "📦", "Hash": "#", "B64": "64", "QR": "▦", "SplitFile": "◫",
          "Join": "⛓", "Subs": "💬", "Loud": "🔊", "Trim": "✂",
          "Contact": "⊞", "GIF": "🎞", "Playlist": "🎵", "Diff": "↔", "Portfolio": "📕"}

HINTS = {
    "Compress": "Shrink file size", "Metadata": "View · remove GPS", "Redact": "Hide private info",
    "Crop": "Trim to a ratio", "Edit": "Light · colour · rotate", "Annotate": "Arrows · text · steps",
    "Add BG": "Gradient backdrop", "Resize": "Change dimensions", "Split": "One PDF per page",
    "Rotate": "Turn pages 90°", "Merge": "Join into one PDF", "Protect": "Add a password",
    "Extract": "Save embedded images",
    "Tidy": "Clean whitespace", "Sort": "Sort lines A→Z", "Mask": "Hide KEY= secrets",
    "Format": "Pretty-print JSON/XML", "Minify": "Shrink JSON/XML/CSS",
    "EOL LF": "Unix line endings", "EOL CRLF": "Windows line endings",
    "Voice": "Tiny mono MP3", "Sample": "First 30s MP3", "CleanTags": "Remove metadata",
    "Mute": "Remove audio track", "Join": "Join same format", "Subs": "Extract subtitles",
    "Loud": "Normalize loudness", "Trim": "Cut start→end",
    "ZIP": "Bundle into .zip", "Hash": "SHA-256 sidecar", "B64": "Base64 encode",
    "QR": "QR code PNG", "SplitFile": "Split 10 MB parts",
    "Contact": "Contact sheet", "GIF": "Animated GIF", "Playlist": ".m3u list",
    "Diff": "Diff 2 files → HTML", "Portfolio": "Portfolio PDF",
}
FORMAT_HINTS = {"JPG": "Small, universal", "PNG": "Lossless · transparency", "WEBP": "Smallest for web",
                "HEIC": "iPhone format", "TIFF": "Print · archival", "AVIF": "Next-gen, tiny",
                "BMP": "Uncompressed", "PDF": "Document", "ICO": "Windows icon", "GIF": "Legacy web",
                "DOCX": "Editable Word", "TXT": "Plain text", "HTML": "Web page",
                "MP3": "Audio", "WAV": "Uncompressed audio", "OGG": "Open audio",
                "OPUS": "Voice audio", "FLAC": "Lossless audio", "M4A": "Apple audio",
                "MP4": "Video", "WEBM": "Web video", "MKV": "Video container",
                "CSV": "Spreadsheet", "XLSX": "Excel"}

IMAGE_TOOLS = ["Compress", "Resize", "Crop", "Edit", "Annotate", "Redact", "Add BG", "Metadata"]
PDF_TOOLS = ["Compress", "Split", "Rotate", "Protect", "Extract", "Metadata"]
AUDIO_TOOLS = ["Voice", "Sample", "CleanTags", "Loud", "Trim"]
VIDEO_TOOLS = ["Voice", "Sample", "CleanTags", "Mute", "Subs", "Loud", "Trim"]
SUBTITLE_TOOLS = ["Shift", "Merge"]
NOTEBOOK_TOOLS = ["Strip", "Code"]
EMAIL_TOOLS = ["Attach"]
CONTACT_TOOLS = ["Merge"]
FONT_TOOLS = ["Specimen"]
PRESETS = {
    "web-small": {"tool": "Compress", "q": 70, "side": 1920, "fmt": "JPG", "strip": True},
    "voice-note": {"tool": "Voice"},
}


def text_tools_for(path: str) -> list[str]:
    """Tools ring for text/config/code files, filtered so each entry makes sense."""
    from . import texttools
    names = ["Tidy", "Sort", "EOL LF", "EOL CRLF"]
    if texttools.can_mask(path):
        names.append("Mask")
    if texttools.can_format(path):
        names.append("Format")
    if texttools.can_minify(path):
        names.append("Minify")
    return names


# ---------------------------------------------------------------- background jobs
class _Sig(QObject):
    done = Signal(object)
    failed = Signal(str)


class Job(QRunnable):
    def __init__(self, action: str, srcs: list, fn, extra: str = ""):
        super().__init__()
        self.action, self.srcs, self.fn, self.extra = action, srcs, fn, extra
        self.sig = _Sig()

    def run(self):
        try:
            outs = self.fn() or []
            self.sig.done.emit(report.summarize(self.action, self.srcs, outs, self.extra))
        except UserError as e:
            self.sig.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.sig.failed.emit(friendly_error(e))


def friendly_error(e: Exception) -> str:
    msg = str(e) or e.__class__.__name__
    low = msg.lower()
    if isinstance(e, PermissionError) or "permission denied" in low:
        return "No permission to write next to this file. Try a folder you own, or set Settings → Save results → subfolder."
    if "cannot identify image" in low:
        return "This file doesn't look like an image DragShift can read."
    if isinstance(e, FileNotFoundError):
        return "The file was moved or deleted."
    return msg


# ---------------------------------------------------------------- icon
def make_tray_icon() -> QIcon:
    """macOS menu bar wants a monochrome 'template' image; Windows gets the colour icon."""
    if not IS_MAC:
        return make_icon()
    pm = QPixmap(44, 44)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    from PySide6.QtGui import QPen
    p.setPen(QPen(QColor(0, 0, 0), 4.5))
    p.drawEllipse(QPointF(22, 22), 14, 14)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0))
    p.drawEllipse(QPointF(22, 22), 5, 5)
    for a in range(0, 360, 45):  # petal gaps
        import math
        x, y = 22 + 14 * math.cos(math.radians(a + 22.5)), 22 + 14 * math.sin(math.radians(a + 22.5))
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.drawEllipse(QPointF(x, y), 2.2, 2.2)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
    p.end()
    pm.setDevicePixelRatio(2.0)
    icon = QIcon(pm)
    icon.setIsMask(True)
    return icon


def make_icon() -> QIcon:
    ico = Path(__file__).with_name("assets") / "dragshift.ico"
    if ico.exists():
        return QIcon(str(ico))
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(glass.iridescent_pen(QPointF(32, 32), 7, 255))
    p.drawEllipse(QPointF(32, 32), 24, 24)
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------- the app
class DragShiftApp(QObject):
    def __init__(self, qapp: QApplication):
        super().__init__()
        self.qapp = qapp
        self.settings = Settings()
        self.settings.apply()
        self.pool = QThreadPool.globalInstance()
        self.windows: list[QWidget] = []
        self.toasts = ToastStack()
        self.menu = RadialMenu(self.build_rings, self.describe)
        self.menu.activated.connect(self.run_item)

        # the watcher only manages menus it opened (drag mode); click-mode menus (tray, right-click,
        # Send To) must not be closed just because no mouse button is held
        self.watcher = DragShiftWatcher(lambda: self.menu.isVisible() and not self.menu.click_mode,
                                        lambda: self.menu.got_drag, self)
        self.watcher.set_key(self.settings.get("trigger"))
        self.watcher.show_menu.connect(lambda pos: self.menu.popup(pos))
        self.watcher.toggle_ring.connect(self.menu.next_ring)
        self.watcher.hide_menu.connect(self.menu.close_menu)
        self.watcher.start()

        # files handed over by "Send to", the right-click menu, or a second launch
        self._pending: list[str] = []
        self._pending_timer = QTimer(self, singleShot=True, interval=280, timeout=self._flush_pending)
        self.server = QLocalServer(self)
        QLocalServer.removeServer(IPC_NAME)
        self.server.listen(IPC_NAME)
        self.server.newConnection.connect(self._ipc)

        self.tray = QSystemTrayIcon(make_tray_icon(), self)
        self.tray.setToolTip(f"{APP_NAME} — press {self.trigger_label()} while dragging a file")
        m = QMenu()
        m.setStyleSheet(glass.QSS)
        self.act_enabled = QAction("Enabled", m, checkable=True, checked=True)
        self.act_enabled.toggled.connect(lambda on: setattr(self.watcher, "enabled", on))
        m.addAction(self.act_enabled)
        m.addAction("Open a file…", self.open_dialog)
        m.addSeparator()
        try:
            from . import history as _history
            recent = _history.recent(8)
            if recent:
                rm = m.addMenu("Recent")
                for ts, action, outs in recent:
                    outs_list = [o for o in outs.split("\n") if o]
                    label = f"{action} · {Path(outs_list[0]).name}" if outs_list else action
                    rm.addAction(label[:60],
                                 lambda o=outs_list: self._open_recent(o))
        except Exception:
            pass
        m.addAction("Settings…", self.open_settings)
        m.addAction("How to use", self.show_welcome)
        m.addAction("Tip the developer ♥", lambda: QDesktopServices.openUrl(QUrl(TIP_URL)))
        m.addSeparator()
        m.addAction("Backup settings…", self._backup_settings)
        m.addAction("Restore settings…", self._restore_settings)
        m.addSeparator()
        m.addAction(f"Quit {APP_NAME}", self.qapp.quit)
        self.tray_menu = m
        self.tray.setContextMenu(m)
        self.tray.activated.connect(self._tray_click)
        self.tray.show()

    def trigger_label(self) -> str:
        return dict(TRIGGERS).get(self.settings.get("trigger"), "Shift")

    # ------------------------------------------------------------ IPC
    def _ipc(self):
        sock = self.server.nextPendingConnection()
        if sock is None:
            return
        buf = bytearray()
        done = {"v": False}

        def consume():
            if done["v"]:
                return
            try:
                buf.extend(bytes(sock.readAll()))
            except RuntimeError:
                pass
            try:
                data = json.loads(buf.decode("utf-8"))
            except Exception:
                return  # incomplete: wait for more
            done["v"] = True
            files = [f for f in data.get("files", []) if os.path.exists(f)]
            print(f"IPC: {len(files)} file(s) handed over", flush=True)
            if files:
                self.queue_files(files)
            elif data.get("show"):
                self.toasts.info("DragShift is already running",
                                 f"Drag any file and press {self.trigger_label()}. It lives in the tray.")
            sock.disconnectFromServer()
            sock.deleteLater()

        # Windows pipes: the sender may already be gone, so read on every signal + a fallback timer
        sock.readyRead.connect(consume)
        sock.disconnected.connect(consume)
        for ms in (0, 50, 200, 600):
            QTimer.singleShot(ms, consume)

    def queue_files(self, files: list[str]):
        """Explorer's right-click menu launches once per file: gather them, then show one menu."""
        for f in files:
            if f not in self._pending:
                self._pending.append(f)
        self._pending_timer.start()

    def _flush_pending(self):
        files, self._pending = self._pending, []
        if files:
            self.show_click_menu(files)

    # ------------------------------------------------------------ menu contents
    def describe(self, paths: list[str]) -> str:
        from .util import CONFIG
        base = f"{len(paths)} files" if len(paths) > 1 else human_size(file_size(paths[0]))
        dest = "→ DragShift/" if CONFIG.get("output") == "folder" else "→ junto al original"
        cat = category(paths[0]) if paths else None
        return f"{base} · {cat or '?'} · {dest}"

    def build_rings(self, paths: list[str]) -> dict[str, list[Item]]:
        cat = category(paths[0])
        if cat is None:
            if len(paths) >= 1:
                # universal ZIP works for anything, even unsupported mixes
                return {"Convert": [],
                        "Tools": [Item("ZIP", GLYPHS["ZIP"], key="tool:ZIP", hint=HINTS["ZIP"]),
                                  Item("Hash", GLYPHS["Hash"], key="tool:Hash", hint=HINTS["Hash"]),
                                  Item("B64", GLYPHS["B64"], key="tool:B64", hint=HINTS["B64"])]}
            return {"Unsupported": []}
        ext = Path(paths[0]).suffix
        same = [p for p in paths if category(p) == cat]
        convert_items = []
        for t in convert.targets_for(cat, ext):
            hint = FORMAT_HINTS.get(t, "")
            if cat == "image" and t == "PDF" and len(same) > 1:
                hint = f"{len(same)} images → 1 PDF"
            convert_items.append(Item(t, key=f"convert:{t}", hint=hint))
        rings: dict[str, list[Item]] = {"Convert": convert_items}
        if cat == "image":
            names = list(IMAGE_TOOLS)
            if len(same) > 1:
                names += ["Contact", "GIF"]
            rings["Tools"] = [Item(n, GLYPHS.get(n, ""), key=f"tool:{n}", hint=HINTS.get(n, ""))
                              for n in names]
        elif cat == "pdf":
            names = PDF_TOOLS[:3] + (["Merge"] if len(same) > 1 else []) + PDF_TOOLS[3:]
            rings["Tools"] = [Item(n, GLYPHS.get(n, ""), key=f"tool:{n}", hint=HINTS.get(n, ""))
                              for n in names]
        elif cat in ("text", "docx"):
            names = text_tools_for(paths[0])
            if names:
                rings["Tools"] = [Item(n, GLYPHS.get(n, ""), key=f"tool:{n}", hint=HINTS.get(n, ""))
                                  for n in names]
        elif cat == "audio":
            rings["Tools"] = [Item(n, GLYPHS.get(n, ""), key=f"tool:{n}", hint=HINTS.get(n, ""))
                              for n in AUDIO_TOOLS]
        elif cat == "video":
            rings["Tools"] = [Item(n, GLYPHS.get(n, ""), key=f"tool:{n}", hint=HINTS.get(n, ""))
                              for n in VIDEO_TOOLS]
        elif cat == "subtitle":
            rings["Tools"] = [Item(n, GLYPHS.get(n, ""), key=f"tool:{n}", hint=HINTS.get(n, "Shift ±s" if n == "Shift" else "Merge subs"))
                              for n in SUBTITLE_TOOLS]
        elif cat == "notebook":
            rings["Tools"] = [Item(n, GLYPHS.get(n, ""), key=f"tool:{n}", hint=HINTS.get(n, ""))
                              for n in NOTEBOOK_TOOLS]
        elif cat == "email":
            rings["Tools"] = [Item(n, GLYPHS.get(n, ""), key=f"tool:{n}", hint=HINTS.get(n, "Save attachments"))
                              for n in EMAIL_TOOLS]
        elif cat == "contact":
            rings["Tools"] = [Item(n, GLYPHS.get(n, ""), key=f"tool:{n}", hint=HINTS.get(n, "Merge cards"))
                              for n in CONTACT_TOOLS]
        elif cat == "font":
            rings["Tools"] = [Item(n, GLYPHS.get(n, ""), key=f"tool:{n}", hint=HINTS.get(n, "Specimen sheet"))
                              for n in FONT_TOOLS]
        # presets ring for images/audio
        if cat in ("image", "audio") and PRESETS:
            rings["Presets"] = [Item(n, "★", key=f"preset:{n}", hint="One-click preset") for n in PRESETS]
        # multi-file extras live on a second ring regardless of cat
        extras: list[Item] = []
        if len(paths) > 1 and len(same) == len(paths):
            if cat in ("image", "pdf", "text", "sheet", "presentation"):
                extras.append(Item("Portfolio", GLYPHS["Portfolio"], key="tool:Portfolio",
                                   hint=HINTS["Portfolio"]))
            if len(paths) == 2 and cat == "text":
                extras.append(Item("Diff", GLYPHS["Diff"], key="tool:Diff", hint=HINTS["Diff"]))
            if cat in ("audio", "video"):
                extras.append(Item("Playlist", GLYPHS["Playlist"], key="tool:Playlist",
                                   hint=HINTS["Playlist"]))
                if len({Path(p).suffix.lower() for p in same}) == 1:
                    extras.append(Item("Join", GLYPHS["Join"], key="tool:Join",
                                       hint=HINTS["Join"]))
        if len(paths) > 1 or cat in ("sheet", "presentation", "ebook"):
            extras += [Item("ZIP", GLYPHS["ZIP"], key="tool:ZIP", hint=HINTS["ZIP"]),
                       Item("Hash", GLYPHS["Hash"], key="tool:Hash", hint=HINTS["Hash"])]
            if cat in ("image", "audio", "video", "text") and len(paths) > 1:
                extras.append(Item("Duplicates", "⧉", key="tool:Duplicates",
                                   hint="Find duplicates"))
        if cat == "image" and len(paths) == 1:
            extras.append(Item("Palette", "🎨", key="tool:Palette", hint="Color palette"))
        if cat == "pdf":
            extras.append(Item("Outline", "🗂", key="tool:Outline", hint="Extract outline"))
        if extras:
            rings["Bundle"] = extras
        try:
            mru = self.settings.get("mru") or {}
            for ring in rings.values():
                ring.sort(key=lambda it: -int(mru.get(it.label, 0)))
        except Exception:
            pass
        return rings

    # ------------------------------------------------------------ actions
    def run_item(self, item: Item, paths: list[str]):
        cat = category(paths[0]) if paths else None
        kind, name = item.key.split(":", 1)
        try:  # most-recently-used ordering for next popup
            mru = self.settings.get("mru") or {}
            mru[name] = int(mru.get(name, 0)) + 1
            self.settings.set("mru", mru)
        except Exception:
            pass
        if kind == "preset":
            p = PRESETS.get(name, {})
            if p.get("tool") == "Compress":
                self.submit(f"preset:{name}", paths,
                            lambda: [imaging.compress_to(x, p["q"], p["side"], p["fmt"]) for p in paths],
                            f"Preset {name}…")
            elif p.get("tool") == "Voice":
                from . import mediatools
                self.submit(f"preset:{name}", paths,
                            lambda: [mediatools.audio_voice(x) for x in paths], f"Preset {name}…")
            return
        if cat is None or name in ("ZIP", "Hash", "B64", "Portfolio", "Diff", "Playlist",
                                   "Contact", "GIF", "Join", "Duplicates", "Palette",
                                   "Outline", "Folder", "QR", "SplitFile"):
            from . import filetools, multitools
            if name == "ZIP":
                all_paths = paths  # bundle the mixed selection as dropped
                pw = None
                if len(all_paths) > 1:
                    try:
                        import pyminizip  # noqa: F401
                        from PySide6.QtWidgets import QInputDialog
                        text, ok = QInputDialog.getText(None, "ZIP bundle",
                                                       "Password (empty = no password):",
                                                       echo=QInputDialog.Password)
                        if not ok:
                            return
                        pw = text or None
                    except Exception:
                        pw = None
                if pw:
                    self.submit("tool:ZIP", all_paths,
                                lambda: [filetools.zip_files(all_paths, password=pw)],
                                "Zipping…")
                else:
                    self.submit("tool:ZIP", all_paths, lambda: [filetools.zip_files(all_paths)],
                                "Zipping…")
            elif name == "Hash":
                self.submit("tool:Hash", paths, lambda: [filetools.sha256_file(p) for p in paths],
                            "Hashing…")
            elif name == "B64":
                self.submit("tool:B64", paths, lambda: [filetools.b64_encode(p) for p in paths],
                            "Encoding…")
            elif name == "Portfolio":
                self.submit("tool:Portfolio", paths, lambda: [multitools.merge_to_single_pdf(paths)],
                            "Building portfolio…")
            elif name == "Diff":
                if len(paths) >= 2:
                    self.submit("tool:Diff", paths[:2],
                                lambda: [filetools.diff_texts(paths[0], paths[1])], "Diffing…")
            elif name == "Playlist":
                self.submit("tool:Playlist", paths, lambda: [filetools.playlist_m3u(paths)],
                            "Writing playlist…")
            elif name == "Contact":
                self.submit("tool:Contact", paths, lambda: [multitools.contact_sheet(paths)],
                            "Contact sheet…")
            elif name == "GIF":
                self.submit("tool:GIF", paths, lambda: [multitools.images_to_gif(paths)],
                            "Animating…")
            elif name == "Join":
                from . import mediatools
                self.submit("tool:Join", paths, lambda: [mediatools.concat_same(paths)],
                            "Joining…")
            elif name == "Duplicates":
                self.submit("tool:Duplicates", paths, lambda: [filetools.find_duplicates(paths)],
                            "Finding duplicates…")
            elif name == "Palette":
                self.submit("tool:Palette", paths,
                            lambda: [imaging.palette(p)[1] for p in paths], "Sampling colors…")
            elif name == "Outline":
                def _outline(p: str):
                    from pathlib import Path as _P
                    from .util import sibling as _sib
                    out = _sib(p, "Outline", ".md")
                    out.write_text(imaging.pdf_outline(p), encoding="utf-8")
                    return out
                self.submit("tool:Outline", paths, lambda: [_outline(p) for p in paths],
                            "Outlining…")
            elif name == "Folder":
                self.submit("tool:Folder", paths, lambda: [filetools.folder_report(paths[0])],
                            "Scanning folder…")
            elif name == "QR":
                self.submit("tool:QR", paths, lambda: [filetools.qr_of_text(p) for p in paths],
                            "QR…")
            elif name == "SplitFile":
                self.submit("tool:SplitFile", paths,
                            lambda: [o for p in paths for o in filetools.split_file(p)], "Splitting…")
            return
        paths = [p for p in paths if category(p) == cat]
        kind, name = item.key.split(":", 1)
        if kind == "convert":
            if cat == "image" and name == "PDF" and len(paths) > 1:
                self.submit(f"convert:{name}", paths, lambda: convert.images_to_single_pdf(paths),
                            f"Combining {len(paths)} images…")
            else:
                verb = f"Converting to {name}…"
                self.submit(f"convert:{name}", paths,
                            lambda: [o for p in paths for o in convert.convert(p, cat, name)], verb)
            return
        if cat == "pdf":
            if name == "Merge":
                self.submit("tool:Merge", paths, lambda: [imaging.merge_pdfs(paths)], "Merging…")
            elif name == "Metadata":
                self.open_window(tools.MetadataWindow(paths[0], self.notify, is_pdf=True))
            elif name == "Protect":
                self.open_window(tools.ProtectWindow(paths[0], self.notify))
            else:
                fns = {"Compress": lambda p: [imaging.compress_pdf(p)], "Split": imaging.split_pdf,
                       "Rotate": lambda p: [imaging.rotate_pdf(p)], "Extract": imaging.extract_pdf_images}
                f = fns[name]
                self.submit(f"tool:{name}", paths, lambda: [o for p in paths for o in f(p)],
                            {"Compress": "Compressing…", "Split": "Splitting…", "Rotate": "Rotating…",
                             "Extract": "Extracting images…"}[name])
            return
        if cat in ("text", "docx"):
            from . import texttools
            fns = {
                "Tidy": texttools.tidy_text,
                "Sort": texttools.sort_text,
                "Mask": texttools.mask_secrets,
                "Format": texttools.format_text,
                "Minify": texttools.minify_text,
                "EOL LF": lambda p: texttools.convert_eol(p, False),
                "EOL CRLF": lambda p: texttools.convert_eol(p, True),
            }
            if name in fns:
                f = fns[name]
                self.submit(f"tool:{name}", paths, lambda: [f(p) for p in paths],
                            {"Tidy": "Tidying…", "Sort": "Sorting…", "Mask": "Masking secrets…",
                             "Format": "Formatting…", "Minify": "Minifying…",
                             "EOL LF": "Converting line endings…",
                             "EOL CRLF": "Converting line endings…"}.get(name, "Working…"))
                return
        if cat in ("audio", "video"):
            from . import mediatools
            if name in ("Voice", "Sample", "CleanTags", "Mute", "Subs", "Loud", "Trim", "Join"):
                if name == "Voice":
                    self.submit("tool:Voice", paths,
                                lambda: [mediatools.audio_voice(p) for p in paths], "Compressing voice…")
                elif name == "Sample":
                    self.submit("tool:Sample", paths,
                                lambda: [mediatools.audio_sample(p) for p in paths], "Sampling…")
                elif name == "CleanTags":
                    self.submit("tool:CleanTags", paths,
                                lambda: [mediatools.strip_media_tags(p) for p in paths], "Cleaning…")
                elif name == "Mute":
                    self.submit("tool:Mute", paths,
                                lambda: [mediatools.video_mute(p) for p in paths], "Muting…")
                elif name == "Subs":
                    self.submit("tool:Subs", paths,
                                lambda: [mediatools.extract_subs(p) for p in paths], "Extracting subs…")
                elif name == "Loud":
                    self.submit("tool:Loud", paths,
                                lambda: [mediatools.loudnorm(p) for p in paths], "Normalizing…")
                elif name == "Trim":
                    try:
                        from PySide6.QtWidgets import QInputDialog
                        text, ok = QInputDialog.getText(None, "Trim media",
                                                       "Start-End seconds (e.g. 5-20):")
                        if not ok or "-" not in text:
                            return
                        a, b = text.split("-", 1)
                        s, e = float(a.strip()), float(b.strip())
                    except Exception:
                        self.toasts.error("Trim", "Use format start-end, e.g. 5-20.")
                        return
                    self.submit("tool:Trim", paths,
                                lambda: [mediatools.trim_media(p, s, e) for p in paths], "Trimming…")
                elif name == "Join":
                    self.submit("tool:Join", paths, lambda: [mediatools.concat_same(paths)],
                                "Joining…")
                return
        if cat == "sheet" and name in ("ZIP", "Hash"):
            from . import filetools
            if name == "ZIP":
                self.submit("tool:ZIP", paths, lambda: [filetools.zip_files(paths)], "Zipping…")
            else:
                self.submit("tool:Hash", paths, lambda: [filetools.sha256_file(p) for p in paths],
                            "Hashing…")
            return
        if cat == "subtitle":
            from . import texttools
            if name == "Shift":
                try:
                    from PySide6.QtWidgets import QInputDialog
                    text, ok = QInputDialog.getText(None, "Shift subtitles",
                                                   "Seconds (+/-), e.g. 1.5 or -2:")
                    if not ok:
                        return
                    secs = float(text.strip())
                except Exception:
                    self.toasts.error("Shift", "Use a number like 1.5 or -2.")
                    return
                self.submit("tool:Shift", paths,
                            lambda: [texttools.subtitles_shift(p, secs) for p in paths], "Shifting…")
            elif name == "Merge":
                self.submit("tool:Merge", paths, lambda: [texttools.subtitles_merge(paths)],
                            "Merging subs…")
            return
        if cat == "notebook":
            from . import nbtools
            if name == "Strip":
                self.submit("tool:Strip", paths, lambda: [nbtools.ipynb_strip(p) for p in paths],
                            "Stripping outputs…")
            elif name == "Code":
                self.submit("tool:Code", paths,
                            lambda: [o for p in paths for o in nbtools.ipynb_to_py(p)], "Extracting code…")
            return
        if cat == "email":
            from . import nbtools
            if name == "Attach":
                self.submit("tool:Attach", paths,
                            lambda: [o for p in paths for o in nbtools.eml_attachments(p)],
                            "Extracting…")
            return
        if cat == "contact":
            from . import nbtools
            if name == "Merge":
                self.submit("tool:Merge", paths, lambda: [nbtools.contact_merge(paths)], "Merging…")
            return
        if cat == "font":
            from . import nbtools
            if name == "Specimen":
                self.submit("tool:Specimen", paths,
                            lambda: [o for p in paths for o in nbtools.font_specimen(p)], "Rendering…")
            return
        windows = {"Crop": tools.CropWindow, "Add BG": tools.AddBgWindow, "Annotate": tools.AnnotateWindow,
                   "Redact": tools.RedactWindow, "Edit": tools.EditWindow, "Metadata": tools.MetadataWindow}
        try:
            if name == "Compress":
                self.open_window(tools.CompressWindow(paths, self.notify))
            elif name == "Resize":
                self.open_window(tools.ResizeWindow(paths, self.notify))
            else:
                self.open_window(windows[name](paths[0], self.notify))
        except UserError as e:
            self.toasts.error(f"Couldn't open {name}", str(e))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.toasts.error(f"Couldn't open {name}", friendly_error(e))

    def open_window(self, w: QWidget):
        if hasattr(w, "submit"):
            w.submit = self.submit
        self.windows.append(w)
        w.destroyed.connect(lambda *_: self.windows.remove(w) if w in self.windows else None)
        if hasattr(w, "present"):
            w.present()
        else:
            w.show()

    def submit(self, action: str, srcs: list, fn, working: str = "Working…", extra: str = ""):
        """Run in the background. A spinner card appears only if it takes > 150 ms,
        with an elapsed-seconds ticker for long jobs (ffmpeg etc)."""
        state = {"card": None, "finished": False, "t0": None, "ticker": None}
        names = Path(srcs[0]).name if len(srcs) == 1 else f"{len(srcs)} files"

        def show_spinner():
            if not state["finished"]:
                import time as _t
                state["card"] = self.toasts.new()
                state["card"].working(working, names)
                state["t0"] = _t.monotonic()
                tick = QTimer(state["card"])
                tick.setInterval(1000)
                def _tick():
                    if state["finished"] or state["card"] is None:
                        tick.stop()
                        return
                    try:
                        state["card"].progress(int(_t.monotonic() - state["t0"]))
                    except Exception:
                        pass
                tick.timeout.connect(_tick)
                tick.start()
                state["ticker"] = tick
                state["card"]._ticker = tick

        QTimer.singleShot(150, show_spinner)
        job = Job(action, srcs, fn, extra)

        def done(r):
            release(job)
            state["finished"] = True
            try:
                from . import history
                history.log(action, [str(s) for s in srcs], [str(o) for o in r.outs])
            except Exception:
                pass
            card = state["card"] or self.toasts.new()
            card.done(r)

        def failed(msg):
            release(job)
            state["finished"] = True
            card = state["card"] or self.toasts.new()
            card.error("Couldn't finish", msg)

        job.sig.done.connect(done)
        job.sig.failed.connect(failed)
        self.pool.start(keep(job))

    def notify(self, action: str, srcs: list, outs: list, extra: str = ""):
        """Called by tool windows after they save."""
        self.toasts.new().done(report.summarize(action, srcs, outs, extra))

    # ------------------------------------------------------------ misc
    def _tray_click(self, reason):
        # macOS: a click on the menu-bar icon shows the menu; Windows: click opens a file
        if not IS_MAC and reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
            self.open_dialog()

    def open_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(None, "Choose file(s) for DragShift", QDir.homePath())
        if files:
            self.show_click_menu(files)

    def show_click_menu(self, files: list[str]):
        g = (QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()).availableGeometry()
        pos = QCursor.pos() if g.contains(QCursor.pos()) else g.center()
        self.menu.popup(pos, files)
        self.menu.activateWindow()

    def open_settings(self):
        w = SettingsWindow(self.settings)
        w.changed.connect(self._settings_changed)
        self.open_window(w)

    def _backup_settings(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(None, "Backup DragShift settings", "dragshift-settings.json",
                                              "JSON (*.json)")
        if path:
            try:
                SettingsWindow(self.settings).export(path)
                self.toasts.info("Settings", f"Backed up to {Path(path).name}")
            except Exception as e:
                self.toasts.error("Settings", str(e))

    def _restore_settings(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(None, "Restore DragShift settings", "",
                                              "JSON (*.json)")
        if path:
            try:
                SettingsWindow(self.settings).import_(path)
                self._settings_changed()
                self.toasts.info("Settings", "Restored.")
            except Exception as e:
                self.toasts.error("Settings", str(e))

    def _open_recent(self, outs: list[str]):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        for o in outs:
            if os.path.exists(o):
                QDesktopServices.openUrl(QUrl.fromLocalFile(o))
                return
        self.toasts.error("Recent", "That file was moved or deleted.")

    def _settings_changed(self):
        self.watcher.set_key(self.settings.get("trigger"))
        self.tray.setToolTip(f"{APP_NAME} — press {self.trigger_label()} while dragging a file")

    def show_welcome(self):
        self.open_window(WelcomeWindow(self.settings, self.trigger_label()))


class DragShiftQApplication(QApplication):
    """macOS delivers files from Finder's "Open With", the Dock and `open -a` as FileOpen
    events (not argv)."""
    file_opened = Signal(str)

    def __init__(self, argv):
        super().__init__(argv)
        self.early_files: list[str] = []

    def event(self, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.FileOpen:
            f = e.file()
            if f:
                self.early_files.append(f)
                self.file_opened.emit(f)
            return True
        return super().event(e)


def mac_setup(qapp):
    from PySide6.QtGui import QFont
    for fam in ("Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI"):
        QFont.insertSubstitutions(fam, [".AppleSystemUIFont", "SF Pro Display", "Helvetica Neue"])
    try:
        from . import platform_mac
        platform_mac.become_accessory()
    except Exception:
        pass


def send_to_running(payload: dict) -> bool:
    s = QLocalSocket()
    s.connectToServer(IPC_NAME)
    if not s.waitForConnected(300):
        return False
    s.write(json.dumps(payload).encode("utf-8"))
    s.flush()
    s.waitForBytesWritten(500)
    s.disconnectFromServer()
    return True


def setup_logging():
    """Errors go to %LOCALAPPDATA%\\DragShift\\log.txt (pythonw / the .exe have no console)."""
    import faulthandler
    if IS_MAC:
        base = Path.home() / "Library" / "Logs" / "DragShift"
    else:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "DragShift"
    base.mkdir(parents=True, exist_ok=True)
    path = base / "log.txt"
    if path.exists() and path.stat().st_size > 1_000_000:
        path.replace(base / "log.old.txt")
    f = open(path, "a", encoding="utf-8", buffering=1)
    f.write(f"\n==== DragShift {VERSION} started {time.strftime('%Y-%m-%d %H:%M:%S')} ====\n")
    if sys.stderr is None or getattr(sys, "frozen", False) or sys.executable.lower().endswith("pythonw.exe"):
        sys.stdout = sys.stderr = f
    faulthandler.enable(f)

    def hook(t, v, tb):
        f.write("Unhandled: " + "".join(traceback.format_exception(t, v, tb)))
    sys.excepthook = hook
    return path


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    try:
        setup_logging()
    except Exception:
        pass
    if IS_WIN:
        try:  # crisp taskbar/tray icon grouping
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DragShift.App")
        except Exception:
            pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = DragShiftQApplication(argv)
    if IS_MAC:
        mac_setup(qapp)
    qapp.setApplicationName(APP_NAME)
    qapp.setApplicationVersion(VERSION)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setWindowIcon(make_icon())

    if "--selftest" in argv:
        return selftest()
    # headless scripting: DragShift.exe *.png --convert-to JPG [--out-dir DIR] [--tool tool:Hash]
    #   --preset web-small | --dry-run | --export-set s.json | --import-set s.json
    if "--no-ui" in argv or "--convert-to" in argv or "--tool" in argv or "--preset" in argv \
            or "--export-set" in argv or "--import-set" in argv or "--dry-run" in argv:
        try:
            from .settings import Settings as _Set
            if "--export-set" in argv:
                _Set().export(argv[argv.index("--export-set") + 1])
                print("OK settings exported")
                return 0
            if "--import-set" in argv:
                _Set().import_(argv[argv.index("--import-set") + 1])
                print("OK settings imported")
                return 0
            dry = "--dry-run" in argv
            vals = {"--out-dir", "--convert-to", "--tool", "--preset"}
            taken = set()
            for _flag in vals:
                if _flag in argv:
                    taken.add(argv[argv.index(_flag) + 1])
            out_dir = argv[argv.index("--out-dir") + 1] if "--out-dir" in argv else None
            conv = argv[argv.index("--convert-to") + 1].upper() if "--convert-to" in argv else None
            tool = argv[argv.index("--tool") + 1] if "--tool" in argv else None
            preset = argv[argv.index("--preset") + 1] if "--preset" in argv else None
            files = [os.path.abspath(a) for a in argv[1:]
                     if a not in taken and not a.startswith("--") and os.path.exists(a)]
            from .util import category as _cat, sibling as _sib
            if preset:
                from .app import PRESETS as _P
                if preset not in _P:
                    print(f"ERROR: unknown preset {preset} (web-small, voice-note)")
                    return 2
                if dry or "--no-ui" in argv:
                    for f in files:
                        if dry:
                            print(f"WOULD preset:{preset} {f}")
                            continue
                        c = _cat(f)
                        if c == "image":
                            from . import imaging
                            p = _P[preset]
                            o = imaging.compress_to(f, p["q"], p["side"], p["fmt"]) if p.get("tool") == "Compress" else None
                            print(f"OK {f} -> {o}")
                        elif c in ("audio", "video"):
                            from . import mediatools
                            print(f"OK {f} -> {mediatools.audio_voice(f)}")
                    return 0
            if dry and (conv or tool or preset):
                for f in files:
                    print(f"WOULD {conv or tool or 'preset:' + str(preset)} {f} -> {str(_sib(f, 'Preview'))}")
                return 0
            if conv:
                for f in files:
                    c = _cat(f)
                    if c is None:
                        print(f"SKIP {f}: unsupported"); continue
                    outs = convert.convert(f, c, conv)
                    print(f"OK {f} -> {', '.join(str(o) for o in outs)}")
                return 0
            if tool:
                _, _, tname = tool.partition(":")
                from . import filetools
                outs = {"ZIP": lambda: filetools.zip_files(files),
                        "Hash": lambda: [filetools.sha256_file(p) for p in files]}.get(tname, lambda: (_ for _ in ()).throw(
                    ValueError(f"Unknown tool {tool}")))()
                print(f"OK -> {', '.join(str(o) for o in outs)}")
                return 0
        except Exception as e:
            print(f"ERROR: {e}")
            return 2
    files = [os.path.abspath(a) for a in argv[1:] if not a.startswith("-") and os.path.exists(a)]
    # already running? hand over and exit (instant: no second UI start-up)
    if send_to_running({"files": files} if files else {"show": "--quiet" not in argv}):
        return 0
    app = DragShiftApp(qapp)
    qapp.file_opened.connect(lambda f: app.queue_files([f]))
    if qapp.early_files:
        app.queue_files(list(qapp.early_files))
    if files:  # e.g. "Send to → DragShift" or drag onto the .exe
        QTimer.singleShot(120, lambda: app.queue_files(files))
    elif not app.settings.get("welcomed"):
        QTimer.singleShot(300, app.show_welcome)
    elif "--quiet" not in argv:
        QTimer.singleShot(400, lambda: app.toasts.info(
            "DragShift is running", f"Drag any file, then press {app.trigger_label()}."))
    return qapp.exec()


def selftest() -> int:
    """Used by CI on the frozen .exe: exercise every library and build the UI, then exit."""
    import tempfile
    from PIL import Image
    try:
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "t.png"
            Image.new("RGBA", (64, 48), (255, 100, 80, 255)).save(src)
            for t in convert.targets_for("image", ".png"):
                convert.convert(src, "image", t)
            pdf = convert.convert(src, "image", "PDF")[0]
            for t in convert.PDF_TARGETS:
                convert.convert(pdf, "pdf", t)
            (Path(d) / "n.txt").write_text("hello")
            docx = convert.convert(Path(d) / "n.txt", "text", "DOCX")[0]
            convert.convert(docx, "docx", "TXT")
            for t in convert.TEXT_TARGETS:
                convert.convert(Path(d) / "n.txt", "text", t)
            env = Path(d) / ".env"
            env.write_text("KEY=secret\nDEBUG=1  \n")
            assert category(str(env)) == "text"
            from . import texttools, filetools, multitools
            texttools.tidy_text(env)
            texttools.sort_text(env)
            texttools.mask_secrets(env)
            texttools.convert_eol(env, False)
            j = Path(d) / "c.json"
            j.write_text('{"b":1,"a":2}')
            texttools.format_text(j)
            texttools.minify_text(j)
            filetools.zip_files([str(env), str(j)])
            filetools.sha256_file(env)
            filetools.b64_encode(env)
            filetools.playlist_m3u([str(env), str(j)])
            filetools.diff_texts(env, j)
            multitools.contact_sheet([str(src), str(src)])
            multitools.images_to_gif([str(src), str(src)])
            # sheet: csv -> xlsx -> csv/html
            csvp = Path(d) / "t.csv"
            csvp.write_text("a,b\n1,2\n")
            xlsx = convert.convert(csvp, "sheet", "XLSX")[0]
            convert.convert(xlsx, "sheet", "CSV")
            # yaml -> json
            yp = Path(d) / "t.yaml"
            yp.write_text("a: 1\n")
            from . import sheettools
            sheettools.yaml_to_json(yp)
            # sqlite -> csv
            import sqlite3
            dbp = Path(d) / "t.db"
            con = sqlite3.connect(dbp)
            con.execute("CREATE TABLE t(a,b)")
            con.execute("INSERT INTO t VALUES (1,2)")
            con.commit()
            con.close()
            assert category(str(dbp)) == "sheet"
            convert.convert(dbp, "sheet", "CSV")
            from . import mediatools
            mediatools._ffmpeg()  # fail-fast if the engine didn't bundle
            big = Path(d) / "big.bin"
            big.write_bytes(b"x" * 100)
            parts = filetools.split_file(big, part_size=30)
            assert len(parts) >= 3 and parts[0].suffix == ".part001"
            assert filetools.join_parts(parts).read_bytes() == b"x" * 100
            enc = filetools.encrypt_file(env, "pw123")
            assert filetools.decrypt_file(enc, "pw123").read_bytes() == env.read_bytes()
            filetools.qr_of_text(env)
            filetools.b64_decode(filetools.b64_encode(env))
            # new cats quick check
            srt = Path(d) / "s.srt"
            srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHi\n")
            convert.convert(srt, "subtitle", "VTT")
            nb = Path(d) / "n.ipynb"
            nb.write_text('{"cells": [], "nbformat": 4, "nbformat_minor": 5}')
            convert.convert(nb, "notebook", "PY")
            em = Path(d) / "m.eml"
            em.write_text("From: a@b.c\nSubject: hi\nContent-Type: text/plain\n\nbody\n")
            convert.convert(em, "email", "TXT")
            try:
                from pptx import Presentation
                prs = Presentation()
                prs.slides.add_slide(prs.slide_layouts[6])
                pptx_p = Path(d) / "s.pptx"
                prs.save(pptx_p)
                assert category(str(pptx_p)) == "presentation"
                convert.convert(pptx_p, "presentation", "TXT")
            except Exception as e:
                raise e
            imaging.add_background(convert.open_image(src), imaging.Background())
            imaging.compress_pdf(pdf)
            imaging.protect_pdf(pdf, "pw")
            from . import liquid
            liquid.render(Image.new("RGB", (80, 80)), liquid.sdf_circle(80, 80, 40, 40, 30))
            menu = RadialMenu(lambda p: {"Convert": [Item("PNG")]}, lambda p: "1 KB")
            menu._load([str(src)])
            n = lambda *a, **k: None
            for w in (tools.CropWindow(str(src), n), tools.AddBgWindow(str(src), n), tools.EditWindow(str(src), n),
                      tools.AnnotateWindow(str(src), n), tools.RedactWindow(str(src), n),
                      tools.MetadataWindow(str(src), n), tools.CompressWindow([str(src)], n),
                      tools.ResizeWindow([str(src)], n), tools.ProtectWindow(str(pdf), n)):
                w.close()
            ToastStack().info("ok", "ok").dismiss()
        print("SELFTEST OK")
        return 0
    except Exception:
        traceback.print_exc()
        print("SELFTEST FAILED")
        return 1
