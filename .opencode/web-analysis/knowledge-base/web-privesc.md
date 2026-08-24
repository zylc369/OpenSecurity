# Web 应用层权限提升

> Web 提权不需要 exploit——找应用逻辑中的权限检查漏洞。注册后立即检查普通用户能否越权访问管理员功能（第一优先级）。
> 加载时机: 应用有注册/登录、角色权限管理、API 参数传输用户身份信息。

## §1 Mass Assignment（批量赋值）

注册/更新请求中**添加应用未预期的权限字段**（服务端把请求字段直接绑到模型）。**每次只加一个字段**（全改可能触发 WAF）。

```json
{"role":"admin"} {"is_admin":true} {"is_staff":1} {"admin":1}
{"group":"administrators"} {"permissions":["admin"]} {"type":"admin"}
{"privilege":"high"} {"level":9} {"is_superuser":true}
```
非权限但有价值: `{"balance":999999}` `{"verified":true}` `{"email_confirmed":true}` `{"credits":99999}`

**框架惯例**: Django `is_staff`/`is_superuser`/`groups`｜Rails `admin`/`role`｜Laravel `is_admin`/`role_id`｜Spring `authorities`/`roles`

**字段发现四法**: ①`GET /api/users/me` 响应暴露的字段 ②Swagger/OpenAPI（`/docs` `/swagger` `/openapi.json`）③发无效值触发枚举错误（`"role" must be one of: user, admin`）④框架惯例猜测。

验证纪律: 改完查 `GET /api/users/me` 确认权限真的变。数字型角色参数改值: `type=0` 查看者 / `1` 编辑者 / `2` 管理员。结合 IDOR + Mass Assignment 效果更好。

## §2 管理端点访问与方法/Header/Cookie 篡改

**端点变体**（403 时逐个试）: `/admin` → `/admin/`（尾斜杠）→ `/Admin`（大小写）→ `/dashboard` → `/api/admin/users`。前端守卫常只匹配精确路径，后端路由表可能注册多种变体。

**方法切换**: `GET /admin/flag` 403 → POST/PUT/PATCH 同路径。

**Header 篡改**（绕反代路径限制）: `X-Original-URL: /admin/flag`｜`X-Rewrite-URL`｜`X-Forwarded-For: 127.0.0.1`｜`X-Custom-IP-Authorization: 127.0.0.1` —— 完整矩阵见 `$AGENT_DIR/knowledge-base/host-header-attacks.md`（覆盖头/绝对 URI/双 Host 等）。

**Cookie 篡改**:
- 明文: `role=user`→`role=admin`、`admin=0`→`admin=1`
- Base64: `b64decode` 解 JSON → 改 `role` → 重编码
- Flask session: 签名 JSON **不加密**——拿 `secret_key` 即可伪造任意 session（flask-unsign 解/签）
- JWT 见 `$AGENT_DIR/knowledge-base/web-vulnerabilities.md` §2.2

**默认凭据**（最快路径）: `admin:admin` / `admin:password` / `admin:123456` / `root:root` / `root:toor` / `test:test` / `guest:guest`

**自动化检测**: Burp Autorize 插件——配置低权限 Cookie 自动重放全部请求，三份响应（原始/低权限/无 Cookie）并排比对筛越权端点。自定义鉴权头 `X-Admin: true` 直接注入。Intruder 遍历资源 ID + Comparer 比对两账号响应。高危场景: 文件下载参数/订单查询/配置修改接口。

## §3 SPA 前端鉴权绕过

**后台"一闪而过"**: 页面瞬间加载管理界面又被 JS 路由守卫重定向 → 管理代码已全部加载:
1. 代理拦截 302/301 响应包，不让浏览器跳转
2. 等管理后台 JS 加载完
3. 从 JS 提取全部管理接口（urlfind 等工具）
4. 直接对这些 API 测未授权访问（后端可能完全没有鉴权）

**响应篡改**（登录/权限检查在前端时）: `{"success":false,"code":401}` → 篡改为 `{"success":true,"code":200,"data":true}`。
**判定条件**: 响应不含 JWT/Token/Session 等后端凭据 = 鉴权完全在前端 = 篡改有效。
进入"虚假"界面后重点: ①提取新加载 JS 中的管理 API ②测未授权 ③看隐藏功能入口。

## §4 邀请接口提权（双账户自测法）

团队/组织功能场景:
```
1. 管理员 B 生成查看者邀请: POST /api/team/invite {"role":"viewer","teamId":"xxx"}
2. 观察 B 的请求格式（找更高角色链接的接口）
3. 普通用户 A 调同一接口改 role: {"role":"editor","teamId":"xxx"} —— 自己生成编辑者链接
4. A 点击自己的链接 → 提升为 editor/admin
```
关键: A/B 都是自己的测试账户——用 A 调 B 才有权限的接口（越权调用+参数篡改组合）。

## §5 关联文件

- `$AGENT_DIR/knowledge-base/web-vulnerabilities.md` — §5 逻辑类（IDOR/条件竞争）
- `$AGENT_DIR/knowledge-base/host-header-attacks.md` — Header 篡改完整矩阵
- `$AGENT_DIR/knowledge-base/spa-frontend-analysis.md` — SPA 前端分析方法论
