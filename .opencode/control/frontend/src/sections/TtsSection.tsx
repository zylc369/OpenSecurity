/**
 * TTS 管理分区（听书深度测试台）——Ant Design 组件化 UI。
 *
 * 音色列表（Avatar/即时 Tooltip）+ 三通道卡片（①默认文案/②自定义/③txt+起始索引）
 * + 苹果风播放器（大圆钮/时间轴/指标行）+ 默认音色 + 上传。
 * 组件库: antd v5（Tooltip mouseEnterDelay=0 替代列 ellipsis 原生 title 的 ~2s 延迟）。
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Avatar, Button, Card, Empty, Form, Input, InputNumber, Modal, Progress,
  Radio, Select, Space, Table, Tag, Tooltip, Typography, Upload, message,
} from "antd";
import {
  AudioOutlined, BookOutlined, CaretRightOutlined, EditOutlined,
  FileTextOutlined, LoadingOutlined, PauseOutlined, QuestionCircleOutlined,
  SoundOutlined, StarFilled, StopOutlined, UploadOutlined,
} from "@ant-design/icons";
import type { VoiceAsset } from "../types";
import { useTtsPlayer } from "../hooks/useTtsPlayer";
import { parseStairs } from "../utils/segmentText";

/** 通道 a 固定测试文案（覆盖对话引号/拟声/叹号/省略号/问号） */
const DEFAULT_TEXT =
  "细那康子们，吃饭了，呜嘞呜嘞呜嘞！" +
  "系着围裙的崔桂英左手端碗，右手握勺，边呼喊边敲打着粥缸边缘。" +
  "\u201C都什么年代了，还怕他们听见？\u201D李维汉没好气地骂道。" +
  "孩子们呼啦一下涌进门来，最大的十六，最小的才三岁\u2026";

const BLUE = "#0071e3";

/** 朗读指令选项（官方 instruct 列表 + 实测档; value=传给引擎的指令文本, ""=默认） */
const INSTRUCT_GROUPS = [
  {
    label: "⭐ 推荐（自创指令·已实测验证）",
    options: [
      { value: "", label: "正常语速（默认·生产档·⭐）" },
      { value: "请用较快的语速说一句话。", label: "较快" },
    ],
  },
  {
    label: "语速（官方内置）",
    options: [
      { value: "请用尽可能快地语速说一句话。", label: "尽可能快" },
      { value: "请用尽可能慢地语速说一句话。", label: "尽可能慢" },
    ],
  },
  {
    label: "方言（官方内置）",
    options: ["广东话", "四川话", "东北话", "甘肃话", "贵州话",
      "河南话", "湖北话", "湖南话", "江西话", "闽南话",
      "宁夏话", "山西话", "陕西话", "山东话", "上海话",
      "天津话", "云南话"].map((d) => ({
        value: `请用${d}表达。`, label: d,
      })),
  },
  {
    label: "情感 / 音量 / 风格（官方内置）",
    options: [
      { value: "请非常开心地说一句话。", label: "非常开心" },
      { value: "请非常伤心地说一句话。", label: "非常伤心" },
      { value: "请非常生气地说一句话。", label: "非常生气" },
      { value: "Please say a sentence as loudly as possible.", label: "尽可能大声（官方英文）" },
      { value: "Please say a sentence in a very soft voice.", label: "轻声细语（官方英文）" },
      { value: "我想体验一下小猪佩奇风格，可以吗？", label: "小猪佩奇风格" },
      { value: "你可以尝试用机器人的方式解答吗？", label: "机器人方式" },
    ],
  },
  { label: "自定义", options: [{ value: "__custom__", label: "自定义指令…" }] },
];

const SEED_HELP = [
  "随机种子（seed）：控制生成韵律的随机性。",
  "• 同一段文字 + 同一 seed ≈ 相同输出（时长与韵律一致）",
  "• 想换一种韵律试试改值（推荐 0~20）",
  "• 留空使用默认值 4",
].join("\n");

interface VoiceAssetX extends VoiceAsset {
  is_default?: boolean;
}

/** mm:ss（听书尺度小时兜底 h:mm:ss） */
function fmtSec(sec: number): string {
  const s = Math.floor(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(r).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** 指标小块（小标签灰 + 值等宽数字） */
function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <Typography.Text type="secondary" style={{ fontSize: 11, display: "block" }}>
        {label}
      </Typography.Text>
      <Typography.Text style={{ fontSize: 13, fontVariantNumeric: "tabular-nums" }}>
        {value}
      </Typography.Text>
    </div>
  );
}

