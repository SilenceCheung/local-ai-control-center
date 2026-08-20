import { describe, expect, it } from "vitest";
import { fmtBytes, fmtNum, fmtPct, fmtUptime } from "./ui";

describe("formatters", () => {
  it("fmtBytes", () => {
    expect(fmtBytes(28_600_000_000)).toBe("28.6 GB");
    expect(fmtBytes(3_500_000)).toBe("4 MB");
    expect(fmtBytes(null)).toBe("—");
    expect(fmtBytes(0)).toBe("—");
  });

  it("fmtNum handles missing values honestly", () => {
    expect(fmtNum(27.53, 1)).toBe("27.5");
    expect(fmtNum(undefined)).toBe("—");
    expect(fmtNum(NaN)).toBe("—");
  });

  it("fmtPct", () => {
    expect(fmtPct(0.682)).toBe("68.2%");
    expect(fmtPct(null)).toBe("—");
  });

  it("fmtUptime", () => {
    expect(fmtUptime(42)).toBe("42s");
    expect(fmtUptime(125)).toBe("2m 5s");
    expect(fmtUptime(7261)).toBe("2h 1m");
    expect(fmtUptime(null)).toBe("—");
  });
});
