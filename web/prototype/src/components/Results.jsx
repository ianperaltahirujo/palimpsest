import { Badge, Button, Group, SimpleGrid, Text, Title } from "@mantine/core";
import { IconDownload } from "@tabler/icons-react";
import { notifications } from "@mantine/notifications";
import { DOWNLOADS, FONT_SUBS, RESULTS_ISSUES, RESULTS_STATS } from "../state.jsx";
import { useAppState } from "../state.jsx";
import { useT } from "../i18n.jsx";
import { MOCK } from "../config.js";
import * as api from "../api.js";
import CompareStage from "./CompareStage.jsx";

const STATUS_COLOR = { failed: "flag", refused: "under", identical: "gray", skipped: "register" };
const STAT_COLOR = { ok: "ok", skip: "gray", fail: "flag" };
const DOWNLOAD_META = {
  replica: { icon: null },
  dual: { icon: "2x" },
  report: { icon: "{ }" },
};

function extLabel(name) {
  const ext = (name || "").split(".").pop();
  return ext ? ext.toUpperCase() : "?";
}

// pdf.pipeline's report is pages/paragraphs-shaped (translated, skipped,
// failed[{page,text,status}], font_substitutions). office.ooxml's is
// completely different -- nodes/parts-shaped (stats.nodes, failures[] as
// bare strings with no page number, no font_substitutions concept at
// all) -- so each file's report is normalized to one common shape here
// before anything downstream (stats grid, "what didn't translate") has
// to know which pipeline produced it.
function normalizeReport(f) {
  if (!f.report) return { translated: 0, paragraphs: 0, skipped: 0, failed: [], fontSubs: {} };
  if (f.kind === "office") {
    const nodes = f.report.stats?.nodes || 0;
    const failures = f.report.failures || [];
    return {
      translated: nodes,
      paragraphs: nodes + failures.length,
      skipped: 0,
      failed: failures.map((text) => ({ text, status: "failed" })),
      fontSubs: {},
    };
  }
  return {
    translated: f.report.translated || 0,
    paragraphs: f.report.paragraphs || 0,
    skipped: f.report.skipped || 0,
    failed: f.report.failed || [],
    fontSubs: f.report.font_substitutions || {},
  };
}

// Aggregates every file's (normalized) report in a job into the shapes
// the fixed (single-document) fixtures below already have -- failed[]
// entries carry their own `status` (failed/refused/identical), which is
// exactly what RESULTS_ISSUES/STATUS_COLOR already key on, so no
// reclassification is needed, only flattening across files.
function summarize(job) {
  const files = job?.files || [];
  const normalized = files.map((f) => ({ f, r: normalizeReport(f) })).filter(({ f }) => f.report);
  const translated = normalized.reduce((n, { r }) => n + r.translated, 0);
  const paragraphs = normalized.reduce((n, { r }) => n + r.paragraphs, 0);
  const skipped = normalized.reduce((n, { r }) => n + r.skipped, 0);
  const failedList = normalized.flatMap(({ f, r }) =>
    r.failed.map((issue) => ({ ...issue, fileId: f.file_id })),
  );
  const countByStatus = (status) => failedList.filter((i) => i.status === status).length;
  const fontSubs = normalized.flatMap(({ r }) =>
    Object.entries(r.fontSubs).map(([from, to]) => ({ from, to })),
  );
  // A file that never produced a report at all -- OCR/translation
  // backend/dependency errors raised before any paragraph was touched
  // (jobs.py catches these per-file, sets status="failed" and `error`,
  // but leaves `report` null). Distinct from failedList above, which is
  // per-PARAGRAPH issues inside an otherwise-successful report.
  const fileFailures = files
    .filter((f) => f.status === "failed")
    .map((f) => ({ name: f.name, error: f.error || "translation failed" }));
  const firstOk = files.find((f) => f.status === "done");
  return {
    translated, paragraphs, skipped, failedList, fileFailures,
    stats: [
      { n: translated, label: "translated", tone: "ok" },
      { n: skipped, label: "skippedProtected", tone: "skip" },
      { n: countByStatus("failed"), label: "failed", tone: "fail" },
      { n: countByStatus("refused"), label: "refused", tone: "fail" },
      { n: countByStatus("identical"), label: "identical", tone: "skip" },
    ],
    fontSubs,
    firstFileId: firstOk?.file_id,
    firstFileName: firstOk?.name || files[0]?.name,
    // Dual PDF is never generated for Office files (jobs.py only builds
    // one when job.dual and the file isn't "office") -- the download
    // card must not be offered where clicking it can only 404.
    firstFileIsOffice: firstOk?.kind === "office",
  };
}

