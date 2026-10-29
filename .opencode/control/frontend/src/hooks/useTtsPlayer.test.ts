// @vitest-environment jsdom
/**
 * useTtsPlayer 协议与状态机测试（jsdom + FakeAudio + fetch 记录）。
 *
 * 防线对应的真实故障形态:
 *  • 请求体漏字段: 试听重建时 voice 未透传——所有试听走服务端默认音色
 *  • 预取越层: 起播前后请求错发（协议: 起播前只发 seg0, 深度 1）
 *  • 自然播完不落态: 状态残留 "正在朗读"、预取轮询不退出
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";

import { useTtsPlayer } from "./useTtsPlayer";
import { FakeAudio, installTtsEnv, type TtsEnv } from "../test/hook-env";
import {
  DEFAULT_FIRST_LEN, DEFAULT_NEXT_LEN, rampFor, segmentText,
} from "../utils/segmentText";

/** 2 段（21 字 + 51 字→收 31/51——句边界整句成段） */
const TEXT2 = "甲".repeat(30) + "。" + "乙".repeat(50) + "。";
/** 3 段（每句均 ≥ 档位目标——21/61/81） */
const TEXT3 = "甲".repeat(20) + "。" + "乙".repeat(60) + "。" + "丙".repeat(80) + "。";

let env: TtsEnv;

function expectedSegCount(text: string): number {
  return segmentText(text, DEFAULT_NEXT_LEN, undefined,
    rampFor(DEFAULT_FIRST_LEN, DEFAULT_NEXT_LEN)).length;
}

