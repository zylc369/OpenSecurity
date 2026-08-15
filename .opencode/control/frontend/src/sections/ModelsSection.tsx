/**
 * 模型分区：模型资产卡（缓存状态/路径/硬件适配/下载）。
 *
 * 数据：App 的 useModels 统一拉取传入（下载中时 App 层轮询）。
 */
import React from "react";
import { Card, Tag, Button, Progress, Typography, Space, Descriptions, Alert } from "antd";
import { CloudDownloadOutlined, CheckCircleOutlined } from "@ant-design/icons";
import type { ModelAsset } from "../types";

interface Props {
  models: ModelAsset[] | undefined;
  hfCacheDir: string | undefined;
  onDownload: (id: string) => void;
}

const ModelCard: React.FC<{ m: ModelAsset; onDownload: (id: string) => void }> = ({ m, onDownload }) => {
  const hw = m.hardware;
  const dl = m.download;

  return (
    <Card size="small" style={{ marginBottom: 0 }}>
      <Space direction="vertical" size={8} style={{ width: "100%" }}>
        <Space wrap>
          <Typography.Text strong style={{ fontSize: 14 }}>{m.display}</Typography.Text>
          <Tag color={m.type === "embedder" ? "blue" : "purple"}>
            {m.type === "embedder" ? "向量化" : "重排序"}
          </Tag>
          {m.cached ? (
            <Tag icon={<CheckCircleOutlined />} color="success">磁盘 {m.size_gb}GB</Tag>
          ) : (
            <Tag color="warning">未下载</Tag>
          )}
          {m.loaded && <Tag color="processing">已加载</Tag>}
        </Space>

        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {m.purpose} · {m.repo_id} · 磁盘参考 {m.disk_gb}GB
        </Typography.Text>

        {m.cached && m.cache_path && (
          <Typography.Text code style={{ fontSize: 12 }}>{m.cache_path}</Typography.Text>
        )}

        {/* 硬件适配结论 */}
        {hw.ok ? (
          <Typography.Text type="success" style={{ fontSize: 12 }}>
            ✓ 硬件满足（可用内存 {hw.available_gb}GB ≥ 需求 {m.min_free_gb}GB）
            {hw.notes.length > 0 && ` · ${hw.notes.join(" · ")}`}
          </Typography.Text>
        ) : (
          <Alert
            type="error" showIcon style={{ padding: "4px 12px" }}
            message={hw.reasons.join("；")}
          />
        )}

        {/* 下载进度 / 错误 */}
        {dl.status === "downloading" && (
          <Progress percent={Math.round(dl.progress * 100)} status="active" size="small"
            format={(p) => `${p}%`} />
        )}
        {dl.status === "error" && (
          <Alert type="error" showIcon style={{ padding: "4px 12px" }} message={dl.error} />
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

const ModelsSection: React.FC<Props> = ({ models, hfCacheDir, onDownload }) => {
  if (!models) return <Typography.Text type="secondary">加载中…</Typography.Text>;

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      {hfCacheDir && (
        <Descriptions size="small" column={1} style={{ marginBottom: 0 }}>
          <Descriptions.Item label="缓存目录">
            <Typography.Text code style={{ fontSize: 12 }}>{hfCacheDir}</Typography.Text>
          </Descriptions.Item>
        </Descriptions>
      )}
      {models.map((m) => (
        <ModelCard key={m.id} m={m} onDownload={onDownload} />
      ))}
    </Space>
  );
};

export default ModelsSection;
