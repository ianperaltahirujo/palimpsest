import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearCachedKey, getCachedKey, setCachedKey } from "./keys.js";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

describe("getCachedKey()/setCachedKey()/clearCachedKey()", () => {
  it("returns null for a backend with nothing cached", () => {
    expect(getCachedKey("anthropic")).toBeNull();
  });

  it("round-trips a value through set/get", () => {
    setCachedKey("anthropic", "sk-ant-test");
    expect(getCachedKey("anthropic")).toBe("sk-ant-test");
  });

  it("keeps each backend's cache independent", () => {
    setCachedKey("anthropic", "sk-ant-test");
    setCachedKey("gemini", "AIza-test");
    expect(getCachedKey("anthropic")).toBe("sk-ant-test");
    expect(getCachedKey("gemini")).toBe("AIza-test");
  });

  it("clearCachedKey removes only that backend's value", () => {
    setCachedKey("anthropic", "sk-ant-test");
    setCachedKey("gemini", "AIza-test");
    clearCachedKey("anthropic");
    expect(getCachedKey("anthropic")).toBeNull();
    expect(getCachedKey("gemini")).toBe("AIza-test");
  });

  it("setCachedKey with an empty value clears instead of storing an empty string", () => {
    setCachedKey("anthropic", "sk-ant-test");
    setCachedKey("anthropic", "");
    expect(getCachedKey("anthropic")).toBeNull();
  });
});
