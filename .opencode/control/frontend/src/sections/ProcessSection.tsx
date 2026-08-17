/**
 * 进程分区：控制台后端管理的全部进程清单。
 *
 * 数据：本组件自轮询（10s）——进程状态与页面其余数据（环境就绪）生命周期不同，
 * 不并入 useScan 刷新链。
 *
 * 展示：每个进程的 PID/内存/用途/状态；OCR 行展开引用计数体系
 * （当前引用数、持有者明细、最后活跃时间）。
 */
import React, { useCallback, useEffect, useState } from "react";
import { Card, Table, Tag, Tooltip, Typography, Space } from "antd";
import { ReloadOutlined, QuestionCircleOutlined } from "@ant-design/icons";
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

/** 时间戳 → 相对时间（xx 秒/分 前）。 */
function relTime(ts: number | null): string {
  if (!ts) return "—";
  const sec = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (sec < 60) return `${sec} 秒前`;
  if (sec < 3600) return `${Math.floor(sec / 60)} 分前`;
  return `${Math.floor(sec / 3600)} 时 ${Math.floor((sec % 3600) / 60)} 分前`;
}

const ProcessSection: React.FC = () => {
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

  const cols = [
    {
      title: "进程",
      dataIndex: "name",
      width: 170,
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
      width: 90,
      render: (pid: number | null) => (pid != null ? String(pid) : "—"),
    },
    {
      title: "内存",
      dataIndex: "memory_footprint_mb",
      width: 110,
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
      width: 90,
      render: (s: string) => (
        <Tag color={STATUS_COLOR[s] ?? "default"} style={{ marginInlineEnd: 0 }}>
          {STATUS_TEXT[s] ?? s}
        </Tag>
      ),
    },
    {
      title: (
        <Space size={4}>
          引用计数
          <Tooltip title="OCR 模型实例的持有者数量：每个识图消费者（MCP 服务）启动时 +1、退出时 -1；归零 30 秒后空闲自动释放模型内存。悬停数字可看持有者明细（PID/命令行/最后心跳）。仅 OCR 行有此机制，其余进程显示 —">
            <QuestionCircleOutlined style={{ color: "#999", fontSize: 12 }} />
          </Tooltip>
        </Space>
      ),
      dataIndex: "ref_count",
      width: 100,
      render: (n: number | null, r: ProcessInfo) =>
        n == null ? (
          "—"
        ) : (
          <Tooltip
            title={
              r.holders.length > 0 ? (
                <div>
                  {r.holders.map((h, i) => (
                    <div key={i}>
                      PID {h.pid} · {h.alive ? "存活" : "已死"} ·{" "}
                      {h.last_seen_sec_ago != null ? `${h.last_seen_sec_ago.toFixed(0)}s 前` : "—"}
                      {h.cmdline && (
                        <div style={{ opacity: 0.7, fontSize: 11 }}>{h.cmdline}</div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                "无持有者（空闲计时中，归零 30s 后自动释放）"
              )
            }
          >
            <Typography.Text>{n}</Typography.Text>
          </Tooltip>
        ),
    },
    {
      title: "最后活跃",
      dataIndex: "last_active_at",
      width: 110,
      render: (ts: number | null) => relTime(ts),
    },
    {
      title: "启动命令",
      dataIndex: "cmdline",
      render: (c: string) => <EllipsisCell text={c} maxWidth={380} />,
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
      extra={
        <ReloadOutlined spin={loading} onClick={() => void refresh()} style={{ cursor: "pointer" }} />
      }
    >
      <Table
        rowKey="key"
        size="small"
        columns={cols}
        dataSource={data?.processes ?? []}
        loading={loading && !data}
        pagination={false}
        expandable={{
          rowExpandable: (r) => r.holders.length > 0,
          expandedRowRender: (r) => (
            <Table
              rowKey={(h) => `${h.pid}-${h.last_seen_sec_ago}`}
              size="small"
              pagination={false}
              dataSource={r.holders}
              columns={[
                { title: "持有者 PID", dataIndex: "pid", width: 110 },
                {
                  title: "状态",
                  dataIndex: "alive",
                  width: 90,
                  render: (a: boolean) =>
                    a ? <Tag color="green" style={{ marginInlineEnd: 0 }}>存活</Tag>
                      : <Tag color="red" style={{ marginInlineEnd: 0 }}>已退出</Tag>,
                },
                {
                  title: "最后心跳",
                  dataIndex: "last_seen_sec_ago",
                  width: 110,
                  render: (s: number | null) => (s != null ? `${s.toFixed(0)} 秒前` : "—"),
                },
                {
                  title: "命令行（识别持有者身份）",
                  dataIndex: "cmdline",
                  render: (c: string) => <EllipsisCell text={c} maxWidth={520} />,
                },
              ]}
            />
          ),
        }}
      />
    </Card>
  );
};

export default ProcessSection;
