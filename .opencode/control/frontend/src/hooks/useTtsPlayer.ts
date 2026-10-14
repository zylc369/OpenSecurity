/**
 * TTS 听书播放器 hook（段级协议客户端——Legado 业内模式）。
 *
 * 职责: 分段(segmentText) → 逐段 POST /api/tts（预取, ≤3 in-flight）
 *      → Audio 顺序接力播放 → 暂停/恢复/停止。
 * 服务端无状态; 单实例（新 start 自动停旧）; 段失败重试 1 次后停止并报错。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { segmentText } from "../utils/segmentText";

export type PlayerStatus = "idle" | "starting" | "playing" | "paused";

export interface TtsPlayerState {
  status: PlayerStatus;
  segIndex: number;    // 当前播放段（0-based）
  segTotal: number;
  buffered: number;    // 已下载完成、尚未播放的段数
  segProgress: number; // 当前段内播放进度 0~1
  error: string;
}

const INITIAL: TtsPlayerState = {
  status: "idle", segIndex: 0, segTotal: 0, buffered: 0, segProgress: 0, error: "",
};

const PREFETCH = 3; // in-flight 上限(服务端锁串行, 此值只控制客户端并发挂起量)

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

  const cleanup = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    for (const u of urlPool.current) URL.revokeObjectURL(u);
    urlPool.current = [];
    blobPromises.current = new Map();
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
        const r = await fetch("/api/tts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, speed: 1.0 }),
          signal,
        });
        if (!r.ok) throw new Error(`段 ${idx + 1} 合成失败 HTTP ${r.status}`);
        return await r.blob();
      } catch (e) {
        // 单次重试(网络抖动)
        const r2 = await fetch("/api/tts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, speed: 1.0 }),
          signal,
        });
        if (!r2.ok) throw new Error(`段 ${idx + 1} 合成失败 HTTP ${r2.status}`);
        return await r2.blob();
      }
    };
    p = doFetch();
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
      audioRef.current = audio;
      setState((s) => ({ ...s, status: "playing", segIndex: idx,
        segTotal: segsRef.current.length, error: "" }));
      audio.ontimeupdate = () => {
        setState((s) => s.segIndex === idx
          ? { ...s, segProgress: audio.duration
              ? audio.currentTime / audio.duration : 0 }
          : s);
      };
      audio.onended = () => {
        if (stoppedRef.current) return;
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

  const start = useCallback((text: string) => {
    stop(); // 单实例: 新试听停旧
    const segs = segmentText(text);
    if (segs.length === 0) {
      setState({ ...INITIAL, error: "文本为空（起始索引超出文件末尾?）" });
      return;
    }
    segsRef.current = segs;
    stoppedRef.current = false;
    pausedRef.current = false;
    const ac = new AbortController();
    abortRef.current = ac;
    setState({ ...INITIAL, status: "starting", segTotal: segs.length });
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

  const resume = useCallback(() => {
    pausedRef.current = false;
    void audioRef.current?.play();
    setState((s) => ({ ...s, status: "playing" }));
  }, []);

  return { state, start, pause, resume, stop };
}
