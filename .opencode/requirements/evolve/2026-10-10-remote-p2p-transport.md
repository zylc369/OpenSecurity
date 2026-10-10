# remote 链路 P2P 传输（打洞直连 + 中继兜底 + 远端 TTS）

日期: 2026-10-10
状态: 已确认待实施

## §1 背景与目标

**来源痛点**: 模型远程化一期（`remote_link.py` / `remote_client.py`）的传输层是纯 HTTP——主控侧必须能直连远程节点的 URL。远程节点（Mac Mini）位于家庭宽带 NAT 后（CGNAT，无公网 IPv4，不使用 IPv6），现有 HTTP 传输在广域网根本不可达，远程模型能力被限制在局域网。同时手机端阅读 App（legado）需要远程 TTS 朗读，同样受此约束。

**目标**:
1. 为 remote 链路新增传输路径: **UDP 打洞直连（常态，流量不过 VPS）+ VPS 中继 TCP（兜底）+ 局域网 HTTP（现状保留）**，路径自动探测与切换
2. 三端统一方案: 控制台 backend（Python，客户端角色）、Mac Mini backend（Python，网关角色，同款代码第二部署形态）、legado（Kotlin SDK，先在 `modules/remote-link` 开发、稳定后抽 `sdk/Android/remote-link`）
3. VPS（搬瓦工 2C/1GB）上 `remote_relayd` 守护: 信令 + STUN + 字节中继，systemd 裸进程（无 Docker / 无 nginx）
4. 远端角色新增 TTS 服务（kokoro-onnx + LRU 缓存），legado 经同一传输调用
5. 全链路加密: Noise NNpsk2（PSK 认证 + 前向保密），无域名无证书，VPS 零知识（只见密文）

**预期收益**:
- Mac Mini 无任何公网可达地址时，控制台远程模型与手机 TTS 均可用（直连优先，中继兜底）
- 常态流量端到端（打洞成功后 VPS 零流量），中继仅兜底（VPS 带宽/延迟压力最小化）
- `RemoteConsoleClient` 全部现有接口（embed/rerank/ocr/health/node-config/autostart）经新传输零改动白送
- 现有降级链路（REMOTE→DEGRADED→本地模型）对新传输天然生效（失败统一 `RemoteUnavailable`）

## §2 技术方案

### 2.1 协议（wire protocol 规范，全文见 `services/remote_relayd/protocol.md`）

**设计决策**:

| # | 决策 | 理由 |
|---|------|------|
| D1 | transport 承载 **HTTP API 语义**（`api.req`/`api.resp` 消息），不逐业务定义消息 | `RemoteConsoleClient` 全接口零改动; gateway 零业务耦合（内部 httpx 转发本机 backend，全部现有/未来 API 自动可用） |
| D2 | 中继 = **独立 TCP 数据连接**配对，relayd 纯字节转发（不解析帧） | relayd 极薄（无状态转发）; 信令连接职责单一; 会话隔离（sid 一次性） |
| D3 | 打洞 = relayd 协调的 UDP 互射 + HMAC(PSK) 打洞包认证 + 成功后端到端 Noise 握手 | 打洞包须在无会话时被对端识别且防伪造; 加密会话在洞通后建立 |
| D4 | STUN = relayd UDP 端口上的简化自定协议（非 RFC 5389） | 两端自研无互操作需求; 少一个二进制协议解析面 |
| D5 | TTS = 远端角色 `routes/tts.py`（kokoro-onnx），走同一 `api.req` 传输 | 与模型 API 同构; legado 侧无需专用消息 |
| D6 | legado 接入 = SDK 内置 **localhost HTTP 网关**（NanoHTTPD，`127.0.0.1:<port>/tts`） | legado 的 HttpReadAloudService/HttpTTS 引擎零改动，配一个 URL 即用 |
| D7 | 分片重组在加密层内（每个分片独立加密为一个 UDP 帧） | 分片头不泄露消息结构; 与帧 codec 正交 |
| D8 | TTS 初版输出 WAV（24kHz），Opus 压缩列为后续优化 | 可用性优先，避免引入音频编码依赖链 |

