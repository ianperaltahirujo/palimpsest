# Protected entities: the GRUPO → CLUSTER failure class

This is the best-documented bug in this project's history, because it was
found *after* a full corpus run had already shipped, not during a pilot,
and because tracing it required following actual call stacks rather than
inspecting code for an obviously-missing check.

## What was found

A company name, `GRUPO MERIDIAN, SRL.`, came back translated as `CLUSTER
MERIDIAN, SRL.` -- "grupo" (group) had been machine-translated as if it
were an ordinary Spanish noun rather than the fixed first word of a proper
name. The same pattern turned up in nine-plus documents once the corpus
was scanned for it, and it wasn't limited to company names: real people's
given names were corrupted the same way whenever the surrounding context
let a name-fragment reach the translator alone (`Andrés` → `Andrew`,
`Alberto` → `Albert`).

Two independent root causes produced this, and a guard against it was
bypassed at three separate call sites before being fixed architecturally.

## Root cause A -- OCR per-word size jitter

An OCR text layer reports its own bbox-derived font size per *word*, not
per line. On one real scanned heading, three words of the same physical
line came back at three slightly different sizes:

    GRUPO     10.80pt
    MERIDIAN, 10.89pt
    SRL.      11.19pt

Rounded to one decimal place, these land in different style buckets, so
the paragraph extractor's run-building step fragmented the heading into
three separate styled runs instead of one. That fragmentation then
satisfied a downstream heuristic in the paragraph translator: a
differently-styled *leading* run reads as a label (the same shape as a
genuine label like `CONSIDERANDO:`), so the run-splitting logic sent
`GRUPO` to the translation backend in total isolation from `MERIDIAN,
SRL.` -- with no surrounding context, "grupo" translated exactly the way
a bare Spanish noun would.

Fixed two ways, both still in effect in this codebase:

- `pdf.layout._build_runs` tolerates size jitter within one run
  (`_SIZE_JITTER_TOL`, default 0.75pt) -- see
  `tests/fixtures/synth.py:size_jitter_heading_spans()`, built from these
  exact real numbers, for the regression fixture.
- The label-splitting heuristic in `pdf.pipeline.translate_paragraph`
  requires the candidate label to end in `:` or `.`. A bare uppercase word
  with no terminal punctuation is weak evidence for "this is a label" and
  is exactly what size-jitter fragmentation produces; no genuine label in
  the source corpus lacked punctuation.

## Root cause B -- OCR never read part of a logo at all

On a different document's letterhead, Tesseract read `GRUPO` out of a
stylised logo on five separate pages but never recognised the company's
second name in any of them -- it rendered as decorative typography, not
plain text. Full-phrase substring protection (matching a known multi-word
entity name against the extracted text) can never catch this case: the
full phrase never existed in the extracted page text to begin with, so
there is no "rest" to merge the isolated word back into.

Fixed by treating a paragraph that is nothing but ONE constituent word of
a known multi-word protected entity as protected too --
`text.protect.protected_word_fragments`. In a corpus of legal/financial
documents about specifically named companies and people, a paragraph that
is bare `GRUPO` or `PEÑASCO` alone is essentially never legitimate
freestanding prose; it is a truncated capture of a name, so the safe
default is leaving it untranslated rather than guessing at a translation
with no context. (See `text.protect.EntityGuard.is_name_fragment` and
`tests/unit/test_audit.py::test_detects_accent_and_case_variants_of_fragment`
for the accent-stripped variant matching this also needed --
`strip_accents("Grupo Peñasco")` still has to yield `"PENASCO"` as a
fragment.)

## Three bypasses of the guard -- found by tracing call stacks

Adding the fragment guard once was not enough, because it kept getting
missed at each new place text could reach the translation backend. Each
of these was found only by tracing an actual call path end to end, not by
inspecting code for an obviously-missing check -- which is worth
recording, because guessing where a text-slicing function might route
text next is exactly how the first two were missed in the first place:

1. **The label-split path itself.** The same heuristic responsible for
   root cause A called the translator directly on the isolated "rest"
   fragment, never routing it back through the top-level paragraph guard.
2. **The list-marker/ordinal-peeling path.** Peeling a leading marker off
   `"2. GRUPO"` yields the prefix `"2."` plus the bare remainder `"GRUPO"`
   -- and that remainder went straight to the translator, bypassing the
   guard the same way.
3. **The batch pre-translation ("warm") pass.** Its work list was built
   from cache/glossary membership only, with no guard consultation at all.

## The fix was architectural, not a fourth patch

Re-adding the guard at a fourth call site would just have set up a fifth.
Instead, every call path in `palimpsest.translate.translator` funnels
through one `EntityGuard` instance at the top of `Translator.translate()`
-- the very first thing checked, before the text is glossary-looked-up,
cache-looked-up, or handed to any backend. Nothing downstream
re-implements any part of that decision. `pdf.pipeline.translate_paragraph`
still applies the same guard explicitly to the label-split "rest" and
"head" fragments before calling the translator (see its own docstring),
because those fragments are decided at the pipeline layer, above
`Translator.translate()` -- but the invariant those checks protect is the
same one, single-funnel-point guard.

`test_protect.py` and `test_pdf_pipeline.py` parameterize this regression
directly: a `FakeBackend`/`_NeverBackend` that would mistranslate a bare
`GRUPO`/`MERIDIAN` fragment must never actually be *called* with one,
across every path named above.

## Verification

The original fix was verified with a corpus-wide scan -- every cache entry
whose key is a bare constituent word of a protected multi-word entity, and
whose cached value differs from the key -- run to **zero** hits across
five full-corpus re-runs, purging poisoned cache entries between each run
so a stale hit couldn't hide a fresh regression. That scan is now a
maintained, shippable command rather than a one-off script:
`palimpsest audit cache`, backed by `qa.audit.poisoned_fragment_entries`.
