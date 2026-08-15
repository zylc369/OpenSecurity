/**
 * 硬件信息页。
 *
 * 显示完整硬件规格（CPU、内存、OS、GPU 详细信息）。
 */
import React from "react";
import { useHardware } from "../hooks";

const HardwarePage: React.FC = () => {
  const { data: hw, loading, error } = useHardware();

  if (loading) {
    return (
      <div>
        <h2>硬件信息</h2>
        <div className="card"><span className="loading" /> 加载硬件信息...</div>
      </div>
    );
  }

  if (error) {
    return <div className="card">硬件信息加载失败：{error}</div>;
  }

  if (!hw) return null;

  return (
    <div>
      <h2>硬件信息</h2>

      <div className="card">
        <h3 className="card-title">CPU</h3>
        <div className="tool-row">
          <div className="tool-name"><span className="name">物理核</span></div>
          <div className="tool-hint">{hw.cpu.physical_cores}</div>
        </div>
        <div className="tool-row">
          <div className="tool-name"><span className="name">逻辑核</span></div>
          <div className="tool-hint">{hw.cpu.logical_cores}</div>
        </div>
        <div className="tool-row">
          <div className="tool-name"><span className="name">频率</span></div>
          <div className="tool-hint">{hw.cpu.frequency_mhz ?? "?"} MHz</div>
        </div>
      </div>

      <div className="card">
        <h3 className="card-title">内存</h3>
        <div className="tool-row">
          <div className="tool-name"><span className="name">总内存</span></div>
          <div className="tool-hint">{hw.memory.total_gb} GB</div>
        </div>
        <div className="tool-row">
          <div className="tool-name"><span className="name">可用</span></div>
          <div className="tool-hint">{hw.memory.available_gb} GB</div>
        </div>
      </div>

      <div className="card">
        <h3 className="card-title">操作系统</h3>
        <div className="tool-row">
          <div className="tool-name"><span className="name">系统</span></div>
          <div className="tool-hint">{hw.os.system}</div>
        </div>
        <div className="tool-row">
          <div className="tool-name"><span className="name">平台</span></div>
          <div className="tool-hint">{hw.os.platform}</div>
        </div>
        <div className="tool-row">
          <div className="tool-name"><span className="name">架构</span></div>
          <div className="tool-hint">{hw.os.machine}</div>
        </div>
        <div className="tool-row">
          <div className="tool-name"><span className="name">内核版本</span></div>
          <div className="tool-hint" style={{ fontSize: 11 }}>{hw.os.version}</div>
        </div>
      </div>

      <div className="card">
        <h3 className="card-title">GPU（{hw.gpu.length}）</h3>
        {hw.gpu.length === 0 ? (
          <p style={{ color: "#718096" }}>未检测到 GPU</p>
        ) : (
          hw.gpu.map((g, idx) => (
            <div key={idx} style={{ marginBottom: 16, paddingBottom: 16, borderBottom: idx < hw.gpu.length - 1 ? "1px solid #edf2f7" : "none" }}>
              <div className="tool-row">
                <div className="tool-name"><span className="name">名称</span></div>
                <div className="tool-hint">{g.name}</div>
              </div>
              {g.vendor && (
                <div className="tool-row">
                  <div className="tool-name"><span className="name">厂商</span></div>
                  <div className="tool-hint">{g.vendor}</div>
                </div>
              )}
              {g.metal && (
                <div className="tool-row">
                  <div className="tool-name"><span className="name">Metal</span></div>
                  <div className="tool-hint">{g.metal}</div>
                </div>
              )}
              {g.vram && (
                <div className="tool-row">
                  <div className="tool-name"><span className="name">显存</span></div>
                  <div className="tool-hint">{g.vram}</div>
                </div>
              )}
              {g.vram_gb && (
                <div className="tool-row">
                  <div className="tool-name"><span className="name">显存（GB）</span></div>
                  <div className="tool-hint">{g.vram_gb} GB</div>
                </div>
              )}
              <div className="tool-row">
                <div className="tool-name"><span className="name">支持能力</span></div>
                <div className="tool-hint">
                  {g.capabilities.length > 0 ? g.capabilities.join(" · ") : "（无）"}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default HardwarePage;
