/**
 * 状态总览页（默认页）。
 *
 * 显示：
 *   • 必要配置 banner（缺失时）
 *   • 硬件信息卡片（CPU、内存、OS、GPU）
 *   • 全局资源快照（Docker、模型）
 */
import React from "react";
import RequiredConfigBanner from "../components/RequiredConfigBanner";
import { useHardware, useScan } from "../hooks";

const StatusPage: React.FC = () => {
  const { data: hw, loading: hwLoading, error: hwError } = useHardware();
  const { data: scan, loading: scanLoading } = useScan();

  return (
    <div>
      <RequiredConfigBanner />

      <h2>状态总览</h2>

      {hwLoading ? (
        <div className="card"><div className="loading" /> 加载硬件信息...</div>
      ) : hwError ? (
        <div className="card">硬件信息加载失败：{hwError}</div>
      ) : hw ? (
        <div className="card-grid">
          <div className="stat-card">
            <div className="label">CPU</div>
            <div className="value">{hw.cpu.physical_cores} 核</div>
            <div className="sub">{hw.cpu.logical_cores} 逻辑核 · {hw.cpu.frequency_mhz ?? "?"} MHz</div>
          </div>
          <div className="stat-card">
            <div className="label">内存</div>
            <div className="value">{hw.memory.total_gb} GB</div>
            <div className="sub">可用 {hw.memory.available_gb} GB</div>
          </div>
          <div className="stat-card">
            <div className="label">操作系统</div>
            <div className="value">{hw.os.system}</div>
            <div className="sub">{hw.os.machine} · {hw.os.platform}</div>
          </div>
          <div className="stat-card">
            <div className="label">GPU</div>
            <div className="value">{hw.gpu.length > 0 ? hw.gpu[0].name : "无"}</div>
            <div className="sub">
              {hw.gpu[0]?.capabilities?.join(" · ") || "无加速"}
            </div>
          </div>
        </div>
      ) : null}

      <h2 style={{ marginTop: 24 }}>全局资源</h2>

      {scanLoading ? (
        <div className="card"><div className="loading" /> 加载资源状态...</div>
      ) : scan ? (
        <>
          <div className="card">
            <h3 className="card-title">Docker</h3>
            <div className="tool-row">
              <div className="tool-name">
                <span className={`status-dot ${scan.global.docker.docker.installed ? "ok" : "error"}`} />
                <span className="name">Docker 安装</span>
              </div>
            </div>
            <div className="tool-row">
              <div className="tool-name">
                <span className={`status-dot ${scan.global.docker.docker.daemon_running ? "ok" : "warning"}`} />
                <span className="name">Docker daemon</span>
              </div>
            </div>
            {scan.global.docker.containers.map((c) => (
              <div className="tool-row" key={c.name}>
                <div className="tool-name">
                  <span className={`status-dot ${c.status === "running" ? "ok" : c.status === "stopped" ? "warning" : "error"}`} />
                  <span className="name">{c.name}</span>
                  <span className="version">{c.image}</span>
                </div>
                <div className="tool-hint">{c.status}</div>
              </div>
            ))}
          </div>

          <div className="card">
            <h3 className="card-title">模型</h3>
            {scan.global.models.map((m) => (
              <div className="tool-row" key={m.name}>
                <div className="tool-name">
                  <span className={`status-dot ${m.loaded ? "ok" : "warning"}`} />
                  <span className="name">{m.name}</span>
                  <span className="version">{m.type}</span>
                </div>
                <div className="tool-hint">{m.loaded ? "已加载" : "加载中..."}</div>
              </div>
            ))}
          </div>

          <div className="card">
            <h3 className="card-title">必要配置</h3>
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
        </>
      ) : null}
    </div>
  );
};

export default StatusPage;
