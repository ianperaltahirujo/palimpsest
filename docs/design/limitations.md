# Known limitations

An honest account of what this pipeline does not handle, drawn from a real
corpus run rather than written speculatively. None of these are silent --
each either degrades visibly (original Spanish left in place) or is
recorded in the run report.

## Text rotation is not reproduced

A source page with rotated column headers (seen in a real estate
comparables table) renders its translated headers horizontally rather
than at the source's rotation angle. Numeric data in the same table is
unaffected -- protected as digits, not re-laid-out.

## Inline emphasis mid-sentence is not preserved

A short bold lead-in label followed by regular body text (`CONSIDERANDO:`,
`Asunto:`) keeps its own styling, because `pdf.pipeline.translate_paragraph`
translates the label and the body as two separate units specifically to
preserve this pattern. Emphasis on a phrase *inside* a sentence -- an
italicised word mid-paragraph, say -- is not preserved: the whole sentence
is translated as one unit and drawn in its dominant style. Translating
arbitrary sub-sentence fragments separately was tried conceptually and
rejected -- it damages translation quality more than the emphasis loss is
worth, and risks reintroducing the isolated-fragment failure class
documented in [`protected-entities.md`](protected-entities.md).

## Bold-weight detection on scans is ~95% accurate

See [`bold-calibration.md`](bold-calibration.md) for the full fitting methodology and the
recall/false-positive tradeoff table. This is a measurement against pixels,
not a certainty.

## Very small text on scans is left in Spanish

Below `[thresholds].min_text_size_scan` (default 7pt), OCR confidence
degrades enough that a mistranslation is judged worse than leaving the
line untranslated. In practice this is almost always footer boilerplate
or a small-print address line, not body content.

## OCR occasionally reads noise out of decorative logos and brand graphics

A handful of instances (roughly a dozen across a real 40-document corpus)
where OCR extracted a short garbled fragment from a stylised logo or brand
graphic -- not real text at all -- and machine translation was then run on
that garbage. Confirmed narrow in scope: always on logo/stamp graphics,
never in body prose, and mostly harmless in practice (MT usually returns
nonsense input unchanged rather than confidently mistranslating it).
Deliberately not fixed: a real fix means detecting and excluding
logo/decorative-graphic regions from OCR entirely, which is a different
scope of engineering work than the fixes documented in
[`v1-postmortem.md`](v1-postmortem.md) and
[`protected-entities.md`](protected-entities.md). Accepted as a known,
narrow-impact gap rather than pursued.

## A stamp or seal overlapping real text defeats OCR region separation

Seen on one real financial-statement notes page, where an auditor's rubber
stamp physically overlapped the last line of a note. OCR has no concept of
"this pixel region is a non-text stamp, not a text line," so the two get
read as one garbled blob. Same underlying cause as the logo-noise
limitation above, and the same decision: not fixed, for the same
scope-of-work reason.

## The Spanish Tesseract model is the "fast" variant

The `spa` traineddata used is the compact `fast` variant (a few MB). The
`best` variant (an order of magnitude larger) would likely improve
recognition on degraded scans; it is not installed by default. Point
`[ocr].tessdata_prefix` at your own `best`-variant install if OCR quality
on poor scans matters more than setup size to you.
