/**
 * 依赖管理页。
 *
 * 显示：
 *   • 全量扫描 loading 动画
 *   • 缺失项汇总
 *   • 按 Agent 折叠查看细节
 *   • 全局资源区块
 */
import React, { useState, useMemo } from "react";
import { useScan } from "../hooks";
import { api } from "../api/client";
import type { ToolStatus } from "../types";

const AGENT_NAMES = [
  "binary-analysis",
  "mobile-analysis",
  "web-analysis",
  "crypto-analysis",
  "ai-security-analysis",
] as const;

const DepsPage: React.FC = () => {
  const { data: scan, loading, error, refresh } = useScan();
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);

  // 汇总缺失项
  const missingItems = useMemo(() => {
    if (!scan) return [];
    const items: Array<{ agent: string; tool: ToolStatus }> = [];
    for (const [agent, tools] of Object.entries(scan.agents)) {
      for (const t of tools) {
        if (!t.available && t.required && !t.skipped) {
          items.push({ agent, tool: t });
        }
      }
    }
    return items;
  }, [scan]);

  const handleInstall = async (packageName: string) => {
    setInstalling(packageName);
    try {
      await api.install(packageName);
      await refresh();
    } catch (e) {
      alert(`安装失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setInstalling(null);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text).then(() => {
      alert("已复制：" + text);
    });
  };

  if (loading && !scan) {
    return (
      <div>
        <h2>依赖管理</h2>
        <div className="card">
          <p><span className="loading" /> 正在全量扫描...</p>
          <div className="loading-bar" style={{ marginTop: 12 }} />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <h2>依赖管理</h2>
        <div className="card">扫描失败：{error}</div>
      </div>
    );
  }

  if (!scan) return null;

  return (
    <div>
      <h2>
        依赖管理
        <button className="btn btn-sm" style={{ marginLeft: 12 }} onClick={() => refresh()}>
          {loading ? "扫描中..." : "刷新"}
        </button>
      </h2>

      {/* 缺失项汇总 */}
      {missingItems.length > 0 && (
        <div className="card">
          <h3 className="card-title">⚠️ 缺失项汇总（{missingItems.length}）</h3>
          {missingItems.map(({ agent, tool }) => (
            <div className="tool-row" key={`${agent}-${tool.name}`}>
              <div className="tool-name">
                <span className="status-dot error" />
                <span className="name">{tool.name}</span>
                <span className="version">{agent}</span>
              </div>
              <div className="tool-hint">{tool.install_hint.slice(0, 80)}</div>
              <div className="tool-actions">
                {tool.install_hint.includes("brew") || tool.install_hint.includes("apt") ? (
                  <button
                    className="btn btn-sm"
                    onClick={() => copyToClipboard(tool.install_hint.split("\n")[0])}
                  >
                    复制命令
                  </button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 全局资源 */}
      <div className="card">
        <h3 className="card-title">全局资源</h3>
        <div className="tool-row">
          <div className="tool-name">
            <span className={`status-dot ${scan.global.docker.docker.installed && scan.global.docker.docker.daemon_running ? "ok" : "error"}`} />
            <span className="name">Docker daemon</span>
          </div>
          <div className="tool-hint">
            {scan.global.docker.docker.installed
              ? scan.global.docker.docker.daemon_running
                ? "运行中"
                : "未运行"
              : "未安装"}
          </div>
        </div>
        {scan.global.docker.containers.map((c) => (
          <div className="tool-row" key={c.name}>
            <div className="tool-name">
              <span className={`status-dot ${c.status === "running" ? "ok" : "warning"}`} />
              <span className="name">{c.name}</span>
              <span className="version">{c.image}</span>
            </div>
            <div className="tool-hint">{c.status}</div>
          </div>
        ))}
        {scan.global.docker.images.filter((i) => !i.pulled).map((i) => (
          <div className="tool-row" key={i.name}>
            <div className="tool-name">
              <span className="status-dot error" />
              <span className="name">{i.name}</span>
              <span className="version">镜像未拉取</span>
            </div>
            <div className="tool-actions">
              <a href="/docker" className="btn btn-sm">前往拉取</a>
            </div>
          </div>
        ))}
        {Object.entries(scan.global.required_configs).map(([key, status]) => (
          <div className="tool-row" key={key}>
            <div className="tool-name">
              <span className={`status-dot ${status.ok ? "ok" : "error"}`} />
              <span className="name">{status.label}</span>
              <span className="version">{key}</span>
            </div>
            <div className="tool-hint">{status.ok ? "已配置" : status.error || "未配置"}</div>
          </div>
        ))}
      </div>

      {/* 按 Agent 折叠 */}
      <h3 style={{ marginTop: 24 }}>按 Agent 查看</h3>
      {AGENT_NAMES.map((agent) => {
        const tools = scan.agents[agent] || [];
        if (tools.length === 0) return null;
        const isExpanded = expandedAgent === agent;
        return (
          <div className="collapsible" key={agent}>
            <div
              className="collapsible-header"
              onClick={() => setExpandedAgent(isExpanded ? null : agent)}
            >
              <span>{agent}（{tools.filter((t) => t.available).length}/{tools.length} 可用）</span>
              <span>{isExpanded ? "▼" : "▶"}</span>
            </div>
            {isExpanded && (
              <div className="collapsible-body">
                {tools.map((t) => (
                  <div className="tool-row" key={t.name}>
                    <div className="tool-name">
                      <span className={`status-dot ${t.available ? "ok" : t.required ? "error" : t.skipped ? "skipped" : "warning"}`} />
                      <span className="name">{t.name}</span>
                      {t.version && <span className="version">{t.version}</span>}
                      {!t.required && <span className="version">(可选)</span>}
                      {t.skipped && <span className="version">(平台不适用)</span>}
                    </div>
                    <div className="tool-hint">{t.description}</div>
                    <div className="tool-actions">
                      {!t.available && (t.install_hint.includes("brew") || t.install_hint.includes("apt")) && (
                        <button
                          className="btn btn-sm"
                          onClick={() => copyToClipboard(t.install_hint.split("\n")[0])}
                        >
                          复制命令
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {/* Python 包安装（白名单内） */}
      <div className="card" style={{ marginTop: 24 }}>
        <h3 className="card-title">一键安装 Python 包</h3>
        <p style={{ fontSize: 13, color: "#718096" }}>
          白名单：frida、angr、triton、z3-solver、playwright、httpx、beautifulsoup4、lxml 等
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {["frida", "frida-tools", "angr", "triton", "z3-solver", "playwright", "pyautogui", "pillow"].map((pkg) => (
            <button
              key={pkg}
              className="btn btn-sm"
              disabled={installing !== null}
              onClick={() => handleInstall(pkg)}
            >
              {installing === pkg ? "安装中..." : `+ ${pkg}`}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

export default DepsPage;
