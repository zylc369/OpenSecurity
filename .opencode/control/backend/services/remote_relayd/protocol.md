# remote-p2p wire protocol v1

> 三端（Python 控制台 transport / Python gateway / Kotlin SDK）实现的唯一权威规范。
> 本文档自包含: 不依赖任何外部需求文档即可独立实现。
> 测试向量见附录 B（由 Python 参考实现生成，三端单测消费同一 JSON）。

## 1. 概述与角色

| 角色 | 部署位置 | 职责 |
|------|---------|------|
| relayd | VPS（公网 IP） | 信令中枢 + STUN + 打洞协调 + 中继字节转发 + 准入封禁 |
| gateway | Mac Mini（backend 进程内） | 向 relayd 注册; 打洞应答; 接受直连/中继会话; api.req → 本机 backend HTTP 转发 |
| client | 控制台 backend（transport）/ legado（SDK） | 信令查询; 发起打洞; 建立直连或中继会话; 发送 api.req |

端口约定: relayd 监听 `TCP 41000`（信令+中继）与 `UDP 41000`（STUN+打洞协调）。全部可配置。

## 2. 加密基础

**原语**: X25519（DH）+ ChaCha20-Poly1305（AEAD）+ SHA-256（哈希）。Python `cryptography` / Kotlin BouncyCastle。

**PSK**: 32 字节随机，base64 编码录入配置。relayd / gateway / client 四处（relayd 与两侧）持有同一 PSK。
生成: `python -m services.remote_relayd genkey`。

**Noise 模式**: `Noise_NNpsk2_25519_ChaChaPoly_SHA256`（标准模式，实现细节见附录 A）。

- 握手 2 消息: `-> e` / `<- e, ee, psk`
- 第 2 消息完成后: 双方互验 PSK（无钥者无法完成）、派生双向会话密钥
- 前向保密: 会话密钥仅由临时密钥派生，连接结束销毁

**三种加密会话**（互不相同、相互独立）:
1. 信令连接（client/gateway ↔ relayd）: Noise 握手后所有信令消息加密
2. 数据会话-直连（client ↔ gateway，UDP）
3. 数据会话-中继（client ↔ gateway，字节经 relayd 透传，relayd 只见密文）

## 3. 统一帧格式

**payload 透明原则**: 帧只负责封装与定界，不感知 payload 语义——握手阶段 payload = Noise 握手消息（明文，安全性由 Noise 自身保证）; 会话阶段 payload = 密文（§2 会话密钥加密的 msgpack 消息）。

### 3.1 TCP 帧（流式承载）

```
[4B big-endian payload 长度 N][N bytes payload]
```
- N 上限 1 MiB（防御性; 超限即断连）
- 用于: 信令连接、中继数据连接、中继上的会话帧

### 3.2 UDP 帧（数据报承载）

```
[8B nonce 前缀][密文(含16B tag)]
```
- 用于: 直连会话
- 明文消息 ≤ `FRAG_LIMIT`(900B) 时单帧; 超出走分片（§5）

**UDP 承载上的握手判别**（接收方按来源地址状态区分，无封装标记）:
- 无会话的来源地址: 32 字节包 = Noise 握手 msg1（**裸 Noise 消息，无 nonce 前缀**）; `{"t":"punch",...}` JSON = 打洞包
- 已建会话的来源地址: [8B nonce 前缀][密文] 会话帧

### 3.3 nonce 规则

- 会话密钥建立后，每方向维护 u64 发送计数器（从 0 起，每帧 +1）
- **TCP**: nonce = 计数器小端 8B，**不传输**（字节流严格有序）; 接收计数器必须连续，乱序/跳跃即协议错误断连
- **UDP**: nonce = 计数器小端 8B，**显式传输**（数据报可乱序丢失）; 接收端必须丢弃重复计数器（防重放），乱序允许; 已见集合超过 1024 条时剪枝并抬升拒绝水位（floor = max-WINDOW，水位判定独立于集合大小）

## 4. 消息与序列化

payload（密文解开后）= msgpack 编码的消息 dict。字段 `t` 为消息类型（字符串）。实现须容忍未知字段（前向兼容）、拒绝未知 `t`（回 `error`）。

### 4.1 信令消息（信令连接上）

| 方向 | 消息 | 字段 |
|------|------|------|
| gw→relayd | `register` | `t,node`(str),`ver`(u32=1) |
| relayd→gw | `registered` | `t,heartbeat_sec`(u32=30) |
| gw→relayd | `heartbeat` | `t` |
| relayd→gw | `heartbeat_ack` | `t` |
| gw→relayd | `update_ep` | `t,ep:[ip(str),port(u16)]`（STUN 刷新后） |
| client→relayd | `lookup` | `t,node`(str),`udp_ep`?[ip,port]（client 预先经 relayd UDP STUN 探测的自身 UDP 公网映射，见 §6） |
| relayd→client | `endpoints` | 成功: `t,ok:true,gw:[ip,port],sid`(str)；离线: `t,ok:false,error:"node_offline"` |
| relayd→gw | `punch_hint` | `t,sid`(str),`client:[ip,port]`（= lookup 携带的 udp_ep; 未携带则用信令 TCP 源地址兜底） |
| client→relayd | `relay_open` | `t,node`(str) |
| relayd→client | `relay_ready` | `t,sid`(str),`addr:[ip,port]` |

