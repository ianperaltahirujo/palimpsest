"""Process a whole corpus: translate every mapped PDF and Office file,
copy everything in copy-as-is scope untouched, and write a report.

Resumable: an output that already exists and is newer than its source is
skipped unless `force=True`. Each document is wrapped in its own
try/except so one bad file cannot take the whole run down -- failures
land in the report instead.

Digital PDFs are processed before scans (no OCR wait up front) --
`--only pdf` alone, without OCR-heavy scans dominating the front of a
resumed run, is common enough (re-running after a layout/render change)
that this ordering is worth doing unconditionally rather than behind a
flag.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from palimpsest.config.model import Config, DocumentMap
from palimpsest.office.pipeline import translate_office_document
from palimpsest.pdf.classify import classify_pdf
from palimpsest.pdf.pipeline import translate_pdf_document
from palimpsest.text.glossary import Glossary
from palimpsest.translate.backend import Backend

log = logging.getLogger(__name__)

_ONLY_VALUES = ("pdf", "office", "copy")


def _up_to_date(src: Path, out: Path) -> bool:
    return out.exists() and out.stat().st_mtime >= src.stat().st_mtime


def _copy_verbatim(src: Path, out: Path, force: bool) -> str:
    if not force and _up_to_date(src, out):
        return "skipped (up to date)"
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, out)
    return "copied"


def _copy_tree_verbatim(src: Path, out: Path, force: bool) -> str:
    if not src.is_dir():
        return "MISSING SOURCE DIR"
    n = 0
    for root, _dirs, files in os.walk(src):
        rel_root = Path(root).relative_to(src)
        out_root = out / rel_root if str(rel_root) != "." else out
        out_root.mkdir(parents=True, exist_ok=True)
        for fname in files:
            s = Path(root) / fname
            d = out_root / fname
            if force or not _up_to_date(s, d):
                shutil.copy2(s, d)
                n += 1
    return f"copied {n} files"


def _run_items(
    fn: Callable[[str, str], dict], items: Sequence[tuple[str, str]], jobs: int
) -> list[dict]:
    """Run `fn(rel_src, rel_out)` over `items`, in parallel if `jobs > 1`.
    Safe to parallelize: each call builds its own Translator, cache file,
    FontResolver and RenderContext (see `pdf.pipeline.translate_pdf_document`
    / `office.pipeline.translate_office_document`) -- no state is shared
    or mutated across documents."""
    if jobs <= 1 or len(items) <= 1:
        return [fn(rel_src, rel_out) for rel_src, rel_out in items]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(fn, rel_src, rel_out) for rel_src, rel_out in items]
        return [f.result() for f in futures]


def run_corpus(
    config: Config,
    documents: DocumentMap,
    backend: Backend,
    entities: tuple[str, ...],
    glossary: Glossary,
    post_rules: tuple[tuple[str, str], ...],
    force: bool = False,
    only: str | None = None,
    jobs: int = 1,
    debug: bool = False,
) -> dict:
    if only is not None and only not in _ONLY_VALUES:
        raise ValueError(f"only must be one of {_ONLY_VALUES} or None, got {only!r}")

    report: dict = {"pdf": [], "office": [], "copy": [], "errors": []}

    def _translate_one_pdf(rel_src: str, rel_out: str) -> dict:
        src = config.paths.source_dir / rel_src
        out = config.paths.output_dir / rel_out
        if not force and _up_to_date(src, out):
            return {"src": rel_src, "status": "skipped"}
        t0 = time.time()
        try:
            rep = translate_pdf_document(
                src, out, rel_src, backend, entities, glossary, post_rules, config, debug=debug,
            )
            rep["src"] = rel_src
            rep["status"] = "ok"
            rep["seconds"] = round(time.time() - t0, 1)
            return rep
        except Exception as e:
            log.error("PDF failed: %s: %s", rel_src, e)
            return {"src": rel_src, "status": "ERROR", "error": str(e)}

    if only in (None, "pdf"):
        items = list(documents.pdf.items())

        def _is_scan(item: tuple[str, str]) -> bool:
            rel_src, _rel_out = item
            try:
                return classify_pdf(str(config.paths.source_dir / rel_src)) == "scan"
            except Exception:
                return True

        items.sort(key=_is_scan)
        results = _run_items(_translate_one_pdf, items, jobs)
        report["pdf"] = results
        report["errors"].extend(
            {"src": r["src"], "error": r["error"]} for r in results if r.get("status") == "ERROR"
        )

    def _translate_one_office(rel_src: str, rel_out: str) -> dict:
        src = config.paths.source_dir / rel_src
        out = config.paths.output_dir / rel_out
        if not force and _up_to_date(src, out):
            return {"src": rel_src, "status": "skipped"}
        try:
            result = translate_office_document(
                src, out, rel_src, backend, entities, glossary, post_rules, config,
            )
            return {
                "src": rel_src, "status": "ok",
                "nodes": result["stats"]["nodes"],
                "lost_parts": result["diff"]["lost"],
                "failures": len(result["failures"]),
            }
        except Exception as e:
            log.error("Office file failed: %s: %s", rel_src, e)
            return {"src": rel_src, "status": "ERROR", "error": str(e)}

    if only in (None, "office"):
        items = list(documents.office.items())
        results = _run_items(_translate_one_office, items, jobs)
        report["office"] = results
        for r in results:
            if r.get("status") == "ERROR":
                report["errors"].append({"src": r["src"], "error": r["error"]})
            elif r.get("lost_parts"):
                report["errors"].append(
                    {"src": r["src"], "error": f"LOST PARTS: {r['lost_parts']}"}
                )

    if only in (None, "copy"):
        for rel in documents.copy_as_is.files:
            src = config.paths.source_dir / rel
            out = config.paths.output_dir / rel
            try:
                status = _copy_verbatim(src, out, force)
                report["copy"].append({"src": rel, "status": status})
            except Exception as e:
                report["errors"].append({"src": rel, "error": str(e)})
                report["copy"].append({"src": rel, "status": "ERROR", "error": str(e)})

        for rel in documents.copy_as_is.dirs:
            # A copy-as-is directory name may appear at more than one
            # place in the source tree -- walk to find every occurrence
            # rather than assuming a single fixed location.
            for root, dirs, _files in os.walk(config.paths.source_dir):
                if rel not in dirs:
                    continue
                full_rel = Path(root).relative_to(config.paths.source_dir) / rel
                src = config.paths.source_dir / full_rel
                out = config.paths.output_dir / full_rel
                try:
                    status = _copy_tree_verbatim(src, out, force)
                    report["copy"].append({"src": str(full_rel), "status": status})
                except Exception as e:
                    report["errors"].append({"src": str(full_rel), "error": str(e)})
                    report["copy"].append(
                        {"src": str(full_rel), "status": "ERROR", "error": str(e)}
                    )

    return report