**统一帧格式**（三种承载、一个 codec）:

```
TCP（流式）: [4B big-endian 长度 N][N bytes Noise 密文]
UDP（数据报）: [8B nonce 前缀][密文(含16B tag)]
密文 = ChaCha20-Poly1305(会话密钥, 发送计数器, msgpack(消息))
```

**UDP 分片**: 单帧明文 > 阈值（1100B 密文预算）时拆为 `{"t":"_frag","id":u32,"seq":u16,"total":u16,"data":bytes}`; 接收端 100ms 重组窗口，未齐回 `_frag_nack`（缺失 seq 列表），3 轮补片失败放弃（上层超时兜底）。

**Noise NNpsk2**（标准模式，Rev 34 状态机，官方测试向量对齐）:
```
-> e
<- e, ee, psk        ← 此刻互验 PSK + 派生双向会话密钥
```
- 原语: X25519 + ChaCha20-Poly1305 + SHA-256（Python `cryptography`; Kotlin BouncyCastle）
- 认证: PSK 32B（`python -m services.remote_relayd genkey` 生成，base64 配置）
- 防重放: 帧层双向计数器; 握手含随机数

**信令消息**（信令连接上的加密 msgpack）:

```
gateway→relayd: {"t":"register","node":NODE_ID,"ver":1}
relayd→gateway: {"t":"registered","heartbeat_sec":30}
gateway→relayd: {"t":"heartbeat"}                     # 30s 周期
gateway→relayd: {"t":"update_ep","ep":["IP",PORT]}    # STUN 刷新后
client→relayd:  {"t":"lookup","node":NODE_ID}
relayd→client:  {"t":"endpoints","ok":true,"gw":["IP",PORT],"sid":SID}
              | {"t":"endpoints","ok":false,"error":"node_offline"}
relayd→gateway: {"t":"punch_hint","sid":SID,"client":["IP",PORT]}   # lookup 触发
client→relayd:  {"t":"relay_open","node":NODE_ID}
relayd→client:  {"t":"relay_ready","sid":SID,"addr":["IP",PORT]}
# 中继数据连接（新 TCP，首帧明文 JSON——sid 即一次性准入凭证）:
client  →relayd: {"t":"relay_attach","sid":SID}
gateway→relayd: {"t":"relay_join","sid":SID}
relayd→两侧:    {"t":"relay_start"} → 此后纯字节转发（TCP 帧透传，端到端加密）
```

**打洞流程**:
1. client `lookup` → relayd 生成一次性 SID，向 gateway 下发 `punch_hint(client_ep)`，向 client 回 gateway 最新公网 endpoint
2. 双方对彼此 endpoint 各发 3×100ms 打洞包（明文 JSON `{"t":"punch","sid":...,"mac":hmac_sha256(psk,sid)[:8]}`——HMAC 防伪造）
3. 收到对端打洞包即洞通 → 在该 UDP 四元组上客户端发起端到端 Noise 握手 → 直连会话
4. 1.5s 超时未通 → client `relay_open` 走中继; 中继期间后台低频重试打洞，成功后新请求切直连

**业务消息**（端到端会话上）:

```
client→gateway: {"t":"api.req","id":u32,"method":"POST","path":"/embed","body":{...},"token":"..."}
gateway→client: {"t":"api.resp","id":u32,"status":200,"body":{...}}
{"t":"ping"} → {"t":"pong","ts":...}
gateway 内部: httpx 转发 127.0.0.1:<backend_port> + path（业务零耦合）
```

### 2.2 模块清单与落位

**Python（`services/` + `routes/` + `tests/` + `tools/`）**:

