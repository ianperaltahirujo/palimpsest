from palimpsest.text.glossary import Glossary
from palimpsest.translate.cache import compute_namespace
from palimpsest.translate.translator import Translator
from tests.fixtures.fake_backend import FailingBackend, FakeBackend

FICTIONAL_ENTITIES = ["Grupo Meridian", "Grupo Aurora, SRL.", "Grupo Peñasco", "Banco Litoral"]


def _translate_upper_but_grupo_to_cluster(text: str) -> str:
    return "CLUSTER" if text.strip().upper() == "GRUPO" else text.upper()


def _make_translator(tmp_path, backend=None, entities=FICTIONAL_ENTITIES, glossary=None):
    backend = backend or FakeBackend(translate_fn=_translate_upper_but_grupo_to_cluster)
    namespace = compute_namespace(backend.name, None, "es", "en")
    translator = Translator(
        tmp_path / "cache.json", backend, namespace,
        entities=entities, glossary=glossary, verbose=False,
    )
    return translator, backend


# -- the funnel-point regression: GRUPO must never reach the backend -------

def test_bare_entity_fragment_never_reaches_the_backend(tmp_path):
    translator, backend = _make_translator(tmp_path)
    english, status = translator.translate("GRUPO")
    assert english == "GRUPO"  # passed through unchanged, not "translated"
    assert status == "ok"
    assert backend.calls == []


def test_bare_entity_fragment_case_and_punctuation_variants(tmp_path):
    translator, backend = _make_translator(tmp_path)
    for fragment in ["GRUPO", "grupo", " Grupo ", "GRUPO.", "GRUPO,"]:
        backend.calls.clear()
        translator.translate(fragment)
        assert backend.calls == [], f"{fragment!r} reached the backend"


def test_paragraph_mentioning_entity_is_still_translated(tmp_path):
    """The other half of the guard: a paragraph that MERELY MENTIONS a
    protected entity (not one that IS only the entity) must still be
    translated -- the entity itself is protected via placeholder
    substitution, not by refusing to translate the whole sentence."""
    translator, backend = _make_translator(tmp_path)
    text = "en nuestra opinion, grupo meridian presenta razonablemente"
    english, status = translator.translate(text)
    assert status == "ok"
    assert backend.calls  # the backend WAS called for this one


def test_standalone_full_entity_name_is_not_sent_to_backend(tmp_path):
    translator, backend = _make_translator(tmp_path)
    english, status = translator.translate("Grupo Aurora, SRL.")
    assert status == "ok"
    assert english == "Grupo Aurora, SRL."
    assert backend.calls == []


# -- warm() batch path: the other real historical bypass --------------------

def test_warm_never_sends_bare_fragment_to_batch_call(tmp_path):
    translator, backend = _make_translator(tmp_path)
    translator.warm(["GRUPO", "un texto normal de prueba"])
    for call in backend.batch_calls:
        assert "GRUPO" not in [c.strip().upper() for c in call]


def test_warm_translates_and_caches_normal_strings(tmp_path):
    translator, backend = _make_translator(tmp_path)
    translator.warm(["hola mundo"])
    assert translator.cache.get_ok("hola mundo") is not None


# -- glossary / cache / entity-guard short-circuit ordering -----------------

def test_glossary_hit_short_circuits_before_backend_call(tmp_path):
    glossary = Glossary(terms={"Fideicomiso": "Trust"})
    translator, backend = _make_translator(tmp_path, glossary=glossary)
    english, status = translator.translate("Fideicomiso")
    assert english == "Trust"
    assert status == "ok"
    assert backend.calls == []
    assert translator.stats["glossary"] == 1


def test_cache_hit_short_circuits_before_backend_call(tmp_path):
    translator, backend = _make_translator(tmp_path)
    translator.cache.put("ya traducido antes", "already translated before", "ok")
    english, status = translator.translate("ya traducido antes")
    assert english == "already translated before"
    assert backend.calls == []
    assert translator.stats["cache"] == 1


# -- honest status propagation -----------------------------------------------

def test_failed_backend_call_is_recorded_as_failed_not_ok(tmp_path):
    translator, _backend = _make_translator(tmp_path, backend=FailingBackend())
    english, status = translator.translate("un texto cualquiera")
    assert english is None
    assert status == "failed"
    assert translator.cache.get_ok("un texto cualquiera") is None


def test_failed_translation_is_pending_for_retry(tmp_path):
    translator, _backend = _make_translator(tmp_path, backend=FailingBackend())
    translator.translate("un texto cualquiera")
    assert "un texto cualquiera" in translator.cache.pending()


def test_identical_output_with_source_language_markers_flagged_identical(tmp_path):
    """A backend that fails silently by echoing the input back is caught:
    if the 'translation' still contains source-language function words,
    it isn't a translation."""
    identity_backend = FakeBackend(translate_fn=lambda s: s)
    translator, _backend = _make_translator(tmp_path, backend=identity_backend)
    text = "que la sociedad presente el contrato"
    english, status = translator.translate(text)
    assert status == "identical"
    assert english is None


def test_identical_output_without_source_markers_is_ok(tmp_path):
    """A bare company name or code translating to itself is legitimate
    and must not be flagged as a failure forever."""
    identity_backend = FakeBackend(translate_fn=lambda s: s)
    translator, _backend = _make_translator(
        tmp_path, backend=identity_backend, entities=[]
    )
    english, status = translator.translate("COCO-4471")
    assert status == "ok"
    assert english == "COCO-4471"


def test_retry_pending_recovers_after_backend_starts_succeeding(tmp_path):
    translator, _backend = _make_translator(tmp_path, backend=FailingBackend())
    translator.translate("un texto cualquiera")
    assert translator.cache.pending()

    # Swap in a working backend, as if the transient failure had cleared.
    translator.backend = FakeBackend()
    recovered, total = translator.retry_pending()
    assert total == 1
    assert recovered == 1
    assert translator.cache.get_ok("un texto cualquiera") is not None


# -- placeholder protection: numbers/currency survive verbatim -------------

def test_entities_and_amounts_survive_translation_verbatim(tmp_path):
    translator, _backend = _make_translator(tmp_path)
    text = "Grupo Meridian pago RD$50,000 el 3 de enero"
    english, status = translator.translate(text)
    assert status == "ok"
    assert "Grupo Meridian" in english
    assert "RD$50,000" in english


def test_placeholder_retry_unprotected_when_a_reference_is_left_unresolved(tmp_path):
    """If a backend's output contains a placeholder reference restore()
    can't resolve (simulating a backend that garbles or hallucinates a
    reference -- out of range for the real token list), Translator
    retries unprotected rather than shipping text with a literal
    '[[99]]' still in it. The fake only misbehaves when it SEES a
    placeholder in its input, so the unprotected retry (plain text, no
    '[[' markers) translates cleanly -- isolating the one thing being
    tested from the fake's own behavior."""

    def confuse_on_placeholders(text: str) -> str:
        if "[[" in text:
            return text.upper() + " [[99]]"  # a reference no real token has
        return text.upper()

    backend = FakeBackend(translate_fn=confuse_on_placeholders)
    translator, _ = _make_translator(tmp_path, backend=backend)
    text = "Grupo Meridian pago RD$50,000"
    english, status = translator.translate(text)
    assert status == "ok"
    assert "[[" not in english
    # The second (retry) call was the plain, unprotected text.
    assert backend.calls.count(text) == 1
    assert len(backend.calls) == 2
