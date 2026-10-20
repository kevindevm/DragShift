"""Spreadsheet / data / office / ebook conversions (openpyxl, odfpy, pptx, EbookLib).

Only light deps, no pandas. Every function returns a list of output paths.
"""
from __future__ import annotations

import csv
import html
import io
import json
import sqlite3
from pathlib import Path

from .convert import html_to_pdf, read_text
from .util import UserError, sibling

SHEET_TARGETS = ["CSV", "XLSX", "HTML", "PDF", "TXT"]
PRESENT_TARGETS = ["PDF", "TXT", "HTML"]
EBOOK_TARGETS = ["TXT", "HTML", "PDF", "DOCX"]


def _rows_of_xls(src: str | Path) -> tuple[list[str], list[list]]:
    """Excel 97-2003 via xlrd."""
    try:
        import xlrd
    except Exception as e:
        raise UserError(f"XLS support needs xlrd: {e}")
    try:
        book = xlrd.open_workbook(str(src))
        sh = book.sheet_by_index(0)
    except Exception as e:
        raise UserError(f"Couldn't read spreadsheet: {e}")
    rows = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
    if not rows:
        return [], []
    norm = lambda v: int(v) if isinstance(v, float) and v.is_integer() else ("" if v is None else v)
    header = [str(norm(c)) for c in rows[0]]
    return header, [[norm(c) for c in r] for r in rows[1:]]


def _rows_of_xlsx(src: str | Path) -> tuple[list[str], list[list]]:
    try:
        from openpyxl import load_workbook
    except Exception as e:
        raise UserError(f"Excel support needs openpyxl: {e}")
    wb = load_workbook(src, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return [], []
    header = [(str(c) if c is not None else "") for c in rows[0]]
    return header, [[c if c is not None else "" for c in r] for r in rows[1:]]


def sheet_to_csv(src: str | Path) -> list[Path]:
    ext = Path(src).suffix.lower()
    if ext in (".csv", ".tsv", ".tab", ".psv"):
        from .convert import read_text
        out = sibling(src, "Normalized", ".csv")
        out.write_text(read_text(src).replace("\r\n", "\n"), encoding="utf-8")
        return [out]
    if ext in (".xlsx", ".xls"):
        header, rows = _rows_of_xlsx(src) if ext == ".xlsx" else _rows_of_xls(src)
        out = sibling(src, ext=".csv")
        with out.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if header:
                w.writerow(header)
            w.writerows(rows)
        return [out]
    if ext in (".sqlite", ".sqlite3", ".db"):
        return sqlite_to_csv(src)
    # .ods -> read via odfpy then write csv
    header, rows = ods_rows(src)
    out = sibling(src, ext=".csv")
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if header:
            w.writerow(header)
        w.writerows(rows)
    return [out]


def ods_rows(src: str | Path) -> tuple[list[str], list[list]]:
    try:
        from odf.opendocument import load
        from odf.table import Table, TableRow, TableCell
        from odf.text import P
    except Exception as e:
        raise UserError(f"ODS support needs odfpy: {e}")
    doc = load(str(src))
    tables = doc.getElementsByType(Table)
    if not tables:
        raise UserError("No tables found in this ODS file.")
    rows: list[list] = []
    for row in tables[0].getElementsByType(TableRow):
        vals = []
        for cell in row.getElementsByType(TableCell):
            repeat = int(cell.getAttribute("numbercolumnsrepeated") or 1)
            text = "".join(p.firstChild.data if p.firstChild else ""
                           for p in cell.getElementsByType(P) if p.firstChild)
            vals += [text] * repeat
        rows.append(vals)
    return rows[0] if rows else [], rows[1:] if len(rows) > 1 else []


def csv_to_xlsx(src: str | Path) -> list[Path]:
    try:
        from openpyxl import Workbook
    except Exception as e:
        raise UserError(f"Excel support needs openpyxl: {e}")
    text = read_text(src)
    try:
        dialect = csv.Sniffer().sniff(text[:8000], delimiters=[",", ";", "\t", "|"])
    except csv.Error:
        dialect = csv.excel
    wb = Workbook()
    ws = wb.active
    ws.title = Path(src).stem[:31] or "Sheet1"
    for row in csv.reader(io.StringIO(text), dialect):
        ws.append(row)
    out = sibling(src, ext=".xlsx")
    wb.save(out)
    return [out]


def sqlite_tables(src: str | Path) -> list[str]:
    con = sqlite3.connect(str(src))
    try:
        return [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    finally:
        con.close()


def sqlite_to_csv(src: str | Path, table: str | None = None) -> list[Path]:
    tables = sqlite_tables(src)
    if not tables:
        raise UserError("No tables found in this database.")
    table = table or tables[0]
    con = sqlite3.connect(str(src))
    try:
        cur = con.execute(f'SELECT * FROM "{table.replace(chr(34), chr(34)*2)}"')
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    finally:
        con.close()
    out = sibling(src, table, ".csv")
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)
    return [out]


def sheet_to_html(src: str | Path) -> list[Path]:
    from .convert import read_text
    ext = Path(src).suffix.lower()
    if ext == ".xlsx":
        header, rows = _rows_of_xlsx(src)
    elif ext == ".xls":
        header, rows = _rows_of_xls(src)
    elif ext in (".sqlite", ".sqlite3", ".db"):
        csvp = sqlite_to_csv(src)[0]
        text = csvp.read_text(encoding="utf-8")
        header, *rows = list(csv.reader(io.StringIO(text)))
        csvp.unlink()
    elif ext == ".ods":
        header, rows = ods_rows(src)
    else:  # .csv/.tsv/.tab plain table
        text = read_text(src)
        try:
            dialect = csv.Sniffer().sniff(text[:8000], delimiters=[",", ";", "\t", "|"])
        except csv.Error:
            dialect = csv.excel
        parsed = list(csv.reader(io.StringIO(text), dialect))
        header, rows = (parsed[0], parsed[1:]) if parsed else ([], [])
    cells = "".join(f"<th>{html.escape(str(c))}</th>" for c in header)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>"
                   for r in rows[:5000])
    out = sibling(src, ext=".html")
    out.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(Path(src).name)}"
                   f"</title></head><body><table border='1'><tr>{cells}</tr>{body}</table></body></html>",
                   encoding="utf-8")
    return [out]


