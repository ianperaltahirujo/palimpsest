"""Pin the fix for the v1 defect that blocked testing entirely: several
modules ran sys.stdout.reconfigure(...) and os.makedirs(...) at MODULE
IMPORT time, which AttributeErrors under pytest's output capture (a
CaptureFixture has no .reconfigure) and creates directories as a side
effect of merely importing a module. Every palimpsest module must be
importable in a read-only working directory with stdout untouched.
"""

import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "palimpsest"


def _module_names() -> list[str]:
    names = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        rel = path.relative_to(PACKAGE_ROOT.parent)
        if rel.name == "__main__.py":
            continue
        parts = rel.with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        names.append(".".join(parts))
    return names


def test_every_module_imports_without_creating_directories(tmp_path):
    script = (
        "import sys, importlib\n"
        f"mods = {_module_names()!r}\n"
        "for m in mods:\n"
        "    importlib.import_module(m)\n"
        "print('OK')\n"
    )

    before = {p.name for p in tmp_path.iterdir()}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    after = {p.name for p in tmp_path.iterdir()}

    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
    assert before == after, f"import created unexpected files/dirs: {after - before}"
