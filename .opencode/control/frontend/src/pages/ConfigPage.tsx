/**
 * 配置管理页（.ai_env 编辑）。
 *
 * 显示：
 *   • 必要配置表单（缺失时高亮）
 *   • 可选配置
 *   • 保存按钮
 */
import React, { useState } from "react";
import { useAllConfig } from "../hooks";
import { api } from "../api/client";

const ConfigPage: React.FC = () => {
  const { data: configs, loading, error, save, refresh } = useAllConfig();
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  if (loading && !configs) {
    return (
      <div>
        <h2>配置管理</h2>
        <div className="card"><span className="loading" /> 加载配置...</div>
      </div>
    );
  }

  if (error) {
    return <div className="card">配置加载失败：{error}</div>;
  }

  if (!configs) return null;

  // 必要配置
  const requiredKeys = ["DEEPSEEK_API_KEY", "IDA_PRO_HOME"];
  // 可选配置（除必要外的已知配置）
  const optionalKeys = ["DEEPSEEK_MODEL", "RESUME_ANALYSIS_ENABLED"];

  const getValue = (key: string) => editing[key] ?? configs[key] ?? "";

  const setValue = (key: string, value: string) => {
    setEditing({ ...editing, [key]: value });
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await save(editing);
      setEditing({});
      alert("保存成功");
      refresh();
    } catch (e) {
      alert("保存失败：" + (e instanceof Error ? e.message : String(e)));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (key: string) => {
    if (!confirm(`删除配置项 ${key}？`)) return;
    try {
      await api.deleteConfig(key);
      refresh();
    } catch (e) {
      alert("删除失败：" + (e instanceof Error ? e.message : String(e)));
    }
  };

  return (
    <div>
      <h2>
        配置管理
        {Object.keys(editing).length > 0 && (
          <button
            className="btn btn-primary btn-sm"
            style={{ marginLeft: 12 }}
            disabled={saving}
            onClick={handleSave}
          >
            {saving ? "保存中..." : `保存到 .ai_env（${Object.keys(editing).length} 项）`}
          </button>
        )}
      </h2>

      <div className="card">
        <h3 className="card-title">必要配置<span style={{ color: "#e53e3e", fontSize: 13 }}>（缺失会影响功能）</span></h3>

        <div className="form-group">
          <label>DEEPSEEK_API_KEY<span className="required-mark">*</span></label>
          <input
            type="password"
            value={getValue("DEEPSEEK_API_KEY")}
            onChange={(e) => setValue("DEEPSEEK_API_KEY", e.target.value)}
            placeholder="sk-xxx"
          />
          <div className="hint">获取地址：https://platform.deepseek.com/api-keys</div>
        </div>

        <div className="form-group">
          <label>IDA_PRO_HOME<span className="required-mark">*</span></label>
          <input
            type="text"
            value={getValue("IDA_PRO_HOME")}
            onChange={(e) => setValue("IDA_PRO_HOME", e.target.value)}
            placeholder="/Applications/IDA Professional 9.1.app/Contents/MacOS"
          />
          <div className="hint">IDA Pro 安装目录（该目录下需有 idat 可执行文件）</div>
        </div>
      </div>

      <div className="card">
        <h3 className="card-title">可选配置</h3>

        <div className="form-group">
          <label>DEEPSEEK_MODEL</label>
          <input
            type="text"
            value={getValue("DEEPSEEK_MODEL")}
            onChange={(e) => setValue("DEEPSEEK_MODEL", e.target.value)}
            placeholder="deepseek-v4-flash"
          />
          <div className="hint">DeepSeek 模型名（影响 LLM 调用）</div>
        </div>

        <div className="form-group">
          <label>RESUME_ANALYSIS_ENABLED</label>
          <input
            type="text"
            value={getValue("RESUME_ANALYSIS_ENABLED")}
            onChange={(e) => setValue("RESUME_ANALYSIS_ENABLED", e.target.value)}
            placeholder="0 或 1"
          />
          <div className="hint">
            分析恢复开关（1/true=启用，0/false=禁用）。启用时 AI 完成一轮未输出完成标记会自动续传。
          </div>
        </div>
      </div>

      {Object.keys(configs).length > requiredKeys.length + optionalKeys.length && (
        <div className="card">
          <h3 className="card-title">其他配置</h3>
          {Object.entries(configs)
            .filter(([k]) => !requiredKeys.includes(k) && !optionalKeys.includes(k))
            .map(([k, v]) => (
              <div className="tool-row" key={k}>
                <div className="tool-name">
                  <span className="name" style={{ fontFamily: "monospace" }}>{k}</span>
                  <span className="version" style={{ fontFamily: "monospace" }}>
                    {v.length > 30 ? v.slice(0, 30) + "..." : v}
                  </span>
                </div>
                <div className="tool-actions">
                  <button className="btn btn-sm" onClick={() => handleDelete(k)}>删除</button>
                </div>
              </div>
            ))}
        </div>
      )}
    </div>
  );
};

export default ConfigPage;