| 文件 | 角色 | 职责 | 预估行数 |
|------|------|------|---------|
| `services/remote_crypto.py` | 共用 | Noise NNpsk2 握手 / SessionCrypto（计数器加解密）/ FrameCodec（TCP+UDP）/ Fragmenter | ~350 |
| `services/remote_relayd/__init__.py` `__main__.py` `server.py` `registry.py` `stun.py` `relay.py` `failban.py` | VPS | TCP 准入+信令、注册表、UDP STUN+打洞协调、中继配对字节转发、失败封禁、CLI（serve/genkey） | ~600 |
| `services/remote_gateway.py` | Mac Mini | 注册循环、STUN 刷新、打洞应答、直连/中继会话服务、api.req→本地 httpx 分发 | ~350 |
| `services/remote_transport.py` | 控制台 | SignalingClient、Puncher、路径状态机（DIRECT/RELAY/HTTP×自动切换）、同步 facade | ~300 |
| `services/tts_service.py` | Mac Mini | kokoro-onnx 懒加载、LRU 缓存、合成 | ~180 |
| `routes/tts.py` | Mac Mini | POST /api/tts、GET /api/tts/voices | ~60 |
| `services/remote_client.py`（改） | 控制台 | `_post_json/_get_json/_put_json` 增加 transport 分支 | +60 |
| `services/config_manager.py`（改） | 共用 | 新键 + remote_tunables 扩展 + UI 项 | +80 |
| `server.py`（改） | Mac Mini | lifespan 启动 gateway（`P2P_GATEWAY_ENABLE=1` 时） | +15 |
| `tests/test_remote_crypto.py` `test_remote_relayd.py` `test_remote_e2e.py` | — | 向量/单元/本机三组件全链路 | ~500 |
| `tools/relay-deploy/deploy.py`（根薄壳 `deploy-relayd.sh`）`remote-relayd.service` | VPS | venv+pip+systemd+防火墙 一键部署 | ~230 |
| `services/remote_relayd/protocol.md` | 共用 | wire protocol 规范 + 测试向量（三端对齐唯一权威） | ~300 |

**Kotlin（legado `modules/remote-link/`，Android library，稳定后抽 `sdk/Android/remote-link/`）**:

| 包 | 职责 | 预估行数 |
|----|------|---------|
| `crypto/` | NoiseHandshake + SessionCrypto（BouncyCastle） | ~250 |
| `frame/` | FrameCodec + Fragmenter（msgpack-core） | ~180 |
| `transport/` | SignalingClient / Puncher / RelayClient / PathManager | ~350 |
| `gateway/` | LocalHttpGateway（NanoHTTPD，/tts → api.req → WAV） | ~120 |
| `core/` | RemoteLinkManager（生命周期）/ ConfigStore（SharedPreferences） | ~120 |
| `ui/` | 极简配置 Activity（relay 地址/PSK/节点ID/本地端口） | ~150 |
| `src/test/` | 向量对齐 + 回环单测 | ~300 |

**legado app 侧改动（最小化）**: `settings.gradle` include + `app/build.gradle.kts` 依赖 + App 启动钩子 `RemoteLinkManager.init()` + 配置 Activity 注册（manifest）。

### 2.3 配置（`.ai_env` 新键，ConfigManager 收口）

```
RELAY_HOST=""            # VPS IP
RELAY_PORT=41000
RELAY_PSK=""             # base64(32B)，genkey 生成
REMOTE_NODE_ID="macmini" # 网关节点 ID（client lookup 目标 / gateway 注册名）
P2P_GATEWAY_ENABLE=0     # node 角色开关（Mac Mini 上=1 → 启动 gateway）
P2P_CLIENT_ENABLE=0      # main 角色开关（控制台=1 → remote_client 走 transport）
```

`remote_tunables()` 扩展: `punch_timeout_ms=1500`、`punch_burst=3`、`relay_connect_timeout_sec=5`、`session_idle_close_sec=60`、`stun_refresh_sec=60`、`api_call_timeout_sec=30`。

### 2.4 与现有模块的集成关系

