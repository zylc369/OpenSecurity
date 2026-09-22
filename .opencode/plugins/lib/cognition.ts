/**
 * 认知契约（反公理固化）——共享词汇、口径与镜像校验的唯一来源。
 *
 * 消费方（插件内插值；改本文件即全量同步）：
 *   - lib/task-session-persistence.ts：ledger.md 模板的节名与字段列
 *   - security-analysis.ts：压缩保留规则（结论台账与未测清单）
 *   - lib/checkpoint.ts：认知检查点行动指令
 *
 * 镜像点（静态文件无法 import，由 cognition.verifyMirrors()（插件启动自检）逐字比对）：
 *   - agents-rules/execution-discipline.md：禁止裸写词表 + 契约词汇（结论三件套 / 证据等级枚举 / 未测条件节名）
 *
 * 手动即时验证（无独立脚本）：
 *   bun -e "const m=await import('./plugins/lib/cognition.ts'); console.log(m.cognition.verifyMirrors())"
 */

import { readFileSync } from "fs";
import { join } from "path";
import { OPENCODE_ROOT } from "./constants";

/**
 * 认知契约：常量与镜像校验收口在同一类。
 * 实例字段按声明顺序初始化（evidenceLevelSpec 依赖先声明的 fields / evidenceLevelValues）。
 */
class CognitionContract {
  /** 结论三件套的固定称呼 */
  readonly triadName = "结论三件套";

  /** 证据等级的取值枚举 */
  readonly evidenceLevelValues = "observed/inferred/assumption/unverified";

  /** 结论三件套字段口径（台账模板列 / 压缩注入共用同一词汇） */
  readonly fields = {
    evidenceLevel: "证据等级",
    verifiedScope: "已验证范围",
    untestedList: "未测清单",
  } as const;

  /** 带取值枚举的证据等级说明（压缩注入使用） */
  readonly evidenceLevelSpec = `${this.fields.evidenceLevel}（${this.evidenceLevelValues}）`;

  /** 分析台账节名（台账模板与检查点指令共用） */
  readonly sections = {
    observations: "观测记录",
    conclusions: "结论台账",
    untested: "未测条件（维度）",
    changelog: "变更日志",
  } as const;

  /** 台账文件名（模板创建与压缩注入文本共用） */
  readonly ledgerFilename = "ledger.md";

  /** 否定类封闭词表：保留此类表述必须同时附未测清单（压缩注入按此顺序展示） */
  readonly universalDenyMarkers = [
    "永远",
    "所有情况",
    "完备",
    "恒真",
    "不可能",
    "已排除",
  ] as const;

  /**
   * 镜像点一致性校验：返回不一致项列表（空 = 一致）。
   * 插件启动时自动调用；手动即时验证见本文件头部注释。
   */
  verifyMirrors(): string[] {
    const problems: string[] = [];
    try {
      const discipline = readFileSync(
        join(OPENCODE_ROOT, "agents-rules", "execution-discipline.md"),
        "utf-8",
      );
      const mdDeny =
        discipline.match(/禁止裸写[「“"]([^」”"]+)[」”"]/)?.[1]?.split("/") ?? [];
      if (!this.sameList(mdDeny, this.universalDenyMarkers))
        problems.push(
          `execution-discipline.md 禁止裸写词表=${mdDeny.join("/")}，应为 ${this.universalDenyMarkers.join("/")}`,
        );

      // md 无法 import 契约常量，只能镜像；以下词汇必须在 md 中出现（缺 = 漂移）
      for (const [label, token] of [
        ["结论三件套", this.triadName],
        ["证据等级枚举", this.evidenceLevelValues],
        ["未测条件节名", this.sections.untested],
      ] as const) {
        if (!discipline.includes(token))
          problems.push(
            `execution-discipline.md 缺契约词汇: ${label} (${token})`,
          );
      }
    } catch (e) {
      problems.push(`镜像文件读取失败: ${(e as Error)?.message}`);
    }
    return problems;
  }

  /** 逐字列表比较（含顺序） */
  private sameList(a: readonly string[], b: readonly string[]): boolean {
    return a.length === b.length && a.every((v, i) => v === b[i]);
  }
}

/** 模块级单例（消费方 `import { cognition } from "./lib/cognition"`） */
export const cognition = new CognitionContract();
