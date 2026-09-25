# 代理 IP 管理系统（Proxy IP Manager）技术方案

> 状态：定稿（对齐后重写）
> 日期：2026-09-25
> 来源：OoC Web 题限流实战复盘 + 代理IP供应商实测验证（附录 A）

---

## 0. 一句话总结

在**已有的控制台后端**（FastAPI，:9776）内新增 IP 池（pool）与本地代理服务（relay，:9676），新增一个薄壳 proxy MCP；浏览器出生即连 relay 固定入口、requests 脚本显式一行 `proxies` 接入；**agent 是唯一的限流判定者与换出口决策者**，控制台提供完整的可查询状态保证判定无信息缺口。零新增进程、零环境变量接管、零运行时 patch。

---

## 1. 背景与两条铁律

### 1.1 痛点（实测数据，附录 A 有验证细节）

| 痛点 | 数据 |
|------|------|
| 本机 IP 被限流 | ~10 个请求（1.5s 间隔）触发 429，持续则升级为 Cloudflare 挑战页，被迫中断 |
| 新代理 IP 表现 | 0.5s 间隔连打 60 发零限流——限流按单 IP 历史累计 |
| 代理逻辑无法复用 | 签名/提取/过期/换新，每个脚本重复手写 |
| 代理 IP 浪费 | 无缓存管理时每次跑脚本提取新 IP；实际单 IP 可承载 30~60 发 |

### 1.2 铁律一：信息完整性（agent 判定无缺口）

> **agent（LLM）操作浏览器与脚本，判定依赖完整上下文。任何它不知道的换出口动作，都会制造时间线黑洞，导致误判（典型：自动换 IP 后的预期挑战被误判为真限流 → 连环换 IP 烧配额）。**

约束推论：

1. 换出口只有三个来源，每个都满足"agent 发起"或"可查询"之一：
   - ① agent 调 MCP `proxy_rotate` / `proxy_mode`（天然知道）；
   - ② 脚本报告限流信号（输出/print）→ agent 判定后走 ①（天然知道）；
   - ③ relay 的 35 连接阈值自动轮换（agent 未发起）→ **必须写入 `rotate_history`，agent 判定前经 `proxy_status` 查询补全时间线**；
2. **脚本内禁止任何写死的自动换 IP 代码**（自动上报、自动切换均不允许）——脚本只报告信号，行动权归 agent；
3. `proxy_status` 必须返回完整 `rotate_history`（时间/原因/新旧出口）。

### 1.3 铁律二：故障域隔离（显式接入，无全局隐式接管）

> 不用环境变量全局接管、不用 venv patch、不改任何库源码。代理是"显式选用"的能力，不用它的流量完全不感知 relay 的存在。relay 故障的最坏影响 = 正在显式使用它的脚本与浏览器重试一次，pip/git/控制台/其他一切无感。

---

## 2. 术语表

| 术语 | 定义 |
|------|------|
| **供应商 API** | 代理商 juliangip.com 的提取接口（企业版 `v2.api.juliangip.com/company/dynamic/getips`）。一次提取返回一个 `IP:端口`，存活 300s。凭证：订单号 + API 秘钥，存 `.ai_env` |
| **出口（egress）** | 流量最终从哪个 IP 离开本机：direct（本机 IP）或 proxy（某供应商代理IP） |
| **换出口** | relay 切换出口的动作，三种：direct→proxy、proxy→direct、代理IP供应商 A→代理IP供应商 B（后者专称"轮换 IP"） |
| **本地代理服务（relay）** | 控制台进程内的 asyncio TCP 服务，监听 `127.0.0.1:9676`（端口无语义，可配置；取 9776−100 是为避开控制台顺延方向）。所有显式接入的流量经它转发，它在背后选择出口 |
| **IP 池（pool）** | 控制台内服务：代理IP供应商签名/提取/缓存/过期/黑名单/域名冷却/轮换历史，状态持久化 |
| **域名冷却表** | `{域名: 截止时刻}`——某域名对该出口限流后，仅该域名流量切代理，其他域照常（relay 在 CONNECT 阶段可见目标域名，HTTPS 下域名是明文） |
| **rotate_history** | 换出口历史（时间/原因/新旧出口），agent 判定的时间线依据（铁律一） |
| **限流信号** | 状态码 429；或 `cf-mitigated: challenge` 响应头（CF 挑战页明确自标记，一个头定案）；或 403/503 且 `server: cloudflare`；或 body 特征（`Just a moment...` 等） |
| **服务端票据绑定** | `cf_clearance`/Flask-Login `_id` 等在签发时绑定出口 IP+UA。换出口后 cookie 本体还在本地，但服务端拒绝认可 → 重过一次挑战/重登录。服务端行为，客户端任何架构无解 |
| **判定 SOP** | agent 的三场景判定流程（§5.2），物化在 MCP 工具描述内每轮可查 |

