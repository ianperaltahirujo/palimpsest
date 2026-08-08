import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api.js", () => ({
  getEntities: vi.fn(),
  putEntities: vi.fn(),
  health: vi.fn(),
}));

import * as api from "../api.js";
import { theme } from "../theme.js";
import { I18nProvider } from "../i18n.jsx";
import { AppStateProvider } from "../state.jsx";
import Rail from "./Rail.jsx";

function renderRail() {
  return render(
    <MantineProvider theme={theme}>
      <I18nProvider>
        <AppStateProvider>
          <Rail showSuggested onCollapse={() => {}} />
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
  // vite.config.js sets test.globals: false, so @testing-library/react's
  // usual auto-cleanup (which hooks into a GLOBAL afterEach) never
  // registers here -- without this, each test's render accumulates in the
  // document instead of unmounting, and later tests see duplicate nodes
  // from every render before them.
  cleanup();
  vi.restoreAllMocks();
});

describe("real mode: no mock fixtures leak in", () => {
  it("renders no protected-entity chips while GET /api/entities is unreachable", async () => {
    api.getEntities.mockRejectedValue(new Error("could not reach the server"));
    renderRail();

    await waitFor(() => expect(api.getEntities).toHaveBeenCalled());

    expect(screen.queryByText("Grupo Meridian, S.A.S.")).not.toBeInTheDocument();
    expect(screen.queryByText("Banco Litoral, S.A.")).not.toBeInTheDocument();
    expect(screen.queryByText("Andres Carreno")).not.toBeInTheDocument();
  });

  it("shows a 0 count, not the fixture's 3, before the server answers", async () => {
    api.getEntities.mockRejectedValue(new Error("could not reach the server"));
    renderRail();

    await waitFor(() => expect(api.getEntities).toHaveBeenCalled());

    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("never shows the suggested-entities fixture chips", async () => {
    api.getEntities.mockRejectedValue(new Error("could not reach the server"));
    renderRail();

    await waitFor(() => expect(api.getEntities).toHaveBeenCalled());

    expect(screen.queryByText(/Fideicomiso Aurora Plaza/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Lucia Fernandez Roa/)).not.toBeInTheDocument();
  });

  it("replaces the empty state with the real roster once the server answers", async () => {
    api.getEntities.mockResolvedValue({
      companies: ["Real Company Inc."], people: [], places: [], other: [],
    });
    renderRail();

    expect(await screen.findByText("Real Company Inc.")).toBeInTheDocument();
  });
});
