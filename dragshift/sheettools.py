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
    if ext == ".xlsx":
        header, rows = _rows_of_xlsx(src)
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
        lines.append(f"--- Slide {i} ---")
        for shape in slide.shapes:
            if shape.has_text_frame:
                t = shape.text.strip()
                if t:
                    lines.append(t)
    out = sibling(src, ext=".txt")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
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
        parts.append(f"<h2>Slide {i}</h2>")
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text.strip():
                parts.append(f"<p>{html.escape(shape.text.strip())}</p>")
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
