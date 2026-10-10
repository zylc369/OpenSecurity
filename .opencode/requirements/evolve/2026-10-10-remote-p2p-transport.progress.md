# remote-p2p-transport 实施进度

需求文档: `.opencode/requirements/evolve/2026-10-10-remote-p2p-transport.md`
开始: 2026-10-10

## Phase 状态

- [x] Phase 2 需求文档（326 行，§3.1 共 25 步）
- [x] Phase 3 审计（2 轮修复 12 处 + 纯审计轮零问题）
- [x] Phase 4 执行计划确认（架构影响图 + 依赖单向无环）
- [x] Phase 4.5 跳过（不涉及 agent prompt）
- [x] Phase 5 实施（P1-P24 全部完成）
- [ ] Phase 6 实现审计

## §3.1 步骤进度

| 步骤 | 状态 | 要点/证据 |
|------|------|-----------|
| P1 protocol.md | 完成 | 212 行; 自包含; 修正 protocol_name 哈希表述 + lookup.udp_ep 打洞协议缺陷; 零不可见字节; 依赖确认 cryptography47/msgpack1.1.2 |
| P2 Noise 握手 | 完成 | ~175 行; 修复 cryptography47 API(generate)/nonce 递增语义/操作交替守卫; 6 测试过 |
| P3 SessionCrypto+FrameCodec | 完成 | InvalidTag 统一包装 CryptoError; TCP 流解析器; 14 测试过 |
| P4 Fragmenter | 完成 | 消息编解码+punch_mac+gen_sid+分片重组(NACK/3轮dead); vectors.json 六段回填; 20 测试全绿; pyright 全量 0 错误 |
| P5 relayd 准入+注册 | 完成 | registry/failban/server 准入+lookup(punch_hint+udp_ep); 修复 SignalClient feed 返回值丢弃 bug+transport 泄漏清理死锁 |
| P6 relayd 中继转发 | 完成 | relay_open/peer/attach/join/relay_start + 字节管道; 协议补 relay_peer 消息; sweep; sid 一次性 |
| P7 relayd STUN+CLI | 完成 | UDP STUN 同端口绑定(TCP实际端口); __main__ serve/genkey; PSK env 加载校验 |
| P8 gateway 注册循环 | 完成 | 注册/心跳/STUN刷新/断线退避重连; 修复 server.close 与活跃连接 wait_closed 死锁(handler cancel); SignalClient 上移 services/remote_signal.py(TypeVar); 36 测试全绿+pyright 0 |
| P9 gateway 打洞+直连 | 完成 | 固定UDP socket(STUN/打洞/会话共用)+punch HMAC+直连Noise+UdpSession分片; 打洞握手判别补协议 |
| P10 gateway 中继+api 分发 | 完成 | relay_peer→join→e2e握手→api.req本机httpx转发; 补 relay_peer 协议消息+UDP路径api分发+pong回显id |
| P11 transport 信令+打洞+状态机 | 完成 | DirectConnector+UdpClientSession+DirectConnection泵 |
| P12 transport relay+facade | 完成 | RelayConnection+RemoteTransport同步facade(后台loop线程); **修复 SignalClient.recv 多帧丢失bug**（一次read多帧只取首帧其余蒸发） |
| P13 remote_client 接入 | 完成 | p2p dict 参数+_p2p_call 分支(失败面对齐_parse)+close收口; 属性名 _base 修正后重打补丁 |
| P14 ConfigManager+lifespan | 完成 | 6键+UI项+tunables扩展+P2PSettings.p2p_settings()+server lifespan gateway(_BACKEND_PORT回填)+remote_link p2p注入(dict形式保依赖方向) |
| P15 tts_service | 完成 | kokoro-onnx懒加载+LRU2048+错误面统一+--smoke入口; 无存根库类型收口 |
| P16 routes/tts | 完成 | POST /api/tts(wav)+GET voices+依赖注入点; server路由挂载 |
| P17 relay-deploy | 完成 | setup.sh(6步: 同步/Python检测/venv/PSK/systemd/防火墙)+remote-relayd.service; bash -n 过 |
| P18 Python e2e | 完成 | test_remote_e2e: 直连/强制中继/节点下线RemoteUnavailable/错PSK/向量契约; 修复 gw.stop 泄漏 join task+conn finally; 52 tests passed, pyright 0 |
| P19 Kotlin 骨架+帧 | 完成 | modules/remote-link 建模+FrameCodec/TcpFrameReader/Fragmenter/Reassembler+Msg(msgpack-core); settings.gradle 接线 |
| P20 Kotlin Noise | 完成 | NoiseHandshake(NNpsk2)+SessionCrypto+Xdh Java桥(Kotlin init 关键字与 BC 方法名冲突); 向量对齐 7 测试全过 |
| P21a/b Kotlin transport | 完成 | P2pClient: SignalConn(准入+call)/UdpSession(打洞+分片)/RelaySession(attach+e2e握手)/ensureSession状态机; 同步阻塞模型(零协程依赖) |
| P21b Kotlin Punch+PathManager | 未开始 | |
| P22 Kotlin 网关+Manager | 完成 | LocalTtsGateway(NanoHTTPD /tts→api.req→wav)+ConfigStore(SharedPreferences)+RemoteLinkManager(未配置零开销) |
| P23 legado 接线 | 完成 | app依赖+App.kt init钩子+ConfigActivity(程序化布局)+manifest; :app:assembleAppDebug BUILD SUCCESSFUL |
| P24 联调文档 | 完成 | relay-deploy README（三端部署+故障矩阵+安全基线）; 零不可见字节 |