- **`remote_client.py`**: `P2P_CLIENT_ENABLE=1` 且 relay 配置完整时，`_post_json/_get_json/_put_json` 改组 `api.req` 经 `remote_transport` 发送（`probe_health` 的 GET 同理）; `=0` 时与现状逐字节一致。`RemoteUnavailable` 失败面不变。
- **`remote_link.py`**: **零改动**。`probe_health`/`note_request_failure` 经 client 自然工作; 打洞+中继全失败 → `RemoteUnavailable` → 状态机 DEGRADED → 本地模型兜底（现有降级链路白送）。
- **`server.py` lifespan**: `_start_remote_link()` 旁新增 `_start_remote_gateway()`（`P2P_GATEWAY_ENABLE=1` 时启动注册循环）。
- **依赖方向（单向）**: `remote_transport`/`remote_gateway`/`remote_relayd.*` → `remote_crypto`; `remote_client` → `remote_transport`; `remote_link` → `remote_client`（不直达 transport）。

## §3 实现规范

**改动范围表**:

| 类型 | 文件 | 新增/修改 |
|------|------|----------|
| 新增 | `services/remote_crypto.py`、`services/remote_relayd/*`（7 文件）、`services/remote_gateway.py`、`services/remote_transport.py`、`services/tts_service.py`、`routes/tts.py`、`tools/relay-deploy/*`（2 文件）、`services/remote_relayd/protocol.md`、`tests/test_remote_{crypto,relayd,e2e}.py` | 新增 |
| 修改 | `services/remote_client.py`、`services/config_manager.py`、`server.py` | 小幅（+60/+80/+15 行） |
| 新增（legado 仓） | `modules/remote-link/`（Android library） | 新增 |
| 修改（legado 仓） | `settings.gradle`、`app/build.gradle.kts`、`App.kt`、`AndroidManifest.xml` | 最小接线 |

**编码规则**:
- Python: 全量 pyright 通过（backend 已有 pyrightconfig.json）; 强类型 dataclass 边界模型（沿用 `RemoteHealthInfo` 模式）; msgpack 原始 bytes 仅在 codec 边界出现
- Kotlin: 无 Android UI 框架依赖的纯逻辑类（crypto/frame/transport）须可跑 JVM 单测; UI 仅 `ui/` 与 `gateway/`（NanoHTTPD 2.3.1）
- 协议实现三端对齐的唯一判据: `protocol.md` 附录测试向量（Noise 官方向量 + 自定帧/分片向量，Python 生成、Kotlin 消费同一 JSON）
- VPS 部署目标: Python ≥3.9（asyncio API 兼容）; 依赖仅 `cryptography`、`msgpack`（manylinux wheel 直装）

### §3.1 实施步骤拆分

（每步 ≤200 行改动、含验证点; 执行中若实际超 200 行，就地拆子步骤）

**P1. 协议规范文档**
- 文件: `services/remote_relayd/protocol.md`（全文）+ `tools/relay-deploy/` 占位
- 内容: §2.1 全部细节展开为自包含规范 + 测试向量附录（向量由 P2 实现后回填 JSON）。必须澄清: ①帧 payload 对上层透明——握手阶段承载 Noise 握手消息（明文，安全性由 Noise 协议自身保证），会话阶段承载密文; ②TCP 帧用隐式发送计数器做 nonce（字节流严格有序），UDP 帧显式携带 8B 小端计数器（数据报可乱序丢失）
- 验证: 自包含审读（不依赖本需求文档可独立实现）+ 不可见字节扫描
- 依赖: 无

**P2. remote_crypto 之一: Noise NNpsk2 握手**
- 文件: `services/remote_crypto.py`（NoiseHandshake 类: initialize/write_message/read_message/Split）
- 前置: 确认 backend 依赖清单含 `cryptography`、`msgpack`（缺则补装并记录）
- 验证: pytest 官方 NNpsk2 向量（Noise 规范 vectors）逐字节对齐
- 依赖: P1

