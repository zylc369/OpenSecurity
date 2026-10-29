# 认证与访问控制攻击专题

> 认证实现缺陷、OTP/MAC 弱构造、访问控制绕过（代理解码差异/方法绕过/指纹校验）、认证基础设施后攻击。
> JWT/JWE token 攻击见 `$AGENT_DIR/knowledge-base/jwt-attacks.md`；OAuth redirect_uri 与 token 窃取见 web-vulnerabilities.md §7；前端鉴权绕过见 web-privesc.md §3。

---

## §1 认证校验实现缺陷（源码审计模式）

| 模式 | 特征 | 检测 |
|------|------|------|
| 恒真哈希检查 | `if sha256(password).hexdigest():` —— 非空字符串恒真，忘记与 expected 比对 | 哈希函数出现在布尔上下文且无 `==` 比较 |
| 弱签名前缀校验 | `sig.toLowerCase().startsWith(expected.slice(0, 2))` —— 只比对前 2 hex 字符（256 种） | 哈希/签名值上的 `.slice()`/`.substring()`/`.startsWith()` |
| Java hashCode 比较 | `password.hashCode() == storedHash` —— 31 基多项式+32 位溢出碰撞稠密（"Aa"=="BB"、"ParDJon"=="Pas$ion"），爆破短串即过 | `.hashCode()` 出现在 `==` 比较或认证逻辑 |

## §2 密码推断与 OTP 弱构造

**结构化标识符密码推断**: 注册用身份证/学号做密码 + profile 泄露公开字段（生日/性别/地区）→ 按标识符格式（埃及身份证 = 世纪位+YYMMDD+省代码+5 序号）推导，已知字段把爆破空间压到 ~5 万以内。

**仿射密码 OTP**: OTP = (char·mult+add)%26 变换用户名 → mult 与 26 互素仅 12 值 × add 26 值 = 312 全量爆破。识别: OTP 与用户名等长、流量暴露 mult/add、无速率限制。通用规则——小字母表+模运算约束参数的自定义密码，先精确算密钥空间再全爆。

**TOTP srand(time()) 种子恢复**: secret 由 `srand(time())` 生成时，注册时间缩到分钟即知 → 60 个种子，ctypes 复现 libc.srand(seed)+rand()%len(charset)（如 "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"×16）重建 secret，pyotp 生成当前码逐试。注册时间线索: 博客/管理面板/用户创建时间戳。

**密码重置验证码流程缺陷五型**: ①空验证码（空值绕过 `if code == expected`）②万能验证码（000000/123456 后门值）③验证码重用（未做一次性标记）④验证码回显（响应含明文，改返回包同理）⑤4-6 位纯数字无频率限制全空间爆破。测试顺序: 空值/万能值 → 重放已用码 → 查响应 → 估熵定爆破。Sequencer 分析随机性。

**验证码 OCR 自动识别**: 项目内 OCR 工具（ocr_extract_text，本地 glm-ocr 多模态模型——扭曲/干扰线/算术型验证码都稳，prompt 可引导如"只输出图中字符，区分大小写"）。脚本流程: 请求验证码端点存图片到 $TASK_DIR → ocr_extract_text 识别 → 带码重放登录请求，循环爆破。简单绕过失败后再上 OCR。
**响应递归提取**: 载荷参数需从上一响应动态取（每请求刷新的 token/验证码字段）——纯脚本实现: 正则/XPath 从上一响应提取变量 → f-string 注入下一请求构造 → 会话保持循环; 密码 md5 后传输场景在脚本内 hashlib.md5(pwd).hexdigest() 内联加密，全程无外部爆破器依赖。

**接收者篡改与 openid 篡改**: ①重置请求同时含目标账号与手机号/邮箱参数——手机号替换为自己的→验证码到己方手机→重置目标账号（服务端不校验绑定关系）②openid 作为客户端可控参数直接篡改登录他人账号（微信/小程序生态）③Access-Reset-Ticket 类重置票据直接置入跳过验证。

## §3 自定义 MAC/签名伪造

**选块线性 MAC**: 结构 `out[i] = hash_block[i] XOR secret[selector] XOR chain` 且 `selector = hash[offset] % N`（哈希在 N 个秘密块中"选择"而非密码学混合）→ 收集若干 (id, sig) 对 → 由签名结构反推各秘密块 → 恢复全部 N 块后对任意 id 伪造。审计规则: 自定义 MAC 必查线性性，selector 型结构几个样本即可完全恢复。

