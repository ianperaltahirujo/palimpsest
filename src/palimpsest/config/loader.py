"""Load a palimpsest.toml (plus packaged defaults and optional private
files) into a `Config`.

See `model.py` for why configuration is layered data rather than a Python
module of literals.
"""

from __future__ import annotations

import tomllib
from importlib import resources
from pathlib import Path
from typing import Any

from palimpsest.config.model import (
    AnthropicBackendConfig,
    BackendConfig,
    Config,
    CopyAsIsConfig,
    DocumentMap,
    FontsConfig,
    GlossaryConfig,
    GoogleBackendConfig,
    LanguageConfig,
    OcrConfig,
    PathsConfig,
    PostRulesConfig,
    PrivateConfig,
    ThresholdsConfig,
)
from palimpsest.core.errors import ConfigError


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: invalid TOML -- {e}") from e


def _load_defaults() -> dict[str, Any]:
    with resources.files("palimpsest.config").joinpath("defaults.toml").open("rb") as fh:
        return tomllib.load(fh)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """override wins on scalars; dicts merge recursively; anything else
    (lists included) is replaced wholesale rather than concatenated -- a
    project's [thresholds] overriding one value must not require it to
    repeat every other one, but a project's glossary `domains` list is
    meant to fully replace the (empty) default, not append to it."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _resolve(base_dir: Path, value: str | None) -> Path | None:
    if value is None:
        return None
    p = Path(value)
    return p if p.is_absolute() else (base_dir / p)


def _resolve_all(base_dir: Path, values: list[str]) -> tuple[Path, ...]:
    return tuple(_resolve(base_dir, v) for v in values if v is not None)  # type: ignore[misc]


def load(config_path: Path | None) -> Config:
    """Build a Config from packaged defaults, optionally overridden by the
    project file at `config_path`. `config_path=None` returns pure
    defaults (used by `palimpsest config show` before a project exists,
    and by tests that need a Config without a filesystem fixture).

    All relative paths in the resulting Config are resolved against
    `config_path`'s parent directory, not the process's current working
    directory.
    """
    data = _load_defaults()
    base_dir = Path.cwd()

    if config_path is not None:
        if not config_path.is_file():
            raise ConfigError(f"config file not found: {config_path}")
        data = _deep_merge(data, _read_toml(config_path))
        base_dir = config_path.resolve().parent

    schema = data.get("schema", 1)
    if schema != 1:
        raise ConfigError(f"unsupported config schema {schema!r} (expected 1)")

    lang = data.get("language", {})
    paths = data.get("paths", {})
    private = data.get("private", {})
    backend = data.get("backend", {})
    backend_anthropic = backend.get("anthropic", {})
    backend_google = backend.get("google", {})
    glossary = data.get("glossary", {})
    postrules = data.get("postrules", {})
    ocr = data.get("ocr", {})
    thresholds = data.get("thresholds", {})
    fonts = data.get("fonts", {})

    default_paths = PathsConfig()
    default_backend_a = AnthropicBackendConfig()
    default_backend_g = GoogleBackendConfig()
    default_ocr = OcrConfig()
    default_thresholds = ThresholdsConfig()
    default_fonts = FontsConfig()

    return Config(
        schema=schema,
        language=LanguageConfig(
            source=lang.get("source", "es"),
            target=lang.get("target", "en"),
        ),
        paths=PathsConfig(
            source_dir=_resolve(base_dir, paths.get("source_dir")) or default_paths.source_dir,
            output_dir=_resolve(base_dir, paths.get("output_dir")) or default_paths.output_dir,
            work_dir=_resolve(base_dir, paths.get("work_dir")) or default_paths.work_dir,
            cache_dir=_resolve(base_dir, paths.get("cache_dir")) or default_paths.cache_dir,
            report_dir=_resolve(base_dir, paths.get("report_dir")) or default_paths.report_dir,
        ),
        private=PrivateConfig(
            entities=_resolve(base_dir, private.get("entities")),
            documents=_resolve(base_dir, private.get("documents")),
        ),
        backend=BackendConfig(
            name=backend.get("name", "anthropic"),
            fallback=backend.get("fallback", "google"),
            anthropic=AnthropicBackendConfig(
                model=backend_anthropic.get("model", default_backend_a.model),
                effort=backend_anthropic.get("effort", default_backend_a.effort),
                batch_size=backend_anthropic.get("batch_size", default_backend_a.batch_size),
                use_batches_api=backend_anthropic.get(
                    "use_batches_api", default_backend_a.use_batches_api
                ),
                max_retries=backend_anthropic.get("max_retries", default_backend_a.max_retries),
                max_concurrency=backend_anthropic.get(
                    "max_concurrency", default_backend_a.max_concurrency
                ),
            ),
            google=GoogleBackendConfig(
                batch_size=backend_google.get("batch_size", default_backend_g.batch_size),
                pause_seconds=backend_google.get("pause_seconds", default_backend_g.pause_seconds),
            ),
        ),
        glossary=GlossaryConfig(
            domains=tuple(glossary.get("domains", ())),
            extra=_resolve_all(base_dir, glossary.get("extra", [])),
            heading_numbers=glossary.get("heading_numbers", True),
        ),
        postrules=PostRulesConfig(
            sets=tuple(postrules.get("sets", ("dates",))),
            extra=_resolve_all(base_dir, postrules.get("extra", [])),
        ),
        ocr=OcrConfig(
            enabled=ocr.get("enabled", default_ocr.enabled),
            language=ocr.get("language", default_ocr.language),
            tessdata_prefix=ocr.get("tessdata_prefix", default_ocr.tessdata_prefix),
            oversample=ocr.get("oversample", default_ocr.oversample),
            mode=ocr.get("mode", default_ocr.mode),
            optimize=ocr.get("optimize", default_ocr.optimize),
        ),
        thresholds=ThresholdsConfig(
            min_text_size=thresholds.get("min_text_size", default_thresholds.min_text_size),
            min_text_size_scan=thresholds.get(
                "min_text_size_scan", default_thresholds.min_text_size_scan
            ),
            size_jitter_tolerance=thresholds.get(
                "size_jitter_tolerance", default_thresholds.size_jitter_tolerance
            ),
            bold_stem_ratio=thresholds.get("bold_stem_ratio", default_thresholds.bold_stem_ratio),
            ink_dark_threshold=thresholds.get(
                "ink_dark_threshold", default_thresholds.ink_dark_threshold
            ),
            min_scale=thresholds.get("min_scale", default_thresholds.min_scale),
            justify_max_stretch=thresholds.get(
                "justify_max_stretch", default_thresholds.justify_max_stretch
            ),
            label_max_chars=thresholds.get("label_max_chars", default_thresholds.label_max_chars),
        ),
        fonts=FontsConfig(
            scan_default=fonts.get("scan_default", default_fonts.scan_default),
            extra_dirs=_resolve_all(base_dir, fonts.get("extra_dirs", [])),
            use_bundled_fallback=fonts.get(
                "use_bundled_fallback", default_fonts.use_bundled_fallback
            ),
            per_document=dict(fonts.get("per_document", {})),
        ),
    )


def load_entities(config: Config) -> tuple[str, ...]:
    """Flatten the private entities file into one tuple, or return an
    empty tuple if none is configured / the file doesn't exist yet.
    A missing private file is normal, not an error -- see model.py."""
    path = config.private.entities
    if path is None or not path.is_file():
        return ()
    data = _read_toml(path)
    entities = data.get("entities", {})
    out: list[str] = []
    for group in ("companies", "people", "places", "other"):
        out.extend(entities.get(group, []))
    return tuple(out)


def load_documents(config: Config) -> DocumentMap:
    """The private document map (source-relative -> output-relative, per
    format) and copy-as-is list. Returns an empty DocumentMap if no
    private documents file is configured -- callers fall back to
    mirroring the source-relative path under output_dir (see the CLI's
    output-resolution order in PR7)."""
    path = config.private.documents
    if path is None or not path.is_file():
        return DocumentMap()
    data = _read_toml(path)
    copy_as_is = data.get("copy_as_is", {})
    return DocumentMap(
        pdf=dict(data.get("pdf", {})),
        office=dict(data.get("office", {})),
        copy_as_is=CopyAsIsConfig(
            dirs=tuple(copy_as_is.get("dirs", ())),
            files=tuple(copy_as_is.get("files", ())),
        ),
    )
