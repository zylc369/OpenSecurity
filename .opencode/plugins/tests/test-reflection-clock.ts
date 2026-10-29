/**
 * 反思时钟空闲扣除（活跃时长口径）测试。
 *
 * 覆盖: SessionData 空闲窗口状态机（markIdle / settleIdle / activeMsSinceReflection）
 * 与反思判定/发射的净活跃口径（isReflectionDue / markReflectionFired）。
 *
 * 运行: OPENSECURITY_HOME=/tmp/reflection_clock_test bun .opencode/plugins/tests/test-reflection-clock.ts
 */
import { SessionData } from "../lib/session-manager";
import {
  isReflectionDue,
  markReflectionFired,
  activeMinutesSinceReflection,
} from "../lib/reflection";

// ── 沙箱防污染保护（同 test-reflection-config.ts 模式）──
if (
  !process.env.OPENSECURITY_HOME ||
  process.env.OPENSECURITY_HOME.includes("bw-security-analysis")
) {
  console.error(
    "✗ 危险：未设置沙箱 OPENSECURITY_HOME。请用：OPENSECURITY_HOME=/tmp/reflection_clock_test bun .opencode/plugins/tests/test-reflection-clock.ts",
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

function assertTrue(cond: boolean, msg: string): void {
  if (!cond) {
    throw new Error(msg);
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

/** 构造独立测试会话（不落任何持久化） */
function newSession(): SessionData {
  return new SessionData("flow-test", "web-analysis", "ses_test", "ses_test");
}

async function main(): Promise<void> {
  console.log("test-reflection-clock: 反思时钟空闲扣除（活跃时长口径）\n");

  await test("T1 出生即空闲：创建→首次使用整体计入；立即结算 ≈0", () => {
    const s = newSession();
    assertTrue(s.idleAt !== null, "新建会话应为空闲窗口开启状态（出生即空闲）");
    const d0 = s.settleIdle(Date.now());
    assertTrue(d0 < 1000, `消息内首次创建立即结算应 ≈0，实际 ${d0}ms`);
    assertEq(s.totalIdleMs, d0, "总计同步累加");
    // 显式对齐创建时刻，验证"创建→首次使用 5min 整体计入"
    const s2 = newSession();
    s2.idleAt = s2.createdAt;
    const d1 = s2.settleIdle(s2.createdAt + 300_000);
    assertEq(d1, 300_000, "创建→首次使用 5min 应整体计入空闲");
    assertEq(s2.idleSinceReflectionMs, 300_000, "反思批次累加器同步");
  });

  await test("T2 markIdle 幂等保留最早；settleIdle 累计+关闭+幂等", () => {
    const s = newSession();
    s.settleIdle(); // 清掉出生窗口
    s.markIdle(1_000);
    s.markIdle(2_000); // 不覆盖
    assertEq(s.idleAt, 1_000, "保留最早起点");
    const before = s.totalIdleMs;
    const d = s.settleIdle(61_000);
    assertEq(d, 60_000, "窗口时长");
    assertEq(s.idleAt, null, "窗口已关闭");
    assertEq(s.totalIdleMs, before + 60_000, "总计累加");
    assertEq(s.settleIdle(999_999), 0, "未开窗结算=0（幂等）");
    assertEq(s.totalIdleMs, before + 60_000, "幂等调用不改变计数");
  });

  await test("T3 activeMsSinceReflection 三态（无空闲/已结算扣除/开放窗口不参与）", () => {
    const s = newSession();
    s.lastReflectionAt = 1_000_000;
    s.idleAt = null;
    s.idleSinceReflectionMs = 0;
    assertEq(
      s.activeMsSinceReflection(1_600_000),
      600_000,
      "无空闲：= 墙钟跨度",
    );
    s.idleSinceReflectionMs = 300_000;
    assertEq(
      s.activeMsSinceReflection(1_600_000),
      300_000,
      "已结算空闲扣除",
    );
    s.idleAt = 1_500_000;
    assertEq(
      s.activeMsSinceReflection(1_600_000),
      300_000,
      "开放窗口不参与扣减（仅已结算空闲）",
    );
  });

  await test("T4 开窗/结算日志冒烟（沙箱下不抛异常）", () => {
    const s = newSession();
    s.settleIdle(); // 出生窗口（≈0，不触发日志分支）
    s.markIdle(Date.now() - 120_000); // 2min 窗口 → 结算触发日志分支
    const d = s.settleIdle();
    assertTrue(d >= 119_000, `≈2min 窗口，实际 ${d}ms`);
  });

  await test("T5 isReflectionDue 边界（净活跃 29.9min 否 / 30.1min 是）", () => {
    const reader = () => ({ REFLECT_NUDGE_INTERVAL_MIN: "30" });
    const s = newSession();
    s.settleIdle();
    s.idleAt = null;
    s.idleSinceReflectionMs = 0;
    s.lastReflectionAt = Date.now() - 29.9 * 60_000;
    assertEq(isReflectionDue(s, reader), false, "净活跃 29.9min 未到期");
    s.lastReflectionAt = Date.now() - 30.1 * 60_000;
    assertEq(isReflectionDue(s, reader), true, "净活跃 30.1min 已到期");
  });

  await test("T6 markReflectionFired：先算后清（净活跃口径）、idleAt 保持、计数与工具差", () => {
    // 场景 A：墙钟 60.25min、已结算空闲 40min → sinceMin≈20.25（两位小数）
    const s = newSession();
    s.settleIdle();
    s.lastReflectionAt = Date.now() - 3_615_000; // 60min15s
    s.idleSinceReflectionMs = 2_400_000; // 已结算空闲 40min
    s.idleAt = null;
    s.toolCallCount = 42;
    s.lastReflectionToolCount = 40;
    const rA = markReflectionFired(s);
    assertTrue(
      Math.abs(rA.sinceMin - 20.25) < 0.1,
      `净活跃 20.25min（两位小数、先算后清），实际 ${rA.sinceMin}`,
    );
    assertEq(rA.sinceTools, 2, "工具差");
    assertEq(s.idleSinceReflectionMs, 0, "批次累加器归零");
    assertEq(s.reflectionCount, 1, "计数递增");
    assertTrue(
      Math.abs(Date.now() - s.lastReflectionAt) < 1000,
      "lastReflectionAt≈now",
    );

    // 场景 B：发射时窗口已开（唤醒通道）→ 不清 idleAt
    const s2 = newSession();
    s2.settleIdle();
    const winStart = Date.now() - 500_000;
    s2.idleAt = winStart;
    markReflectionFired(s2);
    assertEq(s2.idleAt, winStart, "idleAt 保持（开放窗口留给下一批结算）");

    // 场景 C：两位小数四舍五入与下限（显式 now，确定性）
    const s3 = newSession();
    s3.settleIdle();
    s3.lastReflectionAt = 1_000_000;
    s3.idleSinceReflectionMs = 0;
    assertEq(
      activeMinutesSinceReflection(s3, 1_000_000 + 1_234_567),
      20.58,
      "1234567ms → 20.58min（四舍五入两位小数）",
    );
    assertEq(
      activeMinutesSinceReflection(s3, 1_000_000),
      0.01,
      "下限 0.01",
    );
  });

  await test("T7 跨周期回归：净活跃口径不吃历史空闲（旧墙钟公式误判样本）", () => {
    const reader = () => ({ REFLECT_NUDGE_INTERVAL_MIN: "30" });
    const s = newSession();
    s.settleIdle();
    // 墙钟 180min 中空闲 170min → 净活跃 10min：旧公式会到期（180≥30），新公式不到期
    s.lastReflectionAt = Date.now() - 180 * 60_000;
    s.idleSinceReflectionMs = 170 * 60_000;
    s.idleAt = null;
    assertEq(
      isReflectionDue(s, reader),
      false,
      "净活跃 10min 未到期（旧墙钟公式误判样本）",
    );
    // 净活跃达 31min → 到期
    s.lastReflectionAt = Date.now() - 201 * 60_000;
    assertEq(isReflectionDue(s, reader), true, "净活跃 31min → 到期");
    // 发射清零：历史空闲不残留到下一周期
    markReflectionFired(s);
    assertEq(s.idleSinceReflectionMs, 0, "第二周期从零累计");
    assertEq(isReflectionDue(s, reader), false, "刚发射 → 未到期");
  });

  await test("T8 全链路序列模拟：markIdle→settle→工作→发射→再循环", () => {
    const reader = () => ({ REFLECT_NUDGE_INTERVAL_MIN: "30" });
    const s = newSession();
    s.settleIdle(); // 出生窗口结算
    // 工作 20min（无空闲）→ 未到期
    s.idleAt = null;
    s.idleSinceReflectionMs = 0;
    s.lastReflectionAt = Date.now() - 20 * 60_000;
    assertEq(isReflectionDue(s, reader), false, "工作 20min 未到期");
    // 空闲 2h：markIdle → settle
    const t1 = Date.now();
    s.markIdle(t1);
    s.settleIdle(t1 + 2 * 3_600_000);
    assertTrue(s.totalIdleMs >= 2 * 3_600_000, "2h 空闲入账");
    // 净活跃累计 30min → 到期
    s.lastReflectionAt = Date.now() - (30 * 60_000 + 2 * 3_600_000);
    assertEq(isReflectionDue(s, reader), true, "净活跃 30min → 到期");
    markReflectionFired(s);
    assertEq(s.idleSinceReflectionMs, 0, "批次归零");
    // 第二轮：空闲 40min + 工作 5min → 净活跃 5min 未到期
    s.lastReflectionAt = Date.now() - 45 * 60_000;
    s.idleSinceReflectionMs = 40 * 60_000;
    s.idleAt = null;
    assertEq(isReflectionDue(s, reader), false, "第二轮净活跃 5min 未到期");
  });

  console.log(`\n通过 ${_passed} / 失败 ${_failed}`);
  if (_failed > 0) {
    console.log(_failures.join("\n"));
    process.exit(1);
  }
}

main();
