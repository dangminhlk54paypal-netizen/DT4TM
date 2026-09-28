"""gen_ar_marker.py -- printable AprilTag (tag36h11) 2x2 BOARD for the WebAR digital twin.

Outputs (default):
    outputs/ar_marker.pdf   A4, VECTOR (tags are filled squares, not a raster) -- print at 100 % / actual size
    outputs/ar_marker.png   raster PREVIEW of the same page (150 dpi, DPI metadata set)

Usage:
    python gen_ar_marker.py [--pdf outputs/ar_marker.pdf] [--png outputs/ar_marker.png] [--edge 48]

BOARD GEOMETRY  (single source of truth: this constant block is imported by build_ar_twin.py and
baked into the AR page, so print and pose solver cannot disagree)
    * family tag36h11, IDs 0 1 / 2 3 in reading order (0 = top-left as seen when the board is upright)
    * a tag36h11 code is an 8x8-module black-bordered square (+1 module white border = 10 modules)
      -> module = TAG_EDGE_MM / 8 ; default edge 48 mm = 6 mm module
    * gap between the black squares of neighbouring tags = 2 modules (0.25 * edge), white margin
      around the board = 1 module (0.125 * edge)  ->  board = 2.5 * edge = 120.0 mm square
      (every tag keeps >= 1 module of white all round)
    * board coordinate system == the old QR convention: origin = board CENTRE, x right, y UP (mm),
      "top" = the edge with tags 0 and 1.
    The 36h11 bit patterns come from tag36h11_codes.json, extracted by build_apriltag_wasm.py from
    the pinned AprilRobotics/apriltag sources (the same source the WASM detector is built from).

`python gen_ar_marker.py` needs `reportlab` and `pillow` (pip install reportlab pillow); no URL
is encoded any more (the old QR marker took a URL argument -- it is ignored with a notice).
"""
from __future__ import annotations
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CODES_JSON = os.path.join(HERE, "tag36h11_codes.json")

# ---- board geometry (see docstring) ------------------------------------------------------------
MARKER_FAMILY = "tag36h11"
TAG_EDGE_MM = 48.0            # black-square edge of ONE tag; the AR page's default markerSizeMm
GAP_RATIO = 0.25              # gap between neighbouring black squares, x edge   (2 modules)
MARGIN_RATIO = 0.125          # white margin from outermost black edge to board outline, x edge (1 module)
BOARD_EDGE_RATIO = 2.0 + GAP_RATIO + 2.0 * MARGIN_RATIO      # board side / tag edge = 2.5
# id -> tag centre in units of half the tag pitch, (x right, y up): pitch = edge * (1 + GAP_RATIO)
TAG_CENTERS_UNIT = {0: (-1.0, +1.0), 1: (+1.0, +1.0), 2: (-1.0, -1.0), 3: (+1.0, -1.0)}
TAG_IDS = tuple(sorted(TAG_CENTERS_UNIT))
# Corner order reported by AprilTag for an UPRIGHT tag (image y down): p0 = bottom-left,
# p1 = bottom-right, p2 = top-right, p3 = top-left.  In board mm (y UP), in units of edge/2:
CORNER_UNIT = ((-1.0, -1.0), (+1.0, -1.0), (+1.0, +1.0), (-1.0, +1.0))

MARKER_JS_CONFIG = {          # baked into the AR page verbatim
    "family": MARKER_FAMILY, "ids": list(TAG_IDS), "edgeMm": TAG_EDGE_MM, "gapRatio": GAP_RATIO,
    "marginRatio": MARGIN_RATIO, "centersUnit": {str(k): list(v) for k, v in TAG_CENTERS_UNIT.items()},
    "cornerUnit": [list(c) for c in CORNER_UNIT],
}


def board_edge_mm(edge_mm: float = TAG_EDGE_MM) -> float:
    return edge_mm * BOARD_EDGE_RATIO


def tag_layout(edge_mm: float = TAG_EDGE_MM) -> list[dict]:
    """[{id, cx, cy, edge, corners[4][2]}] in board mm (origin = board centre, y up)."""
    half_pitch = edge_mm * (1.0 + GAP_RATIO) / 2.0
    out = []
    for tid in TAG_IDS:
        ux, uy = TAG_CENTERS_UNIT[tid]
        cx, cy = ux * half_pitch, uy * half_pitch
        out.append({"id": tid, "cx": cx, "cy": cy, "edge": edge_mm,
                    "corners": [[cx + u * edge_mm / 2.0, cy + v * edge_mm / 2.0] for u, v in CORNER_UNIT]})
    return out


def load_codes() -> dict:
    with open(CODES_JSON, encoding="utf-8") as f:
        return json.load(f)


def tag_cells(tag_id: int, codes: dict | None = None) -> list[list[int]]:
    """8x8 grid of the tag (row 0 = top, col 0 = left as printed upright); 1 = WHITE, 0 = black.
    Border cells are black; interior cells hold the code bits (bit 0 = MSB, 1 = white)."""
    c = codes or load_codes()
    n = c["width_at_border"]
    code = int(c["codes_hex"][tag_id], 16)
    grid = [[0] * n for _ in range(n)]
    for i in range(c["nbits"]):
        bit = (code >> (c["nbits"] - 1 - i)) & 1
        grid[c["bit_y"][i]][c["bit_x"][i]] = bit
    return grid


