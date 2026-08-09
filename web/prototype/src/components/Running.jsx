import { useEffect, useRef, useState } from "react";
import { Button, Loader, Progress, Text, Title } from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";
import { notifications } from "@mantine/notifications";
import { PHASES } from "../state.jsx";
import { useAppState } from "../state.jsx";
import { useT } from "../i18n.jsx";
import { MOCK } from "../config.js";
import * as api from "../api.js";

// A real spinner, not a static glyph -- the previous "⟳" character never
// moved, which made a genuinely long phase (OCR, or Translate against a
// slow/rate-limited backend) look identical to a frozen tab. A real
// Loader is the one honest signal "still working" has over "stopped
// working" when nothing else on screen is changing yet.
const ICON = { done: <IconCheck size={13} />, active: <Loader size={13} color="register" /> };
const PHASE_KEYS = ["classify", "ocr", "extract", "translate", "render", "save"];

// How long without ANY server signal (an SSE progress event, or a
// successful health probe) before treating this job as possibly gone --
// generous on purpose. A real single phase (Translate, against a slow or
// rate-limited backend) can legitimately go quiet for a while between
// progress events; this must not fire on that, only on something that
// looks like the job has actually stopped existing.
const STALL_MS = 90_000;
const STALL_CHECK_INTERVAL_MS = 15_000;
// Collapses a burst of EventSource auto-reconnect `error` events (it
// retries repeatedly on its own, each attempt re-firing onerror) into at
// most one real health check every few seconds, and also rate-limits the
// stall-interval's own checks relative to any onError-triggered one --
// both paths share this one timestamp.
const PROBE_DEBOUNCE_MS = 4_000;

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

  // Tracks whether the job might be GONE, not just slow -- the SSE
  // stream is the only source of progress, but it has no way to tell
  // "still working" from "the server died and nothing will ever arrive
  // again" on its own (a native EventSource just keeps silently
  // retrying a URL that may 404 forever; see api.js's watchJob). These
  // refs (not state -- nothing here should re-render on every tick)
  // back a periodic reconciliation against the server's actual GET
  // /api/jobs/{id}, which IS able to tell the difference.
  const lastEventAtRef = useRef(0);
  const lastProbeAtRef = useRef(0);
  const stalledNotifiedRef = useRef(false);

  useEffect(() => {
    if (MOCK || !jobId) return;
    setPhases(initialPhases());
    setFileIndex(0);
    setFileCount(uploads.length || 1);
    lastEventAtRef.current = Date.now();
    lastProbeAtRef.current = 0;
    stalledNotifiedRef.current = false;

    // Shared by onDone (the normal path -- the SSE stream itself
    // reported completion) and checkJobHealth (the recovery path --
    // the stream never told us, but a direct GET /api/jobs/{id} shows
    // the job actually finished). A failed job still has a real Job
    // record (per-file errors, whatever files DID finish), and Results
    // is what knows how to show that -- leaving the user stuck here
    // with only a toast (which autocloses) was the original bug: the
    // job was genuinely done, just not successfully, and nothing here
    // ever said so persistently.
    function finishWithJob(freshJob) {
      setJob(freshJob);
      if (freshJob.status !== "done") {
        notifications.show({
          message: freshJob.error || t("running.jobFailed"),
          color: "flag",
          autoClose: 8000,
        });
      }
      setTimeout(() => goto("results"), 400);
    }

    // The one authoritative check, called from both a real SSE `error`
    // event and a stall timer that fires even if `error` never does
    // (e.g. a proxy holding a dead TCP connection open with no FIN/RST
    // ever reaching the browser). Debounced across BOTH callers via one
    // shared timestamp, since EventSource's own auto-reconnect can fire
    // `error` repeatedly in a burst and the stall timer ticks on its own
    // schedule regardless.
    function checkJobHealth() {
      const now = Date.now();
      if (now - lastProbeAtRef.current < PROBE_DEBOUNCE_MS) return;
      lastProbeAtRef.current = now;
      api
        .getJob(jobId)
        .then((freshJob) => {
          if (freshJob.status === "done" || freshJob.status === "failed") {
            // The SSE stream missed its own terminal event -- we still
            // have the real, finished job, so finish exactly as if it
            // had arrived normally.
            finishWithJob(freshJob);
            return;
          }
          // Still genuinely queued/running server-side -- a transient
          // blip, not job loss. EventSource is already retrying on its
          // own; only surface this once per stall episode, not on every
          // debounced re-check.
          if (!stalledNotifiedRef.current) {
            stalledNotifiedRef.current = true;
            notifications.show({ message: t("running.connectionLost"), color: "flag" });
          }
        })
        .catch(() => {
          // Can't even ask -- unreachable server, or a 404 because the
          // job (and everything about it) is genuinely gone, e.g. a
          // hosted deployment's process restarted and lost all
          // in-memory/on-disk job state (see docs/deployment.md).
          // Nothing left to watch or wait for.
          setJob(null);
          notifications.show({ message: t("running.jobLost"), color: "flag", autoClose: 8000 });
          setTimeout(() => goto("results"), 400);
        });
    }

    const stallCheck = setInterval(() => {
      if (Date.now() - lastEventAtRef.current > STALL_MS) checkJobHealth();
    }, STALL_CHECK_INTERVAL_MS);

    const unsubscribe = api.watchJob(jobId, {
      onEvent: (payload) => {
        lastEventAtRef.current = Date.now();
        stalledNotifiedRef.current = false;
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
      onError: checkJobHealth,
    });
    return () => {
      clearInterval(stallCheck);
      unsubscribe();
    };
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
