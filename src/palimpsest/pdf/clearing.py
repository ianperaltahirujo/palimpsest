"""Remove the original source-language text from a page WITHOUT damaging
anything else.

The defect this exists to prevent
-----------------------------------
Calling `page.apply_redactions()` with no arguments uses PyMuPDF's
defaults:

    apply_redactions(images=2, graphics=1, text=0)
      images=2   -> PDF_REDACT_IMAGE_PIXELS: blanks the pixels of any
                    image underneath a redaction rectangle
      graphics=1 -> PDF_REDACT_LINE_ART_REMOVE_IF_COVERED: deletes vector
                    line art covered by a rectangle

On a scanned document the entire page IS one image, so `images=2` punches
holes through the scan wherever an OCR box happens to overlap artwork --
a letterhead's decorative rule, a seal, a border. `graphics=1` deletes
vector borders and rules the same way. On top of that, a redaction
rectangle is by default filled with hard white `(1, 1, 1)`, which reads
as a visibly bright patch against off-white scanned paper.

Both paths here pass `images=PDF_REDACT_IMAGE_NONE` and
`graphics=PDF_REDACT_LINE_ART_NONE`, so redaction only ever removes text.

Digital pages
    Removing the text operators is enough: whatever was behind the text
    -- white paper, a highlight box, a logo -- is untouched and simply
    shows through. No fill is drawn at all.

Scanned pages
    The source-language text is baked into the raster, so the raster
    itself must be edited. Each text region is filled with a colour
    sampled from that same region (a high percentile per channel, which
    is the paper behind the glyphs) rather than white, so highlight boxes
    and toned paper stay the right colour. Optional matched noise keeps
    the patch from looking suspiciously flat against a noisy scan.
"""

from __future__ import annotations

import io

import fitz
import numpy as np
from PIL import Image

SAFE = dict(
    images=fitz.PDF_REDACT_IMAGE_NONE,
    graphics=fitz.PDF_REDACT_LINE_ART_NONE,
    text=fitz.PDF_REDACT_TEXT_REMOVE,
)


def clear_text_digital(page: fitz.Page, rects) -> int:
    """Delete text inside `rects`, leaving images and vector art intact."""
    if not rects:
        return 0
    for r in rects:
        # fill=False -> no covering rectangle is painted; the page's own
        # background (highlight box, logo, photo) remains visible.
        page.add_redact_annot(fitz.Rect(r), fill=False)
    page.apply_redactions(**SAFE)
    return len(rects)


def strip_text_layer(page: fitz.Page, rects) -> int:
    """Remove an invisible OCR text layer so the output does not still
    carry selectable source-language text underneath the rendered
    translation."""
    return clear_text_digital(page, rects)


# ---------------------------------------------------------------------------
# Raster inpainting for scanned pages
# ---------------------------------------------------------------------------


def _page_images(page: fitz.Page) -> list[tuple[int, fitz.Rect, float]]:
    """Images on the page, largest coverage first, with their placement rects."""
    out = []
    for item in page.get_images(full=True):
        xref = item[0]
        try:
            bbox = page.get_image_bbox(item)
        except Exception:
            continue
        if bbox.is_empty or bbox.is_infinite:
            continue
        out.append((xref, bbox, abs(bbox.get_area())))
    out.sort(key=lambda t: -t[2])
    return out


def _sample_fill(
    arr: np.ndarray, x0: int, y0: int, x1: int, y1: int, percentile: int = 82
) -> tuple[np.ndarray | None, float]:
    """Background colour for a text region: a high percentile of each channel.

    Glyph coverage inside a line of text is roughly 15-25% of the area,
    so the upper percentiles are paper, not ink. Sampling from the region
    itself (not a surrounding ring) means a highlighted line yields the
    highlight colour and a line over toned paper yields that tone.
    """
    patch = arr[y0:y1, x0:x1]
    if patch.size == 0:
        return None, 0.0
    flat = patch.reshape(-1, patch.shape[-1])
    fill = np.percentile(flat, percentile, axis=0)
    # Noise level of the paper only (pixels at or above the fill level).
    lum = flat.mean(axis=1)
    thresh = np.percentile(lum, percentile * 0.75)
    paper = flat[lum >= thresh]
    sigma = float(paper.std()) if paper.size else 0.0
    return fill, min(sigma, 6.0)


