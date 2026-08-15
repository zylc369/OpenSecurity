# Progress: 控制台前端重设计（2026-08-15）✅ 完成

需求: 2026-08-15-control-frontend-redesign.md（§3.1 共 10 步，全部完成）

## 全部步骤完成

- [x] 步骤1 后端 fs/check + config/meta + write trim
  - routes/fs.py；config.py +EXTRA_CONFIG_META；config_route.py +/meta；config_store.write strip
- [x] 步骤2 后端 model_assets + /api/models
  - 子进程下载（剥离 HF_HUB_OFFLINE）+ 已缓存无操作（防 onnx 冗余）+ HF_ENDPOINT 镜像 + 硬件评估
- [x] 步骤3 后端 /api/system + scanner.models 收口到 model_assets
- [x] 步骤4 前端 AntD 5 + 单页骨架（Header/Anchor/四分区；删 router/pages/styles）
- [x] 步骤5 前端 client/types/hooks（useSystem/useModels 轮询/useConfigMeta）
- [x] 步骤6 DockerSection（容器表/镜像表/SSE 拉取进度）
- [x] 步骤7 ModelsSection（缓存路径/硬件结论红字/下载进度）
- [x] 步骤8 DepsSection（venv 路径头/按 Agent Collapse/白名单行级安装/安装提示列）
- [x] 步骤9 ConfigSection（password 密文眼睛/path 实时徽标防抖 400ms/bool Select/双 trim）
- [x] 步骤10 InstallOrchestrator（pip→docker→model 顺序 Modal 进度）+ build + 后端重启 + E2E
  - GET /api/install 白名单暴露（前后端单一数据源）

## 审计修复记录

轮 1: ① DepsSection 缺 install_hint 列 ② types ModelStatus 过时→ModelAsset[] ③ 下载失败静默→message.error ④ docker SSE 完成判断改用权威标志 __done__ exit_code
轮 2: ⑤ bool Select "0" 被 falsy 吞 ⑥ deps Tag 文案 ⑦ unused import
测试隔离追加: ⑧ test_integration/test_control 注入随机 CONTROL_PORT（沙箱孤儿探测曾收编并误杀生产 21845——第 6 个同类地雷）

## 测试终态

- pytest control: 47（API 层 14 + **E2E 无头浏览器 10** + 单元 23）
  - E2E: test_frontend_e2e.py（playwright chromium）——白屏回归断言/零 console 错误/
    四分区 DOM/路径存在性徽标真实交互链（输入→防抖→fs/check→徽标）
- 后端单元 53 + 集成 5 + Plugin TS 18 = **123 全通过**

## 白屏事故与补课（2026-08-15 用户反馈）

事故：用户打开 5173 白屏。根因：vite dev 运行中 npm install/uninstall 变更依赖
→ 旧进程预构建缓存失效 → 504 Outdated Optimize Dep → React 未挂载。
修复：重启 vite dev。

教训（已沉淀 knowledge id=687）：
- 前端"测试"只做 API 断言 = 没测前端。必须有无头浏览器渲染验证。
- fixture 已抽到 conftest.py（control_server session 级，API/E2E 共享沙箱实例）
- 依赖变更后必须重启 vite dev server

## 迭代 2（2026-08-15 用户反馈三问题）

1. **布局横向利用率** → 2 列网格（Docker|模型 / Python依赖|外部工具 / 配置通栏），maxWidth 1600
2. **数字对不上** →
   - 环境就绪 X/Y = 五类总和（外部工具+Python包+镜像+模型+配置），悬浮 Popover 逐类显示 X/Y + 缺失项名称
   - 一键安装 N = 可自动安装项（pip 包+镜像+硬件达标模型），悬浮显示将安装清单 + 无法自动安装清单（外部工具/conda/硬件不达标）；N=0 禁用（修复原"计数含不可装项→点击静默无效"bug）
3. **Python 依赖与工具混淆** → 彻底拆分：
   - 后端: tools_detector.py 新增 PYTHON_PACKAGES 清单（26 包，迁移自 detect_env.py 检测侧，同步注释）+ scan_python_packages()（importlib.metadata 查 venv）+ pip_installable_packages()
   - scan.global.python_packages 新字段（kind="python"）；install.py 白名单 = 可选包 ∪ pip_installable_packages()（单一数据源）
   - 前端: PythonDepsSection（包表：pip名/conda标记/版本/已装/安装按钮）+ ToolsSection（按 Agent 分组，无安装按钮只留提示）

测试: E2E 12（新增外部工具分离断言/就绪度悬浮明细断言/Python 真实包名断言）+ API 断言 python_packages
终态: **125 全通过**（pytest 49 + 单元 53 + 集成 5 + TS 18）

## 后续可优化（未做，记录）

- bundle 1.1MB 单 chunk → 可 code-split（本地控制台影响小）
- detect_env.py 与 tools_detector.PYTHON_PACKAGES 双清单同步（加包两边都加——已有注释标记）
