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
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Popover,
  Descriptions,
  Input,
  Popconfirm,
  Row,
  Space,
  Switch,
  Tag,
  Tooltip,
  Typography,
  App as AntApp,
} from "antd";
import {
  ApiOutlined,
  CheckCircleOutlined,
  CloudServerOutlined,
  DesktopOutlined,
  LinkOutlined,
  ReloadOutlined,
  SaveOutlined,
  SettingOutlined,
  SyncOutlined,
  WarningOutlined,
  CloudDownloadOutlined,
} from "@ant-design/icons";
import { api } from "../api/client";
import { useAllConfig, useConfigMeta } from "../hooks";
import ConfigFieldRow from "../components/ConfigFieldRow";
import {
  findGroup,
  groupByCategory,
  writableUpdates,
} from "../utils/configGrouping";
import type {
  AutostartView,
  ConfigMap,
  NodeConfigView,
  RemoteLinkStatusView,
} from "../types";

const POLL_MS = 5000;

/** 模式徽标（卡片 2 大字标示 + 降级红闪） */
function ModeBadge({ status }: { status: RemoteLinkStatusView | null }) {
  if (!status)
    return <Typography.Text type="secondary">加载中…</Typography.Text>;
  // 建联中间态可视化: 管道已配置但未连上（OFF）——心跳正在建隧道/探测
  if (status.state === "off" && status.transport) {
    const label = status.transport === "p2p" ? "P2P" : "远程链接";
    return (
      <Space size={8}>
        <SyncOutlined spin style={{ fontSize: 22, color: "#faad14" }} />
        <Typography.Text strong style={{ fontSize: 18, color: "#faad14" }}>
          {label}连接建立中…
        </Typography.Text>
        <Tag color="warning" style={{ marginInlineEnd: 0 }}>
          期间推理走本地
        </Tag>
      </Space>
    );
  }
  if (status.state === "remote") {
    const tp = status.transport;
    return (
      <Space size={8}>
        <CloudServerOutlined style={{ fontSize: 22, color: "#0A6CFF" }} />
        <Typography.Text strong style={{ fontSize: 18 }}>
          远程模式
        </Typography.Text>
        {tp === "p2p" && (
          <Tag color="geekblue" style={{ marginInlineEnd: 0 }}>
            P2P 隧道
          </Tag>
        )}
        {tp === "http" && (
          <Tag color="blue" style={{ marginInlineEnd: 0 }}>
            HTTP 直连
          </Tag>
        )}
        {!tp && (
          <Tag color="warning" style={{ marginInlineEnd: 0 }}>
            管道未配置
          </Tag>
        )}
        <Typography.Text type="secondary">推理走远程节点</Typography.Text>
      </Space>
    );
  }
  if (status.state === "degraded") {
    return (
      <Space size={8} wrap>
        <WarningOutlined
          className="remote-degraded-blink"
          style={{ fontSize: 22, color: "#ff4d4f" }}
        />
        <Typography.Text
          strong
          className="remote-degraded-blink"
          style={{ fontSize: 18, color: "#ff4d4f" }}
        >
          已降级 · 实际使用本地服务
        </Typography.Text>
      </Space>
    );
  }
  return (
    <Space size={8}>
      <DesktopOutlined style={{ fontSize: 22, color: "#52c41a" }} />
      <Typography.Text strong style={{ fontSize: 18 }}>
        本地模式
      </Typography.Text>
    </Space>
  );
}

