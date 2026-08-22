/**
 * 模型分区：模型资产卡片（两列网格）。
 *
 * 数据：App 的 useModels 统一拉取传入（下载中时 App 层轮询）。
 * 加载态: loaded 由后端真实判定（embedder=常驻标志, reranker=懒加载实际态,
 * OCR=服务 state==="ready"）; OCR 卡片额外显示当前引用数。
 *
 * 布局约定:
 *  - 不显示类型标签（向量化/重排序/OCR）——purpose 行已描述用途，避免重复
 *  - purpose 行为主视觉（主题色, 非灰）——它是用户最关心的"这模型干嘛的"
 *  - 硬件评估不逐模型显示（三个模型需求值相同导致重复）——汇总行在
 *    板块标题旁（App.tsx 传入 hardwareSummary）
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

const ellipsis = { tooltip: true } as const;

const ModelBlock: React.FC<{ m: ModelAsset; onDownload: (id: string) => void; onRelease: () => void }> = ({ m, onDownload, onRelease }) => {
  const dl = m.download;

  return (
    <Card size="small" style={{ height: "100%" }} bodyStyle={{ padding: "10px 12px" }}>
      <Space direction="vertical" size={6} style={{ width: "100%" }}>
        {/* 标题行：名称 + 大小/下载态 + 加载态（OCR 附引用数 + 停止按钮） */}
        <Space size={6} style={{ width: "100%" }}>
          <Typography.Text strong ellipsis={ellipsis} style={{ fontSize: 13, maxWidth: 150 }}>
            {m.display}
          </Typography.Text>
          {m.cached ? (
            <Tag icon={<CheckCircleOutlined />} color="success" style={{ marginInlineEnd: 0 }}>{m.size_gb}GB</Tag>
          ) : (
            <Tag color="warning" style={{ marginInlineEnd: 0 }}>未下载</Tag>
          )}
          {m.loaded && (
            <Tag color="processing" style={{ marginInlineEnd: 0 }}>
              {m.type === "ocr"
                ? `运行中${m.active_clients != null ? ` · ${m.active_clients} 引用` : ""}`
                : "已加载"}
            </Tag>
          )}
          {m.type === "ocr" && m.loaded && (
            <Button
              size="small" type="text" danger icon={<PoweroffOutlined />}
              onClick={onRelease} title="释放 OCR 模型内存（下次使用自动重载）"
            />
          )}
        </Space>

        {/* 用途（主视觉行——这模型是干什么的） */}
        <Typography.Text style={{ fontSize: 12.5, color: "#1677ff" }} ellipsis={ellipsis}>
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
