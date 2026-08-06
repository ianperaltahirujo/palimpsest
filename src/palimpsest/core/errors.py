"""Shared exception types.

Kept deliberately small and flat -- one type per class of failure a CLI
command needs to report distinctly, not one type per module.
"""

from __future__ import annotations


class PalimpsestError(Exception):
    """Base class for all errors raised by palimpsest itself (as opposed
    to a third-party library propagating one of its own)."""


class ConfigError(PalimpsestError):
    """A palimpsest.toml (or a file it references) is missing, malformed,
    or internally inconsistent."""


class BackendError(PalimpsestError):
    """A translation backend failed in a way that isn't a per-unit
    translation failure (those are recorded in the cache with
    status="failed" and retried, not raised) -- e.g. missing credentials,
    or the backend rejecting the request outright."""


class DependencyError(PalimpsestError):
    """A required external tool or system dependency (Tesseract,
    Ghostscript, a font) is missing or misconfigured. Raised with an
    actionable message rather than letting the underlying subprocess
    stack trace surface -- see `palimpsest audit ocr` / `audit fonts`."""
