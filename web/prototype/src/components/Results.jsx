import { Badge, Button, Group, SimpleGrid, Text, Title } from "@mantine/core";
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
  replica: { icon: "PDF" },
  dual: { icon: "2x" },
  report: { icon: "{ }" },
};

// Aggregates every file's report in a job into the shapes the fixed
// (single-document) fixtures below already have -- report.failed[]
// entries carry their own `status` (failed/refused/identical), which is
// exactly what RESULTS_ISSUES/STATUS_COLOR already key on, so no
// reclassification is needed, only flattening across files.
function summarize(job) {
  const files = job?.files || [];
  const reports = files.map((f) => f.report).filter(Boolean);
  const translated = reports.reduce((n, r) => n + (r.translated || 0), 0);
  const paragraphs = reports.reduce((n, r) => n + (r.paragraphs || 0), 0);
  const skipped = reports.reduce((n, r) => n + (r.skipped || 0), 0);
  const failedList = files.flatMap((f) =>
    (f.report?.failed || []).map((issue) => ({ ...issue, fileId: f.file_id })),
  );
  const countByStatus = (status) => failedList.filter((i) => i.status === status).length;
  const fontSubs = files.flatMap((f) =>
    Object.entries(f.report?.font_substitutions || {}).map(([from, to]) => ({ from, to })),
  );
  return {
    translated, paragraphs, skipped, failedList,
    stats: [
      { n: translated, label: "translated", tone: "ok" },
      { n: skipped, label: "skippedProtected", tone: "skip" },
      { n: countByStatus("failed"), label: "failed", tone: "fail" },
      { n: countByStatus("refused"), label: "refused", tone: "fail" },
      { n: countByStatus("identical"), label: "identical", tone: "skip" },
    ],
    fontSubs,
    firstFileId: files[0]?.file_id,
    firstFileName: files[0]?.name,
  };
}

export default function Results() {
  const { goto, openCompare, compareOpen, job, jobId, resetPipeline } = useAppState();
  const t = useT();

  if (compareOpen) return <CompareStage />;

  const summary = MOCK ? null : summarize(job);
  const stats = MOCK ? RESULTS_STATS : summary.stats;
  const issues = MOCK ? RESULTS_ISSUES : summary.failedList;
  const fontSubs = MOCK ? FONT_SUBS : summary.fontSubs;
  const translated = MOCK ? 154 : summary.translated;
  const paragraphs = MOCK ? 172 : summary.paragraphs;
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
        <Button variant="default" onClick={handleNewTranslation}>
          {t("results.newTranslation")}
        </Button>
      </Group>

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
        {issues.length === 0 && !MOCK && (
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
                {MOCK ? t(`results.issue.${issue.detail}`) : `page ${issue.page} -- ${issue.status}`}
              </Text>
            </div>
            <button className="pp-link-btn" onClick={() => openCompare(issue.page)}>
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
              </button>
            ))
          : Object.keys(DOWNLOAD_META).map((key) => (
              <a
                key={key}
                className="pp-download-card"
                href={api.downloadUrl(jobId, key, summary.firstFileId)}
                download
              >
                <span className="pp-dl-icon">{DOWNLOAD_META[key].icon}</span>
                <span>
                  <span style={{ fontWeight: 700, fontSize: 12.5, display: "block" }}>{t(`results.download.${key}.title`)}</span>
                  <span style={{ fontSize: 11, color: "var(--pp-ink-soft)" }}>{summary.firstFileName || ""}</span>
                </span>
              </a>
            ))}
      </Group>
    </div>
  );
}
