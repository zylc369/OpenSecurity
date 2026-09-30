/**
 * 配置页（#/config）——服务端分类驱动的配置管理面。
 *
 * 布局（Apple 系统设置风; 样式见 global.css .config-cats）:
 *   ≥lg: 左侧分类导航（图标+desc，选中态圆角高亮块，sticky）+ 右侧当前分类卡片
 *   <lg: 顶部水平滚动分类胶囊条
 *   卡片内双列网格（信息密度优先）; 保存按钮在卡片右上（dirty 提示）
 * 页面组成零定制: 分类/顺序/描述全部来自 /api/config/meta?surface=config，
 * 前端不硬编码任何配置项判断（图标映射除外——纯视觉）。
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  Alert, App as AntApp, Button, Card, Col, Row, Space, Tag, Typography,
} from "antd";
import { SaveOutlined } from "@ant-design/icons";
import { useAllConfig, useConfigMeta } from "../hooks";
import { groupByCategory, writableUpdates } from "../utils/configGrouping";
import { categoryIcon } from "../constants/configIcons";
import ConfigFieldRow from "../components/ConfigFieldRow";
import type { ConfigMap } from "../types";

const ConfigPage: React.FC = () => {
  const { message } = AntApp.useApp();
  const meta = useConfigMeta("config");
  const { data: configs, loading, save } = useAllConfig("config");
  const [values, setValues] = useState<ConfigMap>({});
  const [saving, setSaving] = useState(false);
  const [active, setActive] = useState("");

  useEffect(() => {
    if (configs) setValues(configs);
  }, [configs]);

  const groups = useMemo(
    () => (meta.data ? groupByCategory(meta.data.entries, meta.data.categories) : []),
    [meta.data]);

  // 默认选中首个分类（服务端序）
  useEffect(() => {
    if (!active && groups.length > 0) setActive(groups[0].code);
  }, [groups, active]);

  const dirty = useMemo(() => {
    if (!configs) return false;
    return Object.keys(values).some((k) => (values[k] ?? "") !== (configs[k] ?? ""));
  }, [values, configs]);

  const requiredMissing = useMemo(() => {
    if (!meta.data) return [];
    return Object.entries(meta.data.entries)
      .filter(([k, m]) => m.required && !(values[k] ?? "").trim())
      .map(([, m]) => m.label);
  }, [meta.data, values]);

  const doSave = async () => {
    setSaving(true);
    try {
      const entries = meta.data?.entries ?? {};
      // 只保存本页面可写键（全量 values 含其他 surface 键，整包回传会被 422）
      const updates = Object.fromEntries(
        Object.entries(writableUpdates(values, entries))
          .map(([k, v]) => [k, (v ?? "").trim()]),
      );
      await save(updates);
      message.success("配置已保存（已自动去除首尾空格）");
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  if (loading || !meta.data) {
    return <Typography.Text type="secondary">加载中…</Typography.Text>;
  }
  if (groups.length === 0) {
    return <Typography.Text type="secondary">无配置项</Typography.Text>;
  }

  const current = groups.find((g) => g.code === active) ?? groups[0];
  const HeadIcon = categoryIcon(current.code);
  // 守卫后捕获（JSX 回调内属性窄化会丢失）
  const entries = meta.data.entries;

  return (
    <Space direction="vertical" size={14} style={{ width: "100%" }}>
      {requiredMissing.length > 0 && (
        <Alert
          type="warning" showIcon
          message={`必要配置缺失：${requiredMissing.join("、")}`}
        />
      )}
      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        <nav className="config-cats" aria-label="配置分类">
          {groups.map((g) => {
            const GIcon = categoryIcon(g.code);
            const on = g.code === current.code;
            return (
              <button
                key={g.code}
                type="button"
                className={`config-cat${on ? " on" : ""}`}
                onClick={() => setActive(g.code)}
              >
                <GIcon />
                <span>{g.desc}</span>
              </button>
            );
          })}
        </nav>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Card
            size="small"
            title={
              <Space size={8}>
                <HeadIcon />
                <span>{current.desc}</span>
                <Tag style={{ marginInlineEnd: 0 }}>{current.keys.length} 项</Tag>
              </Space>
            }
            extra={
              <Button
                type="primary" icon={<SaveOutlined />} loading={saving}
                disabled={!dirty}
                onClick={() => void doSave()}
              >
                保存{dirty ? "（有未保存修改）" : ""}
              </Button>
            }
          >
            <Row gutter={[16, 0]}>
              {current.keys.map((key) => (
                <Col xs={24} lg={12} key={key}>
                  <ConfigFieldRow
                    meta={entries[key]}
                    value={values[key] ?? ""}
                    onChange={(v) => setValues((s) => ({ ...s, [key]: v }))}
                  />
                </Col>
              ))}
            </Row>
          </Card>
        </div>
      </div>
    </Space>
  );
};

export default ConfigPage;
