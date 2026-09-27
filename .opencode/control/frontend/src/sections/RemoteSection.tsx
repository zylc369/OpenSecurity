/**
 * 远程资源 TAB（#/remote）——模型远程化的管理面。
 *
 * 三卡片:
 *   1. 远程连接: URL/TOKEN 配置 + 开关状态（忠实显示配置值）+ 切换按钮
 *      （切换远程 = 先校验，失败红色展示原因，成功后按钮翻转）+ 远程健康度
 *   2. 当前模式: 实际生效模式（本地/远程/已降级——降级红色闪烁+原因）
 *      + 本地三模型加载状态 + 卸载倒计时
 *   3. 远程节点管理: CONTROL_API_KEY 设置（可生成随机）/ 常驻开关 /
 *      开机自启（LaunchAgent）——全部经本控制台转发到远程节点
 *
 * 数据源: api.getRemoteStatus() 5s 轮询（后端状态机单一事实源）。
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  Alert, Badge, Button, Card, Descriptions, Input, Popconfirm, Space,
  Switch, Tag, Tooltip, Typography, App as AntApp,
} from "antd";
import {
  ApiOutlined, CheckCircleOutlined, CloudServerOutlined,
  DesktopOutlined, LinkOutlined, ReloadOutlined, SaveOutlined,
  SettingOutlined, WarningOutlined,
} from "@ant-design/icons";
import { api } from "../api/client";
import type { AutostartView, NodeConfigView, RemoteLinkStatusView } from "../types";

const POLL_MS = 5000;

/** 模式徽标（卡片 2 大字标示 + 降级红闪） */
function ModeBadge({ status }: { status: RemoteLinkStatusView | null }) {
  if (!status) return <Typography.Text type="secondary">加载中…</Typography.Text>;
  if (status.state === "remote") {
    return (
      <Space size={8}>
        <CloudServerOutlined style={{ fontSize: 22, color: "#0A6CFF" }} />
        <Typography.Text strong style={{ fontSize: 18 }}>远程模式</Typography.Text>
        <Tag color="blue" style={{ marginInlineEnd: 0 }}>推理走远程节点</Tag>
      </Space>
    );
  }
  if (status.state === "degraded") {
    return (
      <Space size={8} wrap>
        <WarningOutlined className="remote-degraded-blink" style={{ fontSize: 22, color: "#ff4d4f" }} />
        <Typography.Text strong className="remote-degraded-blink" style={{ fontSize: 18, color: "#ff4d4f" }}>
          已降级 · 实际使用本地服务
        </Typography.Text>
      </Space>
    );
  }
  return (
    <Space size={8}>
      <DesktopOutlined style={{ fontSize: 22, color: "#52c41a" }} />
      <Typography.Text strong style={{ fontSize: 18 }}>本地模式</Typography.Text>
    </Space>
  );
}

