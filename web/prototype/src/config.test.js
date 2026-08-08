import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { getApiBase, setApiBase } from "./config.js";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

describe("getApiBase()/setApiBase()", () => {
  it("defaults to the built-in value (empty, i.e. same-origin) with nothing set", () => {
    expect(getApiBase()).toBe("");
  });

  it("returns whatever was saved via setApiBase()", () => {
    setApiBase("http://127.0.0.1:9000");
    expect(getApiBase()).toBe("http://127.0.0.1:9000");
  });

  it("persists across calls -- backed by localStorage, not in-memory state", () => {
    setApiBase("http://localhost:8765");
    expect(localStorage.getItem("pp-api-base")).toBe("http://localhost:8765");
  });

  it("an empty value clears back to the built-in default rather than becoming a literal empty base", () => {
    setApiBase("http://127.0.0.1:9000");
    setApiBase("");
    expect(getApiBase()).toBe("");
    expect(localStorage.getItem("pp-api-base")).toBeNull();
  });
});