---

## 3. 总体架构

### 3.1 架构图

```
┌────────────────────────── 消费端（三种形态） ──────────────────────────┐
│                                                                        │
│  ① 浏览器(有头/无头)          ② requests 脚本            ③ agent 对话流 │
│     launch(proxy=固定入口)       proxies={"https": 入口}    MCP 四工具   │
│     (出生即连, 永不变)           (脚本内一行, 显式)          (判定+决策)  │
└──────────┬─────────────────────────┬──────────────────────┬───────────┘
           │ :9676                   │ :9676                │ stdio
           ▼                         ▼                      ▼
┌───────────────────────────────────────────────────┐ ┌────────────────┐
│ 控制台后端（已有进程 FastAPI :9776）                  │ │ proxy MCP 薄壳   │
│                                                     │ │ (第4个MCP, 照抄  │
│  ┌───────────────────────────────────────────────┐ │ │ ocr 模式)       │
│  │ relay  :9676  本地代理服务(supervisor 自愈)      │ │ └────────────────┘
│  │  · CONNECT 隧道(HTTPS)+明文GET转发               │ │
│  │  · 出口选择: direct(默认)/proxy + 域名冷却分流     │◄┼── 工具转发到
│  │  · 35连接阈值自动轮换(写入 rotate_history)       │ │    控制台接口
│  │  · 换出口=优雅关闭(FIN收尾,在飞响应完整送达)      │ │
│  └───────────────┬───────────────────────────────┘ │
│                  │ 进程内函数调用                      │
│  ┌───────────────▼───────────────────────────────┐ │
│  │ pool  IP池(唯一簿记与状态实现)                   │ │
│  │  代理IP供应商签名/提取/缓存/过期/黑名单/域名冷却/          │ │
│  │  rotate_history/域名归一化(§5.1)                │ │
│  └───────────────┬───────────────────────────────┘ │
│  ┌───────────────▼───────────────────────────────┐ │
│  │ routes/proxy.py  控制接口(仅127.0.0.1)           │ │
│  │  GET/POST /api/proxy/*  (参数校验+归一化)        │ │
│  └───────────────────────────────────────────────┘ │
└──────────────────────┬────────────────────────────┘
                       │ HTTPS + MD5 签名（仅提取时调用）
                       ▼
              供应商 API（每次提取 1 个 IP，存活 300s）
```

### 3.2 关键设计决策

