/**
 * 进程分区：控制台后端管理的进程清单（「运行状态」页右卡）。
 *
 * 数据：GET /api/processes（10s 自轮询 + 页级统一刷新按钮经 refreshToken 触发）。
 * 刷新归属：本组件无独立刷新按钮——运行状态页顶部统一刷新（用户指令：
 * 不要一块一块点刷新）。
 */
import React, { useCallback, useEffect, useState } from "react";
import { Card, Table, Tag, Tooltip, Typography } from "antd";
import type { ProcessInfo, ProcessRegistryView } from "../types";
import { api } from "../api/client";
import EllipsisCell from "../components/EllipsisCell";

const STATUS_COLOR: Record<string, string> = {
  running: "green",
  ready: "green",
  starting: "blue",
  stopping: "orange",
  stopped: "default",
  idle: "default",
};
const STATUS_TEXT: Record<string, string> = {
  running: "运行中",
  ready: "运行中",
  starting: "启动中",
  stopping: "停止中",
  stopped: "已停止",
  idle: "空闲",
};

function fmtMB(m: number): string {
  return m >= 1024 ? `${(m / 1024).toFixed(2)} GB` : `${m.toFixed(0)} MB`;
}

interface Props {
  /** 页级统一刷新信号（递增计数器；>0 时触发一次立即刷新） */
  refreshToken: number;
}

const ProcessSection: React.FC<Props> = ({ refreshToken }) => {
  const [data, setData] = useState<ProcessRegistryView | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.getProcesses());
    } catch {
      /* 轮询失败静默（下次重试） */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), 10_000);
    return () => clearInterval(t);
  }, [refresh]);

  // 页级统一刷新（跳过首渲染 0——挂载 effect 已刷）
  useEffect(() => {
    if (refreshToken > 0) void refresh();
  }, [refreshToken, refresh]);

  const cols = [
    {
      title: "进程",
      dataIndex: "name",
      width: 150,
      render: (_: unknown, r: ProcessInfo) => (
        <Tooltip title={r.role} placement="topLeft">
          <Typography.Text strong>{r.name}</Typography.Text>
          <div style={{ fontSize: 12, color: "#888" }}>{r.extra || "　"}</div>
        </Tooltip>
      ),
    },
    {
      title: "PID",
      dataIndex: "pid",
      width: 80,
      render: (pid: number | null) => (pid != null ? String(pid) : "—"),
    },
    {
      title: "内存",
      dataIndex: "memory_footprint_mb",
      width: 100,
      render: (fp: number | null, r: ProcessInfo) => {
        const rss = r.memory_mb;
        // footprint = 活动监视器"内存"列同口径；缺失（非 macOS）回退 RSS
        const main = fp ?? rss;
        if (main == null) return "—";
        const tip = fp != null && rss != null && Math.abs(fp - rss) > 1
          ? `活动监视器口径 ${fp.toFixed(0)} MB（含压缩页 + GPU/Metal 映射）\nRSS ${rss.toFixed(0)} MB（仅驻留未压缩页，看不见 MPS/MLX 模型权重）`
          : null;
        return tip ? (
          <Tooltip title={<div style={{ whiteSpace: "pre-line" }}>{tip}</div> }>
            <Typography.Text strong>{fmtMB(main)}</Typography.Text>
          </Tooltip>
        ) : (
          fmtMB(main)
        );
      },
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 80,
      render: (s: string) => (
        <Tag color={STATUS_COLOR[s] ?? "default"} style={{ marginInlineEnd: 0 }}>
          {STATUS_TEXT[s] ?? s}
        </Tag>
      ),
    },
    {
      title: "启动命令",
      dataIndex: "cmdline",
      render: (c: string) => <EllipsisCell text={c} maxWidth={260} />,
    },
  ];

  return (
    <Card
      size="small"
      title={
        <span>
          进程
          <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12, fontWeight: 400 }}>
            控制台管理的进程（10s 轮询）
          </Typography.Text>
        </span>
      }
    >
      <Table
        rowKey="key"
        size="small"
        columns={cols}
        dataSource={data?.processes ?? []}
        loading={loading && !data}
        pagination={false}
      />
    </Card>
  );
};

export default ProcessSection;
