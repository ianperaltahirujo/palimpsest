"""Progress reporting for long-running pipeline calls.

`ProgressEvent` is a plain, frozen value, not a callback interface with
methods to implement -- callers just pass a `Callable[[ProgressEvent],
None]`, which keeps `Translator.warm()` and `pdf.pipeline.process_document`
usable with a lambda, a Queue.put, or nothing at all (`None` is always a
valid callback: see `emit()` below). Phases match the CLI's `--verbose`
log output and the web prototype's `PHASES` fixture 1:1, so a caller
driving a progress UI never has to invent its own phase names.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

Phase = Literal["classify", "ocr", "extract", "translate", "render", "save"]
PhaseStatus = Literal["active", "done"]


@dataclass(frozen=True)
class ProgressEvent:
    phase: Phase
    status: PhaseStatus
    detail: str | None = None
    count: int | None = None
    """Progress within the phase, e.g. unique strings translated so far.
    None for phases with no meaningful sub-count."""
    total: int | None = None


ProgressCallback = Callable[[ProgressEvent], None]


def emit(callback: ProgressCallback | None, event: ProgressEvent) -> None:
    """No-op when `callback` is None, so call sites never need an `if
    callback is not None:` guard of their own."""
    if callback is not None:
        callback(event)
