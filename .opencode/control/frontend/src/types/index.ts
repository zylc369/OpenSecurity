/**
 * 控制台 API 类型定义。
 *
 * 收口：所有 TypeScript 类型定义在本文件，其他文件只导入不重复定义。
 * 与控制台后端 routes 的 Pydantic 模型 / dict 返回结构对齐。
 */

// ─── /api/hardware ────────────────────────────────────────

export interface CPUInfo {
  physical_cores: number;
  logical_cores: number;
  frequency_mhz: number | null;
}

export interface MemoryInfo {
  total_gb: number;
  available_gb: number;
}

export interface OSInfo {
  system: string;
  platform: string;
  machine: string;
  version: string;
}

export interface GPUInfo {
  name: string;
  vendor?: string;
  metal?: string;
  vram?: string;
  vram_gb?: number;
  vram_mb?: number;
  capabilities: string[];
}

export interface HardwareInfo {
  cpu: CPUInfo;
  memory: MemoryInfo;
  os: OSInfo;
  gpu: GPUInfo[];
}

// ─── /api/config/* ────────────────────────────────────────

export type ConfigMap = Record<string, string>;

export interface RequiredConfigStatus {
  label: string;
  ok: boolean;
  hint: string;
  error: string;
}

export type RequiredStatusMap = Record<string, RequiredConfigStatus>;

// ─── /api/deps + /api/scan ────────────────────────────────

export interface ToolStatus {
  name: string;
  description: string;
  required: boolean;
  available: boolean;
  skipped?: boolean;       // 当前平台不适用
  version: string | null;
  path: string | null;
  install_hint: string;
  kind?: "tool";           // 外部工具（IDA/apktool 等，区别于 Python 包）
}

export type AgentTools = Record<string, ToolStatus[]>;

/** venv 内 Python 包状态（scan.global.python_packages） */
export interface PyPackageStatus {
  name: string;            // import 名
  pip_name: string;        // pip 安装名
  kind: "python";
  description: string;
  required: boolean;
  installer: "pip" | "conda";
  agents: string[];        // ["all"] = 全部
  available: boolean;
  version: string | null;
}

// ─── /api/docker/* ────────────────────────────────────────

export interface DockerStatus {
  installed: boolean;
  daemon_running: boolean;
}

export interface KnownContainer {
  name: string;
  image: string;
  description: string;
  status: "running" | "stopped" | "not_exists" | "unknown";
  auto_start: boolean;
}

export interface KnownImage {
  name: string;
  description: string;
  size_hint: string;
  pulled: boolean;
}

export interface DockerScanGlobal {
  docker: DockerStatus;
  containers: KnownContainer[];
  images: KnownImage[];
}

// ─── /api/scan ────────────────────────────────────────────
// models 字段与 /api/models 同源（services/model_assets.py），类型复用 ModelAsset。

export interface GlobalResources {
  docker: DockerScanGlobal;
  required_configs: RequiredStatusMap;
  python_packages: PyPackageStatus[];
  models: ModelAsset[];
}

export interface ScanResult {
  agents: AgentTools;
  global: GlobalResources;
  timestamp: number;
}

// ─── /api/install ─────────────────────────────────────────

export interface InstallResult {
  success: boolean;
  package: string;
  stdout?: string;
  stderr?: string;
  error?: string;
}

// ─── 通用 ─────────────────────────────────────────────────

export interface ApiError {
  detail: string;
}

// ─── /api/system ──────────────────────────────────────────

export interface SystemInfo {
  venv_path: string;
  venv_python: string;
  python_version: string;
  hf_cache_dir: string;
  hf_endpoint: string;
  control_pid: number;
  dev_mode: boolean;
  platform: string;
}

// ─── /api/models ──────────────────────────────────────────

export interface HardwareAssessment {
  ok: boolean;
  reasons: string[];      // 不达标原因（ok=false 时非空）
  notes: string[];        // 加速说明（如 Apple Silicon Metal）
  available_gb: number;
}

export interface DownloadState {
  status: "idle" | "downloading" | "done" | "error";
  progress: number;       // 0~1
  error: string;
}

export interface ModelAsset {
  id: string;
  repo_id: string;
  type: string;           // embedder / reranker
  display: string;
  purpose: string;
  min_free_gb: number;
  disk_gb: number;
  cached: boolean;
  cache_path: string | null;
  size_gb: number;
  loaded: boolean;
  hardware: HardwareAssessment;
  download: DownloadState;
}

export interface ModelsResponse {
  models: ModelAsset[];
  hf_endpoint: string;
}

// ─── /api/fs/check ────────────────────────────────────────

export interface FsCheckResult {
  path: string;
  resolved: string;
  exists: boolean;
  is_dir: boolean;
}

// ─── /api/config/meta ─────────────────────────────────────

export type ConfigFieldType = "password" | "path" | "text" | "bool";

export interface ConfigMetaItem {
  label: string;
  type: ConfigFieldType;
  hint: string;
  required: boolean;
}

export type ConfigMetaMap = Record<string, ConfigMetaItem>;
