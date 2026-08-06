from pathlib import Path

import pytest

from palimpsest.config import loader
from palimpsest.core.errors import ConfigError


def test_load_none_returns_pure_defaults():
    config = loader.load(None)
    assert config.thresholds.bold_stem_ratio == 0.155
    assert config.language.source == "es"
    assert config.language.target == "en"


def test_missing_config_file_raises():
    with pytest.raises(ConfigError):
        loader.load(Path("does/not/exist.toml"))


def test_invalid_toml_raises_config_error(tmp_path):
    bad = tmp_path / "palimpsest.toml"
    bad.write_text("this is not [valid toml", encoding="utf-8")
    with pytest.raises(ConfigError):
        loader.load(bad)


def test_unsupported_schema_raises(tmp_path):
    cfg = tmp_path / "palimpsest.toml"
    cfg.write_text("schema = 99\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        loader.load(cfg)


def test_project_overrides_one_threshold_without_resetting_others(tmp_path):
    cfg = tmp_path / "palimpsest.toml"
    cfg.write_text("[thresholds]\nbold_stem_ratio = 0.2\n", encoding="utf-8")
    config = loader.load(cfg)
    assert config.thresholds.bold_stem_ratio == 0.2
    # Untouched thresholds keep their packaged default.
    assert config.thresholds.min_text_size_scan == 7.0


def test_relative_paths_resolve_against_config_file_directory(tmp_path):
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    cfg = project_dir / "palimpsest.toml"
    cfg.write_text(
        '[paths]\nsource_dir = "corpus/source"\n',
        encoding="utf-8",
    )
    config = loader.load(cfg)
    assert config.paths.source_dir == project_dir / "corpus" / "source"


def test_absolute_path_is_not_rebased(tmp_path):
    cfg = tmp_path / "palimpsest.toml"
    abs_dir = tmp_path / "elsewhere"
    toml_value = str(abs_dir).replace("\\", "\\\\")
    cfg.write_text(f'[paths]\nwork_dir = "{toml_value}"\n', encoding="utf-8")
    config = loader.load(cfg)
    assert config.paths.work_dir == abs_dir


def test_backend_defaults():
    config = loader.load(None)
    assert config.backend.name == "gemini"
    assert config.backend.fallback == "anthropic"
    assert config.backend.gemini.model == "gemini-3.5-flash-lite"
    assert config.backend.anthropic.model == "claude-opus-5"


def test_backend_override_preserves_unset_fields(tmp_path):
    cfg = tmp_path / "palimpsest.toml"
    cfg.write_text(
        '[backend.anthropic]\nmodel = "claude-sonnet-5"\n', encoding="utf-8"
    )
    config = loader.load(cfg)
    assert config.backend.anthropic.model == "claude-sonnet-5"
    assert config.backend.anthropic.batch_size == 25  # untouched default


def test_backend_gemini_override_preserves_unset_fields(tmp_path):
    cfg = tmp_path / "palimpsest.toml"
    cfg.write_text('[backend.gemini]\nmodel = "gemini-3.6-flash"\n', encoding="utf-8")
    config = loader.load(cfg)
    assert config.backend.gemini.model == "gemini-3.6-flash"
    assert config.backend.gemini.batch_size == 20  # untouched default


# -- private entities / documents -------------------------------------

def test_load_entities_missing_file_returns_empty_tuple():
    config = loader.load(None)  # private.entities is None
    assert loader.load_entities(config) == ()


def test_load_entities_flattens_all_groups(tmp_path):
    entities_path = tmp_path / "entities.toml"
    entities_path.write_text(
        """
        [entities]
        companies = ["Grupo Meridian"]
        people = ["Andres Carreno"]
        places = ["Santo Domingo Este"]
        other = ["MICM"]
        """,
        encoding="utf-8",
    )
    cfg = tmp_path / "palimpsest.toml"
    cfg.write_text(f'[private]\nentities = "{entities_path.name}"\n', encoding="utf-8")

    config = loader.load(cfg)
    entities = loader.load_entities(config)
    assert set(entities) == {"Grupo Meridian", "Andres Carreno", "Santo Domingo Este", "MICM"}


def test_load_documents_missing_file_returns_empty_maps():
    config = loader.load(None)
    doc_map = loader.load_documents(config)
    assert doc_map.pdf == {}
    assert doc_map.office == {}
    assert doc_map.copy_as_is.dirs == ()


def test_load_documents_reads_pdf_office_and_copy_as_is(tmp_path):
    documents_path = tmp_path / "documents.toml"
    documents_path.write_text(
        """
        [pdf]
        "Deed.pdf" = "Deed (English).pdf"
        [office]
        "Budget.xlsx" = "Budget (English).xlsx"
        [copy_as_is]
        dirs = ["Drawings"]
        files = ["Passport.pdf"]
        """,
        encoding="utf-8",
    )
    cfg = tmp_path / "palimpsest.toml"
    cfg.write_text(f'[private]\ndocuments = "{documents_path.name}"\n', encoding="utf-8")

    config = loader.load(cfg)
    doc_map = loader.load_documents(config)
    assert doc_map.pdf == {"Deed.pdf": "Deed (English).pdf"}
    assert doc_map.office == {"Budget.xlsx": "Budget (English).xlsx"}
    assert doc_map.copy_as_is.dirs == ("Drawings",)
    assert doc_map.copy_as_is.files == ("Passport.pdf",)
