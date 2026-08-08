import { useCallback, useRef, useState } from "react";

// Port of the pass-2 prototype's EDIT Map + undo stack, as a React hook.
// One entry per paragraph, created lazily (kept until first touched).
// key -> {key, op, rect:{x0,y0,x1,y1}, origin:[x,y], align, size, leading,
//         font, baseStyle, runs:[{text,bold,italic,underline,highlight,color}]}
export function useEditBoxes(pageIr) {
  const [boxes, setBoxes] = useState(() => new Map());
  const undoStack = useRef([]);
  const [undoCount, setUndoCount] = useState(0);

  function paraKey(i) {
    return "0:" + i; // page:index -- becomes ir.Paragraph.id once that field exists (deferred Part C)
  }

  const initialBoxState = useCallback((p, i) => {
    const first = p.runs[0];
    return {
      key: paraKey(i),
      op: "kept",
      rect: { ...p.rect },
      origin: p.origin.slice(),
      align: p.align,
      size: p.size,
      leading: p.leading,
      font: p.font,
      // The style new/select-all-and-type edits fall back to -- see
      // edit/runs.js wordSnap() and docToRuns(). Taken from the
      // paragraph's first run since single-run paragraphs (the common
      // case) are uniform by definition.
      baseStyle: { bold: first.bold, italic: first.italic, underline: false, highlight: null, color: first.color.slice() },
      runs: p.runs.map((r) => ({
        text: r.text,
        bold: r.bold,
        italic: r.italic,
        underline: false,
        highlight: null,
        color: r.color.slice(),
      })),
    };
  }, []);

  const getBox = useCallback(
    (key) => {
      const existing = boxes.get(key);
      if (existing) return existing;
      const i = Number(key.split(":")[1]);
      return initialBoxState(pageIr.paragraphs[i], i);
    },
    [boxes, pageIr, initialBoxState],
  );

  const cloneBox = (b) => ({
    ...b,
    rect: { ...b.rect },
    origin: b.origin.slice(),
    runs: b.runs.map((r) => ({ ...r, color: r.color.slice(), highlight: r.highlight ? r.highlight.slice() : null })),
  });

  const pushUndo = useCallback(
    (key) => {
      undoStack.current.push({ key, before: cloneBox(getBox(key)) });
      if (undoStack.current.length > 100) undoStack.current.shift();
      setUndoCount(undoStack.current.length);
    },
    [getBox],
  );

  const setBox = useCallback((key, updater) => {
    setBoxes((prev) => {
      const next = new Map(prev);
      const cur = next.get(key) ?? getBox(key);
      const updated = typeof updater === "function" ? updater(cur) : { ...cur, ...updater };
      next.set(key, updated);
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const markModified = useCallback((key) => {
    setBox(key, (box) => (box.op === "kept" ? { ...box, op: "modified" } : box));
  }, [setBox]);

  // draw_paragraph anchors the first baseline at origin[1] absolutely --
  // move it WITH the rect, or the redrawn text sits at the old baseline
  // and available_rect's max_height math goes wrong.
  const translateBox = useCallback(
    (key, startRect, startOrigin, dxPt, dyPt) => {
      setBox(key, (box) => ({
        ...box,
        op: box.op === "kept" ? "modified" : box.op,
        rect: { x0: startRect.x0 + dxPt, x1: startRect.x1 + dxPt, y0: startRect.y0 + dyPt, y1: startRect.y1 + dyPt },
        origin: [startOrigin[0] + dxPt, startOrigin[1] + dyPt],
      }));
    },
    [setBox],
  );

  const resizeBoxWidth = useCallback(
    (key, startRect, dxPt) => {
      const newX1 = Math.max(startRect.x0 + 20, startRect.x1 + dxPt);
      setBox(key, (box) => ({ ...box, op: box.op === "kept" ? "modified" : box.op, rect: { ...startRect, x1: newX1 } }));
    },
    [setBox],
  );

  const toggleDelete = useCallback(
    (key, deleted) => {
      pushUndo(key);
      // Restoring doesn't try to detect whether the box is now byte-
      // identical to its original state -- it's still "modified" (the
      // user took an explicit delete-then-restore action, worth keeping
      // in the diff) rather than silently reverting to "kept".
      setBox(key, (box) => ({ ...box, op: deleted ? "deleted" : "modified" }));
    },
    [pushUndo, setBox],
  );

  const setRuns = useCallback(
    (key, runs) => {
      setBox(key, (box) => ({ ...box, op: box.op === "kept" ? "modified" : box.op, runs }));
    },
    [setBox],
  );

  // Text edits (typing, and now alignment set via the in-editor Align
  // controls) are deliberately NOT pushed onto the undo stack, same as
  // setRuns above -- only structural ops (move/resize/delete) are. Reads
  // both back from the live TipTap editor in one commit so a paragraph's
  // alignment change lands with its text, not as a second history step.
  const setRunsAndAlign = useCallback(
    (key, runs, align) => {
      setBox(key, (box) => ({ ...box, op: box.op === "kept" ? "modified" : box.op, runs, align }));
    },
    [setBox],
  );

  const setAlign = useCallback(
    (key, align) => {
      pushUndo(key);
      setBox(key, (box) => ({ ...box, op: box.op === "kept" ? "modified" : box.op, align }));
    },
    [pushUndo, setBox],
  );

  const applyFormatToBox = useCallback(
    (key, fmt, value) => {
      pushUndo(key);
      setBox(key, (box) => ({
        ...box,
        op: box.op === "kept" ? "modified" : box.op,
        runs: box.runs.map((r) => {
          if (fmt === "bold") return { ...r, bold: !r.bold };
          if (fmt === "italic") return { ...r, italic: !r.italic };
          if (fmt === "underline") return { ...r, underline: !r.underline };
          if (fmt === "highlight") return { ...r, highlight: r.highlight ? null : value };
          if (fmt === "color") return { ...r, color: value.slice() };
          return r;
        }),
      }));
    },
    [pushUndo, setBox],
  );

  const undo = useCallback(() => {
    const entry = undoStack.current.pop();
    if (!entry) return null;
    setUndoCount(undoStack.current.length);
    setBoxes((prev) => {
      const next = new Map(prev);
      next.set(entry.key, entry.before);
      return next;
    });
    return entry.key;
  }, []);

  const discardAll = useCallback(() => {
    undoStack.current = [];
    setUndoCount(0);
    setBoxes(new Map());
  }, []);

  const unsavedCount = [...boxes.values()].filter((b) => b.op !== "kept").length;

  const exportPayload = useCallback(
    (source) => {
      const paragraphs = pageIr.paragraphs.map((p, i) => {
        const key = paraKey(i);
        const box = boxes.get(key);
        if (!box) return { ...p, id: key, edit: "kept" };
        return {
          text: box.runs.map((r) => r.text).join(""),
          runs: box.runs,
          rect: box.rect,
          origin: box.origin,
          align: box.align,
          leading: box.leading,
          size: box.size,
          font: box.font,
          color: p.color,
          indent: p.indent,
          hang_x0: p.hang_x0,
          starts_item: p.starts_item,
          clip: p.clip,
          id: key,
          edit: box.op,
        };
      });
      return {
        schema: 1,
        job: "prototype-sample",
        document: { source, pages: [{ number: 0, width: pageIr.width, height: pageIr.height, paragraphs }] },
      };
    },
    [pageIr, boxes],
  );

  return {
    boxes,
    getBox,
    paraKey,
    pushUndo,
    markModified,
    translateBox,
    resizeBoxWidth,
    toggleDelete,
    setRuns,
    setRunsAndAlign,
    setAlign,
    applyFormatToBox,
    undo,
    undoCount,
    discardAll,
    unsavedCount,
    exportPayload,
  };
}
