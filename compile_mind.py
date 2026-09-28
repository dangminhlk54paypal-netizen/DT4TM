"""compile_mind.py — Compile ar_marker.png into outputs/targets.mind using headless Edge/Chrome."""
import functools
import http.server
import os
import subprocess
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "outputs")
TEMP_HTML = os.path.join(OUT_DIR, "compile_temp.html")
TARGETS_MIND = os.path.join(OUT_DIR, "targets.mind")

compiled_buffer = None

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HERE, **kwargs)

    def do_POST(self):
        global compiled_buffer
        if self.path == '/upload_targets':
            length = int(self.headers['Content-Length'])
            compiled_buffer = self.rfile.read(length)
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        elif self.path == '/log':
            length = int(self.headers['Content-Length'])
            msg = self.rfile.read(length).decode('utf-8', errors='ignore')
            print(f"   [Browser Log] {msg}")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')

HTML = """<!DOCTYPE html>
<html>
<head>
<script type="importmap">
{
  "imports": {
    "mindar-image": "https://cdn.jsdelivr.net/npm/mind-ar@1.2.5/dist/mindar-image.prod.js"
  }
}
</script>
</head>
<body style="background:#000; color:#fff;">
<h2>Compiling targets.mind...</h2>
<div id="status">Lade Bild...</div>
<script type="module">
import { Compiler } from 'mindar-image';

function log(msg) {
  console.log(msg);
  fetch('/log', { method: 'POST', body: msg }).catch(() => {});
}

async function run() {
  log('Starting compiler script...');
  const img = new Image();
  img.src = '/outputs/ar_marker.png';
  await new Promise((res, rej) => {
    img.onload = () => { log('Marker image loaded (' + img.width + 'x' + img.height + ')'); res(); };
    img.onerror = rej;
  });

  log('Initializing MindAR Compiler...');
  const compiler = new Compiler();
  await compiler.compileImageTargets([img], (progress) => {
    log('Compile progress: ' + Math.round(progress) + '%');
  });
  log('Exporting data buffer...');
  const buffer = await compiler.exportData();
  log('Buffer exported, size: ' + buffer.byteLength + ' bytes. Uploading...');
  await fetch('/upload_targets', { method: 'POST', body: buffer });
  log('Upload complete!');
}

run().catch(e => log('Error: ' + e.stack || e.message));
</script>
</body>
</html>
"""

def compile_targets():
    global compiled_buffer
    with open(TEMP_HTML, "w", encoding="utf-8") as f:
        f.write(HTML)

    port = 8765
    server = http.server.HTTPServer(('127.0.0.1', port), Handler)
    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()

    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    edge_exe = next((p for p in edge_paths if os.path.exists(p)), None)
    if not edge_exe:
        print("[compile_mind] Could not find Edge executable.")
        server.shutdown()
        return False

    print(f"[compile_mind] Running headless Edge to compile targets.mind ...")
    proc = subprocess.Popen([edge_exe, "--headless", "--disable-gpu", f"http://127.0.0.1:{port}/outputs/compile_temp.html"])

    for _ in range(45):
        time.sleep(1)
        if compiled_buffer:
            break

    try:
        proc.terminate()
    except Exception:
        pass
    server.shutdown()

    if os.path.exists(TEMP_HTML):
        try:
            os.remove(TEMP_HTML)
        except Exception:
            pass

    if compiled_buffer:
        with open(TARGETS_MIND, "wb") as f:
            f.write(compiled_buffer)
        size_kb = len(compiled_buffer) / 1024
        print(f"[compile_mind] SUCCESS! Saved {TARGETS_MIND} ({size_kb:.1f} KB)")
        return True
    else:
        print("[compile_mind] Failed to compile targets.mind.")
        return False

if __name__ == "__main__":
    compile_targets()
