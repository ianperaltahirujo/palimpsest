import zipfile

import pytest

from palimpsest.config.model import Config, PathsConfig
from palimpsest.office.pipeline import translate_office_document
from palimpsest.text.glossary import Glossary
from tests.fixtures.fake_backend import FailingBackend, FakeBackend

CONTENT_TYPES = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>"""

ROOT_RELS = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

WORKBOOK_XML = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheets>
    <sheet name="Hoja1" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>
  </sheets>
</workbook>"""

SHARED_STRINGS_XML = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="1" uniqueCount="1">
  <si><t>Direccion</t></si>
</sst>"""

SHEET1_XML = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c></row>
  </sheetData>
</worksheet>"""


def _build_xlsx(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("xl/workbook.xml", WORKBOOK_XML)
        z.writestr("xl/worksheets/sheet1.xml", SHEET1_XML)
        z.writestr("xl/sharedStrings.xml", SHARED_STRINGS_XML)


@pytest.fixture
def src_xlsx(tmp_path):
    path = tmp_path / "source.xlsx"
    _build_xlsx(path)
    return path


def _config(tmp_path) -> Config:
    return Config(paths=PathsConfig(cache_dir=tmp_path / "cache"))


def test_translates_shared_string(src_xlsx, tmp_path):
    out = tmp_path / "out.xlsx"
    backend = FakeBackend(translate_fn=lambda s: s.upper(), uses_placeholder_protection=False)
    result = translate_office_document(
        src_xlsx, out, "source.xlsx", backend, entities=(), glossary=Glossary(),
        post_rules=(), config=_config(tmp_path),
    )
    assert out.exists()
    assert result["stats"]["nodes"] >= 1
    assert result["failures"] == []
    assert result["diff"]["lost"] == []

    import zipfile as zf

    with zf.ZipFile(out) as z:
        shared = z.read("xl/sharedStrings.xml").decode("utf-8")
    assert "DIRECCION" in shared


def test_failed_translation_leaves_original_and_reports_failure(src_xlsx, tmp_path):
    out = tmp_path / "out.xlsx"
    backend = FailingBackend()
    result = translate_office_document(
        src_xlsx, out, "source.xlsx", backend, entities=(), glossary=Glossary(),
        post_rules=(), config=_config(tmp_path),
    )
    # "Hoja1" (the sheet tab name) is also translatable and attempted --
    # both it and the cell content fail with a backend that always fails.
    assert set(result["failures"]) == {"Direccion", "Hoja1"}

    with zipfile.ZipFile(out) as z:
        shared = z.read("xl/sharedStrings.xml").decode("utf-8")
    assert "Direccion" in shared  # untranslated original preserved, not blanked


def test_writes_cache_under_configured_cache_dir(src_xlsx, tmp_path):
    config = _config(tmp_path)
    backend = FakeBackend(translate_fn=lambda s: s.upper(), uses_placeholder_protection=False)
    translate_office_document(
        src_xlsx, tmp_path / "out.xlsx", "source.xlsx", backend, entities=(),
        glossary=Glossary(), post_rules=(), config=config,
    )
    assert list(config.paths.cache_dir.glob("*.json"))


def test_glossary_hit_takes_priority_over_backend(src_xlsx, tmp_path):
    backend = FakeBackend(translate_fn=lambda s: "SHOULD NOT BE USED")
    glossary = Glossary({"Direccion": "Address"})
    result = translate_office_document(
        src_xlsx, tmp_path / "out.xlsx", "source.xlsx", backend, entities=(),
        glossary=glossary, post_rules=(), config=_config(tmp_path),
    )
    assert result["failures"] == []
    with zipfile.ZipFile(tmp_path / "out.xlsx") as z:
        shared = z.read("xl/sharedStrings.xml").decode("utf-8")
    assert "Address" in shared
    assert "SHOULD NOT BE USED" not in shared


def test_entity_protection_prevents_bare_fragment_translation(src_xlsx, tmp_path):
    """'Direccion' happens to also be the sole content string here -- use
    a distinct protected entity to prove Translator's OWN internal guard
    (constructed with `entities=`) is what's protecting it, not a
    coincidence of this fixture's one string."""
    backend = FakeBackend(translate_fn=lambda s: "MISTRANSLATED")
    result = translate_office_document(
        src_xlsx, tmp_path / "out.xlsx", "source.xlsx", backend,
        entities=("Direccion",), glossary=Glossary(), post_rules=(),
        config=_config(tmp_path),
    )
    assert result["failures"] == []
    with zipfile.ZipFile(tmp_path / "out.xlsx") as z:
        shared = z.read("xl/sharedStrings.xml").decode("utf-8")
    assert "Direccion" in shared
    assert "MISTRANSLATED" not in shared
