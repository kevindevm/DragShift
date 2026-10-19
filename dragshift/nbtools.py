"""Notebook / email / contact / font conversions (light deps only)."""
from __future__ import annotations

import csv
import html
import io
import json
from pathlib import Path

from .convert import html_to_pdf, read_text
from .util import UserError, sibling


# ---------------------------------------------------------------- notebook (.ipynb is JSON)
def _nb_cells(src: str | Path) -> list[dict]:
    try:
        nb = json.loads(read_text(src))
    except Exception as e:
        raise UserError(f"Not a valid notebook: {e}")
    cells = nb.get("cells", [])
    if not isinstance(cells, list):
        raise UserError("Not a valid notebook (nbformat).")
    return cells


def ipynb_to_py(src: str | Path) -> list[Path]:
    parts = []
    for c in _nb_cells(src):
        if c.get("cell_type") == "code":
            parts.append("".join(c.get("source", [])))
    out = sibling(src, ext=".py")
    out.write_text("\n\n".join(p for p in parts if p.strip()) + "\n", encoding="utf-8")
    return [out]


def ipynb_to_txt(src: str | Path) -> list[Path]:
    lines = []
    for c in _nb_cells(src):
        kind = c.get("cell_type", "")
        body = "".join(c.get("source", []))
        if body.strip():
            lines += [f"### {kind} ###", body, ""]
    out = sibling(src, ext=".txt")
    out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return [out]


def ipynb_to_html(src: str | Path) -> list[Path]:
    parts = []
    for c in _nb_cells(src):
        body = "".join(c.get("source", []))
        if not body.strip():
            continue
        if c.get("cell_type") == "markdown":
            parts.append(f"<p>{html.escape(body)}</p>")
        else:
            parts.append(f"<pre>{html.escape(body)}</pre>")
    out = sibling(src, ext=".html")
    out.write_text("<!doctype html><html><head><meta charset='utf-8'></head><body>"
                   + "\n".join(parts) + "</body></html>", encoding="utf-8")
    return [out]


def ipynb_to_pdf(src: str | Path) -> list[Path]:
    h = ipynb_to_html(src)[0]
    try:
        out = sibling(src, ext=".pdf")
        html_to_pdf(h.read_text(encoding="utf-8")[:30000], out)
        return [out]
    finally:
        try:
            h.unlink()
        except OSError:
            pass


def ipynb_strip(src: str | Path) -> Path:
    nb = json.loads(read_text(src))
    for c in nb.get("cells", []):
        c.pop("outputs", None)
        c.pop("execution_count", None)
    out = sibling(src, "Clean", ".ipynb")
    out.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# ---------------------------------------------------------------- email (.eml)
def _parse_eml(src: str | Path):
    import email
    from email import policy
    try:
        return email.message_from_bytes(Path(src).read_bytes(), policy=policy.default)
    except Exception as e:
        raise UserError(f"Couldn't parse email: {e}")


def eml_to_txt(src: str | Path) -> list[Path]:
    m = _parse_eml(src)
    try:
        body = m.get_body(("plain",)).get_content() if m.get_body(("plain",)) else ""
    except Exception:
        body = ""
    out = sibling(src, ext=".txt")
    out.write_text(f"From: {m['from']}\nDate: {m['date']}\nSubject: {m['subject']}\n\n{body}",
                   encoding="utf-8")
    return [out]


def eml_to_html(src: str | Path) -> list[Path]:
    m = _parse_eml(src)
    try:
        html_body = m.get_body(("html",))
        if html_body:
            content = html_body.get_content()
        else:
            content = f"<pre>{html.escape(m.get_body(('plain',)).get_content())}</pre>" if m.get_body(("plain",)) else ""
    except Exception:
        content = ""
    out = sibling(src, ext=".html")
    out.write_text(f"<!doctype html><html><head><meta charset='utf-8'></head><body>"
                   f"<p><b>From:</b> {html.escape(str(m['from']))}<br>"
                   f"<b>Subject:</b> {html.escape(str(m['subject']))}</p>{content}</body></html>",
                   encoding="utf-8")
    return [out]


def eml_to_pdf(src: str | Path) -> list[Path]:
    h = eml_to_html(src)[0]
    try:
        out = sibling(src, ext=".pdf")
        html_to_pdf(h.read_text(encoding="utf-8")[:30000], out)
        return [out]
    finally:
        try:
            h.unlink()
        except OSError:
            pass


