/**
 * TTS 听书播放器 hook（段级协议客户端——Legado 业内模式）。
 *
 * 职责: 分段(segmentText) → 逐段 POST /api/tts（预取, ≤3 in-flight）
 *      → Audio 顺序接力播放 → 暂停/恢复/停止。
 * 服务端无状态; 单实例（新 start 自动停旧）; 段失败重试 1 次后停止并报错。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { rampFor, segmentText } from "../utils/segmentText";

export type PlayerStatus = "idle" | "starting" | "playing" | "paused";

export interface TtsPlayerState {
  speed: number;        // 播放倍速(1.0=原速——音频文件不改, 播放端保持音高变速)
  status: PlayerStatus;
  segIndex: number;    // 当前播放段（0-based）
  segTotal: number;
  buffered: number;    // 已下载完成、尚未播放的段数
  segProgress: number; // 当前段内播放进度 0~1
  error: string;
  elapsedSec: number;  // 已播放时长（已完成段 + 当前段进度）
  totalSec: number;    // 总时长（已知段 duration + 未生成段按 0.2s/字估算）
  firstSegMs: number;  // 首段生成耗时（完成即定格——首响指标）
  avgGenMs: number;    // 平均每段生成耗时
  startTick: number;   // start() 时刻（starting 计时, ms）
}

const INITIAL: TtsPlayerState = {
  speed: 1.0,
  status: "idle", segIndex: 0, segTotal: 0, buffered: 0, segProgress: 0, error: "",
  elapsedSec: 0, totalSec: 0, firstSegMs: 0, avgGenMs: 0, startTick: 0,
};

/** 中文朗读估速（秒/字）——未生成段总时长估算用 */
const SEC_PER_CHAR = 0.2;

const PREFETCH = 3; // in-flight 上限(服务端锁串行, 此值只控制客户端并发挂起量)

/** 试听可选参数(测试台): 朗读指令/采样种子/分段字长 */
export interface StartOptions {
  instruct?: string; // 朗读指令(空=引擎默认"请用正常语速说一句话")
  seed?: number;     // 采样种子(≤0=默认 4)
  firstLen?: number; // 首段字数(默认 30)
  nextLen?: number;  // 常规段字数(默认 300)
}

/** 总时长 = 已知段真实时长 + 未生成段按字数估算 */
function computeTotalOf(segs: readonly string[], durations: readonly number[]): number {
  let total = 0;
  for (let i = 0; i < segs.length; i++) {
    total += durations[i] ?? segs[i].length * SEC_PER_CHAR;
  }
  return total;
}

