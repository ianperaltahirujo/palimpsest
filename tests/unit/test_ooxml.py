"""ooxml.py exists to fix a specific class of data loss: a library like
openpyxl reconstructs a workbook from the subset of the format it models
and silently drops everything else -- drawings, images, person/webextension
parts, calc metadata. The fixture below is built BY HAND with zipfile, not
with openpyxl, because the entire point of these tests is proving that
parts an openpyxl round-trip would drop survive a palimpsest round-trip.
"""

import zipfile

import pytest

from palimpsest.office import ooxml

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

# Parts openpyxl is documented (in ooxml.py's own module docstring) to drop
# on a round-trip. Content is a minimal-but-valid stub -- what matters for
# this test is only that the bytes survive untouched, not that they're a
# complete real drawing/person/webextension part.
DRAWING_XML = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"/>"""

PERSON_XML = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<personList xmlns="http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments"/>"""

WEBEXTENSION_XML = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<we:webextension xmlns:we="http://schemas.microsoft.com/office/webextensions/webextension/2010/11"/>"""

EXTRA_PARTS = {
    "xl/drawings/drawing1.xml": DRAWING_XML,
    "xl/persons/person.xml": PERSON_XML,
    "xl/webextensions/webextension1.xml": WEBEXTENSION_XML,
}


def _build_xlsx(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("xl/workbook.xml", WORKBOOK_XML)
        z.writestr("xl/worksheets/sheet1.xml", SHEET1_XML)
        z.writestr("xl/sharedStrings.xml", SHARED_STRINGS_XML)
        for name, data in EXTRA_PARTS.items():
            z.writestr(name, data)


@pytest.fixture
def src_xlsx(tmp_path):
    path = tmp_path / "source.xlsx"
    _build_xlsx(path)
    return path


def test_collect_strings_finds_shared_string(src_xlsx):
    assert ooxml.collect_strings(str(src_xlsx)) == ["Direccion"]


def test_sheet_names(src_xlsx):
    assert ooxml.sheet_names(str(src_xlsx)) == ["Hoja1"]


def test_verify_no_parts_lost_or_added(src_xlsx, tmp_path):
    out = tmp_path / "out.xlsx"
    ooxml.translate_office(str(src_xlsx), str(out), lookup=lambda s: s.upper())
    report = ooxml.verify(str(src_xlsx), str(out))
    assert report["lost"] == []
    assert report["added"] == []


def test_verify_only_text_parts_changed(src_xlsx, tmp_path):
    out = tmp_path / "out.xlsx"
    # translate_sheet_names=False isolates this test to cell-content
    # translation -- lookup() would otherwise also rename the "Hoja1" tab
    # (its upper() differs from itself), which legitimately touches
    # xl/workbook.xml too and is covered separately by the rename test.
    ooxml.translate_office(
        str(src_xlsx), str(out), lookup=lambda s: s.upper(), translate_sheet_names=False
    )
    report = ooxml.verify(str(src_xlsx), str(out))
    assert set(report["changed"]) <= {"xl/sharedStrings.xml", "xl/worksheets/sheet1.xml"}


def test_non_text_parts_survive_byte_for_byte(src_xlsx, tmp_path):
    """The actual regression: a library round-trip drops xl/drawings,
    xl/persons, xl/webextensions entirely. Here they must come through
    unmodified, because ooxml.py never parses parts it doesn't recognise
    as text-bearing."""
    out = tmp_path / "out.xlsx"
    ooxml.translate_office(str(src_xlsx), str(out), lookup=lambda s: s.upper())
    with zipfile.ZipFile(src_xlsx) as a, zipfile.ZipFile(out) as b:
        names_out = set(b.namelist())
        for name, original_bytes in EXTRA_PARTS.items():
            assert name in names_out, f"{name} was dropped"
            assert b.read(name) == original_bytes == a.read(name)


def test_shared_string_is_translated(src_xlsx, tmp_path):
    out = tmp_path / "out.xlsx"
    ooxml.translate_office(str(src_xlsx), str(out), lookup=lambda s: "Address" if s == "Direccion" else None)
    assert ooxml.collect_strings(str(out)) == ["Address"]


def test_untranslated_string_is_left_unchanged(src_xlsx, tmp_path):
    out = tmp_path / "out.xlsx"
    ooxml.translate_office(str(src_xlsx), str(out), lookup=lambda s: None)
    assert ooxml.collect_strings(str(out)) == ["Direccion"]


def test_sheet_rename_retargets_bare_and_quoted_formula_refs(tmp_path):
    src = tmp_path / "with_formula.xlsx"
    sheet2 = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1"><f>Hoja1!A1+'Hoja1'!B1</f></c></row>
  </sheetData>
</worksheet>"""
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("xl/workbook.xml", WORKBOOK_XML)
        z.writestr("xl/worksheets/sheet1.xml", SHEET1_XML)
        z.writestr("xl/worksheets/sheet2.xml", sheet2)
        z.writestr("xl/sharedStrings.xml", SHARED_STRINGS_XML)

    out = tmp_path / "renamed.xlsx"
    ooxml.translate_office(str(src), str(out), lookup=lambda s: "Sheet One" if s == "Hoja1" else None)

    with zipfile.ZipFile(out) as z:
        workbook = z.read("xl/workbook.xml").decode("utf-8")
        formula_sheet = z.read("xl/worksheets/sheet2.xml").decode("utf-8")

    assert 'name="Sheet One"' in workbook
    assert "Sheet One!A1" in formula_sheet
    assert "'Sheet One'!B1" in formula_sheet
