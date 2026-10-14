/**
 * TTS 管理分区（听书深度测试台——重建版）。
 *
 * 音色列表 + 行展开三通道试听（a 默认文案 / b 自定义文字 / c 本地 txt+起始索引）
 * + 流式接力播放（段级协议: 分段→预取→顺序播放——与 Legado 同模式）
 * + 默认音色设置（.ai_env 持久化）+ 上传音色。
 * 设计: 需求 2026-10-15-tts-console-rebuild。
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Button, Form, Input, InputNumber, Modal, Progress, Radio, Space,
  Table, Tag, Typography, message,
} from "antd";
import {
  CaretRightOutlined, PauseOutlined, PlayCircleOutlined,
  SoundOutlined, StarFilled, UploadOutlined,
} from "@ant-design/icons";
import type { VoiceAsset } from "../types";
import { useTtsPlayer } from "../hooks/useTtsPlayer";
import { segmentText } from "../utils/segmentText";

/** 通道 a 固定测试文案（128 字——覆盖对话引号/拟声/叹号/省略号/问号全难点） */
const DEFAULT_TEXT =
  "细那康子们，吃饭了，呜嘞呜嘞呜嘞！" +
  "系着围裙的崔桂英左手端碗，右手握勺，边呼喊边敲打着粥缸边缘。" +
  "\u201C都什么年代了，还怕他们听见？\u201D李维汉没好气地骂道。" +
  "孩子们呼啦一下涌进门来，最大的十六，最小的才三岁\u2026";

interface VoiceAssetX extends VoiceAsset {
  is_default?: boolean;
}

