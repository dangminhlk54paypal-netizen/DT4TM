"""gen_ar_marker.py — Generate a high-contrast printable AR marker with an embedded QR code.

The generated marker serves two functions simultaneously:
1. Phone Camera Scan: Scans the QR code to open the WebAR Digital Twin in the browser.
2. WebAR Image Tracking Anchor: High-contrast corner fiducials and borders provide
   rich feature points for camera pose estimation (e.g. MindAR / Three.js).

Usage:
    python gen_ar_marker.py [URL] [--out outputs/ar_marker.png] [--size 60]
"""
from __future__ import annotations
import argparse
import os
import sys

try:
    import qrcode
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("[gen_ar_marker] Error: 'qrcode' and 'pillow' are required.")
    print("Install with: pip install qrcode pillow")
    sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_URL = "https://example.com/ar_twin.html"


def generate_ar_marker(
    url: str,
    out_path: str,
    target_width_mm: float = 60.0,
    dpi: int = 300,
) -> str:
    """Generate a printable marker containing:
    - Central QR code encoding the URL
    - Distinctive geometric border with corner identification targets
    - Center alignment crosshairs
    - Real-world scale annotation (in mm)
    """
    # 1. Generate core QR code
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=3,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qw, qh = qr_img.size

    # 2. Outer border layout
    border_px = int(qw * 0.22)
    canvas_w = qw + 2 * border_px
    canvas_h = qh + 2 * border_px + int(border_px * 0.7)  # Extra bottom margin for text

    img = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(img)

    # Paste QR in center
    img.paste(qr_img, (border_px, border_px))

    # Outer solid framing (black band)
    frame_thick = max(6, int(border_px * 0.16))
    frame_inset = int(border_px * 0.25)
    draw.rectangle(
        [frame_inset, frame_inset, canvas_w - frame_inset, qh + 2 * border_px - frame_inset],
        outline="black",
        width=frame_thick,
    )

    # 4 distinctive asymmetric corner fiducials (for robust 6-DoF orientation)
    fid_size = int(border_px * 0.6)
    # Top-Left: Solid square
    draw.rectangle([frame_inset, frame_inset, frame_inset + fid_size, frame_inset + fid_size], fill="black")
    # Top-Right: Concentric target (circle in square)
    tr_x0, tr_y0 = canvas_w - frame_inset - fid_size, frame_inset
    draw.rectangle([tr_x0, tr_y0, tr_x0 + fid_size, tr_y0 + fid_size], fill="black")
    draw.rectangle([tr_x0 + fid_size // 4, tr_y0 + fid_size // 4, tr_x0 + 3 * fid_size // 4, tr_y0 + 3 * fid_size // 4], fill="white")
    # Bottom-Left: Diagonal notch
    bl_x0, bl_y0 = frame_inset, qh + 2 * border_px - frame_inset - fid_size
    draw.polygon([(bl_x0, bl_y0), (bl_x0 + fid_size, bl_y0), (bl_x0, bl_y0 + fid_size)], fill="black")
    # Bottom-Right: Double bar
    br_x0, br_y0 = canvas_w - frame_inset - fid_size, qh + 2 * border_px - frame_inset - fid_size
    draw.rectangle([br_x0, br_y0, br_x0 + fid_size // 3, br_y0 + fid_size], fill="black")
    draw.rectangle([br_x0 + 2 * fid_size // 3, br_y0, br_x0 + fid_size, br_y0 + fid_size], fill="black")

    # Center notch guides (alignment with disc center r = 0)
    mid_x = canvas_w // 2
    top_y = frame_inset
    draw.line([(mid_x, top_y - 10), (mid_x, top_y + 15)], fill="black", width=3)
    draw.line([(mid_x, qh + 2 * border_px - frame_inset - 15), (mid_x, qh + 2 * border_px - frame_inset + 10)], fill="black", width=3)

    # Annotations below the marker
    font_size = max(14, int(canvas_w * 0.035))
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
        small_font = ImageFont.truetype("arial.ttf", int(font_size * 0.75))
    except IOError:
        font = ImageFont.load_default()
        small_font = font

    title_text = "DT4TM — TEAM 28 THERMAL DIGITAL TWIN"
    scale_text = f"Target Size: {target_width_mm:.0f} x {target_width_mm:.0f} mm · Center = Disc Origin (r=0)"

    text_y = qh + 2 * border_px + 10
    draw.text((mid_x, text_y), title_text, fill="black", font=font, anchor="mt")
    draw.text((mid_x, text_y + font_size + 6), scale_text, fill="#444444", font=small_font, anchor="mt")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    img.save(out_path, dpi=(dpi, dpi))
    print(f"[gen_ar_marker] Marker generated -> {out_path}")
    print(f"[gen_ar_marker] Encoded URL: {url}")
    print(f"[gen_ar_marker] Suggested print size: {target_width_mm} mm x {target_width_mm} mm")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate printable WebAR marker for TEAM 28 Digital Twin")
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help=f"URL encoded in the QR code (default: {DEFAULT_URL})")
    parser.add_argument("--out", default=os.path.join(HERE, "outputs", "ar_marker.png"), help="Output path (default: outputs/ar_marker.png)")
    parser.add_argument("--size", type=float, default=60.0, help="Target physical width in mm (default: 60.0)")
    args = parser.parse_args()

    generate_ar_marker(args.url, args.out, target_width_mm=args.size)