const RemoteSection: React.FC = () => {
  const { message } = AntApp.useApp();
  const [status, setStatus] = useState<RemoteLinkStatusView | null>(null);
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [saving, setSaving] = useState(false);
  const [switching, setSwitching] = useState(false);
  // 卡片 3: 远程节点管理（经转发）
  const [nodeCfg, setNodeCfg] = useState<NodeConfigView | null>(null);
  const [autostart, setAutostart] = useState<AutostartView | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [nodeBusy, setNodeBusy] = useState(false);

  // 5s 轮询（单一事实源）
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const st = await api.getRemoteStatus();
        if (alive) setStatus(st);
      } catch {
        /* 后端不可达时保持上一帧 */
      }
    };
    void poll();
    const timer = setInterval(poll, POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  // 首帧回填表单一次（此后用户编辑不受轮询覆盖——ref 标记防清空重编辑时被回填打断）
  const backfilled = React.useRef(false);
  useEffect(() => {
    if (status && !backfilled.current) {
      setUrl(status.url);
      setToken(status.token_configured ? "（已配置，输入以更换）" : "");
      backfilled.current = true;
    }
  }, [status]);

  const saveConfig = useCallback(async () => {
    if (!url.trim()) {
      message.warning("远程链接不能为空");
      return;
    }
    setSaving(true);
    try {
      const tokenToSave = token.includes("（已配置") ? "" : token.trim();
      await api.updateRemoteConfig(url.trim(), tokenToSave);
      message.success("远程连接配置已保存");
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }, [url, token, message]);

  const doSwitch = useCallback(async (target: "remote" | "local") => {
    setSwitching(true);
    try {
      const r = await api.switchRemote(target);
      if (r.ok) {
        message.success(target === "remote" ? "已切换远程" : "已切换本地");
        if (r.warnings?.length) {
          message.warning({ content: r.warnings.join("；"), duration: 10 });
        }
      } else {
        message.error({ content: `切换失败: ${r.error || r.detail || "未知原因"}`, duration: 10 });
      }
      const st = await api.getRemoteStatus();
      setStatus(st);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSwitching(false);
    }
  }, [message]);

  const health = status?.remote_health ?? null;
  const enabled = status?.enabled ?? false;
  const degraded = status?.state === "degraded";

  // ── 卡片 3: 远程节点管理加载 ─────────────────────────
  const loadNodeInfo = useCallback(async () => {
    try {
      const [cfg, auto] = await Promise.all([api.getNodeConfig("remote"), api.getAutostart("remote")]);
      setNodeCfg(cfg);
      setAutostart(auto);
    } catch (e) {
      // 远程未配置/不可达——空态提示由卡片 3 渲染
      setNodeCfg(null);
      setAutostart(null);
    }
  }, []);

  useEffect(() => {
    if (status?.url) void loadNodeInfo();
  }, [status?.url, loadNodeInfo]);

  const saveApiKey = useCallback(async (value: string) => {
    if (!value.trim()) return;
    setNodeBusy(true);
    try {
      const r = await api.updateNodeConfig({ CONTROL_API_KEY: value.trim() }, "remote");
      message.success(r.reboot_required ? "已保存; 需重启远程节点控制台生效" : "已保存");
      await loadNodeInfo();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setNodeBusy(false);
    }
  }, [message, loadNodeInfo]);

  const toggleNodeKey = useCallback(async (key: "CONTROL_RESIDENT" | "CONTROL_AUTOSTART", on: boolean) => {
    setNodeBusy(true);
    try {
      await api.updateNodeConfig({ [key]: on ? "1" : "0" } as Partial<Record<"CONTROL_RESIDENT" | "CONTROL_AUTOSTART" | "CONTROL_API_KEY", string>>, "remote");
      message.success("已更新");
      await loadNodeInfo();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
      await loadNodeInfo(); // 恢复真实态
    } finally {
      setNodeBusy(false);
    }
  }, [message, loadNodeInfo]);

  const toggleAutostart = useCallback(async (on: boolean) => {
    setNodeBusy(true);
    try {
      const r = await api.setAutostart(on, "remote");
      message.success(on ? "LaunchAgent 已安装（设备需开启自动登录）" : "LaunchAgent 已卸载");
      if (r.hint) message.info({ content: r.hint, duration: 8 });
      await loadNodeInfo();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
      await loadNodeInfo();
    } finally {
      setNodeBusy(false);
    }
  }, [message, loadNodeInfo]);

  const genApiKey = useCallback(() => {
    const bytes = new Uint8Array(24);
    crypto.getRandomValues(bytes);
    const key = Array.from(bytes).map((b) => b.toString(16).padStart(2, "0")).join("");
    setApiKeyInput(key);
  }, []);

  const modelState = (name: string): { label: string; color: string } => {
    const st = status?.local_models?.[name] ?? "unknown";
    if (status?.state === "remote") return { label: "远程托管", color: "blue" };
    if (st === "ready") return { label: "已加载", color: "success" };
    if (st === "starting") return { label: "加载中", color: "processing" };
    return { label: "未加载", color: "default" };
  };

  const cardProps = { size: "small" as const, style: { height: "100%" } };

  return (
    <Space direction="vertical" size={14} style={{ width: "100%" }}>
      {/* ── 卡片 1: 远程连接 ─────────────────────────────── */}
      <Card
        {...cardProps}
        title={
          <Space size={8}>
            <LinkOutlined />
            <span>远程连接</span>
            <Tag style={{ marginInlineEnd: 0 }} color={enabled ? "green" : "default"}>
              开关: {enabled ? "已开启" : "已关闭"}
            </Tag>
            {degraded && (
              <Tag color="error" style={{ marginInlineEnd: 0 }}>远程失效中</Tag>
            )}
          </Space>
        }
        extra={
          enabled ? (
            <Popconfirm
              title="切换本地？"
              description="模型推理改回本地; 本地资源保持可用"
              okText="切换本地"
              cancelText="取消"
              onConfirm={() => void doSwitch("local")}
              disabled={switching}
            >
              <Button loading={switching} danger>切换本地</Button>
            </Popconfirm>
          ) : (
            <Button
              type="primary"
              icon={<ApiOutlined />}
              loading={switching}
              disabled={!url.trim()}
              onClick={() => void doSwitch("remote")}
            >
              切换远程
            </Button>
          )
        }
      >
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <Space.Compact style={{ width: "100%" }}>
            <Input
              addonBefore="链接"
              placeholder="http://192.168.1.20:9776"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
            <Input.Password
              addonBefore="令牌"
              placeholder="与远程节点 CONTROL_API_KEY 相同"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              style={{ width: 320 }}
            />
            <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={() => void saveConfig()}>
              保存
            </Button>
          </Space.Compact>
          {degraded && (
            <Alert
              type="error" showIcon
              message={`远程不可用: ${status?.last_fail_reason ?? "未知原因"}`}
              description="请求已自动降级到本地（无需操作）; 远程恢复后将自动切回并释放本地资源"
            />
          )}
          <Descriptions size="small" column={3} style={{ background: "rgba(0,0,0,0.02)", padding: "8px 12px", borderRadius: 8 }}>
            <Descriptions.Item label="心跳延迟">
              {health ? `${health.latency_ms} ms` : "—"}
            </Descriptions.Item>
            <Descriptions.Item label="连续成功">
              {status ? `${status.recover_streak} 次` : "—"}
            </Descriptions.Item>
            <Descriptions.Item label="最近在线">
              {status?.last_ok_at
                ? new Date(status.last_ok_at * 1000).toLocaleTimeString()
                : "—"}
            </Descriptions.Item>
          </Descriptions>
          {health && (
            <Space size={6} wrap>
              {health.models.map((m) => (
                <Tooltip key={m.repo_id} title={`snapshot: ${m.snapshot || "未知"}`}>
                  <Tag icon={m.loaded ? <CheckCircleOutlined /> : undefined}
                       color={m.loaded ? "success" : "default"}
                       style={{ marginInlineEnd: 0 }}>
                    {m.repo_id.split("/").pop()} {m.loaded ? "" : "(未加载)"}
                  </Tag>
                </Tooltip>
              ))}
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                远程版本 {health.version}
              </Typography.Text>
            </Space>
          )}
        </Space>
      </Card>

      {/* ── 卡片 2: 当前模式 ─────────────────────────────── */}
      <Card
        {...cardProps}
        title={
          <Space size={8}>
            <DesktopOutlined />
            <span>当前模式</span>
            {status?.unload_countdown_sec != null && (
              <Tag color="purple" style={{ marginInlineEnd: 0 }}>
                {Math.ceil(status.unload_countdown_sec)}s 后释放本地内存
              </Tag>
            )}
          </Space>
        }
        extra={
          <Tooltip title="立即刷新">
            <Button size="small" type="text" icon={<ReloadOutlined />}
                    onClick={() => void api.getRemoteStatus().then(setStatus).catch(() => {})} />
          </Tooltip>
        }
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            background: degraded ? "rgba(255,77,79,0.06)" : "rgba(0,0,0,0.02)",
            borderRadius: 10, padding: "14px 16px",
          }}>
            <ModeBadge status={status} />
            <Space size={14}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                开关配置: {enabled ? "开启" : "关闭"}
              </Typography.Text>
              {degraded && (
                <Badge status="error" text={
                  <Typography.Text type="danger" style={{ fontSize: 12 }}>
                    {status?.last_fail_reason ?? "远程不可用"}
                  </Typography.Text>
                } />
              )}
            </Space>
          </div>
          <Space size={8} wrap>
            {[
              { key: "embedder", name: "BGE-M3" },
              { key: "reranker", name: "Reranker v2 m3" },
              { key: "ocr", name: "GLM-OCR" },
            ].map(({ key, name }) => {
              const st = modelState(key);
              return (
                <Tag key={key} color={st.color} style={{ marginInlineEnd: 0 }}>
                  {name}: {st.label}
                </Tag>
              );
            })}
          </Space>
        </Space>
      </Card>

      {/* ── 卡片 3: 远程节点管理（经转发）─────────────────── */}
      <Card
        {...cardProps}
        title={
          <Space size={8}>
            <SettingOutlined />
            <span>远程节点管理</span>
            {nodeCfg && (
              <Tag style={{ marginInlineEnd: 0 }}>
                {nodeCfg.CONTROL_RESIDENT === "1" ? "常驻" : "非常驻"}
              </Tag>
            )}
          </Space>
        }
      >
        {!status?.url ? (
          <Alert type="info" showIcon message="先在上方配置远程连接（链接 + 令牌）才能管理远程节点" />
        ) : !nodeCfg ? (
          <Alert type="warning" showIcon
                 message="远程节点不可达——检查节点控制台是否运行、CONTROL_API_KEY 是否已在本机（节点）页面配置" />
        ) : (
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Descriptions size="small" column={2} style={{ background: "rgba(0,0,0,0.02)", padding: "8px 12px", borderRadius: 8 }}>
              <Descriptions.Item label="鉴权令牌">
                {nodeCfg.CONTROL_API_KEY ? `${nodeCfg.CONTROL_API_KEY}…（已配置）` : "未配置"}
              </Descriptions.Item>
              <Descriptions.Item label="LaunchAgent">
                {autostart?.installed ? "已安装" : "未安装"}
                {autostart && !autostart.supported && "（非 macOS 不支持）"}
              </Descriptions.Item>
            </Descriptions>
            <Space.Compact style={{ width: "100%" }}>
              <Input.Password
                addonBefore="CONTROL_API_KEY"
                placeholder="远程节点的鉴权令牌"
                value={apiKeyInput}
                onChange={(e) => setApiKeyInput(e.target.value)}
              />
              <Button onClick={genApiKey}>生成随机 KEY</Button>
              <Button type="primary" loading={nodeBusy} disabled={!apiKeyInput.trim()}
                      onClick={() => void saveApiKey(apiKeyInput)}>
                保存到节点
              </Button>
            </Space.Compact>
            <Space size={24} wrap>
              <Space size={8}>
                <Switch checked={nodeCfg.CONTROL_RESIDENT === "1"} loading={nodeBusy}
                        onChange={(on) => void toggleNodeKey("CONTROL_RESIDENT", on)} />
                <Typography.Text>常驻模式</Typography.Text>
                <Tooltip title="禁用心跳自杀机制——无 opencode 连接时节点控制台不退出（节点推荐开启）">
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>?</Typography.Text>
                </Tooltip>
              </Space>
              <Space size={8}>
                <Switch checked={autostart?.installed ?? false} loading={nodeBusy}
                        onChange={(on) => void toggleAutostart(on)} />
                <Typography.Text>开机自启</Typography.Text>
                <Tooltip title="安装 macOS LaunchAgent; 设备需开启「自动登录」（登录后才会拉起）">
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>?</Typography.Text>
                </Tooltip>
              </Space>
            </Space>
            <Alert type="info" showIcon style={{ marginTop: 0 }}
                   message="部署提示: ① CONTROL_API_KEY 保存后需重启远程节点控制台生效（绑定 0.0.0.0 + 鉴权）; ② Mac mini 需开启系统「自动登录」，LaunchAgent 在登录后运行; ③ 首次绑 0.0.0.0 macOS 可能弹防火墙允许提示" />
          </Space>
        )}
      </Card>
    </Space>
  );
};

export default RemoteSection;
