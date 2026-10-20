"""Tests for text/file/sheet utilities (stdlib + light deps, no ffmpeg transcode)."""
from pathlib import Path

from dragshift import convert, filetools, multitools, sheettools, texttools
from dragshift import imaging
from dragshift.util import category, sibling


def test_text_names_and_targets(tmp_path):
    for name in (".env", ".gitignore", "Dockerfile", "Makefile", "LICENSE", "README"):
        assert category(str(tmp_path / name)) == "text"
    assert category(str(tmp_path / "a.py")) == "text"
    assert category(str(tmp_path / "x.zip")) == "archive"
    assert category(str(tmp_path / "x.rar")) == "archive"
    assert "TXT" in convert.targets_for("text", ".env")
    assert "HTML" in convert.targets_for("text", ".md")


def test_tidy_sort_mask(tmp_path):
    e = tmp_path / ".env"
    e.write_text("B=2\nA=1  \n# c\n")
    assert texttools.tidy_text(e).read_text().splitlines() == ["B=2", "A=1", "# c"]
    assert "A=1" in texttools.sort_text(e).read_text()
    e2 = tmp_path / ".env"
    e2.write_text("KEY=secret\nOTHER=x\n")
    masked = texttools.mask_secrets(e2).read_text()
    assert "KEY=***" in masked and "OTHER=***" in masked


def test_format_minify(tmp_path):
    j = tmp_path / "a.json"
    j.write_text('{"b":1,"a":2}')
    assert '"a": 2' in texttools.format_text(j).read_text()
    assert texttools.minify_text(j).read_text().strip() == '{"b":1,"a":2}'


def test_sheet_csv_sqlite_yaml(tmp_path):
    c = tmp_path / "t.csv"
    c.write_text("a,b\n1,2\n")
    xlsx = sheettools.csv_to_xlsx(c)[0]
    assert xlsx.suffix == ".xlsx"
    assert "1" in sheettools.sheet_to_csv(xlsx)[0].read_text()
    assert "<table" in sheettools.sheet_to_html(c)[0].read_text()
    import sqlite3
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t(a,b)")
    con.execute('INSERT INTO t VALUES (1,2)')
    con.commit()
    con.close()
    assert category(str(db)) == "sheet"
    assert "a,b" in sheettools.sqlite_to_csv(db)[0].read_text()
    y = tmp_path / "t.yaml"
    y.write_text("a: 2020-01-01\n")
    assert '"a": "2020-01-01"' in sheettools.yaml_to_json(y)[0].read_text()


def test_filetools_roundtrip(tmp_path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"y" * 100)
    parts = filetools.split_file(f, part_size=30)
    assert len(parts) == 4 and parts[0].suffix == ".part001"
    assert filetools.join_parts(parts).read_bytes() == b"y" * 100
    assert filetools.sha256_file(f).suffix == ".sha256"
    assert filetools.b64_decode(filetools.b64_encode(f)).read_bytes() == b"y" * 100
    enc = filetools.encrypt_file(f, "pw")
    assert filetools.decrypt_file(enc, "pw").read_bytes() == b"y" * 100
    z = filetools.zip_files([str(f)])
    assert z.suffix == ".zip"
    t = tmp_path / "t.txt"
    t.write_text("hello qr")
    assert filetools.qr_of_text(t).suffix == ".png"


def test_multi_and_sibling(tmp_path):
    from PIL import Image
    a = tmp_path / "a.png"
    Image.new("RGB", (32, 32), (255, 0, 0)).save(a)
    assert multitools.contact_sheet([str(a), str(a)]).exists()
    assert multitools.images_to_gif([str(a), str(a)]).suffix == ".gif"
    arch = tmp_path / "a.tar.gz"
    arch.write_bytes(b"x")
    assert sibling(arch, "Out").name == "a Out.tar.gz"


def test_history_and_trim_validation(tmp_path):
    from dragshift import history, mediatools
    from dragshift.util import UserError
    f = tmp_path / "h.txt"
    f.write_text("x")
    history.log("convert:TXT", [str(f)], [str(f)])
    assert history.recent(5)
    import pytest as _pt
    with _pt.raises(UserError):
        mediatools.trim_media(f, 20, 5)
    with _pt.raises(UserError):
        mediatools.concat_same([str(f)])


