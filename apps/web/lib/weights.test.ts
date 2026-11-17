import { describe, expect, it } from "vitest";
import { setWeight, total } from "./weights";

const DEFAULT = { role: 20, exp: 15, core: 15, cloud: 10, ai: 10, domain: 10, loc: 10, skills: 5, comp: 5 };

describe("setWeight", () => {
  it("keeps the total at 100 when raising a factor", () => {
    const w = setWeight(DEFAULT, "ai", 30);
    expect(w.ai).toBe(30);
    expect(total(w)).toBe(100);
  });

  it("keeps the total at 100 when lowering a factor", () => {
    const w = setWeight(DEFAULT, "role", 0);
    expect(w.role).toBe(0);
    expect(total(w)).toBe(100);
  });

  it("clamps to 0..60 and never produces negatives", () => {
    const w = setWeight(DEFAULT, "role", 95);
    expect(w.role).toBe(60);
    expect(total(w)).toBe(100);
    expect(Object.values(w).every((v) => v >= 0 && v <= 60)).toBe(true);
  });

  it("works through many random edits", () => {
    let w: Record<string, number> = { ...DEFAULT };
    const keys = Object.keys(w);
    for (let i = 0; i < 500; i++) {
      w = setWeight(w, keys[i % keys.length]!, (i * 37) % 61);
      expect(total(w)).toBe(100);
    }
  });
});