def eml_attachments(src: str | Path) -> list[Path]:
    m = _parse_eml(src)
    from .util import output_dir, unique_path
    folder = unique_path(output_dir(src) / f"{Path(src).stem} attachments")
    outs = []
    for part in m.iter_attachments():
        name = part.get_filename() or "attachment.bin"
        folder.mkdir(exist_ok=True)
        p = unique_path(folder / name)
        p.write_bytes(part.get_content())
        outs.append(p)
    if not outs:
        raise UserError("No attachments in this email.")
    return outs


def _parse_msg(src: str | Path):
    try:
        import extract_msg
    except Exception as e:
        raise UserError(f"MSG support needs extract-msg: {e}")
    try:
        return extract_msg.Message(str(src))
    except Exception as e:
        raise UserError(f"Couldn't read Outlook message: {e}")


def _msg_to_eml_fields(src: str | Path) -> tuple[str, str, str, str]:
    m = _parse_msg(src)
    try:
        return (str(m.sender or ""), str(m.date or ""), str(m.subject or ""),
                str(m.body or ""))
    finally:
        try:
            m.close()
        except Exception:
            pass


def msg_to_txt(src: str | Path) -> list[Path]:
    sender, date, subject, body = _msg_to_eml_fields(src)
    out = sibling(src, ext=".txt")
    out.write_text(f"From: {sender}\nDate: {date}\nSubject: {subject}\n\n{body}", encoding="utf-8")
    return [out]


def msg_to_html(src: str | Path) -> list[Path]:
    sender, date, subject, body = _msg_to_eml_fields(src)
    out = sibling(src, ext=".html")
    out.write_text(f"<!doctype html><html><head><meta charset='utf-8'></head><body>"
                   f"<p><b>From:</b> {html.escape(sender)}<br>"
                   f"<b>Subject:</b> {html.escape(subject)}</p>"
                   f"<pre>{html.escape(body)}</pre></body></html>", encoding="utf-8")
    return [out]


def msg_to_pdf(src: str | Path) -> list[Path]:
    h = msg_to_html(src)[0]
    try:
        out = sibling(src, ext=".pdf")
        html_to_pdf(h.read_text(encoding="utf-8")[:30000], out)
        return [out]
    finally:
        try:
            h.unlink()
        except OSError:
            pass


def msg_attachments(src: str | Path) -> list[Path]:
    m = _parse_msg(src)
    from .util import output_dir, unique_path
    folder = unique_path(output_dir(src) / f"{Path(src).stem} attachments")
    outs = []
    try:
        for att in m.attachments:
            name = att.longFilename or att.shortFilename or "attachment.bin"
            folder.mkdir(exist_ok=True)
            p = unique_path(folder / str(name))
            p.write_bytes(att.data)
            outs.append(p)
    finally:
        try:
            m.close()
        except Exception:
            pass
    if not outs:
        raise UserError("No attachments in this message.")
    return outs