/** 通道卡片：序号徽章 + 标题 + 图标 + 右上试听主按钮 */
const READER_BLOCK_CHARS = 3000;  // 正文视图块大小（窗口化渲染粒度）

/** 正文阅读视图（窗口化渲染——791 万字不全量 DOM; 选中→右键→从选中处朗读）。 */
const ReaderView: React.FC<{
  text: string;
  readFrom: (offset: number) => void;
}> = ({ text, readFrom }) => {
  const [blocks, setBlocks] = useState(1);   // 已渲染块数（触底续加）
  const [menu, setMenu] = useState<{ x: number; y: number; offset: number } | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const totalBlocks = Math.max(1, Math.ceil(text.length / READER_BLOCK_CHARS));

  useEffect(() => { setBlocks(1); setMenu(null); }, [text]);  // 换书重置视图

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 240 && blocks < totalBlocks) {
      setBlocks((b) => Math.min(totalBlocks, b + 1));
    }
  };

  /** 选区起点 → 全文字符偏移（块 data-offset + 块内文本偏移）。null=无有效选区。 */
  const selectionOffset = (): number | null => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null;
    const range = sel.getRangeAt(0);
    const node = range.startContainer;
    const holder = (node.nodeType === Node.ELEMENT_NODE
      ? (node as Element) : node.parentElement)?.closest("[data-offset]");
    if (!holder) return null;
    const base = Number(holder.getAttribute("data-offset") ?? "0");
    const pre = document.createRange();
    pre.selectNodeContents(holder);
    pre.setEnd(node, range.startOffset);
    return base + pre.toString().length;
  };

  const onContextMenu = (e: React.MouseEvent) => {
    const off = selectionOffset();
    if (off === null) return;  // 无选中 → 原生菜单不干扰
    e.preventDefault();
    setMenu({ x: e.clientX, y: e.clientY, offset: off });
  };

  return (
    <div style={{ marginTop: 8 }}>
      <div ref={scrollRef} onScroll={onScroll} onContextMenu={onContextMenu}
        style={{
          maxHeight: 360, overflowY: "auto", border: "1px solid #e8e8ed",
          borderRadius: 8, padding: "10px 14px", fontSize: 14, lineHeight: 1.9,
          background: "#fffdfa", whiteSpace: "pre-wrap", wordBreak: "break-all",
        }}>
        {Array.from({ length: blocks }, (_, i) => (
          <span key={i} data-offset={i * READER_BLOCK_CHARS}>{
            text.slice(i * READER_BLOCK_CHARS,
                       Math.min(text.length, (i + 1) * READER_BLOCK_CHARS))
          }</span>
        ))}
      </div>
      {menu && (
        <>
          <div style={{ position: "fixed", inset: 0, zIndex: 999 }}
            onClick={() => setMenu(null)}
            onContextMenu={(e) => { e.preventDefault(); setMenu(null); }} />
          <Button size="small" type="primary"
            style={{ position: "fixed", left: menu.x, top: menu.y, zIndex: 1000 }}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => { const off = menu.offset; setMenu(null); readFrom(off); }}>
            从选中处朗读
          </Button>
        </>
      )}
    </div>
  );
};

