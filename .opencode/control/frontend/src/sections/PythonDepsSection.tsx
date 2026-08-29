/**
 * Python 依赖分区：venv 内 Python 包清单。
 *
 * 交互（用户反馈固化）：
 *   • 分页：默认 5 条/页，可切 10/20/50/100
 *   • 排序：未安装的排前面（待办的优先看到）
 *   • 搜索：按包名模糊过滤（不区分大小写，匹配 pip 名或 import 名）
 *   • 说明列悬浮立即显示全文（EllipsisCell，0 延迟）
 */
import React, { useMemo, useState } from "react";
import {
  Table, Tag, Button, Typography, Space, App as AntApp, Tooltip, Input,
} from "antd";
import { DownloadOutlined, SearchOutlined } from "@ant-design/icons";
import type { PyPackageStatus } from "../types";
import { api } from "../api/client";
import EllipsisCell from "../components/EllipsisCell";

interface Props {
  packages: PyPackageStatus[] | undefined;
  venvPath: string | undefined;
  onRefresh: () => void;
}

const PythonDepsSection: React.FC<Props> = ({ packages, venvPath, onRefresh }) => {
  const { message } = AntApp.useApp();
  const [installing, setInstalling] = useState<string>("");
  const [keyword, setKeyword] = useState("");

  const doInstall = async (pipName: string) => {
    setInstalling(pipName);
    try {
      const r = await api.install(pipName);
      if (r.success) message.success(`${pipName} 安装成功`);
      else message.error({ content: `${pipName} 安装失败：${r.stderr || r.error}`, duration: 8 });
      onRefresh();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setInstalling("");
    }
  };

  // 过滤（模糊搜索 pip 名/import 名）+ 排序（缺失置前，之后按 pip 名）
  const dataSource = useMemo(() => {
    if (!packages) return [];
    const kw = keyword.trim().toLowerCase();
    const filtered = kw
      ? packages.filter(
          (p) => p.pip_name.toLowerCase().includes(kw) || p.name.toLowerCase().includes(kw))
      : packages;
    return [...filtered].sort((a, b) => {
      if (a.available !== b.available) return a.available ? 1 : -1; // 缺失在前
      return a.pip_name.localeCompare(b.pip_name);
    });
  }, [packages, keyword]);

  if (!packages) return <Typography.Text type="secondary">加载中…</Typography.Text>;

  const okCount = packages.filter((p) => p.available).length;

  const columns = [
    { title: "包名", dataIndex: "pip_name", width: 170,
      render: (v: string, r: PyPackageStatus) => (
        <Space size={4}>
          <span>{v}</span>
          {r.installer === "conda" && (
            <Tooltip title="conda 安装（sagemath），不走 pip">
              <Tag style={{ marginInlineEnd: 0 }}>conda</Tag>
            </Tooltip>
          )}
        </Space>
      ) },
    {
      title: "说明", dataIndex: "description",
      render: (v: string) => <EllipsisCell text={v} />,
    },
    { title: "版本", dataIndex: "version", width: 100,
      render: (v: string | null) => (v ? v.split("+")[0].slice(0, 14) : "—") },
    {
      title: "状态", dataIndex: "available", width: 80,
      render: (v: boolean, r: PyPackageStatus) =>
        v ? <Tag color="success">已装</Tag>
          : <Tag color={r.required ? "error" : "warning"}>{r.required ? "缺失" : "可选"}</Tag>,
    },
    {
      title: "操作", width: 80,
      render: (_: unknown, r: PyPackageStatus) =>
        !r.available && r.installer === "pip" ? (
          <Button size="small" icon={<DownloadOutlined />}
            loading={installing === r.pip_name}
            onClick={() => doInstall(r.pip_name)}>安装</Button>
        ) : (
          <Typography.Text type="secondary">—</Typography.Text>
        ),
    },
  ];

  return (
    <Space direction="vertical" size={8} style={{ width: "100%" }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        Python 依赖共 {packages.length} 个（{okCount} 可用）——全部 agent 共享清单，按需安装
      </Typography.Text>
      {venvPath && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          虚拟环境：<Typography.Text code style={{ fontSize: 12 }}>{venvPath}</Typography.Text>
        </Typography.Text>
      )}
      <Space size={8} style={{ justifyContent: "space-between", width: "100%" }}>
        <Input
          allowClear size="small" placeholder="搜索包名…"
          prefix={<SearchOutlined />}
          style={{ width: 220 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {okCount}/{packages.length} 已装{packages.length - okCount > 0 && ` · 缺 ${packages.length - okCount} 个`}
        </Typography.Text>
      </Space>
      <Table<PyPackageStatus>
        size="small" rowKey="pip_name"
        columns={columns} dataSource={dataSource}
        pagination={{
          pageSize: 5,
          pageSizeOptions: [10, 20, 50, 100],
          showSizeChanger: true,
          showTotal: (t, range) => `${range[0]}-${range[1]} / ${t}`,
          size: "small",
        }}
      />
    </Space>
  );
};

export default PythonDepsSection;
