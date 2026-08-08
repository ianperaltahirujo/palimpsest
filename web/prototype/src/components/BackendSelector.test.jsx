import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api.js", () => ({
  health: vi.fn(),
  setKeys: vi.fn(),
}));

import * as api from "../api.js";
import { theme } from "../theme.js";
import { I18nProvider } from "../i18n.jsx";
import { AppStateProvider } from "../state.jsx";
import BackendSelector from "./BackendSelector.jsx";

function renderSelector() {
  return render(
    <MantineProvider theme={theme}>
      <I18nProvider>
        <AppStateProvider>
          <BackendSelector />
        </AppStateProvider>
      </I18nProvider>
    </MantineProvider>,
  );
}

function selectClaude() {
  fireEvent.click(screen.getByText("claude"));
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("key box: always visible and usable, never gated on reachability", () => {
  it("shows an entry form (not a blocked/error state) when the server is unreachable", async () => {
    api.health.mockRejectedValue(new Error("could not reach the server"));
    renderSelector();
    selectClaude();

    await waitFor(() => expect(api.health).toHaveBeenCalled());

    expect(screen.getByLabelText("API key")).toBeInTheDocument();
  });

  it("shows an entry form immediately, before the health probe even resolves", () => {
    api.health.mockReturnValue(new Promise(() => {})); // never resolves
    renderSelector();
    selectClaude();

    expect(screen.getByLabelText("API key")).toBeInTheDocument();
  });

  it("shows 'detected' + change link once the server confirms the key is present", async () => {
    api.health.mockResolvedValue({
      version: "0", backend: "gemini", anthropic_key_present: true, gemini_key_present: false,
    });
    renderSelector();
    selectClaude();

    expect(await screen.findByText("detected")).toBeInTheDocument();
    expect(screen.getByText("change API key")).toBeInTheDocument();
  });

  it("hides the key's visibility again after Save, even if it was revealed before submitting", async () => {
    api.health.mockRejectedValue(new Error("could not reach the server"));
    renderSelector();
    selectClaude();
    await waitFor(() => expect(api.health).toHaveBeenCalled());

    const input = screen.getByLabelText("API key");
    fireEvent.change(input, { target: { value: "sk-ant-test" } });
    // Mantine's visibility toggle fires on mousedown, not click.
    fireEvent.mouseDown(screen.getByRole("button", { name: "Toggle password visibility" }));
    expect(input).toHaveAttribute("type", "text");

    fireEvent.click(screen.getByText("Save"));
    await screen.findByText("forget saved key");

    // Reopen the entry form (e.g. to change the key) and confirm it comes
    // back hidden -- the visibility toggle must not still be "on" from
    // before the previous save.
    fireEvent.click(screen.getByText("change API key"));
    expect(screen.getByLabelText("API key")).toHaveAttribute("type", "password");
  });

  it("shows the cached-locally message (with change/forget) while the server stays unreachable", async () => {
    // Genuinely unreachable (rejects), not just "reachable but key
    // absent" -- the latter triggers refreshHealth()'s own auto-push
    // (below), which would race this straight to "detected" instead of
    // staying in the cached-but-unconfirmed state this test targets.
    api.health.mockRejectedValue(new Error("could not reach the server"));
    renderSelector();
    selectClaude();
    await waitFor(() => expect(api.health).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "sk-ant-test" } });
    fireEvent.click(screen.getByText("Save"));

    expect(await screen.findByText(/Saved in this browser/)).toBeInTheDocument();
    expect(screen.getByText("forget saved key")).toBeInTheDocument();
    expect(localStorage.getItem("pp-key-anthropic")).toBe("sk-ant-test");
  });

  it("forget saved key clears the cache and returns to the entry form", async () => {
    api.health.mockRejectedValue(new Error("could not reach the server"));
    renderSelector();
    selectClaude();
    await waitFor(() => expect(api.health).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "sk-ant-test" } });
    fireEvent.click(screen.getByText("Save"));
    await screen.findByText("forget saved key");

    fireEvent.click(screen.getByText("forget saved key"));

    expect(localStorage.getItem("pp-key-anthropic")).toBeNull();
    expect(screen.getByLabelText("API key")).toBeInTheDocument();
  });

  it("saving while a server is reachable auto-pushes the cached key via the next health probe", async () => {
    api.health.mockResolvedValue({
      version: "0", backend: "gemini", anthropic_key_present: false, gemini_key_present: false,
    });
    api.setKeys.mockResolvedValue({
      version: "0", backend: "gemini", anthropic_key_present: true, gemini_key_present: false,
    });
    renderSelector();
    selectClaude();
    await waitFor(() => expect(api.health).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "sk-ant-test" } });
    fireEvent.click(screen.getByText("Save"));

    // submitEntryKey() itself never calls setKeys -- it caches, then
    // calls refreshHealth(), whose OWN auto-push (state.jsx) is what
    // actually sends it, avoiding two separate push code paths to keep
    // in sync.
    await waitFor(() =>
      expect(api.setKeys).toHaveBeenCalledWith({ anthropic_api_key: "sk-ant-test" }),
    );
    expect(await screen.findByText("detected")).toBeInTheDocument();
  });
});