### 4.2 中继数据连接（新 TCP，独立于信令连接）

中继数据连接与信令连接**同流程 Noise 准入**（首帧承载握手）; 准入后**首个加密消息**标识角色（sid 即一次性准入凭证，32 字符 hex = 16B 随机）:

```
client→relayd(信令):  {"t":"relay_open","node":NODE_ID,"sid":SID}   # SID=lookup 返回值
relayd→gateway(信令): {"t":"relay_peer","sid":SID}                  # 通知 gw 开数据连接 join
relayd→client(信令):  {"t":"relay_ready","sid":SID,"addr":[ip,port]}
client  →relayd(新TCP): {"t":"relay_attach","sid":SID}              # 准入后首条加密消息
gateway→relayd(新TCP): {"t":"relay_join","sid":SID}
relayd→两侧:          {"t":"relay_start"}                            # 配对成功告知
```
`relay_start` 之后该连接为**纯字节管道**（承载端到端 TCP 帧; relayd 不解析）。sid 配对即失效; 错误 sid 回 `{"t":"error","code":"bad_sid"}` 并断开; 30s 未配对超时断开。lookup 生成的 sid 同时用于打洞协调与中继配对（中继配对成功才消费; 打洞成功而不走中继时由 TTL 清理）。

### 4.3 会话业务消息（端到端会话上，client ↔ gateway）

| 方向 | 消息 | 字段 |
|------|------|------|
| c→g | `api.req` | `t,id`(u32),`method`("GET"/"POST"/"PUT"),`path`(str),`body`?(dict/bytes),`token`?(str) |
| g→c | `api.resp` | `t,id,status`(u16),`mime`(str,默认"application/json"),`body`(dict 或 bytes) |
| c→g | `ping` | `t` |
| g→c | `pong` | `t,id`(回显),`ts`(f64 unix 秒) |
| 双向 | `error` | `t,code,msg`（code: `noise_failed`/`node_offline`/`bad_sid`/`banned`/`proto_error`/`bad_punch`） |

gateway 转发: `httpx.AsyncClient` 请求 `http://127.0.0.1:<backend_port><path>`（backend_port 由 lifespan 注入）; 响应 Content-Type 为 JSON → `body=dict`，否则 `body=bytes` + `mime` 原样。

### 4.4 UDP 明文控制包（无会话时，JSON + LF）

```
STUN:   任意端→relayd UDP: {"t":"stun"}\n
        relayd→源:           {"t":"stun.resp","src":[ip,port]}\n
打洞:    双方互发:           {"t":"punch","sid":"<sid>","mac":"<hex16>"}\n
        mac = hmac_sha256(psk_bytes, "punch:"+sid).hex()[:16]
```

## 5. UDP 分片协议

单条明文消息 > `FRAG_LIMIT`(900B) 时:

- 发送端拆为 `{"t":"_frag","id":u32,"seq":u16,"total":u16,"data":bytes}`，每个分片独立加密为一个 UDP 帧（§3.2）
- 接收端: 收到首个分片启动 `REASM_WINDOW`(100ms) 窗口; 窗口结束未集齐 → 回 `{"t":"_frag_nack","id":u32,"missing":[seq,...]}`; 发送端补发缺失分片; 累计 3 轮 NACK 后放弃（上层超时兜底）
- `total` 上限 256; 超限消息直接 `error proto_error`

## 6. 打洞协议（时序）

```
1. client 经 relayd UDP 41000 发 stun → 得自身 UDP 公网映射 udp_ep（cone NAT 下对任意目的地映射一致）
2. client →relayd(信令): lookup{node, udp_ep}
3. relayd: 生成一次性 sid → 向 gw 信令连接下发 punch_hint{sid, client=udp_ep}
   relayd →client: endpoints{gw:[最新 update_ep 值], sid}
4. 双方并行互射（各 3 包、100ms 间隔）:
   client →gw_ep(UDP): punch{sid, mac}
   gw     →client_ep(UDP): punch{sid, mac}   （收到 punch_hint 后立即; 必须使用其 STUN 探测用的同一本地 UDP socket——NAT 映射属于该 socket; 收到对端 punch 后，后续包改射对端实际源地址）
5. 任一方收到合法 punch（mac 校验过）→ 路径确认
6. client 在该 UDP 四元组上发起端到端 Noise 握手（握手帧 = UDP 帧承载 Noise 消息，§3 透明原则）
7. 握手完成 → 直连会话建立（后续 api.req/ping 走此会话）
```