const TtsSection: React.FC = () => {
  const [voices, setVoices] = useState<VoiceAssetX[] | undefined>();
  const [expandedId, setExpandedId] = useState<string>("");
  const [customText, setCustomText] = useState("");
  const [txtName, setTxtName] = useState("");
  const [txtContent, setTxtContent] = useState("");
  const [startIdx, setStartIdx] = useState(0);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [form] = Form.useForm();
  const fileRef = useRef<File | null>(null);
  const player = useTtsPlayer();
  // 播放中的音色 id + 通道（用于行内高亮）
  const [activeVoice, setActiveVoice] = useState("");
  

  const refresh = useCallback(() => {
    fetch("/api/tts/voices")
      .then((r) => r.json())
      .then((d: { voices: VoiceAssetX[] }) => setVoices(d.voices))
      .catch(() => setVoices([]));
  }, []);

  useEffect(refresh, [refresh]);

  const launch = (voiceId: string, _channel: string, text: string) => {
    setActiveVoice(voiceId);
    player.start(text);
  };

  const doStop = () => {
    player.stop();
    setActiveVoice("");
  };

  const setDefault = async (voiceId: string) => {
    const resp = await fetch("/api/tts/voices/default", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voice_id: voiceId }),
    });
    if (!resp.ok) {
      const d = await resp.json().catch(() => ({}));
      message.error(`设置失败: ${(d as { detail?: string }).detail ?? resp.status}`);
      return;
    }
    message.success("默认音色已设置");
    refresh();
  };

  const onTxtFile = async (f: File | null) => {
    if (!f) return;
    setTxtName(f.name);
    setTxtContent(await f.text());
  };

  const txtTail = txtContent.slice(Math.max(0, startIdx));
  const txtSegCount = txtTail ? segmentText(txtTail).length : 0;
  const txtPreview = txtTail.slice(0, 20);

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
      message.error(`上传失败: ${(d as { detail?: string }).detail ?? resp.status}`);
      return;
    }
    message.success(`音色已入库: ${(d as { id: string }).id}`);
    setUploadOpen(false);
    form.resetFields();
    fileRef.current = null;
    refresh();
  };

  const renderChannelRow = (
    label: string, channel: string, v: VoiceAssetX,
    extra: React.ReactNode, btnDisabled: boolean,
  ) => (
    <Space style={{ width: "100%", justifyContent: "space-between" }}>
      <Space direction="vertical" size={2} style={{ flex: 1, minWidth: 0 }}>
        <Typography.Text strong style={{ fontSize: 12 }}>{label}</Typography.Text>
        {extra}
      </Space>
      <Button
        size="small" type="primary" ghost icon={<CaretRightOutlined />}
        disabled={btnDisabled}
        onClick={() => launch(v.id, channel,
          channel === "a" ? DEFAULT_TEXT : channel === "b" ? customText : txtTail)}
      >试听</Button>
    </Space>
  );

  const expandedRow = (v: VoiceAssetX) => {
    const isActiveVoice = activeVoice === v.id;
    return (
      <div style={{ display: "grid", gap: 12 }}>
        {renderChannelRow(`① 默认文案（${DEFAULT_TEXT.length} 字·覆盖对话/拟声/叹号/省略号）`, "a", v,
          <Typography.Text type="secondary" style={{ fontSize: 11 }} ellipsis>
            {DEFAULT_TEXT.slice(0, 60)}…
          </Typography.Text>, !v.available)}
        {renderChannelRow("② 自定义文字", "b", v,
          <Input.TextArea rows={2} maxLength={2000} showCount
            placeholder="输入要试听的文字（≤2000 字）"
            onChange={(e) => setCustomText(e.target.value)} />,
          !v.available || customText.trim().length === 0)}
        {renderChannelRow("③ 本地图书模拟（真实听书场景·流式接力）", "c", v,
          <Space direction="vertical" size={2} style={{ width: "100%" }}>
            <Space wrap>
              <input type="file" accept=".txt,text/plain"
                onChange={(e) => void onTxtFile(e.target.files?.[0] ?? null)} />
              {txtName && <Tag closable onClose={() => { setTxtName(""); setTxtContent(""); }}>
                {txtName}
              </Tag>}
              <InputNumber min={0} max={Math.max(0, txtContent.length - 1)} value={startIdx}
                onChange={(n) => setStartIdx(Number(n) || 0)} style={{ width: 110 }}
                addonBefore="起始" addonAfter="字" size="small" />
            </Space>
            {txtContent && (
              <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                从第 {startIdx} 字「{txtPreview}…」起 · 共 {txtTail.length} 字 · 约 {txtSegCount} 段
              </Typography.Text>
            )}
          </Space>, !v.available || txtTail.trim().length === 0)}
        {isActiveVoice && (
          <div style={{ padding: "8px 12px", background: "#fafafa", borderRadius: 6 }}>
            <Space style={{ width: "100%", justifyContent: "space-between" }}>
              <Space size={16}>
                <Typography.Text strong style={{ fontSize: 12 }}>
                  {player.state.status === "starting" && "生成中…首段即将开始"}
                  {player.state.status === "playing" &&
                    `第 ${player.state.segIndex + 1}/${player.state.segTotal} 段`}
                  {player.state.status === "paused" &&
                    `已暂停（第 ${player.state.segIndex + 1}/${player.state.segTotal} 段）`}
                </Typography.Text>
                <Progress percent={Math.round(player.state.segProgress * 100)} size="small"
                  showInfo={false} style={{ width: 140, margin: 0 }} />
                {player.state.error &&
                  <Typography.Text type="danger" style={{ fontSize: 11 }}>
                    {player.state.error}
                  </Typography.Text>}
              </Space>
              <Space>
                {player.state.status === "paused"
                  ? <Button size="small" icon={<PlayCircleOutlined />}
                      onClick={player.resume}>恢复</Button>
                  : <Button size="small" icon={<PauseOutlined />}
                      disabled={player.state.status !== "playing"}
                      onClick={player.pause}>暂停</Button>}
                <Button size="small" danger onClick={doStop}>停止</Button>
              </Space>
            </Space>
          </div>
        )}
      </div>
    );
  };

  const columns = [
    {
      title: "音色", dataIndex: "name", key: "name",
      render: (name: string, v: VoiceAssetX) => (
        <Space>
          <span>{name}</span>
          {v.is_default && <Tag color="gold" icon={<StarFilled />}>默认</Tag>}
        </Space>
      ),
    },
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
      title: "", key: "ops", width: 200,
      render: (_: unknown, v: VoiceAssetX) => (
        <Space>
          {!v.is_default && (
            <Button size="small" icon={<StarFilled />} onClick={() => void setDefault(v.id)}>
              设为默认
            </Button>
          )}
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            点击行展开试听 <SoundOutlined />
          </Typography.Text>
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" size={8} style={{ width: "100%" }}>
      <Space style={{ width: "100%", justifyContent: "space-between" }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          TTS 管理（段级流式试听——本地深度测试通过后服务手机听书）
        </Typography.Text>
        <Button size="small" icon={<UploadOutlined />} onClick={() => setUploadOpen(true)}>
          上传音色
        </Button>
      </Space>
      <Table size="small" rowKey="id" dataSource={voices} columns={columns}
        pagination={false} loading={voices === undefined}
        expandable={{
          expandedRowRender: expandedRow,
          expandedRowKeys: expandedId ? [expandedId] : [],
          onExpand: (expanded, v) => setExpandedId(expanded ? v.id : ""),
        }}
      />
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

export default TtsSection;