def inpaint_scanned(
    page: fitz.Page, rects, pad: float = 0.6, add_noise: bool = True, percentile: int = 82
) -> int:
    """Erase text regions from the page's underlying scan.

    Only the dominant page image is touched. Rectangles are mapped from
    PDF space into image pixel space through that image's placement box.
    Returns the number of regions filled.
    """
    if not rects:
        return 0
    images = _page_images(page)
    if not images:
        return 0
    xref, bbox, _ = images[0]
    # Only treat this as "the scan" if it actually covers most of the page.
    if abs(bbox.get_area()) < 0.55 * abs(page.rect.get_area()):
        return 0

    doc = page.parent
    try:
        info = doc.extract_image(xref)
    except Exception:
        return 0
    if not info or not info.get("image"):
        return 0
    try:
        img = Image.open(io.BytesIO(info["image"]))
        img.load()
    except Exception:
        return 0
    mode = img.mode
    if mode not in ("RGB", "L"):
        img = img.convert("RGB")
        mode = "RGB"
    arr = np.array(img)
    if arr.ndim == 2:
        arr = arr[:, :, None]
    h_img, w_img = arr.shape[0], arr.shape[1]

    sx = w_img / bbox.width if bbox.width else 0
    sy = h_img / bbox.height if bbox.height else 0
    if not sx or not sy:
        return 0

    rng = np.random.default_rng(12345)
    filled = 0
    for r in rects:
        r = fitz.Rect(r)
        r = fitz.Rect(r.x0 - pad, r.y0 - pad, r.x1 + pad, r.y1 + pad)
        x0 = int(round((r.x0 - bbox.x0) * sx))
        x1 = int(round((r.x1 - bbox.x0) * sx))
        y0 = int(round((r.y0 - bbox.y0) * sy))
        y1 = int(round((r.y1 - bbox.y0) * sy))
        x0, x1 = max(0, min(x0, w_img)), max(0, min(x1, w_img))
        y0, y1 = max(0, min(y0, h_img)), max(0, min(y1, h_img))
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue
        fill, sigma = _sample_fill(arr, x0, y0, x1, y1, percentile)
        if fill is None:
            continue
        h, w = y1 - y0, x1 - x0
        block = np.broadcast_to(fill, (h, w, arr.shape[2])).astype(np.float32)
        if add_noise and sigma > 0.5:
            block = block + rng.normal(0.0, sigma * 0.55, block.shape)
        arr[y0:y1, x0:x1] = np.clip(block, 0, 255).astype(arr.dtype)
        filled += 1

    if not filled:
        return 0
    out = arr[:, :, 0] if arr.shape[2] == 1 else arr
    pil = Image.fromarray(out.astype(np.uint8), "L" if arr.shape[2] == 1 else "RGB")

    # Re-encode in the format the scan already used. Saving a JPEG scan as
    # PNG is lossless but can be dramatically larger -- a letter-sized
    # 659 KB JPEG scan became 19 MB as PNG in the corpus this was built
    # against. JPEG artefacts are not a concern here: the translated text
    # is drawn as vector text on top of this image, never baked into it,
    # and the regions altered are flat fill.
    src_ext = (info.get("ext") or "").lower()
    buf = io.BytesIO()
    if src_ext in ("jpeg", "jpg"):
        pil.save(buf, format="JPEG", quality=88, optimize=True, subsampling=0)
    else:
        pil.save(buf, format="PNG", optimize=True)
    data = buf.getvalue()

    # Never let the rewrite balloon the file; fall back to JPEG if PNG is huge.
    original_len = len(info.get("image") or b"")
    if src_ext not in ("jpeg", "jpg") and original_len and len(data) > original_len * 3:
        buf = io.BytesIO()
        pil.convert("RGB").save(buf, format="JPEG", quality=88, optimize=True, subsampling=0)
        data = buf.getvalue()

    try:
        page.replace_image(xref, stream=data)
    except Exception:
        return 0
    return filled