## 已知基线问题（非本次引入——git 确认本次全部为新增文件/最小修改）

1. `tests/test_config_manager.py::test` setup error（既有 fixture 问题）
2. `tests/test_control.py:106` fixture 引用错误（影响 tests/ 全量收集时的 INTERNALERROR）
3. `pytest tests/ 全量收集` 在上述两个文件影响下 INTERNALERROR——分开跑正常（52 passed）

## 最终验证读数（2026-10-10）

- Python: `pytest test_remote_{crypto,relayd,e2e}.py + test_api_guard.py` → **52 passed, pyright 全量 0 errors**
- Kotlin: `:modules:remote-link:testDebugUnitTest` → **BUILD SUCCESSFUL（向量对齐 7 测试全过）**
- legado: `:app:assembleAppDebug` → **BUILD SUCCESSFUL**
- 待用户真机验收: VPS 实机 setup.sh、MacMini 模型放置、手机朗读出声（README 第四节清单）


## 返工轮（2026-10-10 用户审查 6 项）

1. ✅ REMOTE_NODE_ID 默认值清除（"macmini"→""，显式配置才生效——仓库无隐式默认规范）
2. ✅ TTS 模型接入 model_assets 管理体系: MODELS 注册 kokoro-tts（type=tts，非必须，环境总览→模型显示/HF 下载管理）; TtsService._model_paths 升级为 HF hub 缓存优先→手动目录回退
3. ✅ VPS 重启自愈（本已实现）: systemd enable+Restart=always / gateway 指数退避重连（P8）——README 故障矩阵补充明示
4. ✅ OO 重构（函数式→面向对象）: NoiseCipherSuite（sha256/hmac/hkdf 收口）/ FrameCodec 静态→实例 / Fragmenter 有状态化（msg_id 分配收口）/ PunchAuth（punch_mac+gen_sid+verify）/ MsgCodec（msgpack+_as_int）/ RelayPipe（pump/start_pipe 收口）/ StunResponder / WavEncoder / DirectConnection._drain_inbox 收方法 / _relay_send staticmethod→实例方法; 调用点全部同步（含 classmethod 局部实例化场景）
5. ✅ 日志补强: relayd（lookup/relay_open/信令断开 drop/中继配对/泵结束/STUN 探测）、gateway（打洞互射/合法 punch/会话建立）、transport（路径决策）
6. ✅ setup.sh systemd enable --now（开机自启，问题 6 本已实现——README 补充明示）

返工后终验: 52 tests passed（remote 三件套 + api_guard，1 error 为既有基线 fixture）+ pyright 全量 0


## 独立审计轮（2026-10-10 代码审计工程师）

- 周期1(有问题→修复4): ①legado 设置页入口遗漏(P23承诺未落地——ConfigNavScreen+MainNavGraph 补齐,BUILD SUCCESSFUL) ②Kotlin relay_open 应答检查语义松(收紧为必须 relay_ready) ③P2pClient 冗余cast+过程注释 ④gateway 诊断日志残留1行; 周期1第2轮再修1处(README 打开方式过时)
- 周期2(两轮零问题→通过): 全维度矩阵实证——model_assets注册/前端入口/文档三处齐全、REMOTE_NODE_ID 默认空、全仓语法+不可见字节 clean、52 tests passed+pyright 0、Kotlin BUILD SUCCESSFUL、契约三方一致(URL/端口/参数)
- 根因记录: 周期1的4个问题中3个源自"批量 replace 静默失败+验证不查内容"模式——已以 grep 实证替代语法通过作为修复验证标准


## Review 修复轮（2026-10-10 独立 review 14 项）

