# progress — 配置分类 TAB + surface 模型（2026-09-30）

需求文档: 2026-09-30-config-surface-categories.md（同目录）

## Phase 记录

- [x] Phase 2 需求文档成稿（394 行，控制字节 0）
- [x] Phase 3 审计 3 轮（2 修 + 1 纯），4 问题全修：
  client.test.ts 随步骤6同步 / section-config 锚点保留 / 模板非目标 /
  Query 参数 Literal 化
- [x] Phase 4 执行计划确认（架构影响图见下）
- [x] Phase 4.5 跳过：本需求不触碰任何 agent prompt（纯控制台前后端）;
  新增文件全部落在既有目录模式内（sections/components/utils/constants）

## 架构影响图（>3 文件，Phase 4 要求）

```
backend/services/config_manager.py   [改] 枚举+DTO+清单重构 ←─ 唯一权威
  │                                     （.ai_env 读写/tunables 读取器不动）
  ├─→ backend/routes/config_route.py [改] meta surface 参数 + 写校验
  └─→ backend/routes/remote.py       [改] 删 PUT /config（唯一废除项）
backend/tests/{test_config_manager,test_control,test_api_guard}.py [改]

frontend/src/types/index.ts          [改] 契约类型
  └─→ api/client.ts                  [改] surface 参数化（-updateRemoteConfig）
        └─→ hooks/index.ts           [改] useConfigMeta(surface)
frontend/src/utils/configGrouping.ts (+test)   [新] 分组纯函数
frontend/src/constants/configIcons.ts          [新] 图标映射
frontend/src/components/ConfigFieldRow.tsx     [新] 共享行渲染 ←─ 复用
  ├─→ sections/ConfigPage.tsx       [新] 配置页（App 第四 TAB #/config）
  │      └─→ App.tsx                [改] 接线 + overview 摘要卡（保锚点）
  └─→ sections/RemoteSection.tsx    [改] 连接区 meta 驱动 + 调参只读卡
frontend/src/sections/ConfigSection.tsx        [删]
frontend/src/api/client.test.ts     [改]

不动: 插件(plugins/*) / GET /api/config 值接口 / required-status /
      远程动作端点(switch/status/health/node-config/autostart) /
      constants/categories.ts(readiness) / mcp-servers
依赖方向: 无新增跨层依赖; 前端新增文件均叶子化（无反向依赖）
```

## 步骤执行记录

- **步骤 1** ✅ 枚举+DTO+Keys 反思键纯增量
  验证: compile ✓ + pyright 0/0 + test_config_manager 5/5（标准跑法）
  （pytest 单跑的 1 error 为存量收集噪音——stash 对照证实与改动无关）
- **步骤 2** ✅ 字段替换+六清单重构+config_meta(surface)+GET /meta 适配
  验证: compile ✓ + pyright 0/0 + 语义冒烟（config 面 5 分类序
  tools→models→proxy→behavior→developer; remote 面 2 分类 9 条目;
  readonly/hidden 语义 ✓）
  实施: StrEnum 体内 _DESC 带注解被 3.13 收编为成员 → 改模块级私有映射
- **步骤 3** ✅ test_config_manager 断言更新（surface 过滤/分类序/readonly/
  未知键兜底仅 config 面/分类枚举 9 项全覆盖）
  验证: 5/5 绿
- **步骤 4** ✅ _guard_surface + PUT×2/DELETE surface 必填 + _after_write
  热重载钩子 + 废除 PUT /api/remote/config（含 RemoteConfigUpdate/
  ConfigUpdateResult 孤立 DTO 清零）
  验证: compile ✓ + pyright 0/0 + 残留 grep=0
  发现: 旧端点有 reload_config 热重载副作用——经 _after_write key 触发
  钩子保留（同 invalidate_deps_snapshot 模式），需求文档已回填
- **步骤 5** ✅ E2E 用例: meta 契约重写（surface 必填/分类内嵌/hidden 键
  不返回）+ 新增写校验用例（跨面/readonly/hidden/未声明/ENABLED 文案）+
  热重载用例改走通用接口 + 存量 PUT/DELETE 用例补 surface 参数
  验证: test_control 94/94 + test_api_guard 4/4 + test_remote_routes 5/5

- **步骤 6** ✅ 前端契约同步（types/client/hooks/ConfigSection 最小适配/
  client.test surface 断言 + delete 替身签名修复——真实 axios delete(url,cfg)
  支持第二参数）
  联动消费方: useAllConfig(surface) 参数化 + RemoteSection 写路径最小迁移
  （旧端点已废，先改调用保编译）
  验证: tsc 0 + vitest 31/31
- **步骤 7** ✅ ConfigFieldRow（差异化渲染+readonly 态+PathCheckBadge 迁入）
  + configGrouping 纯函数（+5 测试）+ configIcons 图标映射
  验证: tsc 0 + vitest 36/36
- **步骤 8** ✅ ConfigPage（侧栏/胶囊分类导航+卡片+sticky 保存）+ App 第四
  TAB #/config + overview 配置卡→摘要+跳转（保 section-config 锚点）+ 删
  ConfigSection + global.css 导航样式
  **发现并修复步骤内缺陷**: doSave 发全量 values（GET /api/config 含其他
  surface 键）会被服务端 422 → 抽 writableUpdates 共享纯函数（本页面+非
  readonly 键过滤，服务端校验的前端镜像）+ 测试
  验证: tsc 0 + vitest 37/37 + npm run build ✓
- **步骤 9** ✅ RemoteSection: 连接区 meta 驱动（URL/TOKEN 可写+ENABLED
  只读行，save 走通用接口+过滤）+ 远程调参只读卡（remote_tuning 6 项）;
  删 url/token 临时态与"（已配置）"占位 hack
  验证: tsc 0 + vitest 37/37 + build ✓
- **步骤 10** ✅ 契约测试已在步骤 6/7 落地（client.test 14 用例含 3 新契约
  + writableUpdates）; 验证: vitest 37/37
- **步骤 11** ✅ 全量终验:
  - pyright backend 0/0 + mcp-servers 0/0（修 test_config_manager 一处
    Optional 访问）
  - 后端家族: control 94 + proxy 批 60（proxy_mcp 需 IPC 指向活控制台——
    存量环境依赖）+ oop 6 + remote_link 9 + config_manager 5 +
    model_lifecycle 14 + integration 6 + api_guard 4 + remote_client 8 +
    remote_routes 5 + **e2e_real 6/6** + **e2e_remote 全过**（E2E_REMOTE=1）
  - 前端: tsc 0 + vitest 37/37
  - live（控制台 pid 16110 新代码）: 缺 surface 422 / hidden 422 /
    config 面 5 分类序+反思键默认 30 / remote 面 9 条目 readonly /
    跨面写 422 / readonly 写 422 / ENABLED 专用文案 / 反思键写 roundtrip
    落盘 .ai_env ✓ / vite dev 服务新页面 ✓
  - hidden 残存精准 grep 前后端=0; 存活文档/插件对旧名（tunable_configs/
    remote_tab_configs/updateRemoteConfig/旧端点）零引用
  - 事件: 原控制台已死 → 手动按插件 spawn 契约拉起（server.py + 最小环境
    + 日志落盘），opencode 心跳已接管