function ChannelCard({
  no, title, icon, subtitle, action, disabled,
}: {
  no: string; title: string; icon: React.ReactNode;
  subtitle: React.ReactNode; action: React.ReactNode; disabled: boolean;
}) {
  return (
    <Card size="small" style={{ borderRadius: 10, opacity: disabled ? 0.55 : 1 }}
      styles={{ body: { padding: "12px 16px" } }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", rowGap: 8 }}>
        <Avatar shape="square" size={36}
          style={{ background: `${BLUE}14`, color: BLUE, fontSize: 16, flexShrink: 0 }}>
          {icon}
        </Avatar>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Space size={6} align="baseline">
            <Typography.Text strong style={{ color: BLUE, fontSize: 15 }}>{no}</Typography.Text>
            <Typography.Text strong style={{ fontSize: 13.5 }}>{title}</Typography.Text>
          </Space>
          <div style={{ marginTop: 2, minWidth: 0 }}>{subtitle}</div>
        </div>
        {action}
      </div>
    </Card>
  );
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
  const [activeVoice, setActiveVoice] = useState("");
  const bufferedCount = player.state.buffered;
  // 测试台设置
  const [instructSel, setInstructSel] = useState("");
  const [useCustomInstruct, setUseCustomInstruct] = useState(false);
  const [customInstruct, setCustomInstruct] = useState("");
  const [seedVal, setSeedVal] = useState<number | null>(null);
  const [stairsText, setStairsText] = useState<string>("20,40,60,80"); // 阶梯序列(逗号分隔——默认 20,40,60,80)
  const [engineMode, setEngineMode] = useState<"default" | "instruct">("default");

  const refresh = useCallback(() => {
    fetch("/api/tts/voices")
      .then((r) => r.json())
      .then((d: { voices: VoiceAssetX[] }) => setVoices(d.voices))
      .catch(() => setVoices([]));
  }, []);

  useEffect(refresh, [refresh]);

  const launch = (voiceId: string, _channel: string, text: string) => {
    setActiveVoice(voiceId);
    const instruct = useCustomInstruct ? customInstruct.trim() : instructSel;
    player.start(text, {
      voice: voiceId,  // 试听=用该行音色(空串走服务端默认)
      instruct,
      seed: seedVal !== null ? seedVal : -1,  // 0 是合法种子; null(留空)=默认
      stairs: parseStairs(stairsText) ?? undefined,
      mode: engineMode === "instruct" ? "instruct" : "",  // ""=默认 zero_shot 情感饱满
    });
  };

  /** 正文选词朗读: 以选中处为新起点重新起播（整段源文本切片——惰性分段自然衔接）。
   *  音色=所在展开行的音色（与行内试听按钮一致）。 */
  const readFromOffset = (voiceId: string, offset: number) => {
    launch(voiceId, "选词", txtContent.slice(offset));
  };

  const doStop = () => {
    player.stop();
    setActiveVoice("");
  };

  // 自然播完（idle）→ 清理行高亮（播放卡随 activeVoice 收起）
  useEffect(() => {
    if (player.state.status === "idle") setActiveVoice("");
  }, [player.state.status]);

  // 首段生成秒表: starting 期间本地 200ms tick 驱动读数刷新（startTick 不变）
  const [, setGenTick] = useState(0);
  useEffect(() => {
    if (player.state.status !== "starting") return;
    const timer = window.setInterval(() => setGenTick((x) => x + 1), 200);
    return () => window.clearInterval(timer);
  }, [player.state.status]);

  const listenBtn = (v: VoiceAssetX, channel: string, text: string, disabled: boolean) => (
    <Button type="primary" ghost icon={<CaretRightOutlined />}
      disabled={disabled} onClick={() => launch(v.id, channel, text)}>
      试听
    </Button>
  );

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

  // tail 切片 memo（无段数估算——去总账本；惰性分段不预扫全文）
  const txtTail = useMemo(
    () => txtContent.slice(Math.max(0, startIdx)), [txtContent, startIdx]);

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

  const expandedRow = (v: VoiceAssetX) => {
    const isActiveVoice = activeVoice === v.id;
    return (
      <div style={{ display: "grid", gap: 12, padding: "4px 4px 8px" }}>
        <ChannelCard no="①" title="默认文案" icon={<SoundOutlined />}
          subtitle={
            <Tooltip title={DEFAULT_TEXT} mouseEnterDelay={0} placement="topLeft">
              <Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis>
                {DEFAULT_TEXT.slice(0, 60)}…
              </Typography.Text>
            </Tooltip>
          }
          action={listenBtn(v, "a", DEFAULT_TEXT, !v.available)}
          disabled={!v.available} />

        <ChannelCard no="②" title="自定义文字" icon={<EditOutlined />}
          subtitle={
            <Input.TextArea rows={3} maxLength={2000} showCount
              style={{ width: "100%" }} placeholder="输入要试听的文字（≤2000 字）"
              onChange={(e) => setCustomText(e.target.value)} />
          }
          action={listenBtn(v, "b", customText, !v.available || customText.trim().length === 0)}
          disabled={!v.available} />

        <ChannelCard no="③" title="本地图书模拟" icon={<BookOutlined />}
          subtitle={
            <div>
              <Space wrap>
                <Upload accept=".txt,text/plain" showUploadList={false} maxCount={1}
                  beforeUpload={(f) => { void onTxtFile(f); return false; }}>
                  <Button size="small" icon={<FileTextOutlined />}>选择 txt 文件</Button>
                </Upload>
                {txtName && (
                  <Tag closable onClose={() => { setTxtName(""); setTxtContent(""); }}>
                    {txtName}
                  </Tag>
                )}
                <InputNumber min={0} max={Math.max(0, txtContent.length - 1)} value={startIdx}
                  onChange={(n) => setStartIdx(Number(n) || 0)} style={{ width: 170 }}
                  addonBefore="起始字符" addonAfter="字" size="small" />
              </Space>
              {txtContent && (
                <Typography.Text type="secondary" style={{ fontSize: 12, display: "block", marginTop: 6 }}>
                  从第 {startIdx} 字「{txtTail.slice(0, 20)}…」起 · 共 {txtTail.length} 字
                </Typography.Text>
              )}
              {txtContent && (
                <ReaderView text={txtContent} readFrom={(off) => readFromOffset(v.id, off)} />
              )}
            </div>
          }
          action={listenBtn(v, "c", txtTail, !v.available || txtTail.trim().length === 0)}
          disabled={!v.available} />

        {isActiveVoice && (
          <div style={{
            padding: "16px 20px",
            background: "linear-gradient(180deg, #fbfbfd 0%, #f5f5f7 100%)",
            borderRadius: 12, border: "1px solid #e8e8ed",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <Space size={8}>
                {player.state.status === "starting" && (
                  <LoadingOutlined spin style={{ color: BLUE, fontSize: 14 }} />
                )}
                <Typography.Text strong style={{ fontSize: 13 }}>
                  {player.state.status === "starting"
                    ? `正在生成首段… ${(Math.max(0, Date.now() - player.state.startTick) / 1000).toFixed(1)}s`
                    : player.state.status === "paused" ? "已暂停"
                      : player.state.status === "idle" ? "已播完" : "正在朗读"}
                </Typography.Text>
                {player.state.status === "playing" && player.state.waiting && (
                  <Tag color="processing" style={{ marginInlineEnd: 0 }}>
                    等待下一段…
                  </Tag>
                )}
                {(player.state.status === "playing" || player.state.status === "paused"
                  || player.state.status === "idle") && player.state.segIndex > 0 && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    已读 {player.state.segIndex + 1} 段
                  </Typography.Text>
                )}
              </Space>
              {player.state.error && (
                <Typography.Text type="danger" style={{ fontSize: 12 }}>{player.state.error}</Typography.Text>
              )}
            </div>

            <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 28, margin: "14px 0 6px" }}>
              <Tooltip title="停止" mouseEnterDelay={0}>
                <Button shape="circle" size="large" danger ghost
                  icon={<StopOutlined style={{ fontSize: 16 }} />} onClick={doStop} />
              </Tooltip>
              {player.state.status === "paused" ? (
                <Tooltip title="继续播放" mouseEnterDelay={0}>
                  <div onClick={player.resume} style={{
                    width: 52, height: 52, borderRadius: "50%", background: BLUE,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    cursor: "pointer", boxShadow: `0 4px 14px ${BLUE}59`,
                  }}>
                    <CaretRightOutlined style={{ color: "#fff", fontSize: 22, marginLeft: 2 }} />
                  </div>
                </Tooltip>
              ) : (
                <Tooltip title={player.state.status === "playing" ? "暂停" : "生成中…"}
                  mouseEnterDelay={0}>
                  <div
                    onClick={player.state.status === "playing" ? player.pause : undefined}
                    style={{
                      width: 52, height: 52, borderRadius: "50%",
                      background: player.state.status === "playing" ? BLUE : "#c7c7cc",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      cursor: player.state.status === "playing" ? "pointer" : "default",
                      boxShadow: player.state.status === "playing" ? `0 4px 14px ${BLUE}59` : "none",
                    }}>
                    {player.state.status === "starting"
                      ? <LoadingOutlined spin style={{ color: "#fff", fontSize: 20 }} />
                      : <PauseOutlined style={{ color: "#fff", fontSize: 20 }} />}
                  </div>
                </Tooltip>
              )}
              <div style={{ width: 40 }} />
            </div>

            <div>
              {/* 段内进度（真实听书场景: 不预设全书总账本, 无全局进度/剩余时长） */}
              <Progress
                percent={Math.min(100, Math.round(player.state.segProgress * 100))}
                showInfo={false} size={["100%", 6]}
                strokeColor={BLUE} trailColor="#e8e8ed" />
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 2 }}>
                <Typography.Text type="secondary" style={{ fontSize: 12, fontVariantNumeric: "tabular-nums" }}>
                  {fmtSec(player.state.elapsedSec)}
                </Typography.Text>
              </div>
            </div>

            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 8, flexWrap: "wrap", gap: 8 }}>
              <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
              <Metric label="首段生成" value={player.state.firstSegMs
                ? `${(player.state.firstSegMs / 1000).toFixed(1)}s${
                    player.state.firstSegSource === "remote" ? "·远程"
                    : player.state.firstSegSource === "local" ? "·本地" : ""}`
                : "…"} />
              <Metric label="平均生成/段" value={player.state.avgGenMs
                ? `${(player.state.avgGenMs / 1000).toFixed(1)}s` : "…"} />
              <Metric label="已缓冲" value={`${bufferedCount} 段`} />
              </div>
              <Space size={4}>
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>倍速</Typography.Text>
                {[0.9, 1.0, 1.15, 1.3].map((v) => (
                  <Button key={v} size="small" type={player.state.speed === v ? "primary" : "default"}
                    style={{ paddingInline: 8, fontSize: 12 }}
                    onClick={() => player.setSpeed(v)}>
                    {v === 1.0 ? "原速" : `${v}×`}
                  </Button>
                ))}
              </Space>
            </div>
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
          <Avatar size={32} icon={<AudioOutlined />}
            style={{ background: v.gender === "female" ? "#eb2f961f" : "#1677ff1f",
                     color: v.gender === "female" ? "#eb2f96" : "#1677ff" }} />
          <Space direction="vertical" size={0}>
            <Space size={6}>
              <Typography.Text strong>{name}</Typography.Text>
              {v.is_default && <Tag color="gold" icon={<StarFilled />}
                style={{ marginInlineEnd: 0 }}>默认</Tag>}
            </Space>
          </Space>
        </Space>
      ),
    },
    {
      title: "性别", dataIndex: "gender", key: "gender", width: 64,
      render: (g: string) => <Tag color={g === "female" ? "magenta" : "blue"}
        style={{ marginInlineEnd: 0 }}>{g === "female" ? "女" : "男"}</Tag>,
    },
    {
      title: "描述", dataIndex: "description", key: "description",
      render: (desc: string) => (
        <Tooltip title={desc} mouseEnterDelay={0} placement="topLeft">
          <Typography.Text type="secondary" style={{ fontSize: 12, maxWidth: 320 }}
            ellipsis>{desc}</Typography.Text>
        </Tooltip>
      ),
    },
    {
      title: "来源", dataIndex: "source", key: "source", width: 64,
      render: (s: string) => <Tag style={{ marginInlineEnd: 0 }}>
        {s === "builtin" ? "内置" : "上传"}</Tag>,
    },
    {
      title: "默认", key: "default", width: 64, align: "center" as const,
      render: (_: unknown, v: VoiceAssetX) => (
        <Tooltip title="设为朗读默认音色" mouseEnterDelay={0}>
          <Radio checked={!!v.is_default} onChange={() => void setDefault(v.id)} />
        </Tooltip>
      ),
    },
    {
      title: "", key: "ops", width: 170,
      render: () => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          点击行展开试听 <SoundOutlined />
        </Typography.Text>
      ),
    },
  ];

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <Space direction="vertical" size={0}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            🎧 TTS 听书
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            段级流式朗读深度测试台——本地通过即服务手机（Legado 同协议直连）
          </Typography.Text>
        </Space>
        <Button icon={<UploadOutlined />} onClick={() => setUploadOpen(true)}>上传音色</Button>
      </div>

      {/* 测试台设置（试听用; 生产默认"正常语速"不依赖此处） */}
      <Card size="small" style={{ borderRadius: 10 }}
        styles={{ body: { padding: "12px 16px" } }}>
        <Space wrap size={20} align="start">
          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 4 }}>
              引擎模式
            </Typography.Text>
            <Radio.Group value={engineMode} size="small" optionType="button"
              onChange={(e) => setEngineMode(e.target.value as "default" | "instruct")}>
              <Radio.Button value="default">默认（情感饱满）</Radio.Button>
              <Radio.Button value="instruct">指令控制</Radio.Button>
            </Radio.Group>
            <Typography.Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 4, maxWidth: 300 }}>
              {engineMode === "instruct"
                ? "指令调语速/方言/情感（语速统一, 情感偏平）"
                : "参考韵律续写, 情感饱满（语速较自由）"}
            </Typography.Text>
          </div>
          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 4 }}>
              朗读指令（仅"指令控制"模式生效）
            </Typography.Text>
            <Select
              value={useCustomInstruct ? "__custom__" : instructSel}
              disabled={engineMode !== "instruct"}
              style={{ width: 300 }}
              options={INSTRUCT_GROUPS}
              onChange={(v) => {
                if (v === "__custom__") {
                  setUseCustomInstruct(true);
                } else {
                  setUseCustomInstruct(false);
                  setInstructSel(v);
                }
              }}
            />
            {useCustomInstruct && (
              <Input value={customInstruct} maxLength={200}
                placeholder="输入自定义指令（推荐短句 ≤60 字）"
                style={{ width: 300, marginTop: 6 }}
                onChange={(e) => setCustomInstruct(e.target.value)} />
            )}
          </div>
          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 4 }}>
              seed{" "}
              <Tooltip mouseEnterDelay={0}
                title={<span style={{ whiteSpace: "pre-line" }}>{SEED_HELP}</span>}>
                <QuestionCircleOutlined style={{ cursor: "help", color: BLUE }} />
              </Tooltip>
            </Typography.Text>
            <InputNumber value={seedVal} min={0} max={99999}
              placeholder="默认 4" style={{ width: 120 }}
              onChange={(v) => setSeedVal(v)} />
          </div>
          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 4 }}>
              分段设置（字）
            </Typography.Text>
            <Space>
              <Input value={stairsText} style={{ width: 260 }} addonBefore="阶梯(字)"
                placeholder="20,40,60,80"
                onChange={(e) => setStairsText(e.target.value)}
                onBlur={() => { if (parseStairs(stairsText) === null) setStairsText("20,40,60,80"); }} />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                逗号分隔逐档渐进; 末档=常规段封顶
              </Typography.Text>
            </Space>
          </div>
        </Space>
      </Card>

      {voices && voices.length === 0 ? (
        <Empty description="音色库为空" />
      ) : (
        <Table size="middle" rowKey="id" dataSource={voices} columns={columns}
          scroll={{ x: "max-content" }}
          pagination={false} loading={voices === undefined}
          onRow={(v) => ({
            onClick: (e) => {
              // 排除行内交互元素(按钮/单选/Tag/输入)——点它们不触发展开
              if ((e.target as HTMLElement).closest(
                "button, a, .ant-radio, .ant-tag, input, .ant-upload")) return;
              setExpandedId(expandedId === v.id ? "" : v.id);
            },
            style: { cursor: "pointer" },
          })}
          expandable={{
            expandedRowRender: expandedRow,
            expandedRowKeys: expandedId ? [expandedId] : [],
            onExpand: (expanded, v) => setExpandedId(expanded ? v.id : ""),
            rowExpandable: (v) => v.available,
          }} />
      )}
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        上传要求：3-30 秒清晰人声 + 逐字稿（逐字稿与音频内容一致才能保证克隆质量）
      </Typography.Text>

      <Modal title="上传音色" open={uploadOpen} onOk={submitUpload}
        onCancel={() => setUploadOpen(false)} okText="入库">
        <Form form={form} layout="vertical" initialValues={{ gender: "female" }}>
          <Form.Item label="音频文件（wav/flac/ogg, 3-30 秒清晰人声）" required>
            <Upload accept="audio/*" maxCount={1} showUploadList={{ showRemoveIcon: true }}
              beforeUpload={(f) => { fileRef.current = f; return false; }}>
              <Button icon={<AudioOutlined />}>选择音频文件</Button>
            </Upload>
          </Form.Item>
          <Form.Item name="name" label="音色名" rules={[{ required: true, max: 40 }]}>
            <Input placeholder="如: 浑厚男声" />
          </Form.Item>
          <Form.Item name="gender" label="性别">
            <Radio.Group options={[{ value: "female", label: "女" }, { value: "male", label: "男" }]} />
          </Form.Item>
          <Form.Item name="ref_text" label="逐字稿（音频里说的原话）" rules={[{ required: true, max: 600 }]}>
            <Input.TextArea rows={3} />
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