def sheet_to_pdf(src: str | Path) -> list[Path]:
    h, t = sheet_to_html(src)[0], None
    try:
        out = sibling(src, ext=".pdf")
        html_to_pdf(h.read_text(encoding="utf-8"), out)
        return [out]
    finally:
        try:
            h.unlink()
        except OSError:
            pass


def sheet_to_txt(src: str | Path) -> list[Path]:
    csvp = sheet_to_csv(src)[0]
    out = sibling(src, ext=".txt")
    out.write_text(csvp.read_text(encoding="utf-8"), encoding="utf-8")
    return [out]


def sheet_to_json(src: str | Path) -> list[Path]:
    ext = Path(src).suffix.lower()
    if ext == ".xlsx":
        header, rows = _rows_of_xlsx(src)
    elif ext == ".xls":
        header, rows = _rows_of_xls(src)
    elif ext in (".sqlite", ".sqlite3", ".db"):
        csvp = sqlite_to_csv(src)[0]
        text = csvp.read_text(encoding="utf-8")
        parsed = list(csv.reader(io.StringIO(text)))
        csvp.unlink()
        header, rows = (parsed[0], parsed[1:]) if parsed else ([], [])
    elif ext == ".ods":
        header, rows = ods_rows(src)
    else:
        from .convert import read_text
        text = read_text(src)
        try:
            dialect = csv.Sniffer().sniff(text[:8000], delimiters=[",", ";", "\t", "|"])
        except csv.Error:
            dialect = csv.excel
        parsed = list(csv.reader(io.StringIO(text), dialect))
        header, rows = (parsed[0], parsed[1:]) if parsed else ([], [])
    data = [dict(zip(header, [c if c != "" else None for c in r])) for r in rows]
    out = sibling(src, ext=".json")
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return [out]