const RemoteSection: React.FC = () => {
  const { message } = AntApp.useApp();
  const [status, setStatus] = useState<RemoteLinkStatusView | null>(null);
  // 连接配置: meta 驱动（surface=remote——管道/RELAY/URL/TOKEN 等可写;
  // ENABLED 为 hidden 状态机键不经此面，状态显示归模式徽标）
  const rmeta = useConfigMeta("remote");
  const {
    data: rconfigs,
    save: saveRemote,
    refresh: refreshRemoteConfig,
  } = useAllConfig("remote");
  const [rvalues, setRvalues] = useState<ConfigMap>({});
  const [saving, setSaving] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [switchingTo, setSwitchingTo] = useState<"" | "p2p" | "http">("");
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

  useEffect(() => {
    if (rconfigs) setRvalues(rconfigs);
  }, [rconfigs]);

  const rgroups = useMemo(
    () =>
      rmeta.data
        ? groupByCategory(rmeta.data.entries, rmeta.data.categories)
        : [],
    [rmeta.data],
  );
  const linkGroup = findGroup(rgroups, "remote");
  const tuningGroup = findGroup(rgroups, "remote_tuning");

  const rdirty = useMemo(() => {
    if (!rconfigs || !rmeta.data) return false;
    return Object.entries(writableUpdates(rvalues, rmeta.data.entries)).some(
      ([k, v]) => (v ?? "") !== (rconfigs[k] ?? ""),
    );
  }, [rvalues, rconfigs, rmeta.data]);

  const saveRemoteConfig = useCallback(async () => {
    // 可用性校验在「切换远程」时做（后端先校验后置位）; 保存只写值——
    // 远程配置全部可选，允许只配 P2P、只配 HTTP 直连或暂存草稿。
    setSaving(true);
    try {
      const updates = Object.fromEntries(
        Object.entries(writableUpdates(rvalues, rmeta.data?.entries ?? {})).map(
          ([k, v]) => [k, (v ?? "").trim()],
        ),
      );
      await saveRemote(updates);
      message.success("远程连接配置已保存");
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }, [rvalues, rmeta.data, saveRemote, message]);

  // ── 更新并重启（git pull + restart; 轮询远程 boot_token 变化判定完成——
  //     exec 重启 PID 不变、boot_token 必变，是进程身份的唯一可靠信号）──
  const [updating, setUpdating] = React.useState(false);
  const doUpdateRestart = async () => {
    setUpdating(true);
    const hide = message.loading("远程节点: 拉取新代码并重启中…", 0);
    try {
      const r = await api.updateRestartRemote();
      const oldToken = r.old_boot_token;
      const deadline = Date.now() + 30_000;
      let newToken: string | null = null;
      while (Date.now() < deadline) {
        await new Promise((res) => setTimeout(res, 2000));
        newToken = await api.remoteBootToken().catch(() => null);
        if (newToken && newToken !== oldToken) break;
      }
      hide();
      if (newToken && newToken !== oldToken) {
        message.success(
          `远程节点已更新并重启完成${r.pull_output ? "（代码已更新）" : ""}`,
        );
      } else {
        message.warning("重启已触发，但 30 秒内远程未恢复健康——请检查远程日志");
      }
    } catch (e) {
      hide();
      message.error(`更新失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setUpdating(false);
    }
  };

  const doSwitch = useCallback(
    async (transport: "" | "p2p" | "http") => {
      setSwitching(true);
      setSwitchingTo(transport);
      try {
        const r = await api.switchRemote(transport);
        if (r.ok) {
          const label = transport === "p2p" ? "P2P 连接"
            : transport === "http" ? "远程链接" : "";
          message.success(label ? `已切换: ${label}` : "已关闭远程（回到本地推理）");
          if (r.warnings?.length) {
            message.warning({ content: r.warnings.join("；"), duration: 10 });
          }
        } else {
          message.error({
            content: `切换失败: ${r.error || "未知原因"}`,
            duration: 10,
          });
        }
        // 一切以后端最新数据为准刷新（通用逻辑——不做本地状态推导）
        const st = await api.getRemoteStatus();
        setStatus(st);
        refreshRemoteConfig();
      } catch (e) {
        message.error(e instanceof Error ? e.message : String(e));
      } finally {
        setSwitching(false);
        setSwitchingTo("");
      }
    },
    [message, refreshRemoteConfig],
  );

  const health = status?.remote_health ?? null;
  const localCodeFp = status?.local_code_fingerprint ?? "";
  const enabled = status?.enabled ?? false;
  const degraded = status?.state === "degraded";
  // 守卫后捕获（JSX 回调内属性窄化会丢失）
  const rmetaEntries = rmeta.data?.entries ?? null;

  // ── 卡片 3: 远程节点管理加载 ─────────────────────────
  const loadNodeInfo = useCallback(async () => {
    try {
      const [cfg, auto] = await Promise.all([
        api.getNodeConfig("remote"),
        api.getAutostart("remote"),
      ]);
      setNodeCfg(cfg);
      setAutostart(auto);
    } catch (e) {
      // 远程未配置/不可达——空态提示由卡片 3 渲染
      setNodeCfg(null);
      setAutostart(null);
    }
  }, []);

  // 节点管理加载门控: 两管道任一可用（http=url; p2p=管道已配——转发走隧道）
  const p2pReady = status?.transport === "p2p";
  useEffect(() => {
    if (status?.url || p2pReady) void loadNodeInfo();
  }, [status?.url, p2pReady, loadNodeInfo]);

  const saveApiKey = useCallback(
    async (value: string) => {
      if (!value.trim()) return;
      setNodeBusy(true);
      try {
        const r = await api.updateNodeConfig(
          { CONTROL_API_KEY: value.trim() },
          "remote",
        );
        message.success(
          r.reboot_required ? "已保存; 需重启远程节点控制台生效" : "已保存",
        );
        await loadNodeInfo();
      } catch (e) {
        message.error(e instanceof Error ? e.message : String(e));
      } finally {
        setNodeBusy(false);
      }
    },
    [message, loadNodeInfo],
  );

  const toggleNodeKey = useCallback(
    async (key: "CONTROL_RESIDENT" | "CONTROL_AUTOSTART", on: boolean) => {
      setNodeBusy(true);
      try {
        await api.updateNodeConfig(
          { [key]: on ? "1" : "0" } as Partial<
            Record<
              "CONTROL_RESIDENT" | "CONTROL_AUTOSTART" | "CONTROL_API_KEY",
              string
            >
          >,
          "remote",
        );
        message.success("已更新");
        await loadNodeInfo();
      } catch (e) {
        message.error(e instanceof Error ? e.message : String(e));
        await loadNodeInfo(); // 恢复真实态
      } finally {
        setNodeBusy(false);
      }
    },
    [message, loadNodeInfo],
  );

  const toggleAutostart = useCallback(
    async (on: boolean) => {
      setNodeBusy(true);
      try {
        const r = await api.setAutostart(on, "remote");
        message.success(
          on
            ? "LaunchAgent 已安装（设备需开启自动登录）"
            : "LaunchAgent 已卸载",
        );
        if (r.hint) message.info({ content: r.hint, duration: 8 });
        await loadNodeInfo();
      } catch (e) {
        message.error(e instanceof Error ? e.message : String(e));
        await loadNodeInfo();
      } finally {
        setNodeBusy(false);
      }
    },
    [message, loadNodeInfo],
  );

  const genApiKey = useCallback(() => {
    const bytes = new Uint8Array(24);
    crypto.getRandomValues(bytes);
    const key = Array.from(bytes)
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    setApiKeyInput(key);
  }, []);

  /** 单模型状态展示（state → 徽标; 注册表驱动——与环境总览同源） */
  const stateBadge = (st: string): { label: string; color: string } => {
    if (status?.state === "remote") return { label: "远程托管", color: "blue" };
    if (st === "ready") return { label: "已加载", color: "success" };
    if (st === "starting") return { label: "加载中", color: "processing" };
    if (st === "error") return { label: "状态异常", color: "error" };
    if (st === "unknown") return { label: "状态未知", color: "warning" };
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
            <Tag
              style={{ marginInlineEnd: 0 }}
              color={enabled ? "green" : "default"}
            >
              开关:{" "}
              {status?.transport === "p2p"
                ? "P2P 连接"
                : status?.transport === "http"
                  ? "远程链接"
                  : enabled
                    ? "已开启"
                    : "已关闭"}
            </Tag>
            {degraded && (
              <Tag color="error" style={{ marginInlineEnd: 0 }}>
                远程失效中
              </Tag>
            )}
          </Space>
        }
        extra={
          <Space>
            <Popconfirm
              title="更新并重启远程节点？"
              description="远程 git pull 最新代码后自动重启; 完成前按钮保持转圈（最长 30s）"
              okText="更新并重启"
              cancelText="取消"
              onConfirm={() => void doUpdateRestart()}
              disabled={updating || !enabled}
            >
              <Button
                loading={updating}
                icon={<CloudDownloadOutlined />}
                disabled={!enabled}
              >
                更新并重启
              </Button>
            </Popconfirm>
            <Popover
              trigger="hover"
              placement="bottomRight"
              content={
                <Space direction="vertical" size={8} style={{ width: 220 }}>
                  <Tooltip
                    title={status?.transport === "p2p"
                      ? "当前模式——再次点击清空模式配置（回到本地推理）"
                      : "只用 P2P 隧道（Noise 加密+打洞直连，无需公网暴露）; 只校验中继三项+节点 ID，不要求远程链接"}
                  >
                    <Button
                      block
                      icon={<ApiOutlined />}
                      loading={switching && switchingTo === "p2p"}
                      onClick={() => void doSwitch(status?.transport === "p2p" ? "" : "p2p")}
                    >
                      切换 P2P 连接
                      {status?.transport === "p2p" && (
                        <CheckCircleOutlined style={{ color: "#52c41a", marginInlineStart: 8 }} />
                      )}
                    </Button>
                  </Tooltip>
                  <Tooltip
                    title={status?.transport === "http"
                      ? "当前模式——再次点击清空模式配置（回到本地推理）"
                      : "只用 HTTP 直连; 只校验远程链接+令牌"}
                  >
                    <Button
                      block
                      icon={<LinkOutlined />}
                      loading={switching && switchingTo === "http"}
                      onClick={() => void doSwitch(status?.transport === "http" ? "" : "http")}
                    >
                      切换远程链接
                      {status?.transport === "http" && (
                        <CheckCircleOutlined style={{ color: "#52c41a", marginInlineStart: 8 }} />
                      )}
                    </Button>
                  </Tooltip>
                </Space>
              }
            >
              <span>
                <Button type="primary" icon={<ApiOutlined />} disabled={switching}>
                  {enabled
                    ? `切换远程（${status?.transport === "p2p" ? "P2P" : "链接"}）▾`
                    : "切换远程 ▾"}
                </Button>
              </span>
            </Popover>
          </Space>
        }
      >
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          {linkGroup && rmetaEntries ? (
            <Row gutter={[16, 0]} align="bottom">
              {linkGroup.keys.map((key) => {
                const m = rmetaEntries[key];
                return (
                  <Col xs={24} md={12} key={key}>
                    <ConfigFieldRow
                      meta={m}
                      value={rvalues[key] ?? ""}
                      onChange={
                        m.readonly
                          ? undefined
                          : (v) => setRvalues((s) => ({ ...s, [key]: v }))
                      }
                    />
                  </Col>
                );
              })}
              <Col xs={24}>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  loading={saving}
                  disabled={!rdirty}
                  onClick={() => void saveRemoteConfig()}
                >
                  保存{rdirty ? "（有未保存修改）" : ""}
                </Button>
              </Col>
            </Row>
          ) : (
            <Typography.Text type="secondary">连接配置加载中…</Typography.Text>
          )}
            {status?.state === "off" && status.transport && (
              <Alert
                type="warning"
                showIcon
                icon={<SyncOutlined spin />}
                message={`${
                  status.transport === "p2p" ? "P2P 隧道" : "远程链接"
                }连接建立中…（心跳每轮自动重试，期间推理走本地）`}
                description={`已尝试 ${status.probe_attempts} 次; ${
                  status.next_probe_in_sec > 0
                    ? `${Math.ceil(status.next_probe_in_sec)} 秒后第 ${status.probe_attempts + 1} 次尝试（每 ${Math.round(status.probe_interval_sec)} 秒自动重试）`
                    : "正在尝试中…"
                }${
                  status.last_fail_reason
                    ? `; 最近失败: ${status.last_fail_reason}`
                    : "; 首次探测含隧道建立（打洞/中继），约 5-10 秒"
                }`}
              />
            )}
            {degraded && (
              <Alert
                type="error"
                showIcon
                message={`远程不可用: ${status?.last_fail_reason ?? "未知原因"}`}
                description={`请求已自动降级到本地（无需操作）; 远程恢复后将自动切回并释放本地资源。后台持续建联: 已尝试 ${status?.probe_attempts ?? 0} 次${
                  status && status.next_probe_in_sec > 0
                    ? `，${Math.ceil(status.next_probe_in_sec)} 秒后第 ${(status.probe_attempts ?? 0) + 1} 次（每 ${Math.round(status?.probe_interval_sec ?? 5)} 秒）`
                    : "，正在尝试中…"
                }`}
              />
            )}
          <Descriptions
            size="small"
            column={3}
            style={{
              background: "rgba(0,0,0,0.02)",
              padding: "8px 12px",
              borderRadius: 8,
            }}
          >
            <Descriptions.Item label="心跳延迟">
              {health ? (
                `${health.latency_ms} ms`
              ) : status?.state === "off" && status.transport ? (
                <Tag color="warning" style={{ marginInlineEnd: 0 }}>
                  建联中（首次探测含隧道建立，约 5-10s）
                </Tag>
              ) : (
                "—"
              )}
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
                <Tooltip
                  key={m.repo_id}
                  title={`${m.repo_id}\nsnapshot: ${m.snapshot || "未知"}`}
                >
                  <Tag
                    icon={m.loaded ? <CheckCircleOutlined /> : undefined}
                    color={m.loaded ? "success" : "default"}
                    style={{ marginInlineEnd: 0 }}
                  >
                    {m.display || m.repo_id}
                    {m.loaded ? "" : "（未加载）"}
                  </Tag>
                </Tooltip>
              ))}
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                远程 {health.version}
                {health.code_fingerprint
                  ? ` · 代码 ${health.code_fingerprint}${
                      localCodeFp && localCodeFp !== health.code_fingerprint
                        ? "（与本地不一致——远程节点可能需要更新）"
                        : "（与本地一致）"
                    }`
                  : ""}
              </Typography.Text>
            </Space>
          )}
        </Space>
      </Card>

      {/* ── 卡片 1.5: 远程调参（meta 驱动只读展示）────────── */}
      {tuningGroup && rmetaEntries && (
        <Card
          {...cardProps}
          title={
            <Space size={8}>
              <SyncOutlined />
              <span>{tuningGroup.desc}</span>
              <Tag style={{ marginInlineEnd: 0 }}>只读</Tag>
            </Space>
          }
        >
          <Row gutter={[16, 0]}>
            {tuningGroup.keys.map((key) => (
              <Col xs={24} md={12} xl={8} key={key}>
                <ConfigFieldRow
                  meta={rmetaEntries[key]}
                  value={rvalues[key] ?? ""}
                />
              </Col>
            ))}
          </Row>
        </Card>
      )}

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
            <Button
              size="small"
              type="text"
              icon={<ReloadOutlined />}
              onClick={() =>
                void api
                  .getRemoteStatus()
                  .then(setStatus)
                  .catch(() => {})
              }
            />
          </Tooltip>
        }
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              background: degraded
                ? "rgba(255,77,79,0.06)"
                : "rgba(0,0,0,0.02)",
              borderRadius: 10,
              padding: "14px 16px",
            }}
          >
            <ModeBadge status={status} />
            <Space size={14}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                开关配置: {enabled ? "开启" : "关闭"}
              </Typography.Text>
              {degraded && (
                <Badge
                  status="error"
                  text={
                    <Typography.Text type="danger" style={{ fontSize: 12 }}>
                      {status?.last_fail_reason ?? "远程不可用"}
                    </Typography.Text>
                  }
                />
              )}
            </Space>
          </div>
          <Space size={8} wrap>
            {(status?.local_models ?? []).map((m) => {
              const st = stateBadge(m.state);
              return (
                <Tag key={m.id} color={st.color} style={{ marginInlineEnd: 0 }}>
                  {m.display}: {st.label}
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
        {!status?.url && !p2pReady ? (
          <Alert
            type="info"
            showIcon
            message="先在上方配置远程连接（HTTP 链接+令牌，或 P2P 管道四项）才能管理远程节点"
          />
        ) : !nodeCfg ? (
          <Alert
            type="warning"
            showIcon
            message="远程节点不可达——检查节点控制台是否运行、CONTROL_API_KEY 是否已在本机（节点）页面配置"
          />
        ) : (
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Descriptions
              size="small"
              column={2}
              style={{
                background: "rgba(0,0,0,0.02)",
                padding: "8px 12px",
                borderRadius: 8,
              }}
            >
              <Descriptions.Item label="鉴权令牌">
                {nodeCfg.CONTROL_API_KEY
                  ? `${nodeCfg.CONTROL_API_KEY}…（已配置）`
                  : "未配置"}
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
              <Button
                type="primary"
                loading={nodeBusy}
                disabled={!apiKeyInput.trim()}
                onClick={() => void saveApiKey(apiKeyInput)}
              >
                保存到节点
              </Button>
            </Space.Compact>
            <Space size={24} wrap>
              <Space size={8}>
                <Switch
                  checked={nodeCfg.CONTROL_RESIDENT === "1"}
                  loading={nodeBusy}
                  onChange={(on) => void toggleNodeKey("CONTROL_RESIDENT", on)}
                />
                <Typography.Text>常驻模式</Typography.Text>
                <Tooltip title="禁用心跳自杀机制——无 opencode 连接时节点控制台不退出（节点推荐开启）">
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    ?
                  </Typography.Text>
                </Tooltip>
              </Space>
              <Space size={8}>
                <Switch
                  checked={autostart?.installed ?? false}
                  loading={nodeBusy}
                  onChange={(on) => void toggleAutostart(on)}
                />
                <Typography.Text>开机自启</Typography.Text>
                <Tooltip title="安装 macOS LaunchAgent; 设备需开启「自动登录」（登录后才会拉起）">
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    ?
                  </Typography.Text>
                </Tooltip>
              </Space>
            </Space>
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 0 }}
              message="部署提示: ① CONTROL_API_KEY 保存后需重启远程节点控制台生效（绑定 0.0.0.0 + 鉴权）; ② Mac mini 需开启系统「自动登录」，LaunchAgent 在登录后运行; ③ 首次绑 0.0.0.0 macOS 可能弹防火墙允许提示"
            />
          </Space>
        )}
      </Card>
    </Space>
  );
};

export default RemoteSection;
