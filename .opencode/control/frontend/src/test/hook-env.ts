/**
 * TTS 播放器 hook 测试环境（jsdom 缺件补齐）。
 *
 * - FakeAudio: 可编程音频元素——测试手动触发 ended/metadata 驱动播放状态机
 *   （jsdom 无真实音频栈; 本层锁定"协议与状态机"而非音频引擎行为）
 * - installTtsEnv(): fetch / Audio / URL.createObjectURL stub + 调用记录
 *   （请求体契约断言用——字段缺失类回归的防线）
 */
import { vi } from "vitest";

/** 可控音频元素（记录实例以便测试按序驱动）。 */
export class FakeAudio {
  static instances: FakeAudio[] = [];

  static reset(): void {
    FakeAudio.instances = [];
  }

  src: string;
  duration = NaN;
  currentTime = 0;
  playbackRate = 1;
  preservesPitch = true;
  onended: (() => void) | null = null;
  onloadedmetadata: (() => void) | null = null;
  ontimeupdate: (() => void) | null = null;
  onerror: (() => void) | null = null;
  play = vi.fn((): Promise<void> => Promise.resolve());
  pause = vi.fn((): void => { /* noop */ });

  constructor(src: string) {
    this.src = src;
    FakeAudio.instances.push(this);
  }

  /** 模拟本段播放结束（先回填时长再触发 ended——与真实事件序一致）。 */
  finish(duration = 1): void {
    this.duration = duration;
    this.currentTime = duration;
    this.onloadedmetadata?.();
    this.onended?.();
  }
}

type FetchInit = { body?: string } | undefined;
type FetchMock = (url: string, init?: FetchInit) => Promise<unknown>;

export interface TtsEnv {
  /** 全部 /api/tts 请求记录（顺序 + 请求体）。 */
  calls: { url: string; body: Record<string, unknown> }[];
  /** >0 时接下来的 N 次 fetch 返回 HTTP 500（失败路径测试用）。 */
  failNextTimes: number;
  /** 响应头 X-Tts-Source 值（"local"/"remote"——来源标识测试用）。 */
  source: string;
  /** revokeObjectURL 调用记录。 */
  revokeMock: ReturnType<typeof vi.fn>;
  /** 命中该子串的请求挂起（不返回）——release() 放行，制造"未就绪等待窗口"。 */
  holdText: string;
  /** 放行全部挂起请求（依次 resolve）。 */
  release: () => void;
  /** 命中该子串的请求按 failTextTimes 计数失败（定向失败——并发预取下
   *  failNextTimes 会被无关请求消耗，无法精确打在目标段上）。 */
  failText: string;
  failTextTimes: number;
}

function mkResp(status: number, blob: Blob | null, source: string): unknown {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get: (k: string): string | null =>
        k.toLowerCase() === "x-tts-source" ? source : null,
    },
    blob: async (): Promise<Blob> => blob ?? new Blob([]),
  };
}

/** 装载环境（调用方在 afterEach 里 vi.unstubAllGlobals()）。 */
export function installTtsEnv(): TtsEnv {
  FakeAudio.reset();
  const calls: TtsEnv["calls"] = [];
  const state = { failNextTimes: 0, source: "local", holdText: "",
                  failText: "", failTextTimes: 0 };
  let held: (() => void)[] = [];
  const revokeMock = vi.fn();

  const fetchMock = vi.fn<FetchMock>(async (url: string, init?: FetchInit) => {
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    calls.push({ url, body });
    if (state.failNextTimes > 0) {
      state.failNextTimes -= 1;
      return mkResp(500, null, "");
    }
    if (state.failText && state.failTextTimes > 0
        && String(body.text).includes(state.failText)) {
      state.failTextTimes -= 1;
      return mkResp(500, null, "");
    }
    if (state.holdText && String(body.text).includes(state.holdText)) {
      const b = new Blob([new Uint8Array([1, 2])], { type: "audio/wav" });
      return new Promise<unknown>((resolve) => {
        held.push(() => resolve(mkResp(200, b, state.source)));
      });
    }
    return mkResp(200, new Blob([new Uint8Array([1, 2])], { type: "audio/wav" }),
                  state.source);
  });

  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("Audio", FakeAudio);
  let urlSeq = 0;  // 自增 URL（测试可精确断言回收了哪些段）
  URL.createObjectURL = vi.fn((_b: Blob | MediaSource): string => `blob:mock-${++urlSeq}`);
  URL.revokeObjectURL = revokeMock as unknown as typeof URL.revokeObjectURL;

  return {
    get calls() { return calls; },
    get failNextTimes() { return state.failNextTimes; },
    set failNextTimes(v: number) { state.failNextTimes = v; },
    get source() { return state.source; },
    set source(v: string) { state.source = v; },
    get holdText() { return state.holdText; },
    set holdText(v: string) { state.holdText = v; },
    get failText() { return state.failText; },
    set failText(v: string) { state.failText = v; },
    get failTextTimes() { return state.failTextTimes; },
    set failTextTimes(v: number) { state.failTextTimes = v; },
    release: () => { const h = held; held = []; h.forEach((f) => f()); },
    revokeMock,
  };
}
