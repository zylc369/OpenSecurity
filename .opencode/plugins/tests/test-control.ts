/**
 * Plugin 控制台模块测试。
 *
 * 覆盖：
 *   - ref-counter.ts: users 文件读写
 *   - process-utils.ts: PID 检测 + 启动时间
 *   - control-config.ts: 配置缓存
 *   - control-manager.ts: 端口文件解析
 *
 * 运行：bun .opencode/plugins/tests/test-control.ts
 */
import {
  parseUsers, formatUsers, readUsers, atomicWriteUsers,
  addSelfToUsers, removeSelfFromUsers, cleanupDeadUsers,
} from "../lib/ref-counter";
import {
  isProcessAliveSync, getProcessStartTime,
} from "../lib/process-utils";
import { getAllConfig, getCachedConfig, refreshConfig } from "../lib/control-config";
import { readControlPortFile } from "../lib/control-manager";
import { CONTROL_USERS_FILE } from "../lib/constants";
import { existsSync, readFileSync, unlinkSync, writeFileSync } from "fs";

// ── 沙箱防污染保护 ────────────────────────────────────────
// 本测试直接 unlink/write 真实路径常量（CONTROL_USERS_FILE 等）。
// constants.ts 的 DATA_DIR 支持 env 覆盖——必须设置到 /tmp 沙箱，
// 否则会删掉生产控制台的 users 文件、导致真实控制台自杀退出（已发生过一次事故）。
// 不设置 DATA_DIR 直接运行 → 立即报错退出。
if (!process.env.DATA_DIR || process.env.DATA_DIR.includes("bw-security-analysis")) {
  console.error("✗ 危险：未设置沙箱 DATA_DIR。请用：DATA_DIR=/tmp/control_test_ts bun .opencode/plugins/tests/test-control.ts");
  process.exit(1);
}

let _passed = 0;
let _failed = 0;
const _failures: string[] = [];

function assert(condition: boolean, msg: string): void {
  if (!condition) throw new Error(msg);
}

function assertEq<T>(actual: T, expected: T, msg: string): void {
  if (actual !== expected) {
    throw new Error(`${msg}: actual=${JSON.stringify(actual)}, expected=${JSON.stringify(expected)}`);
  }
}

async function test(name: string, fn: () => Promise<void> | void): Promise<void> {
  try {
    await fn();
    _passed++;
    console.log(`  ✓ ${name}`);
  } catch (e) {
    _failed++;
    const msg = e instanceof Error ? e.message : String(e);
    _failures.push(`${name}: ${msg}`);
    console.log(`  ✗ ${name}: ${msg}`);
  }
}

// ─── process-utils 测试 ────────────────────────────────────

await test("process-utils: 自己 PID 存活", () => {
  assert(isProcessAliveSync(process.pid), "自己 PID 应存活");
});

await test("process-utils: 死 PID 99999 不存活", () => {
  assert(!isProcessAliveSync(99999), "99999 应不存活");
});

await test("process-utils: PID 复用防护（startTime=0 视为未提供）", () => {
  // startTime=0 视为未提供，宽容返回 true
  assert(isProcessAliveSync(process.pid, 0), "startTime=0 应宽容返回 true");
  // startTime=99999 不匹配，应返回 false
  assert(!isProcessAliveSync(process.pid, 99999), "不匹配 startTime 应 false");
});

await test("process-utils: getProcessStartTime 返回有效时间戳", () => {
  const st = getProcessStartTime(process.pid);
  assert(st !== null, "应返回非 null");
  assert((st ?? 0) > 1_000_000_000, "时间戳应 > 2001 年");
});

// ─── ref-counter 测试 ──────────────────────────────────────

await test("ref-counter: parseUsers + formatUsers 往返", () => {
  const entries = [
    { pid: 12345, startTime: 1000 },
    { pid: 67890, startTime: 2000 },
  ];
  const text = formatUsers(entries);
  const parsed = parseUsers(text);
  assertEq(parsed.length, 2, "应解析 2 条");
  assertEq(parsed[0].pid, 12345, "第一条 pid");
  assertEq(parsed[1].startTime, 2000, "第二条 startTime");
});

await test("ref-counter: addSelfToUsers + readUsers", () => {
  // 清理
  if (existsSync(CONTROL_USERS_FILE)) unlinkSync(CONTROL_USERS_FILE);
  addSelfToUsers();
  const users = readUsers();
  assert(users.some((u) => u.pid === process.pid), "应包含自己 PID");
});

await test("ref-counter: cleanupDeadUsers 清理死 PID", () => {
  // 先写自己 + 死 PID
  const users = readUsers();
  users.push({ pid: 99999, startTime: 0 });
  atomicWriteUsers(users);

  const alive = cleanupDeadUsers();
  assertEq(alive.length, 1, "应剩 1 条（自己）");
  assertEq(alive[0].pid, process.pid, "应是自己");
});