| 决策 | 理由 |
|------|------|
| 复用控制台进程，不新增常驻进程 | plugin 已保证控制台存活（startControl 幂等拉起）；MCP 经 IPC 端口发现，控制台重启 MCP 自愈 |
| relay 端口 9676 而非并入 9776 | FastAPI/ASGI 无法承载代理协议（CONNECT 后 TCP 连接须成为永久双向字节管道，框架不交出底层连接控制权）。同进程、不同端口、不同协议 |
| 浏览器出生即连 relay（"直连"由 relay direct 模式实现） | Playwright 代理参数 launch 时定死且运行中不可改。**出生即连固定入口是不重启浏览器切换出口的唯一前提**。代价（浏览器依赖 relay 存活）由 supervisor 自愈（2 秒级重拉）兜底 |
| requests 脚本显式一行 proxies（不做环境变量/patch/魔改） | 铁律二：故障域隔离。隐式全局接管会把 relay 变成一切流量的单点（relay 故障=全部断网），且多组件联动配置（NO_PROXY/patch 回退）引入隐性故障面 |
| 判定者 = agent（唯一），无 watchdog/evaluator 状态机 | 铁律一。浏览器与脚本的操作者本来就在环里、有完整时间线；无上下文的状态机需要"观察窗"猜测挑战推进，且任何脚本内自动换 IP 都制造时间线黑洞——agent 是天然且唯一的判定者 |
| 脚本只报告信号不行动 | 铁律一推论：脚本内任何写死的自动换 IP 都制造时间线黑洞 |

### 3.3 文件清单

| 文件 | 动作 | 内容 |
|------|------|------|
| `control/backend/services/proxy_pool.py` | 新增 | IP 池 + 域名归一化 + rotate_history，~200 行 |
| `control/backend/services/proxy_relay.py` | 新增 | 本地代理服务（含 supervisor 自愈），~200 行 |
| `control/backend/routes/proxy.py` | 新增 | 控制接口（参数校验），~100 行 |
| `control/backend/server.py` | 改 2 行 | include_router + 启动 relay |
| `mcp-servers/proxy/server.py` | 新增 | MCP 薄壳（4 工具，描述内嵌判定 SOP），~90 行 |
| `plugins/lib/mcp-manager.ts` | 改 1 处 | MCP_SERVERS 注册 proxy |
| `agents/web-analysis.md` | 改 ~10 行 | 代理使用策略（触发条件+入口） |
| `web-analysis/knowledge-base/proxy-usage.md` | 新增 | 代码模板（entry 用法/Retry/限流特征清单/判定特征） |
| `.ai_env` | 用户填写 | `JULIANG_TRADE_NO` / `JULIANG_API_KEY`（控制台配置页可编辑） |

---

## 4. 模块详解

### 4.1 pool `services/proxy_pool.py`（唯一簿记与状态实现）

```python
@dataclass
class ProxyInfo:
    ip: str              # "1.2.3.4:5678"
    fetched_at: float
    expire_at: float     # fetched_at + 300 - 30（安全余量）

@dataclass
class RotateEvent:
    ts: float
    reason: str          # "agent_rotate" | "bad_ip" | "auto_rotate_35conn" | "mode_direct_to_proxy" | ...
    old: str | None      # 旧出口（"direct" 或 "ip:port"）
    new: str | None

@dataclass
class PoolState:
    current: ProxyInfo | None
    bad_ips: list[str]                 # 会话内黑名单
    domain_limited: dict[str, float]   # {归一化域名: 冷却截止时刻}
    mode: str                          # "direct" | "proxy"
    surplus: int                       # 订单余量
    total_fetched: int                 # 累计消耗
    rotate_history: list[RotateEvent]  # 最近 50 条（铁律一）

class ProxyPool:
    def get(self, force_new=False) -> ProxyInfo      # 缓存命中直接复用（省花销的核心）
    def rotate(self, reason: str) -> ProxyInfo       # 提取新 IP + 记 rotate_history
    def mark_bad(self, ip: str, reason: str)         # 黑名单；若是当前 IP 则触发 rotate
    def domain_cool(self, domain: str, minutes=10)   # 域名冷却（域名先经归一化）
    def set_mode(self, mode: str)                    # 全局粗开关，记 history
    def status(self) -> PoolState                    # 含完整 history
```

