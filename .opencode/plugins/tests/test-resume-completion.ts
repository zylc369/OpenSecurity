/**
 * 续跑完成态（粘性）测试。
 *
 * 缺陷现场：完成标记命中 → 跳过续跑 ✓ → 上下文压缩生成摘要（成为最后一条 assistant 消息，
 * 不含标记）→ 下次 idle 文本检测失效 → 又续跑 → 完成→压缩→续跑 死循环。
 * 修复：完成态固化为会话状态 resumeCompletedAt（跨压缩保持），真实用户消息才清空。
 *
 * 覆盖: SessionData.resumeCompletedAt / isAnalysisCompleted() 的状态机语义，
 * 以及与 isResumeEcho（回声不清完成态/不刷新 lastUserMessageAt）的契约。
 *
 * 运行: OPENSECURITY_HOME=/tmp/resume_completion_test bun .opencode/plugins/tests/test-resume-completion.ts
 */
import { SessionData } from "../lib/session-manager";

// ── 沙箱防污染保护（同 test-reflection-clock.ts 模式）──
if (
  !process.env.OPENSECURITY_HOME ||
  process.env.OPENSECURITY_HOME.includes("bw-security-analysis")
) {
  console.error(
    "✗ 危险：未设置沙箱 OPENSECURITY_HOME。请用：OPENSECURITY_HOME=/tmp/resume_completion_test bun .opencode/plugins/tests/test-resume-completion.ts",
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

/** 模拟 maybeResumeAnalysis 的完成标记命中分支 */
function markCompleted(s: SessionData, at: number = Date.now()): void {
  s.resumeCompletedAt = at;
}

async function main(): Promise<void> {
  console.log("test-resume-completion: 续跑完成态（粘性）\n");

  await test("T1 新建会话未完成：isAnalysisCompleted()=false", () => {
    const s = newSession();
    assertEq(s.resumeCompletedAt, null, "初值应为 null");
    assertEq(s.isAnalysisCompleted(), false, "未完成");
  });

  await test("T2 完成标记命中 → 固化完成态=true", () => {
    const s = newSession();
    s.lastUserMessageAt = Date.now() - 60_000; // 上一条真实用户消息在 1 分钟前
    markCompleted(s);
    assertTrue(s.resumeCompletedAt !== null, "完成时刻已置位");
    assertEq(s.isAnalysisCompleted(), true, "完成态成立");
  });

  await test("T3 粘性：压缩产生新 assistant 文本（无用户消息）后仍=true，且幂等", () => {
    const s = newSession();
    s.lastUserMessageAt = Date.now() - 60_000;
    markCompleted(s);
    // 压缩发生：lastText 被摘要覆盖——本状态不依赖文本，故无需任何模拟即应保持
    assertEq(s.isAnalysisCompleted(), true, "压缩后完成态保持");
    assertEq(s.isAnalysisCompleted(), true, "重复判定幂等");
    // 再推进一段时间（模拟压缩后再次 idle）
    s.lastUserMessageAt = s.lastUserMessageAt; // 未变（无真实用户消息）
    assertEq(s.isAnalysisCompleted(), true, "无用户消息 → 一直保持");
  });

  await test("T4 真实用户消息（upsert 语义：刷新时间 + 清空完成态）→ false", () => {
    const s = newSession();
    s.lastUserMessageAt = Date.now() - 60_000;
    markCompleted(s);
    assertEq(s.isAnalysisCompleted(), true, "前置：已完成");
    // upsert 真实用户消息分支的两项动作
    s.lastUserMessageAt = Date.now();
    s.resumeCompletedAt = null;
    assertEq(s.isAnalysisCompleted(), false, "新一轮对话 → 完成态作废");
  });

  await test("T5 防御性时间比较：完成时刻 ≤ 最后用户消息 → false（视为新一轮）", () => {
    const s = newSession();
    const now = Date.now();
    s.lastUserMessageAt = now;
    markCompleted(s, now - 1_000); // 完成态落后于用户消息（非本轮）
    assertEq(s.isAnalysisCompleted(), false, "过期完成态不生效");
  });

  await test("T6 回声契约：恢复提示词回声不改 lastUserMessageAt/resumeMarker，完成态仍成立", () => {
    const s = newSession();
    s.resumePrompt = "【测试】恢复提示词正文";
    s.resumeMarker = ">>>COMPLETE-test<<<";
    s.lastUserMessageAt = Date.now() - 60_000;
    markCompleted(s);

    const echo = {
      message: {},
      parts: [{ type: "text", text: s.resumePrompt }],
    } as unknown as Parameters<SessionData["isResumeEcho"]>[0];
    assertEq(s.isResumeEcho(echo), true, "回声被识别");

    // 回声路径（upsert isResumeEcho 分支）不清 resumeMarker、不刷新 lastUserMessageAt
    const userAt = s.lastUserMessageAt;
    const completedAt = s.resumeCompletedAt;
    assertEq(s.lastUserMessageAt, userAt, "回声不刷新 lastUserMessageAt");
    assertEq(s.resumeCompletedAt, completedAt, "回声不清完成态");
    assertEq(s.isAnalysisCompleted(), true, "回声后完成态仍成立");
  });

  await test("T7 未完成的会话（从未固化）保持 false，可正常续跑", () => {
    const s = newSession();
    s.lastUserMessageAt = Date.now() - 60_000;
    // 未命中完成标记 → 不置位
    assertEq(s.resumeCompletedAt, null, "未完成不置位");
    assertEq(s.isAnalysisCompleted(), false, "不抑制续跑");
  });

  console.log(`\n通过 ${_passed} / 失败 ${_failed}`);
  if (_failed > 0) {
    console.log(_failures.join("\n"));
    process.exit(1);
  }
}

main();
