/**
 * 必要配置 banner（顶部红色横幅）。
 *
 * 当 DEEPSEEK_API_KEY、IDA_PRO_HOME 等必要配置缺失时显示。
 * 点击"立即配置"按钮跳转到 /config 页面。
 */
import React from "react";
import { useNavigate } from "react-router-dom";
import { useRequiredStatus } from "../hooks";

const RequiredConfigBanner: React.FC = () => {
  const navigate = useNavigate();
  const { data, loading, error } = useRequiredStatus();

  if (loading || error || !data) return null;

  // 找出缺失的必要配置
  const missing = Object.entries(data).filter(([_, v]) => !v.ok);
  if (missing.length === 0) return null;

  const missingLabels = missing.map(([_, v]) => v.label).join(", ");

  return (
    <div className="banner">
      <div>
        <strong>⚠️ 必要配置缺失：</strong>
        {missingLabels}（部分功能不可用）
      </div>
      <button onClick={() => navigate("/config")}>
        立即配置
      </button>
    </div>
  );
};

export default RequiredConfigBanner;