**P3. remote_crypto 之二: SessionCrypto + FrameCodec**
- 文件: `remote_crypto.py` 续（SessionCrypto: 计数器 nonce 加解密; FrameCodec: TCP 4B 前缀 / UDP 8B nonce 封装）
- 验证: pytest 加解密往返 + 密文篡改拒绝 + 帧编解码往返 + 越界长度拒绝
- 依赖: P2

**P4. remote_crypto 之三: Fragmenter/Reassembler**
- 文件: `remote_crypto.py` 续 + `tests/test_remote_crypto.py` 补分片用例 + 生成向量 JSON 回填 protocol.md
- 验证: pytest 分片重组/乱序/NACK 补片/3 轮放弃
- 依赖: P3

**P5. relayd 之一: 准入 + 注册表 + lookup**
- 文件: `services/remote_relayd/{__init__,server,registry,failban}.py`
- 内容: TCP 服务端 Noise 准入、register/heartbeat/update_ep/lookup、node 在线表、握手失败 IP 封禁（10 次/5min → 封 10min）
- 验证: pytest 注册/lookup/node_offline/无 PSK 拒绝/封禁计数
- 依赖: P3

**P6. relayd 之二: 中继配对与字节转发**
- 文件: `services/remote_relayd/relay.py` + server 接线
- 内容: relay_open 生成一次性 SID → relay_ready; relay_attach/relay_join 首帧明文配对 → relay_start → 双向纯字节 pipe
- 验证: pytest 两条测试 TCP 经 relayd pipe 互通（echo 会话）+ 错误 SID 拒绝 + SID 一次性
- 依赖: P5

**P7. relayd 之三: UDP STUN + punch 协调 + CLI**
- 文件: `services/remote_relayd/{stun,__main__}.py`
- 内容: UDP 41000 收 `stun` 包回源地址; lookup 时向 gateway 下发 punch_hint; CLI `serve` / `genkey`
- 验证: pytest STUN 回显 + punch_hint 下发 + genkey 输出 base64(32B) 合法性
- 依赖: P5

**P8. gateway 之一: 注册循环与信令处理**
- 文件: `services/remote_gateway.py`（注册连接 Noise 握手、heartbeat、STUN 定期刷新 update_ep、relayd 断线指数退避重连）
- 验证: 本机起 relayd+gateway，registry 出现节点且 endpoint 随 STUN 刷新（日志断言）; 杀 relayd 进程验证重连
- 依赖: P5, P7

**P9. gateway 之二: 打洞应答 + 直连 UDP 会话**
- 文件: `remote_gateway.py` 续（punch 包收发 HMAC 校验、UDP 监听、直连会话 Noise 服务端）
- 验证: 本机集成测试——测试桩 client 经 relayd 协调与 gateway UDP 打洞成功并完成握手（同机双 socket）
- 依赖: P4, P8

**P10. gateway 之三: 中继会话 + api.req 分发**
- 文件: `remote_gateway.py` 续（relay_join、api.req→httpx.AsyncClient 本机转发（端口由 lifespan 启动时传入，见 P14）、ping/pong）
- 验证: 本机三组件（relayd+gateway+backend stub）中继全链路 api.resp 返回
- 依赖: P6, P9

**P11. transport 之一: SignalingClient + Puncher + 路径状态机**
- 文件: `services/remote_transport.py`
- 验证: 本机直连路径集成测试（transport.request 走 UDP 直连成功）
- 依赖: P9

**P12. transport 之二: RelayClient + 会话管理 + 同步 facade**
- 文件: `remote_transport.py` 续（relay_open/attach、会话缓存、`request()` 同步 API: 打洞 1.5s → 中继 → 失败 RemoteUnavailable）。线程模型: 内部后台 asyncio loop 线程，`request()` 提交 future 同步等待（remote_client 调用点在 worker 线程）
- 验证: 本机中继路径 request() + 模拟 UDP 阻断强制中继 + 双路径切换
- 依赖: P10, P11

