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
  SystemInfo, ModelsResponse, FsCheckResult,
  ConfigSurface, ConfigMetaResponse,
  ProcessRegistryView, HeartbeatsResponse,
  RemoteLinkStatusView, SwitchResultView, NodeConfigView, AutostartView,
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

  // ─── /api/processes ─────────────────────────────────────
  async getProcesses(): Promise<ProcessRegistryView> {
    const r = await instance.get<ProcessRegistryView>("/api/processes");
    return r.data;
  },

  // ─── /api/heartbeats（运行状态页: 连接的 opencode 进程）───
  async getHeartbeats(): Promise<HeartbeatsResponse> {
    const r = await instance.get<HeartbeatsResponse>("/api/heartbeats");
    return r.data;
  },

  // ─── /api/system/restart ────────────────────────────────
  async restartConsole(): Promise<{ success: boolean; scheduled: boolean; message: string }> {
    const r = await instance.post("/api/system/restart");
    return r.data;
  },

  // ─── /api/config（全 POST + 结构化 body; surfaces 列表贯穿全链路） ─────
  async getConfig(surface: ConfigSurface): Promise<ConfigMap> {
    const r = await instance.post<ConfigMap>("/api/config/list",
      { surfaces: [surface] });
    return r.data;
  },

  async getRequiredStatus(surface: ConfigSurface): Promise<RequiredStatusMap> {
    const r = await instance.post<RequiredStatusMap>("/api/config/required-status",
      { surfaces: [surface] });
    return r.data;
  },

  async updateConfig(updates: ConfigMap, surface: ConfigSurface): Promise<ConfigMap> {
    const r = await instance.post<ConfigMap>("/api/config/update",
      { surfaces: [surface], configs: updates });
    return r.data;
  },

  async deleteConfig(key: string, surface: ConfigSurface): Promise<ConfigMap> {
    const r = await instance.post<ConfigMap>("/api/config/delete",
      { surfaces: [surface], keys: [key] });
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

  // ─── /api/system ────────────────────────────────────────
  async getSystem(): Promise<SystemInfo> {
    const r = await instance.get<SystemInfo>("/api/system");
    return r.data;
  },

  // ─── /api/models ────────────────────────────────────────
  async getModels(): Promise<ModelsResponse> {
    const r = await instance.get<ModelsResponse>("/api/models");
    return r.data;
  },

  async downloadModel(modelId: string): Promise<{ ok: boolean; model_id: string }> {
    const r = await instance.post(`/api/models/${encodeURIComponent(modelId)}/download`);
    return r.data;
  },

  // ─── /api/fs/check ──────────────────────────────────────
  async fsCheck(path: string): Promise<FsCheckResult> {
    const r = await instance.get<FsCheckResult>("/api/fs/check", {
      params: { path },
    });
    return r.data;
  },

  // ─── /api/config/meta ───────────────────────────────────
  async getConfigMeta(surface: ConfigSurface): Promise<ConfigMetaResponse> {
    const r = await instance.post<ConfigMetaResponse>("/api/config/meta",
      { surfaces: [surface] });
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

  // ─── /api/remote（远程资源 TAB）─────────────────────────
  async getRemoteStatus(): Promise<RemoteLinkStatusView> {
    const r = await instance.get<RemoteLinkStatusView>("/api/remote/status");
    return r.data;
  },

  async switchRemote(target: "remote" | "local"): Promise<SwitchResultView> {
    const r = await instance.post<SwitchResultView>("/api/remote/switch", { target });
    return r.data;
  },

  /** 节点三 KEY（node=remote 经本控制台转发到远程节点） */
  async getNodeConfig(node: "local" | "remote" = "remote"): Promise<NodeConfigView> {
    const r = await instance.get<NodeConfigView>("/api/remote/node-config", {
      params: { node },
    });
    return r.data;
  },

  async updateNodeConfig(
    configs: Partial<Record<"CONTROL_RESIDENT" | "CONTROL_AUTOSTART" | "CONTROL_API_KEY", string>>,
    node: "local" | "remote" = "remote",
  ): Promise<{ ok: boolean; reboot_required: boolean; hint: string }> {
    const r = await instance.put("/api/remote/node-config", { configs }, { params: { node } });
    return r.data;
  },

  async getAutostart(node: "local" | "remote" = "remote"): Promise<AutostartView> {
    const r = await instance.get<AutostartView>("/api/remote/autostart", { params: { node } });
    return r.data;
  },

  async setAutostart(enable: boolean, node: "local" | "remote" = "remote"): Promise<AutostartView & { hint?: string }> {
    const r = await instance.post("/api/remote/autostart", { enable }, { params: { node } });
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
