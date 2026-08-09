import { describe, expect, it } from "vitest";
import accept from "attr-accept";
import { UPLOAD_ACCEPT } from "./accept.js";

// Mirrors react-dropzone's own flattening of an {mime: [ext,...]} accept
// object into one comma-separated accept-attr string (both mime keys and
// extension values become entries) -- see acceptPropAsAcceptAttr in
// react-dropzone/dist/es/utils/index.js. Not imported directly: that
// module isn't part of react-dropzone's public "exports" map.
function acceptAttr(uploadAccept) {
  return Object.entries(uploadAccept)
    .reduce((all, [mime, exts]) => [...all, mime, ...exts], [])
    .join(",");
}

describe("UPLOAD_ACCEPT", () => {
  it("has the exact MIME type for each of the four supported extensions", () => {
    expect(UPLOAD_ACCEPT).toEqual({
      "application/pdf": [".pdf"],
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
      "application/vnd.openxmlformats-officedocument.presentationml.presentation": [".pptx"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
    });
  });

  // This is the actual regression lock. A DataTransferItem -- the shape
  // react-dropzone gets during dragenter/dragover, before a drop -- has a
  // `type` but NO `name`. An extension-only accept always failed this
  // (attr-accept's leading-dot branch reads `(file.name || '')`, which is
  // '' for a DataTransferItem), which is why the dropzone used to read
  // "reject" (Mantine's stock red) on every drag of a genuinely acceptable
  // file, even though the eventual drop always succeeded.
  it("accepts a bare DataTransferItem (no `name`) by its MIME type during drag-over", () => {
    const attr = acceptAttr(UPLOAD_ACCEPT);
    expect(accept({ type: "application/pdf" }, attr)).toBe(true);
    expect(
      accept(
        { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" },
        attr,
      ),
    ).toBe(true);
    expect(
      accept(
        { type: "application/vnd.openxmlformats-officedocument.presentationml.presentation" },
        attr,
      ),
    ).toBe(true);
    expect(
      accept({ type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }, attr),
    ).toBe(true);
  });

  it("rejects an unrelated MIME type during drag-over", () => {
    const attr = acceptAttr(UPLOAD_ACCEPT);
    expect(accept({ type: "application/zip" }, attr)).toBe(false);
  });

  it("still accepts a real File with a name and matching extension (the drop path, unchanged)", () => {
    const attr = acceptAttr(UPLOAD_ACCEPT);
    expect(accept({ name: "deed.pdf", type: "application/pdf" }, attr)).toBe(true);
    expect(accept({ name: "payload.exe", type: "application/octet-stream" }, attr)).toBe(false);
  });
});
