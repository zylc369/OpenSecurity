# 控制台前端重设计（单页管理 + AntD 5 + 三层一键安装）

日期: 2026-08-15
状态: 已确认（用户拍板：AntD 5 / 布局 A 单页锚点 / 硬件顶栏 Popover / 5 个新 API / HF 匿名下载 + 镜像兜底）

## §1 背景与目标

来源: 用户对前端 v1 的复盘反馈。v1 是 5 个路由页（总览/依赖/Docker/硬件/配置）+ 手写 CSS，痛点：

1. 屏幕利用率低（大标题横幅、卡片间距大、表格不满宽）
2. 重点不突出：Docker/模型/依赖/配置平铺在不同页面，来回跳转
3. 缺一键安装：装个依赖要去后端日志看结果，装模型没有入口
4. 秘钥明文显示、路径配错不知道（空格问题不可见）、模型硬件门槛无提示
5. 无组件库，手写 CSS 维护成本高

预期收益（四维度量）:
- 减少上下文: 页面分区导航直达（锚点），无页面切换
- 减少轮次: 三层一键安装（行/卡片/整页）把 N 次人工操作收为 1 次
- 提升速度: 缺失项计数在顶栏和锚点上实时可见，判断环境状态零点击
- 提升准确度: 服务端+前端双 trim、路径存在性实时校验、模型硬件适配结论

## §2 技术方案

### 2.1 后端新增

**routes/system.py** — `GET /api/system`：
```python
{
  "venv_path": "~/.bw-security-analysis/.venv",   # 实际绝对路径
  "venv_python": ".../bin/python",
  "python_version": "3.13.x",
  "hf_cache_dir": "~/.cache/huggingface",
  "hf_endpoint": "https://huggingface.co",        # 或 hf-mirror.com
  "control_pid": 89098,
  "dev_mode": true
}
```

**services/model_assets.py** — 模型资产单一数据源（收口：scan.models 也从这里取）：
```python
MODELS = [
  {"id": "bge-m3", "repo_id": "BAAI/bge-m3", "type": "embedder",
   "display": "BGE-M3", "purpose": "向量化（知识库/事件图谱）",
   "min_free_gb": 4,   # 加载所需可用内存下限
   "disk_gb": 4.3},    # 磁盘占用参考值
  {"id": "bge-reranker-v2-m3", "repo_id": "BAAI/bge-reranker-v2-m3", "type": "reranker",
   "display": "BGE Reranker v2 m3", "purpose": "重排序（事件检索）",
   "min_free_gb": 4, "disk_gb": 2.2},
]
# get_model_assets() -> list[dict]  # 含 cached/cache_path/size_on_disk/loaded/hardware{ok,reasons}/download{status,progress,error}
# start_download(model_id) -> bool  # 后台线程 snapshot_download（HF_ENDPOINT 环境变量生效）
```
- cached 判定: `huggingface_hub.scan_cache_dir()` 或 try_to_load_from_cache
- 进度: 后台线程更新全局 dict；progress = size_on_disk/disk_gb（近似，轮询）
- 硬件评估: `psutil.virtual_memory().available >= min_free_gb`；Apple Silicon 标注 Metal
- scan.models 改为调 `get_model_assets()`（消灭 scanner 里的重复定义）

**routes/models.py**：
- `GET /api/models` → `{"models": [...], "hf_endpoint": "..."}`（含下载状态）
- `POST /api/models/{model_id}/download` → 启动后台下载（幂等：已在下载中返回 ok）

**routes/fs.py** — `GET /api/fs/check?path=`：
```python
{"path": "...", "exists": true, "is_dir": false, "resolved": "expanduser 后的路径"}
```
仅本机 127.0.0.1 监听（已有约束），无额外白名单。

**config meta** — `GET /api/config/meta`（挂在 config_route.py）：
```python
{"DEEPSEEK_API_KEY": {"label": "...", "type": "password", "hint": "...", "required": true},
 "DEEPSEEK_MODEL": {"label": "DeepSeek 模型", "type": "text", "hint": "", "required": false}, ...}
```
- REQUIRED_CONFIGS 里的键：直接取 ConfigField（label/type/hint/required）
- 其余键（.ai_env 有但不在 REQUIRED_CONFIGS）: 内置元数据表 EXTRA_CONFIG_META 补充（DEEPSEEK_MODEL/CONTROL_FRONTEND_DEV/RESUME_ANALYSIS_ENABLED...），缺省 `{"type": "text", "required": false, "label": key}`
- type 枚举: password / path / text / bool（与 ConfigField 一致）

**PUT trim** — config_store.write/write_one 入口处 `value.strip()`（服务端兜底，前端也 trim）。

### 2.2 前端重写（frontend/src）

技术栈: React 18 + **antd@^5** + @ant-design/icons@^5，移除 react-router-dom。

结构（布局 A: 单页 + sticky 锚点）：
```
main.tsx          — ConfigProvider(zhCN, 紧凑主题) + App
App.tsx           — Layout: Header(常驻) + Anchor(sticky) + 分区卡片 + BackTop
api/client.ts     — 新增 getSystem/getModels/downloadModel/fsCheck/getConfigMeta
hooks/            — useScan/useConfigMeta/useModels/useSystem/useHardware/useHardwareAssessment
sections/
  DockerSection.tsx    — 容器表 + 镜像表 + SSE 拉取进度
  ModelsSection.tsx    — 模型卡: 缓存路径/大小/硬件适配结论/下载按钮+进度
  DepsSection.tsx      — venv 路径头 + 按 Agent 分组的依赖表 + 行级安装
  ConfigSection.tsx    — meta 驱动: password→Input.Password(自带眼睛)/path→存在性徽标/text
InstallOrchestrator.tsx — 整页一键安装（顺序执行 pip→docker→models，Modal 进度+日志）
```

