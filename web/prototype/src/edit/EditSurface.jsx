import { useEffect, useMemo, useRef, useState } from "react";
import { useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { TextStyle } from "@tiptap/extension-text-style";
import { Color } from "@tiptap/extension-color";
import { Highlight } from "@tiptap/extension-highlight";
import { TextAlign } from "@tiptap/extension-text-align";
import { Subscript } from "@tiptap/extension-subscript";
import { Superscript } from "@tiptap/extension-superscript";
import { RichTextEditor } from "@mantine/tiptap";
import { ActionIcon, Button, Group, Text, Tooltip } from "@mantine/core";
import { IconGripVertical, IconTrash } from "@tabler/icons-react";
import { notifications } from "@mantine/notifications";
import { useEditBoxes } from "./useEditBoxes.js";
import { capacityLabel } from "./capacity.js";
import { docToRuns, runsToHtml } from "./runs.js";
import { useZoom } from "../components/useZoom.js";
import ZoomControls from "../components/ZoomControls.jsx";
import { useLang, useT } from "../i18n.jsx";

const SWATCHES = ["#000000", "#6B0D52", "#053389", "#59595F"];

// @mantine/tiptap's own toolbar tooltips (Bold, Italic, Align text: left,
// ...) come from its `labels` prop, not from our dictionary -- passed
// through only in Spanish since English is Mantine's own default.
const RTE_LABELS_ES = {
  linkControlLabel: "Enlace",
  colorPickerControlLabel: "Color de texto",
  highlightControlLabel: "Resaltar texto",
  colorControlLabel: (color) => `Establecer color de texto ${color}`,
  boldControlLabel: "Negrita",
  italicControlLabel: "Cursiva",
  underlineControlLabel: "Subrayado",
  strikeControlLabel: "Tachado",
  clearFormattingControlLabel: "Borrar formato",
  unlinkControlLabel: "Quitar enlace",
  bulletListControlLabel: "Lista con viñetas",
  orderedListControlLabel: "Lista numerada",
  h1ControlLabel: "Encabezado 1",
  h2ControlLabel: "Encabezado 2",
  h3ControlLabel: "Encabezado 3",
  h4ControlLabel: "Encabezado 4",
  blockquoteControlLabel: "Cita",
  alignLeftControlLabel: "Alinear texto: izquierda",
  alignCenterControlLabel: "Alinear texto: centro",
  alignRightControlLabel: "Alinear texto: derecha",
  alignJustifyControlLabel: "Alinear texto: justificado",
  codeControlLabel: "Código",
  subscriptControlLabel: "Subíndice",
  superscriptControlLabel: "Superíndice",
  unsetColorControlLabel: "Quitar color",
  hrControlLabel: "Línea horizontal",
  undoControlLabel: "Deshacer",
  redoControlLabel: "Rehacer",
  linkEditorInputLabel: "Ingresa la URL",
  linkEditorInputPlaceholder: "https://ejemplo.com/",
  linkEditorExternalLink: "Abrir enlace en una pestaña nueva",
  linkEditorInternalLink: "Abrir enlace en la misma pestaña",
  linkEditorSave: "Guardar",
  colorPickerCancel: "Cancelar",
  colorPickerClear: "Quitar color",
  colorPickerColorPicker: "Selector de color",
  colorPickerPalette: "Paleta de colores",
  colorPickerSave: "Guardar",
  colorPickerColorLabel: (color) => `Establecer color de texto ${color}`,
};

// Full toolbar parity was the explicit call (pass-4 review) -- every
// control in the reference image is enabled, including headings, lists,
// blockquote, code(block), hr, links and sub/superscript, none of which
// pdf/render.py can draw (it renders through exactly two
// page.insert_text() calls, and per-run size isn't representable at all
// -- render.py:74 destructures size into `_size` and discards it).
//
// This is safe rather than silently lossy: docToRuns() (edit/runs.js)
// walks state.doc.descendants() collecting TEXT NODES only, so a heading
// or list item still yields its text on export -- only the structural
// wrapper is dropped, nothing disappears. The edit-note copy below says
// so explicitly rather than leaving it to be discovered in the exported
// JSON.
function useFullExtensions() {
  return useMemo(
    () => [
      StarterKit,
      TextStyle,
      Color,
      Highlight.configure({ multicolor: true }),
      TextAlign.configure({ types: ["paragraph", "heading"] }),
      Subscript,
      Superscript,
    ],
    [],
  );
}

// Editing implies a job -- this is reachable only from Results -> View on
// page. Runs on REAL paragraph geometry: sample/generate.py builds the
// sample page, then runs the actual extract_paragraphs + page_to_ir over
// it, so layout.json is genuine library output, not a hand-built
// approximation (see that script's docstring).
export default function EditSurface({ layout, active, imgSrc, onExport }) {
  const t = useT();
  const [lang] = useLang();
  const pageIr = layout.pages[0];
  const renderInfo = layout.render.pages[0];
  const ZOOM = layout.render.zoom;
  const PT_W = renderInfo.px_width / ZOOM;
  const PT_H = renderInfo.px_height / ZOOM;

  const stackRef = useRef(null);
  const [scale, setScale] = useState(1);
  const zoomState = useZoom(stackRef);
  const { zoom } = zoomState;
  const [selectedKey, setSelectedKey] = useState(null);
  const [editingKey, setEditingKey] = useState(null);
  const suppressUpdateRef = useRef(false);
  const dragRef = useRef(null);

  const boxState = useEditBoxes(pageIr);
  const { getBox, translateBox, resizeBoxWidth, toggleDelete, setRuns, setRunsAndAlign, undo, undoCount, discardAll, unsavedCount, exportPayload } = boxState;

  const extensions = useFullExtensions();
  const editor = useEditor({
    extensions,
    content: "<p></p>",
    onUpdate: ({ editor: ed }) => {
      if (suppressUpdateRef.current || !editingKey) return;
      const box = getBox(editingKey);
      const runs = docToRuns(ed, box.baseStyle);
      setRuns(editingKey, runs);
    },
  });

  // --pp-scale: px per PDF point, refreshed by a single ResizeObserver.
  // Typography can't be expressed as a % of width the way geometry can
  // (see index.css .pp-page-stack comment), so this is the one thing that
  // needs a JS recompute -- if it misfires, text is the wrong size in a
  // correctly-placed box: degraded, not broken.
  useEffect(() => {
    if (!active || !stackRef.current) return;
    const el = stackRef.current;
    function update() {
      const w = el.getBoundingClientRect().width;
      if (w > 0) setScale(w / PT_W);
    }
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [active, PT_W]);

  function selectBox(key) {
    if (editingKey && editingKey !== key) commitEditing(editingKey);
    setSelectedKey(key);
  }
  function deselect() {
    if (editingKey) commitEditing(editingKey);
    setSelectedKey(null);
  }

  function enterTextEdit(key) {
    const box = getBox(key);
    if (box.op === "deleted") return;
    setSelectedKey(key);
    setEditingKey(key);
    suppressUpdateRef.current = true;
    editor.commands.setContent(runsToHtml(box.runs));
    suppressUpdateRef.current = false;
    // Seed the editor's own alignment from the box so the Align controls
    // reflect it immediately, then select-all so an unmodified toolbar
    // click (Bold, say) acts on the whole paragraph by default.
    editor.chain().focus().setTextAlign(box.align === "justify" ? "justify" : box.align).selectAll().run();
  }
  function commitEditing(key) {
    if (!editor || editingKey !== key) return;
    const box = getBox(key);
    const runs = docToRuns(editor, box.baseStyle);
    const align = editor.getAttributes("paragraph").textAlign || box.align;
    setRunsAndAlign(key, runs, align);
    setEditingKey(null);
  }

  const allBoxes = pageIr.paragraphs.map((_, i) => getBox(boxState.paraKey(i)));

  function moveStart(e, key) {
    e.stopPropagation();
    const box = getBox(key);
    boxState.pushUndo(key);
    dragRef.current = { mode: "move", key, startX: e.clientX, startY: e.clientY, startRect: { ...box.rect }, startOrigin: box.origin.slice() };
    window.addEventListener("pointermove", onDragMove);
    window.addEventListener("pointerup", onDragEnd);
    selectBox(key);
  }
  function resizeStart(e, key) {
    e.stopPropagation();
    const box = getBox(key);
    boxState.pushUndo(key);
    dragRef.current = { mode: "resize", key, startX: e.clientX, startRect: { ...box.rect } };
    window.addEventListener("pointermove", onDragMove);
    window.addEventListener("pointerup", onDragEnd);
    selectBox(key);
  }
  function currentPxPerPt() {
    const r = stackRef.current.getBoundingClientRect();
    return { x: r.width / PT_W, y: r.height / PT_H };
  }
  function onDragMove(e) {
    const d = dragRef.current;
    if (!d) return;
    const s = currentPxPerPt();
    if (d.mode === "move") {
      translateBox(d.key, d.startRect, d.startOrigin, (e.clientX - d.startX) / s.x, (e.clientY - d.startY) / s.y);
    } else {
      resizeBoxWidth(d.key, d.startRect, (e.clientX - d.startX) / s.x);
    }
  }
  function onDragEnd() {
    dragRef.current = null;
    window.removeEventListener("pointermove", onDragMove);
    window.removeEventListener("pointerup", onDragEnd);
  }

  function handleDelete(key) {
    toggleDelete(key, true);
    notifications.show({ message: t("edit.deleteNotice"), autoClose: 3200 });
  }
  function handleRestore(key) {
    toggleDelete(key, false);
    notifications.show({ message: t("edit.restoreNotice"), autoClose: 3200 });
  }

  function handleExport() {
    const payload = exportPayload(layout.source);
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "trust-deed-aurora.edits.json";
    a.click();
    if (onExport) {
      // Real mode: PATCH /api/jobs/{id}/layout persists the payload
      // server-side AND regenerates the affected page of the translated
      // PDF from it (see routes.patch_layout / pdf.reflow).
      onExport(payload).then(
        () => notifications.show({ message: t("edit.exportNoticeReal"), autoClose: 4200 }),
        (e) => notifications.show({ message: e.message, color: "flag" }),
      );
    } else {
      notifications.show({ message: t("edit.exportNotice"), autoClose: 4200 });
    }
  }

  function boxKeyDown(e, key) {
    if (editingKey === key) {
      if (e.key === "Escape") {
        e.preventDefault();
        commitEditing(key);
        setSelectedKey(key);
      }
      return; // everything else (incl. Ctrl+B/I/U, arrows) reaches the caret / Mantine's own shortcuts
    }
    const box = getBox(key);
    if (box.op === "deleted") return;
    if (e.key === "Enter" || e.key === "F2") {
      e.preventDefault();
      enterTextEdit(key);
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      handleDelete(key);
    } else if (e.key === "Escape") {
      e.preventDefault();
      deselect();
    } else if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) {
      e.preventDefault();
      const step = e.shiftKey ? 10 : 1;
      if (e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
        boxState.pushUndo(key);
        resizeBoxWidth(key, box.rect, e.key === "ArrowRight" ? step : -step);
        return;
      }
      let dx = 0,
        dy = 0;
      if (e.key === "ArrowLeft") dx = -step;
      if (e.key === "ArrowRight") dx = step;
      if (e.key === "ArrowUp") dy = -step;
      if (e.key === "ArrowDown") dy = step;
      boxState.pushUndo(key);
      translateBox(key, box.rect, box.origin, dx, dy);
    }
  }

  // Format/align controls act on whatever the ONE shared TipTap editor
  // currently holds, which is only ever synced to `editingKey`'s runs
  // (see enterTextEdit/commitEditing) -- gating on editingKey rather than
  // selectedKey keeps a click on the toolbar from silently formatting a
  // different, stale paragraph. Delete doesn't touch the editor at all,
  // so it stays keyed on selectedKey alone.
  const isEditingSomething = !!editingKey;

  return (
    <RichTextEditor editor={editor} styles={{ root: { border: "none" } }} labels={lang === "es" ? RTE_LABELS_ES : undefined}>
      {/* Docked above the page, not a floating selection popup -- a popup
          on text selection would misleadingly suggest formatting only
          ever touches the selection; see edit/runs.js for why whole-word
          snapping means it's a little more than that. */}
      <RichTextEditor.Toolbar sticky className="pp-edit-toolbar" style={{ marginBottom: 4 }}>
        {/* Every format/align/history/colour control below gets a REAL
            `disabled` (Mantine's tiptap controls accept it and it blocks
            the click, not just dims it -- see RichTextEditorControl.mjs).
            Before this, these were only opacity-dimmed while still fully
            clickable: clicking one when a paragraph was merely SELECTED
            (not double-clicked into text-edit) silently formatted the
            shared editor's disconnected, invisible content instead of
            the paragraph on screen -- it looked broken because it WAS
            operating on nothing visible. Gating on isEditingSomething
            makes "can't click it yet" the actual state, not just the
            look. */}
        <RichTextEditor.ControlsGroup>
          <RichTextEditor.Bold disabled={!isEditingSomething} />
          <RichTextEditor.Italic disabled={!isEditingSomething} />
          <RichTextEditor.Underline disabled={!isEditingSomething} />
          <RichTextEditor.Strikethrough disabled={!isEditingSomething} />
          <RichTextEditor.ClearFormatting disabled={!isEditingSomething} />
          <RichTextEditor.Code disabled={!isEditingSomething} />
          <RichTextEditor.Highlight disabled={!isEditingSomething} />
        </RichTextEditor.ControlsGroup>

        <RichTextEditor.ControlsGroup>
          <RichTextEditor.H1 disabled={!isEditingSomething} />
          <RichTextEditor.H2 disabled={!isEditingSomething} />
          <RichTextEditor.H3 disabled={!isEditingSomething} />
          <RichTextEditor.H4 disabled={!isEditingSomething} />
        </RichTextEditor.ControlsGroup>

        <RichTextEditor.ControlsGroup>
          <RichTextEditor.Blockquote disabled={!isEditingSomething} />
          <RichTextEditor.Hr disabled={!isEditingSomething} />
          <RichTextEditor.BulletList disabled={!isEditingSomething} />
          <RichTextEditor.OrderedList disabled={!isEditingSomething} />
          <RichTextEditor.Subscript disabled={!isEditingSomething} />
          <RichTextEditor.Superscript disabled={!isEditingSomething} />
        </RichTextEditor.ControlsGroup>

        <RichTextEditor.ControlsGroup>
          <RichTextEditor.Link disabled={!isEditingSomething} />
          <RichTextEditor.Unlink disabled={!isEditingSomething} />
        </RichTextEditor.ControlsGroup>
      </RichTextEditor.Toolbar>

      <RichTextEditor.Toolbar className="pp-edit-toolbar" style={{ marginBottom: 10 }}>
        <RichTextEditor.ControlsGroup>
          <RichTextEditor.AlignLeft disabled={!isEditingSomething} />
          <RichTextEditor.AlignCenter disabled={!isEditingSomething} />
          <RichTextEditor.AlignRight disabled={!isEditingSomething} />
          <RichTextEditor.AlignJustify disabled={!isEditingSomething} />
        </RichTextEditor.ControlsGroup>

        <RichTextEditor.ControlsGroup>
          <RichTextEditor.Undo disabled={!isEditingSomething} />
          <RichTextEditor.Redo disabled={!isEditingSomething} />
        </RichTextEditor.ControlsGroup>

        <RichTextEditor.ControlsGroup>
          <RichTextEditor.ColorPicker colors={SWATCHES} disabled={!isEditingSomething} />
          {SWATCHES.map((c) => (
            <RichTextEditor.Color key={c} color={c} disabled={!isEditingSomething} />
          ))}
          <RichTextEditor.UnsetColor disabled={!isEditingSomething} />
        </RichTextEditor.ControlsGroup>

        {/* Delete is NOT gated on isEditingSomething -- it acts on
            selectedKey alone and works from a plain single-click select,
            by design (see the comment on isEditingSomething above). */}
        <Tooltip label={t("edit.deleteParagraph")}>
          <ActionIcon variant="default" disabled={!selectedKey} onClick={() => selectedKey && handleDelete(selectedKey)}>
            <IconTrash size={15} />
          </ActionIcon>
        </Tooltip>

        <ZoomControls {...zoomState} />

        <Text size="xs" ff="monospace" c="dimmed" ml="auto">
          {selectedKey
            ? t("edit.paragraphLabel", { n: Number(selectedKey.split(":")[1]) + 1 }) + (isEditingSomething ? t("edit.editingSuffix") : "")
            : t("edit.noneSelected")}
        </Text>
      </RichTextEditor.Toolbar>

      <div className="pp-page-viewport">
      <div ref={stackRef} className="pp-page-stack" style={{ "--pp-scale": scale, "--pp-zoom": zoom, cursor: "default" }}>
        <img className="pp-page-base" src={imgSrc || `${import.meta.env.BASE_URL}sample/${renderInfo.png}`} alt={t("sample.altOut")} draggable={false} />
        <div className="pp-edit-layer">
          {pageIr.paragraphs.map((p, i) => {
            const key = boxState.paraKey(i);
            const box = getBox(key);
            const isEditing = editingKey === key;
            const isSelected = selectedKey === key;
            const left = (100 * (box.rect.x0 * ZOOM)) / renderInfo.px_width;
            const top = (100 * (box.rect.y0 * ZOOM)) / renderInfo.px_height;
            const width = (100 * ((box.rect.x1 - box.rect.x0) * ZOOM)) / renderInfo.px_width;
            const height = (100 * ((box.rect.y1 - box.rect.y0) * ZOOM)) / renderInfo.px_height;
            const lead = box.leading || box.size * 1.18;
            const padTopPt = Math.max(0, box.origin[1] - box.rect.y0 - 0.78 * box.size);
            const cap = active ? capacityLabel(box, allBoxes, PT_H, t) : null;

            return (
              <div
                key={key}
                className={"pp-pbox" + (isSelected ? " selected" : "") + (isEditing ? " editing" : "") + (box.op === "deleted" ? " deleted" : "")}
                style={{
                  left: left + "%",
                  top: top + "%",
                  width: width + "%",
                  minHeight: height + "%",
                  fontSize: `calc(var(--pp-scale) * ${box.size}px)`,
                  lineHeight: `calc(var(--pp-scale) * ${lead}px)`,
                  paddingTop: `calc(var(--pp-scale) * ${padTopPt}px)`,
                  textAlign: box.align === "justify" ? "left" : box.align,
                }}
                tabIndex={0}
                role="group"
                aria-label={t("edit.paragraphAria", { n: i + 1, total: pageIr.paragraphs.length })}
                onClick={() => !isEditing && box.op !== "deleted" && selectBox(key)}
                onDoubleClick={() => box.op !== "deleted" && enterTextEdit(key)}
                onKeyDown={(e) => boxKeyDown(e, key)}
              >
                {box.op === "deleted" ? (
                  <button className="pp-pbox-restore" onClick={(e) => { e.stopPropagation(); handleRestore(key); }}>
                    {t("edit.restore")}
                  </button>
                ) : isEditing ? (
                  <RichTextEditor.Content className="pp-pbox-text" onBlur={() => commitEditing(key)} />
                ) : (
                  <div className="pp-pbox-text" dangerouslySetInnerHTML={{ __html: runsToHtml(box.runs).replace(/^<p>|<\/p>$/g, "") }} />
                )}
                {box.op !== "deleted" && !isEditing && (
                  <div
                    className="pp-pbox-move-handle"
                    style={{ position: "absolute", left: -18, top: 0, width: 16, height: 16, display: isSelected ? "grid" : "none", placeItems: "center", cursor: "grab", color: "var(--pp-register)" }}
                    onPointerDown={(e) => moveStart(e, key)}
                    aria-hidden="true"
                  >
                    <IconGripVertical size={13} />
                  </div>
                )}
                {box.op !== "deleted" && <div className="pp-pbox-grow" style={{ height: cap ? cap.growPct + "%" : 0 }} />}
                {box.op !== "deleted" && cap && <span className={"pp-pbox-cap " + cap.state}>{cap.text}</span>}
                {box.op !== "deleted" && !isEditing && <button className="pp-pbox-grip" aria-hidden="true" tabIndex={-1} onPointerDown={(e) => resizeStart(e, key)} />}
              </div>
            );
          })}
        </div>
      </div>
      </div>

      <Group justify="space-between" mt="md" wrap="wrap">
        <Text size="xs" ff="monospace" c="dimmed">
          {unsavedCount
            ? t(unsavedCount === 1 ? "edit.unsavedCount" : "edit.unsavedCountPlural", { n: unsavedCount })
            : t("edit.noUnsaved")}
        </Text>
        <Group gap="xs">
          <Button variant="default" size="compact-sm" disabled={undoCount === 0} onClick={() => { const k = undo(); if (k) setSelectedKey(k); }}>
            {t("common.undo")}
          </Button>
          <Button variant="default" size="compact-sm" disabled={unsavedCount === 0} onClick={() => { discardAll(); setSelectedKey(null); setEditingKey(null); notifications.show({ message: t("edit.discardNotice"), autoClose: 3200 }); }}>
            {t("edit.discard")}
          </Button>
          <Button variant="default" size="compact-sm" onClick={handleExport}>
            {t("edit.download")}
          </Button>
        </Group>
      </Group>
    </RichTextEditor>
  );
}