**分隔符序列化注入**: 手写 `{}:{}:{}` 冒号连字段+换行分行存储不转义时，username 填 `fearless:12345:true\ntest` → 存储解析出 admin=true 的记录。对每个用户可控字段测全部结构字节（`: , | \n \r \t`）。

## §4 账号碰撞类接管

**OAuth 邮箱 subaddressing**: provider 不验证邮箱所有权 + RP 用归一化邮箱做账号键 → 注册 `admin+attacker@example.com`，RP 归一化剥 +tag 映射到已有 admin 账号。归一化变体: `+tag`（RFC 5321）/ Gmail 点号折叠 / 大小写折叠。自测: OAuth 注册 `yourtest+x@gmail.com` 登录进 `yourtest@gmail.com` 即中招。防御: provider 验证所有权；RP 用 sub claim 而非邮箱做身份键。

**Unicode 归一化用户名碰撞**: 管道"归一化后查找、分开存原形"→ 注册 `ᴬdmin`（U+1D2C），nodeprep.prepare（RFC 3491）归一化 == "admin" → 查到已有行 → 密码重置接管。审计库: nodeprepare / icu.normalize / unicodedata.normalize / precis。与编码归一化身份混淆同族不同侧（本条是注册查找侧）。
**toUpperCase/toLowerCase Unicode 陷阱**: 黑名单 match(/admin/i) 拦原文 + toUpperCase 存储白名单的组合——注册 `admın`（dotless i U+0131）: 正则 case-fold 不等 ı≡i 过黑名单，`toUpperCase('admın')`='ADMIN' 过白名单。同族 ſ(U+017F)→S、K(U+212A Kelvin)→k; 检测: 遍历 BMP 找大小写映射结果含目标字母的码点。与 NFC 归一化（上条）不同机制（大小写映射 vs 归一化）。

**std::unordered_set 桶碰撞**: 桶索引由摘要截断成 size_t + 查找有探测上限（MAX_LOOKUPS=1000）→ 注册 1100+ 同桶条目使 root 查找在正确比对前放弃 → 任意密码被接受。截断摘要做桶索引暴露第二原像面。

**SRP A=0**: 实现不校验 `A % N != 0` → 发 A=0（或 k·N）→ 服务端 S=0 → 会话键 K=H(0) 已知，无口令通过。群协议公开值必须校验非平凡。

**ArangoDB AQL MERGE**: 输入拼进 FILTER 时注入 `x' || 1 == 1 LET newitem = MERGE(u, {'role':'admin'}) RETURN newitem //` → MERGE 在内存中造出 role 提升的新文档，绕过只查持久存储的 ACL。AQL 必须用 bind variables。

## §5 访问控制绕过（传输层差异）

**HAProxy ACL vs 后端解码差**: HAProxy ACL regex 匹配原始 URL 字节（解码前），Flask/Express 路由先解码 → `acl path_reg ^/+admin` 用 `/%61dmin/flag` 绕过（%61→a）。变体: `/%41dmin`（大写）、`/%2561dmin`（双编码）、段内任意字符 `a%64min`。

**Express %2F 路由不匹配**: Express 路由匹配不解码 %2F（当字面字符）→ `app.all("/api/export/chat")` 中间件不匹配 `/api/export%2Fchat` 整体跳过；前置 nginx 解码后代理给后端正常处理。对受限端点逐段测 %2F。检测: Node 网关+Python 后端+nginx 反代。

**HTTP 方法绕过**: 访问控制常只拦 GET/POST → 403 端点先 OPTIONS 枚举，再测 TRACE/PUT/PATCH/DELETE。`curl -X TRACE` 对 GET 403 端点可能返回内容。

**mod_rewrite 规则顺序 + PATH_INFO**: 放行 `^index\.php$` 的 [L] 规则在拦截规则前时，`/index.php/getflag` 命中放行规则→PHP 收 PATH_INFO='/getflag' 自行路由。对每个受保护路径测 `/已放行脚本/<path>`。

## §6 客户端指纹校验（JA4/JA4H）

服务端校验 UA 哈希+JA4H+JA4 三重指纹时，UA 伪造不够:
- **JA4** = TLS ClientHello 参数哈希（版本/密码套件排序/扩展/签名算法/群组）；不同 TLS 库同 UA 不同 JA4
- **JA4H** = HTTP 头顺序+名称+值哈希；浏览器/curl/requests 头序各异