删除: pages/StatusPage|DepsPage|DockerPage|HardwarePage|ConfigPage、components/RequiredConfigBanner、react-router 依赖、旧 styles.css（AntD 接管）。

### 2.3 三层一键安装语义

- 行级: 表格行内按钮（单包装白名单 / 单镜像 pull / 单模型下载）
- 卡片级: 每分区标题右侧按钮（该分区全部缺失项）
- 整页: 顶栏主按钮（pip 缺失包 → docker 缺失镜像 → 未缓存模型，顺序执行，Modal 显示逐项结果）

## §3 实现规范

- 后端遵守现有分层: routes 薄、逻辑在 services
- 前端所有 API 调用收口 api/client.ts；类型收口 types/index.ts
- 后端下载线程 daemon=True；全局状态 dict 带 lock
- 禁止降级: 模型下载失败在 UI 显式红色错误 + HF_ENDPOINT 镜像提示
- 测试沙箱铁律: 所有新测试 DATA_DIR→tmp；不碰生产 .ai_env / 端口文件

### §3.1 实施步骤

1. 后端: routes/fs.py + config meta + write trim
   - 文件: routes/fs.py(新)、routes/config_route.py、services/config_store.py、server.py(注册)、config.py(EXTRA_CONFIG_META)
   - 预估行数: ~120
   - 验证点: curl /api/fs/check 与 /api/config/meta 返回结构正确；PUT 值带空格写入后无空格（沙箱 .ai_env）
2. 后端: services/model_assets.py + routes/models.py
   - 文件: services/model_assets.py(新)、routes/models.py(新)、server.py(注册)
   - 预估行数: ~180
   - 验证点: GET /api/models 返回 cached=true(生产已缓存) + 硬件结论；POST download 幂等（重复 POST 不报错）
3. 后端: routes/system.py + scanner.models 收口
   - 文件: routes/system.py(新)、services/scanner.py、server.py(注册)
   - 预估行数: ~70
   - 验证点: GET /api/system 返回 venv/hf_cache/pid；/api/scan 的 models 与 /api/models 同源（字段一致）
4. 前端: AntD 安装 + 布局骨架（main/App/styles）
   - 文件: package.json、main.tsx、App.tsx、styles.css(删)、pages/*(删)、components/RequiredConfigBanner(删)
   - 预估行数: ~180
   - 验证点: vite dev 编译零错误；Header+硬件Popover+Anchor+四分区占位渲染；zh_CN 生效
5. 前端: client.ts + types + hooks 扩展
   - 文件: api/client.ts、types/index.ts、hooks/index.ts
   - 预估行数: ~150
   - 验证点: tsc 零错误；hooks 拉到真实数据（console 可见）
6. 前端: DockerSection
   - 文件: sections/DockerSection.tsx
   - 预估行数: ~150
   - 验证点: 容器/镜像表渲染生产数据；pull SSE 进度条动
7. 前端: ModelsSection
   - 文件: sections/ModelsSection.tsx
   - 预估行数: ~150
   - 验证点: 模型卡显示缓存路径/大小/硬件结论；点下载触发后端并可轮询进度
8. 前端: DepsSection
   - 文件: sections/DepsSection.tsx
   - 预估行数: ~180
   - 验证点: venv 路径显示；按 Agent 分组表 + 行级安装按钮（白名单内）
9. 前端: ConfigSection
   - 文件: sections/ConfigSection.tsx
   - 预估行数: ~200
   - 验证点: 秘钥默认密文+眼睛；路径输入防抖调 fs/check 显绿/红徽标；保存前后端均 trim
10. 前端: InstallOrchestrator + 构建 + 后端重启 + E2E
    - 文件: sections/InstallOrchestrator.tsx、App.tsx(集成)、test/control/test_frontend.py(扩展)
    - 预估行数: ~200
    - 验证点: npm run build 成功；后端重启后新 API 全 200；整页安装 Modal 顺序执行；全部测试通过

## §4 验收标准

功能验收:
- 单页四分区 + 顶栏硬件 Popover + 锚点导航（各分区缺失计数）
- 行/卡片/整页三层一键安装可用，整页安装有 Modal 进度
- 模型卡: 缓存路径/磁盘占用/硬件适配结论（不达标红字）/下载+进度
- 秘钥默认密文 + 小眼睛；路径配置实时存在性徽标；保存双 trim
- Python 依赖分区标题含 venv 路径；卡片名"Python 依赖"

回归验收:
- 既有 108 测试全通过（pytest 32 + backend 53 + integration 5 + TS 18）
- test_frontend.py 扩展新 API 断言
- 生产控制台重启后 MCP 自愈正常（embed/rerank 可调）

架构验收:
- scan.models 与 /api/models 单一数据源（model_assets）
- API 调用/类型收口不破坏；无 docs/ 引用；测试零生产污染

## §5 与现有需求文档的关系

- `2026-07-28-opencode-control.md`（控制台初建）的前端部分由本文档迭代升级
- `progress-2026-07-28-opencode-control.md` 记录进度，本文档完成后追加 progress-2026-08-15
- 端口文件孤儿探测修复（2026-08-15 会话）不受影响；后端重启走既有 SIGTERM+自愈链路
