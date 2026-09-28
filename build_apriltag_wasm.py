"""build_apriltag_wasm.py -- reproducible build of the AprilTag (tag36h11) WebAssembly detector.

Compiles the OFFICIAL AprilRobotics/apriltag C library (pinned commit) + apriltag_glue.c with
Emscripten inside a DISPOSABLE Docker container (`docker run --rm`, pinned emsdk image) and writes
two flat, committed artifacts that the rest of the repo consumes WITHOUT Docker:

    apriltag_wasm.js      single-file Emscripten module (wasm inlined as base64), factory
                          `createAprilTag()`; read + embedded by build_ar_twin.py
    tag36h11_codes.json   the 36h11 code table + bit layout extracted from the SAME pinned
                          tag36h11.c; read by gen_ar_marker.py (so the printed tags cannot drift
                          from what the detector decodes)

Only needed when the C glue / pinned versions change:   python build_apriltag_wasm.py
(needs Docker; ~1-2 min, network for `git clone` + the emsdk image the first time).

Licence: AprilTag is (C) 2013-2016 The Regents of The University of Michigan, BSD 2-Clause;
the notice is prepended to apriltag_wasm.js and recorded in tag36h11_codes.json.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
EMSDK_IMAGE = "emscripten/emsdk:4.0.10"                     # pinned toolchain
APRILTAG_REPO = "https://github.com/AprilRobotics/apriltag"
APRILTAG_TAG = "v3.4.5"                                      # human-readable ...
APRILTAG_COMMIT = "94be783968e5091bcc9972c72c84fd63efce2935"  # ... and the exact pin (verified in-container)
OUT_JS = os.path.join(HERE, "apriltag_wasm.js")
OUT_CODES = os.path.join(HERE, "tag36h11_codes.json")

# Library sources actually linked (no pose, no image I/O, no jpeg/pnm/getopt -> small wasm)
LIB_SRCS = ["apriltag.c", "apriltag_quad_thresh.c", "tag36h11.c",
            "common/g2d.c", "common/homography.c", "common/image_u8.c", "common/matd.c",
            "common/svd22.c", "common/unionfind.c", "common/workerpool.c", "common/zarray.c",
            "common/zhash.c", "common/zmaxheap.c", "common/time_util.c", "common/string_util.c",
            "common/pthreads_cross.c", "common/pnm.c", "common/image_u8x3.c", "common/image_u8x4.c",
            "common/pam.c", "common/image_u8_parallel.c"]
EXPORTS = ["_at_init", "_at_config", "_at_buffer", "_at_detect", "_at_results", "_at_stride",
           "_at_free", "_malloc", "_free"]

CONTAINER_SCRIPT = f"""
set -e
git clone --quiet {APRILTAG_REPO} /tmp/at
cd /tmp/at
git checkout --quiet {APRILTAG_COMMIT}
test "$(git rev-parse HEAD)" = "{APRILTAG_COMMIT}"
cp tag36h11.c LICENSE.md /out/
emcc -O3 -flto -DNDEBUG -I/tmp/at -I/tmp/at/common \\
  /src/apriltag_glue.c {' '.join('/tmp/at/' + s for s in LIB_SRCS)} \\
  -sMODULARIZE=1 -sEXPORT_NAME=createAprilTag -sSINGLE_FILE=1 -sENVIRONMENT=web,worker \\
  -sALLOW_MEMORY_GROWTH=1 -sINITIAL_MEMORY=16777216 -sMALLOC=emmalloc -sFILESYSTEM=0 \\
  -sEXPORTED_FUNCTIONS={','.join(EXPORTS)} -sEXPORTED_RUNTIME_METHODS=HEAPU8,HEAPF64 \\
  --closure 1 -sASSERTIONS=0 -o /out/apriltag_wasm.js
"""


def extract_codes(c_path: str, license_path: str) -> dict:
    src = open(c_path, encoding="utf-8").read()
    codes = [int(m, 16) for m in re.findall(r"0x([0-9a-fA-F]+)UL", src.split("tag36h11_create")[0])]
    n = int(re.search(r"tf->ncodes = (\d+);", src).group(1))
    nbits = int(re.search(r"tf->nbits = (\d+);", src).group(1))
    assert len(codes) == n == 587 and nbits == 36, (len(codes), n, nbits)
    bx, by = [0] * nbits, [0] * nbits
    for axis, arr in (("x", bx), ("y", by)):
        for i, v in re.findall(rf"tf->bit_{axis}\[(\d+)\] = (\d+);", src):
            arr[int(i)] = int(v)
    return {
        "family": "tag36h11",
        "source": f"{APRILTAG_REPO} @ {APRILTAG_TAG} ({APRILTAG_COMMIT}) tag36h11.c",
        "license": "BSD-2-Clause, (C) 2013-2016 The Regents of The University of Michigan",
        "nbits": nbits, "ncodes": n,
        "min_hamming": int(re.search(r"tf->h = (\d+);", src).group(1)),
        "width_at_border": int(re.search(r"tf->width_at_border = (\d+);", src).group(1)),
        "total_width": int(re.search(r"tf->total_width = (\d+);", src).group(1)),
        "reversed_border": "true" in re.search(r"tf->reversed_border = (\w+);", src).group(1),
        "bit_x": bx, "bit_y": by,
        "codes_hex": [f"{c:016x}" for c in codes],
        "_note": "bit i (0 = MSB of the 36-bit code) sits at grid cell (bit_x[i], bit_y[i]) of the "
                 "8x8 black-bordered area, origin top-left of the upright tag, y down; 1 = white.",
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as out:
        cmd = ["docker", "run", "--rm", "-v", f"{HERE}:/src:ro", "-v", f"{out}:/out",
               EMSDK_IMAGE, "bash", "-c", CONTAINER_SCRIPT]
        print("[build_apriltag_wasm]", " ".join(cmd[:8]), "...")
        subprocess.run(cmd, check=True)
        js = open(os.path.join(out, "apriltag_wasm.js"), encoding="utf-8").read()
        lic = open(os.path.join(out, "LICENSE.md"), encoding="utf-8").read().strip()
        header = ("/* apriltag_wasm.js -- AprilTag tag36h11 detector, WebAssembly (GENERATED by build_apriltag_wasm.py;\n"
                  f" * do not edit).  {APRILTAG_REPO} {APRILTAG_TAG} ({APRILTAG_COMMIT[:12]}),\n"
                  f" * {EMSDK_IMAGE}, glue = apriltag_glue.c.  BSD 2-Clause licence of AprilTag follows.\n *\n"
                  + "\n".join(" * " + ln for ln in lic.splitlines()).replace("*/", "* /") + "\n */\n")
        with open(OUT_JS, "w", encoding="utf-8", newline="\n") as f:
            f.write(header + js)
        codes = extract_codes(os.path.join(out, "tag36h11.c"), os.path.join(out, "LICENSE.md"))
        with open(OUT_CODES, "w", encoding="utf-8", newline="\n") as f:
            json.dump(codes, f, indent=1)
    print(f"[build_apriltag_wasm] wrote {OUT_JS} ({os.path.getsize(OUT_JS) / 1024:.1f} KB) and "
          f"{OUT_CODES} ({os.path.getsize(OUT_CODES) / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
