"""Typed configuration model.

Why this exists
----------------
The pipeline this project was extracted from kept its entire configuration
as Python literals in one module: 143 protected entities, a 91-entry
glossary, and a 40-entry source-to-output filename map, alongside runtime
thresholds and an absolute Windows path (`ROOT = r"C:\\Users\\..."`), all
in the same file, imported as code. That made the project's actual
*document* data inseparable from its *code* -- there was no way to publish
the pipeline without publishing the corpus it was built against.

Here, configuration is data (TOML), not code, and it is layered: packaged
defaults (thresholds only, shipped with the package) are overridden by a
project file (`palimpsest.toml`, safe to commit -- it names no documents
or people), which in turn references private files (an entity roster, a
document map) that are gitignored and may simply not exist. A missing
private file is not an error: it resolves to an empty entity list and
identity path mapping, which is what makes `git clone && palimpsest
translate sample.pdf` work with no setup at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class LanguageConfig:
    source: str = "es"
    target: str = "en"


@dataclass(frozen=True)
class PathsConfig:
    """All paths are resolved relative to the directory containing the
    project's palimpsest.toml, not the process's current working
    directory -- so the same config behaves the same regardless of where
    a command happens to be invoked from."""

    source_dir: Path = Path("corpus/source")
    output_dir: Path = Path("corpus/output")
    work_dir: Path = Path(".palimpsest/work")
    cache_dir: Path = Path(".palimpsest/cache")
    report_dir: Path = Path(".palimpsest/reports")

    def ensure_dirs(self) -> None:
        """Create the writable directories. Called explicitly by the CLI,
        never at import time -- a config module that creates directories
        merely by being imported makes the whole package unsafe to import
        in a read-only environment (e.g. under test)."""
        for d in (self.work_dir, self.cache_dir, self.report_dir):
            d.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class PrivateConfig:
    """Paths to gitignored, user-owned files. None means "not configured",
    which callers must treat as "no data", not as an error."""

    entities: Path | None = None
    documents: Path | None = None


@dataclass(frozen=True)
class AnthropicBackendConfig:
    model: str = "claude-opus-5"
    effort: str = "low"
    batch_size: int = 25
    use_batches_api: bool = False
    max_retries: int = 5
    max_concurrency: int = 4


@dataclass(frozen=True)
class GoogleBackendConfig:
    batch_size: int = 20
    pause_seconds: float = 0.35


@dataclass(frozen=True)
class GeminiBackendConfig:
    model: str = "gemini-3.5-flash-lite"
    batch_size: int = 20
    max_output_tokens_per_unit: int = 4096


@dataclass(frozen=True)
class BackendConfig:
    name: str = "gemini"
    fallback: str | None = "anthropic"
    anthropic: AnthropicBackendConfig = field(default_factory=AnthropicBackendConfig)
    google: GoogleBackendConfig = field(default_factory=GoogleBackendConfig)
    gemini: GeminiBackendConfig = field(default_factory=GeminiBackendConfig)


@dataclass(frozen=True)
class GlossaryConfig:
    domains: tuple[str, ...] = ()
    extra: tuple[Path, ...] = ()
    heading_numbers: bool = True


@dataclass(frozen=True)
class PostRulesConfig:
    sets: tuple[str, ...] = ("dates",)
    extra: tuple[Path, ...] = ()


@dataclass(frozen=True)
class OcrConfig:
    enabled: bool = True
    language: str = "spa"
    # "" means auto-detect at runtime (see palimpsest.pdf.ocr), not "no
    # tessdata" -- an empty string is never a valid filesystem path, so it
    # can't be confused with a real configured location.
    tessdata_prefix: str = ""
    oversample: int = 400
    mode: str = "skip-text"
    optimize: int = 1


@dataclass(frozen=True)
class ThresholdsConfig:
    min_text_size: float = 3.0
    min_text_size_scan: float = 7.0
    size_jitter_tolerance: float = 0.75
    bold_stem_ratio: float = 0.155
    ink_dark_threshold: int = 165
    min_scale: float = 0.72
    justify_max_stretch: float = 2.6
    label_max_chars: int = 90


@dataclass(frozen=True)
class LimitsConfig:
    """Abuse guardrails for the SERVER, not the CLI -- a local `palimpsest
    translate` invocation has no need for either of these (the operator
    already controls what they feed it). They matter once a server
    process is reachable by more than one visitor (see server/app.py's
    module docstring): the visitor's own API key already bounds per-
    request cost to whoever's key it is, but compute (OCR, disk) is
    still paid for by the host regardless of whose key is attached."""

    max_upload_bytes: int = 50 * 1024 * 1024
    """Mirrors `server.uploads.MAX_UPLOAD_BYTES`'s default -- that
    module-level constant remains the hardcoded fallback for any caller
    that doesn't thread a `Config` through (e.g. existing unit tests
    exercising `validate_and_save` directly); the server route reads
    this field instead so it's overridable via `[limits]` without a code
    change."""
    max_concurrent_jobs_per_visitor: int = 1
    """Jobs already run one at a time process-wide (one
    `ThreadPoolExecutor(max_workers=1)`, `server/jobs.py`) -- this only
    stops one visitor from QUEUEING many at once ahead of everyone
    else."""


@dataclass(frozen=True)
class FontsConfig:
    scan_default: str = "Calibri"
    extra_dirs: tuple[Path, ...] = ()
    use_bundled_fallback: bool = True
    per_document: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CopyAsIsConfig:
    """Not part of Config / palimpsest.toml on purpose: which directories
    and files get copied through untranslated is corpus-specific and
    typically as disclosive as the document map itself (a copy-as-is
    entry is still a real filename from someone's real documents). It
    lives in the private documents file instead -- see
    `config.loader.load_documents()`."""

    dirs: tuple[str, ...] = ()
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentMap:
    """The private source->output filename mapping and copy-as-is list,
    loaded separately from Config via `config.loader.load_documents()`
    (not part of Config itself -- see CopyAsIsConfig)."""

    pdf: dict[str, str] = field(default_factory=dict)
    office: dict[str, str] = field(default_factory=dict)
    copy_as_is: CopyAsIsConfig = field(default_factory=CopyAsIsConfig)


@dataclass(frozen=True)
class EntityGroups:
    """The private entities file's own grouping, preserved -- unlike
    `config.loader.load_entities()`, which flattens all four groups into
    one tuple for `EntityGuard`, this keeps them apart for anything that
    displays or edits the roster by category (e.g. the web UI's sidebar).
    See `config.loader.load_entity_groups`/`save_entity_groups`."""

    companies: tuple[str, ...] = ()
    people: tuple[str, ...] = ()
    places: tuple[str, ...] = ()
    other: tuple[str, ...] = ()


@dataclass(frozen=True)
class Config:
    schema: int = 1
    language: LanguageConfig = field(default_factory=LanguageConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    private: PrivateConfig = field(default_factory=PrivateConfig)
    backend: BackendConfig = field(default_factory=BackendConfig)
    glossary: GlossaryConfig = field(default_factory=GlossaryConfig)
    postrules: PostRulesConfig = field(default_factory=PostRulesConfig)
    ocr: OcrConfig = field(default_factory=OcrConfig)
    thresholds: ThresholdsConfig = field(default_factory=ThresholdsConfig)
    fonts: FontsConfig = field(default_factory=FontsConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
