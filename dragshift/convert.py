"""Format conversions. Every function takes a source path and returns a list of
output paths written next to the source."""
from __future__ import annotations

import html
import io
import sys
from pathlib import Path

from PIL import Image, ImageOps

from .util import UserError, sibling

try:  # HEIC / HEIF support
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF_OK = True
except Exception:  # pragma: no cover
    HEIF_OK = False

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore

IMAGE_TARGETS = ["PNG", "JPG", "WEBP", "HEIC", "TIFF", "AVIF", "BMP", "PDF", "ICO", "GIF"]
PDF_TARGETS = ["JPG", "PNG", "DOCX", "TXT", "HTML", "PPTX"]
DOCX_TARGETS = ["PDF", "TXT", "HTML"]
TEXT_TARGETS = ["PDF", "DOCX", "TXT", "HTML"]
AUDIO_TARGETS = ["MP3", "WAV", "OGG", "OPUS", "FLAC", "M4A"]
VIDEO_TARGETS = ["MP4", "WEBM", "MKV", "MP3", "WAV", "GIF", "PNG", "JPG", "SRT", "VTT"]
SHEET_TARGETS = ["CSV", "XLSX", "HTML", "PDF", "TXT", "JSON", "VCF"]
PRESENT_TARGETS = ["PDF", "TXT", "HTML", "PPTX"]
EBOOK_TARGETS = ["TXT", "HTML", "PDF", "DOCX", "EPUB"]
SUBTITLE_TARGETS = ["SRT", "VTT", "TXT", "LRC"]
NOTEBOOK_TARGETS = ["PY", "HTML", "TXT", "PDF"]
EMAIL_TARGETS = ["TXT", "HTML", "PDF"]
CONTACT_TARGETS = ["CSV", "TXT", "HTML"]
FONT_TARGETS = ["PNG", "PDF", "TXT", "WOFF", "WOFF2", "TTF"]
ARCHIVE_TARGETS = ["FOLDER", "ZIP", "TAR.GZ", "7Z"]
LEGACY_TARGETS = ["PDF"]

PIL_FORMAT = {"PNG": "PNG", "JPG": "JPEG", "WEBP": "WEBP", "HEIC": "HEIF", "TIFF": "TIFF",
              "AVIF": "AVIF", "BMP": "BMP", "PDF": "PDF", "ICO": "ICO", "GIF": "GIF"}
NO_ALPHA = {"JPG", "PDF", "BMP"}


# ---------------------------------------------------------------- images
def open_image(path: str | Path) -> Image.Image:
    im = Image.open(path)
    im.seek(0)
    im = ImageOps.exif_transpose(im)  # honour camera rotation
    im.load()
    if im.mode in ("P", "LA", "PA"):
        im = im.convert("RGBA")
    elif im.mode not in ("RGB", "RGBA", "L"):
        im = im.convert("RGB")
    return im


def open_preview(path: str | Path, max_side: int = 1400) -> Image.Image:
    """Fast, reduced-size decode for on-screen previews (JPEG decodes at 1/2, 1/4, 1/8 scale)."""
    im = Image.open(path)
    im.seek(0)
    if im.format == "JPEG":
        im.draft("RGB", (max_side, max_side))
    im = ImageOps.exif_transpose(im)
    im.load()
    if im.mode in ("P", "LA", "PA"):
        im = im.convert("RGBA")
    elif im.mode not in ("RGB", "RGBA", "L"):
        im = im.convert("RGB")
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side), Image.LANCZOS)
    return im


def open_pdf(path: str | Path):
    doc = fitz.open(path)
    if doc.needs_pass:
        doc.close()
        raise UserError("This PDF is password-protected. Remove the password first.")
    return doc


def flatten(im: Image.Image, bg=(255, 255, 255)) -> Image.Image:
    if im.mode == "RGBA":
        base = Image.new("RGB", im.size, bg)
        base.paste(im, mask=im.split()[3])
        return base
    return im.convert("RGB") if im.mode != "RGB" else im


