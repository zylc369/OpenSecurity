/**
 * Docker 资源管理页。
 *
 * 显示：
 *   • daemon 状态
 *   • 已知容器（启停按钮）
 *   • 已知镜像（拉取按钮 + SSE 进度）
 *   • 实际容器/镜像列表
 */
import React, { useState, useEffect, useCallback } from "react";
import { api } from "../api/client";
import type { DockerScanGlobal } from "../types";

const DockerPage: React.FC = () => {
  const [data, setData] = useState<DockerScanGlobal | null>(null);
  const [loading, setLoading] = useState(true);
  const [pulling, setPulling] = useState<string | null>(null);
  const [pullLogs, setPullLogs] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api.getDockerStatus();
      setData(d);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const handlePull = (image: string) => {
    setPulling(image);
    setPullLogs([]);
    const stop = api.pullImage(image, (line) => {
      setPullLogs((prev) => [...prev.slice(-50), line]);
      if (line.startsWith("__done__") || line.startsWith("__error__")) {
        setPulling(null);
        refresh();
      }
    });
    return stop;
  };

  const handleContainerAction = async (name: string, action: "start" | "stop") => {
    setBusy(`${name}-${action}`);
    try {
      const fn = action === "start" ? api.startContainer : api.stopContainer;
      const r = await fn(name);
      if (!r.success) alert(r.message);
      await refresh();
    } finally {
      setBusy(null);
    }
  };

  if (loading && !data) {
    return (
      <div>
        <h2>Docker 管理</h2>
        <div className="card"><span className="loading" /> 加载中...</div>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div>
      <h2>
        Docker 管理
        <button className="btn btn-sm" style={{ marginLeft: 12 }} onClick={refresh}>
          刷新
        </button>
      </h2>

      <div className="card">
        <h3 className="card-title">daemon 状态</h3>
        <div className="tool-row">
          <div className="tool-name">
            <span className={`status-dot ${data.docker.installed ? "ok" : "error"}`} />
            <span className="name">Docker 安装</span>
          </div>
          <div className="tool-hint">{data.docker.installed ? "已安装" : "未安装"}</div>
        </div>
        <div className="tool-row">
          <div className="tool-name">
            <span className={`status-dot ${data.docker.daemon_running ? "ok" : "warning"}`} />
            <span className="name">Docker daemon</span>
          </div>
          <div className="tool-hint">{data.docker.daemon_running ? "运行中" : "未运行"}</div>
        </div>
      </div>

      <div className="card">
        <h3 className="card-title">已知容器</h3>
        {data.containers.length === 0 ? (
          <p style={{ color: "#718096" }}>无</p>
        ) : (
          data.containers.map((c) => (
            <div className="tool-row" key={c.name}>
              <div className="tool-name">
                <span className={`status-dot ${c.status === "running" ? "ok" : c.status === "stopped" ? "warning" : "error"}`} />
                <span className="name">{c.name}</span>
                <span className="version">{c.image}</span>
              </div>
              <div className="tool-hint">{c.description}</div>
              <div className="tool-actions">
                {c.status === "running" ? (
                  <button
                    className="btn btn-sm"
                    disabled={busy === `${c.name}-stop`}
                    onClick={() => handleContainerAction(c.name, "stop")}
                  >
                    {busy === `${c.name}-stop` ? "停止中..." : "停止"}
                  </button>
                ) : (
                  <button
                    className="btn btn-sm btn-primary"
                    disabled={busy === `${c.name}-start`}
                    onClick={() => handleContainerAction(c.name, "start")}
                  >
                    {busy === `${c.name}-start` ? "启动中..." : "启动"}
                  </button>
                )}
              </div>
            </div>
          ))
        )}
      </div>

      <div className="card">
        <h3 className="card-title">已知镜像</h3>
        {data.images.map((i) => (
          <div className="tool-row" key={i.name}>
            <div className="tool-name">
              <span className={`status-dot ${i.pulled ? "ok" : "error"}`} />
              <span className="name">{i.name}</span>
              <span className="version">{i.size_hint}</span>
            </div>
            <div className="tool-hint">{i.description}</div>
            <div className="tool-actions">
              {i.pulled ? (
                <span style={{ fontSize: 12, color: "#38a169" }}>已拉取</span>
              ) : pulling === i.name ? (
                <span className="loading" />
              ) : pulling !== null ? (
                <button className="btn btn-sm" disabled>等待中</button>
              ) : (
                <button
                  className="btn btn-sm btn-primary"
                  onClick={() => handlePull(i.name)}
                >
                  一键拉取
                </button>
              )}
            </div>
          </div>
        ))}

        {pulling && (
          <div className="progress-container">
            {pullLogs.map((line, idx) => (
              <div key={idx}>{line}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default DockerPage;
