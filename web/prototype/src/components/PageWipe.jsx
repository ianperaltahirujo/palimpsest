import { useEffect, useRef, useState } from "react";
import { IconArrowsHorizontal } from "@tabler/icons-react";
import { useZoom } from "./useZoom.js";
import ZoomControls from "./ZoomControls.jsx";
import { useT } from "../i18n.jsx";

// The signature interaction: drag the divider, or focus it and use the
// arrow keys, to compare the source and translated page in exact
// registration. `.pp-page-stack` shrink-wraps its `.pp-page-base` <img>
// exactly (see index.css), so every absolutely-positioned layer here
// registers against the raster with zero extra JS.
export default function PageWipe({ baseSrc, baseAlt, wipeSrc, wipeAlt, sample = false, drift = false, children }) {
  const t = useT();
  const [pct, setPct] = useState(50);
  const userSet = useRef(false);
  const stackRef = useRef(null);
  const draggingRef = useRef(false);
  const zoomState = useZoom(stackRef);
  const { zoom } = zoomState;

  function clampSet(p) {
    const clamped = Math.max(0, Math.min(100, p));
    setPct(clamped);
  }
  function fromClientX(clientX) {
    const r = stackRef.current.getBoundingClientRect();
    return ((clientX - r.left) / r.width) * 100;
  }

  useEffect(() => {
    if (!drift) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) return;
    let t = 0;
    let dir = 1;
    const id = setInterval(() => {
      if (userSet.current) return;
      t += dir * 0.35;
      if (t > 16 || t < -16) dir *= -1;
      setPct(50 + t);
    }, 60);
    return () => clearInterval(id);
  }, [drift]);

  function onPointerDown(e) {
    draggingRef.current = true;
    stackRef.current.setPointerCapture(e.pointerId);
    userSet.current = true;
    clampSet(fromClientX(e.clientX));
  }
  function onPointerMove(e) {
    if (draggingRef.current) clampSet(fromClientX(e.clientX));
  }
  function onPointerUp() {
    draggingRef.current = false;
  }
  function onKeyDown(e) {
    if (e.key === "ArrowLeft") {
      userSet.current = true;
      clampSet(pct - 4);
      e.preventDefault();
    }
    if (e.key === "ArrowRight") {
      userSet.current = true;
      clampSet(pct + 4);
      e.preventDefault();
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
        <ZoomControls {...zoomState} />
      </div>
      <div className="pp-page-viewport">
        <div
          ref={stackRef}
          className={"pp-page-stack" + (sample ? " pp-page-stack--sample" : "")}
          style={{ "--pp-wipe-pct": pct + "%", "--pp-zoom": zoom }}
          tabIndex={0}
          role="slider"
          aria-label={t("wipe.aria")}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(pct)}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onKeyDown={onKeyDown}
        >
          <img className="pp-page-base" src={baseSrc} alt={baseAlt} draggable={false} />
          <img className="pp-page-wipe" src={wipeSrc} alt={wipeAlt} draggable={false} />
          <span className="pp-wipe-label pp-wipe-label--src">{t("wipe.source")}</span>
          <span className="pp-wipe-label pp-wipe-label--out">{t("wipe.translated")}</span>
          <div className="pp-wipe-divider">
            <div className="pp-wipe-handle">
              <IconArrowsHorizontal size={16} />
            </div>
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}
