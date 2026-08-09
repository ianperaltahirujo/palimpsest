import { useEffect } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { cleanNotifications, Notifications } from "@mantine/notifications";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api.js", () => ({
  health: vi.fn(),
  uploadFile: vi.fn(),
  estimate: vi.fn(),
  createJob: vi.fn(),
  cancelJob: vi.fn(),
}));

import * as api from "../api.js";
import { theme } from "../theme.js";
import { I18nProvider } from "../i18n.jsx";
import { AppStateProvider, useAppState } from "../state.jsx";
import Estimate from "./Estimate.jsx";

// Estimate reads `uploads`/`estimates` from AppStateProvider but never
// populates them itself (that's Overview/Sample + Queue's "Estimate
// cost"). This harness drives the same real (non-MOCK) calls a user
// action would, then renders Estimate against the resulting state.
//
// Two effects, not one chained call: `runEstimate` is a useCallback keyed
// on `uploads` (state.jsx), so the reference captured by an effect that
// only runs once at mount is permanently bound to `uploads === []`.
// Calling it after `addUploads` resolves would still submit an empty
// file_ids list. Splitting the trigger on `uploads` itself picks up the
// closure from the render where `uploads` actually contains the new file.
function ScreenProbe() {
  const { screen: current } = useAppState();
  return <div data-testid="screen-probe">{current}</div>;
}

function Harness({ files }) {
  const { addUploads, runEstimate, uploads } = useAppState();
  useEffect(() => {
    addUploads(files.map((f) => new File(["x"], f.name)));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (uploads.length === files.length) runEstimate();
  }, [uploads]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      <ScreenProbe />
      <Estimate />
    </>
  );
}

function renderEstimate(files) {
  return render(
    <MantineProvider theme={theme}>
      <I18nProvider>
        <Notifications />
        <AppStateProvider>
          <Harness files={files} />
        </AppStateProvider>
      </I18nProvider>
    </MantineProvider>,
  );
}

const DIGITAL_FILE = { file_id: "f1", name: "deed.pdf", kind: "digital" };
const SCAN_FILE = { file_id: "f2", name: "scan.pdf", kind: "scan" };

const DIGITAL_ESTIMATE = {
  file_id: "f1", name: "deed.pdf", kind: "digital", pages: 1,
  unit_count: 12, unique_count: 10, cache_hits: 2, input_tokens: 500, output_tokens: 500, usd: 0.05,
};
const SCAN_ESTIMATE = {
  file_id: "f2", name: "scan.pdf", kind: "scan", pages: 3,
  unit_count: 0, unique_count: 0, cache_hits: 0, input_tokens: 0, output_tokens: 0, usd: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  cleanNotifications();
  api.health.mockResolvedValue({
    version: "0", backend: "gemini", anthropic_key_present: false, gemini_key_present: false,
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("all files are scans", () => {
  it("shows the honest alert instead of the zeroed-out stat grid, and keeps Translate enabled", async () => {
    api.uploadFile.mockResolvedValueOnce(SCAN_FILE);
    api.estimate.mockResolvedValue([SCAN_ESTIMATE]);

    renderEstimate([SCAN_FILE]);

    expect(await screen.findByText(/every file here is a scan/i)).toBeInTheDocument();
    expect(screen.queryByText("Paragraphs")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /translate 1 document/i })).not.toBeDisabled();
  });
});

describe("mixed digital and scanned files", () => {
  it("keeps the stat grid and adds a line naming how many scanned files are excluded", async () => {
    api.uploadFile
      .mockResolvedValueOnce(DIGITAL_FILE)
      .mockResolvedValueOnce(SCAN_FILE);
    api.estimate.mockResolvedValue([DIGITAL_ESTIMATE, SCAN_ESTIMATE]);

    renderEstimate([DIGITAL_FILE, SCAN_FILE]);

    // findByText (not getByText) because the grid renders immediately
    // with zeros while `estimates` is still [] -- these assertions must
    // wait for the async runEstimate() to actually resolve and update it.
    expect(await screen.findByText("12")).toBeInTheDocument(); // the digital file's own unit_count
    expect(await screen.findByText(/1 scanned file isn't counted above/i)).toBeInTheDocument();
  });
});

describe("all files are digital", () => {
  it("renders the grid with no scan disclosure at all", async () => {
    api.uploadFile.mockResolvedValueOnce(DIGITAL_FILE);
    api.estimate.mockResolvedValue([DIGITAL_ESTIMATE]);

    renderEstimate([DIGITAL_FILE]);

    expect(await screen.findByText("12")).toBeInTheDocument(); // the real unit_count, not the pre-load 0
    expect(screen.queryByText(/scanned file/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/every file here is a scan/i)).not.toBeInTheDocument();
  });
});

describe("job-limit 429 offers a Cancel-and-retry affordance", () => {
  it("shows a Cancel button naming the blocking job, and clicking it cancels then retries", async () => {
    api.uploadFile.mockResolvedValueOnce(DIGITAL_FILE);
    api.estimate.mockResolvedValue([DIGITAL_ESTIMATE]);
    const blockingError = Object.assign(new Error("you already have 1 job(s) in progress -- wait for one to finish"), {
      status: 429, jobId: "blocking-job-1",
    });
    api.createJob
      .mockRejectedValueOnce(blockingError)
      .mockResolvedValueOnce({ job_id: "new-job-1" });
    api.cancelJob.mockResolvedValue({ id: "blocking-job-1", status: "cancelled" });

    renderEstimate([DIGITAL_FILE]);
    await screen.findByText("12"); // grid loaded, Translate is clickable

    fireEvent.click(screen.getByRole("button", { name: /translate 1 document/i }));

    const cancelButton = await screen.findByRole("button", { name: /cancel that job and start this one/i });
    expect(screen.getByText(/you already have 1 job\(s\) in progress/i)).toBeInTheDocument();

    fireEvent.click(cancelButton);

    await screen.findByText("running", { selector: '[data-testid="screen-probe"]' });
    expect(api.cancelJob).toHaveBeenCalledWith("blocking-job-1");
    expect(api.createJob).toHaveBeenCalledTimes(2);
  });
});
