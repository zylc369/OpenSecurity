/**
 * 音色库分区：TTS 音色列表 + 试听 + 上传（无删除——引用悬空防护）。
 *
 * 数据：GET /api/tts/voices（双源合并: 内置 git 资产在前，用户上传在后）。
 * 试听：POST /api/tts（固定样本句，音色 default_speed）→ blob 播放。
 * 上传：POST /api/tts/voices（multipart; 服务端统一转 24kHz 单声道）。
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Button, Form, Input, Modal, Radio, Space, Table, Tag, Typography, message } from "antd";
import { SoundOutlined, UploadOutlined } from "@ant-design/icons";
import type { VoiceAsset } from "../types";

const SAMPLE_TEXT = "你好，这是音色试听。细那康子们，吃饭了，呜嘞呜嘞呜嘞～";

const VoiceSection: React.FC = () => {
  const [voices, setVoices] = useState<VoiceAsset[] | undefined>();
  const [playing, setPlaying] = useState<string>("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [form] = Form.useForm();
  const fileRef = useRef<File | null>(null);

  const refresh = useCallback(() => {
    fetch("/api/tts/voices")
      .then((r) => r.json())
      .then((d: { voices: VoiceAsset[] }) => setVoices(d.voices))
      .catch(() => setVoices([]));
  }, []);

  useEffect(refresh, [refresh]);

  const preview = async (v: VoiceAsset) => {
    setPlaying(v.id);
    try {
      const resp = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: SAMPLE_TEXT, voice: v.id, speed: v.default_speed }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      new Audio(URL.createObjectURL(blob)).play();
    } catch (e) {
      message.error(`试听失败: ${e instanceof Error ? e.message : e}`);
    } finally {
      setPlaying("");
    }
  };

  const submitUpload = async () => {
    const values = await form.validateFields();
    if (!fileRef.current) {
      message.warning("请选择音频文件");
      return;
    }
    const fd = new FormData();
    fd.append("wav", fileRef.current);
    fd.append("name", values.name);
    fd.append("gender", values.gender);
    fd.append("ref_text", values.ref_text);
    fd.append("description", values.description ?? "");
    const resp = await fetch("/api/tts/voices", { method: "POST", body: fd });
    const d = await resp.json();
    if (!resp.ok) {
      message.error(`上传失败: ${d.detail ?? resp.status}`);
      return;
    }
    message.success(`音色已入库: ${d.id}`);
    setUploadOpen(false);
    form.resetFields();
    fileRef.current = null;
    refresh();
  };

  const columns = [
    { title: "音色", dataIndex: "name", key: "name" },
    {
      title: "性别", dataIndex: "gender", key: "gender", width: 70,
      render: (g: string) => <Tag color={g === "female" ? "magenta" : "blue"}>{g === "female" ? "女" : "男"}</Tag>,
    },
    { title: "描述", dataIndex: "description", key: "description", ellipsis: true },
    {
      title: "来源", dataIndex: "source", key: "source", width: 70,
      render: (s: string) => <Tag>{s === "builtin" ? "内置" : "上传"}</Tag>,
    },
    {
      title: "", key: "ops", width: 160,
      render: (_: unknown, v: VoiceAsset) => (
        <Space>
          <Button size="small" icon={<SoundOutlined />} loading={playing === v.id}
            disabled={!v.available} onClick={() => preview(v)}>试听</Button>
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" size={8} style={{ width: "100%" }}>
      <Space style={{ width: "100%", justifyContent: "space-between" }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          TTS 音色（zero-shot 参考音频——换音色不换模型）
        </Typography.Text>
        <Button size="small" icon={<UploadOutlined />} onClick={() => setUploadOpen(true)}>
          上传音色
        </Button>
      </Space>
      <Table size="small" rowKey="id" dataSource={voices} columns={columns}
        pagination={false} loading={voices === undefined} />
      <Typography.Text type="secondary" style={{ fontSize: 11 }}>
        上传要求: 3-30 秒清晰人声 + 逐字稿（逐字稿与音频内容一致才能保证克隆质量）
      </Typography.Text>

      <Modal title="上传音色" open={uploadOpen} onOk={submitUpload} onCancel={() => setUploadOpen(false)}>
        <Form form={form} layout="vertical" initialValues={{ gender: "female" }}>
          <Form.Item label="音频文件（wav/flac/ogg, 3-30 秒清晰人声）" required>
            <input type="file" accept="audio/*"
              onChange={(e) => { fileRef.current = e.target.files?.[0] ?? null; }} />
          </Form.Item>
          <Form.Item name="name" label="音色名" rules={[{ required: true, max: 40 }]}>
            <Input placeholder="如: 浑厚男声" />
          </Form.Item>
          <Form.Item name="gender" label="性别">
            <Radio.Group options={[{ value: "female", label: "女" }, { value: "male", label: "男" }]} />
          </Form.Item>
          <Form.Item name="ref_text" label="逐字稿（音频里说的原话）" rules={[{ required: true, max: 600 }]}>
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
};

export default VoiceSection;