# ---------------------------------------------------------------- contact (.vcf / .ics)
def _unfold(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for ln in text.split("\n"):
        if ln[:1] in (" ", "\t") and lines:
            lines[-1] += ln[1:]
        else:
            lines.append(ln)
    return lines


def _parse_cards(src: str | Path) -> list[dict]:
    cards, cur = [], {}
    for ln in _unfold(read_text(src)):
        u = ln.upper()
        if u.startswith("BEGIN:VCARD"):
            cur = {}
        elif u.startswith("END:VCARD"):
            if cur:
                cards.append(cur)
            cur = {}
        elif ":" in ln and cur is not None:
            k, _, v = ln.partition(":")
            k = k.split(";")[0].upper()
            if k in ("FN", "TEL", "EMAIL", "ORG", "TITLE", "NOTE"):
                cur.setdefault(k, []).append(v)
    return cards


def _parse_ics(src: str | Path) -> list[dict]:
    events, cur = [], {}
    for ln in _unfold(read_text(src)):
        u = ln.upper()
        if u.startswith("BEGIN:VEVENT"):
            cur = {}
        elif u.startswith("END:VEVENT"):
            if cur:
                events.append(cur)
            cur = {}
        elif ":" in ln and cur is not None:
            k, _, v = ln.partition(":")
            k = k.split(";")[0].upper()
            if k in ("SUMMARY", "DTSTART", "DTEND", "LOCATION", "DESCRIPTION"):
                cur[k] = v
    return events


def contact_to_csv(src: str | Path) -> list[Path]:
    ext = Path(src).suffix.lower()
    out = sibling(src, ext=".csv")
    with out.open("w", encoding="utf-8", newline="") as f:
        if ext == ".ics":
            w = csv.writer(f)
            w.writerow(["summary", "start", "end", "location"])
            for e in _parse_ics(src):
                w.writerow([e.get("SUMMARY", ""), e.get("DTSTART", ""),
                            e.get("DTEND", ""), e.get("LOCATION", "")])
        else:
            w = csv.writer(f)
            w.writerow(["name", "phone", "email", "org"])
            for c in _parse_cards(src):
                w.writerow(["; ".join(c.get("FN", [])), "; ".join(c.get("TEL", [])),
                            "; ".join(c.get("EMAIL", [])), "; ".join(c.get("ORG", []))])
    return [out]


def contact_to_txt(src: str | Path) -> list[Path]:
    ext = Path(src).suffix.lower()
    lines = []
    if ext == ".ics":
        for e in _parse_ics(src):
            lines += [e.get("SUMMARY", "(no title)"),
                      f"  {e.get('DTSTART', '')} → {e.get('DTEND', '')}",
                      f"  {e.get('LOCATION', '')}".rstrip(), ""]
    else:
        for c in _parse_cards(src):
            lines += ["; ".join(c.get("FN", ["(no name)"])),
                      f"  tel: {'; '.join(c.get('TEL', []))}".rstrip(),
                      f"  email: {'; '.join(c.get('EMAIL', []))}".rstrip(), ""]
    out = sibling(src, ext=".txt")
    out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return [out]


def contact_to_html(src: str | Path) -> list[Path]:
    csvp = contact_to_csv(src)[0]
    try:
        import csv as _csv
        rows = list(_csv.reader(csvp.read_text(encoding="utf-8").splitlines()))
        head, body = (rows[0], rows[1:]) if rows else ([], [])
        cells = "".join(f"<th>{html.escape(c)}</th>" for c in head)
        trs = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in r) + "</tr>"
                      for r in body[:2000])
        out = sibling(src, ext=".html")
        out.write_text(f"<!doctype html><html><head><meta charset='utf-8'></head><body>"
                       f"<table border='1'><tr>{cells}</tr>{trs}</table></body></html>",
                       encoding="utf-8")
        return [out]
    finally:
        try:
            csvp.unlink()
        except OSError:
            pass


def contact_merge(srcs: list[str | Path]) -> Path:
    blobs = []
    for s in srcs:
        t = read_text(s)
        if "BEGIN:VCARD" in t.upper():
            blobs.append(t.strip())
        else:
            raise UserError("Merge needs .vcf files (calendar merge not supported).")
    out = sibling(srcs[0], "Merged", ".vcf")
    out.write_text("\n".join(blobs) + "\n", encoding="utf-8")
    return out


def csv_to_vcf(src: str | Path) -> list[Path]:
    """name,phone,email CSV → vCard (round-trips with contact_to_csv)."""
    import csv as _csv
    rows = list(_csv.DictReader(read_text(src).splitlines()))
    if not rows or not {"name", "phone", "email"} & set(rows[0].keys()):
        raise UserError("CSV needs name/phone/email columns.")
    cards = []
    for r in rows:
        cards.append("BEGIN:VCARD\nVERSION:3.0\n"
                     f"FN:{r.get('name', '')}\nTEL:{r.get('phone', '')}\n"
                     f"EMAIL:{r.get('email', '')}\nEND:VCARD")
    out = sibling(src, ext=".vcf")
    out.write_text("\n".join(cards) + "\n", encoding="utf-8")
    return [out]


# ---------------------------------------------------------------- font (.ttf/.otf/...)
def font_info(src: str | Path) -> list[Path]:
    try:
        from fontTools.ttLib import TTFont
    except Exception as e:
        raise UserError(f"Font support needs fontTools: {e}")
    try:
        f = TTFont(str(src), lazy=True)
    except Exception as e:
        raise UserError(f"Couldn't read font: {e}")
    names = {}
    try:
        for r in f["name"].names:
            try:
                names.setdefault(r.nameID, r.toUnicode())
            except Exception:
                pass
    except Exception:
        pass
    try:
        glyphs = f["maxp"].numGlyphs
    except Exception:
        glyphs = "?"
    try:
        upm = f["head"].unitsPerEm
    except Exception:
        upm = "?"
    out = sibling(src, ext=".txt")
    out.write_text(f"Family: {names.get(1, Path(src).stem)}\n"
                   f"Style: {names.get(2, '')}\n"
                   f"Full name: {names.get(4, '')}\n"
                   f"Glyphs: {glyphs}\nUnits/em: {upm}\n", encoding="utf-8")
    return [out]