- 超时 `PUNCH_TIMEOUT_MS`(1500) 未通 → client 转中继（§4.2）
- punch 包 mac 校验失败 → 忽略（计数，超阈上报日志）
- gateway 收 punch_hint 但 client 打洞包未到 → 互射照发（对方 NAT 可能丢弃，正常失败路径）

## 7. 客户端路径状态机（规范级）

```
IDLE ──request──▶ TRY_PUNCH ──ok──▶ DIRECT(会话)
                     │fail(1.5s)
                     ▼
                 TRY_RELAY ──ok──▶ RELAY(会话)
                     │fail(5s)
                     ▼
              RemoteUnavailable（上层 remote_link 降级链路接管）
DIRECT 会话请求失败 ──▶ IDLE（下次请求重新打洞）
RELAY 会话保持期 ──后台每 30s 重试打洞──▶ 成功后新请求走 DIRECT（旧中继会话延迟关闭）
会话空闲 SESSION_IDLE_SEC(60) 双侧主动关闭
```

## 8. relayd 准入与封禁

- 任何 TCP 连接: 首个 TCP 帧（§3.1）必须承载 Noise 握手第 1 消息; `NOISE_WAIT`(10s) 未完成握手 → 断开 + 计一次失败
- 失败计数: 同 IP `FAIL_WINDOW`(5min) 内 ≥ `FAIL_LIMIT`(10) 次 → 封禁 `BAN_SEC`(10min)（期内直接 TCP RST）
- UDP punch/stun 包不消耗封禁计数（mac 校验失败仅忽略）

## 9. 超时与常量表

| 常量 | 值 | 说明 |
|------|-----|------|
| DEFAULT_PORT | 41000 | TCP/UDP 同号 |
| FRAG_LIMIT | 900 | 明文字节 |
| FRAG_TOTAL_MAX | 4096 | 分片数上限（≈3.7MB——TTS 音频/OCR 图片量级） |
| REASM_WINDOW | 100ms | 分片重组窗口 |
| NACK_ROUNDS | 3 | 分片补片上限 |
| UDP_REPLAY_FLOOR | 剪枝水位 | 防重放与 set 大小无关（review#3） |
| PUNCH_TIMEOUT_MS | 1500 | 打洞窗口 |
| PUNCH_BURST | 3 × 100ms | 互射包数 |
| RELAY_CONNECT_TIMEOUT | 5s | 中继连接建立 |
| SESSION_IDLE_SEC | 60 | 会话空闲关闭 |
| HEARTBEAT_SEC | 30 | gateway→relayd |
| NODE_OFFLINE_SEC | 90 | relayd 判定离线（3×心跳） |
| STUN_REFRESH_SEC | 60 | gateway STUN 刷新 |
| API_TIMEOUT_SEC | 30 | api.req 端到端 |
| NOISE_WAIT | 10s | 准入握手时限 |
| FAIL_WINDOW / FAIL_LIMIT / BAN_SEC | 5min / 10 / 10min | 封禁三参 |
| TCP_FRAME_MAX | 8 MiB | 防御上限（大音频/图片载荷） |

## 附录 A: Noise NNpsk2 实现细节

- protocol_name: `Noise_NNpsk2_25519_ChaChaPoly_SHA256`（33B > 32B → `h = HASH(protocol_name)`; 若 ≤32B 则 `h = name || zeros`）
- 状态机（Noise Rev 34 语义; 实现必须以官方测试向量对齐，禁止凭记忆手写）:
  ```
  initiator                          responder
  h = HASH(protocol_name); ck = h
  init: e = GENERATE_KEYPAIR()
  msg1 -> : e(32B); MixHash(e.pub)
  msg2 <- : e'; MixHash(e'.pub)
            ee = DH(e, e'); MixKey(ee)
            psk: MixKeyAndHash(PSK);  ← psk token 位置 2
            payload 加密(空 payload) + MAC
  Split(): k1,k2 = HKDF(ck, 2)
  initiator 发送用 k1、接收用 k2; responder 相反
  ```
- 官方向量: Noise 规范 `vectors/` 目录 NNpsk2 条目（附录 B 测试 JSON 内嵌摘录）
- 会话加密: `ChaCha20-Poly1305(key, nonce=counter_le64, aad=空, plaintext)`

## 附录 B: 测试向量

已回填: `services/remote_relayd/vectors.json`（由 `python -m services.remote_relayd.gen_vectors` 生成/刷新，Kotlin 单测消费同一文件）。段落: `noise_nnposk2` / `session_roundtrip` / `tcp_frame` / `udp_frame` / `frag` / `punch_mac`。向量确定性来源: 固定 PSK `00..1f` + 固定双方临时私钥 `01*32` / `02*32`。
