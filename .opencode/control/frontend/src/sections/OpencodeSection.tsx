/**
 * 连接的 opencode 进程分区（「运行状态」页核心卡）。
 *
 * 数据：GET /api/heartbeats（心跳注册表快照 + psutil 富化），本组件自轮询
 * （10s）——与 ProcessSection 同模式：运行时数据不并入 useScan 刷新链。
 *
 * 摘要行：控制台自身身份（PID / 已运行 / boot 令牌）——/api/system 拉取一次
 * （boot_token 经 /api/health 原生 fetch：模型加载中 503 时 axios 拦截器抛错，
 * 而 503 响应体仍含识别字段，fetch 模式可容忍）。
 */
import React, { useCallback, useEffect, useState } from "react";
import { Card, Table, Tag, Tooltip, Typography } from "antd";
import type { OpencodeProcessInfo, SystemInfo } from "../types";
import { api } from "../api/client";
import EllipsisCell from "../components/EllipsisCell";
import { fmtDuration } from "../utils/format";

/** 心跳周期 10s; 超过 1.5 周期未跳视为延迟（网络抖动/卡顿）。 */
const HEARTBEAT_STALE_SEC = 15;

type OpencodeStatus = "online" | "stale" | "gone";

function statusOf(p: OpencodeProcessInfo): OpencodeStatus {
  if (!p.alive) return "gone";
  if (p.last_seen_sec_ago > HEARTBEAT_STALE_SEC) return "stale";
  return "online";
}

const STATUS_PROP: Record<
  OpencodeStatus,
  { color: string; text: string; tip: string }
> = {
  online: { color: "green", text: "在线", tip: "心跳正常（10s 周期）" },
  stale: {
    color: "orange",
    text: "心跳延迟",
    tip: `超过 ${HEARTBEAT_STALE_SEC}s 未跳（进程存活）——可能卡顿或系统繁忙`,
  },
  gone: {
    color: "red",
    text: "疑似退出",
    tip: "进程已不存在；心跳条目为残留，60s 内自动清除",
  },
};

/** 摘要行：控制台自身身份。独立小段（Typography，非卡片——管理进程表已有 console 行）。 */
function ConsoleSummary({ system }: { system: SystemInfo | null }) {
  const [boot, setBoot] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    fetch("/api/health")
      .then((r) => r.json())
      .then((d: { boot_token?: unknown }) => {
        if (alive && typeof d.boot_token === "string") setBoot(d.boot_token);
      })
      .catch(() => {
        /* 摘要行降级——boot_token 缺失不影响主表格 */
      });
    return () => {
      alive = false;
    };
  }, []);
  if (!system) return null;
  return (
    <Typography.Text
      type="secondary"
      style={{ fontSize: 12.5, display: "block", marginBottom: 12 }}
    >
      控制台 PID {system.control_pid} · 已运行{" "}
      {fmtDuration(Date.now() / 1000 - system.control_start_time)}
      {boot && ` · boot ${boot}`}
    </Typography.Text>
  );
}

const OpencodeSection: React.FC<{
  system: SystemInfo | null;
  refreshToken: number;
}> = ({ system, refreshToken }) => {
  const [rows, setRows] = useState<OpencodeProcessInfo[] | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setRows((await api.getHeartbeats()).opencode);
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
      title: "PID",
      dataIndex: "pid",
      width: 90,
      render: (pid: number) => <Typography.Text strong>{pid}</Typography.Text>,
    },
    {
      title: "状态",
      dataIndex: "alive",
      width: 110,
      render: (_: unknown, r: OpencodeProcessInfo) => {
        const s = STATUS_PROP[statusOf(r)];
        return (
          <Tooltip title={s.tip}>
            <Tag color={s.color} style={{ marginInlineEnd: 0 }}>
              {s.text}
            </Tag>
          </Tooltip>
        );
      },
    },
    {
      title: "最后心跳",
      dataIndex: "last_seen_sec_ago",
      width: 100,
      render: (s: number) => fmtDuration(s),
    },
    {
      title: "运行时长",
      dataIndex: "running_sec",
      width: 100,
      render: (s: number | null) => fmtDuration(s),
    },
    {
      title: "命令行",
      dataIndex: "cmdline",
      render: (c: string | null) =>
        c ? <EllipsisCell text={c} maxWidth={420} /> : "—",
    },
    {
      title: "工作目录",
      dataIndex: "cwd",
      render: (c: string | null) =>
        c ? <EllipsisCell text={c} maxWidth={260} /> : "—",
    },
  ];

  return (
    <Card
      size="small"
      title={
        <span>
          opencode 进程
          <Typography.Text
            type="secondary"
            style={{ marginLeft: 8, fontSize: 12, fontWeight: 400 }}
          >
            经心跳注册的会话（10s 周期上报，60s 未跳移除）
          </Typography.Text>
        </span>
      }
    >
      <ConsoleSummary system={system} />
      <Table
        rowKey="pid"
        size="small"
        columns={cols}
        dataSource={rows ?? []}
        loading={loading && rows === null}
        pagination={false}
        locale={{
          emptyText: (
            <Typography.Text type="secondary">
              暂无 opencode
              连接——启动宽限（90s）后心跳表仍为空时，控制台将自动退出
            </Typography.Text>
          ),
        }}
      />
    </Card>
  );
};

export default OpencodeSection;