export default function Results() {
  const { goto, openCompare, compareOpen, job, jobId, resetPipeline } = useAppState();
  const t = useT();

  if (compareOpen) return <CompareStage />;

  // summarize(null) renders zeros in every stat cell ("0 of 0 paragraphs
  // translated", "nothing to report") -- reads as a completed job with
  // a clean bill of health rather than "no job at all", which is the
  // actual state right after a job's own GET /api/jobs/{id} fetch fails
  // (Running.jsx's onDone handler swallows that fetch's rejection and
  // still navigates here). An honest empty state instead of a fake one.
  if (!MOCK && !job) {
    return (
      <div className="pp-state-pad">
        <Title order={1} style={{ fontFamily: '"Archivo Expanded", "Arial Narrow", sans-serif', fontWeight: 800, fontStretch: "112%", fontSize: 30, lineHeight: 1.2 }}>
          {t("results.noJobTitle")}
        </Title>
        <Text size="sm" c="dimmed" mt={10} maw="62ch">
          {t("results.noJobBody")}
        </Text>
        <Button variant="default" mt={18} onClick={handleNewTranslation}>
          {t("results.newTranslation")}
        </Button>
      </div>
    );
  }

  const summary = MOCK ? null : summarize(job);
  const stats = MOCK ? RESULTS_STATS : summary.stats;
  const issues = MOCK ? RESULTS_ISSUES : summary.failedList;
  const fontSubs = MOCK ? FONT_SUBS : summary.fontSubs;
  const translated = MOCK ? 154 : summary.translated;
  const paragraphs = MOCK ? 172 : summary.paragraphs;
  const fileFailures = MOCK ? [] : summary.fileFailures;
  const jobError = MOCK ? null : job?.error;
  const hasDownloads = MOCK || !!summary.firstFileId;
  const docLabel = MOCK
    ? "trust-deed-aurora.pdf → trust-deed-aurora.en.pdf"
    : summary.firstFileName || "";

  function handleNewTranslation() {
    if (!MOCK) resetPipeline();
    goto("sample");
  }

  return (
    <div className="pp-state-pad">
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <div>
          <Text size="xs" tt="uppercase" c="dimmed" ff="monospace" style={{ letterSpacing: ".09em" }}>
            {docLabel}
          </Text>
          <Title order={1} mt={4} style={{ fontFamily: '"Archivo Expanded", "Arial Narrow", sans-serif', fontWeight: 800, fontStretch: "112%", fontSize: 30, lineHeight: 1.2 }}>
            <span style={{ color: "var(--pp-register-ink)" }}>{translated}</span> {t("results.titleRest", { total: paragraphs })}
          </Title>
        </div>
        <Group gap={8}>
          {hasDownloads && (
            <Button variant="default" onClick={() => openCompare(1)}>
              {t("results.viewPages")}
            </Button>
          )}
          <Button variant="default" onClick={handleNewTranslation}>
            {t("results.newTranslation")}
          </Button>
        </Group>
      </Group>

      <Text size="xs" c="dimmed" mt={10} maw="62ch">
        {t("results.disclaimer")}
      </Text>

      {(fileFailures.length > 0 || jobError) && (
        <div style={{ border: "1px solid var(--pp-flag)", borderRadius: 3, padding: "14px 16px", background: "var(--pp-leaf-raised)", marginTop: 20 }}>
          <Text fw={700} size="sm" c="flag">
            {t("results.fileFailedTitle")}
          </Text>
          {fileFailures.map((f) => (
            <Text key={f.name} size="sm" mt={6}>
              <strong>{f.name}:</strong> {f.error}
            </Text>
          ))}
          {jobError && (
            <Text size="sm" mt={6}>
              {jobError}
            </Text>
          )}
        </div>
      )}

      <SimpleGrid cols={{ base: 2, sm: 5 }} spacing={1} mt={22} style={{ background: "var(--pp-rule)", border: "1px solid var(--pp-rule)", borderRadius: 3, overflow: "hidden" }}>
        {stats.map((s) => (
          <div key={s.label} style={{ background: "var(--pp-leaf-raised)", padding: "14px 16px" }}>
            <Text ff="monospace" fw={600} size="19px" c={STAT_COLOR[s.tone]}>
              {s.n}
            </Text>
            <Text ff="monospace" size="10px" tt="uppercase" c="dimmed" mt={3} style={{ letterSpacing: ".07em" }}>
              {t(`results.stat.${s.label}`)}
            </Text>
          </div>
        ))}
      </SimpleGrid>

      <Title order={2} mt={36} mb={12} style={{ fontFamily: '"Archivo Expanded", "Arial Narrow", sans-serif', fontWeight: 700, fontStretch: "110%", fontSize: 15.5 }}>
        {t("results.subtitle1")}
      </Title>
      <div>
        {issues.length === 0 && !MOCK && fileFailures.length === 0 && (
          <Text size="sm" c="dimmed">
            {t("results.noIssues")}
          </Text>
        )}
        {issues.map((issue, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              gap: 14,
              alignItems: "flex-start",
              padding: "13px 15px",
              border: "1px solid var(--pp-rule)",
              borderTop: i === 0 ? "1px solid var(--pp-rule)" : "none",
              borderRadius: i === 0 ? "3px 3px 0 0" : i === issues.length - 1 ? "0 0 3px 3px" : 0,
              background: "var(--pp-leaf-raised)",
            }}
          >
            <Badge size="xs" variant="light" color={STATUS_COLOR[issue.status]} radius="sm" style={{ marginTop: 1 }}>
              {t(`results.status.${issue.status}`)}
            </Badge>
            <div style={{ flex: 1, minWidth: 0 }}>
              <Text size="sm">{issue.text}</Text>
              <Text size="11px" c="dimmed" ff="monospace" mt={4}>
                {MOCK
                  ? t(`results.issue.${issue.detail}`)
                  : issue.page != null
                    ? `page ${issue.page} -- ${issue.status}`
                    : issue.status}
              </Text>
            </div>
            <button className="pp-link-btn" onClick={() => openCompare(issue.page ?? 1)}>
              {t("results.viewOnPage")}
            </button>
          </div>
        ))}
      </div>

      {fontSubs.length > 0 && (
        <>
          <Title order={2} mt={36} mb={12} style={{ fontFamily: '"Archivo Expanded", "Arial Narrow", sans-serif', fontWeight: 700, fontStretch: "110%", fontSize: 15.5 }}>
            {t("results.subtitle2")}
          </Title>
          <div style={{ border: "1px solid var(--pp-rule)", borderRadius: 3, padding: "14px 16px", background: "var(--pp-leaf-raised)" }}>
            {fontSubs.map((s, i) => (
              <Group key={`${s.from}-${i}`} gap={10} ff="monospace" style={{ fontSize: 12.5, padding: "5px 0" }}>
                <span>{s.from}</span>
                <span style={{ color: "var(--pp-ink-faint)" }}>→</span>
                <span>{s.to}</span>
                {MOCK && s.count != null && (
                  <span style={{ color: "var(--pp-ink-faint)" }}>· {t("results.fontSubCount", { count: s.count })}</span>
                )}
              </Group>
            ))}
          </div>
        </>
      )}

      {hasDownloads && (
      <Group mt={32} gap={10} wrap="wrap">
        {MOCK
          ? DOWNLOADS.map((d) => (
              <button
                key={d.file}
                className="pp-download-card"
                onClick={() => notifications.show({ message: t("results.downloadNotice", { file: d.file }) })}
              >
                <span className="pp-dl-icon">{d.icon}</span>
                <span>
                  <span style={{ fontWeight: 700, fontSize: 12.5, display: "block" }}>{t(`results.download.${d.key}.title`)}</span>
                  <span style={{ fontSize: 11, color: "var(--pp-ink-soft)" }}>{t(`results.download.${d.key}.sub`)}</span>
                </span>
                <IconDownload size={16} style={{ marginLeft: "auto", flexShrink: 0, color: "var(--pp-ink-faint)" }} />
              </button>
            ))
          : Object.keys(DOWNLOAD_META)
              .filter((key) => key !== "dual" || !summary.firstFileIsOffice)
              .map((key) => (
                <a
                  key={key}
                  className="pp-download-card"
                  href={api.downloadUrl(jobId, key, summary.firstFileId)}
                  download
                >
                  <span className="pp-dl-icon">
                    {key === "replica" ? extLabel(summary.firstFileName) : DOWNLOAD_META[key].icon}
                  </span>
                  <span>
                    <span style={{ fontWeight: 700, fontSize: 12.5, display: "block" }}>{t(`results.download.${key}.title`)}</span>
                    <span style={{ fontSize: 11, color: "var(--pp-ink-soft)" }}>{summary.firstFileName || ""}</span>
                  </span>
                  <IconDownload size={16} style={{ marginLeft: "auto", flexShrink: 0, color: "var(--pp-ink-faint)" }} />
                </a>
              ))}
      </Group>
      )}
    </div>
  );
}
