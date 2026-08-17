/**
 * 控制台单页主布局（布局 A：单页 + sticky 锚点 + 2 列网格）。
 *
 * 数据对账原则（用户反馈固化）：
 *   环境就绪 X/Y = Σ(外部工具 + Python 包 + Docker 镜像 + 模型 + 必要配置)，
 *   悬浮显示每类明细和缺失项名称——任何数字都能追溯。
 *   一键安装 N = 缺失项中"可自动安装"的（pip 包 + Docker 镜像 + 硬件达标模型），
 *   悬浮显示将安装什么 + 哪些只能手动。N=0 时禁用（不静默无操作）。
 */
import React, { useCallback, useMemo, useState } from "react";
import {
  Layout,
  Anchor,
  Card,
  Typography,
  Space,
  Tag,
  Button,
  Popover,
  Descriptions,
  Badge,
  Row,
  Col,
  App as AntApp,
  Divider,
  Tooltip,
} from "antd";
import {
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  DesktopOutlined,
  ReloadOutlined,
  PoweroffOutlined,
} from "@ant-design/icons";
import { Popconfirm } from "antd";
import DockerSection from "./sections/DockerSection";
import ModelsSection from "./sections/ModelsSection";
import PythonDepsSection from "./sections/PythonDepsSection";
import ToolsSection from "./sections/ToolsSection";
import ConfigSection from "./sections/ConfigSection";
import ProcessSection from "./sections/ProcessSection";
import InstallOrchestrator, {
  InstallTask,
} from "./sections/InstallOrchestrator";
import {
  useScan,
  useModels,
  useSystem,
  useHardware,
  useRequiredStatus,
} from "./hooks";
import { useReadiness } from "./hooks/useReadiness";
import { CATEGORIES, type CategoryKey } from "./constants/categories";
import { api } from "./api/client";
import type { ModelAsset } from "./types";

const { Header, Content } = Layout;

/** docker pull 的 SSE 包装为 Promise（编排器用）——以 __done__ exit_code 为权威标志 */
function pullImageAsync(image: string): Promise<string> {
  return new Promise((resolve, reject) => {
    let last = "";
    api.pullImage(image, (line) => {
      if (line.startsWith("__error__")) {
        reject(new Error(line.replace("__error__ ", "")));
        return;
      }
      if (line.startsWith("__done__")) {
        const code = parseInt(line.split("exit_code=")[1] ?? "1", 10);
        if (code === 0) resolve(`拉取完成（${last.slice(0, 60)}）`);
        else
          reject(
            new Error(
              `docker pull ${image} 失败（exit ${code}，最后输出: ${last.slice(0, 80)}）`,
            ),
          );
        return;
      }
      last = line;
    });
    setTimeout(
      () =>
        reject(
          new Error(`拉取 ${image} 超时（最后进度: ${last.slice(0, 80)}）`),
        ),
      30 * 60 * 1000,
    );
  });
}

/** 模型下载包装：启动 + 轮询到终态 */
async function downloadModelAsync(modelId: string): Promise<string> {
  await api.downloadModel(modelId);
  for (let i = 0; i < 900; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const resp = await api.getModels();
    const m = resp.models.find((x) => x.id === modelId);
    if (!m) throw new Error(`模型 ${modelId} 不存在`);
    if (m.download.status === "done") return "下载完成";
    if (m.download.status === "error") throw new Error(m.download.error);
  }
  throw new Error(`下载 ${modelId} 超时`);
}