**代理IP供应商调用**（已实测验证，附录 A）：企业版接口、参数（num=1/pt=1/result_type=json/ip_remain=1/filter=1）、签名算法（参数 ASCII 字典序 + `&key=` + MD5 小写，代码内置官方示例值自测）、3 次指数退避重试。凭证经 `config_store` 读 `.ai_env`（唯一读写方）。**凭证缺失时**：不抛异常，pool 返回明确的"未配置"状态（`status`/`entry` 正常返回并附配置指引；`rotate`/提取类操作返回 422 + 指引文案），direct 模式不受影响。

**状态持久化**：`proxy_state.json`（控制台数据目录），变更原子写。

### 4.2 relay `services/proxy_relay.py`（本地代理服务）

**职责**：固定入口 + 出口选择 + 优雅关闭 + 阈值轮换。**零 HTTP 语义理解**（HTTPS 只见密文，字节管道）。

| 机制 | 说明 |
|------|------|
| CONNECT 隧道 | 客户端 `CONNECT host:443` → relay 按当前出口建上游 TCP → 回 `200 Connection Established` → 之后双向拷贝字节。TLS 端到端，relay 看不见内容。明文 HTTP（绝对 URI GET）同理 |
| 出口选择（每连接） | 域名在冷却表内 → 该连接走 proxy（代理出口）；否则按全局 mode（direct/proxy）。域名取 CONNECT 目标 host，**经与控制接口相同的归一化函数**（收口，§5.1）。**需 proxy 出口而池内无可用 IP 时惰性触发 pool.get()**（direct 模式下域名冷却命中即此路径） |
| 换出口 = 优雅关闭 | 对存量上游连接发 FIN（half-close）+ 读尽剩余响应字节（drain，收尾宽限 5s 兜底强关）→ 在飞响应完整送达客户端（表现为"连接正常收尾"而非错误）→ 客户端下一连接走新出口。POST 无重复提交风险（响应已到手）。宽限 5s 不是连接寿命限制（IP 寿命 300s，连接任意存活），是换出口动作的收尾窗口——换出口的动机（限流止血/IP 到期）要求及时切换 |
| 35 连接阈值轮换 | proxy 模式下按"新建上游连接数"计数，满 35 自动换 IP（实测 60 发零限流留余量）→ **记 rotate_history（reason=auto_rotate_35conn，铁律一）** |
| supervisor 自愈 | relay 作为控制台进程内独立 asyncio task，崩溃由 supervisor 自动重拉监听（2 秒级），不拖垮控制台主进程（MCP/前端/其他路由零影响） |

### 4.3 控制接口 `routes/proxy.py`（仅 127.0.0.1）

**调用方**：proxy MCP（对话流）、agent 脚本经 MCP 间接、控制台前端（未来可选）。

| 方法 | 路径 | 请求 | 响应 | 语义 |
|------|------|------|------|------|
| GET | `/api/proxy/status` | - | `{mode, current, expire_in_sec, bad_count, domain_limited, surplus, total_fetched, rotate_history[], relay_port}` | 全量状态；**history 是判定 SOP 第一步（铁律一）**。凭证未配置时正常返回（mode=direct，current=null，附配置指引字段） |
| POST | `/api/proxy/rotate` | `{"reason": "agent_rotate"\|"bad_ip"}`（可选，默认 agent_rotate） | `{current, expire_in_sec, surplus}` | 换出口。**reason=bad_ip 时旧 IP 进黑名单后再提取新 IP**（SOP 场景 C 的烂 IP 淘汰动作）；记 history；内部含优雅关闭。凭证未配置时 422 + 明确指引 |
| POST | `/api/proxy/mode` | `{"mode":"proxy"\|"direct"}` | `{mode}` | 全局粗开关（校验：mode 必填且枚举，否则 400） |
| POST | `/api/proxy/domain_limited` | `{"url": "https://X.com/p?a=1", "minutes": 10}` | `{ok, domain}` | 登记域名冷却。**url 必传（缺失 400；无法提取 host 时 400）；经归一化提取域名后入表（§5.1）** |
| GET | `/api/proxy/entry` | - | `{"proxy": "http://127.0.0.1:<真实端口>"}` | 取入口。**端口读状态文件（端口冲突顺延后的真实值，勿在消费端硬编码）**；返回前确保池内有可用 IP（必要时惰性提取；direct 模式下也可能因域名冷却需要 IP） |

