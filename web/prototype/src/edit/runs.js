// Mapping between IR runs ({text,bold,italic,underline,highlight,color})
// and TipTap's document. Selection-scoped emphasis is faithful here
// because pdf/render.py resolves a font alias and colour PER WORD
// (render.py:228-245) -- see the pass-3 plan's Finding 2. The one real
// constraint that survives is WORD GRANULARITY: render._tokenise splits
// on whitespace, so a mark can't end mid-word. wordSnap() below is where
// that gets enforced.

export function rgbFloatToHex(c) {
  const [r, g, b] = c;
  const h = (v) => Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, "0");
  return `#${h(r)}${h(g)}${h(b)}`;
}

export function cssColorToFloat(css) {
  if (!css) return [0, 0, 0];
  const hex = css.match(/^#([0-9a-f]{6})$/i);
  if (hex) {
    const n = hex[1];
    return [parseInt(n.slice(0, 2), 16) / 255, parseInt(n.slice(2, 4), 16) / 255, parseInt(n.slice(4, 6), 16) / 255];
  }
  const rgb = css.match(/rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/i);
  if (rgb) return [Number(rgb[1]) / 255, Number(rgb[2]) / 255, Number(rgb[3]) / 255];
  return [0, 0, 0];
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// One IR paragraph's runs -> the HTML TipTap parses into a doc, used both
// on first mount and whenever a box is re-selected (so external moves/
// deletes made while unselected are reflected).
export function runsToHtml(runs) {
  const spans = runs.map((r) => {
    let html = escapeHtml(r.text);
    if (r.bold) html = `<strong>${html}</strong>`;
    if (r.italic) html = `<em>${html}</em>`;
    if (r.underline) html = `<u>${html}</u>`;
    if (r.highlight) html = `<mark data-color="${rgbFloatToHex(r.highlight)}" style="background-color:${rgbFloatToHex(r.highlight)}">${html}</mark>`;
    html = `<span style="color:${rgbFloatToHex(r.color)}">${html}</span>`;
    return html;
  });
  return `<p>${spans.join("")}</p>`;
}

function styleOfNode(node, fallbackColor) {
  const marks = node.marks || [];
  const bold = marks.some((m) => m.type.name === "bold");
  const italic = marks.some((m) => m.type.name === "italic");
  const underline = marks.some((m) => m.type.name === "underline");
  const highlightMark = marks.find((m) => m.type.name === "highlight");
  const textStyleMark = marks.find((m) => m.type.name === "textStyle");
  const color = textStyleMark && textStyleMark.attrs.color ? cssColorToFloat(textStyleMark.attrs.color) : fallbackColor;
  const highlight = highlightMark ? cssColorToFloat(highlightMark.attrs.color || "#FFE58A") : null;
  return { bold, italic, underline, highlight, color };
}

function sameStyle(a, b) {
  return (
    a.bold === b.bold &&
    a.italic === b.italic &&
    a.underline === b.underline &&
    (a.highlight ? a.highlight.join(",") : null) === (b.highlight ? b.highlight.join(",") : null) &&
    a.color.join(",") === b.color.join(",")
  );
}

function mergeAdjacent(fragments) {
  const out = [];
  for (const f of fragments) {
    const last = out[out.length - 1];
    if (last && sameStyle(last, f)) last.text += f.text;
    else out.push({ ...f });
  }
  return out;
}

// A mark can't end mid-word -- render._tokenise splits on whitespace, so a
// boundary between two differently-styled runs must fall on whitespace.
// When it doesn't, the run whose style differs from the paragraph's base
// style "wins" the whole word (selecting part of a word and pressing Bold
// bolds the word -- the direction users expect). If neither side is the
// base style (two special styles meet mid-word) or the comparison is
// otherwise ambiguous, the shorter fragment is folded into the longer run
// as a deterministic tie-break.
function wordSnap(fragments, baseStyle) {
  const runs = fragments.map((f) => ({ ...f }));
  for (let i = 0; i < runs.length - 1; i++) {
    const a = runs[i];
    const b = runs[i + 1];
    if (!a.text || !b.text) continue;
    if (/\s$/.test(a.text) || /^\s/.test(b.text)) continue;
    const aTail = (a.text.match(/(\S*)$/) || [""])[0];
    const bHead = (b.text.match(/^(\S*)/) || [""])[0];
    const aIsBase = sameStyle(a, baseStyle);
    const bIsBase = sameStyle(b, baseStyle);
    if (aIsBase && !bIsBase) {
      a.text = a.text.slice(0, a.text.length - aTail.length);
      b.text = aTail + b.text;
    } else if (bIsBase && !aIsBase) {
      a.text = a.text + bHead;
      b.text = b.text.slice(bHead.length);
    } else if (aTail.length <= bHead.length) {
      a.text = a.text.slice(0, a.text.length - aTail.length);
      b.text = aTail + b.text;
    } else {
      a.text = a.text + bHead;
      b.text = b.text.slice(bHead.length);
    }
  }
  return runs.filter((r) => r.text.length > 0);
}

// TipTap editor -> IR runs. Walks state.doc.descendants() (not the DOM),
// so it's immune to how the browser happens to have split text nodes.
// Order: merge same-style fragments, word-snap mid-word boundaries, merge
// again (snapping can make neighbours identical), and if editing wiped
// every run (select-all-and-type) collapse to one run carrying the box's
// base style -- matching what pipeline.dominant_style would do server-side.
export function docToRuns(editor, baseStyle) {
  const fragments = [];
  editor.state.doc.descendants((node) => {
    if (node.isText) fragments.push({ text: node.text, ...styleOfNode(node, baseStyle.color) });
  });
  let runs = mergeAdjacent(fragments);
  runs = wordSnap(runs, baseStyle);
  runs = mergeAdjacent(runs);
  if (runs.length === 0) {
    const text = editor.getText();
    return [{ text, ...baseStyle }];
  }
  return runs;
}
