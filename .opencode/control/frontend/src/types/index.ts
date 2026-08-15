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
}

export type AgentTools = Record<string, ToolStatus[]>;

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

export interface ModelStatus {
  name: string;
  type: string;
  loaded: boolean;
}

export interface GlobalResources {
  docker: DockerScanGlobal;
  required_configs: RequiredStatusMap;
  models: ModelStatus[];
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
