/**
 * runDetectEnv 单元测试（bun:test）。
 *
 * 测试 buildDetectEnvArgs 和 interpretDetectEnvResult 两个纯函数。
 * runDetectEnv 本身是薄包装（spawn IPC），业务逻辑全在这两个纯函数里。
 *
 * 运行: bun test test/runDetectEnv/
 */
import { test, expect, describe } from "bun:test";
import {
  buildDetectEnvArgs,
  interpretDetectEnvResult,
} from "../../.opencode/plugins/lib/env-check";
import { AGENT_SECURITY_COORDINATOR } from "../../.opencode/plugins/lib/constants";
import type { ProcessResult } from "../../.opencode/plugins/lib/spawn";

/** 构造 ProcessResult 测试数据 */
function makeResult(overrides: Partial<ProcessResult> = {}): ProcessResult {
  return {
    status: 0,
    signal: null,
    stdout: "",
    stderr: "",
    error: null,
    ...overrides,
  };
}

// ─── buildDetectEnvArgs ────────────────────────────────────────────

describe("buildDetectEnvArgs", () => {
  test("非 Coordinator agent → --check-preinstall <agent>", () => {
    const args = buildDetectEnvArgs("binary-analysis", null);
    expect(args).toEqual(["--check-preinstall", "binary-analysis"]);
  });

  test("Coordinator → --check-preinstall all", () => {
    const args = buildDetectEnvArgs(AGENT_SECURITY_COORDINATOR, null);
    expect(args).toEqual(["--check-preinstall", "all"]);
  });

  test("有 taskDir → 追加 --output <taskDir>/env.json", () => {
    const args = buildDetectEnvArgs("binary-analysis", "/path/to/task");
    expect(args).toEqual([
      "--check-preinstall", "binary-analysis",
      "--output", "/path/to/task/env.json",
    ]);
  });

  test("无 taskDir → 不含 --output", () => {
    const args = buildDetectEnvArgs("binary-analysis", null);
    expect(args).not.toContain("--output");
  });

  test("Coordinator + taskDir → all + --output", () => {
    const args = buildDetectEnvArgs(AGENT_SECURITY_COORDINATOR, "/task");
    expect(args).toEqual(["--check-preinstall", "all", "--output", "/task/env.json"]);
  });
});

// ─── interpretDetectEnvResult ──────────────────────────────────────

describe("interpretDetectEnvResult — 成功路径", () => {
  test("success=true → ready:true, message 空", () => {
    const r = makeResult({ stdout: '{"success": true}' });
    const result = interpretDetectEnvResult(r, "binary-analysis");
    expect(result.ready).toBe(true);
    expect(result.message).toBe("");
  });
});

