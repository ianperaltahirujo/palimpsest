"""Rebuilds, as a maintained test, the corpus-wide cache scan a real
prior version of this pipeline ran ad hoc after finding the GRUPO ->
CLUSTER failure class -- the script itself no longer exists; this pins
the invariant it verified (see qa/audit.py's module docstring)."""

import json

from palimpsest.qa.audit import poisoned_fragment_entries

ENTITIES = ["Grupo Meridian", "Grupo Aurora, SRL.", "Banco Litoral"]


def _write_cache(path, namespace: str, entries: dict):
    path.write_text(json.dumps({"namespaces": {namespace: entries}}), encoding="utf-8")


def test_empty_cache_dir_has_no_hits(tmp_path):
    assert poisoned_fragment_entries(tmp_path, ENTITIES) == []


def test_clean_cache_with_no_fragments_has_no_hits(tmp_path):
    _write_cache(
        tmp_path / "doc1.json", "google:abc",
        {"un texto normal": {"en": "a normal text", "status": "ok"}},
    )
    assert poisoned_fragment_entries(tmp_path, ENTITIES) == []


def test_detects_bare_grupo_mistranslated_as_cluster(tmp_path):
    _write_cache(
        tmp_path / "doc1.json", "google:abc",
        {"GRUPO": {"en": "CLUSTER", "status": "ok"}},
    )
    hits = poisoned_fragment_entries(tmp_path, ENTITIES)
    assert len(hits) == 1
    assert hits[0].source == "GRUPO"
    assert hits[0].cached_value == "CLUSTER"


def test_does_not_flag_fragment_that_translated_to_itself(tmp_path):
    """A fragment guard should have kept this out of MT entirely, but if
    it somehow reached the cache unchanged, that's not the poisoning
    failure mode -- only a CHANGED value is evidence of mistranslation."""
    _write_cache(
        tmp_path / "doc1.json", "google:abc",
        {"GRUPO": {"en": "GRUPO", "status": "identical"}},
    )
    assert poisoned_fragment_entries(tmp_path, ENTITIES) == []


def test_does_not_flag_a_standalone_single_word_entity(tmp_path):
    """A single-word entity (e.g. a company known by one name) is already
    fully protected by the substring regex at translation time -- it is
    never added to the fragment set (see text.protect.
    protected_word_fragments), so audit must not flag it even if its
    cached value happens to differ from the key for an unrelated reason.
    'Excelsior' deliberately shares no word with any multi-word entity in
    ENTITIES, so it can't end up in the fragment set via some OTHER
    entity's constituent words either."""
    entities_with_single_word = [*ENTITIES, "Excelsior"]
    _write_cache(
        tmp_path / "doc1.json", "google:abc",
        {"Excelsior": {"en": "Something else entirely", "status": "ok"}},
    )
    assert poisoned_fragment_entries(tmp_path, entities_with_single_word) == []


def test_detects_across_multiple_files(tmp_path):
    _write_cache(tmp_path / "doc1.json", "google:abc", {"clean": {"en": "clean", "status": "ok"}})
    _write_cache(
        tmp_path / "doc2.json", "google:abc", {"LITORAL": {"en": "COASTAL", "status": "ok"}}
    )
    hits = poisoned_fragment_entries(tmp_path, ENTITIES)
    assert len(hits) == 1
    assert hits[0].cache_file.name == "doc2.json"


def test_detects_across_multiple_namespaces_in_one_file(tmp_path):
    path = tmp_path / "doc1.json"
    path.write_text(
        json.dumps({
            "namespaces": {
                "google:abc": {"clean": {"en": "clean", "status": "ok"}},
                "anthropic:def": {"AURORA": {"en": "DAWN", "status": "ok"}},
            }
        }),
        encoding="utf-8",
    )
    hits = poisoned_fragment_entries(tmp_path, ENTITIES)
    assert len(hits) == 1
    assert hits[0].namespace == "anthropic:def"


def test_tolerates_legacy_flat_cache_files(tmp_path):
    """A cache file predating both the status-dict shape and namespacing
    entirely -- audit must still be able to scan it."""
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"GRUPO": "CLUSTER"}), encoding="utf-8")
    hits = poisoned_fragment_entries(tmp_path, ENTITIES)
    assert len(hits) == 1
    assert hits[0].source == "GRUPO"


def test_tolerates_corrupt_json_file(tmp_path):
    (tmp_path / "corrupt.json").write_text("{not valid", encoding="utf-8")
    assert poisoned_fragment_entries(tmp_path, ENTITIES) == []


def test_ignores_non_json_files(tmp_path):
    (tmp_path / "readme.txt").write_text("GRUPO -> CLUSTER", encoding="utf-8")
    assert poisoned_fragment_entries(tmp_path, ENTITIES) == []


def test_detects_accent_and_case_variants_of_fragment():
    from palimpsest.text.protect import protected_word_fragments

    fragments = protected_word_fragments(["Grupo Peñasco"])
    assert "PENASCO" in fragments  # accent-stripped, upper-cased