### 4.4 proxy MCP `mcp-servers/proxy/server.py`（薄壳，照抄 ocr 模式）

FastMCP + httpx 转发控制接口 + control_url 端口发现 + 失败自愈。4 个工具，**工具描述是 agent 判定的现场引导（每轮注入）**：

| 工具 | 返回 | 描述要点（写进工具 description） |
|------|------|------|
| `proxy_status` | 全量状态含 history | "查询代理状态与 rotate_history。**看到任何限流迹象（429/挑战页/脚本 LIMITED 输出）时的第一个动作**：查 history 判定场景——近期(<1min)有轮换=预期挑战不换；无轮换且任务稳定运行中=真限流调 rotate；轮换过且等>30s 仍挑战=烂 IP 调 rotate(reason=bad_ip)。写批量脚本前先查余量" |
| `proxy_rotate` | 新出口信息 | "换出口。可选 reason：agent_rotate（默认）/ bad_ip（**SOP 场景 C 烂 IP 淘汰时必须传 bad_ip**，旧 IP 进黑名单防再取回）。经判定 SOP 确认真限流/烂 IP 后调用" |
| `proxy_mode` | 模式确认 | "direct↔proxy 全局切换（校验枚举）。大轰炸任务（爆破/fuzz）开始前切 proxy 省撞墙学费，结束切回 direct" |
| `proxy_get_entry` | 入口地址（真实端口） | "取代理入口（**端口可能因冲突顺延，永远以此接口返回值为准，勿硬编码**）。requests 脚本填 proxies / Playwright 填 launch.proxy" |

### 4.5 消费端三形态（agent 写代码的实际形态）

```python
# ① requests 批量脚本（显式一行, 其余裸写; 限流只报告不行动）
# entry 从 MCP proxy_get_entry 获取（勿硬编码端口, 冲突时会顺延）
proxies = {"http": entry, "https": entry}
for pwd in candidates:
    r = requests.post(url, data={"password": pwd}, proxies=proxies, timeout=20)
    if r.status_code == 429:
        print(f"[LIMITED] 429 at #{i}"); fails.append(pwd)   # 报告给 agent
        if len(fails) >= 3: break
    elif r.status_code == 302: print("FOUND", pwd); break

# ② Playwright（有头/无头同; 出生即连, 全程不换地址; entry 同上经 MCP 获取）
browser = p.chromium.launch(proxy={"server": entry})
# 切出口 = agent 调 MCP mode/rotate, 浏览器零重启零重建(§5.3)

# ③ 无代理低频脚本（铁律二: 不用则完全不依赖）
requests.get(url, timeout=15)    # 本机直连, relay 存在与否无影响
```

---

## 5. 关键机制

### 5.1 域名归一化（收口于 pool，relay 与控制接口共用同一函数）

**背景**：域名冷却表的键必须一致，否则同一站点的不同写法会分裂成多个表项，冷却失效。输入来自两处——控制接口的 `url` 参数（agent/前端传入，形态五花八门）与 relay 的 CONNECT 目标 host。**归一化是唯一实现、唯一入口**。

**规则（实现为 `normalize_domain(raw) -> str`，校验失败抛 400）**：