def _odp_texts(src: str | Path) -> list[str] | None:
    """Slide texts from an ODP via odfpy (fallback when pptx can't read it)."""
    if Path(src).suffix.lower() != ".odp":
        return None
    try:
        from odf.opendocument import load
        from odf.draw import Page
        from odf.text import P
    except Exception as e:
        raise UserError(f"ODP support needs odfpy: {e}")
    try:
        doc = load(str(src))
    except Exception as e:
        raise UserError(f"Couldn't read presentation: {e}")
    texts = []
    for page in doc.getElementsByType(Page):
        for p in page.getElementsByType(P):
            t = "".join(n.data for n in p.childNodes if hasattr(n, "data")).strip()
            if t:
                texts.append(t)
    return texts


def odt_text(src: str | Path) -> str:
    try:
        from odf.opendocument import load
        from odf.text import P
    except Exception as e:
        raise UserError(f"ODT support needs odfpy: {e}")
    try:
        doc = load(str(src))
    except Exception as e:
        raise UserError(f"Couldn't read document: {e}")
    return "\n".join("".join(n.data for n in p.childNodes if hasattr(n, "data"))
                     for p in doc.getElementsByType(P))


def odt_to_txt(src: str | Path) -> list[Path]:
    out = sibling(src, ext=".txt")
    out.write_text(odt_text(src), encoding="utf-8")
    return [out]


def odt_to_html(src: str | Path) -> list[Path]:
    out = sibling(src, ext=".html")
    out.write_text("<!doctype html><html><head><meta charset='utf-8'></head><body><pre>"
                   + html.escape(odt_text(src)) + "</pre></body></html>", encoding="utf-8")
    return [out]


def odt_to_pdf(src: str | Path) -> list[Path]:
    from .convert import html_to_pdf
    h = odt_to_html(src)[0]
    try:
        out = sibling(src, ext=".pdf")
        html_to_pdf(h.read_text(encoding="utf-8"), out)
        return [out]
    finally:
        try:
            h.unlink()
        except OSError:
            pass


def pdf_to_pptx(src: str | Path) -> list[Path]:
    """One picture per slide + page text in speaker notes."""
    try:
        from pptx import Presentation
        from pptx.util import Inches
    except Exception as e:
        raise UserError(f"Slides support needs python-pptx: {e}")
    from .convert import fitz, open_pdf
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    with open_pdf(src) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=150, alpha=False)
            from PIL import Image
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            import io as _io
            buf = _io.BytesIO()
            im.save(buf, "PNG")
            buf.seek(0)
            slide = prs.slides.add_slide(blank)
            left = top = Inches(0.25)
            max_w, max_h = Inches(12.833), Inches(7.0)
            scale = min(max_w / pix.width, max_h / pix.height, 1.0)
            slide.shapes.add_picture(buf, left, top, width=int(pix.width * scale), height=int(pix.height * scale))
            try:
                slide.notes_slide.placeholders[1].text = page.get_text("text")[:2000]
            except Exception:
                pass
    out = sibling(src, ext=".pptx")
    prs.save(out)
    return [out]


def yaml_to_toml(src: str | Path) -> list[Path]:
    try:
        import yaml
    except Exception as e:
        raise UserError(f"YAML support needs PyYAML: {e}")
    try:
        import tomli_w
    except Exception as e:
        raise UserError(f"TOML support needs tomli-w: {e}")
    data = yaml.safe_load(read_text(src))
    if not isinstance(data, dict):
        raise UserError("TOML needs a top-level mapping; this YAML is a list/scalar.")
    out = sibling(src, ext=".toml")
    with out.open("wb") as f:
        tomli_w.dump(data, f)
    return [out]


def _slide_title(slide) -> str:
    for shape in slide.shapes:
        try:
            if shape.is_placeholder and shape.placeholder_format.type in (1, 2, 3):
                t = (shape.text or "").strip()
                if t:
                    return t
        except Exception:
            pass
    return ""


def _para_level(par) -> int:
    try:
        return int(par.level or 0)
    except Exception:
        return 0


