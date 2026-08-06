# Bold-weight calibration on scanned pages

An OCR text layer (`GlyphLessFont`) carries no weight information at all --
no bold, no italic, nothing beyond position and codepoints. So on a
scanned document there is nothing in the text layer itself to say that a
paragraph is set in bold. `palimpsest.pdf.inkstyle` recovers it from the
page's own raster.

## Method

For each candidate region, pixels are thresholded into ink/paper, and for
every row of pixels the lengths of consecutive dark runs are collected.
Their median approximates the vertical stem thickness of the glyphs in
that region. Dividing by the type size gives a scale-free ratio: roughly
0.10–0.12 for regular weight, 0.17–0.19 for bold, measured at 300 DPI.

## Why an absolute threshold, not a page-relative one

A page-relative rule (flag anything thicker than this page's own median as
bold) was tried first and abandoned. It fails on exactly the case that
matters most: a document that is bold *nearly throughout*. There, the
page's median stem width is itself bold, so nothing stands out against it
-- on a real corpus letter that was in fact bold body text end to end,
a page-relative rule detected almost no bold at all.

## The fitted threshold

`BOLD_STEM_RATIO = 0.155` (the default in `pdf.inkstyle`, overridable via
`[thresholds].bold_stem_ratio`) was fitted against ground truth from 1,152
text lines drawn from four *digital* source PDFs, where the true weight is
known exactly from the embedded font names -- not guessed, not
hand-labeled.

| stem ratio (p) | bold weight, p50 / p90 / p95 | regular weight, p50 / p90 / p95 |
|---|---|---|
| measured | 0.195 / -- / -- | 0.117 / 0.144 / 0.160 |

| threshold | bold recall | falsely flagged bold |
|---|---:|---:|
| 0.130 | 100% | 16.0% |
| **0.155 (chosen)** | **95%** | **7.3%** |
| 0.160 | 89% | 4.8% |

0.155 sits at the knee of the recall/false-positive curve: pushing lower
buys back very little recall at a steep cost in false positives; pushing
higher trades meaningful recall for a smaller false-positive gain.

## This is a corpus-fitted starting point, not a universal constant

The 1,152-line sample came from four specific PDFs, at one specific
scanning DPI, through one specific OCR pipeline. Publishing 0.155 as a
silent default without this caveat would invite confusing bug reports from
a different corpus with different scan quality, contrast, or DPI. If your
documents behave differently -- systematically over- or under-flagging
bold -- refit against your own ground truth (any set of DIGITAL PDFs where
the true weight is known from the embedded font) rather than hand-tuning
by eye, and override via `[thresholds].bold_stem_ratio` in
`palimpsest.toml`. The measurement method (`pdf.inkstyle.stem_ratio`) is
directly reusable for refitting: run it against your own labeled sample
and look for the same recall/false-positive knee.
