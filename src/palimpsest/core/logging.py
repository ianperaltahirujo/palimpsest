"""Console logging setup for the CLI.

The pipeline this project was extracted from called
`sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")` at
MODULE IMPORT time in four files, because it `print()`ed `repr()` of
accented Spanish text, which raises `UnicodeEncodeError` on a cp1252
Windows console otherwise. That import-time side effect is exactly what
`test_no_import_side_effects.py` exists to forbid: it creates a
process-wide effect (reconfiguring the real `sys.stdout`) merely by being
imported, which is unsafe in a read-only environment and surprising
under any caller that didn't ask for it.

The underlying encoding problem is real, so the fix has to be too:
`configure()` calls `sys.stdout.reconfigure()` at CLI startup instead --
explicitly, from `cli.main()`, never at import time -- so importing any
palimpsest module stays side-effect-free. `reconfigure()` itself works
fine even when `sys.stdout` has been replaced by pytest's capture object
or another non-console stream; the guard below only protects against a
stream that doesn't implement `reconfigure` at all.
"""

from __future__ import annotations

import logging
import sys


def configure(verbose: bool = False) -> None:
    try:
        sys.stdout.reconfigure(  # type: ignore[union-attr]
            encoding="utf-8", errors="backslashreplace"
        )
    except (AttributeError, ValueError, OSError):
        pass

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger("palimpsest")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.propagate = False
