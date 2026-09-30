import { afterEach, describe, expect, it, vi } from "vitest";
import { fmtDuration, relTime } from "./format";

describe("fmtDuration", () => {
  it("空值 → 占位符", () => {
    expect(fmtDuration(null)).toBe("—");
    expect(fmtDuration(undefined)).toBe("—");
  });

  it("秒级四舍五入（<60）", () => {
    expect(fmtDuration(0)).toBe("0 秒");
    expect(fmtDuration(44.6)).toBe("45 秒");
    expect(fmtDuration(59.4)).toBe("59 秒");
  });

  it("分钟级取整（60 ≤ s < 3600）", () => {
    expect(fmtDuration(60)).toBe("1 分钟");
    expect(fmtDuration(119)).toBe("1 分钟");
    expect(fmtDuration(3599)).toBe("59 分钟");
  });

  it("小时+分钟拼接（≥3600）", () => {
    expect(fmtDuration(3600)).toBe("1 时 0 分");
    expect(fmtDuration(7500)).toBe("2 时 5 分");
  });
});

describe("relTime", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("空值/0 → 占位符", () => {
    expect(relTime(null)).toBe("—");
    expect(relTime(undefined)).toBe("—");
    expect(relTime(0)).toBe("—");
  });

  it("近期 → X 秒前", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-30T12:00:00Z"));
    const now = Date.now() / 1000;
    expect(relTime(now - 30)).toBe("30 秒前");
  });

  it("超过一分钟 → 复用 fmtDuration + 前", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-30T12:00:00Z"));
    const now = Date.now() / 1000;
    expect(relTime(now - 90)).toBe("1 分钟前");
    expect(relTime(now - 7500)).toBe("2 时 5 分前");
  });

  it("未来时间戳 → 钳制为 0（现状行为固化; 文档声称 — 与此不符，见注释）", () => {
    // 注意: 函数注释称"未来 → —"，实际实现 Math.max(0, ...) 钳制为 0 → "0 秒前"。
    // 此处固化实际行为；如需改为 — 需同时更新函数注释。
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-30T12:00:00Z"));
    const now = Date.now() / 1000;
    expect(relTime(now + 100)).toBe("0 秒前");
  });
});
