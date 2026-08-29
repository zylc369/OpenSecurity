/**
 * 外部工具分区：按 Agent 分组的外部工具（IDA/apktool/jadx/GoReSym…）。
 *
 * 与"Python 依赖"严格分离。外部工具不可 pip 安装——只展示状态 + 安装提示
 * （brew/官网链接等），不放安装按钮（防误点击后静默无效）。
 */
import React from "react";
import { Table, Tag, Typography, Space, Collapse } from "antd";
import type { AgentTools, ToolStatus } from "../types";
import EllipsisCell from "../components/EllipsisCell";

const AGENT_TITLE: Record<string, string> = {
  "binary-analysis": "二进制逆向",
  "mobile-analysis": "移动端",
  "web-analysis": "Web 安全",
  "ai-security-analysis": "AI 安全",
  "crypto-analysis": "密码学",
  "security-coordinator": "协调器",
};

interface Props {
  agents: AgentTools | undefined;
}

const ToolsSection: React.FC<Props> = ({ agents }) => {
  if (!agents) return <Typography.Text type="secondary">加载中…</Typography.Text>;

  const columns = [
    { title: "工具", dataIndex: "name", width: 110 },
    { title: "说明", dataIndex: "description", width: 150,
      render: (v: string) => <EllipsisCell text={v} /> },
    {
      title: "状态", dataIndex: "available", width: 76,
      render: (v: boolean, r: ToolStatus) =>
        r.skipped ? <Tag>跳过</Tag> :
        v ? <Tag color="success">可用</Tag>
          : <Tag color={r.required ? "error" : "warning"}>{r.required ? "缺失" : "可选"}</Tag>,
    },
    { title: "版本", dataIndex: "version", width: 90, render: (v: string | null) => v?.slice(0, 12) ?? "—" },
    {
      title: "安装提示",
      render: (_: unknown, r: ToolStatus) =>
        !r.available && !r.skipped && r.install_hint ? (
          <EllipsisCell type="warning" maxWidth={240} text={r.install_hint.replace(/\n/g, " · ")} />
        ) : (
          <Typography.Text type="secondary">—</Typography.Text>
        ),
    },
  ];

  const entries = Object.entries(agents);
  const total = entries.find(([k]) => k === "all")?.[1].length;

  return (
    <Space direction="vertical" size={4} style={{ width: "100%" }}>
      {total !== undefined && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          外部工具全量 {total} 个——下方按 agent 归属分组（同一工具可属于多个 agent，各组数字为该 agent 的可用集合而非全集）
        </Typography.Text>
      )}
    <Collapse
      defaultActiveKey={entries.filter(([, ts]) => ts.some((t) => !t.available && !t.skipped && t.required)).map(([k]) => k)}
      items={entries.map(([agent, tools]) => {
        const ok = tools.filter((t) => t.available || t.skipped).length;
        return {
          key: agent,
          label: (
            <Space>
              {AGENT_TITLE[agent] ?? agent}
              <Tag color={ok === tools.length ? "success" : "warning"}>{ok}/{tools.length}</Tag>
            </Space>
          ),
          children: (
            <Table<ToolStatus>
              size="small" rowKey="name" pagination={false}
              columns={columns} dataSource={tools}
            />
          ),
        };
      })}
    />
    </Space>
  );
};

export default ToolsSection;
