import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api.js", () => ({
  health: vi.fn(),
  setKeys: vi.fn(),
  getEntities: vi.fn(),
  putEntities: vi.fn(),
}));

import * as api from "./api.js";
import { theme } from "./theme.js";
import { I18nProvider } from "./i18n.jsx";
import App, { serveCommand } from "./App.jsx";

beforeEach(() => {
  vi.clearAllMocks();
  api.getEntities.mockResolvedValue({ companies: [], people: [], places: [], other: [] });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("serveCommand()", () => {
  afterEach(() => {
    localStorage.clear();
  });

  it("omits --allow-origin when the API base is same-origin (relative)", () => {
    // config.js's getApiBase() returns "" for same-origin builds --
    // exercised here via the real module (no mock), same-origin means
    // no VITE_STANDALONE/localStorage override is in play, which is the
    // default in this test environment.
    expect(serveCommand()).toBe("palimpsest serve");
  });

  it("names this page's exact origin when the API base is genuinely cross-origin", () => {
    // config.js's setApiBase() persists to the same "pp-api-base"
    // localStorage key getApiBase() reads -- this is exactly the
    // standalone/GitHub Pages scenario (config.js's VITE_STANDALONE).
    localStorage.setItem("pp-api-base", "http://127.0.0.1:8765");
    expect(serveCommand()).toBe(`palimpsest serve --allow-origin ${window.location.origin}`);
  });
});

describe("global unreachable banner", () => {
  function renderApp() {
    return render(
      <MantineProvider theme={theme}>
        <I18nProvider>
          <Notifications />
          <App />
        </I18nProvider>
      </MantineProvider>,
    );
  }

  it("appears on load when the health probe fails, with no user action needed", async () => {
    api.health.mockRejectedValue(new Error("could not reach the server"));
    renderApp();

    expect(await screen.findByText("Couldn't reach the server")).toBeInTheDocument();
  });

  it("does not appear once the server is reachable", async () => {
    api.health.mockResolvedValue({
      version: "0", backend: "gemini", anthropic_key_present: false, gemini_key_present: false,
    });
    renderApp();

    await waitFor(() => expect(api.health).toHaveBeenCalled());
    expect(screen.queryByText("Couldn't reach the server")).not.toBeInTheDocument();
  });
});
