import { cleanup, render, screen } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api.js", () => ({
  health: vi.fn(),
  setKeys: vi.fn(),
  downloadUrl: vi.fn(() => "#"),
  pageUrl: vi.fn(() => "#"),
}));

import * as api from "../api.js";
import { theme } from "../theme.js";
import { I18nProvider } from "../i18n.jsx";
import { AppStateProvider } from "../state.jsx";
import Results from "./Results.jsx";

function renderResults() {
  return render(
    <MantineProvider theme={theme}>
      <I18nProvider>
        <AppStateProvider>
          <Results />
        </AppStateProvider>
      </I18nProvider>
    </MantineProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.health.mockResolvedValue({
    version: "0", backend: "gemini", anthropic_key_present: false, gemini_key_present: false,
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("real mode, no job (e.g. its own GET /api/jobs/{id} fetch failed)", () => {
  it("shows an honest empty state, not summarize(null)'s zeroed-out stats", () => {
    renderResults();

    expect(screen.getByText("No results yet")).toBeInTheDocument();
    // The fake-success reading this replaces:
    expect(screen.queryByText(/of 0 paragraphs translated/)).not.toBeInTheDocument();
    expect(screen.queryByText("Nothing to report -- every paragraph translated cleanly.")).not.toBeInTheDocument();
  });

  it("offers a way back to start a real translation", () => {
    renderResults();
    expect(screen.getByText("New translation")).toBeInTheDocument();
  });
});