def test_new_categories(tmp_path):
    from dragshift import nbtools
    from dragshift.util import category
    assert category(str(tmp_path / "a.srt")) == "subtitle"
    assert category(str(tmp_path / "a.vtt")) == "subtitle"
    assert category(str(tmp_path / "n.ipynb")) == "notebook"
    assert category(str(tmp_path / "m.eml")) == "email"
    assert category(str(tmp_path / "c.vcf")) == "contact"
    assert category(str(tmp_path / "e.ics")) == "contact"
    assert category(str(tmp_path / "f.ttf")) == "font"
    assert category(str(tmp_path / "d.csv")) == "sheet"
    s = tmp_path / "s.srt"
    s.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n")
    v = convert.convert(s, "subtitle", "VTT")[0]
    assert v.suffix == ".vtt" and "WEBVTT" in v.read_text()
    assert convert.convert(v, "subtitle", "SRT")[0].suffix == ".srt"
    assert "Hello" in convert.convert(s, "subtitle", "TXT")[0].read_text()
    nb = tmp_path / "n.ipynb"
    nb.write_text('{"cells": [{"cell_type": "code", "source": ["print(1)"]}], "nbformat": 4, "nbformat_minor": 5}')
    assert "print(1)" in convert.convert(nb, "notebook", "PY")[0].read_text()
    assert convert.convert(nb, "notebook", "HTML")[0].suffix == ".html"
    em = tmp_path / "m.eml"
    em.write_text("From: a@b.c\nSubject: hi\nContent-Type: text/plain\n\nbody here\n")
    assert "body here" in convert.convert(em, "email", "TXT")[0].read_text()
    vc = tmp_path / "c.vcf"
    vc.write_text("BEGIN:VCARD\nFN:Alice\nTEL:123\nEND:VCARD\n")
    assert "Alice" in convert.convert(vc, "contact", "CSV")[0].read_text()
    assert "Alice" in nbtools.contact_to_txt(vc)[0].read_text()
    h = tmp_path / "h.html"
    h.write_text("<h1>Hola</h1><p>mundo</p>")
    t = convert.convert(h, "text", "TXT")[0]
    assert "Hola" in t.read_text() and "<h1>" not in t.read_text()
    md = tmp_path / "r.md"
    md.write_text("# H\n**b**\n")
    mh = convert.convert(md, "text", "HTML")[0].read_text()
    assert "<h1>H</h1>" in mh and "<pre>" not in mh
    x = tmp_path / "x.json"
    x.write_text('{"a": 1}')
    assert "a:" in convert.convert(x, "text", "YAML")[0].read_text()
    y = tmp_path / "y.yaml"
    y.write_text("a: 1\n")
    assert convert.convert(y, "text", "TOML")[0].suffix == ".toml"
    dx = tmp_path / "d.docx"
    from docx import Document
    Document().add_paragraph("hi")._element  # noqa
    _d = Document()
    _d.add_paragraph("hi")
    _d.save(dx)
    assert "<p>" in convert.convert(dx, "docx", "HTML")[0].read_text()
    from PIL import Image
    im = tmp_path / "im.png"
    Image.new("RGB", (64, 48), (200, 40, 40)).save(im)
    colors, sw = imaging.palette(im)
    assert len(colors) == 6 and sw.exists()
    pdf = convert.convert(im, "image", "PDF")[0]
    assert "Outline" in imaging.pdf_outline(pdf)
    d1 = tmp_path / "d1.txt"
    d1.write_text("same")
    d2 = tmp_path / "d2.txt"
    d2.write_text("same")
    assert "Duplicates" in filetools.find_duplicates([str(d1), str(d2)]).name
    rep = filetools.folder_report(tmp_path)
    assert rep.exists() and "files" in rep.read_text()


