"""Print files for a KDP paperback coloring book: interior PDF, wrap-around cover PDF, contact sheet, price.

Interior (8.5 x 11 in, no bleed, black ink): title page, copyright page, "This book belongs to", a blank, then each
picture on a right-hand page with a blank back (markers bleed through paper), then a thank-you page and a blank.
Cover: back + spine + front with 0.125 in bleed on every side; spine width from the page count (white paper,
0.002252 in a page); spine text only above 79 pages (KDP's rule). The back keeps KDP's barcode box (2 x 1.2 in,
bottom right) empty. Every text is set here in code, so spelling is exact; the cover art comes from the Cover Designer.
"""

from __future__ import annotations

import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config import ROOT
from .ebook_art import DPI

FONTS = ROOT / "assets" / "fonts"
TITLE_FONT, BODY_FONT = "LuckiestGuy-Regular.ttf", "NunitoSans.ttf"
PAPER = 0.002252           # in per page, white paper, black ink
BLEED = 0.125
COLORS = ["#F57C00", "#2E7D32", "#1565C0", "#C2185B", "#6A1B9A", "#00838F", "#EF6C00", "#D81B60"]


def font(name: str, px: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    try:
        f = ImageFont.truetype(str(FONTS / name), px)
        if weight is not None:
            try:
                axes = f.get_variation_axes()
                f.set_variation_by_axes([weight if (a.get("name") or b"").lower() in (b"weight", "weight") else a["default"] for a in axes])
            except Exception:
                pass
        return f
    except OSError:
        return ImageFont.load_default(px)


def page_count(pictures: int) -> int:
    return 4 + 2 * pictures + 2


def print_cost(pages: int) -> float:
    """US black-ink paperback, an estimate from KDP's published formula; KDP shows the exact figure at upload."""
    return 2.30 if pages <= 108 else round(1.00 + 0.012 * pages, 2)


def price(pictures: int, pages: int, band=(6.99, 9.99), min_royalty: float = 1.75) -> tuple[float, float]:
    """(list price, royalty a copy): the market band for kids' coloring books by size, never a royalty under
    `min_royalty` (60 % of list less printing)."""
    p = 7.99 if pictures <= 30 else 8.99 if pictures <= 50 else 9.99
    p = max(band[0], min(band[1], p))
    while round(0.6 * p - print_cost(pages), 2) < min_royalty and p < band[1]:
        p = round(p + 1, 2)
    return p, round(0.6 * p - print_cost(pages), 2)


def _center(d: ImageDraw.ImageDraw, y: int, text: str, f, w: int, fill="black") -> int:
    box = d.textbbox((0, 0), text, font=f)
    d.text(((w - (box[2] - box[0])) // 2, y), text, font=f, fill=fill)
    return y + (box[3] - box[1])


def _wrap(d, text: str, f, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if d.textlength(t, font=f) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def _blank(trim) -> Image.Image:
    return Image.new("1", (round(trim[0] * DPI), round(trim[1] * DPI)), 1)


def text_page(trim, lines: list[tuple[str, str, int]], top: float = 0.35) -> Image.Image:
    """lines: (text, font file, px). Centred, black on white."""
    im = Image.new("L", (round(trim[0] * DPI), round(trim[1] * DPI)), 255)
    d = ImageDraw.Draw(im)
    y = round(im.height * top)
    for text, f, px in lines:
        fo = font(f, px, 700 if f == BODY_FONT and px >= 70 else None)
        for line in _wrap(d, text, fo, im.width - 2 * DPI) if text else [""]:
            y = _center(d, y, line, fo, im.width) + round(px * 0.45)
    return im.convert("1")


def belongs_page(trim) -> Image.Image:
    im = text_page(trim, [("This book belongs to", TITLE_FONT, 150)], top=0.3)
    d = ImageDraw.Draw(im)
    y = round(im.height * 0.48)
    d.rounded_rectangle((DPI, y, im.width - DPI, y + 420), radius=90, outline=0, width=14)
    return im


def interior(pages: list[Image.Image], book: dict, out: Path) -> int:
    trim = tuple(book.get("trim") or (8.5, 11.0))
    year = book.get("year") or ""
    front = [text_page(trim, [(book["title"], TITLE_FONT, 190), (book.get("subtitle", ""), BODY_FONT, 80), ("", BODY_FONT, 80),
                              (book["author"], BODY_FONT, 70)]),
             text_page(trim, [(f"{book['title']}", BODY_FONT, 55), (f"Copyright © {year} {book['author']}. All rights reserved.", BODY_FONT, 45),
                              ("No part of this book may be copied or sold without the publisher's permission.", BODY_FONT, 40),
                              ("The pictures were drawn with the help of AI and checked page by page.", BODY_FONT, 40)], top=0.72),
             belongs_page(trim), _blank(trim)]
    body = []
    for p in pages:
        body += [p, _blank(trim)]
    back = [text_page(trim, [("Thank you for colouring with us!", TITLE_FONT, 140), ("", BODY_FONT, 60),
                             (f"More books from {book['author']} are on Amazon.", BODY_FONT, 60)]), _blank(trim)]
    allp = [im.convert("L") for im in front + body + back]
    out.parent.mkdir(parents=True, exist_ok=True)
    allp[0].save(out, "PDF", resolution=DPI, save_all=True, append_images=allp[1:])
    return len(allp)


def spine_in(pages: int) -> float:
    return round(pages * PAPER, 4)


def _title_art(d: ImageDraw.ImageDraw, title: str, box: tuple[int, int, int, int]) -> None:
    """The title in bold rainbow letters with a white outline, sized to fit the box (like the reference cover)."""
    x0, y0, x1, y1 = box
    words = title.upper().split()
    lines = [" ".join(words[i:i + 2]) for i in range(0, len(words), 2)] if len(" ".join(words)) > 12 else [" ".join(words)]
    px = 420
    while px > 80:
        f = font(TITLE_FONT, px)
        if max(d.textlength(l, font=f) for l in lines) <= (x1 - x0) and len(lines) * px * 1.1 <= (y1 - y0):
            break
        px -= 10
    f = font(TITLE_FONT, px)
    y, k = y0, 0
    for line in lines:
        x = x0 + ((x1 - x0) - d.textlength(line, font=f)) / 2
        for ch in line:
            if ch != " ":
                d.text((x, y), ch, font=f, fill=COLORS[k % len(COLORS)], stroke_width=max(8, px // 14), stroke_fill="white")
                k += 1
            x += d.textlength(ch, font=f)
        y += round(px * 1.1)


def cover(art: bytes, samples: list[bytes], book: dict, pages: int, out_pdf: Path, out_png: Path) -> dict:
    trim = tuple(book.get("trim") or (8.5, 11.0))
    sp = spine_in(pages)
    W = round((2 * trim[0] + sp + 2 * BLEED) * DPI)
    H = round((trim[1] + 2 * BLEED) * DPI)
    b, fw = round(BLEED * DPI), round(trim[0] * DPI)
    front_x = b + fw + round(sp * DPI)
    im = Image.new("RGB", (W, H), "#FFF8E7")
    d = ImageDraw.Draw(im)

    # front: the art fills the front panel (with bleed), title and badges over it
    a = Image.open(io.BytesIO(art)).convert("RGB")
    fwb, fhb = W - front_x, H
    s = max(fwb / a.width, fhb / a.height)
    a = a.resize((math.ceil(a.width * s), math.ceil(a.height * s)), Image.LANCZOS)
    im.paste(a.crop(((a.width - fwb) // 2, (a.height - fhb) // 2, (a.width - fwb) // 2 + fwb, (a.height - fhb) // 2 + fhb)), (front_x, 0))
    safe = round(0.375 * DPI)
    sub = font(BODY_FONT, 80, 800)
    sub_lines = _wrap(d, book.get("subtitle", ""), sub, fwb - 2 * safe - 2 * b - 80)[:2]
    panel_h = round(H * 0.22) + len(sub_lines) * 100 + 60
    panel = Image.new("RGBA", (fwb - 2 * b - 2 * safe + 2 * 60, panel_h), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle((0, 0, panel.width - 1, panel.height - 1), radius=80, fill=(255, 255, 255, 215))
    im.paste(panel, (front_x + safe - 60, b + safe - 40), panel)
    _title_art(d, book["title"], (front_x + safe, b + safe, W - b - safe, b + safe + round(H * 0.20)))
    y = b + safe + round(H * 0.21)
    for line in sub_lines:
        d.text((front_x + (fwb - d.textlength(line, font=sub)) / 2, y), line, font=sub, fill="#5D2E0C")
        y += 100
    r = round(1.15 * DPI)
    cx, cy = W - b - safe - r, H - b - safe - r
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill="#6A1B9A", outline="white", width=14)
    for i, (t, px) in enumerate(((str(book["pictures"]), 230), ("BIG PAGES", 80))):
        f = font(TITLE_FONT, px)
        d.text((cx - d.textlength(t, font=f) / 2, cy - (230 if i == 0 else -30)), t, font=f, fill="white")
    ages = font(TITLE_FONT, 110)
    t = f"AGES {book['ages']}"
    d.rounded_rectangle((front_x + safe, H - b - safe - 190, front_x + safe + d.textlength(t, font=ages) + 120, H - b - safe), radius=60, fill="#F57C00", outline="white", width=10)
    d.text((front_x + safe + 60, H - b - safe - 165), t, font=ages, fill="white")
    f = font(BODY_FONT, 60, 700)
    d.text((front_x + safe, H - b - safe - 290), book["author"], font=f, fill="#5D2E0C", stroke_width=5, stroke_fill="white")

    # back: blurb, four sample pages, the author; barcode box left empty
    bx0, bx1 = b + safe, b + fw - safe
    tf = font(TITLE_FONT, 120)
    d.text((bx0, b + safe), "INSIDE THIS BOOK", font=tf, fill="#C2185B")
    bf = font(BODY_FONT, 58, 600)
    y = b + safe + 170
    for line in _wrap(d, book.get("blurb", ""), bf, bx1 - bx0)[:8]:
        d.text((bx0, y), line, font=bf, fill="#3E2723")
        y += 78
    room = H - b - round(1.7 * DPI) - (y + 40)           # above the author line and KDP's barcode box
    th_h = min(room // 2 - 50, round(((bx1 - bx0 - 120) // 3) * 11 / 8.5))
    th_w = round(th_h * 8.5 / 11)
    gx = bx0 + ((bx1 - bx0) - (3 * th_w + 120)) // 2
    for i, smp in enumerate(samples[:6]):
        t = Image.open(io.BytesIO(smp)).convert("RGB")
        t.thumbnail((th_w, th_h))
        px_, py_ = gx + (i % 3) * (th_w + 60), y + 40 + (i // 3) * (th_h + 50)
        d.rectangle((px_ - 8, py_ - 8, px_ + t.width + 8, py_ + t.height + 8), fill="white", outline="#B0BEC5", width=4)
        im.paste(t, (px_, py_))
    d.text((bx0, H - b - safe - 80), book["author"], font=font(BODY_FONT, 55, 700), fill="#5D2E0C")
    if pages > 79:
        sf = font(TITLE_FONT, max(30, round(sp * DPI * 0.6)))
        st = f"{book['title'].upper()}  ·  {book['author']}"
        lay = Image.new("RGBA", (H, round(sp * DPI)), (0, 0, 0, 0))
        ImageDraw.Draw(lay).text((H // 2 - d.textlength(st, font=sf) / 2, 0), st, font=sf, fill="#5D2E0C")
        lay = lay.rotate(-90, expand=True)
        im.paste(lay, (b + fw, 0), lay)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_pdf, "PDF", resolution=DPI)
    prev = im.copy()
    prev.thumbnail((1600, 1600))
    prev.save(out_png)
    return {"width_in": round(W / DPI, 3), "height_in": round(H / DPI, 3), "spine_in": sp}


def contact_sheet(pngs: list[bytes], out: Path, cols: int = 6) -> None:
    tw, th = 260, 336
    rows = math.ceil(len(pngs) / cols) or 1
    sheet = Image.new("RGB", (cols * (tw + 20) + 20, rows * (th + 50) + 20), "white")
    d = ImageDraw.Draw(sheet)
    f = font(BODY_FONT, 22, 700)
    for i, p in enumerate(pngs):
        t = Image.open(io.BytesIO(p)).convert("RGB")
        t.thumbnail((tw, th))
        x, y = 20 + (i % cols) * (tw + 20), 20 + (i // cols) * (th + 50)
        sheet.paste(t, (x, y))
        d.rectangle((x - 1, y - 1, x + t.width, y + t.height), outline="#CFD8DC")
        d.text((x, y + th + 8), f"Page {i + 1}", font=f, fill="#37474F")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
