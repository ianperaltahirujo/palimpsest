import { useEffect, useRef, useState } from "react";
import { Button, Progress, Text, Title } from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";
import { notifications } from "@mantine/notifications";
import { PHASES } from "../state.jsx";
import { useAppState } from "../state.jsx";
import { useT } from "../i18n.jsx";
import { MOCK } from "../config.js";
import * as api from "../api.js";

const ICON = { done: <IconCheck size={13} />, active: "⟳" };
const PHASE_KEYS = ["classify", "ocr", "extract", "translate", "render", "save"];

function initialPhases() {
  return PHASE_KEYS.map((key) => ({ key, status: "pending", detail: null, count: 0, total: 0 }));
}

// Jumping here via the dev switcher (or back/forward) shows the static
// mid-progress snapshot already baked into PHASES, so a reviewer can
// inspect the state without it disappearing in a few seconds. Only the
// real "Translate N documents ->" button animates (runAnimated).
export default function Running() {
  const { goto, runAnimated, jobId, uploads, setJob } = useAppState();
  const t = useT();
  const [count, setCount] = useState(87);
  const intervalRef = useRef(null);

  // ---- real mode: live SSE progress ----------------------------------
  const [phases, setPhases] = useState(initialPhases);
  const [fileIndex, setFileIndex] = useState(0);
  const [fileCount, setFileCount] = useState(uploads.length || 1);

  useEffect(() => {
    if (MOCK || !jobId) return;
    setPhases(initialPhases());
    setFileIndex(0);
    setFileCount(uploads.length || 1);

    const unsubscribe = api.watchJob(jobId, {
      onEvent: (payload) => {
        setFileIndex(payload.file_index);
        setFileCount(payload.file_count);
        setPhases((prev) => {
          // A new file starting resets the phase ladder -- a "classify"
          // active event for file_index N+1 always follows the previous
          // file's "save" done, never interleaved (jobs.py processes
          // files sequentially), so this is safe to key off phase alone.
          const next = payload.phase === "classify" && payload.status === "active"
            ? initialPhases()
            : prev.map((p) => ({ ...p }));
          const target = next.find((p) => p.key === payload.phase);
          if (target) {
            target.status = payload.status;
            target.detail = payload.detail;
            if (payload.count != null) target.count = payload.count;
            if (payload.total != null) target.total = payload.total;
          }
          return next;
        });
      },
      onDone: (payload) => {
        // Both branches fetch the job and leave this screen -- a failed
        // job still has a real Job record (per-file errors, whatever
        // files DID finish), and Results is what knows how to show
        // that. Leaving the user stuck on "Running" forever with only a
        // toast (which autocloses) was the actual bug: the job was
        // genuinely done, just not successfully, and nothing here ever
        // said so persistently.
        api.getJob(jobId).then(setJob).catch(() => {});
        if (payload.status !== "done") {
          notifications.show({
            message: payload.error || t("running.jobFailed"),
            color: "flag",
            autoClose: 8000,
          });
        }
        setTimeout(() => goto("results"), 400);
      },
      onError: () => {
        notifications.show({ message: t("running.connectionLost"), color: "flag" });
      },
    });
    return unsubscribe;
  }, [jobId, uploads.length, goto, setJob, t]);

  useEffect(() => {
    if (!MOCK) return;
    setCount(87);
    clearInterval(intervalRef.current);
    if (!runAnimated) return;
    intervalRef.current = setInterval(() => {
      setCount((n) => {
        const next = n + 7;
        if (next >= 154) {
          clearInterval(intervalRef.current);
          setTimeout(() => goto("results"), 550);
          return 154;
        }
        return next;
      });
    }, 420);
    return () => clearInterval(intervalRef.current);
  }, [runAnimated, goto]);

  const mockPct = Math.round((count / 154) * 100);
  const translatePhase = phases.find((p) => p.key === "translate");
  const realPct = translatePhase?.total ? Math.round((100 * translatePhase.count) / translatePhase.total) : 0;
  const pct = MOCK ? mockPct : realPct;
  const displayPhases = MOCK ? PHASES : phases;
  const docName = MOCK ? "trust-deed-aurora.pdf" : uploads[fileIndex]?.name || "";

  return (
    <div className="pp-state-pad">
      <Text size="xs" tt="uppercase" c="dimmed" ff="monospace" mb={8} style={{ letterSpacing: ".09em" }}>
        {t("common.step3")}
      </Text>
      <Title order={1} className="pp-stage-h1">
        {t("running.title")}
      </Title>
      <Text c="dimmed" mt={8}>
        {docName}
      </Text>

      <div style={{ marginTop: 28, border: "1px solid var(--pp-rule)", borderRadius: 3, overflow: "hidden", background: "var(--pp-leaf-raised)" }}>
        {displayPhases.map((p, i) => (
          <div
            key={p.key}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 16,
              padding: "16px 20px",
              borderBottom: i < displayPhases.length - 1 ? "1px solid var(--pp-rule-soft)" : "none",
              opacity: p.status === "pending" ? 0.55 : 1,
            }}
          >
            <div
              style={{
                width: 26,
                height: 26,
                borderRadius: "50%",
                border: "1.5px solid var(--pp-rule)",
                display: "grid",
                placeItems: "center",
                flex: "0 0 auto",
                fontFamily: "var(--mantine-font-family-monospace)",
                fontSize: 11,
                color: "var(--pp-ink-faint)",
                ...(p.status === "done" ? { background: "var(--pp-ok)", borderColor: "var(--pp-ok)", color: "#fff" } : {}),
                ...(p.status === "active" ? { borderColor: "var(--pp-register)", color: "var(--pp-register)" } : {}),
              }}
            >
              {p.status === "pending" ? i + 1 : ICON[p.status]}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <Text fw={700} size="sm">
                {t(`running.phase.${p.key}.name`)}
              </Text>
              <Text size="xs" ff="monospace" c="dimmed" mt={3}>
                {MOCK
                  ? p.key === "translate"
                    ? t("running.translateProgress", { count })
                    : t(`running.phase.${p.key}.detail`)
                  : p.key === "translate" && p.total
                    ? t("running.translateProgressReal", { count: p.count, total: p.total })
                    : p.detail || t("running.waiting")}
              </Text>
              {p.key === "translate" && <Progress value={pct} size={5} radius="xl" mt={8} color="register" />}
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 20 }}>
        <Text size="sm" ff="monospace" c="dimmed">
          {MOCK
            ? t("running.footer", { pct })
            : t("running.footerReal", { i: fileIndex + 1, n: fileCount, pct })}
        </Text>
        <Button variant="outline" color="flag" onClick={() => goto("estimate")}>
          {t("common.cancel")}
        </Button>
      </div>
      <Text size="11.5px" c="dimmed" mt={6} maw="44ch">
        {t("running.cancelNote")}
      </Text>
    </div>
  );
}
