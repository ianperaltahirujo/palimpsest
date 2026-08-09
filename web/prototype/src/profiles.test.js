import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { deleteProfile, getProfiles, saveProfile } from "./profiles.js";

const GROUPS_A = { companies: ["Acme, S.A."], people: [], places: [], other: [] };
const GROUPS_B = { companies: [], people: ["Andres Carreno"], places: [], other: [] };

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

describe("getProfiles()", () => {
  it("returns an empty array with nothing saved", () => {
    expect(getProfiles()).toEqual([]);
  });

  it("tolerates corrupted localStorage instead of throwing", () => {
    localStorage.setItem("pp-entity-profiles", "{not valid json");
    expect(getProfiles()).toEqual([]);
  });
});

describe("saveProfile()", () => {
  it("round-trips a saved profile", () => {
    saveProfile("Brisas deal", GROUPS_A);
    const [profile] = getProfiles();
    expect(profile.name).toBe("Brisas deal");
    expect(profile.groups).toEqual(GROUPS_A);
    expect(profile.id).toBeTruthy();
    expect(profile.savedAt).toBeTypeOf("number");
  });

  it("keeps distinct names as separate entries", () => {
    saveProfile("Deal A", GROUPS_A);
    saveProfile("Deal B", GROUPS_B);
    expect(getProfiles().map((p) => p.name)).toEqual(["Deal A", "Deal B"]);
  });

  it("overwrites in place when saved again under the same name (edit semantics)", () => {
    saveProfile("Brisas deal", GROUPS_A);
    const firstId = getProfiles()[0].id;

    saveProfile("Brisas deal", GROUPS_B);
    const profiles = getProfiles();
    expect(profiles).toHaveLength(1);
    expect(profiles[0].id).toBe(firstId);
    expect(profiles[0].groups).toEqual(GROUPS_B);
  });

  it("does not save a profile with an empty/whitespace-only name", () => {
    saveProfile("   ", GROUPS_A);
    expect(getProfiles()).toEqual([]);
  });

  it("does not mutate the caller's groups object on later edits", () => {
    saveProfile("Brisas deal", GROUPS_A);
    GROUPS_A.companies.push("Injected, S.A.");
    expect(getProfiles()[0].groups.companies).toEqual(["Acme, S.A."]);
    GROUPS_A.companies.pop(); // restore for other tests sharing this const
  });
});

describe("deleteProfile()", () => {
  it("removes only the matching profile", () => {
    saveProfile("Deal A", GROUPS_A);
    saveProfile("Deal B", GROUPS_B);
    const [a, b] = getProfiles();

    deleteProfile(a.id);
    const remaining = getProfiles();
    expect(remaining).toHaveLength(1);
    expect(remaining[0].id).toBe(b.id);
  });

  it("is a no-op for an unknown id", () => {
    saveProfile("Deal A", GROUPS_A);
    deleteProfile("does-not-exist");
    expect(getProfiles()).toHaveLength(1);
  });
});
