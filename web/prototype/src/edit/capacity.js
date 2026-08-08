// JS ports of palimpsest.pdf.layout.available_rect and
// palimpsest.pdf.render.fit_paragraph, used only to drive the per-box
// "fits / will shrink / will overflow" chip in edit mode. This is a
// BROWSER ESTIMATE -- different wrap algorithm, local font substitution --
// not the server's actual decision. Label every result "estimated".

let probeEl = null;
function probe() {
  if (probeEl) return probeEl;
  probeEl = document.createElement("div");
  probeEl.style.cssText =
    "position:absolute; left:-9999px; top:0; visibility:hidden; white-space:pre-wrap; " +
    "word-break:break-word; font-family:Georgia,'Times New Roman',serif;";
  document.body.appendChild(probeEl);
  return probeEl;
}

function overlapsX(a, b) {
  return a.x0 < b.x1 && b.x0 < a.x1;
}

// Port of layout.available_rect: grows a paragraph's own rect downward,
// bounded by the page bottom margin or any paragraph below it that
// overlaps horizontally. 18 matches the library's own default
// bottom_margin.
export function availableY1(box, allBoxes, pageHeightPt) {
  let limit = pageHeightPt - 18;
  for (const other of allBoxes) {
    if (other.key === box.key || other.op === "deleted") continue;
    if (other.rect.y0 > box.rect.y0 && overlapsX(box.rect, other.rect)) {
      limit = Math.min(limit, other.rect.y0 - 1.0);
    }
  }
  return limit;
}

// Port of render.fit_paragraph's shrink loop: 0.25pt steps down to a floor
// of size*0.72 (the library's own min_scale default), stopping at the
// first size whose wrapped height fits -- or giving up and reporting
// overflow, exactly like the server does (it draws anyway).
export function fitInfo(box, availY1) {
  const maxHeight = availY1 - box.origin[1] + box.size;
  const text = box.runs.map((r) => r.text).join("");
  const floor = box.size * 0.72;
  const p = probe();
  let size = box.size;
  while (true) {
    const lead = (box.leading || box.size * 1.18) * (size / box.size);
    p.style.width = box.rect.x1 - box.rect.x0 + "pt";
    p.style.fontSize = size + "pt";
    p.style.lineHeight = lead + "pt";
    p.textContent = text;
    const lines = Math.max(1, Math.round(p.scrollHeight / ((lead * 96) / 72)));
    const height = (lines - 1) * lead + size;
    if (height <= maxHeight || size <= floor) {
      return { size, lines, overflow: height > maxHeight };
    }
    size = Math.max(floor, size - 0.25);
  }
}

export function capacityLabel(box, allBoxes, pageHeightPt, t) {
  if (box.op === "deleted") return null;
  const y1 = availableY1(box, allBoxes, pageHeightPt);
  const info = fitInfo(box, y1);
  let state, label;
  if (info.overflow) {
    state = "overflow";
    label = t("edit.capacity.overflow");
  } else if (info.size < box.size - 0.05) {
    state = "shrunk";
    label = t("edit.capacity.shrunk", { size: info.size.toFixed(1), from: box.size.toFixed(1) });
  } else {
    state = "fits";
    label = t(info.lines === 1 ? "edit.capacity.fits" : "edit.capacity.fitsPlural", { n: info.lines });
  }
  const growPt = Math.max(0, y1 - box.rect.y1);
  const boxHeightPt = Math.max(1, box.rect.y1 - box.rect.y0);
  return { state, text: label + t("edit.capacity.estimatedSuffix"), growPct: (100 * growPt) / boxHeightPt };
}
