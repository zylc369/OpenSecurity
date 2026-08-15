/**
 * Docker 分区：容器管理 + 镜像拉取。
 *
 * 数据：App 的 useScan 统一拉取（global.docker），本组件不重复请求。
 */
import React, { useState } from "react";
import { Table, Tag, Button, Space, Progress, Typography, App as AntApp } from "antd";
import { PlayCircleOutlined, PauseCircleOutlined, CloudDownloadOutlined } from "@ant-design/icons";
import type { DockerScanGlobal, KnownContainer, KnownImage } from "../types";
import { api } from "../api/client";

const STATUS_COLOR: Record<string, string> = {
  running: "green",
  stopped: "orange",
  not_exists: "default",
  unknown: "default",
};
const STATUS_TEXT: Record<string, string> = {
  running: "运行中",
  stopped: "已停止",
  not_exists: "未创建",
  unknown: "未知",
};

interface Props {
  docker: DockerScanGlobal | undefined;
  onRefresh: () => void;
}

const DockerSection: React.FC<Props> = ({ docker, onRefresh }) => {
  const { message } = AntApp.useApp();
  const [pulling, setPulling] = useState<Record<string, string>>({}); // image → 进度行

  const doContainerAction = async (name: string, action: "start" | "stop") => {
    try {
      const fn = action === "start" ? api.startContainer : api.stopContainer;
      const r = await fn(name);
      message[r.success ? "success" : "error"](r.message);
      onRefresh();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const doPull = (image: string) => {
    setPulling((p) => ({ ...p, [image]: "连接中…" }));
    api.pullImage(image, (line) => {
      // 完成信号：后端 pull_image_stream 最后一行 __done__ exit_code=N（权威标志）
      if (line.startsWith("__error__")) {
        message.error(line.replace("__error__ ", ""));
        setPulling((p) => {
          const next = { ...p };
          delete next[image];
          return next;
        });
        return;
      }
      if (line.startsWith("__done__")) {
        const code = parseInt(line.split("exit_code=")[1] ?? "1", 10);
        if (code === 0) {
          message.success(`${image} 拉取完成`);
        } else {
          message.error(`${image} 拉取失败（exit ${code}）`);
        }
        setTimeout(() => {
          setPulling((p) => {
            const next = { ...p };
            delete next[image];
            return next;
          });
          onRefresh();
        }, 600);
        return;
      }
      // 普通进度行
      setPulling((p) => ({ ...p, [image]: line.slice(0, 80) }));
    });
  };

  if (!docker) return <Typography.Text type="secondary">加载中…</Typography.Text>;

  const containerCols = [
    { title: "容器", dataIndex: "name", width: 160 },
    { title: "镜像", dataIndex: "image" },
    { title: "说明", dataIndex: "description", ellipsis: true },
    {
      title: "状态", dataIndex: "status", width: 100,
      render: (s: string) => <Tag color={STATUS_COLOR[s]}>{STATUS_TEXT[s]}</Tag>,
    },
    {
      title: "操作", width: 100,
      render: (_: unknown, r: KnownContainer) =>
        r.status === "running" ? (
          <Button size="small" icon={<PauseCircleOutlined />}
            onClick={() => doContainerAction(r.name, "stop")}>停止</Button>
        ) : (
          <Button size="small" type="primary" ghost icon={<PlayCircleOutlined />}
            disabled={r.status === "not_exists"}
            onClick={() => doContainerAction(r.name, "start")}>启动</Button>
        ),
    },
  ];

  const imageCols = [
    { title: "镜像", dataIndex: "name", width: 260 },
    { title: "说明", dataIndex: "description", ellipsis: true },
    { title: "大小", dataIndex: "size_hint", width: 100 },
    {
      title: "状态", dataIndex: "pulled", width: 90,
      render: (v: boolean) => (v ? <Tag color="green">已拉取</Tag> : <Tag>未拉取</Tag>),
    },
    {
      title: "操作", width: 100,
      render: (_: unknown, r: KnownImage) =>
        r.pulled ? (
          <Typography.Text type="secondary">—</Typography.Text>
        ) : pulling[r.name] ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{pulling[r.name]}</Typography.Text>
        ) : (
          <Button size="small" icon={<CloudDownloadOutlined />} onClick={() => doPull(r.name)}>拉取</Button>
        ),
    },
  ];

  const missingImages = docker.images.filter((i) => !i.pulled);

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      {docker.docker.installed ? (
        docker.docker.daemon_running ? (
          <Typography.Text type="secondary">Docker daemon 正常</Typography.Text>
        ) : (
          <Typography.Text type="danger">Docker 已安装但 daemon 未运行（请先启动 Docker Desktop）</Typography.Text>
        )
      ) : (
        <Typography.Text type="danger">Docker 未安装</Typography.Text>
      )}

      <div>
        <Typography.Title level={5}>容器</Typography.Title>
        <Table<KnownContainer>
          size="small" rowKey="name" pagination={false}
          columns={containerCols} dataSource={docker.containers}
        />
      </div>

      <div>
        <Typography.Title level={5}>镜像（{docker.images.filter((i) => i.pulled).length}/{docker.images.length}）</Typography.Title>
        <Table<KnownImage>
          size="small" rowKey="name" pagination={false}
          columns={imageCols} dataSource={docker.images}
        />
        {Object.keys(pulling).length > 0 && (
          <Space direction="vertical" style={{ marginTop: 12, width: "100%" }}>
            {Object.entries(pulling).map(([img, line]) => (
              <div key={img}>
                <Typography.Text strong style={{ fontSize: 12 }}>{img}</Typography.Text>
                <Progress percent={99} status="active" size="small"
                  format={() => line} />
              </div>
            ))}
          </Space>
        )}
        {missingImages.length > 0 && (
          <Typography.Text type="secondary" style={{ fontSize: 12, display: "block", marginTop: 8 }}>
            {missingImages.length} 个镜像未拉取
          </Typography.Text>
        )}
      </div>
    </Space>
  );
};

export default DockerSection;
