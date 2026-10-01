/**
 * 权限询问超时自动拒绝 单元测试。
 *
 * harness 直接驱动真实 lib/permission-timeout.ts（mock ctx + 注入 configReader）
 * ——不依赖控制台/opencode 运行时。拒绝通道全部经 mock client 断言。
 *
 * 覆盖:
 *   - extractPermissionAskInfo: v1/v2 字段归一 + 缺字段
 *   - getPermissionTimeoutMs/Types: 默认/非法回退/0 关闭/中文逗号
 *   - manager: 超时→底层 post 通道（带反馈文案）/ 类型过滤 / 0=关闭 /
 *     onReplied 清理 / dispose 清理 / 底层缺省→SDK 兜底 /
 *     client.permission.reply 探测优先
 *
 * 运行: OPENSECURITY_HOME=/tmp/perm_timeout_test bun .opencode/plugins/tests/test-permission-timeout.ts
 */
import type { OpencodeClient } from "@opencode-ai/sdk";
import type { SessionDataManager } from "../lib/session-manager";
import { ctx } from "../lib/context";
import {
  PermissionTimeoutManager,
  extractPermissionAskInfo,
  getPermissionTimeoutMs,
  getPermissionTimeoutTypes,
} from "../lib/permission-timeout";

// ── 沙箱防污染保护（同 test-control.ts 模式）──
if (
  !process.env.OPENSECURITY_HOME ||
  process.env.OPENSECURITY_HOME.includes("bw-security-analysis")
) {
  console.error(
    "✗ 危险：未设置沙箱 OPENSECURITY_HOME。请用：OPENSECURITY_HOME=/tmp/perm_timeout_test bun .opencode/plugins/tests/test-permission-timeout.ts",
  );
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
  } finally {
    // 用例失败也要清理定时器（防跨用例污染）
    while (_managers.length > 0) _managers.pop()!.dispose();
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ── mock 基建 ──────────────────────────────────────────────────

/** 底层 post 调用记录（hey-api 风格响应） */
interface RawPostCall {
  url: string;
  body: unknown;
}

function makeRawPostClient(
  calls: RawPostCall[],
  status = 200,
): Record<string, unknown> {
  return {
    _client: {
      post: async (options: { url: string; body?: unknown }) => {
        calls.push({ url: options.url, body: options.body });
        return {
          data: status === 200,
          error: status === 200 ? null : { message: "not found" },
          response: { status },
        };
      },
    },
  };
}

// 注册所有用例创建的 manager——test() 的 finally 统一 dispose（幂等）
const _managers: PermissionTimeoutManager[] = [];

function makeManager(
  configReader: () => Record<string, string>,
): PermissionTimeoutManager {
  // 模拟服务端 effective 语义: 用例未显式给 TYPES 时按服务端声明默认提供
  //（生产中默认值经 /api/config 返回，插件侧无默认副本）
  const wrapped = () => {
    const vals = configReader();
    return vals.PERMISSION_ASK_TIMEOUT_TYPES === undefined
      ? { ...vals, PERMISSION_ASK_TIMEOUT_TYPES: "external_directory" }
      : vals;
  };
  const manager = new PermissionTimeoutManager(wrapped);
  _managers.push(manager);
  return manager;
}

function installMockClient(client: Record<string, unknown>): void {
  ctx.init(
    client as unknown as OpencodeClient,
    "/tmp/perm_timeout_test",
    // debugLog 路由需要 sessionManager.get；返回 undefined 即走默认日志文件
    { get: () => undefined } as unknown as SessionDataManager,
  );
}

const readerOf = (vals: Record<string, string>) => () => vals;

async function main(): Promise<void> {
  console.log("test-permission-timeout: 权限询问超时自动拒绝\n");

  await test("extractPermissionAskInfo: v1/v2 字段归一 + 缺字段", () => {
    const v1 = extractPermissionAskInfo({
      id: "per_1",
      sessionID: "ses_1",
      permission: "external_directory",
    });
    assert(v1 !== null, "v1 应提取成功");
    assertEq(v1!.permissionType, "external_directory", "v1 permission 字段");
    const v2 = extractPermissionAskInfo({
      id: "per_2",
      sessionID: "ses_2",
      action: "external_directory",
    });
    assert(v2 !== null, "v2 应提取成功");
    assertEq(v2!.permissionType, "external_directory", "v2 action 字段");
    assertEq(extractPermissionAskInfo({ id: "per_3" }), null, "缺字段应返回 null");
  });

  await test("getPermissionTimeoutMs: 生效值解析/0 关闭/缺失与非法不启用", () => {
    assertEq(
      getPermissionTimeoutMs(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: "60" })),
      60_000,
      "生效值",
    );
    assertEq(
      getPermissionTimeoutMs(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: "0.3" })),
      300,
      "小数秒",
    );
    assertEq(
      getPermissionTimeoutMs(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: " 60 " })),
      60_000,
      "首尾空格 trim",
    );
    assertEq(
      getPermissionTimeoutMs(readerOf({})),
      0,
      "未取到生效值→不启用（默认值唯一权威在服务端，插件零副本）",
    );
    assertEq(
      getPermissionTimeoutMs(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: "0" })),
      0,
      "0=关闭",
    );
    assertEq(
      getPermissionTimeoutMs(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: "-5" })),
      0,
      "负数=关闭",
    );
    assertEq(
      getPermissionTimeoutMs(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: "abc" })),
      0,
      "非法→不启用",
    );
    assertEq(
      getPermissionTimeoutMs(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: "Infinity" })),
      0,
      "Infinity→不启用",
    );
  });

  await test("getPermissionTimeoutTypes: 列表/容错/缺失空集", () => {
    assertEq(
      getPermissionTimeoutTypes(readerOf({})).size,
      0,
      "未取到生效值→空集（默认值唯一权威在服务端）",
    );
    assertEq(
      [
        ...getPermissionTimeoutTypes(
          readerOf({ PERMISSION_ASK_TIMEOUT_TYPES: "edit,bash" }),
        ),
      ].join(","),
      "edit,bash",
      "英文逗号",
    );
    assertEq(
      [
        ...getPermissionTimeoutTypes(
          readerOf({ PERMISSION_ASK_TIMEOUT_TYPES: "edit，bash" }),
        ),
      ].join(","),
      "edit,bash",
      "中文逗号容错",
    );
    assertEq(
      getPermissionTimeoutTypes(
        readerOf({ PERMISSION_ASK_TIMEOUT_TYPES: "  " }),
      ).size,
      0,
      "空白→空集",
    );
    assertEq(
      [
        ...getPermissionTimeoutTypes(
          readerOf({ PERMISSION_ASK_TIMEOUT_TYPES: "edit,,bash" }),
        ),
      ].join(","),
      "edit,bash",
      "空项过滤",
    );
    assertEq(
      [
        ...getPermissionTimeoutTypes(
          readerOf({ PERMISSION_ASK_TIMEOUT_TYPES: "edit , bash" }),
        ),
      ].join(","),
      "edit,bash",
      "项内空格 trim",
    );
    assertEq(
      getPermissionTimeoutTypes(
        readerOf({ PERMISSION_ASK_TIMEOUT_TYPES: ",," }),
      ).size,
      0,
      "纯逗号为空集（任何类型不匹配）",
    );
    assertEq(
      getPermissionTimeoutTypes(
        readerOf({ PERMISSION_ASK_TIMEOUT_TYPES: "Edit" }),
      ).has("edit"),
      false,
      "类型名大小写敏感（opencode 类型全小写）",
    );
  });

  await test("manager: 超时→底层 post 通道（带反馈文案）", async () => {
    const calls: RawPostCall[] = [];
    installMockClient(makeRawPostClient(calls));
    const mgr = makeManager(
      readerOf({
        PERMISSION_ASK_TIMEOUT_SEC: "0.3",
        PERMISSION_ASK_TIMEOUT_TYPES: "external_directory",
      }),
    );
    mgr.onAsked({
      id: "per_post",
      sessionID: "ses_1",
      permission: "external_directory",
    });
    await sleep(700);
    assertEq(calls.length, 1, "应发出 1 个底层 post 请求");
    assert(
      calls[0].url === "/permission/per_post/reply",
      `路径应含 requestID: ${calls[0].url}`,
    );
    const body = calls[0].body as { reply: string; message?: string };
    assertEq(body.reply, "reject", "reply=reject");
    assert(
      body.message?.includes("超时自动拒绝") === true,
      "message 应含超时来源标识",
    );
    assert(body.message?.includes("Python 脚本") === true, "message 应含反馈文案");
    mgr.dispose();
  });

  await test("manager: 底层 404（已处理）不降级、视为完成", async () => {
    const calls: RawPostCall[] = [];
    const sdkCalls: Array<{ path: { permissionID: string } }> = [];
    installMockClient({
      ...makeRawPostClient(calls, 404),
      postSessionIdPermissionsPermissionId: async (input: {
        path: { permissionID: string };
      }) => {
        sdkCalls.push(input);
        return true;
      },
    });
    const mgr = makeManager(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: "0.3" }));
    mgr.onAsked({
      id: "per_404",
      sessionID: "ses_1",
      permission: "external_directory",
    });
    await sleep(700);
    assertEq(calls.length, 1, "底层 post 已发出");
    assertEq(sdkCalls.length, 0, "404 视为已处理，不应降级 SDK 兜底");
    mgr.dispose();
  });

  await test("manager: 通道② 5xx → 降级 SDK 兜底", async () => {
    const rawCalls: RawPostCall[] = [];
    const sdkCalls: Array<{ path: { permissionID: string } }> = [];
    installMockClient({
      ...makeRawPostClient(rawCalls, 500),
      postSessionIdPermissionsPermissionId: async (input: {
        path: { permissionID: string };
      }) => {
        sdkCalls.push(input);
        return true;
      },
    });
    const mgr = makeManager(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: "0.3" }));
    mgr.onAsked({
      id: "per_500",
      sessionID: "ses_1",
      permission: "external_directory",
    });
    await sleep(700);
    assertEq(rawCalls.length, 1, "通道②已发出");
    assertEq(sdkCalls.length, 1, "5xx 应降级 SDK 兜底（无反馈文案）");
    mgr.dispose();
  });

  await test("manager: 通道② 网络异常 → 降级 SDK 兜底", async () => {
    const sdkCalls: Array<{ path: { permissionID: string } }> = [];
    installMockClient({
      _client: {
        post: async () => {
          throw new Error("network down");
        },
      },
      postSessionIdPermissionsPermissionId: async (input: {
        path: { permissionID: string };
      }) => {
        sdkCalls.push(input);
        return true;
      },
    });
    const mgr = makeManager(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: "0.3" }));
    mgr.onAsked({
      id: "per_neterr",
      sessionID: "ses_1",
      permission: "external_directory",
    });
    await sleep(700);
    assertEq(sdkCalls.length, 1, "网络异常应降级 SDK 兜底");
    mgr.dispose();
  });

  await test("manager: 通道① 抛异常 → 落到通道②", async () => {
    const rawCalls: RawPostCall[] = [];
    installMockClient({
      ...makeRawPostClient(rawCalls),
      permission: {
        reply: async () => {
          throw new Error("channel1 down");
        },
      },
    });
    const mgr = makeManager(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: "0.3" }));
    mgr.onAsked({
      id: "per_c1fail",
      sessionID: "ses_1",
      permission: "external_directory",
    });
    await sleep(700);
    assertEq(rawCalls.length, 1, "通道①失败应走通道②");
    const body = rawCalls[0].body as { message?: string };
    assert(
      body.message?.includes("超时自动拒绝") === true,
      "通道②仍带超时来源标识",
    );
    assert(body.message?.includes("Python 脚本") === true, "通道②仍带反馈文案");
    mgr.dispose();
  });

  await test("manager: 同 requestID 重复布防幂等（只拒绝一次）", async () => {
    const calls: RawPostCall[] = [];
    installMockClient(makeRawPostClient(calls));
    const mgr = makeManager(
      readerOf({
        PERMISSION_ASK_TIMEOUT_SEC: "0.3",
        PERMISSION_ASK_TIMEOUT_TYPES: "external_directory",
      }),
    );
    mgr.onAsked({
      id: "per_dup",
      sessionID: "ses_1",
      permission: "external_directory",
    });
    mgr.onAsked({
      id: "per_dup",
      sessionID: "ses_1",
      permission: "external_directory",
    });
    await sleep(700);
    assertEq(calls.length, 1, "重复布防应只拒绝一次（幂等去重）");
    mgr.dispose();
  });

  await test("manager: 类型过滤（非生效类型不布防）", async () => {
    const calls: RawPostCall[] = [];
    installMockClient(makeRawPostClient(calls));
    const mgr = makeManager(
      readerOf({
        PERMISSION_ASK_TIMEOUT_SEC: "0.3",
        PERMISSION_ASK_TIMEOUT_TYPES: "external_directory",
      }),
    );
    mgr.onAsked({ id: "per_edit", sessionID: "ses_1", permission: "edit" });
    await sleep(700);
    assertEq(calls.length, 0, "edit 不在生效范围，不应请求");
    mgr.dispose();
  });

  await test("manager: 0=关闭（不布防）", async () => {
    const calls: RawPostCall[] = [];
    installMockClient(makeRawPostClient(calls));
    const mgr = makeManager(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: "0" }));
    mgr.onAsked({
      id: "per_off",
      sessionID: "ses_1",
      permission: "external_directory",
    });
    await sleep(400);
    assertEq(calls.length, 0, "关闭态不应请求");
    mgr.dispose();
  });

  await test("manager: onReplied 清理（用户已处理不重复拒绝）", async () => {
    const calls: RawPostCall[] = [];
    installMockClient(makeRawPostClient(calls));
    const mgr = makeManager(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: "0.3" }));
    mgr.onAsked({
      id: "per_replied",
      sessionID: "ses_1",
      permission: "external_directory",
    });
    mgr.onReplied({ requestID: "per_replied" });
    await sleep(700);
    assertEq(calls.length, 0, "已回复的请求不应被超时拒绝");
    mgr.dispose();
  });

  await test("manager: dispose 清理（无孤儿定时器）", async () => {
    const calls: RawPostCall[] = [];
    installMockClient(makeRawPostClient(calls));
    const mgr = makeManager(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: "0.3" }));
    mgr.onAsked({
      id: "per_dispose",
      sessionID: "ses_1",
      permission: "external_directory",
    });
    mgr.dispose();
    await sleep(700);
    assertEq(calls.length, 0, "dispose 后不应触发");
  });

  await test("manager: 底层 post 缺省→SDK 兜底通道", async () => {
    const calls: Array<{
      path: { id: string; permissionID: string };
      body: { response: string };
    }> = [];
    installMockClient({
      postSessionIdPermissionsPermissionId: async (input: {
        path: { id: string; permissionID: string };
        body: { response: string };
      }) => {
        calls.push(input);
        return true;
      },
    });
    const mgr = makeManager(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: "0.3" }));
    mgr.onAsked({
      id: "per_sdk",
      sessionID: "ses_9",
      permission: "external_directory",
    });
    await sleep(700);
    assertEq(calls.length, 1, "应调用 SDK 兜底通道");
    assertEq(calls[0].path.permissionID, "per_sdk", "permissionID 正确");
    assertEq(calls[0].path.id, "ses_9", "sessionID 正确");
    assertEq(calls[0].body.response, "reject", "response=reject");
    mgr.dispose();
  });

  await test("manager: client.permission.reply 探测优先（通道①）", async () => {
    const replyCalls: Array<{ requestID: string; reply: string; message?: string }> =
      [];
    const rawCalls: RawPostCall[] = [];
    installMockClient({
      ...makeRawPostClient(rawCalls),
      permission: {
        reply: async (input: { requestID: string; reply: string; message?: string }) => {
          replyCalls.push(input);
          return true;
        },
      },
    });
    const mgr = makeManager(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: "0.3" }));
    mgr.onAsked({
      id: "per_v2",
      sessionID: "ses_2",
      permission: "external_directory",
    });
    await sleep(700);
    assertEq(replyCalls.length, 1, "应走通道①");
    assertEq(replyCalls[0].reply, "reject", "reply=reject");
    assertEq(rawCalls.length, 0, "通道①成功不应再走底层 post");
    mgr.dispose();
  });

  await test("manager: 事件属性为 null/undefined 不抛（防御边界）", () => {
    const mgr = makeManager(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: "0.3" }));
    mgr.onAsked(null as unknown as Record<string, unknown>);
    mgr.onAsked(undefined as unknown as Record<string, unknown>);
    mgr.onReplied(null as unknown as Record<string, unknown>);
    mgr.onReplied(undefined as unknown as Record<string, unknown>);
    // 不抛即过（防御入口; 事件流中 properties 恒为对象，此为契约兜底）
    mgr.dispose();
  });

  await test("日志层健壮性: 异常 ctx（sessionManager 缺 get）布防不抛", () => {
    // 直接 init 空 sessionManager——debugLog 路由层契约（任何状态不抛）回归锁定
    ctx.init(
      {} as unknown as OpencodeClient,
      "/tmp/perm_timeout_test",
      {} as unknown as SessionDataManager,
    );
    const mgr = makeManager(readerOf({ PERMISSION_ASK_TIMEOUT_SEC: "0.3" }));
    mgr.onAsked({
      id: "per_logsafe",
      sessionID: "ses_1",
      permission: "external_directory",
    });
    // 布防日志走 debugLog(msg, sessionID) → getAgentName → 回退 DEFAULT_LOG，不抛
    mgr.dispose();
  });

  console.log(`\n通过 ${_passed} / 失败 ${_failed} / 总计 ${_passed + _failed}`);
  if (_failed > 0) {
    console.log("失败用例:\n" + _failures.join("\n"));
    process.exit(1);
  }
}

await main();
