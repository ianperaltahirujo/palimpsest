import { act } from "react";
import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api.js", () => ({
  uploadFile: vi.fn(),
  estimate: vi.fn(),
  createJob: vi.fn(),
}));

import * as api from "./api.js";
import { AppStateProvider, useAppState } from "./state.jsx";

function renderAppState() {
  return renderHook(() => useAppState(), { wrapper: AppStateProvider });
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("goto()", () => {
  it("defaults to the overview screen", () => {
    const { result } = renderAppState();
    expect(result.current.screen).toBe("overview");
  });

  it("switches screens and closes any open compare view", () => {
    const { result } = renderAppState();
    act(() => result.current.openCompare(2));
    expect(result.current.compareOpen).toBe(true);

    act(() => result.current.goto("queue"));
    expect(result.current.screen).toBe("queue");
    expect(result.current.compareOpen).toBe(false);
  });

  it("only sets runAnimated when navigating to running WITH animate:true", () => {
    // goto() only touches runAnimated on its way TO "running" -- it's
    // read exclusively by Running.jsx, so leaving it stale while any
    // other screen is active is harmless by construction, not a bug.
    const { result } = renderAppState();

    act(() => result.current.goto("running"));
    expect(result.current.runAnimated).toBe(false);

    act(() => result.current.goto("running", { animate: true }));
    expect(result.current.runAnimated).toBe(true);

    // re-entering running WITHOUT animate:true resets it back to false
    act(() => result.current.goto("estimate"));
    act(() => result.current.goto("running"));
    expect(result.current.runAnimated).toBe(false);
  });
});

describe("openCompare()/closeCompare()", () => {
  it("stores the requested page and opens the overlay", () => {
    const { result } = renderAppState();
    act(() => result.current.openCompare(3));
    expect(result.current.compareOpen).toBe(true);
    expect(result.current.comparePage).toBe(3);

    act(() => result.current.closeCompare());
    expect(result.current.compareOpen).toBe(false);
  });
});

describe("real-mode upload/job state", () => {
  it("addUploads appends the server's response to the uploads list", async () => {
    api.uploadFile.mockResolvedValue({ file_id: "f1", name: "a.pdf", kind: "digital", pages: 1, size: 100 });
    const { result } = renderAppState();

    await act(async () => {
      await result.current.addUploads([{ name: "a.pdf" }]);
    });

    expect(result.current.uploads).toEqual([
      { file_id: "f1", name: "a.pdf", kind: "digital", pages: 1, size: 100 },
    ]);
  });

  it("addUploads surfaces a failure via apiError and rethrows for the caller", async () => {
    const error = new Error("could not reach the server");
    api.uploadFile.mockRejectedValue(error);
    const { result } = renderAppState();

    let thrown = null;
    await act(async () => {
      try {
        await result.current.addUploads([{ name: "a.pdf" }]);
      } catch (e) {
        thrown = e;
      }
    });

    expect(thrown).toBe(error);
    expect(result.current.apiError).toBe(error);
    expect(result.current.uploads).toEqual([]); // failed upload never lands in state
  });

  it("removeUpload drops both the upload and its matching estimate", async () => {
    api.uploadFile.mockResolvedValue({ file_id: "f1", name: "a.pdf", kind: "digital", pages: 1, size: 100 });
    api.estimate.mockResolvedValue([{ file_id: "f1", unit_count: 1, unique_count: 1, cache_hits: 0 }]);
    const { result } = renderAppState();

    await act(async () => {
      await result.current.addUploads([{ name: "a.pdf" }]);
    });
    await act(async () => {
      await result.current.runEstimate();
    });
    expect(result.current.uploads).toHaveLength(1);
    expect(result.current.estimates).toHaveLength(1);

    act(() => result.current.removeUpload("f1"));
    expect(result.current.uploads).toHaveLength(0);
    expect(result.current.estimates).toHaveLength(0);
  });

  it("startJob passes the selected backend through to createJob", async () => {
    api.uploadFile.mockResolvedValue({ file_id: "f1", name: "a.pdf", kind: "digital", pages: 1, size: 100 });
    api.createJob.mockResolvedValue({ job_id: "job1" });
    const { result } = renderAppState();

    await act(async () => {
      await result.current.addUploads([{ name: "a.pdf" }]);
    });
    act(() => result.current.setSelectedBackend("anthropic"));
    await act(async () => {
      await result.current.startJob({ dual: true });
    });

    expect(api.createJob).toHaveBeenCalledWith(["f1"], { backend: "anthropic", dual: true });
    expect(result.current.jobId).toBe("job1");
  });

  it("resetPipeline clears uploads, estimates, and the job", async () => {
    api.uploadFile.mockResolvedValue({ file_id: "f1", name: "a.pdf", kind: "digital", pages: 1, size: 100 });
    api.createJob.mockResolvedValue({ job_id: "job1" });
    const { result } = renderAppState();

    await act(async () => {
      await result.current.addUploads([{ name: "a.pdf" }]);
    });
    await act(async () => {
      await result.current.startJob({});
    });

    act(() => result.current.resetPipeline());
    expect(result.current.uploads).toEqual([]);
    expect(result.current.estimates).toEqual([]);
    expect(result.current.jobId).toBeNull();
    expect(result.current.job).toBeNull();
  });
});