**P13. remote_client 接入与回归**
- 文件: `services/remote_client.py`（transport 分支）
- 验证: P2P_CLIENT_ENABLE=0 回归现状（现有 pytest 全绿）; =1 时 embed/rerank/ocr/probe_health 走 transport（本机 e2e 桩）
- 依赖: P12

**P14. ConfigManager + server lifespan**
- 文件: `services/config_manager.py`（6 键 + tunables 扩展 + UI 项）、`server.py`（gateway 启动——lifespan 将 backend 实际监听端口传入 gateway 供 api.req 转发）
- 验证: pytest config 用例 + lifespan 日志（gateway enable 时启动注册循环）
- 依赖: P8

**P15. tts_service（kokoro-onnx）**
- 文件: `services/tts_service.py`（懒加载、LRU(text→wav) 2048 条、voices 列表、模型缺失错误面）。模型资产约定: `~/.cache/opensecurity/tts/{kokoro-v1_0.onnx,voices.bin}`，下载命令写入 P24 文档
- 验证: pytest（无模型时的错误语义）+ `python -m services.tts_service --smoke` 手测入口合成 wav
- 依赖: 无（可与 P5+ 并行）

**P16. routes/tts.py + e2e**
- 文件: `routes/tts.py`（POST /api/tts {text,voice,speed} → wav bytes base64; GET /api/tts/voices）
- 验证: pytest route 用例（mock service）+ transport 模式全链路调 TTS
- 依赖: P12, P15

**P17. relay-deploy 部署物**
- 文件: `tools/relay-deploy/{deploy.py,remote-relayd.service,README.md}` + 根薄壳 `deploy-relayd.sh`
- 内容: venv + pip（cryptography/msgpack）+ systemd unit（PSK 经 EnvironmentFile=/etc/remote-relayd/relay.env 注入，含 RELAY_PSK/RELAY_PORT）+ firewalld 规则 + Python≥3.9 检测/安装分支（CentOS dnf / 兜底提示手动装）+ 升级/日志说明
- 验证: `bash -n` 语法 + 文档自包含审读
- 依赖: P7

**P18. Python e2e 全链路测试**
- 文件: `tests/test_remote_e2e.py`（单进程内起 relayd+gateway+backend stub: 直连请求/UDP 阻断落中继/中继期间恢复打洞切回/全断 RemoteUnavailable/无 PSK 拒绝）
- 验证: pytest 全绿（本步即验证）
- 依赖: P13, P16

**P19. Kotlin 模块骨架 + FrameCodec/Fragmenter + 向量对齐**
- 文件: `modules/remote-link/`（build.gradle.kts、frame/、src/test/）。向量 JSON 由 P4 生成后复制到本仓 `modules/remote-link/src/test/resources/vectors.json`（跨仓静态拷贝，版本以 Python 端为准）
- 验证: `./gradlew :modules:remote-link:test` 向量全对齐
- 依赖: P4（仅需向量 JSON，可与 Python relayd 并行）

**P20. Kotlin Noise + SessionCrypto**
- 文件: `crypto/`（BouncyCastle）+ 向量对齐测试
- 验证: 同上（Noise 官方向量 + 自定向量）
- 依赖: P19

**P21a. Kotlin SignalingClient + RelayClient**
- 文件: `transport/`（信令连接、relay_open/attach、TCP 数据连接管理）
- 验证: JVM 单测（本地 socket 桩验证帧交互与状态迁移）
- 依赖: P20

**P21b. Kotlin Puncher + PathManager**
- 文件: `transport/` 续（UDP 打洞客户端侧、路径状态机 DIRECT/RELAY 切换）
- 验证: JVM 单测（回环双 socket 打洞 + 状态机迁移表）; 真 relayd 联调列入 P24 手测清单
- 依赖: P21a

**P22. Kotlin LocalHttpGateway + Manager + ConfigStore**
- 文件: `gateway/`（NanoHTTPD /tts）、`core/`
- 验证: JVM 单测（127.0.0.1 HTTP → mock transport → WAV 响应）
- 依赖: P21b

