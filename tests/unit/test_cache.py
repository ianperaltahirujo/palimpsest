import json

from palimpsest.translate.cache import LEGACY_NAMESPACE, Cache, compute_namespace


def test_put_and_get_ok_round_trip(tmp_path):
    cache = Cache(tmp_path / "c.json", namespace="ns1")
    cache.put("Hola", "Hello", "ok")
    assert cache.get_ok("Hola") == "Hello"


def test_get_ok_returns_none_for_non_ok_status(tmp_path):
    cache = Cache(tmp_path / "c.json", namespace="ns1")
    cache.put("Hola", None, "failed")
    assert cache.get_ok("Hola") is None


def test_get_ok_returns_none_for_missing_key(tmp_path):
    cache = Cache(tmp_path / "c.json", namespace="ns1")
    assert cache.get_ok("nunca visto") is None


def test_pending_excludes_ok_entries(tmp_path):
    cache = Cache(tmp_path / "c.json", namespace="ns1")
    cache.put("a", "A", "ok")
    cache.put("b", None, "failed")
    cache.put("c", "c", "identical")
    pending = cache.pending()
    assert set(pending) == {"b", "c"}


def test_save_then_reload_round_trips(tmp_path):
    path = tmp_path / "c.json"
    cache = Cache(path, namespace="ns1")
    cache.put("Hola", "Hello", "ok")
    cache.save()

    reloaded = Cache(path, namespace="ns1")
    assert reloaded.get_ok("Hola") == "Hello"


def test_save_is_noop_when_not_dirty(tmp_path):
    path = tmp_path / "c.json"
    cache = Cache(path, namespace="ns1")
    cache.save()
    assert not path.exists()


def test_save_writes_namespaces_wrapper(tmp_path):
    path = tmp_path / "c.json"
    cache = Cache(path, namespace="ns1")
    cache.put("Hola", "Hello", "ok")
    cache.save()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "namespaces" in raw
    assert raw["namespaces"]["ns1"]["Hola"] == {"en": "Hello", "status": "ok"}


# -- namespace isolation: the switching-backends regression -----------------

def test_different_namespaces_do_not_see_each_others_entries(tmp_path):
    path = tmp_path / "c.json"
    google = Cache(path, namespace="google:abc123")
    google.put("Hola", "Hello (google)", "ok")
    google.save()

    anthropic = Cache(path, namespace="anthropic:def456")
    assert anthropic.get_ok("Hola") is None


def test_switching_back_to_a_prior_namespace_finds_its_cache_intact(tmp_path):
    """Switching Google -> Claude -> back to Google must not have lost or
    corrupted the Google cache in between."""
    path = tmp_path / "c.json"
    google1 = Cache(path, namespace="google:abc123")
    google1.put("Hola", "Hello (google)", "ok")
    google1.save()

    anthropic = Cache(path, namespace="anthropic:def456")
    anthropic.put("Hola", "Hello (anthropic)", "ok")
    anthropic.save()

    google2 = Cache(path, namespace="google:abc123")
    assert google2.get_ok("Hola") == "Hello (google)"


def test_both_namespaces_persist_after_two_saves(tmp_path):
    path = tmp_path / "c.json"
    a = Cache(path, namespace="ns-a")
    a.put("x", "A", "ok")
    a.save()

    b = Cache(path, namespace="ns-b")
    b.put("y", "B", "ok")
    b.save()

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw["namespaces"]) == {"ns-a", "ns-b"}
    assert raw["namespaces"]["ns-a"]["x"]["en"] == "A"
    assert raw["namespaces"]["ns-b"]["y"]["en"] == "B"


# -- legacy flat-cache migration --------------------------------------------

def test_legacy_flat_string_cache_migrates_into_legacy_namespace(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"Hola": "Hello"}), encoding="utf-8")
    cache = Cache(path, namespace=LEGACY_NAMESPACE)
    assert cache.get_ok("Hola") == "Hello"


def test_legacy_entry_equal_to_key_is_reclassified_identical_not_ok(tmp_path):
    """The exact failure this reclassification exists to catch: a naive
    error handler that appended the untranslated source as though it
    were the translation. A legacy flat entry equal to its own key must
    not be trusted as a successful translation."""
    path = tmp_path / "legacy.json"
    key = "GRUPO MERIDIAN, S.A.S."
    path.write_text(json.dumps({key: key}), encoding="utf-8")
    cache = Cache(path, namespace=LEGACY_NAMESPACE)
    assert cache.get_ok(key) is None  # not "ok"
    assert cache.data[key]["status"] == "identical"


def test_legacy_status_dict_cache_without_namespaces_wrapper_migrates(tmp_path):
    path = tmp_path / "legacy_status.json"
    path.write_text(
        json.dumps({"Hola": {"en": "Hello", "status": "ok"}}), encoding="utf-8"
    )
    cache = Cache(path, namespace=LEGACY_NAMESPACE)
    assert cache.get_ok("Hola") == "Hello"


def test_missing_file_is_empty_cache_not_an_error(tmp_path):
    cache = Cache(tmp_path / "does_not_exist.json", namespace="ns1")
    assert cache.get_ok("anything") is None
    assert cache.pending() == {}


def test_corrupt_json_file_is_treated_as_empty(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("{not valid json", encoding="utf-8")
    cache = Cache(path, namespace="ns1")
    assert cache.get_ok("anything") is None


# -- compute_namespace --------------------------------------------------

def test_compute_namespace_deterministic():
    ns1 = compute_namespace("google", None, "es", "en")
    ns2 = compute_namespace("google", None, "es", "en")
    assert ns1 == ns2


def test_compute_namespace_differs_by_backend():
    ns_google = compute_namespace("google", None, "es", "en")
    ns_anthropic = compute_namespace("anthropic", "claude-opus-5", "es", "en")
    assert ns_google != ns_anthropic
    assert ns_google.startswith("google:")
    assert ns_anthropic.startswith("anthropic:")


def test_compute_namespace_differs_by_model():
    ns_opus = compute_namespace("anthropic", "claude-opus-5", "es", "en")
    ns_sonnet = compute_namespace("anthropic", "claude-sonnet-5", "es", "en")
    assert ns_opus != ns_sonnet


def test_compute_namespace_differs_by_glossary_content():
    ns_a = compute_namespace("google", None, "es", "en", glossary_terms={"Fideicomiso": "Trust"})
    ns_b = compute_namespace("google", None, "es", "en", glossary_terms={"Fideicomiso": "Estate"})
    assert ns_a != ns_b


def test_compute_namespace_differs_by_entities():
    ns_a = compute_namespace("google", None, "es", "en", entities=["Grupo Meridian"])
    ns_b = compute_namespace("google", None, "es", "en", entities=["Grupo Aurora"])
    assert ns_a != ns_b


def test_compute_namespace_stable_regardless_of_entity_ordering():
    ns_a = compute_namespace(
        "google", None, "es", "en", entities=["Grupo Meridian", "Banco Litoral"]
    )
    ns_b = compute_namespace(
        "google", None, "es", "en", entities=["Banco Litoral", "Grupo Meridian"]
    )
    assert ns_a == ns_b
