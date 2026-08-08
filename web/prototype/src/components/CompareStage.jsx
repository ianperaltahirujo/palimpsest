import { lazy, Suspense, useEffect, useState } from "react";
import { Button, SegmentedControl, Text } from "@mantine/core";
import { IconChevronLeft, IconChevronRight } from "@tabler/icons-react";
import PageWipe from "./PageWipe.jsx";
import { useAppState } from "../state.jsx";
import { useT } from "../i18n.jsx";
import { MOCK } from "../config.js";
import * as api from "../api.js";
import mockLayout from "../sample/layout.json";

// TipTap + @mantine/tiptap (its own chunk -- see vite.config.js's
// manualChunks) are only needed once someone reaches this screen, which
// sits behind the entire Overview -> Results pipeline. Most page loads
// never touch it; loading it lazily keeps it out of everyone else's
// initial bundle.
const EditSurface = lazy(() => import("../edit/EditSurface.jsx"));

// Reached only from Results -> "View on page". Compare and Edit are two
// mutually exclusive modes of the same surface -- `mode` resets to
// "edit" on every mount (the default view), which happens naturally
// here since this component unmounts on "Back to results" rather than
// needing an imperative reset call.
export default function CompareStage() {
  const { closeCompare, comparePage, setComparePage, jobId, job } = useAppState();
  const t = useT();
  const [mode, setMode] = useState("edit");
  const [layout, setLayout] = useState(MOCK ? mockLayout : null);
  const [layoutError, setLayoutError] = useState(null);
  // Bumped after every successful PATCH /layout so the page PNG's URL
  // changes and the browser re-fetches instead of serving the
  // pre-reflow image it already cached under the same URL.
  const [reflowVersion, setReflowVersion] = useState(0);

  const file = job?.files?.[0];
  const fileId = file?.file_id;
  const pageCount = MOCK ? 4 : file?.report?.pages || 1;
  const pageIndex = comparePage - 1; // comparePage is 1-indexed, the API's page param is 0-indexed

  useEffect(() => {
    if (MOCK) return;
    setLayout(null);
    setLayoutError(null);
    api.getLayout(jobId, { fileId, page: pageIndex }).then(setLayout, (e) => setLayoutError(e));
  }, [jobId, fileId, pageIndex]);

  async function handlePatchLayout(payload) {
    await api.patchLayout(jobId, payload, { fileId });
    setReflowVersion((v) => v + 1);
  }

  return (
    <div className="pp-state-pad">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 14, flexWrap: "wrap", marginBottom: 16 }}>
        <Button variant="default" onClick={closeCompare}>
          {t("compare.back")}
        </Button>
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontFamily: "var(--mantine-font-family-monospace)", fontSize: 12.5 }}>
          <Button variant="default" size="compact-sm" px={6} aria-label={t("compare.prevAria")} onClick={() => setComparePage(Math.max(1, comparePage - 1))}>
            <IconChevronLeft size={14} />
          </Button>
          <span>{t("compare.page", { n: comparePage })}</span>
          <Button variant="default" size="compact-sm" px={6} aria-label={t("compare.nextAria")} onClick={() => setComparePage(Math.min(pageCount, comparePage + 1))}>
            <IconChevronRight size={14} />
          </Button>
        </div>
        <SegmentedControl
          value={mode}
          onChange={setMode}
          data={[
            { label: t("compare.compare"), value: "compare" },
            { label: t("compare.edit"), value: "edit" },
          ]}
        />
      </div>

      {mode === "compare" ? (
        <PageWipe
          baseSrc={MOCK ? "/sample/output.png" : api.pageUrl(jobId, pageIndex, { side: "output", fileId, v: reflowVersion })}
          baseAlt={t("sample.altOut")}
          wipeSrc={MOCK ? "/sample/source.png" : api.pageUrl(jobId, pageIndex, { side: "source", fileId })}
          wipeAlt={t("sample.altSrc")}
        />
      ) : layout ? (
        <Suspense fallback={<Text c="dimmed" size="sm">{t("compare.loadingLayout")}</Text>}>
          <EditSurface
            layout={layout}
            active={mode === "edit"}
            imgSrc={MOCK ? undefined : api.pageUrl(jobId, pageIndex, { side: "output", fileId, v: reflowVersion })}
            onExport={MOCK ? undefined : handlePatchLayout}
          />
        </Suspense>
      ) : (
        <Text c="dimmed" size="sm">
          {layoutError ? layoutError.message : t("compare.loadingLayout")}
        </Text>
      )}

      {mode === "compare" && MOCK && (
        <Text ta="center" size="xs" c="dimmed" mt={10}>
          {t("compare.fixtureNote")}
        </Text>
      )}
    </div>
  );
}
