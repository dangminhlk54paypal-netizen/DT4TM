"""gen_qr.py — Generate a QR code pointing at the hosted digital_twin_fem.html.

Phase 5 (AR delivery) closer: the physics/thermal pipeline never produced a
real hosting URL, so this script does NOT bake one in. Pass the URL on the
command line, or edit DEFAULT_URL below once hosting is decided (GitHub
Pages, a CDN, etc.) — everything else (PNG export, ASCII preview) works
today against a placeholder for testing the mechanism.

Run:
    python gen_qr.py https://example.com/digital_twin_fem.html
    python gen_qr.py                       # uses DEFAULT_URL below
    python gen_qr.py <url> --out outputs/my_qr.png
    python gen_qr.py <url> --no-ascii      # skip terminal preview
"""
from __future__ import annotations
import argparse
import os

import qrcode

HERE = os.path.dirname(os.path.abspath(__file__))

# Placeholder — update once the real hosting URL for digital_twin_fem.html
# is known (see CLAUDE.md "Optional: QR code generation" entry).
DEFAULT_URL = "https://example.com/digital_twin_fem.html"


def make_qr(url: str, out_path: str, ascii_preview: bool = True) -> None:
    qr = qrcode.QRCode(border=2)
    qr.add_data(url)
    qr.make(fit=True)

    if ascii_preview:
        qr.print_ascii(invert=True)

    img = qr.make_image(fill_color="black", back_color="white")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    print(f"QR -> {url}")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate a QR code for the hosted digital twin")
    ap.add_argument("url", nargs="?", default=DEFAULT_URL,
                     help="URL to encode (default: DEFAULT_URL placeholder in this file)")
    ap.add_argument("--out", default=os.path.join(HERE, "outputs", "qr_digital_twin.png"),
                     help="Output PNG path (default: outputs/qr_digital_twin.png)")
    ap.add_argument("--no-ascii", action="store_true",
                     help="Skip the ASCII QR preview printed to the terminal")
    args = ap.parse_args()

    if args.url == DEFAULT_URL:
        print(f"[gen_qr] No URL given — using placeholder DEFAULT_URL ({DEFAULT_URL}).")
        print("[gen_qr] Pass a real URL: python gen_qr.py <url>")

    make_qr(args.url, args.out, ascii_preview=not args.no_ascii)