def font_convert(src: str | Path, target: str) -> list[Path]:
    try:
        from fontTools.ttLib import TTFont
    except Exception as e:
        raise UserError(f"Font support needs fontTools: {e}")
    target = target.upper()
    if target == "WOFF2":
        try:
            import brotli  # noqa: F401
        except Exception:
            raise UserError("WOFF2 needs brotli (pip install brotli).")
    try:
        f = TTFont(str(src))
    except Exception as e:
        raise UserError(f"Couldn't read font: {e}")
    if target == "TTF" and "CFF " in f:
        f = _cff_to_ttf(f)
    f.flavor = {"WOFF": "woff", "WOFF2": "woff2"}.get(target)
    out = sibling(src, ext="." + target.lower())
    f.save(out)
    return [out]


def _cff_to_ttf(f):
    """Convert CFF outlines to TrueType quadratic splines (in-memory)."""
    try:
        from fontTools.cu2qu.pens import Cu2QuPen
        from fontTools.pens.ttGlyphPen import TTGlyphPen
        from fontTools.ttLib import newTable
    except Exception as e:
        raise UserError(f"CFF conversion needs fontTools cu2qu: {e}")
    glyph_order = f.getGlyphOrder()
    cff = f["CFF "].cff
    charstrings = cff[cff.fontNames[0]].CharStrings
    glyf = newTable("glyf")
    glyf.glyphOrder = glyph_order
    glyf.glyphs = {}
    for name in glyph_order:
        tt_pen = TTGlyphPen(None)
        cu_pen = Cu2QuPen(tt_pen, max_err=1.0, reverse_direction=True)
        try:
            charstrings[name].draw(cu_pen)
            glyf.glyphs[name] = tt_pen.glyph()
        except Exception:
            tt_pen.moveTo((0, 0))
            tt_pen.closePath()
            glyf.glyphs[name] = tt_pen.glyph()
    f["glyf"] = glyf
    f["loca"] = newTable("loca")
    try:
        maxp = f["maxp"]
        maxp.tableVersion = 0x00010000
        for g in glyf.glyphs.values():
            try:
                g.recalcBounds(glyf)
            except Exception:
                pass
    except Exception:
        pass
    for tag in ("CFF ", "VORG"):
        if tag in f:
            del f[tag]
    try:
        gasp = newTable("gasp")
        gasp.gaspRange = {65535: 10}
        f["gasp"] = gasp
    except Exception:
        pass
    try:
        prep = newTable("prep")
        prep.program = b"\xb8\x01\xff\x85\xb0"
        f["prep"] = prep
    except Exception:
        pass
    return f


def font_specimen(src: str | Path, kind: str = "PNG") -> list[Path]:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as e:
        raise UserError(f"Specimen needs Pillow: {e}")
    text = "AaBbCcDdEeFfGg 0123456789"
    im = Image.new("RGB", (1200, 500), (255, 255, 255))
    d = ImageDraw.Draw(im)
    y = 10
    for size in (72, 48, 36, 24, 16):
        try:
            font = ImageFont.truetype(str(src), size)
        except Exception as e:
            raise UserError(f"Couldn't render font: {e}")
        d.text((20, y), f"{size}pt  {text}", font=font, fill=(20, 20, 20))
        y += size + 20
    if kind.upper() == "PDF":
        out = sibling(src, "Specimen", ".pdf")
        im.save(out, "PDF", resolution=150.0)
    else:
        out = sibling(src, "Specimen", ".png")
        im.save(out, "PNG")
    return [out]


# ---------------------------------------------------------------- comics (CBZ = zip of images)
def _cbz_images(src: str | Path) -> list[tuple[str, bytes]]:
    import zipfile
    try:
        zf = zipfile.ZipFile(src)
        names = sorted(n for n in zf.namelist()
                       if n.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"))
                       and not n.startswith("__MACOSX"))
        if not names:
            raise UserError("No images in this comic.")
        return [(n, zf.read(n)) for n in names]
    except UserError:
        raise
    except Exception as e:
        raise UserError(f"Couldn't read comic: {e}")


