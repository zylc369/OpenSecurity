# 分析-SiteCheck

**题目：**
```
Welcome to SiteCheck, the SkyCity fleet's favorite web-diagnostics service since 2062!

Enlist for a free inspector account and put any website through its paces: our autonomous inspection drone flies out to the address you provide, clocks how long the page takes to load, tallies how many files it pulls down, and beams back a crisp viewport snapshot — all without you lifting a finger.

Kick the tires on the future of web monitoring.

The drone politely refuses to inspect internal or local addresses. Safety first!

https://spaceship.web.2026.sunshinectf.games
```

## 解题结果

**FLAG:**
```
sun{fr4gm3nt3d_r3fl3ct10ns_1n_th3_futur3}
```

## 解法（赛后复现，环境仍存活）

**核心链：IPv6 环回字面量绕过过滤器 → 无人机自带高权限会话 → 锚点把 flag 拉进视口快照**

1. 注册任意账号，进入 `/dashboard`，表单只接受一个 `url`。
2. 服务端 Bot（"inspection drone"）用无头浏览器访问提交的 URL 并回传**视口截图**（800px 折叠线）。其浏览器**自带 admin 会话**（档案显示 `Inspector: admin — Chief Inspection Drone - Clearance OMEGA`），该会话 cookie 绑定 `[::1]:3000`。
3. 过滤器只拦字面量 `127.x / 0.0.0.0 / localhost`（小写精确匹配），放行 IPv6 环回 `[::1]`。
4. flag 在档案 CLASSIFIED「Clearance Data」区，被 `.spacer` 推到视口折叠线下（作者 CSS 注释："Spacers push the classified section well below the 800px snapshot fold"）。用 URL 片段锚点 `#clearance` 让浏览器跳转到该区即可进入快照。

**EXP：**
```
注册 -> POST /scan   url=http://[::1]:3000/profile#clearance
-> GET /screenshots/<uuid>.png -> 得到 flag
```

**对照（为什么必须是 `[::1]`）：**
- `http://[::1]:3000/profile` → 无人机渲染 admin 档案（OMEGA）✅
- `http://localhost.:3000/profile`、`http://web:3000/profile` → 登录页（cookie 不匹配该主机形态）❌
- `http://127.0.0.1:3000/profile` → 被过滤器拦截 ❌

**弯路记录（避免误入）：** 通过 SSRF 读到的内网 ChromaDB（`VecNetDB` 集合，`user_password_requirements`/`user_hash_sha256`/`magic_string`，vec2text 反演得 `GR$*#sunshinectf8_`）属于兄弟题 **VecNet** 的基础设施，与本题无关——本题不需要任何密码。