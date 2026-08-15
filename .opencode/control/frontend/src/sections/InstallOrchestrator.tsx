/**
 * 一键安装编排器：顺序执行任务列表（pip → docker → model），Modal 实时进度。
 *
 * 任务由 App 按当前数据构建（整页=全部缺失项；卡片级=单分区缺失项）。
 */
import React, { useEffect, useRef, useState } from "react";
import { Modal, Space, Typography, Tag, Progress } from "antd";
import {
  CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined, ClockCircleOutlined,
} from "@ant-design/icons";

export interface InstallTask {
  key: string;
  kind: "pip" | "docker" | "model";
  label: string;
  /** 执行任务；resolve 成功消息 / reject 错误消息 */
  run: () => Promise<string>;
}

type TaskState = "pending" | "running" | "done" | "failed";

interface Props {
  open: boolean;
  title: string;
  tasks: InstallTask[];
  onClose: () => void;
  /** 全部执行完（无论成败）后回调（App 刷新数据） */
  onFinish: () => void;
}

const KIND_TEXT: Record<InstallTask["kind"], string> = {
  pip: "pip",
  docker: "Docker",
  model: "模型",
};

const InstallOrchestrator: React.FC<Props> = ({ open, title, tasks, onClose, onFinish }) => {
  const [states, setStates] = useState<Record<string, TaskState>>({});
  const [messages, setMessages] = useState<Record<string, string>>({});
  const [running, setRunning] = useState(false);
  const finishedRef = useRef(false);

  useEffect(() => {
    if (open) {
      setStates(Object.fromEntries(tasks.map((t) => [t.key, "pending"])));
      setMessages({});
      finishedRef.current = false;
    }
  }, [open, tasks]);

  useEffect(() => {
    if (!open || running || tasks.length === 0 || finishedRef.current) return;

    let cancelled = false;
    setRunning(true);

    (async () => {
      for (const t of tasks) {
        if (cancelled) break;
        setStates((s) => ({ ...s, [t.key]: "running" }));
        try {
          const msg = await t.run();
          setStates((s) => ({ ...s, [t.key]: "done" }));
          setMessages((m) => ({ ...m, [t.key]: msg }));
        } catch (e) {
          setStates((s) => ({ ...s, [t.key]: "failed" }));
          setMessages((m) => ({ ...m, [t.key]: e instanceof Error ? e.message : String(e) }));
        }
      }
      setRunning(false);
      if (!cancelled) {
        finishedRef.current = true;
        onFinish();
      }
    })();

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, running]);

  const doneCount = tasks.filter((t) => states[t.key] === "done").length;
  const failedCount = tasks.filter((t) => states[t.key] === "failed").length;

  const ICON: Record<TaskState, React.ReactNode> = {
    pending: <ClockCircleOutlined style={{ color: "#999" }} />,
    running: <LoadingOutlined style={{ color: "#1677ff" }} />,
    done: <CheckCircleOutlined style={{ color: "#52c41a" }} />,
    failed: <CloseCircleOutlined style={{ color: "#ff4d4f" }} />,
  };

  return (
    <Modal
      open={open} title={title} onCancel={onClose}
      footer={null} width={640} maskClosable={false} closable={!running}
    >
      <Progress
        percent={tasks.length ? Math.round(((doneCount + failedCount) / tasks.length) * 100) : 100}
        status={failedCount > 0 ? "exception" : running ? "active" : "success"}
        size="small" style={{ marginBottom: 12 }}
      />
      <Space direction="vertical" size={6} style={{ width: "100%", maxHeight: 380, overflowY: "auto" }}>
        {tasks.map((t) => (
          <div key={t.key} style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
            {ICON[states[t.key] ?? "pending"]}
            <div style={{ flex: 1, minWidth: 0 }}>
              <Space size={6}>
                <Typography.Text strong style={{ fontSize: 13 }}>{t.label}</Typography.Text>
                <Tag style={{ marginInlineEnd: 0 }}>{KIND_TEXT[t.kind]}</Tag>
              </Space>
              {messages[t.key] && (
                <Typography.Paragraph
                  type={states[t.key] === "failed" ? "danger" : "secondary"}
                  style={{ fontSize: 12, margin: 0, wordBreak: "break-all" }}
                  ellipsis={{ rows: 3, expandable: true }}
                >
                  {messages[t.key]}
                </Typography.Paragraph>
              )}
            </div>
          </div>
        ))}
      </Space>
      {!running && (
        <Typography.Text type="secondary" style={{ fontSize: 12, display: "block", marginTop: 12 }}>
          完成 {doneCount} · 失败 {failedCount} · 共 {tasks.length}
        </Typography.Text>
      )}
    </Modal>
  );
};

export default InstallOrchestrator;
