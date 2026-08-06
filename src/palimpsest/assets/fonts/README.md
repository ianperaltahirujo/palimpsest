# Bundled fallback fonts (not yet populated)

`pdf.fontmap.FontResolver` resolves fonts in three tiers: the system font
index, a same-class substitute in the system index (e.g. "arial" for an
unmatched sans family), and finally a same-class substitute in *this*
directory before giving up and falling back to a PDF base-14 face.

This directory is currently empty. On a machine with no relevant system
fonts installed (a minimal Linux container, for instance), font
resolution still works correctly -- it just falls all the way through to
base-14 (Helvetica/Times), which is exactly what happened before this
project existed and is not a regression.

The plan is to vendor a small set of OFL-licensed faces here (e.g. DejaVu
or Noto: Sans/Serif/Mono, four weights each) as the "sans fallback" /
"serif fallback" / "monospace fallback" families `FontResolver` already
knows to look for (see `_BUNDLED_FALLBACK` in `pdf/fontmap.py`). That's
deferred rather than done here because it requires sourcing real font
binaries from a verified, appropriately-licensed release -- not something
to guess a download URL for. Tracked as follow-up work.