def cbz_to_pdf(src: str | Path) -> list[Path]:
    from PIL import Image
    import io as _io
    from .convert import flatten
    pages = []
    for _name, blob in _cbz_images(src):
        im = flatten(Image.open(_io.BytesIO(blob)).convert("RGB"))
        pages.append(im)
    out = sibling(src, ext=".pdf")
    pages[0].save(out, "PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    return [out]


def cbz_to_epub(src: str | Path) -> list[Path]:
    try:
        from ebooklib import epub
    except Exception as e:
        raise UserError(f"Ebook support needs EbookLib: {e}")
    book = epub.EpubBook()
    book.set_title(Path(src).stem)
    book.set_language("en")
    items = []
    for i, (name, blob) in enumerate(_cbz_images(src)):
        ext = Path(name).suffix.lower().lstrip(".") or "jpg"
        item = epub.EpubImage(uid=f"img{i}", file_name=f"img{i}.{ext}", content=blob)
        book.add_item(item)
        items.append(item)
    chaps = []
    for i, item in enumerate(items):
        c = epub.EpubHtml(title=f"Page {i + 1}", file_name=f"p{i + 1}.xhtml")
        c.content = f'<html><body><img src="{item.file_name}"/></body></html>'
        book.add_item(c)
        chaps.append(c)
    book.toc = chaps
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + chaps
    out = sibling(src, ext=".epub")
    epub.write_epub(str(out), book)
    return [out]


# ---------------------------------------------------------------- FictionBook (.fb2 XML)
def _fb2_texts(src: str | Path) -> tuple[str, list[str]]:
    try:
        from lxml import etree
    except Exception as e:
        raise UserError(f"FB2 support needs lxml: {e}")
    try:
        root = etree.parse(str(src)).getroot()
    except Exception as e:
        raise UserError(f"Couldn't parse FB2: {e}")
    ns = {"f": "http://www.gribuser.ru/xml/fictionbook/2.0"}
    title = " ".join(t.strip() for t in root.xpath("//f:book-title//text()", namespaces=ns)[:3])
    paras = [" ".join(p.itertext()).strip()
             for p in root.xpath("//f:body//f:p", namespaces=ns)]
    paras = [p for p in paras if p]
    if not paras:
        raise UserError("No text in this FB2.")
    return title or Path(src).stem, paras


def fb2_to_txt(src: str | Path) -> list[Path]:
    title, paras = _fb2_texts(src)
    out = sibling(src, ext=".txt")
    out.write_text(title + "\n\n" + "\n\n".join(paras) + "\n", encoding="utf-8")
    return [out]


def fb2_to_html(src: str | Path) -> list[Path]:
    title, paras = _fb2_texts(src)
    body = "".join(f"<p>{html.escape(p)}</p>" for p in paras[:5000])
    out = sibling(src, ext=".html")
    out.write_text(f"<!doctype html><html><head><meta charset='utf-8'>"
                   f"<title>{html.escape(title)}</title></head><body>"
                   f"<h1>{html.escape(title)}</h1>{body}</body></html>", encoding="utf-8")
    return [out]


def fb2_to_pdf(src: str | Path) -> list[Path]:
    h = fb2_to_html(src)[0]
    try:
        out = sibling(src, ext=".pdf")
        html_to_pdf(h.read_text(encoding="utf-8"), out)
        return [out]
    finally:
        try:
            h.unlink()
        except OSError:
            pass


def fb2_to_epub(src: str | Path) -> list[Path]:
    try:
        from ebooklib import epub
    except Exception as e:
        raise UserError(f"Ebook support needs EbookLib: {e}")
    title, paras = _fb2_texts(src)
    book = epub.EpubBook()
    book.set_title(title)
    book.set_language("en")
    c = epub.EpubHtml(title=title, file_name="text.xhtml")
    c.content = "<html><body>" + "".join(f"<p>{html.escape(p)}</p>" for p in paras[:2000]) + "</body></html>"
    book.add_item(c)
    book.toc = [c]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", c]
    out = sibling(src, ext=".epub")
    epub.write_epub(str(out), book)
    return [out]
