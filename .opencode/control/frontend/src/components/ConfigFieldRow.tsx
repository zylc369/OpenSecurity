/**
 * 配置条目共享渲染组件（配置页 + 远程页复用——meta 驱动，零页面定制）。
 *
 * 一行 = label（必要/可选徽标）+ 类型差异化控件; hint 统一渲染在控件下方
 * （Form.Item extra——与控件宽度无关，避免「宽输入框 hint 换行 / 窄下拉框
 * hint 同行」的位置不一致）:
 *   password → Input.Password（小眼睛）   path → Input + 实时存在性徽标
 *   bool     → Select(1/0)                text  → Input
 *   readonly=true → 控件禁用 + 显示生效值（值或默认）+「只读」徽标。
 */
import React, { useEffect, useState } from "react";
import { Form, Input, Select, Space, Tag, Tooltip, Typography } from "antd";
import { QuestionCircleOutlined } from "@ant-design/icons";
import type { ConfigMetaItem, FsCheckResult } from "../types";
import { api } from "../api/client";

/** 路径存在性徽标（防抖 400ms 调 /api/fs/check） */
const PathCheckBadge: React.FC<{ path: string }> = ({ path }) => {
  const [result, setResult] = useState<FsCheckResult | null>(null);

  useEffect(() => {
    const trimmed = path.trim();
    if (!trimmed) { setResult(null); return; }
    const t = setTimeout(() => {
      api.fsCheck(trimmed).then(setResult).catch(() => setResult(null));
    }, 400);
    return () => clearTimeout(t);
  }, [path]);

  if (!path.trim() || !result) return null;
  return result.exists
    ? <Tag color="success" style={{ marginInlineEnd: 0 }}>存在</Tag>
    : <Tag color="error" style={{ marginInlineEnd: 0 }}>不存在</Tag>;
};

/** bool 值显示文案（readonly 态共用） */
const boolLabel = (v: string): string =>
  v === "1" ? "开" : v === "0" ? "关" : "未设置";

const ConfigFieldRow: React.FC<{
  meta: ConfigMetaItem;
  value: string;
  onChange?: (v: string) => void;
}> = ({ meta: m, value, onChange }) => {
  const ro = m.readonly;
  const disabled = ro || onChange === undefined;
  const set = (v: string) => { if (!disabled && onChange) onChange(v); };

  /** readonly 态生效值展示（未配置 → 默认值标注） */
  const effectiveText = (): string => {
    if (value) return value;
    if (m.default_value) return `${m.default_value}（默认）`;
    return "未设置";
  };

  const control = (() => {
    if (m.type === "password") {
      return (
        <Input.Password
          value={value}
          placeholder={ro ? effectiveText() : "输入密钥（默认隐藏）"}
          disabled={disabled}
          autoComplete="new-password"
          visibilityToggle={!disabled}
          onChange={(e) => set(e.target.value)}
        />
      );
    }
    if (m.type === "path") {
      return (
        <Input
          value={value}
          placeholder={ro ? effectiveText() : "绝对路径（支持 ~）"}
          disabled={disabled}
          suffix={<PathCheckBadge path={value} />}
          onChange={(e) => set(e.target.value)}
        />
      );
    }
    if (m.type === "bool") {
      if (ro) {
        return (
          <Space size={8}>
            <Typography.Text>{boolLabel(value)}</Typography.Text>
            <Tag style={{ marginInlineEnd: 0 }}>只读</Tag>
          </Space>
        );
      }
      return (
        <Select
          value={value === "" ? undefined : value} placeholder="未设置" allowClear
          disabled={disabled}
          style={{ width: 140 }}
          options={[{ value: "1", label: "开 (1)" }, { value: "0", label: "关 (0)" }]}
          onChange={(nv) => set(nv ?? "")}
        />
      );
    }
    // text
    if (ro) {
      return (
        <Space size={8}>
          <Typography.Text code>{effectiveText()}</Typography.Text>
          <Tag style={{ marginInlineEnd: 0 }}>只读</Tag>
        </Space>
      );
    }
    return (
      <Input
        value={value}
        placeholder={m.label}
        disabled={disabled}
        onChange={(e) => set(e.target.value)}
      />
    );
  })();

  return (
    <Form.Item
      style={{ marginBottom: 14 }}
      extra={
        m.hint ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {m.hint}
          </Typography.Text>
        ) : undefined
      }
      label={
        <Space size={8}>
          <span>{m.label}</span>
          {m.required ? (
            <Tag color="red" style={{ marginInlineStart: 4 }}>必要</Tag>
          ) : (
            <Tooltip
              title={
                <div style={{ maxWidth: 280 }}>
                  <div>此项可不配置。</div>
                  {m.default_value && (
                    <div>
                      不配置时默认使用：
                      <Typography.Text code style={{ color: "#fff" }}>
                        {m.default_value}
                      </Typography.Text>
                    </div>
                  )}
                </div>
              }
            >
              <Tag style={{ marginInlineStart: 4, cursor: "help" }}>
                可选 <QuestionCircleOutlined />
              </Tag>
            </Tooltip>
          )}
        </Space>
      }
    >
      {control}
    </Form.Item>
  );
};

export default ConfigFieldRow;
