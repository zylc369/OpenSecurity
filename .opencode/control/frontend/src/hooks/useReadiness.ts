/**
 * 环境就绪度单一计算源。
 *
 * 所有 X/Y 数字（顶栏总览、悬浮明细、各卡片 Tag、锚点徽标）都从本 hook 取，
 * 保证任何两处数字必然一致（用户反馈固化：数字必须能对账）。
 * 数据全部来自页面已拉取的 scan/models/required，零额外请求。
 */
import { useMemo } from "react";
import type { ScanResult, ModelsResponse, RequiredStatusMap, ModelAsset, PyPackageStatus, ToolStatus } from "../types";
import { CATEGORIES, type CategoryKey } from "../constants/categories";

export interface CategoryStat {
  key: CategoryKey;
  title: string;
  unit: string;
  ok: number;
  total: number;
  /** 缺失项显示名 */
  missingNames: string[];
}

export interface Readiness {
  cats: CategoryStat[];
  ok: number;
  total: number;
}

/** 外部工具按工具名去重计数（一个工具被多个 agent 用只算一次） */
function dedupTools(toolsAll: ToolStatus[]) {
  const byName = new Map<string, ToolStatus>();
  for (const t of toolsAll) byName.set(t.name, t);
  const all = [...byName.values()];
  return {
    ok: all.filter((t) => t.available || t.skipped).length,
    total: all.length,
    missing: all.filter((t) => !t.available && !t.skipped).map((t) => t.name),
  };
}

export function useReadiness(
  scan: ScanResult | null,
  models: ModelsResponse | null,
  required: RequiredStatusMap | null,
): Readiness {
  return useMemo(() => {
    const pyPkgs: PyPackageStatus[] = scan?.global.python_packages ?? [];
    const toolsAll: ToolStatus[] = Object.values(scan?.agents ?? {}).flat();
    const tools = dedupTools(toolsAll);
    const images = scan?.global.docker.images ?? [];
    const modelsAll: ModelAsset[] = models?.models ?? [];
    const reqEntries = Object.entries(required ?? {});

    const byKey: Record<CategoryKey, CategoryStat> = {
      docker: {
        key: "docker", title: "Docker", unit: "镜像",
        ok: images.filter((i) => i.pulled).length,
        total: images.length,
        missingNames: images.filter((i) => !i.pulled).map((i) => i.name),
      },
      models: {
        key: "models", title: "模型", unit: "就绪",
        ok: modelsAll.filter((m) => m.cached).length,
        total: modelsAll.length,
        missingNames: modelsAll.filter((m) => !m.cached).map((m) => m.display),
      },
      deps: {
        key: "deps", title: "Python 依赖", unit: "已装",
        ok: pyPkgs.filter((p) => p.available).length,
        total: pyPkgs.length,
        missingNames: pyPkgs.filter((p) => !p.available).map((p) => p.pip_name),
      },
      tools: {
        key: "tools", title: "外部工具", unit: "可用",
        ok: tools.ok,
        total: tools.total,
        missingNames: tools.missing,
      },
      config: {
        key: "config", title: "配置", unit: "完整",
        ok: reqEntries.filter(([, r]) => r.ok).length,
        total: reqEntries.length,
        missingNames: reqEntries.filter(([, r]) => !r.ok).map(([k]) => k),
      },
    };

    const cats = CATEGORIES.map((c) => byKey[c.key]);
    return {
      cats,
      ok: cats.reduce((n, c) => n + c.ok, 0),
      total: cats.reduce((n, c) => n + c.total, 0),
    };
  }, [scan, models, required]);
}