def save_image(im: Image.Image, out: Path, target: str, quality: int | None = None, exif=None) -> None:
    from .util import CONFIG
    quality = quality or int(CONFIG.get("jpg_quality", 90))
    target = target.upper()
    fmt = PIL_FORMAT[target]
    if target in NO_ALPHA:
        im = flatten(im)
    kw: dict = {}
    if target in ("JPG", "WEBP", "AVIF", "HEIC"):
        kw["quality"] = quality
    if target == "JPG":
        kw.update(optimize=True, progressive=True)
    if target == "PNG":
        kw["optimize"] = True
    if target == "ICO":
        side = min(256, max(im.size))
        im = ImageOps.contain(im.convert("RGBA"), (side, side))
        kw["sizes"] = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= side]
    if target == "PDF":
        kw["resolution"] = 150.0
    if exif and target in ("JPG", "WEBP", "PNG", "TIFF"):
        kw["exif"] = exif
    atomic_save(lambda dst: im.save(dst, fmt, **kw), out)


def atomic_save(write, out):
    """Write to a hidden temp file, then rename: Explorer never shows a half-written file."""
    import os
    if not isinstance(out, (str, Path)):
        write(out)  # in-memory buffer
        return
    out = Path(out)
    tmp = out.with_name(f".~{out.name}.{os.getpid()}.part")
    try:
        write(tmp)
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def image_to(src: str | Path, target: str) -> list[Path]:
    target = target.upper()
    im = open_image(src)
    out = sibling(src, ext="." + target.lower())
    save_image(im, out, target)
    return [out]


def svg_to_image(src: str | Path, target: str) -> list[Path]:
    """Rasterize an SVG via PyMuPDF (no extra deps)."""
    target = target.upper()
    if target not in ("PNG", "JPG", "WEBP", "BMP", "TIFF", "PDF"):
        raise ValueError(f"Can't convert SVG to {target}")
    with fitz.open(src) as doc:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    out = sibling(src, ext="." + target.lower())
    save_image(im, out, target)
    return [out]