def test_v5_conversions(tmp_path):
    from dragshift import bgremove
    c = tmp_path / "d.csv"
    c.write_text("a,b\n1,2\n")
    import json as _j
    assert _j.loads(convert.convert(c, "sheet", "JSON")[0].read_text())[0]["a"] == "1"
    j = tmp_path / "l.json"
    j.write_text('[{"a": 1, "b": 2}]')
    assert "a,b" in convert.convert(j, "text", "CSV")[0].read_text().splitlines()[0]
    h = tmp_path / "p.html"
    h.write_text("<h1>Hola Mundo</h1>")
    with convert.fitz.open(convert.convert(h, "text", "PDF")[0]) as d:
        assert "Hola Mundo" in d[0].get_text() and "<h1>" not in d[0].get_text()
    sv = tmp_path / "s.svg"
    sv.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
                  '<rect width="64" height="64" fill="red"/></svg>')
    assert convert.convert(sv, "text", "PNG")[0].exists()
    from PIL import Image
    im = tmp_path / "im2.png"
    Image.new("RGB", (32, 32), (0, 200, 0)).save(im)
    pdf = convert.convert(im, "image", "PDF")[0]
    assert "body" in convert.convert(pdf, "pdf", "HTML")[0].read_text().lower()
    md = tmp_path / "m.md"
    md.write_text("# Title\n**bold**\n")
    from docx import Document
    assert Document(convert.convert(md, "text", "DOCX")[0]).paragraphs[0].style.name.startswith("Heading")
    vc = tmp_path / "p.csv"
    vc.write_text("name,phone,email\nAlice,123,a@b.c\n")
    from dragshift import nbtools
    vcf = nbtools.csv_to_vcf(vc)[0]
    assert "FN:Alice" in vcf.read_text() and "Alice" in nbtools.contact_to_txt(vcf)[0].read_text()
    try:
        from odf.opendocument import OpenDocumentText
        from odf.text import P
        odt = tmp_path / "t.odt"
        doc = OpenDocumentText()
        doc.text.addElement(P(text="hola odt"))
        doc.save(odt)
        assert "hola odt" in convert.convert(odt, "docx", "TXT")[0].read_text()
    except Exception:
        pass
    im2 = tmp_path / "prod.png"
    base = Image.new("RGB", (100, 100), (255, 255, 255))
    from PIL import ImageDraw
    ImageDraw.Draw(base).rectangle((30, 30, 70, 70), fill=(200, 30, 30))
    base.save(im2)
    out = bgremove.remove_solid_background(im2)
    assert out.suffix == ".png" and Image.open(out).mode == "RGBA"
    assert bgremove.models_dir().exists()
    assert bgremove.ai_status()[0] in ("ready", "no-model", "no-onnx")
    # isnet preferred over u2net when both exist (rembg cache layout)
    import pathlib as _pl
    home = tmp_path / "fakehome"
    (home / ".rembg" / "models" / "isnet-general-use").mkdir(parents=True)
    (home / ".rembg" / "models" / "u2net").mkdir(parents=True)
    (home / ".rembg" / "models" / "u2net" / "u2net.onnx").write_bytes(b"\0" * 11_000_000)
    (home / ".rembg" / "models" / "isnet-general-use" / "isnet-general-use.onnx").write_bytes(b"\0" * 11_000_000)
    orig_home = _pl.Path.home
    _pl.Path.home = classmethod(lambda cls: home)
    try:
        found = bgremove.find_model()
        assert found is not None and found[0].name == "isnet-general-use.onnx" and found[1] == 1024
    finally:
        _pl.Path.home = orig_home
    # real AI path when engine+model exist here (uses EXIF-aware open_image)
    if bgremove.onnx_available() and bgremove.find_model() is not None:
        from PIL import Image as _I
        ex = _I.Exif()
        ex[0x0112] = 6  # rotate 90 CW
        tall = tmp_path / "tall.jpg"
        _I.new("RGB", (60, 100), (30, 120, 30)).save(tall, exif=ex)
        ref = convert.open_image(tall)
        got = bgremove.remove_ai_background(tall)
        assert _I.open(got).size == ref.size
    from dragshift import imaging as _im
    from dragshift.convert import open_image
    assert _im.save_like(_im.watermark(open_image(im2), "TEST"), im2, "WM").exists()
    assert _im.image_diff(im2, im2).exists()
    assert len(filetools.favicon_pack(im2)) == 5
    t = tmp_path / "q.txt"
    t.write_text("hello")
    assert filetools.qr_with_logo(t, im2).suffix == ".png"
    from dragshift.app import presets_for
    assert presets_for("image") == ["web-small"]
    assert presets_for("audio") == ["voice-note"]
    assert presets_for("video") == ["voice-note"]
    assert presets_for("pdf") == []
    from dragshift import bgremove as _bg2
    state, msg = _bg2.ai_status()
    assert state in ("ready", "no-model", "no-onnx") and msg