| 输入形态 | 处理 | 输出 |
|---------|------|------|
| `"https://Target.COM/path?x=1#frag"` | scheme/路径/参数/锚点全部丢弃；host 小写 | `target.com` |
| `"HTTP://target.com:8443/a"` | 端口剥离 | `target.com` |
| `"http://user:pass@target.com/x"` | userinfo 剥离 | `target.com` |
| `"ws://target.com"` / `"wss://…"` | 任意 scheme 均可，只取 host | `target.com` |
| `"target.com"` / `"target.com:443"`（无 scheme） | 补 `//` 前缀再解析 | `target.com` |
| `"target.com."`（末尾点） | 剥离 trailing dot | `target.com` |
| `"目标站.com"`（非 ASCII/IDN） | 转 punycode（`idna` 编码） | `xn--…com` |
| `""` / 缺失 / `"not a url"` / 纯路径 `"/a/b"` | **400 拒绝（url 必传且必须能提取出 host）** | - |
| `"127.0.0.1:9776"` / `"localhost"` | IP/localhost 原样保留（作为 host 合法；relay 的本地豁免判定在此之后做） | `127.0.0.1` / `localhost` |

实现要点：`urllib.parse.urlsplit`（无 scheme 先补 `//`）→ 取 `.hostname`（自动 lower、剥 userinfo 与端口）→ 去 trailing dot → 非 ASCII 转 IDNA → 合法性校验（非空、host 字符集）。全部进单元测试逐行覆盖上表。

### 5.2 判定 SOP（agent 三场景，物化在 `proxy_status` 工具描述内）

```
看到限流迹象（脚本 [LIMITED] 输出 / 浏览器挑战页 / 页面异常）
  ↓ 第一步: 调 proxy_status 查 rotate_history
  ├─ 场景A: history 显示 <1min 前有轮换, 或我自己刚调过 rotate
  │         → 换出口后的预期挑战, 浏览器正自动过(~5s) → 等待/刷新, 不换
  ├─ 场景B: 无近期轮换, 我也没换过, 任务稳定运行中突发
  │         → 真限流 → 调 proxy_rotate + domain_limited(该域冷却)
  └─ 场景C: history 显示刚轮换过 + 已等待 >30s 仍挑战
            → 该供应商代理IP 信誉差(CF 无限挑战) → 调 proxy_rotate(reason=bad_ip)
              （旧 IP 进黑名单防再取回）换下一个
```

**为什么不写成 watchdog/evaluator 状态机**：无上下文的机械判定需要"观察窗"猜测挑战是否推进；且任何脚本内自动换 IP 都会在 agent 时间线上打洞（自动换了 → 预期挑战 → agent 不知情 → 误判真限流 → 连环换 IP 烧配额）。agent 天然有完整时间线（动作记忆 + history 查询），三场景判定对它是平凡的。

### 5.3 浏览器零重启切换出口（完整时序）

```
T0  launch(proxy={"server": entry})   ← 出生即连固定入口(entry 经 proxy_get_entry
    获取, 勿硬编码端口)                relay 处于 direct 模式 → 流量实际走本地 IP
                                      （行为与直连一致, 多走本机回环一跳）
T1  浏览中有请求返回 429 → 信号出现在脚本输出/页面 → agent 看到
T2  agent 调 proxy_status（SOP 第一步）→ 判定场景B
T3  agent 调 proxy_mode("proxy") + domain_limited(url)
T4  relay: 切代理出口 + 该域名冷却 + 存量连接优雅关闭(FIN+读尽)
T5  浏览器看到连接正常收尾 → 下一请求开新连接(日常行为) → 走代理出口
    【浏览器进程零重启 / context 零重建 / DOM/表单/cookies 全保留】
    (唯一例外: cf_clearance 若绑过本地 IP 失效重过挑战 = 服务端行为)
```

反向（proxy→direct）与轮换 IP（35 阈值/agent rotate）同时序。**前提不可妥协**：若浏览器 launch 时未连 relay（真直连），运行中不可改代理参数，切出口只剩重启浏览器一条路——所以出生即连是策略，不是可选项。

### 5.4 换出口瞬间的请求连续性

