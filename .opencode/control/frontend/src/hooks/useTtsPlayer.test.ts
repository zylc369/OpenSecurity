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

  it("播放驱动预取: 起播前只发 seg0, 起播后恰好预取 seg1（深度 1 不超前）", async () => {
    const { result } = renderHook(() => useTtsPlayer());
    act(() => { result.current.start(TEXT3); });
    await waitFor(() => expect(env.calls.length).toBe(1));           // 点击只发 seg0
    await waitFor(() => expect(FakeAudio.instances.length).toBe(1)); // seg0 起播
    await waitFor(() => expect(env.calls.length).toBe(2));           // 起播后预取 seg1
    await new Promise((r) => setTimeout(r, 600));                    // 跑满一个 500ms 保底周期
    expect(env.calls.length).toBe(2);                                // 不超前 seg2（含保底轮询）
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
    act(() => { result.current.start(TEXT2); });
    await waitFor(() => expect(FakeAudio.instances.length).toBe(1));
    expect(env.calls.length).toBe(3); // seg0 首发 + seg0 重试 + 起播后 seg1 预取
    expect(env.calls[0].body.text).toBe(env.calls[1].body.text); // 重试=同段同参
  });

  it("单段两次失败跳过继续（坏段不卡死）", async () => {
    env.failNextTimes = 2;
    const { result } = renderHook(() => useTtsPlayer());
    act(() => { result.current.start(TEXT3); });
    await waitFor(() => expect(FakeAudio.instances.length).toBe(1)); // 起播的是 seg1（跳过 seg0）
    // seg0 首发 + seg0 重试 + seg1 + seg2（跳过使播放点前移，预取链随之到播放点+1）
    expect(env.calls.length).toBe(4);
    expect(env.calls[2].body.text).not.toBe(env.calls[0].body.text); // 后续为下一段
    expect(result.current.state.segIndex).toBe(1); // 播放点确实前进到 seg1
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