const App: React.FC = () => {
  const { message } = AntApp.useApp();
  const scan = useScan();
  const models = useModels();
  const system = useSystem();
  const hardware = useHardware();
  const required = useRequiredStatus();

  const [orchOpen, setOrchOpen] = useState(false);
  const [orchTitle, setOrchTitle] = useState("");
  const [orchTasks, setOrchTasks] = useState<InstallTask[]>([]);

  const refreshAll = useCallback(() => {
    scan.refresh();
    models.refresh();
    required.refresh();
  }, [scan, models, required]);

  // ── 控制台自重启（页面按钮；execv 替换进程，前端轮询 boot_token 判定完成）──
  const [restarting, setRestarting] = useState(false);

  const fetchHealthToken = useCallback(async (): Promise<string | null> => {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 2500);
      const r = await fetch("/api/health", { signal: ctrl.signal });
      clearTimeout(t);
      if (!r.ok && r.status !== 503) return null; // 503 = 实例活着但模型加载中
      const d = (await r.json()) as { boot_token?: unknown };
      return typeof d.boot_token === "string" ? d.boot_token : null;
    } catch {
      return null; // exec 间隙连接拒绝
    }
  }, []);

  const doRestart = useCallback(async () => {
    if (restarting) return;
    const before = await fetchHealthToken();
    try {
      await api.restartConsole();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
      return;
    }
    setRestarting(true);
    const deadline = Date.now() + 120_000;
    const poll = async () => {
      if (Date.now() > deadline) {
        setRestarting(false);
        message.error("重启超时（120s）——请检查控制台进程状态");
        return;
      }
      const tok = await fetchHealthToken();
      if (tok != null && tok !== before) {
        setRestarting(false);
        message.success("重启完成，新代码已生效");
        refreshAll();
        return;
      }
      setTimeout(() => void poll(), 2000);
    };
    setTimeout(() => void poll(), 3000); // 跳过 exec 延迟窗（1.5s exec + Python 启动）
  }, [restarting, fetchHealthToken, message, refreshAll]);


  // ─── 缺失对象（安装编排用；计数展示一律走 readiness 单一源）───
  const toolsMissing = useMemo(
    () =>
      Object.values(scan.data?.agents ?? {})
        .flat()
        .filter((t) => !t.available && !t.skipped),
    [scan.data],
  );

  const pyMissing = useMemo(
    () => (scan.data?.global.python_packages ?? []).filter((p) => !p.available),
    [scan.data],
  );

  const dockerMissing = useMemo(
    () => scan.data?.global.docker.images.filter((i) => !i.pulled) ?? [],
    [scan.data],
  );

  const modelMissing = useMemo(
    () => (models.data?.models ?? []).filter((m) => !m.cached),
    [models.data],
  );

  // ─── 环境就绪（单一计算源：Popover/顶栏/卡片 Tag/锚点徽标全从这里取）───
  const readiness = useReadiness(scan.data, models.data, required.data);
  const catStat = (key: CategoryKey) =>
    readiness.cats.find((c) => c.key === key)!;

  // ─── 可自动安装项（唯一清单全量可装；installer 只决定服务端执行 pip 还是 conda）───
  const pipInstallable = useMemo(() => pyMissing, [pyMissing]);
  const modelBlocked = useMemo(
    () => modelMissing.filter((m) => !m.hardware.ok),
    [modelMissing],
  );

  const installableCount =
    pipInstallable.length +
    dockerMissing.length +
    (modelMissing.length - modelBlocked.length);

  const installPopover = useMemo(() => {
    if (installableCount === 0) return null;
    return (
      <div style={{ maxWidth: 340 }}>
        <Typography.Text strong style={{ fontSize: 12 }}>
          将自动安装 {installableCount} 项：
        </Typography.Text>
        <ul style={{ margin: "6px 0", paddingLeft: 18, fontSize: 12 }}>
          {pipInstallable.length > 0 && (
            <li>pip：{pipInstallable.map((p) => p.pip_name).join("、")}</li>
          )}
          {dockerMissing.length > 0 && (
            <li>Docker：{dockerMissing.map((i) => i.name).join("、")}</li>
          )}
          {modelMissing.length - modelBlocked.length > 0 && (
            <li>
              模型：
              {modelMissing
                .filter((m) => m.hardware.ok)
                .map((m) => m.display)
                .join("、")}
            </li>
          )}
        </ul>
        {(toolsMissing.length > 0 ||
          modelBlocked.length > 0) && (
          <>
            <Divider style={{ margin: "6px 0" }} />
            <Typography.Text type="warning" style={{ fontSize: 12 }}>
              以下缺失项无法自动安装（需手动）：
            </Typography.Text>
            <ul style={{ margin: "6px 0", paddingLeft: 18, fontSize: 12 }}>
              {toolsMissing.length > 0 && (
                <li>
                  外部工具：
                  {[...new Set(toolsMissing.map((t) => t.name))].join("、")}
                </li>
              )}
              {modelBlocked.length > 0 && (
                <li>
                  硬件不达标模型：
                  {modelBlocked.map((m) => m.display).join("、")}
                </li>
              )}
            </ul>
          </>
        )}
      </div>
    );
  }, [
    installableCount,
    pipInstallable,
    dockerMissing,
    modelMissing,
    modelBlocked,
    toolsMissing,
  ]);

  // ─── 任务构建 ───
  const buildPipTasks = useCallback(
    (): InstallTask[] =>
      pipInstallable.map((p) => ({
        key: `pip-${p.pip_name}`,
        kind: "pip" as const,
        label: `pip install ${p.pip_name}`,
        run: async () => {
          const r = await api.install(p.pip_name);
          if (!r.success) throw new Error(r.stderr || r.error || "未知错误");
          return r.stdout || "安装成功";
        },
      })),
    [pipInstallable],
  );

  const buildDockerTasks = useCallback(
    (): InstallTask[] =>
      dockerMissing.map((i) => ({
        key: `docker-${i.name}`,
        kind: "docker" as const,
        label: `docker pull ${i.name}`,
        run: () => pullImageAsync(i.name),
      })),
    [dockerMissing],
  );

  const buildModelTasks = useCallback(
    (): InstallTask[] =>
      modelMissing
        .filter((m: ModelAsset) => m.hardware.ok)
        .map((m) => ({
          key: `model-${m.id}`,
          kind: "model" as const,
          label: `下载 ${m.display}（${m.disk_gb}GB）`,
          run: () => downloadModelAsync(m.id),
        })),
    [modelMissing],
  );

  const openOrchestrator = (scope: "all" | "docker" | "models" | "deps") => {
    let tasks: InstallTask[] = [];
    if (scope === "docker") tasks = buildDockerTasks();
    else if (scope === "models") tasks = buildModelTasks();
    else if (scope === "deps") tasks = buildPipTasks();
    else
      tasks = [...buildPipTasks(), ...buildDockerTasks(), ...buildModelTasks()];

    if (tasks.length === 0) {
      message.info(
        "该范围内没有可自动安装的缺失项（缺失项均需手动处理，见各分区安装提示）",
      );
      return;
    }
    setOrchTitle(
      `一键安装（${tasks.length} 项，按 pip → Docker → 模型 顺序执行）`,
    );
    setOrchTasks(tasks);
    setOrchOpen(true);
  };

  // ─── 硬件 Popover ───
  // CPU 频率 <1GHz 视为伪值不显示（Apple Silicon 上 psutil 返回 4MHz → "0GHz"）
  const cpuFreqGHz = hardware.data?.cpu.frequency_mhz
    ? hardware.data.cpu.frequency_mhz / 1000
    : 0;
  const hwContent = hardware.data ? (
    <Descriptions
      size="small"
      column={1}
      style={{ minWidth: "auto", maxWidth: 260 }}
    >
      <Descriptions.Item label="CPU">
        {hardware.data.cpu.physical_cores} 核 {hardware.data.cpu.logical_cores}{" "}
        线程
        {cpuFreqGHz >= 1 ? ` · ${Math.round(cpuFreqGHz)}GHz` : ""}
      </Descriptions.Item>
      <Descriptions.Item label="内存">
        {hardware.data.memory.total_gb}GB（可用{" "}
        {hardware.data.memory.available_gb}GB）
      </Descriptions.Item>
      <Descriptions.Item label="GPU">
        {hardware.data.gpu.length > 0
          ? hardware.data.gpu.map((g, i) => (
              <div key={i}>
                {g.name}
                {g.vram ? ` · ${g.vram}` : ""}
              </div>
            ))
          : "无独立 GPU"}
      </Descriptions.Item>
      <Descriptions.Item label="系统">
        {system.data?.platform ?? hardware.data.os.system}
      </Descriptions.Item>
    </Descriptions>
  ) : (
    <Typography.Text type="secondary">加载中…</Typography.Text>
  );

  const anchorItems = CATEGORIES.map((c) => {
    const st = catStat(c.key);
    return {
      key: c.key,
      href: `#section-${c.key}`,
      title: (
        <Space size={4}>
          {c.title}
          {st.missingNames.length > 0 && (
            <Tag color="warning" style={{ marginInlineEnd: 0 }}>
              {st.missingNames.length}
            </Tag>
          )}
        </Space>
      ),
    };
  });

  const cardProps = { size: "small" as const, style: { height: "100%" } };

  return (
    <Layout style={{ minHeight: "100vh", background: "transparent" }}>
      {/* 顶栏：通栏毛玻璃（sticky）。透明容器 + 自绘底色，解决 AntD Header 默认深蓝的老旧观感 */}
      <Header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          paddingInline: "clamp(16px, 3vw, 40px)",
          position: "sticky",
          top: 0,
          zIndex: 100,
          lineHeight: "normal",
          background: "rgba(255,255,255,0.78)",
          backdropFilter: "saturate(180%) blur(20px)",
          WebkitBackdropFilter: "saturate(180%) blur(20px)",
          borderBottom: "1px solid rgba(0,0,0,0.06)",
        }}
      >
        {/* 品牌：图标与文字用 flex 精确居中（Space 组件的基线对齐不可控） */}
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: 9,
              background: "linear-gradient(135deg, #0A6CFF 0%, #0055D4 100%)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              boxShadow: "0 2px 8px rgba(10,108,255,0.28)",
            }}
          >
            <SafetyCertificateOutlined
              style={{ fontSize: 19, color: "#fff" }}
            />
          </div>
          {/* 文字块固定 34px 高（=图标高），内部 flex 居中——消除两行文字的视觉偏移 */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              justifyContent: "center",
              height: 34,
            }}
          >
            <span
              style={{
                fontSize: 16,
                fontWeight: 650,
                letterSpacing: 0.2,
                color: "#1d1d1f",
                lineHeight: 1.15,
              }}
            >
              OpenSecurity
            </span>
            <span
              style={{
                fontSize: 11,
                fontWeight: 500,
                color: "rgba(0,0,0,0.45)",
                letterSpacing: 1,
                lineHeight: 1.3,
              }}
            >
              控制台
            </span>
          </div>
          <Popover
            content={hwContent}
            title={
              /* 标题右侧内联刷新按钮（硬件信息默认只拉一次，此处可强制重拉） */
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 8,
                }}
              >
                <span>硬件信息</span>
                <Tooltip title="重新检测硬件">
                  <Button
                    type="text"
                    size="small"
                    icon={<ReloadOutlined />}
                    loading={hardware.loading}
                    onClick={() => hardware.refresh()}
                  />
                </Tooltip>
              </div>
            }
            placement="bottomRight"
            trigger="click"
            overlayStyle={{ maxWidth: "calc(100vw - 24px)" }}
          >
            <Button
              size="small"
              icon={<DesktopOutlined />}
              style={{ background: "rgba(0,0,0,0.03)" }}
            >
              硬件
            </Button>
          </Popover>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <Popover
            title={`环境就绪 ${readiness.ok}/${readiness.total}（按分类）`}
            content={
              /* 直接内联 Descriptions.Item——自定义组件包裹会被 AntD 解析丢弃（内容区不渲染） */
              <Descriptions size="small" column={1} style={{ maxWidth: 340 }}>
                {readiness.cats.map((c) => (
                  <Descriptions.Item key={c.key} label={c.title}>
                    <Space size={6} wrap>
                      <span>
                        {c.ok}/{c.total} {c.unit}
                      </span>
                      {c.missingNames.length > 0 && (
                        <Typography.Text type="danger" style={{ fontSize: 12 }}>
                          缺: {c.missingNames.join("、")}
                        </Typography.Text>
                      )}
                    </Space>
                  </Descriptions.Item>
                ))}
              </Descriptions>
            }
            placement="bottomRight"
            /* 钳制到视口内，防右溢出 */
            overlayStyle={{ maxWidth: "calc(100vw - 24px)" }}
          >
            <Badge
              status={
                readiness.total > 0 && readiness.ok === readiness.total
                  ? "success"
                  : "warning"
              }
              text={
                <Typography.Text
                  style={{
                    color: "rgba(0,0,0,0.78)",
                    fontSize: 13,
                    fontWeight: 500,
                  }}
                >
                  环境就绪 {readiness.ok}/{readiness.total}
                </Typography.Text>
              }
            />
          </Popover>
          {installableCount > 0 ? (
            <Popover
              content={installPopover}
              title="一键安装范围"
              placement="bottomRight"
              overlayStyle={{ maxWidth: "calc(100vw - 24px)" }}
            >
              <Button
                type="primary"
                size="small"
                icon={<ThunderboltOutlined />}
                onClick={() => openOrchestrator("all")}
              >
                一键安装（{installableCount}）
              </Button>
            </Popover>
          ) : (
            /* 浅色毛玻璃顶栏上的 disabled 态（AntD 默认在浅底上可读，无需特殊处理） */
            <Button
              size="small"
              icon={<ThunderboltOutlined />}
              disabled
              title="没有可自动安装的缺失项（缺失项均需手动，见环境就绪明细）"
            >
              一键安装
            </Button>
          )}
        </div>
      </Header>

      {/* 内容区：通栏（去 maxWidth 限制，留响应式边距），苹果式宽松呼吸感 */}
      <Content
        style={{ padding: "16px clamp(16px, 3vw, 40px) 56px", width: "100%" }}
      >
        {/* 锚点行：分段控件（segmented 风）+ 右刷新；sticky 由本胶囊容器承担。
            注意：Anchor 不用内置 offsetTop（affix 模式会包 ant-affix fixed 层，
            脱离本容器 flex 布局，把刷新按钮挤到下一行——实测踩坑）。 */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            background: "rgba(0,0,0,0.035)",
            borderRadius: 10,
            padding: 4,
            marginBottom: 14,
            position: "sticky",
            top: 64,
            zIndex: 90,
            width: "fit-content",
            maxWidth: "100%",
          }}
        >
          <Anchor
            direction="horizontal"
            items={anchorItems}
            style={{ background: "transparent" }}
          />
          <span
            style={{
              width: 1,
              height: 18,
              background: "rgba(0,0,0,0.1)",
              marginInline: 2,
            }}
          />
          <Tooltip title="重新扫描全部（Docker / 模型 / Python 依赖 / 外部工具 / 配置）">
            <Button
              size="small"
              type="text"
              icon={<ReloadOutlined />}
              loading={scan.loading || models.loading}
              onClick={() => refreshAll()}
            />
          </Tooltip>
          <Popconfirm
            title="重启控制台？"
            description="接口断开数秒、模型重载需几十秒；用于让最新代码生效"
            okText="重启"
            cancelText="取消"
            onConfirm={() => void doRestart()}
            disabled={restarting}
          >
            <Tooltip title={restarting ? "重启中…等待新实例就绪" : "重启控制台（让最新代码生效）"}>
              <Button
                size="small"
                type="text"
                danger={restarting}
                icon={<PoweroffOutlined spin={restarting} />}
                disabled={restarting}
              />
            </Tooltip>
          </Popconfirm>
        </div>
        <Row gutter={[12, 12]}>
          <Col xs={24} xl={12} id="section-docker">
            <Card
              {...cardProps}
              title={
                <Space size={8}>
                  {catStat("docker").title}
                  <Tag style={{ marginInlineEnd: 0 }}>
                    {scan.data
                      ? `${catStat("docker").ok}/${catStat("docker").total} ${catStat("docker").unit}`
                      : "…"}
                  </Tag>
                </Space>
              }
              extra={
                dockerMissing.length > 0 && (
                  <Button
                    size="small"
                    icon={<ThunderboltOutlined />}
                    onClick={() => openOrchestrator("docker")}
                  >
                    拉取缺失（{dockerMissing.length}）
                  </Button>
                )
              }
            >
              <DockerSection
                docker={scan.data?.global.docker}
                onRefresh={() => scan.refresh()}
              />
            </Card>
          </Col>

          <Col xs={24} xl={12} id="section-models">
            <Card
              {...cardProps}
              title={
                <Space size={8}>
                  {catStat("models").title}
                  <Tag style={{ marginInlineEnd: 0 }}>
                    {models.data
                      ? `${catStat("models").ok}/${catStat("models").total} ${catStat("models").unit}`
                      : "…"}
                  </Tag>
                </Space>
              }
              extra={
                modelMissing.length - modelBlocked.length > 0 && (
                  <Button
                    size="small"
                    icon={<ThunderboltOutlined />}
                    onClick={() => openOrchestrator("models")}
                  >
                    下载缺失（{modelMissing.length - modelBlocked.length}）
                  </Button>
                )
              }
            >
              <ModelsSection
                models={models.data?.models}
                onDownload={(id) =>
                  downloadModelAsync(id)
                    .then(() => {
                      models.refresh();
                      message.success("模型下载完成");
                    })
                    .catch((e) => {
                      models.refresh();
                      message.error({
                        content: `模型下载失败：${e.message}`,
                        duration: 10,
                      });
                    })
                }
                onRelease={() => {
                  fetch("/api/ocr/release", { method: "POST" })
                    .then(() => models.refresh())
                    .catch(() => models.refresh());
                }}
              />
            </Card>
          </Col>

          <Col xs={24} xl={12} id="section-deps">
            <Card
              {...cardProps}
              title={
                <Space size={8}>
                  {catStat("deps").title}
                  <Tag style={{ marginInlineEnd: 0 }}>
                    {scan.data
                      ? `${catStat("deps").ok}/${catStat("deps").total} ${catStat("deps").unit}`
                      : "…"}
                  </Tag>
                </Space>
              }
              extra={
                pipInstallable.length > 0 && (
                  <Button
                    size="small"
                    icon={<ThunderboltOutlined />}
                    onClick={() => openOrchestrator("deps")}
                  >
                    安装缺失（{pipInstallable.length}）
                  </Button>
                )
              }
            >
              <PythonDepsSection
                packages={
                  scan.loading && catStat("deps").total === 0
                    ? undefined
                    : (scan.data?.global.python_packages ?? [])
                }
                venvPath={system.data?.venv_path}
                onRefresh={() => scan.refresh()}
              />
            </Card>
          </Col>

          <Col xs={24} xl={12} id="section-tools">
            <Card
              {...cardProps}
              title={
                <Space size={8}>
                  {catStat("tools").title}
                  <Tag style={{ marginInlineEnd: 0 }}>
                    {scan.data
                      ? `${catStat("tools").ok}/${catStat("tools").total} ${catStat("tools").unit}（不可 pip）`
                      : "…"}
                  </Tag>
                </Space>
              }
            >
              <ToolsSection agents={scan.data?.agents} />
            </Card>
          </Col>

          <Col xs={24} id="section-config">
            <Card
              title={
                <Space size={8}>
                  {catStat("config").title}
                  {catStat("config").ok === catStat("config").total &&
                  catStat("config").total > 0 ? (
                    <Tag color="success" style={{ marginInlineEnd: 0 }}>
                      {catStat("config").ok}/{catStat("config").total}{" "}
                      {catStat("config").unit}
                    </Tag>
                  ) : (
                    <Tag color="error" style={{ marginInlineEnd: 0 }}>
                      {catStat("config").ok}/{catStat("config").total} · 缺{" "}
                      {catStat("config").missingNames.join("、")}
                    </Tag>
                  )}
                </Space>
              }
            >
              <ConfigSection />
            </Card>
          </Col>

          {/* 进程清单：运维观测页（非环境就绪分类），自轮询 */}
          <Col xs={24} id="section-processes" style={{ marginTop: 12 }}>
            <ProcessSection />
          </Col>
        </Row>
      </Content>

      <InstallOrchestrator
        open={orchOpen}
        title={orchTitle}
        tasks={orchTasks}
        onClose={() => setOrchOpen(false)}
        onFinish={refreshAll}
      />
    </Layout>
  );
};

export default App;
