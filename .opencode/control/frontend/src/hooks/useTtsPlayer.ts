/**
 * TTS 听书播放器 hook（段级协议客户端——Legado 业内模式）。
 *
 * 职责: 分段(segmentText) → 逐段 POST /api/tts（播放驱动预取, 深度 1:
 *      播第 N 段时挂出第 N+1 段） → Audio 顺序接力播放 → 暂停/恢复/停止。
 * 服务端无状态; 单实例（新 start 自动停旧）; 单段网络失败重试 1 次,
 * 仍失败跳过该段继续, 累计 3 段失败停止并报错。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { DEFAULT_FIRST_LEN, DEFAULT_NEXT_LEN, createSegmentFeeder, rampFor,
  type SegmentFeeder } from "../utils/segmentText";

export type PlayerStatus = "idle" | "starting" | "playing" | "paused";

export interface TtsPlayerState {
  speed: number;        // 播放倍速(1.0=原速——音频文件不改, 播放端保持音高变速)
  status: PlayerStatus;
  segIndex: number;    // 当前播放段（0-based——"已读 N 段"= segIndex+1）
  buffered: number;    // 已下载完成、尚未播放的段数
  segProgress: number; // 当前段内播放进度 0~1
  error: string;
  elapsedSec: number;  // 已播放时长（已完成段 + 当前段进度——纯增量语义）
  firstSegMs: number;  // 首段生成耗时（完成即定格——首响指标）
  avgGenMs: number;    // 平均每段生成耗时
  startTick: number;   // start() 时刻（starting 计时, ms）
  segSource: string;   // 当前段生成来源（"remote"/"local"——服务端 X-Tts-Source）
  firstSegSource: string;  // 首段生成来源（首响指标配套）
}

const INITIAL: TtsPlayerState = {
  speed: 1.0,
  status: "idle", segIndex: 0, buffered: 0, segProgress: 0, error: "",
  elapsedSec: 0, firstSegMs: 0, avgGenMs: 0, startTick: 0,
  segSource: "", firstSegSource: "",
};

/** 中文朗读估速（秒/字）——当前段真实时长未就绪时的兜底估算 */
const SEC_PER_CHAR = 0.2;

// 播放驱动预取深度: 播第 N 段时最多挂到第 N+PREFETCH_DEPTH 段。
// 本地合成为单 GPU 串行队列(远程独立)——多挂无收益; 生成耗时≈播放时长×0.3(RTF),
// 深度 1 正常富余 3 倍, 停播时最多浪费 1 段。
const PREFETCH_DEPTH = 1;

/** 试听可选参数(测试台): 朗读指令/采样种子/分段字长 */
export interface StartOptions {
  voice?: string;    // 音色库 id(空=服务端默认音色)
  instruct?: string; // 朗读指令仅 instruct 模式用(空=引擎默认"请用正常语速朗读接下来的内容。")
  seed?: number;     // 采样种子(≤0=默认 4)
  firstLen?: number; // 首段字数(默认 20)
  nextLen?: number;  // 常规段字数(默认 80)
  mode?: string;     // 合成模式(""=默认 zero_shot 情感饱满; "instruct"=指令控制)
}

