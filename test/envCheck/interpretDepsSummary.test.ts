/**
 * interpretDepsSummary 单元测试（bun:test）。
 *
 * 纯函数：控制台 /api/deps 的 summary → EnvironmentCheckResult（用户可见消息）。
 * 判定语义在服务端收口，本函数只负责消息组装：
 *   ready=true → 放行（optional 缺失不注入，仅 debugLog）
 *   ready=false → 缺失清单 + console_url 引导
 *
 * 运行: bun test test/envCheck/
 */
import { test, expect, describe } from "bun:test";
import { interpretDepsSummary, type DepsSummary } from "../../.opencode/plugins/lib/env-check";

function makeSummary(overrides: Partial<DepsSummary> = {}): DepsSummary {
  return {
    agent: "binary-analysis",
    ready: true,
    required_missing: [],
    optional_missing: [],
    console_url: "http://localhost:9776",
    ...overrides,
  };
}

describe("interpretDepsSummary", () => {
  test("ready=true → 放行，message 为空", () => {
    const r = interpretDepsSummary(makeSummary());
    expect(r.ready).toBe(true);
    expect(r.message).toBe("");
  });

  test("ready=true + optional 缺失 → 仍放行（optional 不拦，用户决策）", () => {
    const r = interpretDepsSummary(makeSummary({
      optional_missing: ["GoReSym", "glm-ocr"],
    }));
    expect(r.ready).toBe(true);
    expect(r.message).toBe("");
  });

  test("ready=false → 终止 + 缺失清单 + 控制台链接", () => {
    const r = interpretDepsSummary(makeSummary({
      ready: false,
      required_missing: ["angr", "z3"],
    }));
    expect(r.ready).toBe(false);
    expect(r.message).toContain("缺失必需依赖 2 项");
    expect(r.message).toContain("angr、z3");
    expect(r.message).toContain("http://localhost:9776");
    expect(r.message).toContain("修复完成后重新发送消息");
  });

  test("required_missing 为空数组时 join 不炸", () => {
    const r = interpretDepsSummary(makeSummary({
      ready: false,
      required_missing: [],
    }));
    expect(r.ready).toBe(false);
    expect(r.message).toContain("缺失必需依赖 0 项");
  });

  test("undefined 数组字段容错（服务端契约防御）", () => {
    const s = makeSummary({ ready: false, required_missing: undefined as unknown as string[] });
    const r = interpretDepsSummary(s);
    expect(r.ready).toBe(false);
  });
});

// ─── 第一层：interpretScanExit（CLI 自举检查） ──────────────

import { interpretScanExit } from "../../.opencode/plugins/lib/env-check";

describe("interpretScanExit", () => {
  test("exit 0 → 放行", () => {
    const r = interpretScanExit(0, "[+] fastapi  0.1  x");
    expect(r.ready).toBe(true);
    expect(r.message).toBe("");
  });

  test("exit 1 + 缺失清单 → install.sh 提示 + 缺失包名", () => {
    const r = interpretScanExit(1, "[+] fastapi  x\n[-] angr   ?  desc\n[-] z3  ?  d\n");
    expect(r.ready).toBe(false);
    expect(r.message).toContain("install.sh");
    expect(r.message).toContain("angr、z3");
  });

  test("exit 1 但 stdout 无缺失行 → install.sh 提示（通用，不炸）", () => {
    const r = interpretScanExit(1, "");
    expect(r.ready).toBe(false);
    expect(r.message).toContain("install.sh");
  });

  test("status null（spawn 失败）→ 拦截并报故障（fail-closed，不静默放行）", () => {
    const r = interpretScanExit(null, "", "ENOENT: no such file or directory");
    expect(r.ready).toBe(false);
    expect(r.message).toContain("环境自举检查故障");
    expect(r.message).toContain("ENOENT");
    expect(r.message).toContain("install.sh");
  });

  test("异常退出码 2 → 拦截并报故障码", () => {
    const r = interpretScanExit(2, "");
    expect(r.ready).toBe(false);
    expect(r.message).toContain("exit 2");
  });
});