# ---- tiny drawing abstraction: PDF (vector) + PNG preview from the SAME primitives ---------------
class _Page:
    """Primitives in mm, origin bottom-left of the page, y up."""
    def __init__(self):
        self.ops: list[tuple] = []
    def rects(self, rs, gray=0.0): self.ops.append(("rects", list(rs), gray))
    def line(self, x0, y0, x1, y1, w=0.25, gray=0.0): self.ops.append(("line", x0, y0, x1, y1, w, gray))
    def poly(self, pts, gray=0.0): self.ops.append(("poly", list(pts), gray))
    def text(self, x, y, s, size=9.0, anchor="l", bold=False, gray=0.0):
        self.ops.append(("text", x, y, s, size, anchor, bold, gray))


def build_page(edge_mm: float, page_w: float = 210.0, page_h: float = 297.0) -> _Page:
    codes = load_codes()
    P = _Page()
    board = board_edge_mm(edge_mm)
    ox, oy = page_w / 2.0, page_h / 2.0          # board centre on the page
    mod = edge_mm / codes["width_at_border"]
    lay = tag_layout(edge_mm)

    for t in lay:                                 # tags: black square + white cells (one union path)
        x0, y0 = ox + t["cx"] - edge_mm / 2.0, oy + t["cy"] - edge_mm / 2.0
        P.rects([(x0, y0, edge_mm, edge_mm)], 0.0)
        grid = tag_cells(t["id"], codes)
        wh = []
        for r in range(len(grid)):
            c = 0
            while c < len(grid[r]):
                if grid[r][c]:
                    c1 = c
                    while c1 + 1 < len(grid[r]) and grid[r][c1 + 1]:
                        c1 += 1
                    wh.append((x0 + c * mod, y0 + (len(grid) - 1 - r) * mod, (c1 - c + 1) * mod, mod))
                    c = c1 + 1
                else:
                    c += 1
        P.rects(wh, 1.0)

    bx0, by0, bx1, by1 = ox - board / 2, oy - board / 2, ox + board / 2, oy + board / 2
    # cut marks at the board outline (offset 2 mm from the corner, 6 mm long, outside the board)
    for (cx, cy, sx, sy) in ((bx0, by0, -1, -1), (bx1, by0, 1, -1), (bx0, by1, -1, 1), (bx1, by1, 1, 1)):
        P.line(cx + sx * 2.0, cy, cx + sx * 8.0, cy, 0.25)
        P.line(cx, cy + sy * 2.0, cx, cy + sy * 8.0, 0.25)
    # tag IDs, outside the board (left / right of each tag row)
    for t in lay:
        left = t["cx"] < 0
        P.text(bx0 - 4.0 if left else bx1 + 4.0, oy + t["cy"] - 1.0, f"ID {t['id']}", 7.0, "r" if left else "l", gray=0.35)
    # "TOP" orientation mark above the board (arrow + label), outside the cut marks
    ay = by1 + 14.0
    P.line(ox, ay, ox, ay + 8.0, 0.6)
    P.poly([(ox, ay + 10.5), (ox - 2.2, ay + 5.5), (ox + 2.2, ay + 5.5)])
    P.text(ox + 5.0, ay + 3.0, "OBEN / TOP  (Tags 0 + 1)", 7.0, "l", gray=0.35)

    # header text
    P.text(ox, page_h - 22.0, "DT4TM - AprilTag-Marker (tag36h11, 2 x 2 Board, IDs 0-3)", 13.0, "c", bold=True)
    P.text(ox, page_h - 31.0, "Mit 100 % / Originalgröße drucken - NICHT \"an Seite anpassen\".", 10.5, "c", bold=True)
    P.text(ox, page_h - 37.5, "Print at 100 % / actual size - do NOT fit to page.", 10.5, "c", bold=True)
    P.text(ox, page_h - 44.0, "Nach dem Druck den Maßstab unten nachmessen: 100 mm  /  Check the scale bar after printing.", 8.0, "c", gray=0.3)

    # 100 mm scale bar with ticks every 10 mm (5 mm minor)
    sy = by0 - 26.0
    sx0 = ox - 50.0
    P.line(sx0, sy, sx0 + 100.0, sy, 0.5)
    for i in range(0, 101, 5):
        h = 4.0 if i % 10 == 0 else 2.0
        P.line(sx0 + i, sy, sx0 + i, sy + h, 0.35)
    for i in range(0, 101, 10):
        P.text(sx0 + i, sy - 4.2, str(i), 6.5, "c", gray=0.3)
    P.text(ox, sy - 10.0, "100 mm  /  scale check", 8.0, "c", gray=0.3)

    # info block
    info = [
        f"Tag36h11, IDs 0 1 / 2 3.  Tag edge (schwarzes Quadrat / black square): {edge_mm:g} mm  (Modul / module {mod:g} mm)",
        f"Board: {board:g} x {board:g} mm inkl. weißer Rand / incl. white border.  Ursprung / origin = Board-Mitte, x rechts, y oben.",
        "In der AR-Seite: \"Marker-Größe\" = Tag-Kantenlänge (Standard 48 mm).",
    ]
    for k, s in enumerate(info):
        P.text(ox, sy - 20.0 - 5.0 * k, s, 7.5, "c", gray=0.3)
    return P


