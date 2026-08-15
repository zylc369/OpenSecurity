/**
 * 配置分区：meta 驱动的差异化表单（响应式 2 列网格）。
 *
 *   password → Input.Password（自带小眼睛，默认密文）
 *   path     → Input + 实时存在性徽标（防抖 400ms 调 /api/fs/check）
 *   bool     → Select(1/0)
 *   text     → Input
 *
 * 布局：≥992px 双列网格（屏占比优先），窄屏单列。
 * 保存前 trim（服务端 write 也兜底 trim，双保险）。
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  Form, Input, Select, Button, Tag, Space, Typography, App as AntApp, Alert, Row, Col, Tooltip,
} from "antd";
import { SaveOutlined, QuestionCircleOutlined } from "@ant-design/icons";
import type { ConfigMap, FsCheckResult } from "../types";
import { api } from "../api/client";
import { useAllConfig, useConfigMeta } from "../hooks";

/** 路径存在性徽标（防抖 400ms） */
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

const ConfigSection: React.FC = () => {
  const { message } = AntApp.useApp();
  const meta = useConfigMeta();
  const { data: configs, loading, save } = useAllConfig();
  const [values, setValues] = useState<ConfigMap>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (configs) setValues(configs);
  }, [configs]);

  const dirty = useMemo(() => {
    if (!configs) return false;
    return Object.keys(values).some((k) => (values[k] ?? "") !== (configs[k] ?? ""));
  }, [values, configs]);

  const requiredMissing = useMemo(() => {
    if (!meta.data || !values) return [];
    return Object.entries(meta.data)
      .filter(([k, m]) => m.required && !(values[k] ?? "").trim())
      .map(([, m]) => m.label);
  }, [meta.data, values]);

  const doSave = async () => {
    setSaving(true);
    try {
      const updates = Object.fromEntries(
        Object.entries(values).map(([k, v]) => [k, (v ?? "").trim()]),
      );
      await save(updates);
      message.success("配置已保存（已自动去除首尾空格）");
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  /** 分组规则：语义相关的配置共享一格（占 50% 宽），格内纵向排列 */
  const CONFIG_GROUPS: string[][] = [
    ["DEEPSEEK_API_KEY", "DEEPSEEK_MODEL"],  // DeepSeek 密钥 + 模型名是一套凭据
  ];

  const sortedGroups = useMemo(() => {
    if (!meta.data) return [];
    const keys = Object.entries(meta.data)
      .sort((a, b) => Number(b[1].required) - Number(a[1].required) || a[1].label.localeCompare(b[1].label))
      .map(([k]) => k);
    // 分组：组内保持 keys 顺序，未分组键各占一格
    const grouped: string[][] = [];
    const consumed = new Set<string>();
    for (const group of CONFIG_GROUPS) {
      const present = group.filter((k) => keys.includes(k));
      if (present.length > 1) {
        grouped.push(present);
        present.forEach((k) => consumed.add(k));
      }
    }
    for (const k of keys) if (!consumed.has(k)) grouped.push([k]);
    return grouped;
  }, [meta.data]);

  if (loading || !meta.data) return <Typography.Text type="secondary">加载中…</Typography.Text>;

  return (
    <Form layout="vertical" component="div">
      {requiredMissing.length > 0 && (
        <Alert
          type="warning" showIcon style={{ marginBottom: 16 }}
          message={`必要配置缺失：${requiredMissing.join("、")}`}
        />
      )}
      <Row gutter={[16, 0]}>
        {sortedGroups.map((group) => (
          /* 一组语义相关配置共享一行（lg=12 即 50% 宽），组内横排（密钥主项弹性 + 附属项定宽） */
          <Col xs={24} lg={12} key={group.join("+")}>
            <Form.Item
              style={{ marginBottom: 14 }}
              label={
                <Space size={8}>
                  {group.map((key) => {
                    const m = meta.data![key];
                    return (
                      <span key={key}>
                        {m.label}
                        {m.required ? (
                          <Tag color="red" style={{ marginInlineStart: 4 }}>必要</Tag>
                        ) : (
                          /* 可选说明悬浮：为什么可选 + 默认值（来自后端 meta，单一数据源） */
                          <Tooltip
                            title={
                              <div style={{ maxWidth: 280 }}>
                                <div>此项可不配置。</div>
                                <div>
                                  不配置时默认使用：
                                  <Typography.Text code style={{ color: "#fff" }}>
                                    {m.default_value || "（无默认值，建议配置）"}
                                  </Typography.Text>
                                </div>
                              </div>
                            }
                          >
                            <Tag style={{ marginInlineStart: 4, cursor: "help" }}>
                              可选 <QuestionCircleOutlined />
                            </Tag>
                          </Tooltip>
                        )}
                      </span>
                    );
                  })}
                </Space>
              }
            >
              <Space.Compact style={{ width: "100%" }}>
                {group.map((key) => {
                  const m = meta.data![key];
                  const v = values[key] ?? "";
                  const isMain = m.type === "password" || m.type === "path";
                  return (
                    <React.Fragment key={key}>
                      {m.type === "password" && (
                        <Input.Password
                          value={v} placeholder={group.length > 1 ? "密钥（默认隐藏）" : "输入密钥（默认隐藏）"}
                          autoComplete="new-password"
                          style={{ flex: isMain && group.length > 1 ? 1 : undefined }}
                          onChange={(e) => setValues((s) => ({ ...s, [key]: e.target.value }))}
                        />
                      )}
                      {m.type === "path" && (
                        <Input
                          value={v} placeholder="绝对路径（支持 ~）"
                          style={{ flex: isMain && group.length > 1 ? 1 : undefined }}
                          onChange={(e) => setValues((s) => ({ ...s, [key]: e.target.value }))}
                          suffix={<PathCheckBadge path={v} />}
                        />
                      )}
                      {m.type === "bool" && (
                        <Select
                          value={v === "" ? undefined : v} placeholder="未设置" allowClear
                          style={{ width: 120 }}
                          options={[{ value: "1", label: "开 (1)" }, { value: "0", label: "关 (0)" }]}
                          onChange={(nv) => setValues((s) => ({ ...s, [key]: nv ?? "" }))}
                        />
                      )}
                      {m.type === "text" && (
                        /* 组内非主 text 项定宽 180，防 100% 默认宽挤占主项；主项 flex:1 占余宽 */
                        <Input
                          value={v} placeholder={m.label}
                          style={group.length > 1 && !isMain
                            ? { width: 180, flexShrink: 0 }
                            : { flex: 1 }}
                          onChange={(e) => setValues((s) => ({ ...s, [key]: e.target.value }))}
                        />
                      )}
                    </React.Fragment>
                  );
                })}
              </Space.Compact>
              {group.some((key) => meta.data![key].hint) && (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {group.map((key) => meta.data![key].hint).filter(Boolean).join("；")}
                </Typography.Text>
              )}
            </Form.Item>
          </Col>
        ))}
      </Row>
      <Button type="primary" icon={<SaveOutlined />} loading={saving} disabled={!dirty}
        onClick={doSave}>
        保存{dirty ? "（有未保存修改）" : ""}
      </Button>
    </Form>
  );
};

export default ConfigSection;