绕过: JA4H 用 OrderedDict 复刻目标浏览器头序（Host→UA→Accept→Accept-Language→Accept-Encoding→Connection）；JA4 用真实浏览器（老版本进 VM）或 `curl --ciphers <list> --tls-max 1.2`。识别: 报错提 JA3/JA4/TLS fingerprint、curl 与浏览器同头不同响应。工具: ja4 CLI、tshark（≥4.2 内置 JA4 字段 -T fields -e tls.ja4）。Cloudflare/Akamai bot 检测已广泛部署。

## §7 服务端信息泄露与会话伪造

**Apache mod_status /server-status**: 默认启用+Location 配置失误可访问 → 泄露活跃请求 URL（隐藏 admin 端点）/客户端 IP/参数片段/会话 token 模式。攻击链: 发现 → 提取 admin 端点与 IP → 分析 token 模式（可预测如 md5(user+ip+ts) 则 ±10s 窗口伪造）→ 重放。同查 /server-info（mod_info）、/.htaccess。

**公开 admin login cookie 播种**: /admin/login 公开路由无校验直接 Set-Cookie 特权会话 → curl 收割 → 重放 → 带特权 cookie 做 authenticated fuzz（隐藏路由常在 /api 外如 /internal/*）。

## §8 认证基础设施后攻击

**凭据泄露面三处**（拿 foothold 后优先翻）:
1. git 历史: `git log -p --all -S "password"`（pickaxe 搜全部分支 diff 字符串增删）+ first commit + 已删除文件
2. CI/CD 变量: GitLab Settings→CI/CD→Variables（项目 admin 可读）/ GitHub Actions Secrets / Jenkins Credentials。常存 authentik/Vault/AWS 服务账号 token
3. Guacamole: 连接参数（SSH 私钥/密码/passphrase）明文存 MySQL —— API `GET /guacamole/api/session/data/mysql/connections/{id}/parameters?token=` 或 SQL join guacamole_connection(_parameter) 全量提取

**IdP 账号接管**（authentik，Keycloak/Okta 同理）: GET /api/v3/core/users/ 枚举 → POST .../users/{pk}/set_password/ → 查认证流 stage: MFA `not_configured_action: skip` 表示无设备自动跳过 → 新密码直登。

**SAML SSO 自动化**: 捕获 SAMLRequest+RelayState → IdP 认证 → 提交 SAMLResponse+**原 RelayState**。RelayState 全程保持（关联回调与登录请求，不匹配即失败）。

**TeamCity REST RCE**: 建项目→build config→simpleRunner 步骤（script.content=命令）→触发 build→读 build log。build agent 属主（ps aux）决定执行权限。admin 凭据=RCE。

**登录页投毒**: 登录成功分支写 `/dev/shm/creds.txt`（tmpfs 可写+监控盲区）→ 等自动登录（bot/cron/健康检查常带高权限硬编码凭据；audit log 找高频登录用户）。

## §9 关联文件

- `$AGENT_DIR/knowledge-base/jwt-attacks.md` — JWT/JWE token 攻击
- `$AGENT_DIR/knowledge-base/web-privesc.md` — Web 提权（Mass Assignment/端点绕过/邀请提权）
- `$AGENT_DIR/knowledge-base/waf-bypass.md` — WAF 识别（§6 JA4 是客户端被指纹的对抗面）
- `$AGENT_DIR/knowledge-base/web-crypto-attacks.md` — Padding Oracle/bit-flip/弱随机数

### §8.1 基础设施产品 CVE 链
| 产品/CVE | 链 |
|---|---|
| GitLab <17.3.3 ruby-saml（CVE-2024-45409） | XPath 摘要走私: 断言 ID 匹配元数据引用 URI + 正确 digest 放 StatusDetail → 伪造任意用户断言提交 /users/auth/saml/callback |
| PaperCut NG <22.0.9（CVE-2023-27350） | GET /app?service=page/SetupCompleted 未认证 admin 会话 → Config Editor 开脚本/关沙箱 → 打印机设置注 RhinoJS RCE → Squid(3128) 代理横向内网 |
| Zabbix（CVE-2024-22120） | trapper 10051 clientip 时间盲注 → 逐字符提 admin 会话 ID（32 hex 防 \r 伪影）→ API script.create+execute RCE |
| WordPress 插件 RCE 后 | wp-config.php 拿 DB 凭据 → DB FILE 权限 `load_file('/backup/id_rsa')` 读私钥 → SSH 横向。指纹: revslider/release_log.txt 泄版本; 可链模块 wp_revslider_upload_execute 等 |
