import { useCallback, useEffect, useState } from "react";

const MIN = 0.5;
const MAX = 3.0;
const STEP = 0.25;
const DEFAULT = 1.0;

// Drives --pp-zoom on .pp-page-stack. Sizing is HEIGHT-based (see
// .pp-page-base in index.css) specifically so the stack keeps shrink-
// wrapping its intrinsic-ratio <img> at every zoom level -- the
// percentage-based overlay geometry in EditSurface.jsx registers against
// that wrapper with zero extra math, at any zoom, same as it does at 1x.
// A width/transform-based zoom would break that property.
export function useZoom(ref) {
  const [zoom, setZoom] = useState(DEFAULT);

  const zoomIn = useCallback(() => setZoom((z) => Math.min(MAX, +(z + STEP).toFixed(2))), []);
  const zoomOut = useCallback(() => setZoom((z) => Math.max(MIN, +(z - STEP).toFixed(2))), []);
  const resetZoom = useCallback(() => setZoom(DEFAULT), []);

  useEffect(() => {
    const el = ref?.current;
    if (!el) return;
    function onKeyDown(e) {
      if (!(e.ctrlKey || e.metaKey)) return;
      if (e.key === "=" || e.key === "+") {
        e.preventDefault();
        zoomIn();
      } else if (e.key === "-") {
        e.preventDefault();
        zoomOut();
      } else if (e.key === "0") {
        e.preventDefault();
        resetZoom();
      }
    }
    el.addEventListener("keydown", onKeyDown);
    return () => el.removeEventListener("keydown", onKeyDown);
  }, [ref, zoomIn, zoomOut, resetZoom]);

  return { zoom, zoomIn, zoomOut, resetZoom, atMin: zoom <= MIN, atMax: zoom >= MAX };
}
