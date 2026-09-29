"""serve_ar.py — Local development server & HTTPS tunnel for testing WebAR on mobile.

Usage:
  python serve_ar.py              # Start local webserver & print URLs + QR code
  python serve_ar.py --tunnel     # Create public HTTPS tunnel via ngrok (if auth token set)
  python serve_ar.py --port 8080  # Custom port
"""
from __future__ import annotations
import argparse
import functools
import http.server
import os
import socket
import sys

import qrcode

HERE = os.path.dirname(os.path.abspath(__file__))


def get_local_ip() -> str:
    """Get LAN IPv4 address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not actually establish connection
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def print_qr(url: str):
    """Print ASCII QR code in the terminal for quick mobile scanning."""
    try:
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        print("\n[Scanne diesen QR-Code mit der Smartphone-Kamera]:")
        qr.print_ascii(invert=True)
    except Exception as e:
        pass


def run_server(port: int = 8000, use_tunnel: bool = False):
    ip = get_local_ip()
    local_url = f"http://{ip}:{port}/outputs/ar_twin.html"
    localhost_url = f"http://localhost:{port}/outputs/ar_twin.html"

    print("=" * 68)
    print("      TEAM 28 — WebAR Digitaler Zwilling Server")
    print("=" * 68)
    print(f"\n[Lokaler Rechner]: {localhost_url}")

    tunnel_url = None
    if use_tunnel:
        try:
            from pyngrok import ngrok
            tunnel = ngrok.connect(port, "http")
            tunnel_url = tunnel.public_url.replace("http://", "https://") + "/outputs/ar_twin.html"
            print(f"\n[Öffentlicher HTTPS-Tunnel (für Smartphone Safari/Chrome)]:\n>> {tunnel_url}")
            print_qr(tunnel_url)
        except Exception as e:
            print(f"\n[ngrok-Hinweis]: Konnte Tunnel nicht starten ({e}).")
            print("Falls du ngrok nutzt, hinterlege deinen kostenlosen Token mit: ngrok config add-authtoken <TOKEN>")

    if not tunnel_url:
        print(f"\n[WLAN-Adresse]: {local_url}")
        print("\n⚠️ WICHTIGER HINWEIS ZU MOBIL-KAMERAS (iOS Safari & Android Chrome):")
        print("  Smartphones erlauben Kamera-Zugriff aus Datenschutzgründen")
        print("  NUR über HTTPS oder GitHub Pages!")
        print("  Empfohlene Dauerlösung: GitHub Pages aktivieren:")
        print("  https://<github-user>.github.io/DT4TM/outputs/ar_twin.html")
        print_qr(local_url)

    print(f"\nServer läuft auf Port {port}. Beenden mit Strg+C ...\n")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=HERE)
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer beendet.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WebAR Local Server")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--tunnel", action="store_true", help="Start HTTPS tunnel via ngrok")
    args = parser.parse_args()

    run_server(port=args.port, use_tunnel=args.tunnel)