beforeEach(() => {
  env = installTtsEnv();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("useTtsPlayer 协议与状态机", () => {
  it("请求体含全部字段且 voice 透传（漏参回归防线）", async () => {
    const { result } = renderHook(() => useTtsPlayer());
    act(() => {
      result.current.start(TEXT2, {
        voice: "my_voice", instruct: "小猪佩奇风格", seed: 42, mode: "instruct",
      });
    });
    await waitFor(() => expect(env.calls.length).toBeGreaterThanOrEqual(1));
    const body = env.calls[0].body;
    expect(body.voice).toBe("my_voice");
    expect(body.instruct).toBe("小猪佩奇风格");
    expect(body.seed).toBe(42);
    expect(body.mode).toBe("instruct");
    expect(body.speed).toBe(1.0);
    expect(typeof body.text).toBe("string");
    expect(String(body.text).length).toBeGreaterThan(0);
  });

  it("串行流水线: 首段立即; 慢首段时第二段 +1s 错峰; 返回驱动补段(在途≤2)", async () => {
    const { result } = renderHook(() => useTtsPlayer());
    env.holdText = "。";   // 全部挂起（慢合成——错峰与在途额度可观察）
    act(() => { result.current.start(TEXT3); });
    await waitFor(() => expect(env.calls.length).toBe(1));   // 首段立即
    const t0 = Date.now();
    await new Promise((r) => setTimeout(r, 500));
    expect(env.calls.length).toBe(1);                        // 500ms 内不补发（错峰窗口）
    await waitFor(() => expect(env.calls.length).toBe(2), { timeout: 1500 }); // ~1s: seg1
    expect(Date.now() - t0).toBeGreaterThanOrEqual(900);     // +1s 错峰（下界）
    await new Promise((r) => setTimeout(r, 300));
    expect(env.calls.length).toBe(2);                        // 无返回 → 在途 2 封顶（不起 seg2）
    await act(async () => { env.release(); });               // seg0 返回 → 返回驱动补 seg2
    await waitFor(() => expect(env.calls.length).toBe(3), { timeout: 1500 });
  });

  it("串行流水线: 快段返回驱动补段, 定时器不双发(每段恰一请求)", async () => {
    const { result } = renderHook(() => useTtsPlayer());
    act(() => { result.current.start(TEXT3); });
    await waitFor(() => expect(env.calls.length).toBe(3), { timeout: 2500 });
    await new Promise((r) => setTimeout(r, 1300));           // 跨过 seg1 的 +1s 定时器点
    const texts = env.calls.map((c) => String(c.body.text));
    expect(texts.length).toBe(3);                            // 无双发
    expect(new Set(texts).size).toBe(3);                     // 不重
  });

  it("stairs 阶梯参数: 优先于 firstLen/nextLen(段按阶梯序列切)", async () => {
    const { result } = renderHook(() => useTtsPlayer());
    // TEXT3 三句(21/61/81); stairs [30,120] → [21, 142] 两段; 若 5/5 的 firstLen/nextLen 生效则段数远多于 2
    act(() => { result.current.start(TEXT3, { stairs: [30, 120], firstLen: 5, nextLen: 5 }); });
    await waitFor(() => expect(env.calls.length).toBe(2));
    expect(String(env.calls[0].body.text)).toBe("甲".repeat(20) + "。");
    expect(env.calls.map((c) => String(c.body.text)).join("")).toBe(TEXT3);
  });

  it("段间等待: 下段未就绪 waiting=true, 就绪起播后清除", async () => {
    const { result } = renderHook(() => useTtsPlayer());
    env.holdText = "乙";  // seg1（乙段）挂起——制造未就绪等待窗口
    act(() => { result.current.start(TEXT3); });
    await waitFor(() => expect(FakeAudio.instances.length).toBe(1)); // seg0 起播（甲段正常）
    expect(result.current.state.waiting).toBe(false);
    await act(async () => { FakeAudio.instances[0].finish(1); });    // seg0 播完 → 等 seg1
    await waitFor(() => expect(result.current.state.waiting).toBe(true));
    expect(FakeAudio.instances.length).toBe(1);                      // seg1 未就绪，尚未起播
    await act(async () => { env.release(); });                       // 放行 seg1
    await waitFor(() => expect(FakeAudio.instances.length).toBe(2)); // seg1 起播
    expect(result.current.state.waiting).toBe(false);
  });

  it("顺序接力播放; 末段播完 status=idle（自然播完标记）", async () => {
    const { result } = renderHook(() => useTtsPlayer());
    act(() => { result.current.start(TEXT3); });
    const segCount = expectedSegCount(TEXT3);
    expect(segCount).toBe(3);
    await waitFor(() => expect(FakeAudio.instances.length).toBe(1));
    expect(result.current.state.status).toBe("playing");
    for (let i = 1; i < segCount; i++) {
      await act(async () => { FakeAudio.instances[i - 1].finish(1); });
      await waitFor(() => expect(FakeAudio.instances.length).toBe(i + 1));
    }
    await act(async () => { FakeAudio.instances[segCount - 1].finish(1); });
    await waitFor(() => expect(result.current.state.status).toBe("idle"));
  });

  it("网络失败自动重试一次后成功", async () => {
    env.failNextTimes = 1;
    const { result } = renderHook(() => useTtsPlayer());
    act(() => { result.current.start(TEXT3); });
    await waitFor(() => expect(FakeAudio.instances.length).toBe(1));
    expect(env.calls.length).toBe(4); // seg0 首发 + 立即预取 seg1/seg2 + seg0 重试（与预取并发，排在最后）
    const texts = env.calls.map((c) => c.body.text);
    expect(texts.filter((t) => t === texts[0]).length).toBe(2); // seg0 首发+重试（同段同参）
  });

  it("单段两次失败跳过继续（坏段不卡死）", async () => {
    env.failText = "甲";       // 定向失败：并发预取时序下 failNextTimes 会被无关请求消耗
    env.failTextTimes = 2;
    const { result } = renderHook(() => useTtsPlayer());
    act(() => { result.current.start(TEXT3); });
    await waitFor(() => expect(FakeAudio.instances.length).toBe(1)); // 起播的是 seg1（跳过 seg0）
    // seg0 首发 + seg1 + seg2 + seg0 重试（两次全败 → 跳过；跳过补泵 seg3=feeder 耗尽不发）
    expect(env.calls.length).toBe(4);
    expect(env.calls[2].body.text).not.toBe(env.calls[0].body.text); // 后续为下一段
    expect(result.current.state.segIndex).toBe(1); // 播放点确实前进到 seg1
  });

  it("来源标识回填（X-Tts-Source: remote → firstSegSource）", async () => {
    env.source = "remote";
    const { result } = renderHook(() => useTtsPlayer());
    act(() => { result.current.start(TEXT2); });
    await waitFor(() => expect(FakeAudio.instances.length).toBe(1));
    expect(result.current.state.firstSegSource).toBe("remote");
    expect(result.current.state.segSource).toBe("remote");
  });

  it("窗口回收: 播过的段释放对象 URL（长会话内存 O(窗口)）", async () => {
    const TEXT4 = "甲".repeat(20) + "。" + "乙".repeat(60) + "。"
      + "丙".repeat(80) + "。" + "丁".repeat(60) + "。";
    const { result } = renderHook(() => useTtsPlayer());
    act(() => { result.current.start(TEXT4); });
    expect(expectedSegCount(TEXT4)).toBe(4);
    for (let i = 0; i < 3; i++) {   // 播完 seg0..seg2 → 第 4 段（idx=3）起播
      await waitFor(() => expect(FakeAudio.instances.length).toBe(i + 1));
      await act(async () => { FakeAudio.instances[i].finish(1); });
    }
    // 窗口回收（k < idx-1 = {0,1}）: 恰好 revoke seg0/seg1 的 URL; 窗口内不误杀
    expect(env.revokeMock).toHaveBeenCalledTimes(2);
    expect(env.revokeMock).toHaveBeenCalledWith("blob:mock-1");
    expect(env.revokeMock).toHaveBeenCalledWith("blob:mock-2");
    expect(env.revokeMock).not.toHaveBeenCalledWith("blob:mock-3");
    // 收尾播放与自然结束不受影响
    await act(async () => { FakeAudio.instances[3].finish(1); });
    await waitFor(() => expect(result.current.state.status).toBe("idle"));
  });

  it("长文本全播放: 段请求序列不重不漏（拼接回原文）", async () => {
    const { result } = renderHook(() => useTtsPlayer());
    act(() => { result.current.start(TEXT3); });
    const segCount = expectedSegCount(TEXT3);
    for (let i = 0; i < segCount; i++) {
      await waitFor(() => expect(FakeAudio.instances.length).toBe(i + 1));
      await act(async () => { FakeAudio.instances[i].finish(1); });
    }
    await waitFor(() => expect(result.current.state.status).toBe("idle"));
    const texts = env.calls.map((c) => c.body.text as string);
    expect(texts.length).toBe(segCount);   // 不重
    expect(texts.join("")).toBe(TEXT3);    // 不漏（分段无损）
  });

  it("重启会话隔离: 旧请求 abort 不污染新会话（B 全部正常播放）", async () => {
    const { result } = renderHook(() => useTtsPlayer());
    env.holdText = "。";                     // A 会话全部挂起（在途请求滞留）
    act(() => { result.current.start(TEXT3); });
    await waitFor(() => expect(env.calls.length).toBe(1));   // A seg0 在途
    await new Promise((r) => setTimeout(r, 1100));           // A 的 +1s 定时器也发出 seg1
    expect(env.calls.length).toBe(2);
    env.holdText = "";                       // B 会话不挂起
    act(() => { result.current.start(TEXT3); });             // 重启（A 被 abort）
    await waitFor(() => expect(FakeAudio.instances.length).toBe(1)); // B seg0 起播
    expect(result.current.state.error).toBe("");             // B 无失败段
    // 留出旧 finally/定时器的污染窗口
    await new Promise((r) => setTimeout(r, 700));
    // B 三段完整播放（无跳过、无提前停止）
    const segCount = expectedSegCount(TEXT3);
    for (let i = 1; i < segCount; i++) {
      await act(async () => { FakeAudio.instances[i - 1].finish(1); });
      await waitFor(() => expect(FakeAudio.instances.length).toBe(i + 1));
    }
    await act(async () => { FakeAudio.instances[segCount - 1].finish(1); });
    await waitFor(() => expect(result.current.state.status).toBe("idle"));
  });

  it("stop 清场: 状态回 idle 且已 revoke 对象 URL", async () => {
    const { result } = renderHook(() => useTtsPlayer());
    act(() => { result.current.start(TEXT2); });
    await waitFor(() => expect(FakeAudio.instances.length).toBe(1));
    act(() => { result.current.stop(); });
    expect(result.current.state.status).toBe("idle");
    expect(env.revokeMock).toHaveBeenCalled();
  });
});
