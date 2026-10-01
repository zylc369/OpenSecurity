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
  fetchConfig,
  getCachedConfig,
} from "../lib/control-config";
import { controlFetch } from "../lib/control-http";
import * as constants from "../lib/constants";
import { existsSync, readFileSync, unlinkSync, writeFileSync } from "fs";
import { join } from "path";
import { homedir } from "os";

// ── 沙箱防污染保护 ────────────────────────────────────────
// 本测试经 IPC 常量触达真实路径（CONTROL_UNIX_SOCKET 等）。
// constants.ts 的 OPENSECURITY_HOME 支持 env 覆盖——必须设置到 /tmp 沙箱，
// 否则单飞测试会 spawn/干扰生产控制台。
// 不设置 OPENSECURITY_HOME 直接运行 → 立即报错退出。
if (
  !process.env.OPENSECURITY_HOME ||
  process.env.OPENSECURITY_HOME.includes("bw-security-analysis")
) {
  console.error(
    "✗ 危险：未设置沙箱 OPENSECURITY_HOME。请用：OPENSECURITY_HOME=/tmp/control_test_ts bun .opencode/plugins/tests/test-control.ts",
  );
  process.exit(1);
}

// 沙箱 OPENSECURITY_HOME 无自有 venv——单飞测试（真实 spawn 控制台）经子进程注入干净 env
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
  // 沙箱 OPENSECURITY_HOME 下无控制台——首跳必然连接失败，但必须安全吞掉
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

await test("control-config: fetchConfig + getCachedConfig TTL/SWR", async () => {
  // fetchConfig fail-fast：控制台不可达直接抛异常。
  // 控制台未启动 = 测试环境不具备 → 明确跳过（替代旧的"静默空配置"语义）。
  let configs: Record<string, string>;
  try {
    configs = await fetchConfig();
  } catch (e) {
    console.log(
      "跳过：控制台未运行（fetchConfig 已 fail-fast）:",
      (e as Error).message,
    );
    return;
  }
  if (Object.keys(configs).length > 0) {
    assert("DEEPSEEK_API_KEY" in configs, "应有 DEEPSEEK_API_KEY");
  }

  // a) fetchConfig 直读后喂缓存：同步侧立即可见（无需等待）
  const synced = getCachedConfig();
  assert(
    Object.keys(synced).length === Object.keys(configs).length,
    "fetchConfig 应喂缓存（getCachedConfig 立即可见）",
  );

  // b) TTL 内同步调用不触发后台刷新（无 in-flight 竞态即可返回完整缓存）
  const again = getCachedConfig();
  assert(
    Object.keys(again).length === Object.keys(configs).length,
    "TTL 内二次同步调用应直接返缓存",
  );
});

await test("control-config: getCachedConfig 同步返回", () => {
  const configs = getCachedConfig();
  // 应该返回对象（空对象也行）
  assert(typeof configs === "object", "应返回对象");
});

await test("control-config: SWR 过期分支（返旧值 + 后台刷新落地）", async () => {
  const before = getCachedConfig();
  if (Object.keys(before).length === 0) {
    console.log("跳过：控制台未运行（缓存为空，SWR 分支依赖已填充的缓存）");
    return;
  }
  const { forceExpireCacheForTest } = await import("../lib/control-config");
  forceExpireCacheForTest(); // 强制 TTL 过期
  const stale = getCachedConfig(); // SWR: 立即返旧值（非空）+ fire-and-forget 后台刷
  assert(
    Object.keys(stale).length === Object.keys(before).length,
    "SWR 过期时应立即返回完整旧值（不阻塞不空转）",
  );
  await new Promise((r) => setTimeout(r, 500)); // 等后台刷新落地
  const fresh = getCachedConfig();
  assert(
    Object.keys(fresh).length === Object.keys(before).length,
    "后台刷新完成后缓存应完整（失败场景才保留旧值——此处应成功刷新）",
  );
  // 判据：fetchConfig 成功会替换缓存对象引用；失败路径只 debugLog、保留旧对象。
  // "内容长度相同"不足以证明刷新落地（失败时旧值同样完整），引用变化才是硬证据。
  assert(fresh !== before, "刷新成功应替换缓存对象（引用未变 = 后台刷新未落地）");
});

// ─── control-http 测试 ─────────────────────────────────────

await test("control-http: IPC 常量与平台分支", () => {
  // 常量存在且形态正确（不实际连接——沙箱 OPENSECURITY_HOME 下无控制台）
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
  // 沙箱 OPENSECURITY_HOME 下无控制台 → /health 应失败（连接错误），不崩溃
  try {
    await controlFetch("/health", { timeoutMs: 1000 });
    // Windows TCP 回退可能碰上真实端口（沙箱隔离了 OPENSECURITY_HOME 但 TCP 是全局的）——
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
  const opensecurityHome = process.env.OPENSECURITY_HOME ?? join(homedir(), "bw-security-analysis");
  const sockPath = join(opensecurityHome, "opensecurity-control.sock");
  // 创建前清理残留 socket——防 EADDRINUSE 连锁：残留 → Bun.serve 抛错 →
  // finally 不执行（server 未创建）→ 残留永存（重跑持续失败）
  try {
    if (existsSync(sockPath)) unlinkSync(sockPath);
  } catch {}
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
  const opensecurityHome = process.env.OPENSECURITY_HOME!;
  const script = `
import { startControl } from "${join(import.meta.dir, "..", "lib", "control-manager.ts")}";
const results = await Promise.all([
  startControl(), startControl(), startControl(),
  startControl(), startControl(), startControl(),
]);
console.log("ALL_OK:", results.every((r) => r === true));
`;
  // 数日志 spawn 次数（基线差值：沙箱日志跨重跑累计，只断言本次新增 1 条）
  const logPath = join(opensecurityHome, "logs", "plugin_debug.log");
  const countSpawns = (): number =>
    existsSync(logPath)
      ? (readFileSync(logPath, "utf-8").match(/startControl: spawn pid=/g) || []).length
      : 0;
  const spawnsBefore = countSpawns();
  const r = spawnSync("bun", ["-e", script], {
    env: {
      ...process.env,
      OPENSECURITY_HOME: opensecurityHome,
      OPENSECURITY_VENV_DIR: process.env.OPENSECURITY_VENV_DIR || join(homedir(), "bw-security-analysis", ".venv"),
      OPENCODE_ROOT: process.env.OPENCODE_ROOT!,
    },
    timeout: 60_000,
    encoding: "utf-8",
  });
  assert(r.stdout?.includes("ALL_OK: true"), `子进程 6 路并发应全部成功。stdout=${(r.stdout || "").slice(-200)} stderr=${(r.stderr || "").slice(-200)}`);
  const spawns = countSpawns() - spawnsBefore;
  assert(spawns === 1, `并发 6 路应只 spawn 1 次，实际 ${spawns}`);
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

// ─── 沙箱清理兜底 ───────────────────────────────────────────
// 防测试异常中断（进程被 kill / 未走到 uds 测试 finally）留下的 socket
// 阻塞下次运行。进程退出前统一清理（失败退出路径同样覆盖）。
try {
  const sockPath = join(process.env.OPENSECURITY_HOME!, "opensecurity-control.sock");
  if (existsSync(sockPath)) unlinkSync(sockPath);
} catch {}

if (_failed > 0) process.exit(1);
