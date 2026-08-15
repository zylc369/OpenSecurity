/**
 * 自定义 hooks 收口。
 *
 * 组件通过 hooks 拿数据，不直接调 api 对象（统一数据获取层）。
 */
import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client";
import type {
  HardwareInfo, RequiredStatusMap, ScanResult, ConfigMap,
} from "../types";

/** 硬件信息（启动时拉一次，硬件不变） */
export function useHardware(): {
  data: HardwareInfo | null;
  loading: boolean;
  error: string | null;
} {
  const [data, setData] = useState<HardwareInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getHardware()
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return { data, loading, error };
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
