/**
 * Python 依赖分区：venv 内 Python 包清单（pip 名/版本/用途/使用方）。
 *
 * 数据：scan.global.python_packages（tools_detector.scan_python_packages）。
 * 与"外部工具"分区严格分离——本分区只有 Python 包。
 */
import React, { useState } from "react";
import { Table, Tag, Button, Typography, Space, App as AntApp, Tooltip } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import type { PyPackageStatus } from "../types";
import { api } from "../api/client";

interface Props {
  packages: PyPackageStatus[] | undefined;
  venvPath: string | undefined;
  onRefresh: () => void;
}

const PythonDepsSection: React.FC<Props> = ({ packages, venvPath, onRefresh }) => {
  const { message } = AntApp.useApp();
  const [installing, setInstalling] = useState<string>("");

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

  if (!packages) return <Typography.Text type="secondary">加载中…</Typography.Text>;

  const okCount = packages.filter((p) => p.available).length;

  const columns = [
    { title: "包名", dataIndex: "pip_name", width: 170,
      render: (v: string, r: PyPackageStatus) => (
        <Space size={4}>
          <span>{v}</span>
          {r.installer === "conda" && <Tooltip title="conda 安装（sagemath），不走 pip"><Tag style={{ marginInlineEnd: 0 }}>conda</Tag></Tooltip>}
        </Space>
      ) },
    { title: "说明", dataIndex: "description", ellipsis: true },
    { title: "版本", dataIndex: "version", width: 100,
      render: (v: string | null) => v ? v.split("+")[0].slice(0, 14) : "—" },
    {
      title: "状态", dataIndex: "available", width: 80,
      render: (v: boolean, r: PyPackageStatus) =>
        v ? <Tag color="success">已装</Tag> : <Tag color={r.required ? "error" : "warning"}>{r.required ? "缺失" : "可选"}</Tag>,
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
      {venvPath && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          虚拟环境：<Typography.Text code style={{ fontSize: 12 }}>{venvPath}</Typography.Text>
        </Typography.Text>
      )}
      <Table<PyPackageStatus>
        size="small" rowKey="pip_name" pagination={false}
        columns={columns} dataSource={packages}
        summary={() => (
          <Table.Summary.Row>
            <Table.Summary.Cell index={0} colSpan={5}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {okCount}/{packages.length} 已安装
                {packages.length - okCount > 0 && ` · 缺 ${packages.length - okCount} 个`}
              </Typography.Text>
            </Table.Summary.Cell>
          </Table.Summary.Row>
        )}
      />
    </Space>
  );
};

export default PythonDepsSection;
