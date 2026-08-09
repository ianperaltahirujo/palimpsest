import { MIME_TYPES } from "@mantine/dropzone";

// Keyed by MIME with the extension as the VALUE -- not an extension array.
//
// react-dropzone flattens both sides of this object into one accept
// attribute ("application/pdf,.pdf,application/vnd...,.docx,..."), so the
// native file picker still filters on the extensions exactly as before.
// What changes is drag-over: dragenter/dragover hand react-dropzone bare
// DataTransferItems, which carry a `type` (the MIME) but have NO `name`.
// attr-accept matches a leading-dot rule with `(file.name || '')
// .endsWith('.pdf')` -- always false for a DataTransferItem -- so an
// extension-only accept made every drag register as isDragReject, painting
// the zone in Mantine's stock `red` (Dropzone's rejectColor default). The
// drop itself always succeeded, because `drop` resolves real File objects
// with real names; only the hover state lied.
//
// With MIME keys the drag matches on DataTransferItem.type, and the case
// where a browser reports an empty type is already handled upstream by
// react-dropzone v15's isDataTransferItemWithEmptyType.
//
// Deliberately excludes MIME_TYPES.doc/.xls -- those are the legacy binary
// Word/Excel formats, which the backend does not handle.
export const UPLOAD_ACCEPT = {
  [MIME_TYPES.pdf]: [".pdf"],
  [MIME_TYPES.docx]: [".docx"],
  [MIME_TYPES.pptx]: [".pptx"],
  [MIME_TYPES.xlsx]: [".xlsx"],
};