describe("interpretDetectEnvResult — 缺包路径", () => {
  test("success=false + errors 含 install_hint 对象 → message 含 hint", () => {
    const r = makeResult({
      stdout: JSON.stringify({
        success: false,
        errors: [{ package: "angr", install_hint: "pip install angr" }],
      }),
    });
    const result = interpretDetectEnvResult(r, "binary-analysis");
    expect(result.ready).toBe(false);
    expect(result.message).toContain("angr");
    expect(result.message).toContain("pip install angr");
    expect(result.message).toContain("装完后重新发送消息");
  });

  test("success=false + errors 含字符串 → message 含该字符串", () => {
    const r = makeResult({
      stdout: JSON.stringify({
        success: false,
        errors: ["C/C++ 编译器未找到。请运行: xcode-select --install"],
      }),
    });
    const result = interpretDetectEnvResult(r, "binary-analysis");
    expect(result.ready).toBe(false);
    expect(result.message).toContain("C/C++ 编译器未找到");
    expect(result.message).toContain("xcode-select");
  });

  test("success=false + 多个 errors → message 含全部 hint（换行分隔）", () => {
    const r = makeResult({
      stdout: JSON.stringify({
        success: false,
        errors: [
          { package: "angr", install_hint: "pip install angr" },
          { package: "ida_pro", install_hint: "IDA Pro 未检测到" },
        ],
      }),
    });
    const result = interpretDetectEnvResult(r, "binary-analysis");
    expect(result.message).toContain("pip install angr");
    expect(result.message).toContain("IDA Pro 未检测到");
  });

  test("success=false + 空 errors → message 含'无 errors'", () => {
    const r = makeResult({
      stdout: JSON.stringify({ success: false, errors: [] }),
    });
    const result = interpretDetectEnvResult(r, "binary-analysis");
    expect(result.ready).toBe(false);
    expect(result.message).toContain("无 errors");
  });

  test("success=false + 无 errors 字段 → message 含'无 errors'", () => {
    const r = makeResult({
      stdout: JSON.stringify({ success: false }),
    });
    const result = interpretDetectEnvResult(r, "binary-analysis");
    expect(result.ready).toBe(false);
    expect(result.message).toContain("无 errors");
  });

  test("stdout 合法 JSON 但缺 success 字段 → 降级为 success=false（'无 errors'）", () => {
    const r = makeResult({
      stdout: JSON.stringify({ foo: "bar" }),
    });
    const result = interpretDetectEnvResult(r, "binary-analysis");
    expect(result.ready).toBe(false);
    expect(result.message).toContain("无 errors");
  });

  test("success=false + error 对象 install_hint 为空 → fallback 到 package 名", () => {
    const r = makeResult({
      stdout: JSON.stringify({
        success: false,
        errors: [{ package: "angr", install_hint: "" }],
      }),
    });
    const result = interpretDetectEnvResult(r, "binary-analysis");
    expect(result.ready).toBe(false);
    expect(result.message).toContain("angr");
    expect(result.message).not.toContain("pip install");  // install_hint 为空，不含安装命令
  });
});

describe("interpretDetectEnvResult — 进程错误路径", () => {
  test("r.error → message 含 error.message + stderr", () => {
    const r = makeResult({
      error: new Error("Bun.spawn 超时（8000ms）"),
      stderr: "[*] 正在检测 angr...\n[+] Python: /path/python",
    });
    const result = interpretDetectEnvResult(r, "binary-analysis");
    expect(result.ready).toBe(false);
    expect(result.message).toContain("Bun.spawn 超时");
    expect(result.message).toContain("正在检测 angr");
    expect(result.message).toContain("检测日志");
  });

  test("r.error + 空 stderr → message 不含'检测日志'", () => {
    const r = makeResult({
      error: new Error("ENOENT: python not found"),
      stderr: "",
    });
    const result = interpretDetectEnvResult(r, "binary-analysis");
    expect(result.ready).toBe(false);
    expect(result.message).toContain("ENOENT");
    expect(result.message).not.toContain("检测日志");
  });
});

describe("interpretDetectEnvResult — JSON 解析失败", () => {
  test("stdout 非合法 JSON → message 含'非合法 JSON' + stderr", () => {
    const r = makeResult({
      stdout: "not a json {{{",
      stderr: "Traceback (most recent call last):\n  File ...",
    });
    const result = interpretDetectEnvResult(r, "binary-analysis");
    expect(result.ready).toBe(false);
    expect(result.message).toContain("非合法 JSON");
    expect(result.message).toContain("Traceback");
  });

  test("stdout 为空 → message 含'非合法 JSON'", () => {
    const r = makeResult({ stdout: "" });
    const result = interpretDetectEnvResult(r, "binary-analysis");
    expect(result.ready).toBe(false);
    expect(result.message).toContain("非合法 JSON");
  });
});

describe("interpretDetectEnvResult — stderr 截断", () => {
  test("stderr 超 300 字符 → 截断到尾部 300", () => {
    const longStderr = "A".repeat(200) + "B".repeat(200); // 400 字符
    const r = makeResult({
      error: new Error("超时"),
      stderr: longStderr,
    });
    const result = interpretDetectEnvResult(r, "binary-analysis");
    expect(result.ready).toBe(false);
    // 尾部 200 个 B 保留
    expect(result.message).toContain("B".repeat(200));
    // 前 200 个 A 被截断（不会出现在尾部 300 里——尾部 300 = 100A + 200B）
    expect(result.message).toContain("A".repeat(100));
    expect(result.message).not.toContain("A".repeat(101));
  });
});
