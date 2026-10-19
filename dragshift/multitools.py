"""Multi-file creative flows: contact sheet, GIF, merge Excel, portfolio PDF."""
from __future__ import annotations

from pathlib import Path

from .convert import open_image
from .util import UserError, sibling


def _need_images(srcs: list[str | Path], minimum: int = 2) -> list[str]:
    if not srcs:
        raise UserError("Select at least 2 images.")
    if len(srcs) < minimum:
        raise UserError(f"Select at least {minimum} images.")
    return [str(s) for s in srcs]


def contact_sheet(srcs: list[str | Path], thumb: int = 400) -> Path:
    from PIL import Image
    import math
    srcs = _need_images(srcs)
    ims = []
    for s in srcs:
        im = open_image(s).convert("RGB")
        im.thumbnail((thumb, thumb), Image.LANCZOS)
        ims.append(im)
    cols = math.ceil(math.sqrt(len(ims)))
    rows = math.ceil(len(ims) / cols)
    sheet = Image.new("RGB", (cols * thumb, rows * thumb), (20, 20, 28))
    for i, im in enumerate(ims):
        x, y = (i % cols) * thumb, (i // cols) * thumb
        sheet.paste(im, (x + (thumb - im.width) // 2, y + (thumb - im.height) // 2))
    out = sibling(srcs[0], "Contact Sheet", ".jpg")
    sheet.save(out, "JPEG", quality=88)
    return out


def images_to_gif(srcs: list[str | Path]) -> Path:
    from PIL import Image
    srcs = _need_images(srcs)
    frames = []
    for s in srcs[:30]:
        im = open_image(s).convert("RGB")
        im.thumbnail((800, 800), Image.LANCZOS)
        frames.append(im)
    out = sibling(srcs[0], "Animated", ".gif")
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=500, loop=0)
    return out


def merge_csv_xlsx(srcs: list[str | Path]) -> Path:
    from openpyxl import Workbook
    import csv
    from .convert import read_text
    wb = Workbook()
    wb.remove(wb.active)
    for s in srcs:
        p = Path(s)
        ws = wb.create_sheet((p.stem[:31] or "Sheet"))
        if p.suffix.lower() == ".xlsx":
            from openpyxl import load_workbook
            src_wb = load_workbook(s, read_only=True, data_only=True)
            for row in src_wb.active.iter_rows(values_only=True):
                ws.append(list(row))
            src_wb.close()
        else:
            text = read_text(s)
            try:
                dialect = csv.Sniffer().sniff(text[:8000], delimiters=[",", ";", "\t", "|"])
            except csv.Error:
                dialect = csv.excel
            for row in csv.reader(text.splitlines(), dialect):
                ws.append(row)
    out = sibling(srcs[0], "Merged", ".xlsx")
    wb.save(out)
    return [out] if isinstance(out, Path) else out


def merge_to_single_pdf(srcs: list[str | Path]) -> Path:
    """Portfolio: text/code/sheets -> single PDF (images appended too)."""
    from .convert import html_to_pdf, open_image
    import html as ihtml
    from .convert import read_text
    parts = [f"<h1>Bundle ({len(srcs)} files)</h1>"]
    for s in srcs:
        p = Path(s)
        parts.append(f"<h2>{ihtml.escape(p.name)}</h2>")
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            continue  # images appended as pages below
        try:
            parts.append(f"<pre>{ihtml.escape(read_text(s)[:20000])}</pre>")
        except Exception:
            parts.append("<p><i>(binary, skipped)</i></p>")
    out = sibling(srcs[0], "Portfolio", ".pdf")
    html_to_pdf("\n".join(parts), out)
    # append images + existing pdfs
    try:
        from .convert import fitz
        doc = fitz.open(out)
        for s in srcs:
            p = Path(s)
            if p.suffix.lower() == ".pdf":
                with fitz.open(s) as d:
                    doc.insert_pdf(d)
            elif p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
                im = open_image(s).convert("RGB")
                rect = fitz.paper_rect("letter")
                pix = fitz.Pixmap(fitz.csRGB, [int(v) for v in im.tobytes()], im.width, im.height, False)
                page = doc.new_page(width=rect.width, height=rect.height)
                page.insert_image(rect, pixmap=pix)
        doc.save(out.with_name(out.stem + " tmp.pdf"))
        doc.close()
        out.with_name(out.stem + " tmp.pdf").replace(out)
    except Exception:
        pass
    return out
