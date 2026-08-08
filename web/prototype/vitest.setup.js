import "@testing-library/jest-dom/vitest";

// React 19 moved `act` into the `react` package itself and gates it on
// this global rather than detecting a test renderer automatically --
// without it, every `act(...)` call under Vitest warns that the
// environment "is not configured to support act(...)" even though the
// act call itself works fine.
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
