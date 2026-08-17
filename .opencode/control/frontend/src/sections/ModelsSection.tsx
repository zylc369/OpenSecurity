/**
 * 模型分区：模型资产矩形块（按类型分组，组内每行两个）。
 *
 * 数据：App 的 useModels 统一拉取传入（下载中时 App 层轮询）。
 * OCR 的 loaded = 控制台 OCR 服务 state==="ready"（后端 get_model_assets 计算）。
 *
 * 布局：全局两列网格（类型由块上彩色 Tag 标识）；块内长文本（路径/用途/硬件说明）
 * 截断显示，悬浮显示全量（Typography ellipsis tooltip）。
 */
import React from "react";
import { Card, Tag, Button, Progress, Typography, Space, Alert, Row, Col } from "antd";
import { CloudDownloadOutlined, CheckCircleOutlined, PoweroffOutlined } from "@ant-design/icons";
import type { ModelAsset } from "../types";

interface Props {
  models: ModelAsset[] | undefined;
  onDownload: (id: string) => void;
  onRelease: () => void;   // OCR 强制释放（停止按钮）
}

const TYPE_META: Record<string, { color: string; label: string }> = {
  embedder: { color: "blue", label: "向量化" },
  reranker: { color: "purple", label: "重排序" },
  ocr: { color: "geekblue", label: "OCR" },
};

const ellipsis = { tooltip: true } as const;

const ModelBlock: React.FC<{ m: ModelAsset; onDownload: (id: string) => void; onRelease: () => void }> = ({ m, onDownload, onRelease }) => {
  const hw = m.hardware;
  const dl = m.download;
  const typeMeta = TYPE_META[m.type] ?? { color: "default", label: m.type };

  return (
    <Card size="small" style={{ height: "100%" }} bodyStyle={{ padding: "10px 12px" }}>
      <Space direction="vertical" size={6} style={{ width: "100%" }}>
        {/* 标题行：名称（截断+悬浮全量）+ 类型/状态 Tag */}
        <Space size={6} style={{ width: "100%" }}>
          <Typography.Text strong ellipsis={ellipsis} style={{ fontSize: 13, maxWidth: 130 }}>
            {m.display}
          </Typography.Text>
          <Tag color={typeMeta.color} style={{ marginInlineEnd: 0 }}>{typeMeta.label}</Tag>
          {m.cached ? (
            <Tag icon={<CheckCircleOutlined />} color="success" style={{ marginInlineEnd: 0 }}>{m.size_gb}GB</Tag>
          ) : (
            <Tag color="warning" style={{ marginInlineEnd: 0 }}>未下载</Tag>
          )}
          {m.loaded && (
            <Tag color="processing" style={{ marginInlineEnd: 0 }}>
              {m.type === "ocr" ? "运行中" : "已加载"}
            </Tag>
          )}
          {m.type === "ocr" && m.loaded && (
            <Button
              size="small" type="text" danger icon={<PoweroffOutlined />}
              onClick={onRelease} title="释放 OCR 模型内存（下次使用自动重载）"
            />
          )}
        </Space>

        {/* 用途 + 仓库（截断，悬浮全量） */}
        <Typography.Text type="secondary" ellipsis={ellipsis} style={{ fontSize: 12 }}>
          {m.purpose}
        </Typography.Text>
        <Typography.Text type="secondary" ellipsis={ellipsis} style={{ fontSize: 12 }}>
          {m.repo_id} · 参考 {m.disk_gb}GB
        </Typography.Text>

        {/* 缓存路径（截断，悬浮全量；未下载不显示） */}
        {m.cached && m.cache_path && (
          <Typography.Text code ellipsis={ellipsis} style={{ fontSize: 11, maxWidth: "100%" }}>
            {m.cache_path}
          </Typography.Text>
        )}

        {/* 硬件适配结论 */}
        {hw.ok ? (
          <Typography.Text type="success" ellipsis={ellipsis} style={{ fontSize: 12 }}>
            ✓ 硬件满足（可用 {hw.available_gb}GB ≥ 需求 {m.min_free_gb}GB）
            {hw.notes.length > 0 && ` · ${hw.notes.join(" · ")}`}
          </Typography.Text>
        ) : (
          <Alert type="error" showIcon style={{ padding: "2px 8px", fontSize: 12 }}
            message={<Typography.Text ellipsis={ellipsis} style={{ fontSize: 12 }}>{hw.reasons.join("；")}</Typography.Text>} />
        )}

        {/* 下载进度 / 错误 / 按钮 */}
        {dl.status === "downloading" && (
          <Progress percent={Math.round(dl.progress * 100)} status="active" size="small" format={(p) => `${p}%`} />
        )}
        {dl.status === "error" && (
          <Alert type="error" showIcon style={{ padding: "2px 8px" }}
            message={<Typography.Text ellipsis={ellipsis} style={{ fontSize: 12 }}>{dl.error}</Typography.Text>} />
        )}
        {!m.cached && dl.status !== "downloading" && (
          <div>
            <Button size="small" type="primary" icon={<CloudDownloadOutlined />}
              disabled={!hw.ok}
              title={hw.ok ? "下载模型权重" : "硬件不满足，无法下载"}
              onClick={() => onDownload(m.id)}>
              下载（约 {m.disk_gb}GB）
            </Button>
          </div>
        )}
      </Space>
    </Card>
  );
};

const ModelsSection: React.FC<Props> = ({ models, onDownload, onRelease }) => {
  if (!models) return <Typography.Text type="secondary">加载中…</Typography.Text>;

  return (
    <Row gutter={[8, 8]}>
      {models.map((m) => (
        <Col key={m.id} xs={24} md={12}>
          <ModelBlock m={m} onDownload={onDownload} onRelease={onRelease} />
        </Col>
      ))}
    </Row>
  );
};

export default ModelsSection;
