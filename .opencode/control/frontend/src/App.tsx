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
  Layout, Anchor, Card, Typography, Space, Tag, Button, Popover, Descriptions, Badge,
  Row, Col, App as AntApp, Divider,
} from "antd";
import {
  SafetyCertificateOutlined, ThunderboltOutlined, DesktopOutlined,
} from "@ant-design/icons";
import DockerSection from "./sections/DockerSection";
import ModelsSection from "./sections/ModelsSection";
import PythonDepsSection from "./sections/PythonDepsSection";
import ToolsSection from "./sections/ToolsSection";
import ConfigSection from "./sections/ConfigSection";
import InstallOrchestrator, { InstallTask } from "./sections/InstallOrchestrator";
import { useScan, useModels, useSystem, useHardware, useRequiredStatus } from "./hooks";
import { api } from "./api/client";
import type { ModelAsset } from "./types";

const { Header, Content } = Layout;

/** docker pull 的 SSE 包装为 Promise（编排器用）——以 __done__ exit_code 为权威标志 */
function pullImageAsync(image: string): Promise<string> {
  return new Promise((resolve, reject) => {
    let last = "";
    api.pullImage(image, (line) => {
      if (line.startsWith("__error__")) { reject(new Error(line.replace("__error__ ", ""))); return; }
      if (line.startsWith("__done__")) {
        const code = parseInt(line.split("exit_code=")[1] ?? "1", 10);
        if (code === 0) resolve(`拉取完成（${last.slice(0, 60)}）`);
        else reject(new Error(`docker pull ${image} 失败（exit ${code}，最后输出: ${last.slice(0, 80)}）`));
        return;
      }
      last = line;
    });
    setTimeout(() => reject(new Error(`拉取 ${image} 超时（最后进度: ${last.slice(0, 80)}）`)), 30 * 60 * 1000);
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

/** 明细行：分类名 X/Y（缺失时列名称） */
const BreakdownRow: React.FC<{
  label: string; ok: number; total: number; missingNames: string[];
}> = ({ label, ok, total, missingNames }) => (
  <Descriptions.Item label={label}>
    <Space size={6} wrap>
      <span>{ok}/{total}</span>
      {missingNames.length > 0 && (
        <Typography.Text type="danger" style={{ fontSize: 12 }}>
          缺: {missingNames.join("、")}
        </Typography.Text>
      )}
    </Space>
  </Descriptions.Item>
);

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

  // ─── 缺失统计（全维度，环境就绪的对账基础）───
  const toolsAll = useMemo(
    () => Object.values(scan.data?.agents ?? {}).flat(),
    [scan.data]);
  const toolsMissing = useMemo(
    () => toolsAll.filter((t) => !t.available && !t.skipped), [toolsAll]);

  const pyPkgs = useMemo(() => scan.data?.global.python_packages ?? [], [scan.data]);
  const pyMissing = useMemo(() => pyPkgs.filter((p) => !p.available), [pyPkgs]);

  const dockerMissing = useMemo(
    () => scan.data?.global.docker.images.filter((i) => !i.pulled) ?? [],
    [scan.data]);

  const modelMissing = useMemo(
    () => (models.data?.models ?? []).filter((m) => !m.cached),
    [models.data]);

  const configMissing = useMemo(
    () => Object.entries(required.data ?? {}).filter(([, r]) => !r.ok),
    [required.data]);

  // ─── 环境就绪（悬浮可追溯）───
  const breakdown = useMemo(() => {
    const cats = [
      { label: "外部工具", ok: toolsAll.length - toolsMissing.length, total: toolsAll.length, names: toolsMissing.map((t) => t.name) },
      { label: "Python 包", ok: pyPkgs.length - pyMissing.length, total: pyPkgs.length, names: pyMissing.map((p) => p.pip_name) },
      { label: "Docker 镜像", ok: (scan.data?.global.docker.images.length ?? 0) - dockerMissing.length, total: scan.data?.global.docker.images.length ?? 0, names: dockerMissing.map((i) => i.name) },
      { label: "模型", ok: (models.data?.models.length ?? 0) - modelMissing.length, total: models.data?.models.length ?? 0, names: modelMissing.map((m) => m.display) },
      { label: "必要配置", ok: Object.keys(required.data ?? {}).length - configMissing.length, total: Object.keys(required.data ?? {}).length, names: configMissing.map(([k]) => k) },
    ];
    return {
      cats,
      ok: cats.reduce((n, c) => n + c.ok, 0),
      total: cats.reduce((n, c) => n + c.total, 0),
    };
  }, [toolsAll, toolsMissing, pyPkgs, pyMissing, scan.data, dockerMissing, models.data, modelMissing, required.data, configMissing]);

  // ─── 可自动安装项（一键安装的真实范围）───
  const pipInstallable = useMemo(
    () => pyMissing.filter((p) => p.installer === "pip"), [pyMissing]);
  const pipManual = useMemo(
    () => pyMissing.filter((p) => p.installer !== "pip"), [pyMissing]);
  const modelBlocked = useMemo(
    () => modelMissing.filter((m) => !m.hardware.ok), [modelMissing]);

  const installableCount =
    pipInstallable.length + dockerMissing.length + (modelMissing.length - modelBlocked.length);

  const installPopover = useMemo(() => {
    if (installableCount === 0) return null;
    return (
      <div style={{ maxWidth: 340 }}>
        <Typography.Text strong style={{ fontSize: 12 }}>将自动安装 {installableCount} 项：</Typography.Text>
        <ul style={{ margin: "6px 0", paddingLeft: 18, fontSize: 12 }}>
          {pipInstallable.length > 0 && <li>pip：{pipInstallable.map((p) => p.pip_name).join("、")}</li>}
          {dockerMissing.length > 0 && <li>Docker：{dockerMissing.map((i) => i.name).join("、")}</li>}
          {modelMissing.length - modelBlocked.length > 0 && (
            <li>模型：{modelMissing.filter((m) => m.hardware.ok).map((m) => m.display).join("、")}</li>
          )}
        </ul>
        {(toolsMissing.length > 0 || pipManual.length > 0 || modelBlocked.length > 0) && (
          <>
            <Divider style={{ margin: "6px 0" }} />
            <Typography.Text type="warning" style={{ fontSize: 12 }}>以下缺失项无法自动安装（需手动）：</Typography.Text>
            <ul style={{ margin: "6px 0", paddingLeft: 18, fontSize: 12 }}>
              {toolsMissing.length > 0 && <li>外部工具：{[...new Set(toolsMissing.map((t) => t.name))].join("、")}</li>}
              {pipManual.length > 0 && <li>conda 包：{pipManual.map((p) => p.pip_name).join("、")}</li>}
              {modelBlocked.length > 0 && <li>硬件不达标模型：{modelBlocked.map((m) => m.display).join("、")}</li>}
            </ul>
          </>
        )}
      </div>
    );
  }, [installableCount, pipInstallable, dockerMissing, modelMissing, modelBlocked, toolsMissing, pipManual]);

  // ─── 任务构建 ───
  const buildPipTasks = useCallback((): InstallTask[] =>
    pipInstallable.map((p) => ({
      key: `pip-${p.pip_name}`, kind: "pip" as const, label: `pip install ${p.pip_name}`,
      run: async () => {
        const r = await api.install(p.pip_name);
        if (!r.success) throw new Error(r.stderr || r.error || "未知错误");
        return r.stdout || "安装成功";
      },
    })), [pipInstallable]);

  const buildDockerTasks = useCallback((): InstallTask[] =>
    dockerMissing.map((i) => ({
      key: `docker-${i.name}`, kind: "docker" as const, label: `docker pull ${i.name}`,
      run: () => pullImageAsync(i.name),
    })), [dockerMissing]);

  const buildModelTasks = useCallback((): InstallTask[] =>
    modelMissing
      .filter((m: ModelAsset) => m.hardware.ok)
      .map((m) => ({
        key: `model-${m.id}`, kind: "model" as const, label: `下载 ${m.display}（${m.disk_gb}GB）`,
        run: () => downloadModelAsync(m.id),
      })), [modelMissing]);

  const openOrchestrator = (scope: "all" | "docker" | "models" | "deps") => {
    let tasks: InstallTask[] = [];
    if (scope === "docker") tasks = buildDockerTasks();
    else if (scope === "models") tasks = buildModelTasks();
    else if (scope === "deps") tasks = buildPipTasks();
    else tasks = [...buildPipTasks(), ...buildDockerTasks(), ...buildModelTasks()];

    if (tasks.length === 0) {
      message.info("该范围内没有可自动安装的缺失项（缺失项均需手动处理，见各分区安装提示）");
      return;
    }
    setOrchTitle(`一键安装（${tasks.length} 项，按 pip → Docker → 模型 顺序执行）`);
    setOrchTasks(tasks);
    setOrchOpen(true);
  };

  // ─── 硬件 Popover ───
  const hwContent = hardware.data ? (
    <Descriptions size="small" column={1} style={{ minWidth: 300 }}>
      <Descriptions.Item label="CPU">
        {hardware.data.cpu.physical_cores} 核 {hardware.data.cpu.logical_cores} 线程
        {hardware.data.cpu.frequency_mhz ? ` · ${Math.round(hardware.data.cpu.frequency_mhz / 1000)}GHz` : ""}
      </Descriptions.Item>
      <Descriptions.Item label="内存">
        {hardware.data.memory.total_gb}GB（可用 {hardware.data.memory.available_gb}GB）
      </Descriptions.Item>
      <Descriptions.Item label="GPU">
        {hardware.data.gpu.length > 0
          ? hardware.data.gpu.map((g, i) => (<div key={i}>{g.name}{g.vram ? ` · ${g.vram}` : ""}</div>))
          : "无独立 GPU"}
      </Descriptions.Item>
      <Descriptions.Item label="系统">{system.data?.platform ?? hardware.data.os.system}</Descriptions.Item>
    </Descriptions>
  ) : (<Typography.Text type="secondary">加载中…</Typography.Text>);

  const anchorItems = [
    { key: "docker", href: "#section-docker", title: <Space size={4}>Docker{dockerMissing.length > 0 && <Tag color="warning" style={{ marginInlineEnd: 0 }}>{dockerMissing.length}</Tag>}</Space> },
    { key: "models", href: "#section-models", title: <Space size={4}>模型{modelMissing.length > 0 && <Tag color="warning" style={{ marginInlineEnd: 0 }}>{modelMissing.length}</Tag>}</Space> },
    { key: "deps", href: "#section-deps", title: <Space size={4}>Python 依赖{pyMissing.length > 0 && <Tag color="warning" style={{ marginInlineEnd: 0 }}>{pyMissing.length}</Tag>}</Space> },
    { key: "tools", href: "#section-tools", title: <Space size={4}>外部工具{toolsMissing.length > 0 && <Tag color="warning" style={{ marginInlineEnd: 0 }}>{[...new Set(toolsMissing.map((t) => t.name))].length}</Tag>}</Space> },
    { key: "config", href: "#section-config", title: <Space size={4}>配置{configMissing.length > 0 && <Tag color="warning" style={{ marginInlineEnd: 0 }}>{configMissing.length}</Tag>}</Space> },
  ];

  const cardProps = { size: "small" as const, style: { height: "100%" } };

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header
        style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          paddingInline: 20, position: "sticky", top: 0, zIndex: 100,
        }}
      >
        <Space size={12}>
          <SafetyCertificateOutlined style={{ fontSize: 20, color: "#1677ff" }} />
          <Typography.Title level={5} style={{ color: "#fff", margin: 0 }}>
            OpenSecurity 控制台
          </Typography.Title>
          <Popover content={hwContent} title="硬件信息" placement="bottomRight" trigger="click">
            <Button size="small" ghost icon={<DesktopOutlined />}>硬件</Button>
          </Popover>
        </Space>
        <Space size={14}>
          <Popover
            title={`环境就绪 ${breakdown.ok}/${breakdown.total}（按分类）`}
            content={(
              <Descriptions size="small" column={1} style={{ minWidth: 320 }}>
                {breakdown.cats.map((c) => (
                  <BreakdownRow key={c.label} label={c.label} ok={c.ok} total={c.total} missingNames={c.names} />
                ))}
              </Descriptions>
            )}
            placement="bottomRight"
          >
            <Badge
              status={breakdown.total > 0 && breakdown.ok === breakdown.total ? "success" : "warning"}
              text={
                <Typography.Text style={{ color: "rgba(255,255,255,0.85)", fontSize: 13 }}>
                  环境就绪 {breakdown.ok}/{breakdown.total}
                </Typography.Text>
              }
            />
          </Popover>
          {installableCount > 0 ? (
            <Popover content={installPopover} title="一键安装范围" placement="bottomLeft">
              <Button type="primary" size="small" icon={<ThunderboltOutlined />}
                onClick={() => openOrchestrator("all")}>
                一键安装（{installableCount}）
              </Button>
            </Popover>
          ) : (
            <Button size="small" icon={<ThunderboltOutlined />} disabled
              title="没有可自动安装的缺失项">
              一键安装
            </Button>
          )}
        </Space>
      </Header>

      <Content style={{ padding: "12px 20px 48px", maxWidth: 1600, margin: "0 auto", width: "100%" }}>
        <Anchor
          offsetTop={52} direction="horizontal" items={anchorItems}
          style={{ background: "#fff", padding: "8px 12px", borderRadius: 6, marginBottom: 12 }}
        />
        <Row gutter={[12, 12]}>
          <Col xs={24} xl={12} id="section-docker">
            <Card
              {...cardProps}
              title={
                <Space size={8}>
                  Docker
                  <Tag style={{ marginInlineEnd: 0 }}>
                    {scan.data ? `${scan.data.global.docker.images.length - dockerMissing.length}/${scan.data.global.docker.images.length} 镜像` : "…"}
                  </Tag>
                </Space>
              }
              extra={dockerMissing.length > 0 && (
                <Button size="small" icon={<ThunderboltOutlined />}
                  onClick={() => openOrchestrator("docker")}>
                  拉取缺失（{dockerMissing.length}）
                </Button>
              )}
            >
              <DockerSection docker={scan.data?.global.docker} onRefresh={() => scan.refresh()} />
            </Card>
          </Col>

          <Col xs={24} xl={12} id="section-models">
            <Card
              {...cardProps}
              title={
                <Space size={8}>
                  模型
                  <Tag style={{ marginInlineEnd: 0 }}>
                    {models.data ? `${models.data.models.length - modelMissing.length}/${models.data.models.length} 就绪` : "…"}
                  </Tag>
                </Space>
              }
              extra={modelMissing.length - modelBlocked.length > 0 && (
                <Button size="small" icon={<ThunderboltOutlined />}
                  onClick={() => openOrchestrator("models")}>
                  下载缺失（{modelMissing.length - modelBlocked.length}）
                </Button>
              )}
            >
              <ModelsSection
                models={models.data?.models}
                hfCacheDir={system.data?.hf_cache_dir}
                onDownload={(id) => downloadModelAsync(id)
                  .then(() => { models.refresh(); message.success("模型下载完成"); })
                  .catch((e) => {
                    models.refresh();
                    message.error({ content: `模型下载失败：${e.message}`, duration: 10 });
                  })}
              />
            </Card>
          </Col>

          <Col xs={24} xl={12} id="section-deps">
            <Card
              {...cardProps}
              title={
                <Space size={8}>
                  Python 依赖
                  <Tag style={{ marginInlineEnd: 0 }}>
                    {pyPkgs.length > 0 ? `${pyPkgs.length - pyMissing.length}/${pyPkgs.length} 已装` : "…"}
                  </Tag>
                </Space>
              }
              extra={pipInstallable.length > 0 && (
                <Button size="small" icon={<ThunderboltOutlined />}
                  onClick={() => openOrchestrator("deps")}>
                  安装缺失（{pipInstallable.length}）
                </Button>
              )}
            >
              <PythonDepsSection
                packages={pyPkgs.length > 0 || !scan.loading ? pyPkgs : undefined}
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
                  外部工具
                  <Tag style={{ marginInlineEnd: 0 }}>
                    {toolsAll.length > 0
                      ? `${toolsAll.length - toolsMissing.length}/${toolsAll.length} 可用（不可 pip，见安装提示）`
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
                  配置
                  {configMissing.length === 0
                    ? <Tag color="success" style={{ marginInlineEnd: 0 }}>完整</Tag>
                    : <Tag color="error" style={{ marginInlineEnd: 0 }}>缺 {configMissing.length} 项必要配置</Tag>}
                </Space>
              }
            >
              <ConfigSection />
            </Card>
          </Col>
        </Row>
      </Content>

      <InstallOrchestrator
        open={orchOpen} title={orchTitle} tasks={orchTasks}
        onClose={() => setOrchOpen(false)}
        onFinish={refreshAll}
      />
    </Layout>
  );
};

export default App;