**P23. legado 接线 + 配置 UI**
- 文件: `settings.gradle`、`app/build.gradle.kts`、`App.kt`（init 钩子）、`ui/ConfigActivity`、manifest、legado 设置页加入口（一行 Preference/菜单项跳 ConfigActivity）
- 验证: `./gradlew assembleDebug` 通过 + 手测清单条目（HttpTTS 引擎配 `http://127.0.0.1:<port>/tts?text={{speakText}}&speed={{speakSpeed}}`、contentType audio/wav、concurrentTasks=1）
- 依赖: P22

**P24. 联调文档 + 收尾**
- 文件: `tools/relay-deploy/README.md` 扩充（VPS/Mac Mini/手机三端配置 + 故障排查矩阵）+ 任务 progress 总结
- 验证: 文档自包含审读; §4 验收清单逐条核对
- 依赖: P18, P23

## §4 验收标准

**功能验收**:
1. `P2P_CLIENT_ENABLE=1` + relay 配置完整时: `probe_health`/`embed`/`rerank`/`ocr_extract` 经 transport 成功（直连或中继路径），返回与 HTTP 路径语义一致
2. UDP 阻断（模拟打洞失败）时自动落中继，请求不失败; 中继期间打洞恢复后新请求切回直连（路径切换无感）
3. relayd 拒绝无 PSK / 错 PSK 连接（Noise 握手失败即断）; 同 IP 高频握手失败触发封禁
4. 中继会话上 relayd 只见密文（VPS 零知识）——抓包/代码路径双重验证
5. legado: 配置 RemoteLink TTS 引擎（127.0.0.1 网关 URL）后朗读出声（真机）
6. `python -m services.remote_relayd genkey` 输出合法 base64(32B); `./deploy-relayd.sh` 在干净 VPS 上一键部署成功
7. TTS LRU 缓存命中（同文本二次合成 <50ms）

**回归验收**:
1. `P2P_CLIENT_ENABLE=0` 时 `remote_client` 行为与现状逐字节一致（HTTP 路径，全部现有 pytest 用例不变绿转红）
2. `remote_link` 状态机语义零变化（OFF/REMOTE/DEGRADED 迁移、心跳、降级预热、恢复卸载逻辑不动）
3. backend 现有 `pytest` 全量通过; pyright 无新增错误
4. legado: 不启用 RemoteLink 时（未配置 PSK），App 行为与现状一致（网关不监听、零开销）

**架构验收**:
1. 依赖方向: `remote_crypto` 不 import 任何 remote_*; `remote_link` 不 import `remote_transport`/`remote_gateway`（经 `remote_client` 间接）
2. legado 侧纯逻辑包（crypto/frame/transport）无 Android 框架依赖，JVM 可测
3. 三端协议实现与 `protocol.md` 向量对齐（Python 生成、Kotlin 消费、CI 单测互验）
4. 新文件全部位于 `.opencode/control/backend/`（Python）与 legado `modules/remote-link/`（Kotlin），无散落

## §5 与现有需求文档的关系

- **延续**: 本文档是模型远程化体系（`remote_link`/`remote_client`，见 `2026-08-16-deps-layering-and-local-ocr.md` 时代的远程化一期）的**传输层演进**——状态机与降级语义完全复用，仅底层承载从"单一 HTTP"扩展为"直连 UDP / 中继 TCP / 局域网 HTTP 三路径自动切换"
- **不改变**: `RemoteConsoleClient` 对外接口、`RemoteLinkStatus` 字段、`/api/remote/*` 路由契约——前端远程 TAB 无需感知传输层变化
- **新增面**: 远端角色业务扩展（TTS）、VPS 部署物、legado 仓 Kotlin 模块（跨仓改动，独立模块化、可抽取）
- **后续衔接**: Opus 音频压缩（D8 优化项）、`sdk/Android/remote-link/` 抽取（模块稳定后）