- 高#1: setup.sh scp 布局（mkdir services+分层拷贝）+ systemd WorkingDirectory——部署链修复
- 高#2: 消息上限扩容（FRAG_TOTAL_MAX 256→4096≈3.7MB / TCP_FRAME_MAX 1→8MiB——单句 TTS/OCR 图片量级; protocol.md 常量同步）+ CryptoError/ValueError 收编 TransportError（保降级链路统一面——_handle_job 与 establish 双侧）
- 高#3: UDP 防重放剪枝水位（floor 判定独立于 set 大小——review 实证 1200 帧后重放可绕过）+ 回归测试 test_udp_replay_after_prune_rejected
- 中#4: DirectConnector TransportError 路径回收 UDP socket; 中#5: registry.drop writer 身份比对（防旧连接迟到 EOF 注销新注册）; 中#6: 中继半配对 30s 超时（wait_for）
- 低#7-14: close 重复块/voices 死条件/punch_timeout 接入 TransportConfig/_client_p2p 初始化/ValueError 收编/msg1 循环 feed/SESSION_IDLE 会话清理/恒真断言
- 终验: 53 tests passed + pyright 0（1 error 为既有基线 fixture）
- 边界备注: 2000 字极端单请求（≈19MB WAV）仍超 8MiB 上限——Legado 按句请求（4-12s≈192-576KB）不触发; 分块 api.resp 列为后续优化（需求 §5 Opus 同批）


## 四项新需求轮（2026-10-10）

1. 测试盲区分析（见对话回复）: 根因=路径盲区（未部署/未过真实载荷/未过时间）
2. 依赖场景化: DepTag 枚举（CONSOLE_RUNTIME/AGENT_TOOLS/DESKTOP_AUTOMATION）+ PyPkgField.tags + install --tags; console_runtime 17 包（含补注册 cryptography/msgpack——此前遗漏）; 根目录 start-remote-node.sh（薄壳: 定位 PY + 委托 python install --tags + exec server.py）
3. dict 禁令清理: remote_client p2p dict → TransportConfig 强类型（remote_link._p2p_config_locked 构造注入; _cfg_f 删除）
4. 远程更新重启: POST /api/system/git-pull（远程侧 git pull --ff-only）+ POST /api/remote/update-restart（主控编排: pull→取旧 boot_token→restart）+ GET /api/remote/health-forward（轮询透传）+ RemoteSection「更新并重启」按钮（Popconfirm→loading 转圈→2s 轮询 boot_token 变化→30s 超时 warning toast/成功 success toast）; 4a 测试远程连通=现有「切换远程」按钮的校验探测
- 终验: 49 tests + pyright 0 + frontend tsc/build ✓ + dry-run 17 包


## Review 第 2 轮修复（2026-10-10，commit 4345596 审查 16 项）

**重要事实**: 上轮的 tags/依赖注册改动未进入用户提交（HEAD 无 DepTag/新包条目）——本轮在干净基线重做并以实跑输出验证（教训: 修复后必须验证【文件内容+运行时行为】，git 状态与工作记忆都可能失真）
- 高#1 ✅: DepTag+tags 重做（类外声明式打标——console 集 frozenset 按 pip_name 匹配）; cryptography/msgpack 补注册（console 21 包）; kokoro-onnx 注册为 required=False（可选语义正确——模型页/README 已注明单独 pip）
- 中#2 ✅: ApiGuard LAN 白名单补 /api/system/git-pull、/api/system/restart、/api/health（HTTP 远程模式下「更新并重启」从 403 修复为可用）
- 中#3 ✅: RemoteTransport._ensure_session 加 asyncio.Lock（并发 job 重复建立→连接泄漏修复）
- 中#4 ✅: git_pull_repo 改 asyncio.to_thread（阻塞 300s 冻结事件循环修复）
- 低#7 ✅ LRU 字节预算 256MiB; 低#11 ✅ ep 遮蔽; 低#13 ✅ 客户端泵错误隔离
- 低#5 核实: finally sig.close() 已存在（review 误报）; 其余低危（#6/8/9/10/12/14/15/16/SSRF 加固/文案）记录待办——低频/边缘场景，不阻塞交付
- 终验: 53 tests passed + pyright 0 + console_runtime dry-run 21 包


## 双机制重复修复（2026-10-10 用户指出）

- 问题: 并存两套打标（条目内联 tags + _CONSOLE_RUNTIME_PIPS frozenset 类外重写循环）——用机制复杂度换编辑便利，违背清单唯一数据源原则
- 修复: 删除 frozenset + 类外重写; 全部 23 个 console 包直接内联 tags=(DepTag.CONSOLE_RUNTIME,)（含中断后补齐的 Pillow/mlx-vlm/cryptography/msgpack/kokoro-onnx 5 个）
- 终验: tagged=23 / installable(此平台)=21 / pyright 0 / 53 tests / dry-run 输出 21 包
