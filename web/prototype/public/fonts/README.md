# Bundled fonts

Three OFL-licensed families, subset to Latin-1 (covers the English UI copy
and the Spanish sample text) so this prototype renders with no network
access and no CDN dependency.

| Family | Role | Source | License |
|---|---|---|---|
| Archivo (variable, `wght`+`wdth` axes) | Display | [google/fonts, ofl/archivo](https://github.com/google/fonts/tree/main/ofl/archivo) | `OFL-Archivo.txt` |
| IBM Plex Sans | Body | [google/fonts, ofl/ibmplexsans](https://github.com/google/fonts/tree/main/ofl/ibmplexsans) | `OFL-IBMPlexSans.txt` |
| IBM Plex Mono | Data | [google/fonts, ofl/ibmplexmono](https://github.com/google/fonts/tree/main/ofl/ibmplexmono) | `OFL-IBMPlexMono.txt` |

Archivo is used as "Archivo Expanded" via `font-stretch` / `font-variation-settings`
on the variable file, not a separately-registered static family — Google
Fonts doesn't publish a static "Archivo Expanded" family, and instantiating
a static width from the variable source keeps one file covering every
weight/width combination the design uses instead of several.

Regenerating: each Plex weight was pulled from the `fonts.googleapis.com/css2`
endpoint (Latin subset only); Archivo was pulled as the full variable `.ttf`
from the google/fonts repo above, then subset to Latin-1 and compressed to
woff2 with `fonttools`:

```
python -m fontTools.subset Archivo-Variable.ttf \
  --output-file=archivo-expanded.woff2 --flavor=woff2 \
  --unicodes="U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215" \
  --layout-features='*' --name-IDs='*'
```