export function useTtsPlayer() {
  const [state, setState] = useState<TtsPlayerState>(INITIAL);

  const segsRef = useRef<string[]>([]);
  const blobPromises = useRef<Map<number, Promise<Blob>>>(new Map());
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const nextPlayRef = useRef(0);
  const nextFetchRef = useRef(0);
  const pausedRef = useRef(false);
  const stoppedRef = useRef(true);
  const urlPool = useRef<string[]>([]);
  const errCount = useRef(0);
  const speedRef = useRef(1.0);
  const optsRef = useRef<StartOptions>({});
  const segDurations = useRef<number[]>([]);   // 已知段真实时长
  const elapsedBase = useRef(0);               // 已完成段时长累计
  const genMsList = useRef<number[]>([]);      // 每段生成耗时

  const cleanup = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    for (const u of urlPool.current) URL.revokeObjectURL(u);
    urlPool.current = [];
    blobPromises.current = new Map();
    segDurations.current = [];
    elapsedBase.current = 0;
    genMsList.current = [];
    nextPlayRef.current = 0;
    nextFetchRef.current = 0;
    errCount.current = 0;
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

  const fetchSeg = useCallback((idx: number, signal: AbortSignal): Promise<Blob> => {
    let p = blobPromises.current.get(idx);
    if (p) return p;
    const text = segsRef.current[idx];
    const doFetch = async (): Promise<Blob> => {
      try {
        const body = JSON.stringify({
          text, speed: 1.0,
          instruct: optsRef.current.instruct ?? "",
          seed: optsRef.current.seed ?? -1,
        });
        const r = await fetch("/api/tts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
          signal,
        });
        if (!r.ok) throw new Error(`段 ${idx + 1} 合成失败 HTTP ${r.status}`);
        return await r.blob();
      } catch (e) {
        if (signal.aborted) throw e; // 停止指令不重试
        // 单次重试(网络抖动)
        const body = JSON.stringify({
          text, speed: 1.0,
          instruct: optsRef.current.instruct ?? "",
          seed: optsRef.current.seed ?? -1,
        });
        const r2 = await fetch("/api/tts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
          signal,
        });
        if (!r2.ok) throw new Error(`段 ${idx + 1} 合成失败 HTTP ${r2.status}`);
        return await r2.blob();
      }
    };
    const t0 = performance.now();
    p = doFetch().then((b) => {
      genMsList.current[idx] = performance.now() - t0;
      setState((s) => ({ ...s, buffered: Math.max(0,
        genMsList.current.filter((x) => x > 0).length - nextPlayRef.current - 1) }));
      return b;
    });
    blobPromises.current.set(idx, p);
    return p;
  }, []);

  const playSeg = useCallback((idx: number, signal: AbortSignal) => {
    if (stoppedRef.current || idx >= segsRef.current.length) {
      setState((s) => ({ ...s, status: "idle" }));
      return;
    }
    nextPlayRef.current = idx;
    fetchSeg(idx, signal).then((blob) => {
      if (stoppedRef.current || signal.aborted) return;
      const url = URL.createObjectURL(blob);
      urlPool.current.push(url);
      const audio = new Audio(url);
      audio.preservesPitch = true;   // 变速保音调(标准播放器语义)
      audio.playbackRate = speedRef.current;
      urlPool.current.push(url);
      audioRef.current = audio;
      const dur = Number.isFinite(audio.duration) ? audio.duration
        : segsRef.current[idx].length * SEC_PER_CHAR;
      segDurations.current[idx] = dur;
      const gens = genMsList.current.filter((x) => x > 0);
      setState((s) => ({
        ...s, status: "playing", segIndex: idx,
        segTotal: segsRef.current.length, error: "",
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
              totalSec: computeTotalOf(segsRef.current, segDurations.current),
            }
          : s);
      };
      audio.onended = () => {
        if (stoppedRef.current) return;
        elapsedBase.current += dur;
        playSeg(idx + 1, signal);
      };
      audio.onerror = () => {
        setState((s) => ({ ...s, error: `段 ${idx + 1} 播放失败` }));
      };
      void audio.play();
    }).catch((e: unknown) => {
      if (stoppedRef.current || signal.aborted) return;
      errCount.current += 1;
      const msg = e instanceof Error ? e.message : String(e);
      if (errCount.current >= 3) {
        stop();
        setState((s) => ({ ...s, error: `${msg}（连续失败已停止）` }));
      } else {
        setState((s) => ({ ...s, error: `${msg}（跳过）` }));
        playSeg(idx + 1, signal); // 跳过坏段继续
      }
    });
  }, [fetchSeg, stop]);

  const start = useCallback((text: string, opts?: StartOptions) => {
    stop(); // 单实例: 新试听停旧
    optsRef.current = opts ?? {};
    const nextLen = opts?.nextLen ?? 300;
    const firstTargets = opts?.firstLen ? rampFor(opts.firstLen, nextLen) : undefined;
    const segs = segmentText(text, nextLen, undefined, firstTargets);
    if (segs.length === 0) {
      setState({ ...INITIAL, error: "文本为空（起始索引超出文件末尾?）" });
      return;
    }
    segsRef.current = segs;
    stoppedRef.current = false;
    pausedRef.current = false;
    const ac = new AbortController();
    abortRef.current = ac;
    setState({ ...INITIAL, status: "starting", segTotal: segs.length,
      startTick: Date.now(), totalSec: segs.reduce(
        (a, s) => a + s.length * SEC_PER_CHAR, 0) });
    // 预取: 立即挂起后续段(≤PREFETCH in-flight)
    const pump = () => {
      while (!stoppedRef.current
             && nextFetchRef.current < segs.length
             && nextFetchRef.current - nextPlayRef.current < PREFETCH) {
        const i = nextFetchRef.current;
        fetchSeg(i, ac.signal).catch(() => { /* playSeg 侧统一处理 */ });
        nextFetchRef.current += 1;
      }
    };
    pump();
    const timer = window.setInterval(() => { // 播放推进后继续补预取
      if (stoppedRef.current) { window.clearInterval(timer); return; }
      pump();
    }, 500);
    // 首段起播; interval 在 stoppedRef 置位后下一拍自杀(≤500ms 残留, 可接受)
    playSeg(0, ac.signal);
  }, [fetchSeg, playSeg, stop]);

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
