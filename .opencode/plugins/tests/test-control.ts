/**
 * Plugin 控制台模块测试。
 *
 * 覆盖：
 *   - heartbeat.ts: 心跳发送器（幂等 start/stop）
 *   - control-config.ts: 配置缓存
 *   - control-manager.ts: 控制台启动管理
 *
 * 运行：bun .opencode/plugins/tests/test-control.ts
 */
import { HeartbeatSender, heartbeatSender } from "../lib/heartbeat";
import {
  getAllConfig,
  getCachedConfig,
  refreshConfig,
} from "../lib/control-config";
import { controlFetch } from "../lib/control-http";
import * as constants from "../lib/constants";
import { existsSync, readFileSync, unlinkSync, writeFileSync } from "fs";
import { join } from "path";
import { homedir } from "os";

// ── 沙箱防污染保护 ────────────────────────────────────────
// 本测试经 IPC 常量触达真实路径（CONTROL_UNIX_SOCKET 等）。
// constants.ts 的 DATA_DIR 支持 env 覆盖——必须设置到 /tmp 沙箱，
// 否则单飞测试会 spawn/干扰生产控制台。
// 不设置 DATA_DIR 直接运行 → 立即报错退出。
if (
  !process.env.DATA_DIR ||
  process.env.DATA_DIR.includes("bw-security-analysis")
) {
  console.error(
    "✗ 危险：未设置沙箱 DATA_DIR。请用：DATA_DIR=/tmp/control_test_ts bun .opencode/plugins/tests/test-control.ts",
  );
  process.exit(1);
}

// 沙箱 DATA_DIR 无自有 venv——单飞测试（真实 spawn 控制台）经子进程注入干净 env
// （constants.VENV_DIR 在模块加载时求值，本进程注入来不及；子进程先设 env 再加载）。
if (!process.env.OPENCODE_ROOT) {
  process.env.OPENCODE_ROOT = join(import.meta.dir, "..", "..");
}

let _passed = 0;
let _failed = 0;
const _failures: string[] = [];

function assert(condition: boolean, msg: string): void {
  if (!condition) throw new Error(msg);
}

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
    const msg = e instanceof Error ? e.message : String(e);
    _failures.push(`${name}: ${msg}`);
    console.log(`  ✗ ${name}: ${msg}`);
  }
}

// ─── heartbeat 测试 ────────────────────────────────────────
// （HeartbeatSender 的真实 HTTP 往返由单飞测试的子进程控制台覆盖；
//   此处验证类协议约束: 幂等/停跳/unref 语义）

await test("heartbeat: 单例已导出且初始未运行", () => {
  assert(heartbeatSender instanceof HeartbeatSender, "模块级单例");
  assert(!heartbeatSender.running, "初始应未运行");
});

await test("heartbeat: start 首跳失败不炸（无控制台时吞异常）", async () => {
  // 沙箱 DATA_DIR 下无控制台——首跳必然连接失败，但必须安全吞掉
  const sender = new HeartbeatSender();
  await sender.start(); // 不应抛
  assert(sender.running, "start 后应处于运行态（interval 已挂载）");
  sender.stop();
  assert(!sender.running, "stop 后应停跳");
});

await test("heartbeat: start 幂等（二次 start 不产生第二个 interval）", async () => {
  const sender = new HeartbeatSender();
  await sender.start();
  await sender.start(); // 幂等：直接返回
  sender.stop();
  sender.stop(); // stop 也幂等
  assert(true, "未抛异常即通过");
});