def images_to_single_pdf(srcs: list[str | Path]) -> list[Path]:
    pages = [flatten(open_image(s)) for s in srcs]
    out = sibling(srcs[0], "Combined", ".pdf")
    pages[0].save(out, "PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    return [out]


# ---------------------------------------------------------------- PDF
def pdf_to_images(src: str | Path, target: str, dpi: int | None = None) -> list[Path]:
    from .util import CONFIG
    dpi = dpi or int(CONFIG.get("pdf_dpi", 200))
    target = target.upper()
    outs = []
    with open_pdf(src) as doc:
        n = doc.page_count
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            label = f"page {i + 1}" if n > 1 else ""
            out = sibling(src, label, "." + target.lower())
            save_image(im, out, target)
            outs.append(out)
    return outs


def pdf_to_txt(src: str | Path) -> list[Path]:
    with open_pdf(src) as doc:
        text = "\n\f\n".join(page.get_text("text") for page in doc)
    out = sibling(src, ext=".txt")
    out.write_text(text, encoding="utf-8")
    return [out]


def pdf_to_html(src: str | Path) -> list[Path]:
    with open_pdf(src) as doc:
        parts = [page.get_text("xhtml") for page in doc]
    out = sibling(src, ext=".html")
    out.write_text("<!doctype html>\n<html><head><meta charset='utf-8'>\n"
                   f"<title>{html.escape(Path(src).name)}</title></head>\n<body>\n"
                   + "\n<hr>\n".join(parts) + "\n</body></html>", encoding="utf-8")
    return [out]


def pdf_to_docx(src: str | Path) -> list[Path]:
    """Text blocks become paragraphs, embedded images are kept, one Word page per PDF page."""
    from docx import Document
    from docx.enum.text import WD_BREAK
    from docx.shared import Inches

    d = Document()
    with open_pdf(src) as doc:
        for pno, page in enumerate(doc):
            if pno:
                d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            items = []
            for b in page.get_text("dict")["blocks"]:
                y = b["bbox"][1]
                if b.get("type") == 0:
                    lines = []
                    size = 11.0
                    bold = False
                    for ln in b["lines"]:
                        spans = ln["spans"]
                        if spans:
                            size = max(size, max(s["size"] for s in spans)) if not lines else size
                            bold = bold or any("Bold" in s["font"] for s in spans)
                        lines.append("".join(s["text"] for s in spans))
                    txt = " ".join(l.strip() for l in lines).strip()
                    if txt:
                        items.append((y, "text", (txt, size, bold)))
                elif b.get("type") == 1 and b.get("image"):
                    items.append((y, "img", (b["image"], b["bbox"])))
            items.sort(key=lambda t: t[0])
            for _, kind, data in items:
                if kind == "text":
                    txt, size, bold = data
                    if size >= 16:
                        d.add_heading(txt, level=1 if size >= 20 else 2)
                    else:
                        p = d.add_paragraph()
                        r = p.add_run(txt)
                        r.bold = bold and len(txt) < 120
                else:
                    raw, bbox = data
                    width_in = min(6.5, max(0.5, (bbox[2] - bbox[0]) / 72))
                    try:
                        d.add_picture(io.BytesIO(raw), width=Inches(width_in))
                    except Exception:
                        pass
    out = sibling(src, ext=".docx")
    d.save(out)
    return [out]


# ---------------------------------------------------------------- DOCX
def _docx_paragraph_html(p) -> str:
    parts = []
    for r in p.runs:
        t = html.escape(r.text)
        if not t:
            continue
        if r.bold:
            t = f"<b>{t}</b>"
        if r.italic:
            t = f"<i>{t}</i>"
        if r.underline:
            t = f"<u>{t}</u>"
        parts.append(t)
    body = "".join(parts) or "&nbsp;"
    style = (p.style.name or "").lower() if p.style is not None else ""
    if style.startswith("heading"):
        lvl = "".join(c for c in style if c.isdigit()) or "1"
        lvl = str(min(int(lvl), 6))
        return f"<h{lvl}>{body}</h{lvl}>"
    if style == "title":
        return f"<h1>{body}</h1>"
    if "list" in style:
        return f"<p>&bull; {body}</p>"
    return f"<p>{body}</p>"


def docx_to_html(src: str | Path) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = Document(src)
    out = []
    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            out.append(_docx_paragraph_html(Paragraph(child, d)))
        elif tag == "tbl":
            t = Table(child, d)
            rows = []
            for row in t.rows:
                cells = "".join(f"<td>{html.escape(c.text)}</td>" for c in row.cells)
                rows.append(f"<tr>{cells}</tr>")
            out.append("<table>" + "".join(rows) + "</table>")
    return "\n".join(out)


def docx_to_txt(src: str | Path) -> list[Path]:
    from docx import Document
    d = Document(src)
    lines = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            lines.append("\t".join(c.text for c in row.cells))
    out = sibling(src, ext=".txt")
    out.write_text("\n".join(lines), encoding="utf-8")
    return [out]


def _word_to_pdf(src: Path, out: Path) -> bool:
    """Use Microsoft Word (if installed) for a perfect-fidelity export."""
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # type: ignore
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        try:
            doc = word.Documents.Open(str(src.resolve()), ReadOnly=True)
            doc.SaveAs(str(out.resolve()), FileFormat=17)  # wdFormatPDF
            doc.Close(False)
        finally:
            word.Quit()
        return out.exists()
    except Exception:
        return False


CSS = """
* { font-family: sans-serif; }
body { font-size: 11pt; line-height: 1.35; }
h1 { font-size: 20pt; } h2 { font-size: 16pt; } h3 { font-size: 13pt; }
p { margin: 0 0 6pt 0; }
pre { font-family: monospace; font-size: 9.5pt; white-space: pre-wrap; }
table { border-collapse: collapse; margin: 6pt 0; }
td { border: 1px solid #888; padding: 3pt 5pt; font-size: 10pt; }
"""


def html_to_pdf(body_html: str, out: Path) -> None:
    story = fitz.Story(html=body_html, user_css=CSS)
    writer = fitz.DocumentWriter(str(out))
    mediabox = fitz.paper_rect("letter")
    where = mediabox + (54, 54, -54, -54)
    more = True
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()


def docx_to_pdf(src: str | Path) -> list[Path]:
    src = Path(src)
    out = sibling(src, ext=".pdf")
    if not _word_to_pdf(src, out):
        html_to_pdf(docx_to_html(src), out)
    return [out]


# ---------------------------------------------------------------- text
def read_text(src: str | Path) -> str:
    raw = Path(src).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def text_to_pdf(src: str | Path) -> list[Path]:
    out = sibling(src, ext=".pdf")
    if Path(src).suffix.lower() in (".html", ".htm"):
        html_to_pdf(read_text(src), out)
    else:
        html_to_pdf(f"<pre>{html.escape(read_text(src))}</pre>", out)
    return [out]


def text_to_docx(src: str | Path) -> list[Path]:
    from docx import Document
    from docx.shared import Pt
    import re as _re
    ext = Path(src).suffix.lower()
    d = Document()
    if ext in (".md", ".markdown"):
        for ln in read_text(src).splitlines():
            s = ln.rstrip()
            m = _re.match(r"^(#{1,6})\s+(.*)", s)
            if m:
                d.add_heading(m.group(2), level=min(len(m.group(1)), 6))
                continue
            if _re.match(r"^(\*|-)\s+", s):
                d.add_paragraph(_re.sub(r"^(\*|-)\s+", "", s), style="List Bullet")
                continue
            if not s.strip():
                continue
            p = d.add_paragraph()
            for chunk in _re.split(r"(\*\*.+?\*\*)", s):
                if chunk.startswith("**") and chunk.endswith("**"):
                    p.add_run(chunk[2:-2]).bold = True
                else:
                    p.add_run(chunk)
    elif ext in (".html", ".htm"):
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(read_text(src), "lxml")
            body = soup.body or soup
            for el in body.descendants:
                if getattr(el, "name", None) in ("h1", "h2", "h3"):
                    lvl = int(el.name[1])
                    d.add_heading(el.get_text(), level=min(lvl, 6))
                elif getattr(el, "name", None) == "p" and el.get_text(strip=True):
                    d.add_paragraph(el.get_text())
                elif getattr(el, "name", None) == "li" and el.get_text(strip=True):
                    d.add_paragraph(el.get_text(), style="List Bullet")
            if not d.paragraphs:
                for line in read_text(src).splitlines():
                    d.add_paragraph(line)
        except Exception:
            for line in read_text(src).splitlines():
                d.add_paragraph(line)
    else:
        for line in read_text(src).splitlines():
            d.add_paragraph(line)
    out = sibling(src, ext=".docx")
    d.save(out)
    return [out]


def text_to_txt(src: str | Path) -> list[Path]:
    """Normalised UTF-8 + LF copy (handy for .env / .gitignore / CRLF sources)."""
    if Path(src).suffix.lower() in (".html", ".htm"):
        from . import texttools
        return [texttools.html_to_txt(src)]
    text = read_text(src).replace("\r\n", "\n").replace("\r", "\n")
    if Path(src).suffix.lower() == ".txt":
        out = sibling(src, "Normalized", ".txt")
    else:
        out = sibling(src, ext=".txt")
    out.write_text(text, encoding="utf-8", newline="\n")
    return [out]


def text_to_html(src: str | Path) -> list[Path]:
    """Standalone HTML. Markdown gets headings/bold/code/lists; rest goes in <pre>."""
    out = sibling(src, ext=".html")
    raw = read_text(src)
    if Path(src).suffix.lower() in (".md", ".markdown"):
        import re as _re
        body = []
        in_list, in_code = False, False
        for ln in raw.split("\n"):
            s = ln.rstrip()
            if s.strip().startswith("```"):
                body.append("</pre>" if in_code else "<pre>")
                in_code = not in_code
                continue
            if in_code:
                body.append(html.escape(s))
                continue
            m = _re.match(r"^(#{1,6})\s+(.*)", s)
            if m:
                lvl = len(m.group(1))
                body.append(f"<h{lvl}>{html.escape(m.group(2))}</h{lvl}>")
                continue
            if _re.match(r"^(\*|-)\s+", s):
                if not in_list:
                    body.append("<ul>")
                    in_list = True
                body.append(f"<li>{html.escape(_re.sub(r'^(\*|-)\s+', '', s))}</li>")
                continue
            if in_list:
                body.append("</ul>")
                in_list = False
            if not s.strip():
                body.append("")
                continue
            s = html.escape(s)
            s = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
            s = _re.sub(r"`(.+?)`", r"<code>\1</code>", s)
            body.append(f"<p>{s}</p>")
        if in_list:
            body.append("</ul>")
        inner = "\n".join(body)
    else:
        inner = f"<pre>{html.escape(raw)}</pre>"
    out.write_text(f"<!doctype html>\n<html><head><meta charset=\"utf-8\">\n"
                   f"<title>{html.escape(Path(src).name)}</title>\n"
                   f"<style>body{{font-family:sans-serif;margin:2em;max-width:60em}}"
                   f"pre{{background:#f4f4f4;padding:1em;white-space:pre-wrap}}"
                   f"code{{background:#f4f4f4}}</style>\n"
                   f"</head><body>{inner}</body></html>\n",
                   encoding="utf-8", newline="\n")
    return [out]


def sheet_convert(src: str | Path, target: str) -> list[Path]:
    from . import sheettools
    target = target.upper()
    if target == "CSV":
        return sheettools.sheet_to_csv(src)
    if target == "XLSX":
        if Path(src).suffix.lower() == ".xlsx":
            raise ValueError("Already XLSX")
        return sheettools.csv_to_xlsx(src)
    if target == "HTML":
        return sheettools.sheet_to_html(src)
    if target == "PDF":
        return sheettools.sheet_to_pdf(src)
    if target == "TXT":
        return sheettools.sheet_to_txt(src)
    if target == "JSON":
        return sheettools.sheet_to_json(src)
    if target == "VCF":
        from . import nbtools
        return nbtools.csv_to_vcf(src)
    # YAML/JSON land here via text cat; sheet yaml->json handled in app tools
    raise ValueError(f"Can't convert sheet to {target}")


# ---------------------------------------------------------------- dispatch
def targets_for(cat: str, src_ext: str) -> list[str]:
    src_ext = src_ext.lower().lstrip(".")
    same = {"jpeg": "JPG", "jpg": "JPG", "tif": "TIFF", "tiff": "TIFF", "heif": "HEIC"}
    cur = same.get(src_ext, src_ext.upper())
    if cat == "image":
        t = [x for x in IMAGE_TARGETS if x != cur]
        if not HEIF_OK:
            t = [x for x in t if x != "HEIC"]
        return t
    table = {"pdf": PDF_TARGETS, "docx": DOCX_TARGETS, "text": TEXT_TARGETS,
             "audio": AUDIO_TARGETS, "video": VIDEO_TARGETS, "sheet": SHEET_TARGETS,
             "presentation": PRESENT_TARGETS, "ebook": EBOOK_TARGETS,
             "subtitle": SUBTITLE_TARGETS, "notebook": NOTEBOOK_TARGETS,
             "email": EMAIL_TARGETS, "contact": CONTACT_TARGETS, "font": FONT_TARGETS,
             "archive": ARCHIVE_TARGETS, "legacy": LEGACY_TARGETS}
    t = [x for x in table.get(cat, []) if x != cur]
    if cat == "text":
        low = src_ext
        if low in ("json", "jsonc"):
            t += [x for x in ("YAML", "CSV") if x != cur]
        elif low in ("yaml", "yml"):
            t += [x for x in ("JSON", "TOML") if x != cur]
        elif low == "toml":
            t += [x for x in ("JSON",) if x != cur]
        elif low == "svg":
            t += [x for x in ("PNG", "JPG", "PDF") if x != cur]
    return t


def convert(src: str | Path, cat: str, target: str) -> list[Path]:
    target = target.upper()
    if cat == "image":
        return image_to(src, target)
    if cat == "pdf":
        if target in ("JPG", "PNG"):
            return pdf_to_images(src, target)
        if target == "TXT":
            return pdf_to_txt(src)
        if target == "HTML":
            return pdf_to_html(src)
        if target == "DOCX":
            try:
                from . import engines as _eng
                if _eng._soffice() is not None:
                    return [_eng.libreoffice_convert(src, "docx")]
            except Exception:
                pass  # fall through to the built-in renderer
            return pdf_to_docx(src)
        if target == "PPTX":
            from . import sheettools
            return sheettools.pdf_to_pptx(src)
    if cat == "docx":
        if Path(src).suffix.lower() == ".odt":
            from . import sheettools
            if target == "PDF":
                return sheettools.odt_to_pdf(src)
            if target == "TXT":
                return sheettools.odt_to_txt(src)
            if target == "HTML":
                return sheettools.odt_to_html(src)
        if target == "PDF":
            return docx_to_pdf(src)
        if target == "TXT":
            return docx_to_txt(src)
        if target == "HTML":
            out = sibling(src, ext=".html")
            out.write_text(f"<!doctype html>\n<html><head><meta charset='utf-8'>\n"
                           f"<style>{CSS}</style></head><body>{docx_to_html(src)}</body></html>",
                           encoding="utf-8")
            return [out]
    if cat == "text":
        if Path(src).suffix.lower() == ".svg" and target in IMAGE_TARGETS:
            return svg_to_image(src, target)
        if target == "PDF":
            return text_to_pdf(src)
        if target == "DOCX":
            return text_to_docx(src)
        if target == "TXT":
            return text_to_txt(src)
        if target == "HTML":
            return text_to_html(src)
        if target == "YAML":
            from . import texttools
            return texttools.json_to_yaml(src)
        if target == "CSV" and Path(src).suffix.lower() in (".json", ".jsonc"):
            from . import texttools
            return texttools.json_to_csv(src)
        if target == "JSON":
            from . import sheettools
            return [sheettools.yaml_to_json(src)[0]]
        if target == "TOML":
            from . import sheettools
            return sheettools.yaml_to_toml(src)
    if cat == "audio":
        from . import mediatools
        return mediatools.audio_to(src, target)
    if cat == "video":
        from . import mediatools
        return mediatools.video_to(src, target)
    if cat == "sheet":
        return sheet_convert(src, target)
    if cat == "presentation":
        from . import sheettools
        if target == "TXT":
            return sheettools.present_to_txt(src)
        if target == "HTML":
            return sheettools.present_to_html(src)
        if target == "PDF":
            try:
                from . import engines as _eng
                if _eng._soffice() is not None:
                    return [_eng.libreoffice_convert(src, "pdf")]
            except Exception:
                pass  # fall through to the built-in renderer
            return sheettools.present_to_pdf(src)
    if cat == "ebook":
        from . import nbtools
        if Path(src).suffix.lower() == ".cbz":
            if target == "PDF":
                return nbtools.cbz_to_pdf(src)
            if target == "EPUB":
                return nbtools.cbz_to_epub(src)
            raise ValueError(f"Can't convert CBZ to {target}")
        if Path(src).suffix.lower() == ".fb2":
            if target == "TXT":
                return nbtools.fb2_to_txt(src)
            if target == "HTML":
                return nbtools.fb2_to_html(src)
            if target == "PDF":
                return nbtools.fb2_to_pdf(src)
            if target == "EPUB":
                return nbtools.fb2_to_epub(src)
            if target == "DOCX":
                h = nbtools.fb2_to_html(src)[0]
                try:
                    from .convert import html_to_pdf  # noqa
                    from docx import Document as _D
                    from bs4 import BeautifulSoup as _B
                    soup = _B(h.read_text(encoding="utf-8"), "lxml")
                    d = _D()
                    for p in soup.find_all(["h1", "h2", "p"]):
                        if p.name in ("h1", "h2"):
                            d.add_heading(p.get_text(), level=1 if p.name == "h1" else 2)
                        elif p.get_text(strip=True):
                            d.add_paragraph(p.get_text())
                    out = sibling(src, ext=".docx")
                    d.save(out)
                    return [out]
                finally:
                    try:
                        h.unlink()
                    except OSError:
                        pass
        from . import sheettools
        try:
            import ebooklib
            from ebooklib import epub
            from bs4 import BeautifulSoup
        except Exception as e:
            from .util import UserError
            raise UserError(f"Ebook support needs EbookLib+bs4: {e}")
        book = epub.read_epub(str(src))
        texts = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "lxml")
            texts.append(soup.get_text("\n"))
        full = "\n".join(texts) or "(empty ebook)"
        if target == "TXT":
            out = sibling(src, ext=".txt")
            out.write_text(full, encoding="utf-8")
            return [out]
        if target == "HTML":
            out = sibling(src, ext=".html")
            out.write_text(f"<!doctype html><html><head><meta charset='utf-8'></head>"
                           f"<body><pre>{html.escape(full)}</pre></body></html>", encoding="utf-8")
            return [out]
        if target == "PDF":
            out = sibling(src, ext=".pdf")
            html_to_pdf(f"<pre>{html.escape(full[:30000])}</pre>", out)
            return [out]
        if target == "DOCX":
            from docx import Document
            d = Document()
            for line in full.splitlines()[:2000]:
                d.add_paragraph(line)
            out = sibling(src, ext=".docx")
            d.save(out)
            return [out]
    if cat == "subtitle":
        from . import texttools
        if target in ("SRT", "VTT"):
            return texttools.subtitles_convert(src, target)
        if target == "TXT":
            return [texttools.subtitles_to_txt(src)]
    if cat == "notebook":
        from . import nbtools
        if target == "PY":
            return nbtools.ipynb_to_py(src)
        if target == "TXT":
            return nbtools.ipynb_to_txt(src)
        if target == "HTML":
            return nbtools.ipynb_to_html(src)
        if target == "PDF":
            return nbtools.ipynb_to_pdf(src)
    if cat == "email":
        from . import nbtools
        is_msg = Path(src).suffix.lower() == ".msg"
        if target == "TXT":
            return nbtools.msg_to_txt(src) if is_msg else nbtools.eml_to_txt(src)
        if target == "HTML":
            return nbtools.msg_to_html(src) if is_msg else nbtools.eml_to_html(src)
        if target == "PDF":
            return nbtools.msg_to_pdf(src) if is_msg else nbtools.eml_to_pdf(src)
    if cat == "contact":
        from . import nbtools
        if target == "CSV":
            return nbtools.contact_to_csv(src)
        if target == "TXT":
            return nbtools.contact_to_txt(src)
        if target == "HTML":
            return nbtools.contact_to_html(src)
    if cat == "font":
        from . import nbtools
        if target == "TXT":
            return nbtools.font_info(src)
        if target == "PNG":
            return nbtools.font_specimen(src, "PNG")
        if target == "PDF":
            return nbtools.font_specimen(src, "PDF")
        if target in ("WOFF", "WOFF2"):
            return nbtools.font_convert(src, target)
    if cat == "archive":
        from . import archtools
        if target == "FOLDER":
            return [archtools.arch_extract(src)]
        if target in ("ZIP", "TAR.GZ", "7Z"):
            return [archtools.arch_create([src], target)]
    if cat == "legacy":
        if target == "PDF":
            from . import engines
            return [engines.libreoffice_pdf(src)]
    raise ValueError(f"Can't convert {cat} to {target}")
