"""Persistent settings + the Settings and Welcome windows."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSlider, QVBoxLayout)

from . import __version__
from .util import CONFIG
from .window import GlassWindow

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
APP = "DragShift"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

DEFAULTS = {
    "output": "next",
    "jpg_quality": 90,
    "pdf_dpi": 200,
    "audio_bitrate": "192k",
    "video_crf": 23,
    "thumb_sec": 1,
    "toast_ms": 6500,
    "hub_ms": 420,
    "high_contrast": False,
    "font_scale": 100,
    "bg_mode": "solid",
    "update_check": False,
    "last_update_check": "",
    "hot_enable": False,
    "hot_src": "",
    "hot_to": "PDF",
    "lang": "es",
    "trigger": "shift",
    "welcomed": False,
}


class Settings:
    def __init__(self):
        self.q = QSettings(APP, APP)

    def get(self, key):
        v = self.q.value(key, DEFAULTS[key])
        d = DEFAULTS[key]
        if isinstance(d, bool):
            return v in (True, "true", "1", 1)
        if isinstance(d, int):
            try:
                return int(v)
            except (TypeError, ValueError):
                return d
        return v

    def set(self, key, value):
        self.q.setValue(key, value)
        self.apply()

    def apply(self):
        for k in ("output", "jpg_quality", "pdf_dpi", "audio_bitrate", "video_crf", "thumb_sec",
                  "toast_ms", "hub_ms", "high_contrast", "font_scale", "bg_mode",
                  "hot_enable", "hot_src", "hot_to", "update_check", "last_update_check",
                  "lang"):
            CONFIG[k] = self.get(k)


# ---------------------------------------------------------------- autostart (Windows)
def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --quiet'
    return f'"{sys.executable}" -m dragshift --quiet'


def autostart_enabled() -> bool:
    if IS_LINUX:
        from . import platform_linux
        return platform_linux.autostart_enabled()
    if IS_MAC:
        from . import platform_mac
        return platform_mac.autostart_enabled()
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP)
            return True
    except OSError:
        return False


def set_autostart(on: bool):
    if IS_LINUX:
        from . import platform_linux
        platform_linux.set_autostart(on)
        return
    if IS_MAC:
        from . import platform_mac
        platform_mac.set_autostart(on)
        return
    if not IS_WIN:
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, APP)
            except OSError:
                pass


TRIGGERS = ([("shift", "Shift ⇧"), ("ctrl", "Control ⌃"), ("alt", "Option ⌥")] if IS_MAC
            else [("shift", "Shift"), ("ctrl", "Ctrl"), ("alt", "Alt")])
OUTPUTS = [("next", "Next to the original"), ("folder", "In a “DragShift” subfolder")]
DPIS = [(150, "150 dpi · small"), (200, "200 dpi · balanced"), (300, "300 dpi · print")]
LANGS = [("es", "Español"), ("en", "English")]


def _t(options):
    from .i18n import tr as _tr
    return [(v, _tr(l)) for v, l in options]


class SettingsWindow(GlassWindow):
    changed = Signal()

    def __init__(self, settings: Settings):
        from .i18n import tr
        super().__init__(tr("Settings"), size=(520, 500))
        self.s = settings
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        r = 0

        def combo(options, current):
            c = QComboBox()
            for v, label in options:
                c.addItem(label, v)
            idx = max(0, [v for v, _ in options].index(current) if current in [v for v, _ in options] else 0)
            c.setCurrentIndex(idx)
            return c

        grid.addWidget(QLabel(tr("Language")), r, 0)
        self.lang = combo(LANGS, self.s.get("lang"))
        self.lang.currentIndexChanged.connect(lambda _: self._save("lang", self.lang.currentData()))
        grid.addWidget(self.lang, r, 1)
        r += 1

        grid.addWidget(QLabel(tr("Open the menu with")), r, 0)
        self.trigger = combo(TRIGGERS, self.s.get("trigger"))
        self.trigger.currentIndexChanged.connect(lambda _: self._save("trigger", self.trigger.currentData()))
        grid.addWidget(self.trigger, r, 1)
        r += 1
        hint = QLabel(tr("…pressed while you’re dragging a file"))
        hint.setObjectName("dim")
        grid.addWidget(hint, r, 1)
        r += 1

        grid.addWidget(QLabel(tr("Save results")), r, 0)
        self.output = combo(_t(OUTPUTS), self.s.get("output"))
        self.output.currentIndexChanged.connect(lambda _: self._save("output", self.output.currentData()))
        grid.addWidget(self.output, r, 1)
        r += 1

        grid.addWidget(QLabel(tr("JPG / WebP quality")), r, 0)
        row = QHBoxLayout()
        self.q = QSlider(Qt.Horizontal)
        self.q.setRange(60, 100)
        self.q.setValue(self.s.get("jpg_quality"))
        self.qv = QLabel(str(self.q.value()))
        self.qv.setObjectName("dim")
        self.qv.setFixedWidth(30)
        self.q.valueChanged.connect(lambda v: (self.qv.setText(str(v)), self._save("jpg_quality", v)))
        row.addWidget(self.q)
        row.addWidget(self.qv)
        grid.addLayout(row, r, 1)
        r += 1

        grid.addWidget(QLabel(tr("PDF → image resolution")), r, 0)
        self.dpi = combo(_t(DPIS), self.s.get("pdf_dpi"))
        self.dpi.currentIndexChanged.connect(lambda _: self._save("pdf_dpi", self.dpi.currentData()))
        grid.addWidget(self.dpi, r, 1)
        r += 1

        grid.addWidget(QLabel(tr("Toast duration")), r, 0)
        self.toast = combo([(4000, "4 s"), (6500, "6.5 s"), (10000, "10 s")], self.s.get("toast_ms"))
        self.toast.currentIndexChanged.connect(lambda _: self._save("toast_ms", self.toast.currentData()))
        grid.addWidget(self.toast, r, 1)
        r += 1

        grid.addWidget(QLabel(tr("Hub ring delay")), r, 0)
        self.hub = combo([(250, tr("Fast")), (420, tr("Default")), (700, tr("Slow"))], self.s.get("hub_ms"))
        self.hub.currentIndexChanged.connect(lambda _: self._save("hub_ms", self.hub.currentData()))
        grid.addWidget(self.hub, r, 1)
        r += 1

        self.hc = QCheckBox(tr("High contrast menu text"))
        self.hc.setChecked(bool(self.s.get("high_contrast")))
        self.hc.toggled.connect(lambda v: self._save("high_contrast", bool(v)))
        grid.addWidget(self.hc, r, 1)
        r += 1

        grid.addWidget(QLabel(tr("Menu text size")), r, 0)
        self.fs = combo([(90, tr("Small")), (100, tr("Default")), (120, tr("Large"))], self.s.get("font_scale"))
        self.fs.currentIndexChanged.connect(lambda _: self._save("font_scale", self.fs.currentData()))
        grid.addWidget(self.fs, r, 1)
        r += 1

        grid.addWidget(QLabel(tr("Background removal")), r, 0)
        try:
            from . import bgremove as _bg
            _st, _msg = _bg.ai_status()
            _ai_label = tr("AI u2net (ready ✓)") if _st == "ready" else tr("AI u2net (auto-downloads once)")
        except Exception:
            _ai_label = tr("AI u2net (auto-downloads once)")
        self.bgm = combo([("solid", tr("Solid (instant)")), ("ai", _ai_label)],
                         self.s.get("bg_mode"))
        self.bgm.currentIndexChanged.connect(lambda _: self._save("bg_mode", self.bgm.currentData()))
        grid.addWidget(self.bgm, r, 1)
        r += 1

        grid.addWidget(QLabel(tr("Watch folder")), r, 0)
        wrow = QHBoxLayout()
        self.hot = QCheckBox(tr("Auto-convert new files"))
        self.hot.setChecked(bool(self.s.get("hot_enable")))
        self.hot.toggled.connect(lambda v: self._save("hot_enable", bool(v)))
        wrow.addWidget(self.hot)
        self.hot_src = QLineEdit(str(self.s.get("hot_src") or ""))
        self.hot_src.setPlaceholderText(r"C:\Watch or ~/Watch")
        self.hot_src.editingFinished.connect(lambda: self._save("hot_src", self.hot_src.text()))
        wrow.addWidget(self.hot_src, 1)
        self.hot_to = combo([("PDF", "→ PDF"), ("PNG", "→ PNG"), ("JPG", "→ JPG"), ("TXT", "→ TXT"),
                             ("MP3", "→ MP3"), ("ZIP", "→ ZIP")], self.s.get("hot_to"))
        self.hot_to.currentIndexChanged.connect(lambda _: self._save("hot_to", self.hot_to.currentData()))
        wrow.addWidget(self.hot_to)
        grid.addLayout(wrow, r, 1)
        r += 1

        opt_btn = QPushButton(tr("Opcionales: motores descargables…"))
        opt_btn.setToolTip("FFmpeg, IA, Pandoc, LibreOffice: estado, instalar, quitar")
        opt_btn.clicked.connect(lambda: self._open_engines())
        grid.addWidget(opt_btn, r, 1)
        r += 1

        self.upd = QCheckBox(tr("Check for updates daily (GitHub)"))
        self.upd.setChecked(bool(self.s.get("update_check")))
        self.upd.toggled.connect(lambda v: self._save("update_check", bool(v)))
        grid.addWidget(self.upd, r, 1)
        r += 1

        if IS_WIN or IS_MAC or IS_LINUX:
            self.auto = QCheckBox(tr("Start DragShift with Windows") if IS_WIN else tr("Open DragShift at login"))
            self.auto.setChecked(autostart_enabled())
            self.auto.toggled.connect(set_autostart)
            grid.addWidget(self.auto, r, 1)
            r += 1
        if IS_MAC:
            from . import platform_mac
            if not platform_mac.has_screen_recording():
                glass_btn = QPushButton(tr("Enable full liquid glass…"))
                glass_btn.setToolTip(tr("Lets the glass refract the windows behind it (Screen Recording permission)"))
                glass_btn.clicked.connect(platform_mac.request_screen_recording)
                grid.addWidget(glass_btn, r, 1)
                r += 1
        self.body.addLayout(grid)
        self.body.addStretch(1)
        about = QLabel(f"DragShift {__version__}  ·  {tr('originals are never modified')}")
        about.setObjectName("dim")
        foot = QHBoxLayout()
        foot.addWidget(about)
        foot.addStretch(1)
        done = QPushButton(tr("Done"))
        done.setObjectName("primary")
        done.clicked.connect(self.close)
        foot.addWidget(done)
        self.body.addLayout(foot)

    def _open_engines(self):
        win = getattr(self, "_engines_win", None)
        if win is None:
            win = EnginesWindow()
            self._engines_win = win
        win.show()
        win.raise_()
        win.activateWindow()

    def _save(self, key, value):
        self.s.set(key, value)
        self.changed.emit()

    def export(self, path):
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump({k: self.s.get(k) for k in DEFAULTS}, f, indent=2, ensure_ascii=False)

    def import_(self, path):
        import json
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for k, v in data.items():
            if k in DEFAULTS:
                self.s.set(k, v)
        self.apply()


class EnginesWindow(GlassWindow):
    """Opcionales: estado e instalación de motores descargables (estilo Filee)."""
    def __init__(self):
        super().__init__("Motores opcionales", size=(620, 460))
        from . import engines as _eng
        self._eng = _eng
        self._rows: dict = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        r = 0
        for e in _eng.registry():
            try:
                state, detail = _eng.status(e)
            except Exception:
                state, detail = "missing", ""
            name = QLabel(f"<b>{e.name}</b> <i>({e.kind}, {e.size})</i>")
            name.setWordWrap(True)
            grid.addWidget(name, r, 0)
            from .i18n import tr as _tr
            st = QLabel(_tr("✓ listo") if state == "ready" else _tr("○ no instalado"))
            st.setObjectName("dim" if state != "ready" else "good")
            grid.addWidget(st, r, 1)
            r += 1
            info = QLabel((e.desc + " " + (detail or e.note or "")).strip())
            info.setObjectName("dim")
            info.setWordWrap(True)
            grid.addWidget(info, r, 0, 1, 2)
            self._rows[e.id] = (st, info)
            r += 1
            row = QHBoxLayout()
            from .i18n import tr as _tr2
            if e.id == "pandoc":
                b = QPushButton(_tr2("Descargar e instalar"))
                b.clicked.connect(lambda _=False, b=b: self._install_pandoc(b))
                row.addWidget(b)
            elif e.id == "ai-bg":
                b = QPushButton(_tr2("Descargar modelo IA (~176 MB)"))
                b.clicked.connect(lambda _=False, b=b: self._install_ai(b))
                row.addWidget(b)
            elif e.id == "libreoffice":
                b = QPushButton(_tr2("Descargar e instalar (~400 MB)"))
                b.clicked.connect(lambda _=False, b=b: self._install_lo(b))
                row.addWidget(b)
                b3 = QPushButton(_tr2("Ya lo tengo…"))
                b3.clicked.connect(self._locate_lo)
                row.addWidget(b3)
            row.addStretch(1)
            if e.id in ("pandoc", "ai-bg", "libreoffice"):
                grid.addLayout(row, r, 0, 1, 2)
                r += 1
            grid.addWidget(QLabel(""), r, 0)
            r += 1
        self.body.addLayout(grid)
        self.body.addStretch(1)
        foot = QHBoxLayout()
        foot.addStretch(1)
        from .i18n import tr as _trf
        done = QPushButton(_trf("Cerrar"))
        done.setObjectName("primary")
        done.clicked.connect(self.close)
        foot.addWidget(done)
        self.body.addLayout(foot)

    def _refresh_row(self, eid: str):
        try:
            from . import engines as _eng
            for e in _eng.registry():
                if e.id == eid and eid in self._rows:
                    state, detail = _eng.status(e)
                    from .i18n import tr as _tr4
                    st, info = self._rows[eid]
                    st.setText(_tr4("✓ listo") if state == "ready" else _tr4("○ no instalado"))
                    st.setObjectName("dim" if state != "ready" else "good")
                    st.style().unpolish(st)
                    st.style().polish(st)
                    info.setText((e.desc + " " + (detail or e.note or "")).strip())
        except Exception:
            pass

    def _install_pandoc(self, btn):
        from .i18n import tr as _tr
        btn.setEnabled(False)
        btn.setText(_tr("Descargando…"))
        try:
            from . import engines as _eng
            import urllib.request
            import zipfile
            import tarfile
            import shutil
            url = (_eng.PANDOC_URLS.get("win32" if sys.platform == "win32"
                                        else "darwin" if sys.platform == "darwin" else "linux")[0])
            if not url:
                raise RuntimeError("Sin URL para esta plataforma")
            dest = _eng.engines_root() / "pandoc"
            dest.mkdir(parents=True, exist_ok=True)
            import tempfile
            tmp = Path(tempfile.mkdtemp()) / Path(url).name
            urllib.request.urlretrieve(url, tmp)
            if str(tmp).endswith(".zip"):
                with zipfile.ZipFile(tmp) as z:
                    z.extractall(dest)
            else:
                with tarfile.open(tmp) as t:
                    t.extractall(dest, filter="data")
            btn.setText(_tr("Instalado ✓ (reinicia)"))
            self._refresh_row("pandoc")
        except Exception as e:
            btn.setText(_tr("Reintentar"))
            btn.setEnabled(True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Pandoc", f"{_tr('No se pudo descargar:')}\n{e}")

    def _install_ai(self, btn):
        from .i18n import tr as _tr
        btn.setEnabled(False)
        btn.setText(_tr("Descargando… (~176 MB)"))
        try:
            from . import bgremove
            bgremove.ensure_onnxruntime()
            bgremove.ensure_model()
            btn.setText(_tr("Instalado ✓"))
            self._refresh_row("ai-bg")
        except Exception as e:
            btn.setText(_tr("Reintentar"))
            btn.setEnabled(True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, _tr("Modelo IA"), str(e))

    def _locate_lo(self):
        from .i18n import tr as _tr
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, _tr("Carpeta de LibreOffice (program)"))
        if d:
            from PySide6.QtWidgets import QMessageBox
            cand = Path(d) / ("soffice.exe" if sys.platform == "win32" else "soffice")
            if cand.exists():
                QMessageBox.information(self, "LibreOffice", f"{_tr('Detectado:')} {cand}\n{_tr('Ya puedes usar Convert → PDF en DOC/XLS/PPT.')}")
            else:
                QMessageBox.warning(self, "LibreOffice", _tr("No encontré soffice ahí."))

    def _install_lo(self, btn):
        from .i18n import tr as _trb
        import sys as _sys
        if _sys.platform != "win32":
            from PySide6.QtWidgets import QMessageBox as _MB
            _MB.information(self, "LibreOffice",
                            _trb("Automatic install is Windows-only. Install LibreOffice with your package manager, then use Ya lo tengo…"))
            from PySide6.QtGui import QDesktopServices as _QDT
            from PySide6.QtCore import QUrl as _QUrl
            _QDT.openUrl(_QUrl("https://www.libreoffice.org/download/download-libreoffice/"))
            return
        from PySide6.QtCore import QObject, QThread, Signal

        class _Worker(QObject):
            done = Signal(object)
            prog = Signal(int)

            def run(self):
                try:
                    from . import engines as _eng
                    _eng.libreoffice_install(progress=lambda p: self.prog.emit(int(p)))
                    self.done.emit(None)
                except Exception as e:  # noqa: BLE001
                    self.done.emit(e)

        btn.setEnabled(False)
        from .i18n import tr as _trb
        btn.setText(_trb("Descargando MSI…"))
        self._lo_thread = QThread(self)
        self._lo_worker = _Worker()
        self._lo_worker.moveToThread(self._lo_thread)
        self._lo_thread.started.connect(self._lo_worker.run)
        self._lo_worker.prog.connect(lambda p: btn.setText(f"{_trb('Descargando…')} {p}%"))
        self._lo_worker.done.connect(lambda e: self._lo_done(btn, e))
        self._lo_thread.start()

    def _lo_done(self, btn, err):
        try:
            self._lo_thread.quit()
            self._lo_thread.wait()
        except Exception:
            pass
        from PySide6.QtWidgets import QMessageBox
        from .i18n import tr as _tr
        if err is None:
            btn.setText(_tr("Instalado ✓ (reinicia)"))
            self._refresh_row("libreoffice")
            QMessageBox.information(self, "LibreOffice", _tr("Listo. Ya puedes usar Convert → PDF en DOC/XLS/PPT/ODT."))
        else:
            btn.setText(_tr("Reintentar"))
            btn.setEnabled(True)
            QMessageBox.warning(self, "LibreOffice", str(err))

    def _get_lo(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl("https://www.libreoffice.org/download/download-libreoffice/"))


class WelcomeWindow(GlassWindow):
    def __init__(self, settings: Settings, trigger_label: str = "Shift"):
        from .i18n import tr
        super().__init__(tr("Welcome to DragShift"), size=(560, 430))
        self.s = settings
        steps = [
            ("1", tr("Start dragging any file"), tr("in Finder or on the desktop") if IS_MAC else
             tr("in your file manager (Thunar, Nautilus…)") if IS_LINUX else tr("in File Explorer or on the desktop")),
            ("2", f"{tr('Press')} {trigger_label}", tr("the glass menu opens right under your cursor")),
            ("3", tr("Drop it on a slice"), tr("the result is saved next to the original")),
            ("⇄", f"{tr('Tap')} {trigger_label} {tr('again')}", tr("to switch between Convert and Tools")),
        ]
        for n, head, sub in steps:
            row = QHBoxLayout()
            badge = QLabel(n)
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedSize(34, 34)
            badge.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #5ac8ff, stop:1 #2f7bff);"
                                "border-radius: 17px; font-weight: 700; font-size: 12pt;")
            row.addWidget(badge)
            col = QVBoxLayout()
            col.setSpacing(0)
            h = QLabel(head)
            h.setStyleSheet("font-size: 12pt; font-weight: 600;")
            d = QLabel(sub)
            d.setObjectName("dim")
            col.addWidget(h)
            col.addWidget(d)
            row.addSpacing(8)
            row.addLayout(col, 1)
            self.body.addLayout(row)
        self.body.addStretch(1)
        if IS_MAC:
            from . import platform_mac
            if not platform_mac.has_screen_recording():
                note = QLabel("Optional: allow Screen Recording so the glass can refract the windows "
                              "behind it (otherwise it shows your wallpaper). DragShift never saves or sends it.")
                note.setObjectName("dim")
                note.setWordWrap(True)
                self.body.addWidget(note)
                b = QPushButton("Allow Screen Recording…")
                b.clicked.connect(platform_mac.request_screen_recording)
                self.body.addWidget(b, 0, Qt.AlignLeft)
        if IS_LINUX:
            from . import platform_linux
            if platform_linux.is_wayland():
                note = QLabel("You're on a Wayland session: the Shift-while-dragging trigger needs X11 (e.g. XFCE). "
                              "Right-click a file → Open With → DragShift still works.")
                note.setObjectName("warn")
                note.setWordWrap(True)
                self.body.addWidget(note)
        foot = QHBoxLayout()
        if IS_WIN or IS_MAC or IS_LINUX:
            from .i18n import tr as _trw
            self.auto = QCheckBox(_trw("Start with Windows") if IS_WIN else _trw("Open at login"))
            self.auto.setChecked(True)
            foot.addWidget(self.auto)
        foot.addStretch(1)
        ok = QPushButton(tr("Got it"))
        ok.setObjectName("primary")
        ok.clicked.connect(self._done)
        foot.addWidget(ok)
        self.body.addLayout(foot)

    def _done(self):
        self.s.set("welcomed", True)
        if IS_WIN or IS_MAC or IS_LINUX:
            set_autostart(self.auto.isChecked())
        self.close()
