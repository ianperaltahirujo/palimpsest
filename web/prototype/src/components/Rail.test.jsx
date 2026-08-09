import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { cleanNotifications, Notifications } from "@mantine/notifications";
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
        <Notifications />
        <AppStateProvider>
          <Rail showSuggested onCollapse={() => {}} />
        </AppStateProvider>
      </I18nProvider>
    </MantineProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  cleanNotifications();
  localStorage.clear(); // profiles.js's pp-entity-profiles must not leak across tests
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
  localStorage.clear();
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

describe("entity profiles: save, load, delete", () => {
  it("saves the current roster as a named profile, and it appears in the profiles list", async () => {
    api.getEntities.mockResolvedValue({ companies: ["Acme, S.A."], people: [], places: [], other: [] });
    api.putEntities.mockResolvedValue({});
    renderRail();
    await screen.findByText("Acme, S.A.");

    fireEvent.change(screen.getByPlaceholderText("Profile name..."), { target: { value: "Deal A" } });
    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));

    expect(await screen.findByRole("button", { name: /load profile: deal a/i })).toBeInTheDocument();
  });

  it("loading a saved profile replaces the current roster and PUTs it to the server", async () => {
    api.getEntities.mockResolvedValue({ companies: ["Acme, S.A."], people: [], places: [], other: [] });
    api.putEntities.mockResolvedValue({});
    renderRail();
    await screen.findByText("Acme, S.A.");

    fireEvent.change(screen.getByPlaceholderText("Profile name..."), { target: { value: "Deal A" } });
    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
    await screen.findByRole("button", { name: /load profile: deal a/i });

    // Clear the roster (remove the one chip), confirming the profile
    // survives independent of the live roster.
    fireEvent.click(screen.getByLabelText("Remove Acme, S.A."));
    await waitFor(() => expect(screen.queryByText("Acme, S.A.")).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /load profile: deal a/i }));

    expect(await screen.findByText("Acme, S.A.")).toBeInTheDocument();
    await waitFor(() =>
      expect(api.putEntities).toHaveBeenLastCalledWith(
        expect.objectContaining({ companies: ["Acme, S.A."] }),
      ),
    );
  });

  it("deleting a saved profile removes it from the list", async () => {
    api.getEntities.mockResolvedValue({ companies: ["Acme, S.A."], people: [], places: [], other: [] });
    api.putEntities.mockResolvedValue({});
    renderRail();
    await screen.findByText("Acme, S.A.");

    fireEvent.change(screen.getByPlaceholderText("Profile name..."), { target: { value: "Deal A" } });
    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
    await screen.findByRole("button", { name: /load profile: deal a/i });

    fireEvent.click(screen.getByLabelText(/delete profile: deal a/i));

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /load profile: deal a/i })).not.toBeInTheDocument(),
    );
    expect(screen.getByText("No saved profiles yet.")).toBeInTheDocument();
  });
});
