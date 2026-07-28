# extensions/ — optional add-ons

Scripts here are **not part of the core pipeline.** The project runs end-to-end
(`config → em_solver → thermal_solver → rom → build_twin_html_fem`) with this whole
folder deleted. Something lives here when it is true that:

- it needs a **heavy or awkward dependency** the core deliberately avoids, and
- **nothing in the repo root imports it** (the dependency arrow points one way:
  `extensions/ → root`, never back).

That's the exception that earns a folder. Everything else — solvers, ROM, the twins the
project is actually graded on, `params.yaml`, input data — stays FLAT in the repo root
per CLAUDE.md's layout rule, because those scripts self-locate via `__file__`.

## Contents

| Script | Dependency | What it is |
|---|---|---|
| `digital_twin_pyvista.py` | `pyvista>=0.45`, `vtk>=9.3,<9.7` (~400 MB) | Desktop 3D live twin (VTK). The third twin, alongside `digital_twin.py` (matplotlib) and `outputs/digital_twin_fem.html` (three.js). Same `twin_core.TwinState` physics; geometry reuses `build_twin_html_fem.py`'s mesh builders verbatim. |

## Running

Run **from the repo root** — relative paths like `outputs/…` resolve against the
current working directory, not the script's folder:

```bash
python extensions/digital_twin_pyvista.py --self-check     # works with NO pyvista/vtk installed
python extensions/digital_twin_pyvista.py --screenshot outputs/twin_pv.png --no-show
python extensions/digital_twin_pyvista.py --speed 50       # live interactive window

# install the optional dependency first for the last two:
pip install "pyvista>=0.45" "vtk>=9.3,<9.7"
```

## Writing a new extension

Copy this contract exactly — it is the only thing that makes `extensions/` work:

```python
from pathlib import Path
import sys

# extensions/ scripts import root modules, so put the ROOT on sys.path — NOT
# this folder. Root modules then self-locate params.yaml/outputs/ via their
# own __file__, so nothing else needs a path fix.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
```

Then:

1. **Guard the heavy import** so the file still imports without it:
   ```python
   try:
       import pyvista as pv
       HAVE_PYVISTA = True
   except ImportError:
       HAVE_PYVISTA = False
   ```
2. **Ship a `--self-check`** that runs with the dependency absent. This is what keeps the
   extension from silently rotting while nobody has VTK installed.
3. **Keep the dependency commented out in `requirements.txt`**, with the install line in a
   comment — a fresh `pip install -r requirements.txt` must not pull 400 MB.
4. **Never import an extension from root code.** If root code needs it, it isn't an
   extension — move it to the root instead.

## Note

`visualize.py --pyvista` (root) also touches PyVista, but stays where it is on purpose:
it's one optional flag on an otherwise core script, already import-guarded, and moving it
would break `visualize.py`'s own CLI.
