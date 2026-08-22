/**
 * 自定义 hooks 收口。
 *
 * 组件通过 hooks 拿数据，不直接调 api 对象（统一数据获取层）。
 */
import { useEffect, useState, useCallback, useRef } from "react";
import { api } from "../api/client";
import type {
  HardwareInfo, RequiredStatusMap, ScanResult, ConfigMap,
  SystemInfo, ModelsResponse, ConfigMetaMap,
} from "../types";

/** 硬件信息（默认拉一次；Popover 内刷新按钮可强制重拉，如插了内存/外置 GPU 后） */
export function useHardware(): {
  data: HardwareInfo | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
} {
  const [data, setData] = useState<HardwareInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    api.getHardware()
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, loading, error, refresh };
}

/** 必要配置状态（用于 banner） */
export function useRequiredStatus(refreshKey = 0): {
  data: RequiredStatusMap | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
} {
  const [data, setData] = useState<RequiredStatusMap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    api.getRequiredStatus()
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, refreshKey]);

  return { data, loading, error, refresh };
}

/** 全量扫描结果 */
export function useScan(autoRefresh = false): {
  data: ScanResult | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
} {
  const [data, setData] = useState<ScanResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api.scan(true);
      setData(d);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // 可选自动刷新（如 30 秒一次）
  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(refresh, 30_000);
    return () => clearInterval(id);
  }, [autoRefresh, refresh]);

  return { data, loading, error, refresh };
}

/** 全部配置（编辑表单用） */
export function useAllConfig(): {
  data: ConfigMap | null;
  loading: boolean;
  error: string | null;
  save: (updates: ConfigMap) => Promise<void>;
  refresh: () => void;
} {
  const [data, setData] = useState<ConfigMap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    api.getConfig()
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const save = useCallback(async (updates: ConfigMap) => {
    const updated = await api.updateConfig(updates);
    setData(updated);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, loading, error, save, refresh };
}

/** 运行环境信息（venv/HF 缓存，一次拉取） */
export function useSystem(): {
  data: SystemInfo | null;
  loading: boolean;
  error: string | null;
} {
  const [data, setData] = useState<SystemInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getSystem()
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return { data, loading, error };
}

/** 模型资产（有下载中任务时自动轮询 2s） */
export function useModels(): {
  data: ModelsResponse | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
} {
  const [data, setData] = useState<ModelsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timerMsRef = useRef(0); // 当前轮询档位（0=停）

  const refresh = useCallback(async () => {
    try {
      const d = await api.getModels();
      setData(d);
      setError(null);
      // 轮询档位（变化时才重设计时器）:
      //   下载中 → 2s（进度条流畅）
      //   OCR 已加载（空闲倒计时 + 卸载翻转）→ 10s（reaper 600s 卸载后卡片须翻回未加载）
      //   否则停（静态数据不刷）
      const downloading = d.models.some((m) => m.download.status === "downloading");
      const ocrActive = d.models.some((m) => m.type === "ocr" && m.loaded);
      const wantMs = downloading ? 2000 : ocrActive ? 10_000 : 0;
      if (wantMs !== timerMsRef.current) {
        if (timerRef.current) clearInterval(timerRef.current);
        timerRef.current = null;
        timerMsRef.current = wantMs;
        if (wantMs > 0) timerRef.current = setInterval(refresh, wantMs);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      timerMsRef.current = 0; // 防 StrictMode 双挂载时档位残留误判
    };
  }, [refresh]);

  return { data, loading, error, refresh };
}

/** 配置元数据（label/type/hint/required，一次拉取） */
export function useConfigMeta(): {
  data: ConfigMetaMap | null;
  loading: boolean;
  error: string | null;
} {
  const [data, setData] = useState<ConfigMetaMap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getConfigMeta()
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return { data, loading, error };
}