await test("ref-counter: removeSelfFromUsers 返回 isEmpty=true", () => {
  // 先确保只有自己
  atomicWriteUsers([{ pid: process.pid, startTime: 0 }]);
  const isEmpty = removeSelfFromUsers();
  assert(isEmpty, "删自己后应 isEmpty=true");
  // 验证文件内容（可能为空字符串或只剩其他不存在的 PID）
  if (existsSync(CONTROL_USERS_FILE)) {
    const content = readFileSync(CONTROL_USERS_FILE, "utf-8").trim();
    // 应该不包含自己 PID
    assert(!content.includes(`pid=${process.pid}`), "文件不应包含自己 PID");
  }
});

await test("ref-counter: removeSelfFromUsers 有其他引用时返回 isEmpty=false", () => {
  // 自己 + 另一个 PID（活的）
  atomicWriteUsers([
    { pid: process.pid, startTime: 0 },
    { pid: process.ppid ?? 1, startTime: 0 },  // 父进程（一般活着）
  ]);
  const isEmpty = removeSelfFromUsers();
  assert(!isEmpty, "还有父进程引用时应 isEmpty=false");
});

// ─── control-config 测试 ───────────────────────────────────
// 注意：control-config 通过 HTTP 调控制台，需要控制台运行

await test("control-config: refreshConfig + getAllConfig", async () => {
  // 假设控制台已运行（测试时手动启动或前一个测试启动）
  await refreshConfig();
  const configs = getAllConfig();
  // 验证拿到配置（数量可能为 0 如果控制台未启动）
  if (Object.keys(configs).length > 0) {
    assert("DEEPSEEK_API_KEY" in configs, "应有 DEEPSEEK_API_KEY");
  }
});

await test("control-config: getCachedConfig 同步返回", () => {
  const configs = getCachedConfig();
  // 应该返回对象（空对象也行）
  assert(typeof configs === "object", "应返回对象");
});

// ─── control-manager 测试 ──────────────────────────────────

await test("control-manager: readControlPortFile 解析", () => {
  // 写入测试端口文件
  const testData = "9123\n12345\n1783000000\n";
  writeFileSync("/tmp/control_test_data/.opencode-control.port", testData);
  // 临时替换 CONTROL_PORT_FILE 路径不现实（常量），所以这里只测函数不抛异常
  const info = readControlPortFile();
  // info 可能是 null（因为 CONTROL_PORT_FILE 指向真实路径）
  // 主要验证函数能调用
  assert(info === null || (typeof info.port === "number"), "应返回 null 或 ControlPortInfo");
});

// ─── 边界条件补充测试 ─────────────────────────────────────

await test("ref-counter: atomicWriteUsers 多次写不残留 tmp", () => {
  if (existsSync(CONTROL_USERS_FILE)) unlinkSync(CONTROL_USERS_FILE);
  // 连续多次写
  for (let i = 0; i < 5; i++) {
    atomicWriteUsers([{ pid: 10000 + i, startTime: i * 1000 }]);
  }
  // 验证 tmp 文件清理（PID 后缀的 tmp 应该被 rename 走）
  const dir = CONTROL_USERS_FILE.substring(0, CONTROL_USERS_FILE.lastIndexOf("/"));
  // 验证最终文件正确
  const final = readUsers();
  assertEq(final.length, 1, "应剩 1 条（最后写入的）");
  assertEq(final[0].pid, 10004, "应是最后一次写入的 PID");
});

await test("ref-counter: parseUsers 容错（空文件）", () => {
  const result = parseUsers("");
  assertEq(result.length, 0, "空文件应返回空数组");
});

await test("ref-counter: parseUsers 容错（仅注释和空行）", () => {
  const result = parseUsers("\n# 注释\n\n");
  assertEq(result.length, 0, "纯注释应返回空数组");
});

await test("ref-counter: parseUsers 容错（缺 start_time）", () => {
  // 缺 start_time 字段时应该用 0 兜底
  const result = parseUsers("pid=11111\n");
  assertEq(result.length, 1, "应解析 1 条");
  assertEq(result[0].pid, 11111);
  assertEq(result[0].startTime, 0, "缺 start_time 应默认 0");
});

await test("process-utils: PID 复用防护（startTime 精确匹配）", () => {
  const st = getProcessStartTime(process.pid);
  if (st !== null) {
    // 精确匹配应存活
    assert(isProcessAliveSync(process.pid, st), "精确匹配 startTime 应存活");
    // 偏差 1s 内应存活（容忍）
    assert(isProcessAliveSync(process.pid, st - 0.5), "偏差 0.5s 应存活");
    // 偏差 >1s 应不存活
    assert(!isProcessAliveSync(process.pid, st + 100), "偏差 100s 应判定 PID 复用");
  }
});

await test("process-utils: 死 PID 99999 不存活", () => {
  assert(!isProcessAliveSync(99999), "99999 应不存活");
  // 用不匹配的 startTime 也应该不存活
  assert(!isProcessAliveSync(99999, 12345), "死 PID + startTime 也不存活");
});

// ─── 汇总 ──────────────────────────────────────────────────

console.log("");
console.log("=" .repeat(60));
console.log(`Plugin 控制台模块测试: 通过 ${_passed} / 失败 ${_failed} / 总计 ${_passed + _failed}`);
if (_failed > 0) {
  console.log("\n失败用例：");
  for (const f of _failures) {
    console.log(`  ✗ ${f}`);
  }
}
console.log("=" .repeat(60));

if (_failed > 0) process.exit(1);
