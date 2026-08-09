"""Command-line entry point.

Exit codes: 0 clean · 1 completed with untranslated paragraphs · 2 usage
(argparse's own default) · 3 hard failure (`PalimpsestError`).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

import fitz
from dotenv import find_dotenv, load_dotenv

from palimpsest import __version__
from palimpsest.config import loader as config_loader
from palimpsest.config.model import Config, DocumentMap
from palimpsest.core import paths as core_paths
from palimpsest.core.errors import DependencyError, PalimpsestError
from palimpsest.core.logging import configure as configure_logging
from palimpsest.corpus import run_corpus
from palimpsest.office.pipeline import translate_office_document
from palimpsest.pdf import layout
from palimpsest.pdf.classify import classify_pdf
from palimpsest.pdf.pipeline import translate_pdf_document
from palimpsest.qa.audit import poisoned_fragment_entries
from palimpsest.qa.compare import build_dual_pdf, side_by_side
from palimpsest.text import postfix
from palimpsest.text.glossary import Glossary
from palimpsest.text.protect import EntityGuard
from palimpsest.translate.backend import TranslationContext
from palimpsest.translate.cache import Cache, compute_namespace
from palimpsest.translate.estimate import estimate_document, format_document_estimate
from palimpsest.translate.registry import make_backend
from palimpsest.translate.translator import Translator

_OFFICE_EXTS = {".xlsx", ".xls", ".docx", ".pptx"}

Context = tuple[Config, tuple[str, ...], Glossary, DocumentMap, tuple[tuple[str, str], ...]]


# -- config / context loading -------------------------------------------------


def _config_path(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    candidate = Path.cwd() / "palimpsest.toml"
    return candidate if candidate.is_file() else None


def load_context(config_arg: str | None) -> Context:
    config = config_loader.load(_config_path(config_arg))
    entities = config_loader.load_entities(config)
    glossary = (
        Glossary.load(domains=config.glossary.domains, extra=config.glossary.extra)
        if config.glossary.domains or config.glossary.extra
        else Glossary()
    )
    documents = config_loader.load_documents(config)
    post_rules = tuple(postfix.load(sets=config.postrules.sets, extra=config.postrules.extra))
    return config, entities, glossary, documents, post_rules


def _backend_for(config: Config, override_name: str | None):
    if override_name and override_name != config.backend.name:
        config = dataclasses.replace(
            config, backend=dataclasses.replace(config.backend, name=override_name)
        )
    return make_backend(config)


# -- output path resolution ---------------------------------------------------


def resolve_output(
    input_path: Path, explicit_out: str | None, config: Config, documents: DocumentMap
) -> tuple[Path, str]:
    """Returns (output_path, rel) -- `rel` is the canonical key used for
    this document's cache file and cache namespace. Resolution order:
    explicit `-o` -> document-map lookup -> mirror the source-relative
    path under output_dir -> `<stem>.<target>.<ext>` beside the input
    when there is no source_dir relationship at all."""
    try:
        rel_path = input_path.resolve().relative_to(config.paths.source_dir.resolve())
        rel = str(core_paths.norm_rel(str(rel_path)))
    except ValueError:
        rel = None

    if explicit_out:
        return Path(explicit_out), (rel or input_path.name)

    if rel is not None:
        table = documents.pdf if input_path.suffix.lower() == ".pdf" else documents.office
        target = table.get(rel, rel)
        return core_paths.to_fs(config.paths.output_dir, target), rel

    target_lang = config.language.target
    out = input_path.with_name(f"{input_path.stem}.{target_lang}{input_path.suffix}")
    return out, input_path.name


def _parse_pages(spec: str) -> set[int]:
    """"1-5,11" -> {0,1,2,3,4,10} (0-indexed)."""
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            pages.update(range(int(a) - 1, int(b)))
        else:
            pages.add(int(part) - 1)
    return pages


# -- translate -----------------------------------------------------------------


def _open_cache(rel: str, config: Config, backend, entities, glossary) -> Cache:
    key = core_paths.cache_key(core_paths.norm_rel(rel))
    cache_path = config.paths.cache_dir / f"{key}.json"
    namespace = compute_namespace(
        backend.name, getattr(backend, "model", None), config.language.source,
        config.language.target, glossary_terms=glossary.terms, entities=entities,
    )
    return Cache(cache_path, namespace=namespace)


def _dry_run_pdf(input_path: Path, rel: str, config: Config, backend, entities, glossary) -> None:
    kind = classify_pdf(str(input_path))
    scanned = kind in ("scan", "ocr")
    min_size = (
        config.thresholds.min_text_size_scan if scanned else config.thresholds.min_text_size
    )
    guard = EntityGuard(entities)
    doc = fitz.open(str(input_path))
    n_pages = len(doc)
    all_texts = []
    for pno in range(n_pages):
        for p in layout.extract_paragraphs(doc[pno], min_size=min_size):
            if not guard.skip(p.text):
                all_texts.append(p.text)
    doc.close()

    cache = _open_cache(rel, config, backend, entities, glossary)
    ctx = TranslationContext(
        source_lang=config.language.source, target_lang=config.language.target,
        entities=entities, glossary=glossary.terms,
    )
    est = estimate_document(rel, all_texts, backend, ctx, cache, kind=kind, pages=n_pages)
    print(format_document_estimate(est))


def _dry_run_office(
    input_path: Path, rel: str, config: Config, backend, entities, glossary
) -> None:
    from palimpsest.office import ooxml

    strings = ooxml.collect_strings(str(input_path))
    names = [n for n in ooxml.sheet_names(str(input_path)) if ooxml._translatable(n)]

    cache = _open_cache(rel, config, backend, entities, glossary)
    ctx = TranslationContext(
        source_lang=config.language.source, target_lang=config.language.target,
        entities=entities, glossary=glossary.terms,
    )
    est = estimate_document(rel, strings + names, backend, ctx, cache)
    print(format_document_estimate(est))


def cmd_translate(args: argparse.Namespace) -> int:
    config, entities, glossary, documents, post_rules = load_context(args.config)
    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"error: no such file: {input_path}", file=sys.stderr)
        return 2

    out, rel = resolve_output(input_path, args.output, config, documents)
    ext = input_path.suffix.lower()

    up_to_date = out.exists() and out.stat().st_mtime >= input_path.stat().st_mtime
    if not args.dry_run and not args.force and up_to_date:
        print(f"[{rel}] up to date, skipping (use --force to retranslate)")
        return 0

    backend = _backend_for(config, args.backend)

    if ext == ".pdf":
        if args.dry_run:
            _dry_run_pdf(input_path, rel, config, backend, entities, glossary)
            return 0
        pages = _parse_pages(args.pages) if args.pages else None
        report = translate_pdf_document(
            input_path, out, rel, backend, entities, glossary, post_rules, config,
            debug=args.debug_boxes, pages=pages,
        )
        print(
            f"[{rel}] kind={report['kind']} pages={report['pages']} "
            f"paragraphs={report['paragraphs']} translated={report['translated']} "
            f"skipped={report['skipped']} failed={len(report['failed'])}"
        )
        for f in report["failed"][:10]:
            print(f"  UNTRANSLATED p{f['page']} [{f['status']}] {f['text'][:90]!r}")
        if args.dual:
            dual_dest = out.with_name(f"{out.stem}.dual{out.suffix}")
            build_dual_pdf(input_path, out, dual_dest)
            print(f"  dual: {dual_dest}")
        return 1 if report["failed"] else 0

    if ext in _OFFICE_EXTS:
        if args.dry_run:
            _dry_run_office(input_path, rel, config, backend, entities, glossary)
            return 0
        result = translate_office_document(
            input_path, out, rel, backend, entities, glossary, post_rules, config
        )
        print(
            f"[{rel}] nodes={result['stats']['nodes']} "
            f"lost_parts={len(result['diff']['lost'])} failures={len(result['failures'])}"
        )
        if result["diff"]["lost"]:
            print(f"  LOST PARTS: {result['diff']['lost']}")
        return 1 if result["failures"] else 0

    print(f"error: unsupported file extension: {ext}", file=sys.stderr)
    return 2


# -- batch ----------------------------------------------------------------


def cmd_batch(args: argparse.Namespace) -> int:
    config, entities, glossary, documents, post_rules = load_context(args.config)
    backend = _backend_for(config, args.backend)
    report = run_corpus(
        config, documents, backend, entities, glossary, post_rules,
        force=args.force, only=args.only, jobs=args.jobs,
    )
    for kind in ("pdf", "office", "copy"):
        ok = sum(1 for r in report[kind] if r.get("status") == "ok")
        skipped = sum(1 for r in report[kind] if r.get("status") == "skipped")
        errors = sum(1 for r in report[kind] if r.get("status") == "ERROR")
        copied = sum(1 for r in report[kind] if r.get("status", "").startswith("copied"))
        if kind == "copy":
            print(f"copy: {copied} copied, {errors} errors")
        else:
            print(f"{kind}: {ok} ok, {skipped} skipped, {errors} errors")
    if report["errors"]:
        print(f"\n{len(report['errors'])} errors:")
        for e in report["errors"]:
            print(f"  {e['src']}: {e['error'][:200]}")
    return 1 if report["errors"] else 0


# -- compare ----------------------------------------------------------------


def cmd_compare(args: argparse.Namespace) -> int:
    pages = [p - 1 for p in (int(x) for x in args.pages.split(","))]
    dest = Path(args.output) if args.output else Path("compare.png")
    result = side_by_side(args.source, args.output_pdf, pages, dest, dpi=args.dpi)
    print(f"wrote {result}")
    return 0


# -- cache ----------------------------------------------------------------


def cmd_cache(args: argparse.Namespace) -> int:
    config, entities, glossary, _documents, post_rules = load_context(args.config)
    files = sorted(config.paths.cache_dir.glob("*.json"))

    if args.cache_action == "stats":
        totals: dict[str, int] = {}
        for path in files:
            data = json.loads(path.read_text(encoding="utf-8"))
            for entries in data.get("namespaces", {}).values():
                for entry in entries.values():
                    status = entry.get("status", "unknown")
                    totals[status] = totals.get(status, 0) + 1
        print(f"{len(files)} cache file(s)")
        for status, count in sorted(totals.items()):
            print(f"  {status}: {count}")
        return 0

    if args.cache_action == "pending":
        total = 0
        for path in files:
            data = json.loads(path.read_text(encoding="utf-8"))
            for ns, entries in data.get("namespaces", {}).items():
                for key, entry in entries.items():
                    if entry.get("status") != "ok":
                        total += 1
                        print(f"[{path.name}:{ns}] [{entry.get('status')}] {key[:90]!r}")
        print(f"{total} pending")
        return 1 if total else 0

    if args.cache_action == "retry":
        backend = _backend_for(config, args.backend)
        namespace = compute_namespace(
            backend.name, getattr(backend, "model", None), config.language.source,
            config.language.target, glossary_terms=glossary.terms, entities=entities,
            post_rules=post_rules,
        )
        recovered_total = 0
        pending_total = 0
        for path in files:
            tr = Translator(
                path, backend, cache_namespace=namespace, entities=entities,
                glossary=glossary, post_rules=post_rules, source=config.language.source,
                target=config.language.target, verbose=False,
            )
            recovered, total = tr.retry_pending()
            recovered_total += recovered
            pending_total += total
        print(f"recovered {recovered_total}/{pending_total}")
        return 0

    if args.cache_action == "purge":
        if not args.yes:
            print(f"would delete {len(files)} cache file(s) under {config.paths.cache_dir}")
            print("pass --yes to actually delete them")
            return 0
        for path in files:
            path.unlink()
        print(f"deleted {len(files)} cache file(s)")
        return 0

    return 2


# -- audit ----------------------------------------------------------------


def cmd_audit(args: argparse.Namespace) -> int:
    config, entities, _glossary, _documents, _post_rules = load_context(args.config)

    if args.audit_action == "cache":
        hits = poisoned_fragment_entries(config.paths.cache_dir, entities)
        if not hits:
            print("clean: no protected-entity fragments found mistranslated in cache")
            return 0
        print(f"{len(hits)} poisoned cache entr{'y' if len(hits) == 1 else 'ies'}:")
        for h in hits:
            print(f"  [{h.cache_file.name}:{h.namespace}] {h.source!r} -> {h.cached_value!r}")
        return 1

    return 2


# -- config -----------------------------------------------------------------


def cmd_config(args: argparse.Namespace) -> int:
    if args.config_action == "init":
        private_dir = Path.cwd() / "private"
        private_dir.mkdir(exist_ok=True)
        (private_dir / ".gitignore").write_text("*\n", encoding="utf-8")

        root_gitignore = Path.cwd() / ".gitignore"
        line = "private/"
        existing = root_gitignore.read_text(encoding="utf-8") if root_gitignore.is_file() else ""
        if line not in existing.splitlines():
            with root_gitignore.open("a", encoding="utf-8") as fh:
                if existing and not existing.endswith("\n"):
                    fh.write("\n")
                fh.write(f"{line}\n")
        print(f"scaffolded {private_dir} (gitignored)")
        return 0

    if args.config_action == "show":
        config, _e, _g, _d, _p = load_context(args.config)
        print(json.dumps(_config_to_jsonable(config), indent=2, ensure_ascii=False))
        return 0

    if args.config_action == "validate":
        try:
            load_context(args.config)
        except PalimpsestError as e:
            print(f"invalid: {e}", file=sys.stderr)
            return 3
        print("ok")
        return 0

    return 2


def cmd_serve(args: argparse.Namespace) -> int:
    if args.host != "127.0.0.1" and not args.i_know:
        print(
            f"error: --host {args.host} binds beyond localhost -- pass --i-know to confirm "
            "you understand this exposes the server (and anything it can reach on your "
            "filesystem) to your network, not just this machine.",
            file=sys.stderr,
        )
        return 2

    try:
        import uvicorn
    except ImportError as e:
        raise DependencyError(
            "the 'server' extra is required for `palimpsest serve` -- "
            "install with `pip install palimpsest-translate[server]`"
        ) from e

    from palimpsest.server.app import create_app

    config, _entities, _glossary, _documents, _post_rules = load_context(args.config)

    static_dir = None
    if not args.dev and not args.api_only:
        packaged = Path(__file__).resolve().parent / "server" / "static"
        static_dir = Path(args.static) if args.static else packaged

    extra_origins = frozenset(({args.dev_origin} if args.dev else set()) | set(args.allow_origin))
    app = create_app(config, static_dir=static_dir, extra_origins=extra_origins)

    url = f"http://{args.host}:{args.port}"
    print(f"palimpsest serving at {url}")
    if not args.no_browser:
        import webbrowser

        webbrowser.open(url)

    log_level = "info" if args.verbose else "warning"
    uvicorn.run(app, host=args.host, port=args.port, log_level=log_level)
    return 0


def _config_to_jsonable(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _config_to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (list, tuple)):
        return [_config_to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _config_to_jsonable(v) for k, v in obj.items()}
    return obj


# -- argument parser ----------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="palimpsest", description=__doc__)
    parser.add_argument("--version", action="version", version=f"palimpsest {__version__}")
    parser.add_argument("--config", help="path to palimpsest.toml (default: ./palimpsest.toml)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_translate = sub.add_parser("translate", help="translate a single document")
    p_translate.add_argument("input")
    p_translate.add_argument("-o", "--output")
    p_translate.add_argument("--pages", help="e.g. 1-5,11 (PDF only)")
    p_translate.add_argument("--backend", help="override [backend].name for this run")
    p_translate.add_argument("--dual", action="store_true", help="also write a bilingual PDF")
    p_translate.add_argument("--dry-run", action="store_true")
    p_translate.add_argument("--debug-boxes", action="store_true")
    p_translate.add_argument("--force", action="store_true")
    p_translate.set_defaults(func=cmd_translate)

    p_batch = sub.add_parser("batch", help="translate the whole configured corpus")
    p_batch.add_argument("--only", choices=("pdf", "office", "copy"))
    p_batch.add_argument("--backend")
    p_batch.add_argument("--force", action="store_true")
    p_batch.add_argument("--jobs", type=int, default=1)
    p_batch.set_defaults(func=cmd_batch)

    p_compare = sub.add_parser("compare", help="render source/output pages side by side")
    p_compare.add_argument("source")
    p_compare.add_argument("output_pdf")
    p_compare.add_argument("--pages", required=True, help="1-indexed, e.g. 1,2")
    p_compare.add_argument("--dpi", type=int, default=110)
    p_compare.add_argument("-o", "--output", help="destination PNG (default: compare.png)")
    p_compare.set_defaults(func=cmd_compare)

    p_cache = sub.add_parser("cache", help="inspect or repair the translation cache")
    p_cache.add_argument(
        "cache_action", choices=("stats", "pending", "retry", "purge")
    )
    p_cache.add_argument("--backend")
    p_cache.add_argument("--yes", action="store_true", help="required for `purge` to act")
    p_cache.set_defaults(func=cmd_cache)

    p_audit = sub.add_parser("audit", help="run a maintained invariant check")
    p_audit.add_argument("audit_action", choices=("cache",))
    p_audit.set_defaults(func=cmd_audit)

    p_config = sub.add_parser("config", help="scaffold, show, or validate configuration")
    p_config.add_argument("config_action", choices=("init", "show", "validate"))
    p_config.set_defaults(func=cmd_config)

    p_serve = sub.add_parser("serve", help="run the local web UI (requires the 'server' extra)")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.add_argument(
        "--i-know", dest="i_know", action="store_true",
        help="required alongside --host to bind beyond localhost",
    )
    p_serve.add_argument(
        "--dev", action="store_true",
        help="serve the API only, expecting `npm run dev` (Vite) to serve the frontend",
    )
    p_serve.add_argument(
        "--dev-origin", default="http://localhost:5173",
        help="the Vite dev server's origin, allowed cross-origin only with --dev",
    )
    p_serve.add_argument(
        "--api-only", action="store_true",
        help="serve the API only, no static SPA mount -- for a production API-only host "
        "(e.g. a Docker deployment fronted by a separately-published frontend build). "
        "Unlike --dev, does NOT fold --dev-origin into the allowed origins; pair with "
        "one or more --allow-origin flags naming the real frontend origin(s) instead.",
    )
    p_serve.add_argument(
        "--allow-origin", action="append", default=[],
        help="an additional origin (e.g. a GitHub Pages URL, exact scheme+host, no "
        "trailing slash) allowed to make cross-origin requests -- repeatable. Only ever "
        "use this for an origin you control; never a wildcard.",
    )
    p_serve.add_argument("--static", help="override the built SPA directory")
    p_serve.add_argument("--no-browser", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(verbose=args.verbose)
    # override=False: a real exported env var always beats .env -- this is a
    # fallback for the unset case, never a way to shadow the shell. CLI-only
    # (not in config/loader.py or server/app.py) so importing palimpsest as a
    # library never mutates the host process's environment as a side effect.
    load_dotenv(find_dotenv(usecwd=True), override=False)
    try:
        return args.func(args)
    except PalimpsestError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