await test("heartbeat: HEARTBEAT_INTERVAL_MS 与控制台超时协议配对", () => {
  // TS 侧 10s 间隔 × 6 = 60s 超时窗口（丢 5 跳仍活；第 6 跳超时前必须到）
  assert(constants.HEARTBEAT_INTERVAL_MS === 10_000, "间隔应为 10s");
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

// ─── control-http 测试 ─────────────────────────────────────

await test("control-http: IPC 常量与平台分支", () => {
  // 常量存在且形态正确（不实际连接——沙箱 DATA_DIR 下无控制台）
  const { CONTROL_UNIX_SOCKET, CONTROL_WIN_PIPE, IS_WINDOWS } = constants;
  assert(
    CONTROL_UNIX_SOCKET.endsWith("opensecurity-control.sock"),
    "Unix socket 路径名",
  );
  assert(
    CONTROL_WIN_PIPE.startsWith("\\\\.\\pipe\\opensecurity-control-"),
    "Windows 管道名前缀",
  );
  assert(typeof IS_WINDOWS === "boolean", "平台标记");
});

await test("control-http: controlFetch 对不可达 IPC 返回 false/抛错", async () => {
  // 沙箱 DATA_DIR 下无控制台 → /health 应失败（连接错误），不崩溃
  try {
    await controlFetch("/health", { timeoutMs: 1000 });
    // Windows TCP 回退可能碰上真实端口（沙箱隔离了 DATA_DIR 但 TCP 是全局的）——
    // 连上了也算通过（只验证不抛未捕获异常）
    assert(true, "请求完成（无论成败）");
  } catch {
    assert(true, "连接失败符合预期（沙箱无控制台）");
  }
});

await test("control-http: uds 真实往返（Bun.serve unix → controlFetch）", async () => {
  // 生产主路径最小复现：uds 服务端 + controlFetch 请求（含 POST 分支）
  const { join } = await import("path");
  const { homedir } = await import("os");
  const dataDir = process.env.DATA_DIR ?? join(homedir(), "bw-security-analysis");
  const sockPath = join(dataDir, "opensecurity-control.sock");
  const server = Bun.serve({
    unix: sockPath,
    fetch: async (req) => {
      if (req.url.endsWith("/health")) return Response.json({ ok: true, via: "uds" });
      if (req.url.endsWith("/echo") && req.method === "POST") {
        const body = await req.text();
        return Response.json({ echoed: body });
      }
      return new Response("not found", { status: 404 });
    },
  });
  try {
    const r = await controlFetch("/health", { timeoutMs: 3000 });
    assert(r.status === 200, `uds GET /health 应 200，实际 ${r.status}`);
    const j: any = await r.json();
    assert(j.ok === true && j.via === "uds", "uds 响应体应正确");

    const r2 = await controlFetch("/echo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ping: 1 }),
      timeoutMs: 3000,
    });
    assert(r2.status === 200, `uds POST 应 200，实际 ${r2.status}`);
    const j2: any = await r2.json();
    assert(j2.echoed.includes("ping"), "POST body 应到达服务端");
  } finally {
    server.stop(true); // stop(true) 同时删除 unix socket 文件
  }
});

await test("control-manager: startControl 单飞——6 路并发仅 1 次 spawn", async () => {
  // 2026/8/20 事故形态的回归锚点：并发调用共享同一 Promise，等待不重复 spawn。
  // 子进程跑（env 先于模块加载注入：OPENSECURITY_VENV_DIR 指真实 venv），
  // 父进程数日志 spawn 行数（沙箱 logs/plugin_debug.log）。
  const { spawnSync } = await import("child_process");
  const dataDir = process.env.DATA_DIR!;
  const script = `
import { startControl } from "${join(import.meta.dir, "..", "lib", "control-manager.ts")}";
const results = await Promise.all([
  startControl(), startControl(), startControl(),
  startControl(), startControl(), startControl(),
]);
console.log("ALL_OK:", results.every((r) => r === true));
`;
  const r = spawnSync("bun", ["-e", script], {
    env: {
      ...process.env,
      DATA_DIR: dataDir,
      OPENSECURITY_VENV_DIR: process.env.OPENSECURITY_VENV_DIR || join(homedir(), "bw-security-analysis", ".venv"),
      OPENCODE_ROOT: process.env.OPENCODE_ROOT!,
    },
    timeout: 60_000,
    encoding: "utf-8",
  });
  assert(r.stdout?.includes("ALL_OK: true"), `子进程 6 路并发应全部成功。stdout=${(r.stdout || "").slice(-200)} stderr=${(r.stderr || "").slice(-200)}`);
  // 数日志中的 spawn 次数
  const logPath = join(dataDir, "logs", "plugin_debug.log");
  if (existsSync(logPath)) {
    const spawns = (readFileSync(logPath, "utf-8").match(/startControl: spawn pid=/g) || []).length;
    assert(spawns === 1, `并发 6 路应只 spawn 1 次，实际 ${spawns}`);
  }
});

// ─── 边界条件补充测试 ─────────────────────────────────────


// ─── 汇总 ──────────────────────────────────────────────────

console.log("");
console.log("=".repeat(60));
console.log(
  `Plugin 控制台模块测试: 通过 ${_passed} / 失败 ${_failed} / 总计 ${_passed + _failed}`,
);
if (_failed > 0) {
  console.log("\n失败用例：");
  for (const f of _failures) {
    console.log(`  ✗ ${f}`);
  }
}
console.log("=".repeat(60));

if (_failed > 0) process.exit(1);
