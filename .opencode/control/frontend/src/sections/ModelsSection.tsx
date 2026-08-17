/**
 * 模型分区：模型资产卡（缓存状态/路径/硬件适配/下载；OCR 卡含运行状态/停止）。
 *
 * 数据：App 的 useModels 统一拉取传入（下载中时 App 层轮询）。
 * OCR 的 loaded = 控制台 OCR 服务 state==="ready"（后端 get_model_assets 计算）。
 */
import React from "react";
import { Card, Tag, Button, Progress, Typography, Space, Descriptions, Alert } from "antd";
import { CloudDownloadOutlined, CheckCircleOutlined, PoweroffOutlined } from "@ant-design/icons";
import type { ModelAsset } from "../types";

interface Props {
  models: ModelAsset[] | undefined;
  hfCacheDir: string | undefined;
  onDownload: (id: string) => void;
  onRelease: () => void;   // OCR 强制释放（停止按钮）
}

const TYPE_META: Record<string, { color: string; label: string }> = {
  embedder: { color: "blue", label: "向量化" },
  reranker: { color: "purple", label: "重排序" },
  ocr: { color: "geekblue", label: "OCR" },
};

const ModelCard: React.FC<{ m: ModelAsset; onDownload: (id: string) => void; onRelease: () => void }> = ({ m, onDownload, onRelease }) => {
  const hw = m.hardware;
  const dl = m.download;
  const typeMeta = TYPE_META[m.type] ?? { color: "default", label: m.type };

  return (
    <Card size="small" style={{ marginBottom: 0 }}>
      <Space direction="vertical" size={8} style={{ width: "100%" }}>
        <Space wrap>
          <Typography.Text strong style={{ fontSize: 14 }}>{m.display}</Typography.Text>
          <Tag color={typeMeta.color}>{typeMeta.label}</Tag>
          {m.cached ? (
            <Tag icon={<CheckCircleOutlined />} color="success">磁盘 {m.size_gb}GB</Tag>
          ) : (
            <Tag color="warning">未下载</Tag>
          )}
          {m.type === "ocr" ? (
            m.loaded && <Tag color="processing">运行中</Tag>
          ) : (
            m.loaded && <Tag color="processing">已加载</Tag>
          )}
          {m.type === "ocr" && m.loaded && (
            <Button
              size="small"
              icon={<PoweroffOutlined />}
              onClick={onRelease}
              title="释放 OCR 模型内存（下次使用自动重载）"
            >
              停止
            </Button>
          )}
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

const ModelsSection: React.FC<Props> = ({ models, hfCacheDir, onDownload, onRelease }) => {
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
        <ModelCard key={m.id} m={m} onDownload={onDownload} onRelease={onRelease} />
      ))}
    </Space>
  );
};

export default ModelsSection;