def render_pdf(P: _Page, path: str, page_w: float = 210.0, page_h: float = 297.0):
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    c = canvas.Canvas(path, pagesize=(page_w * mm, page_h * mm), pageCompression=1)
    c.setTitle("DT4TM AprilTag marker board (tag36h11, IDs 0-3)")
    c.setAuthor("maria-dt4tm gen_ar_marker.py")
    c.setSubject("Print at 100 % / actual size")
    for op in P.ops:
        k = op[0]
        if k == "rects":
            _, rs, g = op
            c.setFillGray(g)
            p = c.beginPath()
            for (x, y, w, h) in rs:
                p.rect(x * mm, y * mm, w * mm, h * mm)
            c.drawPath(p, stroke=0, fill=1)
        elif k == "line":
            _, x0, y0, x1, y1, w, g = op
            c.setStrokeGray(g); c.setLineWidth(w * mm)
            c.line(x0 * mm, y0 * mm, x1 * mm, y1 * mm)
        elif k == "poly":
            _, pts, g = op
            c.setFillGray(g)
            p = c.beginPath(); p.moveTo(pts[0][0] * mm, pts[0][1] * mm)
            for (x, y) in pts[1:]:
                p.lineTo(x * mm, y * mm)
            p.close(); c.drawPath(p, stroke=0, fill=1)
        elif k == "text":
            _, x, y, s, size, anchor, bold, g = op
            c.setFillGray(g); c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
            {"l": c.drawString, "r": c.drawRightString, "c": c.drawCentredString}[anchor](x * mm, y * mm, s)
    c.showPage(); c.save()


def render_png(P: _Page, path: str, dpi: int = 150, page_w: float = 210.0, page_h: float = 297.0):
    from PIL import Image, ImageDraw, ImageFont
    k = dpi / 25.4
    W, H = round(page_w * k), round(page_h * k)
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    X = lambda x: x * k
    Y = lambda y: H - y * k
    for op in P.ops:
        t = op[0]
        if t == "rects":
            _, rs, g = op
            for (x, y, w, h) in rs:
                d.rectangle([round(X(x)), round(Y(y + h)), round(X(x + w)) - 1, round(Y(y)) - 1], fill=int(g * 255))
        elif t == "line":
            _, x0, y0, x1, y1, w, g = op
            d.line([X(x0), Y(y0), X(x1), Y(y1)], fill=int(g * 255), width=max(1, round(w * k)))
        elif t == "poly":
            _, pts, g = op
            d.polygon([(X(x), Y(y)) for x, y in pts], fill=int(g * 255))
        elif t == "text":
            _, x, y, s, size, anchor, bold, g = op
            try:
                font = ImageFont.truetype("arialbd.ttf" if bold else "arial.ttf", max(6, round(size * 25.4 / 72.0 * k)))
            except IOError:
                font = ImageFont.load_default()
            d.text((X(x), Y(y)), s, fill=int(g * 255), font=font, anchor={"l": "ls", "r": "rs", "c": "ms"}[anchor])
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    img.save(path, dpi=(dpi, dpi))


def generate_ar_marker(pdf_path: str, png_path: str | None, edge_mm: float = TAG_EDGE_MM) -> str:
    P = build_page(edge_mm)
    os.makedirs(os.path.dirname(os.path.abspath(pdf_path)), exist_ok=True)
    render_pdf(P, pdf_path)
    print(f"[gen_ar_marker] PDF  -> {pdf_path}")
    if png_path:
        render_png(P, png_path)
        print(f"[gen_ar_marker] PNG preview -> {png_path}")
    b = board_edge_mm(edge_mm)
    print(f"[gen_ar_marker] Print at 100 % (actual size): tag edge {edge_mm:g} mm, board {b:g} x {b:g} mm, "
          f"tags 0/1 top, 2/3 bottom; origin = board centre")
    return pdf_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate the printable AprilTag board PDF for the TEAM 28 WebAR twin")
    ap.add_argument("url", nargs="?", default=None, help="DEPRECATED (ignored): the marker no longer encodes a URL")
    ap.add_argument("--pdf", default=os.path.join(HERE, "outputs", "ar_marker.pdf"))
    ap.add_argument("--png", default=os.path.join(HERE, "outputs", "ar_marker.png"), help="preview PNG ('' = skip)")
    ap.add_argument("--edge", type=float, default=TAG_EDGE_MM,
                    help=f"tag black-square edge in mm (default {TAG_EDGE_MM:g} -> 120 mm board; must fit A4)")
    a = ap.parse_args()
    if a.url:
        print("[gen_ar_marker] NOTE: the URL argument is deprecated and ignored (AprilTag board, no QR payload).")
    generate_ar_marker(a.pdf, a.png or None, a.edge)
