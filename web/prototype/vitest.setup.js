import "@testing-library/jest-dom/vitest";

// React 19 moved `act` into the `react` package itself and gates it on
// this global rather than detecting a test renderer automatically --
// without it, every `act(...)` call under Vitest warns that the
// environment "is not configured to support act(...)" even though the
// act call itself works fine.
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// jsdom has no matchMedia implementation at all -- Mantine's MantineProvider
// calls it on mount to resolve the color scheme (dark/light/auto), so any
// test that renders a real component tree (not just renderHook) throws
// "window.matchMedia is not a function" without this. Minimal stub: no
// query ever matches, no listeners ever fire -- tests that care about a
// specific color scheme should pass defaultColorScheme explicitly instead
// of relying on this to report anything meaningful.
window.matchMedia ??= (query) => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: () => {},
  removeListener: () => {},
  addEventListener: () => {},
  removeEventListener: () => {},
  dispatchEvent: () => false,
});

// jsdom also has no ResizeObserver -- Mantine's ScrollArea (AppShell.Navbar/
// Main use it) calls `new ResizeObserver(...)` on mount. No test here reads
// observed sizes, so a no-op stub is enough.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