def present_to_txt(src: str | Path) -> list[Path]:
    try:
        from pptx import Presentation
        prs = Presentation(str(src))
    except Exception:
        texts = _odp_texts(src)
        if texts is None:
            raise
        out = sibling(src, ext=".txt")
        out.write_text("\n".join(texts).strip() + "\n", encoding="utf-8")
        return [out]
    lines = []
    for i, slide in enumerate(prs.slides, 1):
        title = _slide_title(slide)
        lines.append(f"--- Slide {i}{(': ' + title) if title else ''} ---")
        for shape in slide.shapes:
            try:
                if shape.has_table:
                    for row in shape.table.rows:
                        lines.append(" | ".join(c.text.strip().replace("\n", " ") for c in row.cells))
                elif shape.has_text_frame:
                    for par in shape.text_frame.paragraphs:
                        t = (par.text or "").strip()
                        if t and t != title:
                            lines.append("  " * min(_para_level(par), 3) + ("• " if _para_level(par) else "") + t)
            except Exception:
                continue
    out = sibling(src, ext=".txt")
    out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return [out]


def present_to_html(src: str | Path) -> list[Path]:
    try:
        from pptx import Presentation
        prs = Presentation(str(src))
    except Exception:
        texts = _odp_texts(src)
        if texts is None:
            raise
        out = sibling(src, ext=".html")
        out.write_text("<!doctype html><html><head><meta charset='utf-8'></head><body>"
                       + "".join(f"<p>{html.escape(t)}</p>" for t in texts) + "</body></html>",
                       encoding="utf-8")
        return [out]
    parts = []
    for i, slide in enumerate(prs.slides, 1):
        title = _slide_title(slide)
        parts.append(f"<h2>Slide {i}{(': ' + html.escape(title)) if title else ''}</h2>")
        for shape in slide.shapes:
            try:
                if shape.has_table:
                    rows = []
                    for row in shape.table.rows:
                        cells = "".join(f"<td>{html.escape(c.text.strip().replace(chr(10), ' '))}</td>"
                                        for c in row.cells)
                        rows.append(f"<tr>{cells}</tr>")
                    parts.append("<table border='1' cellspacing='0' cellpadding='4'>" + "".join(rows) + "</table>")
                elif shape.has_text_frame:
                    for par in shape.text_frame.paragraphs:
                        t = (par.text or "").strip()
                        if not t or (title and t == title):
                            continue
                        lvl = min(_para_level(par), 6)
                        if lvl:
                            parts.append(f"<p style='margin-left:{lvl * 24}px'>• {html.escape(t)}</p>")
                        else:
                            b = "".join(f"<b>{html.escape(r.text)}</b>" if r.font.bold else html.escape(r.text or "")
                                        for r in par.runs) or html.escape(t)
                            parts.append(f"<p>{b}</p>")
                elif shape.shape_type == 13:  # picture
                    try:
                        import base64 as _b64
                        blob, ext = shape.image.blob, shape.image.ext
                        mime = "jpeg" if ext.lower() in ("jpg", "jpeg") else "png"
                        parts.append(f"<img src='data:image/{mime};base64,{_b64.b64encode(blob).decode()}' "
                                     f"style='max-width:100%'>")
                    except Exception:
                        pass
            except Exception:
                continue
    out = sibling(src, ext=".html")
    out.write_text("<!doctype html><html><head><meta charset='utf-8'></head><body>"
                   + "\n".join(parts) + "</body></html>", encoding="utf-8")
    return [out]


def present_to_pdf(src: str | Path) -> list[Path]:
    h = present_to_html(src)[0]
    try:
        out = sibling(src, ext=".pdf")
        html_to_pdf(h.read_text(encoding="utf-8"), out)
        return [out]
    finally:
        try:
            h.unlink()
        except OSError:
            pass


def yaml_to_json(src: str | Path) -> list[Path]:
    try:
        import yaml
    except Exception as e:
        raise UserError(f"YAML support needs PyYAML: {e}")
    data = yaml.safe_load(read_text(src))
    out = sibling(src, ext=".json")
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return [out]
