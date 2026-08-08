"""CLI-layer tests. No test here makes a real network call: every test
that would otherwise construct a real backend monkeypatches
`palimpsest.cli.make_backend` to return a `FakeBackend` instead --
`translate.registry.make_backend` itself is already covered directly in
test_registry.py.
"""

from __future__ import annotations

import json
import os

import fitz
import pytest

from palimpsest import cli
from palimpsest.config.model import Config, DocumentMap, PathsConfig
from tests.fixtures.fake_backend import FakeBackend


def _pdf(path, text="Un parrafo de prueba con suficiente texto para ser digital."):
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_textbox(fitz.Rect(20, 20, 380, 180), text, fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def _patch_context(monkeypatch, config, entities=(), documents=None, post_rules=()):
    """Stub out cli.load_context() so tests never read a real
    palimpsest.toml -- config/entities/documents/post_rules are supplied
    directly instead."""
    documents = documents if documents is not None else DocumentMap()
    monkeypatch.setattr(
        cli, "load_context", lambda arg: (config, entities, _glossary(), documents, post_rules)
    )


@pytest.fixture(autouse=True)
def _no_real_backend(monkeypatch):
    """Every test in this file gets a FakeBackend from make_backend()
    unless it explicitly overrides this fixture's target itself."""
    monkeypatch.setattr(
        cli, "make_backend",
        lambda config: FakeBackend(
            translate_fn=lambda s: s.upper(), uses_placeholder_protection=False
        ),
    )


# -- _parse_pages -------------------------------------------------------

def test_parse_pages_range():
    assert cli._parse_pages("1-5") == {0, 1, 2, 3, 4}


def test_parse_pages_single_and_range_and_list():
    assert cli._parse_pages("1-3,7,9") == {0, 1, 2, 6, 8}


def test_parse_pages_single_page():
    assert cli._parse_pages("11") == {10}


# -- resolve_output -------------------------------------------------------

def test_resolve_output_explicit_wins(tmp_path):
    config = Config(paths=PathsConfig(source_dir=tmp_path / "source", output_dir=tmp_path / "out"))
    input_path = tmp_path / "anywhere.pdf"
    out, rel = cli.resolve_output(input_path, str(tmp_path / "explicit.pdf"), config, DocumentMap())
    assert out == tmp_path / "explicit.pdf"


def test_resolve_output_document_map_hit(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    input_path = source_dir / "deed.pdf"
    input_path.write_bytes(b"x")
    config = Config(paths=PathsConfig(source_dir=source_dir, output_dir=tmp_path / "out"))
    documents = DocumentMap(pdf={"deed.pdf": "Deed (English).pdf"})
    out, rel = cli.resolve_output(input_path, None, config, documents)
    assert out == tmp_path / "out" / "Deed (English).pdf"
    assert rel == "deed.pdf"


def test_resolve_output_mirrors_when_not_in_map(tmp_path):
    source_dir = tmp_path / "source"
    (source_dir / "Corp").mkdir(parents=True)
    input_path = source_dir / "Corp" / "unmapped.pdf"
    input_path.write_bytes(b"x")
    config = Config(paths=PathsConfig(source_dir=source_dir, output_dir=tmp_path / "out"))
    out, rel = cli.resolve_output(input_path, None, config, DocumentMap())
    assert out == tmp_path / "out" / "Corp" / "unmapped.pdf"
    assert rel == "Corp/unmapped.pdf"


def test_resolve_output_no_source_dir_relationship(tmp_path):
    config = Config(
        paths=PathsConfig(source_dir=tmp_path / "source_never_used", output_dir=tmp_path / "out")
    )
    input_path = tmp_path / "elsewhere" / "standalone.pdf"
    input_path.parent.mkdir()
    input_path.write_bytes(b"x")
    out, rel = cli.resolve_output(input_path, None, config, DocumentMap())
    assert out == input_path.parent / "standalone.en.pdf"
    assert rel == "standalone.pdf"


# -- cmd_translate ----------------------------------------------------------

def _config(tmp_path) -> Config:
    return Config(
        paths=PathsConfig(
            source_dir=tmp_path / "source", output_dir=tmp_path / "out",
            work_dir=tmp_path / "work", cache_dir=tmp_path / "cache",
        )
    )


def test_translate_pdf_end_to_end(tmp_path, monkeypatch):
    _patch_context(monkeypatch, _config(tmp_path))
    src = tmp_path / "in.pdf"
    _pdf(src)
    rc = cli.main(["translate", str(src), "-o", str(tmp_path / "out.pdf")])
    assert rc == 0
    assert (tmp_path / "out.pdf").exists()


def test_translate_missing_file_exits_2(tmp_path, monkeypatch):
    _patch_context(monkeypatch, _config(tmp_path))
    rc = cli.main(["translate", str(tmp_path / "does_not_exist.pdf")])
    assert rc == 2


def test_translate_unsupported_extension_exits_2(tmp_path, monkeypatch):
    _patch_context(monkeypatch, _config(tmp_path))
    bogus = tmp_path / "file.txt"
    bogus.write_text("hello")
    rc = cli.main(["translate", str(bogus)])
    assert rc == 2


def test_translate_skips_when_up_to_date(tmp_path, monkeypatch, capsys):
    _patch_context(monkeypatch, _config(tmp_path))
    src = tmp_path / "in.pdf"
    _pdf(src)
    out = tmp_path / "out.pdf"
    rc1 = cli.main(["translate", str(src), "-o", str(out)])
    assert rc1 == 0
    rc2 = cli.main(["translate", str(src), "-o", str(out)])
    assert rc2 == 0
    assert "up to date" in capsys.readouterr().out


def test_translate_force_reprocesses(tmp_path, monkeypatch):
    _patch_context(monkeypatch, _config(tmp_path))
    src = tmp_path / "in.pdf"
    _pdf(src)
    out = tmp_path / "out.pdf"
    cli.main(["translate", str(src), "-o", str(out)])
    rc = cli.main(["translate", str(src), "-o", str(out), "--force"])
    assert rc == 0


def test_translate_dry_run_pdf(tmp_path, monkeypatch, capsys):
    _patch_context(monkeypatch, _config(tmp_path))
    src = tmp_path / "in.pdf"
    _pdf(src)
    rc = cli.main(["translate", str(src), "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "kind=digital" in out
    assert not (tmp_path / "out").exists()  # no output written on a dry run


def test_translate_pages_filter(tmp_path, monkeypatch):
    _patch_context(monkeypatch, _config(tmp_path))
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=400, height=200)
        page.insert_textbox(
            fitz.Rect(20, 20, 380, 180), f"Pagina {i} con suficiente texto para ser digital.",
            fontsize=12, fontname="helv",
        )
    src = tmp_path / "in.pdf"
    doc.save(src)
    doc.close()
    out = tmp_path / "out.pdf"
    rc = cli.main(["translate", str(src), "-o", str(out), "--pages", "1"])
    assert rc == 0
    assert out.exists()


def test_translate_dual_writes_extra_file(tmp_path, monkeypatch):
    _patch_context(monkeypatch, _config(tmp_path))
    src = tmp_path / "in.pdf"
    _pdf(src)
    out = tmp_path / "out.pdf"
    rc = cli.main(["translate", str(src), "-o", str(out), "--dual"])
    assert rc == 0
    assert (tmp_path / "out.dual.pdf").exists()


def _glossary():
    from palimpsest.text.glossary import Glossary

    return Glossary()


# -- cmd_batch ----------------------------------------------------------

def test_batch_dispatch(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.paths.source_dir.mkdir()
    _pdf(config.paths.source_dir / "doc.pdf")
    documents = DocumentMap(pdf={"doc.pdf": "doc.pdf"})
    monkeypatch.setattr(cli, "load_context", lambda arg: (config, (), _glossary(), documents, ()))
    rc = cli.main(["batch", "--only", "pdf"])
    assert rc == 0
    assert (config.paths.output_dir / "doc.pdf").exists()


# -- cmd_compare ----------------------------------------------------------

def test_compare_dispatch(tmp_path):
    src = tmp_path / "src.pdf"
    out = tmp_path / "out.pdf"
    _pdf(src, "Original")
    _pdf(out, "Translated")
    dest = tmp_path / "compare.png"
    rc = cli.main(["compare", str(src), str(out), "--pages", "1", "-o", str(dest)])
    assert rc == 0
    assert dest.exists()


# -- cmd_cache ------------------------------------------------------------

def _seed_cache(cache_dir, filename, namespace, entries):
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / filename).write_text(
        json.dumps({"namespaces": {namespace: entries}}), encoding="utf-8"
    )


def test_cache_stats(tmp_path, monkeypatch, capsys):
    config = _config(tmp_path)
    _seed_cache(
        config.paths.cache_dir, "doc.json", "google:abc",
        {"hola": {"en": "hello", "status": "ok"}, "adios": {"en": None, "status": "failed"}},
    )
    _patch_context(monkeypatch, config)
    rc = cli.main(["cache", "stats"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ok: 1" in out
    assert "failed: 1" in out


def test_cache_pending_exits_1_when_nonempty(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _seed_cache(
        config.paths.cache_dir, "doc.json", "google:abc",
        {"adios": {"en": None, "status": "failed"}},
    )
    _patch_context(monkeypatch, config)
    rc = cli.main(["cache", "pending"])
    assert rc == 1


def test_cache_pending_exits_0_when_empty(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _seed_cache(
        config.paths.cache_dir, "doc.json", "google:abc", {"hola": {"en": "hi", "status": "ok"}}
    )
    _patch_context(monkeypatch, config)
    rc = cli.main(["cache", "pending"])
    assert rc == 0


def test_cache_retry_recovers_pending_entries(tmp_path, monkeypatch):
    config = _config(tmp_path)
    from palimpsest.translate.cache import compute_namespace

    namespace = compute_namespace("fake", None, "es", "en")
    _seed_cache(
        config.paths.cache_dir, "doc.json", namespace,
        {"hola": {"en": None, "status": "failed"}},
    )
    _patch_context(monkeypatch, config)
    monkeypatch.setattr(
        cli, "make_backend",
        lambda config: FakeBackend(
            translate_fn=lambda s: "hello", uses_placeholder_protection=False
        ),
    )
    rc = cli.main(["cache", "retry"])
    assert rc == 0


def test_cache_purge_requires_yes(tmp_path, monkeypatch, capsys):
    config = _config(tmp_path)
    _seed_cache(config.paths.cache_dir, "doc.json", "google:abc", {})
    _patch_context(monkeypatch, config)
    rc = cli.main(["cache", "purge"])
    assert rc == 0
    assert (config.paths.cache_dir / "doc.json").exists()
    assert "--yes" in capsys.readouterr().out


def test_cache_purge_with_yes_deletes(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _seed_cache(config.paths.cache_dir, "doc.json", "google:abc", {})
    _patch_context(monkeypatch, config)
    rc = cli.main(["cache", "purge", "--yes"])
    assert rc == 0
    assert not (config.paths.cache_dir / "doc.json").exists()


# -- cmd_audit ------------------------------------------------------------

def test_audit_cache_clean(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _seed_cache(
        config.paths.cache_dir, "doc.json", "google:abc",
        {"clean": {"en": "clean", "status": "ok"}},
    )
    _patch_context(monkeypatch, config, entities=("Grupo Meridian",))
    rc = cli.main(["audit", "cache"])
    assert rc == 0


def test_audit_cache_poisoned_exits_1(tmp_path, monkeypatch, capsys):
    config = _config(tmp_path)
    _seed_cache(
        config.paths.cache_dir, "doc.json", "google:abc",
        {"GRUPO": {"en": "CLUSTER", "status": "ok"}},
    )
    _patch_context(monkeypatch, config, entities=("Grupo Meridian",))
    rc = cli.main(["audit", "cache"])
    assert rc == 1
    assert "CLUSTER" in capsys.readouterr().out


# -- cmd_config -----------------------------------------------------------

def test_config_init_scaffolds_private_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["config", "init"])
    assert rc == 0
    assert (tmp_path / "private" / ".gitignore").read_text(encoding="utf-8") == "*\n"
    assert "private/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")


def test_config_init_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cli.main(["config", "init"])
    cli.main(["config", "init"])
    gitignore_lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert gitignore_lines.count("private/") == 1


def test_config_show_prints_json(tmp_path, monkeypatch, capsys):
    _patch_context(monkeypatch, _config(tmp_path))
    rc = cli.main(["config", "show"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["language"]["source"] == "es"


def test_config_validate_ok(tmp_path, monkeypatch):
    _patch_context(monkeypatch, _config(tmp_path))
    rc = cli.main(["config", "validate"])
    assert rc == 0


def test_config_validate_reports_error(tmp_path, monkeypatch):
    from palimpsest.core.errors import ConfigError

    def _raise(arg):
        raise ConfigError("boom")

    monkeypatch.setattr(cli, "load_context", _raise)
    rc = cli.main(["config", "validate"])
    assert rc == 3


# -- .env loading -----------------------------------------------------------

def test_main_loads_dotenv_into_unset_var(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PALIMPSEST_TEST_DOTENV_VAR", raising=False)
    (tmp_path / ".env").write_text("PALIMPSEST_TEST_DOTENV_VAR=from-dotenv\n", encoding="utf-8")
    cli.main(["config", "init"])
    assert os.environ["PALIMPSEST_TEST_DOTENV_VAR"] == "from-dotenv"


def test_main_dotenv_never_overrides_real_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PALIMPSEST_TEST_DOTENV_VAR", "from-shell")
    (tmp_path / ".env").write_text("PALIMPSEST_TEST_DOTENV_VAR=from-dotenv\n", encoding="utf-8")
    cli.main(["config", "init"])
    assert os.environ["PALIMPSEST_TEST_DOTENV_VAR"] == "from-shell"
