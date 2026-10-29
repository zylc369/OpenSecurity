/**
 * 反思配置读取 fail-safe 语义测试（服务端生效值消费方）。
 *
 * 覆盖: isReflectEnabled / getReflectIntervalMs 的三态语义——
 * 生效值启用/禁用、缺失→fail-safe 不启用（间隔→Infinity 永不到期）、
 * 多次调用稳定。
 *
 * 运行: OPENSECURITY_HOME=/tmp/perm_timeout_test bun .opencode/plugins/tests/test-reflection-config.ts
 */
import {
  isReflectEnabled,
  getReflectIntervalMs,
} from "../lib/reflection";

// ── 沙箱防污染保护（同 test-control.ts 模式）──
if (
  !process.env.OPENSECURITY_HOME ||
  process.env.OPENSECURITY_HOME.includes("bw-security-analysis")
) {
  console.error(
    "✗ 危险：未设置沙箱 OPENSECURITY_HOME。请用：OPENSECURITY_HOME=/tmp/perm_timeout_test bun .opencode/plugins/tests/test-reflection-config.ts",
  );
  process.exit(1);
}

let _passed = 0;
let _failed = 0;
const _failures: string[] = [];

function assertEq<T>(actual: T, expected: T, msg: string): void {
  if (actual !== expected) {
    throw new Error(
      `${msg}: actual=${JSON.stringify(actual)}, expected=${JSON.stringify(expected)}`,
    );
  }
}

async function test(
  name: string,
  fn: () => Promise<void> | void,
): Promise<void> {
  try {
    await fn();
    _passed++;
    console.log(`  ✓ ${name}`);
  } catch (e) {
    _failed++;
    _failures.push(`${name}: ${(e as Error)?.message}`);
    console.log(`  ✗ ${name}: ${(e as Error)?.message}`);
  }
}

const readerOf = (vals: Record<string, string>) => () => vals;

async function main(): Promise<void> {
  console.log("test-reflection-config: 反思配置 fail-safe 语义\n");

  await test("isReflectEnabled: 三态 fail-safe", () => {
    assertEq(
      isReflectEnabled(readerOf({ REFLECT_NUDGE_ENABLED: "1" })),
      true,
      "1=启用",
    );
    assertEq(
      isReflectEnabled(readerOf({ REFLECT_NUDGE_ENABLED: "true" })),
      true,
      "true=启用",
    );
    assertEq(
      isReflectEnabled(readerOf({ REFLECT_NUDGE_ENABLED: "任意非禁用值" })),
      true,
      "非 0/false 值=启用",
    );
    assertEq(
      isReflectEnabled(readerOf({ REFLECT_NUDGE_ENABLED: "0" })),
      false,
      "0=禁用",
    );
    assertEq(
      isReflectEnabled(readerOf({ REFLECT_NUDGE_ENABLED: "FALSE" })),
      false,
      "false（大小写不敏感）=禁用",
    );
    assertEq(
      isReflectEnabled(readerOf({})),
      false,
      "缺失=不启用（fail-safe，默认值唯一权威在服务端）",
    );
    assertEq(
      isReflectEnabled(readerOf({ REFLECT_NUDGE_ENABLED: "" })),
      false,
      "空串=不启用",
    );
    // 多次调用稳定（once 日志节流不影响返回值）
    assertEq(isReflectEnabled(readerOf({})), false, "多次缺失稳定 false");
  });

  await test("getReflectIntervalMs: 生效值/缺失与非法 Infinity", () => {
    assertEq(
      getReflectIntervalMs(readerOf({ REFLECT_NUDGE_INTERVAL_MIN: "30" })),
      1_800_000,
      "30 分钟",
    );
    assertEq(
      getReflectIntervalMs(readerOf({ REFLECT_NUDGE_INTERVAL_MIN: "0.5" })),
      30_000,
      "小数分钟",
    );
    assertEq(
      getReflectIntervalMs(readerOf({})),
      Number.POSITIVE_INFINITY,
      "缺失→Infinity 永不到期（两通道不注入）",
    );
    assertEq(
      getReflectIntervalMs(readerOf({ REFLECT_NUDGE_INTERVAL_MIN: "abc" })),
      Number.POSITIVE_INFINITY,
      "非法→Infinity",
    );
    assertEq(
      getReflectIntervalMs(readerOf({ REFLECT_NUDGE_INTERVAL_MIN: "0" })),
      Number.POSITIVE_INFINITY,
      "0→Infinity",
    );
    assertEq(
      getReflectIntervalMs(readerOf({ REFLECT_NUDGE_INTERVAL_MIN: "-5" })),
      Number.POSITIVE_INFINITY,
      "负数→Infinity",
    );
  });

  console.log(`\n通过 ${_passed} / 失败 ${_failed} / 总计 ${_passed + _failed}`);
  if (_failed > 0) {
    console.log("失败用例:\n" + _failures.join("\n"));
    process.exit(1);
  }
}

await main();
