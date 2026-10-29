# 进度: 手机端定制 TTS 引擎与混合朗读

> 需求文档: `.opencode/requirements/evolve/2026-10-19-mobile-custom-tts.md`
> 目标仓库: `/Users/aserlili/Documents/Codes/legado-with-MD3`（分支 main）
> 构建: `export JAVA_HOME=/Library/Java/JavaVirtualMachines/jdk-21.0.12.jdk/Contents/Home`

## 执行记录

| 步骤 | 状态 | 说明 |
|---|---|---|
| 1. 启动容错与资源释放 | ✅ 完成 | ConfigStore runCatching / startInternal try-catch+lastError / P2pClient.close+isClosed；编译过 |
| 2. 请求级超时 | ✅ 完成 | DEFAULT_API_TIMEOUT_MS=95_000；request(timeoutMs=...)；awaitResponse 显式传参；编译过 |
| 3. TtsClient seam | ✅ 完成 | 新增 transport/TtsClient.kt；P2pClient 实现之（session 字段合并、SessionFactory 注入）；LocalTtsGateway 依赖 TtsClient；编译过 |
| 4. 网关参数扩展 | ✅ 完成 | GatewayParams parse/toJson（5 参数）；/voices 透传；缺 text→400；编译过 |
| 5A/5B/6A/6B. 测试 | ✅ 完成 | 61 用例全绿（协议负向/边界/状态机/网关/ConfigStore） |
| 7A/7B. CI | ✅ 完成 | 主验证集加入 remote-link + custom-tts 测试任务 |
| 8-13. custom-tts 模块 | ✅ 完成 | 模块骨架 + 分段器（12 组 TS 向量逐段一致）+ 参数校验 + HybridTtsPolicy；41 用例 |
| 14-16. 数据与配置 | ✅ 完成 | Settings/Repository（JSON 文件，容错回退）+ Catalog（引擎/音色同步、/voices 拉取）+ 合成参数注入（URL builder/缓存键）；提交 37fb26ec0 |
| 17A-22. 配置界面 | ✅ 完成 | Feature(CustomTts Contract/VM/Route/Screen) + 连接/音色/参数/试听/混合/分段 + CloudTts 入口；提交 5b07cd365 |
| 23-26. 混合朗读 | ✅ 完成 | HybridChapterBuilder（偏移映射）+ Coordinator（段级赛跑）+ HttpReadAloudService 混合分支 + 兜底分派（系统/HTTP/云）+ 网关未运行回退；提交 f1f040ad2 |
| 27-28. 验收 | ✅ 完成 | 全量验证通过 + 交付说明（见下） |

## 外部 Review 修复批（第二轮验收）
已修复（高/中/低全量）：
- 高: 混合合成落主线程（ANR）→ coordinator 全部合成走 IO dispatcher（含兜底超时 15s）
- 高: 配置保存时网关 stop 等 P2P 请求锁（最长 95s 主线程卡死）→ P2pClient.close 不再取请求锁 + restart 移到 IO
- 中: 流式播放缓存键漏参数 → 传 sourceKey（与预合成/非流式一致）
- 中: 混合模式位置表未替换导致 nextP/prevP/seek 错位 → Base 暴露 replacePlaybackUnits，同步段级位置表
- 中: 10s 超时未透传 P2P → 网关支持 `timeout_ms`（请求级超时），CustomTtsUrlBuilder/getSpeakStream 全链路传递
- 中: 远端合成半截文件 → 临时文件 + rename 原子写
- 中: settings Flow 回写覆盖页面草稿 → 首次全量、后续仅合并音色参数
- 中: 测试缺口 → 新增 CustomTtsViewModelTest(5)、网关 timeout 用例(2)、偏移精确断言+缩进用例(2)
- 低: 兜底音色首开为空（首个 settings 应用后加载）；PSK/首段字数保存校验；Repository IO 写+失败抛出；重新配置音色恢复 enabled；试听携带未保存草稿参数；不可用音色按钮禁用；死代码清理（EngineRef/policy 空方法）

已知差异（记录，不修）：
- 混合模式不朗读章节标题（普通路径有标题段；需求未要求）
- 配置页中文文案暂为硬编码（Compose 文本，后续可资源化）
- 云兜底需该音色已在云 TTS 页创建（否则该段降级无声）