export function useTtsPlayer() {
  const [state, setState] = useState<TtsPlayerState>(INITIAL);

  const feederRef = useRef<SegmentFeeder | null>(null);
  const producedRef = useRef<Map<number, string>>(new Map());  // 段文本窗口（播过即回收）
  const producedCountRef = useRef(0);   // feeder 已喂出段数（单调递增的段游标）
  const finishedRef = useRef(false);    // feeder 耗尽（文本结束）
  const blobPromises = useRef<Map<number, Promise<Blob>>>(new Map());
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const nextPlayRef = useRef(0);
  const nextFetchRef = useRef(0);
  const pausedRef = useRef(false);
  const stoppedRef = useRef(true);
  const segUrlRef = useRef<Map<number, string>>(new Map());  // 段→objectURL（仅播放窗口内保留）
  const errCount = useRef(0);
  const speedRef = useRef(1.0);
  const optsRef = useRef<StartOptions>({});
  const playingStartedRef = useRef(false);     // 首段音频就绪开播后才允许预取
  const waitStartRef = useRef<number | null>(null);  // 段间缓冲等待起点(performance.now)
  const elapsedBase = useRef(0);               // 已完成段时长累计
  const genMsList = useRef<number[]>([]);      // 每段生成耗时
  const segSourceRef = useRef<string[]>([]);   // 每段来源（响应头 X-Tts-Source）

  const cleanup = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    for (const u of segUrlRef.current.values()) URL.revokeObjectURL(u);
    segUrlRef.current = new Map();
    blobPromises.current = new Map();
    elapsedBase.current = 0;
    genMsList.current = [];
    producedRef.current = new Map();
    producedCountRef.current = 0;
    finishedRef.current = false;
    feederRef.current = null;
    segSourceRef.current = [];
    nextPlayRef.current = 0;
    nextFetchRef.current = 0;
    errCount.current = 0;
    playingStartedRef.current = false;
    waitStartRef.current = null;
  }, []);

  const stop = useCallback(() => {
    stoppedRef.current = true;
    pausedRef.current = false;
    abortRef.current?.abort();
    abortRef.current = null;
    cleanup();
    setState(INITIAL);
  }, [cleanup]);

  useEffect(() => stop, [stop]); // 卸载即停

  /** 惰性喂段: 确保第 idx 段文本已从 feeder 取出; undefined=再无更多（文本结束）。 */
  const ensureSegment = useCallback((idx: number): string | undefined => {
    while (producedCountRef.current <= idx && !finishedRef.current) {
      const s = feederRef.current?.next() ?? null;
      if (s === null) { finishedRef.current = true; break; }
      producedRef.current.set(producedCountRef.current, s);
      producedCountRef.current++;
    }
    return producedRef.current.get(idx);
  }, []);

  const fetchSeg = useCallback((idx: number, signal: AbortSignal): Promise<Blob> => {
    let p = blobPromises.current.get(idx);
    if (p) return p;
    const text = producedRef.current.get(idx) ?? "";
    // 合成请求体统一构造(与重试共用——省字段漂移)
    const buildBody = (): string => JSON.stringify({
      text, speed: 1.0,
      voice: optsRef.current.voice ?? "",
      instruct: optsRef.current.instruct ?? "",
      seed: optsRef.current.seed ?? -1,
      mode: optsRef.current.mode ?? "",
    });
    const doFetch = async (): Promise<Blob> => {
      try {
        const body = buildBody();
        const r = await fetch("/api/tts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
          signal,
        });
        if (!r.ok) throw new Error(`段 ${idx + 1} 合成失败 HTTP ${r.status}`);
        segSourceRef.current[idx] = r.headers.get("X-Tts-Source") ?? "";
        return await r.blob();
      } catch (e) {
        if (signal.aborted) throw e; // 停止指令不重试
        // 单次重试(网络抖动)
        const body = buildBody();
        const r2 = await fetch("/api/tts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
          signal,
        });
        if (!r2.ok) throw new Error(`段 ${idx + 1} 合成失败 HTTP ${r2.status}`);
        segSourceRef.current[idx] = r2.headers.get("X-Tts-Source") ?? "";
        return await r2.blob();
      }
    };
    const t0 = performance.now();
    console.log(`[tts] seg${idx} 合成请求发出（${text.length}字）`);
    p = doFetch().then((b) => {
      const ms = performance.now() - t0;
      console.log(`[tts] seg${idx} 合成返回 +${ms.toFixed(0)}ms`);
      genMsList.current[idx] = ms;
      setState((s) => ({ ...s, buffered: Math.max(0,
        genMsList.current.filter((x) => x > 0).length - nextPlayRef.current - 1) }));
      return b;
    });
    blobPromises.current.set(idx, p);
    return p;
  }, []);

  // 播放驱动预取: 保证 nextPlay+1 已挂起(经 pumpRef 供 playSeg 调用)
  const pumpRef = useRef<() => void>(() => { /* start() 内替换 */ });

  const playSeg = useCallback((idx: number, signal: AbortSignal) => {
    // stop 指令/旧会话回调: 只退出不改状态（idle 落态由 stop() 与
    // feeder 耗尽分支负责——旧会话的 setState 会错打在新会话上）
    if (stoppedRef.current || signal.aborted) return;
    const text = ensureSegment(idx);
    if (text === undefined) {   // 自然播完(非 stop 指令——feeder 耗尽)
      stoppedRef.current = true; // 标记后预取轮询自查清退
      console.log("[tts] 全部段播放完成");
      setState((s) => ({ ...s, status: "idle" }));
      return;
    }
    nextPlayRef.current = idx;
    // 窗口回收: 段文本与音频资源只保留播放位附近（内存 O(窗口)——
    // 长书连续听不再线性增长; 收听模型为"向后连读、无回退", 播过即安全释放）
    for (const k of Array.from(producedRef.current.keys())) {
      if (k < idx - 1) producedRef.current.delete(k);
    }
    for (const k of Array.from(segUrlRef.current.keys())) {
      if (k < idx - 1) {
        URL.revokeObjectURL(segUrlRef.current.get(k) as string);
        segUrlRef.current.delete(k);
      }
    }
    for (const k of Array.from(blobPromises.current.keys())) {
      if (k < idx - 1) blobPromises.current.delete(k);  // 失败段（无 URL）同样窗口化
    }
    fetchSeg(idx, signal).then((blob) => {
      if (stoppedRef.current || signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const oldUrl = segUrlRef.current.get(idx);
      if (oldUrl) URL.revokeObjectURL(oldUrl);  // 防重入兜底（同段二次路径）
      segUrlRef.current.set(idx, url);
      const audio = new Audio(url);
      audio.preservesPitch = true;   // 变速保音调(标准播放器语义)
      audio.playbackRate = speedRef.current;
      audioRef.current = audio;
      const dur = Number.isFinite(audio.duration) ? audio.duration
        : text.length * SEC_PER_CHAR;
      const gens = genMsList.current.filter((x) => x > 0);
      setState((s) => ({
        ...s, status: "playing", segIndex: idx,
        error: "",
        segSource: segSourceRef.current[idx] ?? "",
        firstSegSource: segSourceRef.current[0] ?? s.firstSegSource,
        firstSegMs: genMsList.current[0] ?? s.firstSegMs,
        avgGenMs: gens.length
          ? Math.round(gens.reduce((a, b) => a + b, 0) / gens.length) : s.avgGenMs,
      }));
      audio.ontimeupdate = () => {
        if (audio !== audioRef.current) return;
        setState((s) => s.segIndex === idx
          ? {
              ...s,
              segProgress: audio.duration
                ? audio.currentTime / audio.duration : 0,
              elapsedSec: elapsedBase.current + audio.currentTime,
            }
          : s);
      };
      audio.onended = () => {
        if (stoppedRef.current) return;
        console.log(`[tts] seg${idx} 播放结束`);
        waitStartRef.current = performance.now();  // 若下一段未就绪, 记录等待起点
        elapsedBase.current += dur;
        playSeg(idx + 1, signal);
      };
      audio.onerror = () => {
        setState((s) => ({ ...s, error: `段 ${idx + 1} 播放失败` }));
      };
      void audio.play();
      // 播放驱动预取: 开播后挂下一段(以及首播时激活预取管道)
      playingStartedRef.current = true;
      if (waitStartRef.current !== null) {
        console.log(`[tts] seg${idx} 开始播放（缓冲等待 ${(performance.now() - waitStartRef.current).toFixed(0)}ms）`);
        waitStartRef.current = null;
      } else {
        console.log(`[tts] seg${idx} 开始播放（无缝）`);
      }
      pumpRef.current();
    }).catch((e: unknown) => {
      if (stoppedRef.current || signal.aborted) return;
      errCount.current += 1;
      const msg = e instanceof Error ? e.message : String(e);
      if (errCount.current >= 3) {
        stop();
        setState((s) => ({ ...s, error: `${msg}（累计失败 3 次已停止）` }));
      } else {
        setState((s) => ({ ...s, error: `${msg}（跳过）` }));
        playSeg(idx + 1, signal); // 跳过坏段继续
      }
    });
  }, [ensureSegment, fetchSeg, stop]);

  const start = useCallback((text: string, opts?: StartOptions) => {
    stop(); // 单实例: 新试听停旧
    optsRef.current = opts ?? {};
    const nextLen = opts?.nextLen ?? DEFAULT_NEXT_LEN;
    const firstTargets = rampFor(opts?.firstLen ?? DEFAULT_FIRST_LEN, nextLen);
    console.log(`[tts] 模式=${opts?.mode || "默认(zero_shot)"} 首段目标=${opts?.firstLen ?? DEFAULT_FIRST_LEN}字 常规段=${nextLen}字`);
    // 惰性分段: 不预切全文——播放路径只依赖"下一段"（真实听书场景: 选起点向后连读）
    feederRef.current = createSegmentFeeder(text, nextLen, undefined, firstTargets);
    producedRef.current = new Map();
    producedCountRef.current = 0;
    finishedRef.current = false;
    if (ensureSegment(0) === undefined) {
      setState({ ...INITIAL, error: "文本为空（起始索引超出文件末尾?）" });
      return;
    }
    stoppedRef.current = false;
    pausedRef.current = false;
    const ac = new AbortController();
    abortRef.current = ac;
    setState({ ...INITIAL, status: "starting", startTick: Date.now() });
    // 播放驱动预取: 播放未开始前不挂任何后续段(点击后先让首段可用);
    // 开播后由 playSeg 每次推进时调用 pump——挂到 nextPlay+PREFETCH_DEPTH。
    const pump = () => {
      if (!playingStartedRef.current) return;
      while (!stoppedRef.current
             && nextFetchRef.current <= nextPlayRef.current + PREFETCH_DEPTH) {
        const i = nextFetchRef.current;
        if (ensureSegment(i) === undefined) break;  // feeder 耗尽
        console.log(`[tts] seg${i} 预取发出（播放点 seg${nextPlayRef.current}）`);
        fetchSeg(i, ac.signal).catch(() => { /* playSeg 侧统一处理 */ });
        nextFetchRef.current += 1;
      }
    };
    pumpRef.current = pump;
    const timer = window.setInterval(() => { // 保底: 播放推进后补预取
      if (stoppedRef.current) { window.clearInterval(timer); return; }
      pump();
    }, 500);
    // 只发首段; 后续段在播放点到达时续发(惰性预取)
    fetchSeg(0, ac.signal).catch(() => { /* playSeg 侧统一处理 */ });
    nextFetchRef.current = 1; // 游标与已请求区间同步(预取从 seg1 起, 避免假挂起)
    playSeg(0, ac.signal);
  }, [ensureSegment, fetchSeg, playSeg, stop]);

  const pause = useCallback(() => {
    pausedRef.current = true;
    audioRef.current?.pause();
    setState((s) => ({ ...s, status: "paused" }));
  }, []);

  const setSpeed = useCallback((v: number) => {
    speedRef.current = v;
    if (audioRef.current) {
      audioRef.current.preservesPitch = true;
      audioRef.current.playbackRate = v;
    }
    setState((s) => ({ ...s, speed: v }));
  }, []);

  const resume = useCallback(() => {
    pausedRef.current = false;
    void audioRef.current?.play();
    setState((s) => ({ ...s, status: "playing" }));
  }, []);

  return { state, start, pause, resume, stop, setSpeed };
}