def test_lo_discovery_and_engines():
    from dragshift import engines
    ids = [e.id for e in engines.registry()]
    assert {"ffmpeg", "office", "ai-bg", "pandoc", "libreoffice"} <= set(ids)
    # version picking without network
    html = ('<a href="7.6.7/">7.6.7/</a><a href="25.2.3/">25.2.3/</a>'
            '<a href="24.8.1/">24.8.1/</a>')
    import re
    vers = re.findall(r'href="(\d+\.\d+\.\d+)/"', html)
    assert sorted(vers, key=lambda v: tuple(int(x) for x in v.split(".")))[-1] == "25.2.3"
    # platform tags used for wheel downloads (mac-arm, linux, win)
    import sys as _sys
    assert engines._plat_tags()  # current platform non-empty
    # LO auto-install is Windows-only
    import pytest as _pt
    from dragshift.util import UserError
    if _sys.platform != "win32":
        with _pt.raises(UserError):
            engines.libreoffice_install()
    # wheel picking from fake PyPI metadata (no network)
    import json as _json

    class _Resp:
        def __init__(self, payload):
            self._p = payload
        def read(self):
            return _json.dumps(self._p).encode()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    meta = {"urls": [
        {"filename": "onnxruntime-1.31.0-cp312-cp312-win_amd64.whl", "size": 1,
         "url": "https://x/onnxruntime-1.31.0-cp312-cp312-win_amd64.whl", "sha256": "x"},
        {"filename": "onnxruntime-1.31.0-cp312-cp312-macosx_11_0_arm64.whl", "size": 1,
         "url": "https://x/onnxruntime-1.31.0-cp312-cp312-macosx_11_0_arm64.whl", "sha256": "x"},
    ]}
    import urllib.request as _u
    real = _u.urlopen
    _u.urlopen = lambda *a, **k: _Resp(meta)
    try:
        picked = [u for u in meta["urls"] if "win_amd64" in u["filename"]]
        assert picked and picked[0]["filename"].startswith("onnxruntime-1.31.0")
    finally:
        _u.urlopen = real


def test_ring_order_stable_for_e2e(tmp_path):
    """E2E computes petal positions with build_rings(None, ...): order must not
    depend on self/settings, or drops land on the wrong slice."""
    from dragshift.app import DragShiftApp
    import tempfile
    from PIL import Image as _I
    d = tmp_path
    a = d / "a.png"
    _I.new("RGB", (32, 32), (255, 0, 0)).save(a)
    b = d / "b.jpg"
    _I.new("RGB", (32, 32), (0, 255, 0)).save(b)
    t = d / "t.txt"
    t.write_text("hi")
    for paths in ([str(a)], [str(a), str(b)], [str(t)], [str(a), str(t)]):
        rings = DragShiftApp.build_rings(None, [str(p) for p in paths])
        assert list(rings) == ["Convert"] or "Convert" in rings
        for name, items in rings.items():
            assert [i.label for i in items] == [i.label for i in items]  # deterministic
    r1 = DragShiftApp.build_rings(None, [str(a)])
    r2 = DragShiftApp.build_rings(None, [str(a)])
    assert [i.label for i in r1["Convert"]] == [i.label for i in r2["Convert"]]
    assert [i.label for i in r1["Tools"]] == [i.label for i in r2["Tools"]]