## 最终验证结果（2026-10-19）
- `:modules:remote-link:testDebugUnitTest` → **63 tests / 0 failures**
- `:modules:custom-tts:testDebugUnitTest` → **47 tests / 0 failures**
- `testAppDebugUnitTest` → 全量通过（含新增 ViewModel 测试）
- `verifyConfigArchitecture` / `lintAppDebug` / `assembleAppDebug` → BUILD SUCCESSFUL
- `git diff --check` 无输出；工作区干净

## 提交链（legado-with-MD3 main，全部已推送）
- `a7de62121` remote-link 质量加固
- `ec2cc044c` custom-tts 模块（分段器/参数/策略）
- `37fb26ec0` 数据层与合成参数注入
- `5b07cd365` 配置界面（Feature-first）
- `f1f040ad2` 混合朗读（段级赛跑 + 兜底分派）
- `5c402233c` 审计修复（停用开关/Slider/段间隔）
- `8d32429b4` 外部 Review 修复批（IO dispatcher/超时透传/流式缓存键/replacePlaybackUnits/原子写/settings 合并等 15 项；remote-link 63 + custom-tts 47 + app 1490 tests）

## 真机冒烟清单（安装 APP 后逐项）
1. 设置页 → RemoteLink 配置（或「引擎与音色」→ 定制引擎）：填 relay 地址/端口/PSK/节点 → 保存并启用 → 测试连接显示"已连通"
2. 配置页 → 音色 → 刷新目录（应看到服务端音色）→ 选一个音色 → 参数（速度/指令/种子/模式）→ 试听有声
3. 设为默认音色 → 保存并应用
4. 「朗读引擎与音色」页 → 定制引擎分组存在 → 点击进入配置页
5. 选择定制引擎朗读：首段（默认 20 字）应立即由兜底引擎出声；后续段远程就绪后自动切用远程（Toast"已恢复定制引擎"）
6. 断网（或停服务端）：当段起自动兜底，朗读不中断（Toast"已切换为兜底引擎"）；恢复后自动切回
7. 兜底速度/定制速度分别调整 → 效果可分辨
8. 暂停/恢复/翻章/停止：无崩溃、无错位（重点检查进度与高亮）
9. 关闭"首段兜底"开关：首段不强制兜底（远程未就绪仍会降级兜底）

## 阶段 D/E 已完成要点
- 配置页：连接（ConfigStore+测试连接）/音色目录（/voices 经网关）/参数 BottomSheet（速度/指令/种子/模式）/试听（MediaPlayer）/混合配置/分段设置/保存并应用
- 混合模式：contentList 替换为分段单元 + playbackQueue 置空；updateNextPos 混合分支按 hybridChapterPositions 推进；upPlayPos 跳过章节标题判断
- 兜底：系统 TTS（speechRate=fallbackSpeed）/ HTTP（fallbackSpeed→0..80 刻度）/ 云（音色 traits）；失败→无声
- 引擎选择：定制引擎+网关未运行 → 回退系统 TTS

## 待办风险记录
- 混合模式下 nextParagraph/prevParagraph 的段级跳转沿用 contentList 逻辑（可能有小漂移，待真机验证）
- 云兜底音色需在 read_aloud_voices 中存在（配置页只能试听/选择，云音色需先在云 TTS 页创建）
- Slider 使用旧 API（deprecation warning，不阻塞）
- 配置页中文文案暂为硬编码（Compose 文本，非 lint 错误）
- 后续小改进：`TtsClient.request` 返回裸 `Triple<Int, String, Any?>`（沿袭 `P2pClient.request` 形状的取舍）——可换 `data class TtsResponse(statusCode, contentType, body)` 消除按位置解构

## 重要修复记录（阶段 A）
- **P2pClient.api.req body 语义 bug**：原实现把 JSON 文本字节当 msgpack 解析（`Msg.decode`）→ 必然抛"消息必须为 map"，手机端链路从未打通。已改为结构化 map（Python 端 `json=dict` 语义），网关参数/响应双形态兼容。
- ConfigStore 非法 PSK / 网关端口占用 → App 启动崩溃风险已消除。
- 客户端超时 30s → 95s（> 服务端 90s）；新增请求级 timeoutMs。