| 客户端 | 表现 |
|--------|------|
| 在飞响应 | **优雅关闭（FIN+读尽）完整送达，请求不失败**；仅超 5s 宽限的超长响应强关，由重试兜底（安全分析场景 KB 级响应基本不触发） |
| 浏览器 | 连接正常收尾 → 新连接走新出口。GET 原生自动重试；POST 不自动重试（防重复提交），依赖优雅关闭送达（响应已到手则无需重试） |
| requests | 默认不重试（抛 ConnectionError）；知识库模板配 `Retry(total=2, status_forcelist=[429,503], backoff_factor=0.5)` 后自愈 |

### 5.5 架构无法解决的部分（诚实边界）

- **服务端票据绑定**：换出口后 `cf_clearance`/绑 IP 的 session 失效，重过挑战/重登录是服务端防御行为，理论最小代价即此；
- **协议本质**：TCP 四元组含出口 IP，在飞字节流无法迁移连接——优雅关闭已把损失压到"超长响应+超 5s"的边角。

---

## 6. 三场景端到端走查

### 6.1 requests 爆破（如 OoC 后续任务）

```
1. agent 调 proxy_status → 余量/模式确认; 调 proxy_mode("proxy")
2. 写脚本: proxies=entry 一行 + 裸 requests + [LIMITED] 报告逻辑 + Retry 模板
3. 脚本跑: 流量经 relay 走代理出口; relay 按 35 连接自动轮换(history 可查)
4. 中途 429: 脚本报告并提前 break → agent 读输出 → SOP 判定
   → rotate + domain_limited → 续跑(入口不变, 脚本无需改)
5. 结束: agent 调 proxy_mode("direct") + status 复盘消耗
```

### 6.2 Playwright 有头浏览器分析（CF 站）

```
见 §5.3 时序。全程 agent 感知(脚本输出/页面状态在 agent 上下文内),
全程 agent 操控(MCP), 无时间线黑洞。
```

### 6.3 对话流内

```
agent 写脚本前: proxy_status 查余量/模式 → 决定脚本形态(代理/直连)
agent 看到限流: proxy_status 查 history → 三场景判定 → mode/rotate 行动
```

---

## 7. AI 执行保障（引导物三层 + 信息完整性设计）

| 层 | 内容 | 文件 |
|----|------|------|
| MCP 工具描述（每轮注入，最强引导） | 4 工具的调用时机 + `proxy_status` 内嵌判定 SOP | `mcp-servers/proxy/server.py` |
| agent prompt（~10 行） | 触发条件：批量任务先拿 entry；浏览器出生即连 entry；限流信号清单；**SOP 第一步=查 history** | `agents/web-analysis.md` |
| 知识库（按需 Read） | 代码模板：entry 用法/[LIMITED] 报告段/Retry 装配/限流特征清单 | `web-analysis/knowledge-base/proxy-usage.md` |

信息完整性不依赖引导物——它是**结构保证**：换出口的唯一自动路径（35 阈值轮换）强制写 history，其余全部 agent 发起；脚本无任何自动行动代码。

反向约束（防误用）：低频探测不接代理（铁律二）；任务结束切回 direct（省花销）。

---

## 8. 实施拆分（每步 ≤200 行、独立验证点）

