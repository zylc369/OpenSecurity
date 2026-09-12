# 平台登录策略 — 浏览器自动化优先

> 需要登录任何 Web 站点/平台才能继续分析时使用。
> 登录是**手段**不是目的——技术绕过成本超过询问用户成本时，必须升级求助。

## 1. 登录决策树

```
登录需求出现
├─ Default: Playwright 自动登录（headless 优先）
│    UI 输入框接受任何用户可输入的值（规避 API 层格式校验/凭证猜测坑），
│    真实浏览器环境下人机验证多数不触发
├─ 升级 1: 人机验证出现且 10s 未自动通过 → headed + 尝试点击验证组件
├─ 升级 2: 交互挑战卡死 / 缺少只有用户知道的凭证
│    → 开有界面浏览器，请用户完成登录/验证，完成后接管同一浏览器继续
└─ 定位: API 逆向服务于登录后的程序化操作（表单提交/批量查询），
     不作为完成登录的手段；禁止为"完成登录"逆向前端超过 5 轮
```

## 2. 执行模式选型

| 模式 | 启动/连接 | 一句话定位 |
|------|-----------|-----------|
| A: Playwright 直接启动 | `launch(channel="chrome", headless=True/False)` | 浏览器是脚本的工具——脚本内闭环（启动→登录→操作→自动关闭） |
| B: 独立进程 + CDP 接管 | `--remote-debugging-port` 启动系统 Chrome + 独立 `--user-data-dir`，`connect_over_cdp` 连接 | 浏览器是独立工作台——跨脚本/跨人共享 |

**选型规则: 能 A 则 A。** A 一行完成启动连接、脚本退出自动清理、Playwright 全功能（拦截/多 context/设备模拟）; B 的"进程独立"要付启动七步/手动清理/CDP 非全功能的复杂度，只在两个场景值得:

- **用户人工介入（升级 2）**: launch 的浏览器是脚本子进程（退出即关闭、pipe 通信不暴露端口），"等用户操作"必须由独立后台进程承载——nohup 后台启动，每步 bash 短命令，用户完成后 `connect_over_cdp` 接管，登录态（cookie/localStorage）直接可用
- **页面/登录态跨脚本存活**: 已打开标签页、JS 运行态只有活进程能保; 磁盘级登录态恢复用模式 A 变体 `launch_persistent_context(固定 user-data-dir)` 即可

`channel="chrome"` 按平台自动定位系统 Chrome（无需手写路径）; 选系统 Chrome 而非自带 Chromium 的原因: 后者缺 Widevine/专有编解码器等组件，指纹易被环境评分识别。
启动/连接代码模板见 `$AGENT_DIR/knowledge-base/browser-debugging.md` §2。
登录完成判定: 轮询 `page.url`——回到目标域且脱离认证路径（`/auth`、`/login` 等）即成功，60s 超时按决策树升级。

启动/连接代码模板见 `$AGENT_DIR/knowledge-base/browser-debugging.md` §2（本文不重复）。
登录完成判定: 轮询 `page.url`——回到目标域且脱离认证路径（`/auth`、`/login` 等）即成功，60s 超时按决策树升级。

## 3. 人机验证: 两类机制勿混淆

| 类型 | 机制 | 应对 |
|------|------|------|
| Cloudflare 环境评分（被动） | 无可见组件，jsd 脚本采集行为/环境 | 真实浏览器（channel="chrome"）+ 正常操作节奏，多数不触发; 触发 → 升级 1 |
| 服务端 CAPTCHA 路由（主动） | 后端在特定端点强制校验验证 token | **不可自动绕过**（siteverify 真实验证）; 换不受保护的路径（如用已有账号登录而非注册），或升级 2 |

- **先查再选路径**: 查平台 CAPTCHA 配置端点（常见 `GET <api>/captcha` 或 `/site/config`，`routes` 字段列出受保护端点）——先知道哪些端点受保护再选路径，而不是撞上再绕
- **升级 1 操作**: 检测 = 遍历 `page.frames` 找 `challenges.cloudflare.com`; 交互组件点击 = `frame.query_selector("input[type=checkbox]").click(timeout=3000)`; 10s 未通过 → 升级 2
- **无头行为结论**: `--headless=new` 下 UA 含 `HeadlessChrome` 但**不构成** Cloudflare 拦截依据。`navigator.webdriver`: 手动启动 + CDP 接管时为 `false`，`launch()` 启动时为 `true`（注入自动化标志; Cloudflare 不单看此值）。被拦时排查 IP 信誉/操作节奏或换 headed，而非归咎 UA

## 4. 硬信号: 出现即停止技术绕过、升级求助

- sitekey 非 Cloudflare 官方测试密钥族——`1x00000000000000000000AA` 总通过 / `2x00000000000000000000AB` 总阻止 / `3x00000000000000000000FF` 总失败，**其余均为生产密钥**（siteverify 真实验证，伪造 token 路线死路）
- 响应含 `CAPTCHA failed validation`（token 已被服务端拒绝，同上死路）
