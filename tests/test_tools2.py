"""Tests for text/file/sheet utilities (stdlib + light deps, no ffmpeg transcode)."""
from pathlib import Path

from dragshift import convert, filetools, multitools, sheettools, texttools
from dragshift import imaging
from dragshift.util import category, sibling


def test_text_names_and_targets(tmp_path):
    for name in (".env", ".gitignore", "Dockerfile", "Makefile", "LICENSE", "README"):
        assert category(str(tmp_path / name)) == "text"
    assert category(str(tmp_path / "a.py")) == "text"
    assert category(str(tmp_path / "x.zip")) is None
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
