import { describe, expect, it } from "vitest";
import { computeReadiness } from "./useReadiness";
import { CATEGORIES } from "../constants/categories";
import type {
  KnownImage, ModelAsset, ModelsResponse, PyPackageStatus,
  RequiredStatusMap, ScanResult, ToolStatus,
} from "../types";

// ── 最小 fixture 工厂（只填被测字段；其余取类型要求的零值）──

const tool = (name: string, available: boolean, skipped = false): ToolStatus => ({
  name, description: "", required: false, available, skipped,
  version: null, path: null, install_hint: "",
});

const pyPkg = (pip_name: string, available: boolean): PyPackageStatus => ({
  name: pip_name, pip_name, kind: "python", description: "", required: false,
  installer: "pip", agents: ["all"], available, version: null,
});

const image = (name: string, pulled: boolean): KnownImage => ({
  name, description: "", size_hint: "", pulled,
});

const model = (id: string, display: string, cached: boolean): ModelAsset => ({
  id, repo_id: id, type: "embedder", display, purpose: "", min_free_gb: 0, disk_gb: 0,
  cached, cache_path: null, size_gb: 0, loaded: false, idle_sec: null, idle_timeout_sec: null,
  download: { status: "idle", progress: 0, error: "" },
});

const scan = (over: {
  agents?: ScanResult["agents"];
  images?: KnownImage[];
  pkgs?: PyPackageStatus[];
}): ScanResult => ({
  agents: over.agents ?? {},
  global: {
    docker: { docker: { installed: true, daemon_running: true }, containers: [], images: over.images ?? [] },
    required_configs: {},
    python_packages: over.pkgs ?? [],
    models: [],
  },
  timestamp: 0,
});

const modelsResp = (list: ModelAsset[]): ModelsResponse => ({
  models: list,
  hardware_summary: { ok: true, reason: "", notes: [], available_gb: 0, total_required_gb: 0 },
  hf_endpoint: "",
});

describe("computeReadiness", () => {
  it("空输入（null×3）→ 全零且不崩", () => {
    const r = computeReadiness(null, null, null);
    expect(r.ok).toBe(0);
    expect(r.total).toBe(0);
    expect(r.cats).toHaveLength(CATEGORIES.length);
  });

  it("分类顺序 = CATEGORIES 声明顺序（页面分区顺序）", () => {
    const r = computeReadiness(null, null, null);
    expect(r.cats.map((c) => c.key)).toEqual(CATEGORIES.map((c) => c.key));
    expect(r.cats.map((c) => c.title)).toEqual(CATEGORIES.map((c) => c.title));
  });

  it("工具跨 agent 去重；available 与 skipped 均计 ok；缺失名入 missingNames", () => {
    const r = computeReadiness(scan({
      agents: {
        "web-analysis": [tool("nmap", true), tool("gdb", false)],
        "binary-analysis": [tool("nmap", true), tool("wine", false, true)],
      },
    }), null, null);
    const tools = r.cats.find((c) => c.key === "tools")!;
    expect(tools.total).toBe(3);   // nmap 只算一次
    expect(tools.ok).toBe(2);      // nmap available + wine skipped
    expect(tools.missingNames).toEqual(["gdb"]);
  });

  it("同名工具以后出现者为准（Map.set 覆盖——现状语义固化）", () => {
    const r = computeReadiness(scan({
      agents: { a: [tool("x", false)], b: [tool("x", true)] },
    }), null, null);
    const tools = r.cats.find((c) => c.key === "tools")!;
    expect(tools.ok).toBe(1);
    expect(tools.total).toBe(1);
  });

  it("docker 镜像：pulled 计 ok，未拉取名入缺失", () => {
    const r = computeReadiness(scan({ images: [image("neo4j:5", true), image("alpine", false)] }), null, null);
    const docker = r.cats.find((c) => c.key === "docker")!;
    expect(docker).toMatchObject({ ok: 1, total: 2, missingNames: ["alpine"] });
  });

  it("models：cached 计 ok，未缓存用 display 记缺失", () => {
    const r = computeReadiness(null, modelsResp([
      model("bge-m3", "BGE-M3 向量", true), model("glm-ocr", "GLM-OCR", false),
    ]), null);
    const models = r.cats.find((c) => c.key === "models")!;
    expect(models).toMatchObject({ ok: 1, total: 2, missingNames: ["GLM-OCR"] });
  });

  it("deps：available 计 ok，缺失用 pip_name 记名", () => {
    const r = computeReadiness(scan({ pkgs: [pyPkg("requests", true), pyPkg("frida", false)] }), null, null);
    const deps = r.cats.find((c) => c.key === "deps")!;
    expect(deps).toMatchObject({ ok: 1, total: 2, missingNames: ["frida"] });
  });

  it("config：按 ok 过滤，缺失以 key 记名", () => {
    const required: RequiredStatusMap = {
      DEEPSEEK_API_KEY: { label: "", ok: true, hint: "", error: "" },
      JULIANG_API_KEY: { label: "", ok: false, hint: "", error: "未配置" },
    };
    const r = computeReadiness(null, null, required);
    const config = r.cats.find((c) => c.key === "config")!;
    expect(config).toMatchObject({ ok: 1, total: 2, missingNames: ["JULIANG_API_KEY"] });
  });

  it("总计 = 各类求和（数字可对账契约）", () => {
    const r = computeReadiness(
      scan({
        agents: { a: [tool("t1", true), tool("t2", false)] },
        images: [image("img", true)],
        pkgs: [pyPkg("p1", true), pyPkg("p2", true), pyPkg("p3", false)],
      }),
      modelsResp([model("m1", "M1", true)]),
      { K1: { label: "", ok: false, hint: "", error: "" } },
    );
    expect(r.ok).toBe(1 + 1 + 2 + 1 + 0);
    expect(r.total).toBe(1 + 1 + 3 + 2 + 1);
  });
});
