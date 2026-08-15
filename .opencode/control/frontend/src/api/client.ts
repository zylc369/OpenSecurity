/**
 * API 客户端（收口）。
 *
 * 所有 axios 调用集中在本文件，组件通过 hooks 或直接调用 api 对象。
 *
 * baseURL 处理：
 *   dev 模式：Vite 5173 → /api 反向代理到 9776（baseURL 为空字符串，走相对路径）
 *   release 模式：同源 9776（baseURL 为空字符串）
 * 因此 baseURL 始终是空字符串（用相对路径）。
 */
import axios, { AxiosInstance } from "axios";
import type {
  HardwareInfo, ConfigMap, RequiredStatusMap, ToolStatus, AgentTools,
  DockerScanGlobal, ScanResult, InstallResult,
} from "../types";

const instance: AxiosInstance = axios.create({
  baseURL: "",  // 相对路径，dev/release 都走当前 origin
  timeout: 30_000,
});

instance.interceptors.response.use(
  (resp) => resp,
  (error) => {
    if (error.response) {
      const msg = error.response.data?.detail || error.response.statusText;
      return Promise.reject(new Error(`HTTP ${error.response.status}: ${msg}`));
    }
    return Promise.reject(error);
  },
);

export const api = {
  // ─── /api/hardware ──────────────────────────────────────
  async getHardware(): Promise<HardwareInfo> {
    const r = await instance.get<HardwareInfo>("/api/hardware");
    return r.data;
  },

  // ─── /api/config ────────────────────────────────────────
  async getConfig(): Promise<ConfigMap> {
    const r = await instance.get<ConfigMap>("/api/config");
    return r.data;
  },

  async getRequiredStatus(): Promise<RequiredStatusMap> {
    const r = await instance.get<RequiredStatusMap>("/api/config/required-status");
    return r.data;
  },

  async updateConfig(updates: ConfigMap): Promise<ConfigMap> {
    const r = await instance.put<ConfigMap>("/api/config", { configs: updates });
    return r.data;
  },

  async deleteConfig(key: string): Promise<ConfigMap> {
    const r = await instance.delete<ConfigMap>(`/api/config/${encodeURIComponent(key)}`);
    return r.data;
  },

  // ─── /api/deps ──────────────────────────────────────────
  async getAllDeps(): Promise<AgentTools> {
    const r = await instance.get<AgentTools>("/api/deps");
    return r.data;
  },

  async getAgentDeps(agent: string): Promise<ToolStatus[]> {
    const r = await instance.get<ToolStatus[]>(`/api/deps/${encodeURIComponent(agent)}`);
    return r.data;
  },

  // ─── /api/scan ──────────────────────────────────────────
  async scan(forceRefresh = false): Promise<ScanResult> {
    const r = await instance.get<ScanResult>("/api/scan", {
      params: { force_refresh: forceRefresh },
    });
    return r.data;
  },

  // ─── /api/install ───────────────────────────────────────
  async install(packageName: string): Promise<InstallResult> {
    const r = await instance.post<InstallResult>("/api/install", { package: packageName });
    return r.data;
  },

  // ─── /api/docker/* ──────────────────────────────────────
  async getDockerStatus(): Promise<DockerScanGlobal> {
    const r = await instance.get<DockerScanGlobal>("/api/docker/status");
    return r.data;
  },

  async startContainer(name: string): Promise<{ success: boolean; message: string }> {
    const r = await instance.post(`/api/docker/containers/${encodeURIComponent(name)}/start`);
    return r.data;
  },

  async stopContainer(name: string): Promise<{ success: boolean; message: string }> {
    const r = await instance.post(`/api/docker/containers/${encodeURIComponent(name)}/stop`);
    return r.data;
  },

  /**
   * 拉取镜像（SSE 流式进度）。
   * 用法：
   *   const stop = api.pullImage("neo4j:5", (line) => console.log(line));
   *   // 取消：stop();
   */
  pullImage(
    image: string,
    onProgress: (line: string) => void,
  ): () => void {
    const url = `/api/docker/images/${encodeURIComponent(image)}/pull`;
    // 用 fetch + ReadableStream 读 SSE
    const controller = new AbortController();
    const decoder = new TextDecoder();
    fetch(url, { signal: controller.signal })
      .then(async (resp) => {
        if (!resp.body) return;
        const reader = resp.body.getReader();
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          // SSE 格式：data: xxx\n\n
          const lines = buffer.split("\n\n");
          buffer = lines.pop() || "";
          for (const chunk of lines) {
            if (chunk.startsWith("data: ")) {
              onProgress(chunk.slice(6).trim());
            }
          }
        }
      })
      .catch((e) => {
        if (e.name !== "AbortError") {
          onProgress(`__error__ ${e.message}`);
        }
      });
    return () => controller.abort();
  },
};
