import { Alert, Button, Group, Progress, SimpleGrid, Text, Title } from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";
import { notifications } from "@mantine/notifications";
import { ESTIMATE } from "../state.jsx";
import { useAppState } from "../state.jsx";
import { T, useT } from "../i18n.jsx";
import { MOCK } from "../config.js";

function Cell({ label, value, sub, valueColor, bar }) {
  return (
    <div style={{ background: "var(--pp-leaf-raised)", padding: "18px 20px" }}>
      <Text size="10.5px" tt="uppercase" c="dimmed" ff="monospace" style={{ letterSpacing: ".08em" }}>
        {label}
      </Text>
      <Text
        mt={6}
        style={{ fontFamily: '"Archivo Expanded", "Arial Narrow", sans-serif', fontWeight: 800, fontStretch: "110%", fontSize: 25, color: valueColor }}
      >
        {value}
      </Text>
      <Text size="11.5px" c="dimmed" mt={4}>
        {sub}
      </Text>
      {bar !== undefined && <Progress value={bar} size={5} radius="xl" mt={9} color="ok" />}
    </div>
  );
}

// Sums the per-file numbers POST /api/estimate returns into the same
// four-cell shape ESTIMATE (the mock fixture) already has -- `usd` stays
// null if every file's was null (all-free or all-unpriceable), never
// coerced to 0, mirroring translate.estimate.CorpusEstimate's own rule.
function aggregate(estimates) {
  const sum = (key) => estimates.reduce((n, e) => n + (e[key] || 0), 0);
  const anyPriced = estimates.some((e) => e.usd != null);
  const usd = anyPriced ? estimates.reduce((n, e) => n + (e.usd || 0), 0) : null;
  return {
    paragraphs: sum("unit_count"),
    uniqueStrings: sum("unique_count"),
    cacheHits: sum("cache_hits"),
    tokensIn: sum("input_tokens"),
    tokensOut: sum("output_tokens"),
    usd,
  };
}

export default function Estimate() {
  // health is lifted into AppStateProvider (state.jsx) -- probed once
  // there and shared with BackendSelector.jsx and the app-level
  // unreachable banner, rather than each fetching its own.
  const { goto, uploads, estimates, startJob, health } = useAppState();
  const t = useT();

  const agg = MOCK
    ? {
        paragraphs: ESTIMATE.paragraphs, uniqueStrings: ESTIMATE.uniqueStrings,
        cacheHits: ESTIMATE.cacheHits, tokensIn: ESTIMATE.tokensIn, tokensOut: ESTIMATE.tokensOut,
      }
    : aggregate(estimates);
  const costText = MOCK ? ESTIMATE.cost : agg.usd != null ? `~$${agg.usd.toFixed(2)}` : t("estimate.costUnknown");
  const modelLabel = MOCK ? ESTIMATE.model : health?.backend ?? "";
  const cacheHitPct = agg.uniqueStrings ? (100 * agg.cacheHits) / agg.uniqueStrings : 0;
  const docCount = MOCK ? 2 : uploads.length;

  // POST /api/estimate opens the RAW upload and never OCRs -- server-side,
  // routes.py's estimate() reads the file directly while the real pipeline
  // (pdf/pipeline.py) calls ensure_ocr() FIRST. So a scan has no text layer
  // at this point and every number for it comes back 0, with usd null. We
  // deliberately do NOT OCR here (minutes per document, and it would time
  // out on a free-tier host) -- we say so instead. Translation is unaffected;
  // it OCRs on its way through.
  const scanCount = MOCK ? 0 : estimates.filter((e) => e.kind === "scan").length;
  const allScans = scanCount > 0 && scanCount === estimates.length;

  async function handleTranslate() {
    if (MOCK) {
      goto("running", { animate: true });
      return;
    }
    try {
      await startJob({ dual: true });
      goto("running", { animate: true });
    } catch (e) {
      notifications.show({ message: e.message, color: "flag" });
    }
  }

  return (
    <div className="pp-state-pad">
      <Text size="xs" tt="uppercase" c="dimmed" ff="monospace" mb={8} style={{ letterSpacing: ".09em" }}>
        {t("common.step2")}
      </Text>
      <Title order={1} className="pp-stage-h1">
        {t("estimate.title")}
      </Title>
      <Text c="dimmed" mt={8} maw="60ch">
        {t("estimate.body")}
      </Text>

      {allScans ? (
        <Alert icon={<IconAlertTriangle size={16} />} color="warn" variant="light" mt={24}>
          <Text size="sm">
            <T k="estimate.allScansBody" />
          </Text>
        </Alert>
      ) : (
        <>
          <SimpleGrid cols={{ base: 2, sm: 4 }} spacing={1} mt={24} style={{ background: "var(--pp-rule)", border: "1px solid var(--pp-rule)", borderRadius: 3, overflow: "hidden" }}>
            <Cell label={t("estimate.paragraphs")} value={agg.paragraphs} sub={t("estimate.uniqueStrings", { n: agg.uniqueStrings })} />
            <Cell
              label={t("estimate.cacheHits")}
              value={<>{agg.cacheHits}<span style={{ fontSize: 15, color: "var(--pp-ink-faint)" }}>/{agg.uniqueStrings}</span></>}
              sub={t("estimate.cacheSub")}
              bar={cacheHitPct}
            />
            <Cell
              label={t("estimate.tokens")}
              value={<span style={{ fontSize: 19 }}>{agg.tokensIn} <span style={{ fontSize: 12, color: "var(--pp-ink-faint)" }}>{t("estimate.in")}</span> / {agg.tokensOut} <span style={{ fontSize: 12, color: "var(--pp-ink-faint)" }}>{t("estimate.out")}</span></span>}
              sub={modelLabel}
            />
            <Cell label={t("estimate.cost")} value={costText} sub={t("estimate.costSub")} valueColor="var(--pp-register-ink)" />
          </SimpleGrid>

          {scanCount > 0 && (
            <Text size="xs" c="dimmed" mt={14}>
              {t(scanCount === 1 ? "estimate.scanExcludedSingular" : "estimate.scanExcluded", { n: scanCount })}
            </Text>
          )}

          <Text size="xs" c="dimmed" mt={14}>
            {t("estimate.note")}
          </Text>
        </>
      )}

      <Group mt={28} gap={10}>
        <Button variant="default" onClick={() => goto("queue")}>
          {t("common.back")}
        </Button>
        <Button onClick={handleTranslate} disabled={docCount === 0}>
          {t(docCount === 1 ? "estimate.ctaSingular" : "estimate.cta", { n: docCount })}
        </Button>
      </Group>
    </div>
  );
}
