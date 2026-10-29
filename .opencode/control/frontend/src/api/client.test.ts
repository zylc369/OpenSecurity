import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 请求契约测试：URL 编码 / payload / params / 错误映射 / SSE 分帧。
 * axios 以 vi.mock 替换为记录型替身（不联网）；fetch 用 stubGlobal 注入流。
 */
const h = vi.hoisted(() => {
  type Call = { method: string; url: string; data?: unknown; params?: unknown };
  const calls: Call[] = [];
  let onRejected: ((e: unknown) => unknown) | undefined;
  const instance = {
    get: async (url: string, cfg?: { params?: unknown }) => {
      calls.push({ method: "get", url, params: cfg?.params });
      return { data: {} };
    },
    post: async (url: string, data?: unknown) => {
      calls.push({ method: "post", url, data });
      return { data: {} };
    },
    put: async (url: string, data?: unknown, cfg?: { params?: unknown }) => {
      calls.push({ method: "put", url, data, params: cfg?.params });
      return { data: {} };
    },
    delete: async (url: string, cfg?: { params?: unknown }) => {
      calls.push({ method: "delete", url, params: cfg?.params });
      return { data: {} };
    },
    interceptors: {
      response: {
        use: (_ok: unknown, rej: (e: unknown) => unknown) => {
          onRejected = rej;
        },
      },
    },
  };
  return { calls, instance, rejected: () => onRejected };
});

vi.mock("axios", () => ({ default: { create: () => h.instance } }));

import { api } from "./client";

beforeEach(() => {
  h.calls.length = 0;
});

describe("URL 编码与请求形状", () => {
  it("简单 GET 拼接路径", async () => {
    await api.getHardware();
    expect(h.calls[0]).toMatchObject({ method: "get", url: "/api/hardware" });
  });

  it("deleteConfig 走 POST /delete + 结构化 body（surfaces/keys 列表）", async () => {
    await api.deleteConfig("A/B C", "config");
    expect(h.calls[0]).toMatchObject({
      method: "post", url: "/api/config/delete",
      data: { surfaces: ["config"], keys: ["A/B C"] },
    });
  });

  it("updateConfig 走 POST /update + 结构化 body", async () => {
    await api.updateConfig({ X: "1" }, "config");
    expect(h.calls[0]).toMatchObject({
      method: "post", url: "/api/config/update",
      data: { surfaces: ["config"], configs: { X: "1" } },
    });
  });

  it("getConfigMeta 走 POST + surfaces 列表", async () => {
    await api.getConfigMeta("remote");
    expect(h.calls[0]).toMatchObject({
      method: "post", url: "/api/config/meta", data: { surfaces: ["remote"] },
    });
  });

  it("getConfig 走 POST /list + surfaces 列表", async () => {
    await api.getConfig("config");
    expect(h.calls[0]).toMatchObject({
      method: "post", url: "/api/config/list", data: { surfaces: ["config"] },
    });
  });

  it("getRequiredStatus 走 POST + surfaces 列表", async () => {
    await api.getRequiredStatus("config");
    expect(h.calls[0]).toMatchObject({
      method: "post", url: "/api/config/required-status", data: { surfaces: ["config"] },
    });
  });

  it("scan 的 force_refresh 走 query params", async () => {
    await api.scan(true);
    expect(h.calls[0]).toMatchObject({ method: "get", url: "/api/scan", params: { force_refresh: true } });
  });

  it("node=local 显式传递（node-config/autostart）", async () => {
    await api.updateNodeConfig({ CONTROL_RESIDENT: "1" }, "local");
    expect(h.calls[0]).toMatchObject({
      method: "put", url: "/api/remote/node-config",
      data: { configs: { CONTROL_RESIDENT: "1" } }, params: { node: "local" },
    });
    await api.getAutostart("local");
    expect(h.calls[1]).toMatchObject({ method: "get", url: "/api/remote/autostart", params: { node: "local" } });
  });

  it("fsCheck 的 path 原样进 params（不做编码，由 axios 处理）", async () => {
    await api.fsCheck("~/a b");
    expect(h.calls[0]).toMatchObject({ method: "get", url: "/api/fs/check", params: { path: "~/a b" } });
  });
});

describe("错误拦截器", () => {
  it("HTTP 错误 → Error(HTTP <status>: <detail 优先，否则 statusText>)", async () => {
    const rej = h.rejected();
    expect(rej).toBeDefined();
    await expect(
      rej!({ response: { status: 404, statusText: "Not Found", data: { detail: "配置项 X 不存在" } } }),
    ).rejects.toThrow("HTTP 404: 配置项 X 不存在");
  });

  it("HTTP 错误无 detail → 回落 statusText", async () => {
    await expect(
      h.rejected()!({ response: { status: 500, statusText: "Internal Server Error", data: undefined } }),
    ).rejects.toThrow("HTTP 500: Internal Server Error");
  });

  it("网络层错误（无 response）→ 原样透传", async () => {
    // axios 网络错误的 reject 值即 Error 本体（无 .response 属性）
    const orig = new Error("Network Error");
    await expect(h.rejected()!(orig)).rejects.toThrow("Network Error");
  });
});

function streamFrom(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch));
      c.close();
    },
  });
}

describe("pullImage SSE 解析", () => {
  it("跨 chunk 分帧 + 忽略非 data 行 + URL 编码", async () => {
    const signalRef: { s?: AbortSignal } = {};
    const fetchMock = vi.fn(async (_url: string, init?: { signal?: AbortSignal }) => {
      signalRef.s = init?.signal;
      // 帧被切在 "li" / "ne1" 之间——验证缓冲区拼接
      return { body: streamFrom(["data: li", "ne1\n\nevent: ping\n\ndata: line2\n\n"]) } as unknown as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    const got: string[] = [];
    api.pullImage("neo4j:5", (l) => got.push(l));
    await new Promise((r) => setTimeout(r, 30));

    expect(fetchMock).toHaveBeenCalledWith("/api/docker/images/neo4j%3A5/pull", expect.anything());
    expect(got).toEqual(["line1", "line2"]);

    vi.unstubAllGlobals();
  });

  it("abort → 不产生 __error__ 回调", async () => {
    const fetchMock = vi.fn(async () => {
      throw Object.assign(new Error("aborted"), { name: "AbortError" });
    });
    vi.stubGlobal("fetch", fetchMock);
    const got: string[] = [];
    api.pullImage("x", (l) => got.push(l));
    await new Promise((r) => setTimeout(r, 30));
    expect(got).toEqual([]);
    vi.unstubAllGlobals();
  });

  it("网络错误 → __error__ 前缀回调", async () => {
    const fetchMock = vi.fn(async () => {
      throw new Error("boom");
    });
    vi.stubGlobal("fetch", fetchMock);
    const got: string[] = [];
    api.pullImage("x", (l) => got.push(l));
    await new Promise((r) => setTimeout(r, 30));
    expect(got).toEqual(["__error__ boom"]);
    vi.unstubAllGlobals();
  });

  it("返回的停止函数会 abort 请求", async () => {
    const signalRef: { s?: AbortSignal } = {};
    vi.stubGlobal("fetch", vi.fn(async (_u: string, init?: { signal?: AbortSignal }) => {
      signalRef.s = init?.signal;
      return { body: streamFrom(["data: only\n\n"]) } as unknown as Response;
    }));
    const stop = api.pullImage("x", () => undefined);
    stop();
    expect(signalRef.s?.aborted).toBe(true);
    vi.unstubAllGlobals();
  });
});
