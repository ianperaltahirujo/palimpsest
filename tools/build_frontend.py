"""Build the web UI and stage it for `palimpsest serve` to mount.

Production mode (`palimpsest serve` without `--dev`) serves the built SPA
from `src/palimpsest/server/static/` at the same origin as the API -- see
`server.app.create_app`'s docstring for why same-origin matters (it's the
whole reason no CORS is needed in production). That directory is a build
artifact (gitignored, not source): this script is what populates it.

    python tools/build_frontend.py

Runs `npm ci` (or `npm install` if no lockfile-clean install is possible)
and `npm run build` in web/prototype, then copies the resulting dist/ over
static/, clearing whatever was there before so a stale asset from a
previous build never lingers alongside a fresh index.html referencing
different hashed filenames.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "web" / "prototype"
DIST_DIR = FRONTEND_DIR / "dist"
STATIC_DIR = ROOT / "src" / "palimpsest" / "server" / "static"


def run(cmd: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(cmd)}  (in {cwd.relative_to(ROOT)})")
    subprocess.run(cmd, cwd=cwd, check=True, shell=sys.platform == "win32")


def main() -> int:
    if not (FRONTEND_DIR / "package.json").is_file():
        print(f"error: no package.json in {FRONTEND_DIR}", file=sys.stderr)
        return 1

    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    has_lockfile = (FRONTEND_DIR / "package-lock.json").is_file()
    run([npm, "ci"] if has_lockfile else [npm, "install"], cwd=FRONTEND_DIR)
    run([npm, "run", "build"], cwd=FRONTEND_DIR)

    if not DIST_DIR.is_dir():
        print(f"error: build did not produce {DIST_DIR}", file=sys.stderr)
        return 1

    if STATIC_DIR.is_dir():
        shutil.rmtree(STATIC_DIR)
    shutil.copytree(DIST_DIR, STATIC_DIR)
    print(f"staged {DIST_DIR.relative_to(ROOT)} -> {STATIC_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
