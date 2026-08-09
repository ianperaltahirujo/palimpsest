import { useEffect } from "react";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { cleanNotifications, Notifications } from "@mantine/notifications";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api.js", () => ({
  health: vi.fn(),
  createJob: vi.fn(),
  watchJob: vi.fn(),
  getJob: vi.fn(),
}));

import * as api from "../api.js";
import { theme } from "../theme.js";
import { I18nProvider } from "../i18n.jsx";
import { AppStateProvider, useAppState } from "../state.jsx";
import Running from "./Running.jsx";

// checkJobHealth() (Running.jsx) is the one authoritative "is this job
// still alive" check, reachable from a real SSE `onerror` and from a
// stall timer that fires even if `onerror` never does. These tests drive
// it directly by capturing the callbacks api.watchJob() was given and
// calling them, rather than trying to simulate a real EventSource.

let watchCallbacks;

function ScreenProbe() {
  const { screen: current } = useAppState();
  return <div data-testid="screen-probe">{current}</div>;
}

// Running never starts a job itself (that's Estimate's "Translate" button)
// -- this harness drives the same real (non-MOCK) startJob() call, then
// mounts/unmounts Running based on the real `screen` value, exactly like
// App.jsx's screen switcher, so a checkJobHealth()-driven goto("results")
// is observable (and correctly unmounts Running, running its cleanup).
function Harness() {
  const { startJob, goto, screen: current } = useAppState();
  useEffect(() => {
    startJob({ dual: true }).then(() => goto("running", { animate: true }));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      <ScreenProbe />
      {current === "running" && <Running />}
    </>
  );
}

function renderRunning() {
  return render(
    <MantineProvider theme={theme}>
      <I18nProvider>
        <Notifications />
        <AppStateProvider>
          <Harness />
        </AppStateProvider>
      </I18nProvider>
    </MantineProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // Mantine's notifications store is global, independent of the
  // component tree -- cleanup() unmounts React but doesn't clear it, so
  // a toast shown in one test would otherwise still be in the DOM (via
  // the Notifications portal) for the next.
  cleanNotifications();
  api.health.mockResolvedValue({
    version: "0", backend: "gemini", anthropic_key_present: false, gemini_key_present: false,
  });
  api.createJob.mockResolvedValue({ job_id: "job1" });
  watchCallbacks = undefined;
  api.watchJob.mockImplementation((_jobId, callbacks) => {
    watchCallbacks = callbacks;
    return vi.fn(); // unsubscribe
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

async function renderAndWaitForWatch() {
  renderRunning();
  await waitFor(() => expect(watchCallbacks).toBeDefined());
}

describe("onError: job genuinely gone", () => {
  it("shows the lost-job toast and navigates to results when getJob rejects", async () => {
    await renderAndWaitForWatch();
    api.getJob.mockRejectedValue(new Error("unknown job 'job1'"));

    watchCallbacks.onError();

    expect(await screen.findByText(/lost track of this job/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("screen-probe")).toHaveTextContent("results"));
  });
});

describe("onError: transient blip, job still alive", () => {
  it("shows connectionLost and does not navigate, and debounces a second immediate onError", async () => {
    await renderAndWaitForWatch();
    api.getJob.mockResolvedValue({ id: "job1", status: "running", files: [] });

    watchCallbacks.onError();
    await screen.findByText(/lost the connection/i);
    expect(screen.getByTestId("screen-probe")).toHaveTextContent("running");

    // Fired again immediately (as EventSource's own auto-reconnect would
    // during a burst of failed attempts) -- must not re-probe within the
    // debounce window.
    watchCallbacks.onError();
    await new Promise((r) => setTimeout(r, 10));
    expect(api.getJob).toHaveBeenCalledTimes(1);
  });
});

describe("onError: SSE missed the terminal event", () => {
  it("finishes normally when getJob reports the job already done", async () => {
    await renderAndWaitForWatch();
    api.getJob.mockResolvedValue({
      id: "job1", status: "done", files: [{ file_id: "f1", status: "done" }],
    });

    watchCallbacks.onError();

    await waitFor(() => expect(screen.getByTestId("screen-probe")).toHaveTextContent("results"));
    expect(screen.queryByText(/lost track of this job/i)).not.toBeInTheDocument();
  });

  it("shows the failure toast when getJob reports the job failed", async () => {
    await renderAndWaitForWatch();
    api.getJob.mockResolvedValue({ id: "job1", status: "failed", error: "boom", files: [] });

    watchCallbacks.onError();

    expect(await screen.findByText("boom")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("screen-probe")).toHaveTextContent("results"));
  });
});

describe("stall timer: no onError ever fires", () => {
  it("reaches the same lost-job outcome once the stream goes silent for too long", async () => {
    vi.useFakeTimers();
    try {
      renderRunning();
      // Flushes the pending microtasks (startJob's mocked promise,
      // goto("running"), Running's mount effect) without advancing wall
      // time -- a real `waitFor` polls via setTimeout, which fake timers
      // don't advance on their own.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(watchCallbacks).toBeDefined();
      api.getJob.mockRejectedValue(new Error("unknown job 'job1'"));

      // Past STALL_MS (90s): the interval tick that first crosses the
      // threshold lands at 105s (7 x 15s), and checkJobHealth's own
      // goto("results") is itself behind a further 400ms setTimeout --
      // advance well past both.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(120_000);
      });

      expect(api.getJob).toHaveBeenCalled();
      expect(screen.getByTestId("screen-probe")).toHaveTextContent("results");
    } finally {
      vi.useRealTimers();
    }
  });
});
