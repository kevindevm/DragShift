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
    f.flavor = "woff2" if target == "WOFF2" else "woff"
    out = sibling(src, ext="." + target.lower())
    f.save(out)
    return [out]


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