| # | 内容 | 文件 | 行数 | 验证点 |
|---|------|------|------|--------|
| 1 | pool + 归一化 | `services/proxy_pool.py` | ~200 | 单测：签名自测（官方示例值）；**归一化全表逐行**（§5.1 表格 10 形态含拒绝分支）；mock 供应商 API 测缓存/过期/黑名单/冷却/history/持久化往返；**凭证缺失：status 正常+rotate 422** |
| 2 | 控制接口 | `routes/proxy.py` + server.py 注册 | ~100 | curl 五接口：**url 缺失 400、无法提取 host 400、归一化后域名入表**；mode 枚举校验；rotate reason 枚举校验（bad_ip 触发黑名单）；status 含 history；entry 返回状态文件真实端口 |
| 3a | relay 基础转发 | `services/proxy_relay.py` + server.py 启动行 | ~120 | `curl -x http://127.0.0.1:<port> https://目标站`（HTTPS/CONNECT）通；明文 HTTP 转发通；出口选择（域名冷却命中走 proxy / 未命中按 mode）；**池内无 IP 时惰性提取**（direct 模式+冷却域场景） |
| 3b | relay 优雅关闭+轮换+自愈 | `services/proxy_relay.py`（续） | ~100 | **优雅关闭**：mock 慢响应服务（分块发送 sleep 1s）+ 切换出口 + 断言客户端完整接收全部字节；35 阈值轮换写入 history（打满 35 连接断言）；**supervisor：task 内抛异常后 2s 级重拉监听** |
| 4 | MCP 薄壳 | `mcp-servers/proxy/server.py` + mcp-manager 注册 | ~90 | opencode 内调 proxy_status 返回真实状态含 history；proxy_rotate reason 参数透传；控制台重启 MCP 自愈 |
| 5 | agent 引导物 | web-analysis.md +10 行；proxy-usage.md | ~120 | prompt 展开 <450 行；知识库自包含（entry 经 MCP 获取/勿硬编码）；工具描述含 SOP 与 reason=bad_ip |
| 6 | 端到端验收 | - | - | 场景 6.1/6.2/6.3 全走查；重放 OoC 登录（60 发零限流）；**SOP 人工演练（对话流走查，非代码断言）：人为触发 429 → history 判定 → rotate → 预期挑战不误换**；供应商消耗审计（total_fetched 单调递增 + surplus 对应递减，与 history 事件可交叉核对） |

依赖：1 → 2 → 3a → 3b → 4 → 5 → 6。

---

## 9. 开放问题（实施前拍板）

> **实现规范补充（实施期违规教训）**：配置数据流唯一且单向——**用户 → 控制台配置页（前端）→ `/api/config/*`（前端专用接口）→ config_store → `.ai_env`**。agent/脚本/MCP 在配置链路上**没有任何角色**：不 Shell 直写文件、不 import config_store、不调用 `/api/config/*`（该接口仅前端使用）。agent 的职责边界 = 实现消费侧代码（pool 经 config_store 读）+ 引导用户到配置页填写。误建配置文件时，修复 = **rm 恢复污染前物理状态**（让 ensure_template 回归正轨），而非接口级清除。

| # | 问题 | 建议 |
|---|------|------|
| 1 | relay 端口起点 9676 | 已定（9776−100 反顺延方向）；可配置，冲突顺延+状态文件记录 |
| 2 | 域名冷却时长 10 分钟 | OoC 实测量级；可配置 |
| 3 | 35 连接阈值 | 实测 60 发零限流留余量；可配置 |
| 4 | 控制台前端 IP 池页面 | 本期不做（API 就绪随时可加） |
| 5 | v1 单通道（并行脚本共享出口模式） | 当前任务全串行，够用；并行需求出现再设计 |

---

## 附录 A：实测数据来源

| 数据 | 验证脚本 | 结论 |
|------|---------|------|
| 签名算法（官方示例 MD5 对照） | `juliang_verify.py` | PASS |
| 代理可用性/HTTPS(CONNECT)/目标站连通 | `juliang_verify.py` | 首提即通 |
| 60 发零限流、10 并发、P50=2.36s、限流按 IP 历史累计 | `juliang_fulltest.py` | 35 阈值依据 |
| 域名矩阵：国内 12/12，国外可达站零失败（失败均为被墙站） | `juliang_domains.py` | 出口为国内 IP |
| CTF 生态：ctftime 17/17 + 真实比赛站 14/14（偶发失败换 IP 即恢复） | `juliang_ctf_real.py` | CTF 场景可用 |