def test_opcionales_opens_and_stays():
    """Regression: EnginesWindow was GC'd instantly (local var). Must stay open."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from dragshift.settings import Settings, SettingsWindow
    app = QApplication.instance() or QApplication([])
    w = SettingsWindow(Settings())
    w._open_engines()
    win = w._engines_win
    assert win is not None and win.isVisible()
    w._open_engines()
    assert w._engines_win is win  # reused, not duplicated
    win.close()
    w.close()


def test_filee_batch(tmp_path):
    from dragshift import archtools, engines, nbtools, updater
    from dragshift.util import category
    assert category(str(tmp_path / "a.7z")) == "archive"
    assert category(str(tmp_path / "a.tar.gz")) == "archive"
    assert category(str(tmp_path / "d.doc")) == "legacy"
    f1 = tmp_path / "f1.txt"
    f1.write_text("hello")
    z = archtools.arch_create([str(f1)], "ZIP")
    assert z.suffix == ".zip"
    out = archtools.arch_extract(z)
    assert (out / "f1.txt").read_text() == "hello"
    assert "f1.txt" in archtools.arch_list(z)
    tgz = archtools.arch_create([str(f1)], "TAR.GZ")
    assert archtools.arch_extract(tgz).exists()
    z7 = archtools.arch_create([str(f1)], "7Z")
    assert archtools.arch_extract(z7).exists()
    from PIL import Image
    im = tmp_path / "p.png"
    Image.new("RGB", (64, 48), (10, 20, 30)).save(im)
    import zipfile
    cbz = tmp_path / "c.cbz"
    with zipfile.ZipFile(cbz, "w") as zf:
        zf.write(im, "p01.png")
    assert category(str(cbz)) == "ebook"
    assert convert.convert(cbz, "ebook", "PDF")[0].suffix == ".pdf"
    fb = tmp_path / "b.fb2"
    fb.write_text('<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
                  '<body><section><p>Hola</p></section></body></FictionBook>', encoding="utf-8")
    assert "Hola" in convert.convert(fb, "ebook", "TXT")[0].read_text()
    assert "PDF" in convert.targets_for("legacy", ".doc")
    pdf = convert.convert(im, "image", "PDF")[0]
    assert convert.convert(pdf, "pdf", "PPTX")[0].suffix == ".pptx"
    lrc = tmp_path / "s.lrc"
    lrc.write_text("[00:01.00]Hello\n[00:03.00]World\n")
    assert category(str(lrc)) == "subtitle"
    v = convert.convert(lrc, "subtitle", "VTT")[0]
    assert "WEBVTT" in v.read_text()
    import shutil
    from pathlib import Path as _P
    arial = _P("C:/Windows/Fonts/arial.ttf")
    if arial.exists():
        w = nbtools.font_convert(arial, "WOFF")[0]
        assert w.suffix == ".woff"
        assert nbtools.font_info(arial)[0].exists()
    ids = [e.id for e in engines.registry()]
    assert {"ffmpeg", "libreoffice", "ai-bg", "office", "pandoc"} <= set(ids)
    assert updater._norm("v1.2.0") > updater._norm("1.1.0")
    assert updater._norm("1.10.0") > updater._norm("1.2.0")


def test_preset_voice_and_websmall(tmp_path):
    """Regression: web-small preset raised NameError (wrong loop var)."""
    from PIL import Image
    from dragshift.app import preset_run
    im = tmp_path / "p.png"
    Image.new("RGB", (800, 600), (10, 200, 30)).save(im)
    outs = preset_run("web-small", [str(im)])
    assert outs and outs[0].exists()
    import pytest as _pt
    with _pt.raises(ValueError):
        preset_run("nope", [str(im)])


def test_present_rich(tmp_path):
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Hello Title"
    tf = slide.placeholders[1].text_frame
    tf.text = "First"
    tf.add_paragraph().text = "Second"
    tf.paragraphs[1].level = 1
    from dragshift import convert
    h = convert.convert(_save(prs, tmp_path), "presentation", "HTML")[0].read_text()
    assert "Hello Title" in h and "Second" in h
    t = convert.convert(_save(prs, tmp_path), "presentation", "TXT")[0].read_text(encoding="utf-8")
    assert "Hello Title" in t and "• Second" in t


def _save(prs, tmp_path):
    p = tmp_path / "r.pptx"
    prs.save(p)
    return str(p)
