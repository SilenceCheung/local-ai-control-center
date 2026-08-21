import { describe, expect, it } from "vitest";
import { formatMsg, resolveLang } from "./catalog";

describe("i18n resolve", () => {
  it("honors explicit English", () => {
    expect(resolveLang("en", "zh-CN")).toBe("en");
  });
  it("honors explicit Chinese", () => {
    expect(resolveLang("zh-Hans", "en-US")).toBe("zh-Hans");
  });
  it("maps system + zh navigator to zh-Hans", () => {
    expect(resolveLang("system", "zh-CN")).toBe("zh-Hans");
    expect(resolveLang("system", "zh-Hans")).toBe("zh-Hans");
    expect(resolveLang("system", "zh-TW")).toBe("zh-Hans");
  });
  it("maps system + English navigator to en", () => {
    expect(resolveLang("system", "en-US")).toBe("en");
  });
  it("interpolates placeholders", () => {
    expect(formatMsg("Installed ({n})", { n: 4 })).toBe("Installed (4)");
  });
});
